"""
OA文献链接重定向处理模块
处理 Unpaywall、Crossref、PMC、Europe PMC 等 API 返回的链接重定向
精准定位到最终的 PDF 下载链接

支持两种场景：
1. 静态PDF链接直接暴露 - 使用requests+BeautifulSoup解析HTML提取链接
2. 需要点击Download PDF按钮 - 使用无头浏览器（Selenium）模拟点击
"""
import logging
import requests
from typing import Optional, Dict, List
from urllib.parse import urlparse, urljoin, quote
from bs4 import BeautifulSoup

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


class RedirectHandler:
    """OA链接重定向处理器"""
    
    def __init__(self, timeout: int = 15, max_redirects: int = 10):
        """
        初始化重定向处理器
        :param timeout: 请求超时时间（秒）
        :param max_redirects: 最大重定向次数
        """
        self.timeout = timeout
        self.max_redirects = max_redirects
        self.headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,application/pdf,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
            "Accept-Encoding": "gzip, deflate, br",
            "Connection": "keep-alive",
        }
    
    
    def resolve_redirect(
        self,
        initial_url_or_doi: str,
        source: str = "unknown"
    ) -> Optional[Dict]:
        """
        处理链接重定向，获取链接
        支持直接传入URL或DOI（如果是DOI，会自动构造doi.org URL）
        根据页面类型自动选择静态或动态处理策略
        
        :param initial_url_or_doi: 初始URL或DOI号
        :param source: 来源（unpaywall/crossref/pmc/europe_pmc）
        :return: 最终URL，失败返回None
        """
        if not initial_url_or_doi:
            logger.warning(f"【重定向获取链接-{source}】初始URL或DOI为空")
            return None
        
        # 判断是DOI还是URL
        initial_url = initial_url_or_doi.strip()
        is_doi = False
        
        # 如果以http开头，认为是URL；否则认为是DOI
        if not initial_url.startswith('http'):
            is_doi = True
            # 清理DOI格式
            clean_doi = initial_url
            if '?' in clean_doi:
                clean_doi = clean_doi.split('?')[0]
            # 构造 doi.org URL（使用doi.org而不是dx.doi.org）
            initial_url = f"https://doi.org/{clean_doi}"
            logger.info(f"【重定向处理-{source}】检测到DOI，构造URL: {initial_url}")
        else:
            logger.info(f"【重定向处理-{source}】开始处理重定向: {initial_url}")
        
        try:
            # 准备请求头
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                "Accept": "text/html"  # 明确请求HTML页面，避免返回其他格式
            }
            
            # 关键参数：allow_redirects=True（自动跟踪所有重定向）
            # GET请求 使用requests.get()进行请求
            response = requests.get(
                initial_url,
                headers=headers,
                allow_redirects=True,  # 核心：自动处理重定向
                timeout=self.timeout,
                stream=True  # 仅获取响应头，不下载正文
            )
            
            # 检查HTTP状态码
            status_code = response.status_code
            logger.info(f"【重定向处理-{source}】HTTP状态码: {status_code}")
            
            # 如果状态码不是2xx，进行相应处理
            if status_code >= 400:
                logger.warning(f"【重定向处理-{source}】HTTP状态码异常: {status_code}")
                if status_code == 403:
                    logger.warning(f"【重定向处理-{source}】403 Forbidden - 可能被服务器拒绝访问")
                    return None
                elif status_code == 404:
                    logger.warning(f"【重定向处理-{source}】404 Not Found - 资源不存在")
                    return None
                elif status_code >= 500:
                    logger.warning(f"【重定向处理-{source}】服务器错误: {status_code}")
                    return None
                else:
                    logger.warning(f"【重定向处理-{source}】客户端错误: {status_code}")
                    return None
            
            # 对于3xx重定向，requests会自动处理，这里只记录
            if 300 <= status_code < 400:
                logger.info(f"【重定向处理-{source}】检测到重定向: {status_code} -> {response.url}")
            
            final_url = response.url  # 重定向后的最终URL
            
            logger.info(f"【重定向获取链接-{source}】重定向完成")
            logger.info(f"【重定向获取链接-{source}】初始URL: {initial_url_or_doi if is_doi else initial_url}")
            logger.info(f"【重定向获取链接-{source}】最终URL: {final_url}")
            
            return {
                "final_url": final_url,
                "initial_url": initial_url,
                "source": source,
                "content_type": response.headers.get("Content-Type", "")
            }
            
        except requests.exceptions.TooManyRedirects:
            logger.error(f"【重定向处理-{source}】重定向次数过多: {initial_url}")
            return None
        except requests.exceptions.Timeout:
            logger.error(f"【重定向处理-{source}】请求超时: {initial_url}")
            return None
        except requests.exceptions.RequestException as e:
            logger.error(f"【重定向处理-{source}】请求错误: {e}")
            return None
        except Exception as e:
            logger.error(f"【重定向处理-{source}】处理失败: {e}")
            return None
    
    
    def get_oa_link(
        self,
        oa_info: Optional[Dict] = None
    ) -> Optional[str]:
        """
        通过 OA检查结果（来自OAChecker），获取 OA 文献的链接
        :param oa_info: OA检查结果（来自OAChecker），如果提供则避免重复API调用
        :return: 最终链接（str）或 None
        """
        # 安全性检查，避免 None 引发属性错误
        if not oa_info:
            logger.warning("【OA重定向处理】未提供 oa_info，无法获取链接")
            return None

        # 优先使用 OA 检查结果中已经给出的 URL
        url = oa_info.get("url")
        if url:
            logger.info(f"【OA重定向处理】使用OA检查结果，直接返回链接: {url}")
            return url

        # 如果没有直接 URL，则尝试通过 DOI 进行重定向
        doi = oa_info.get("doi")
        if doi:
            source = oa_info.get("source", "unknown")
            logger.info(f"【OA重定向处理】通过 doi.org 处理重定向，source={source}")
            redirect_result = self.resolve_redirect(doi, source=source)
            if redirect_result and redirect_result.get("final_url"):
                final_url = redirect_result.get("final_url")
                logger.info(f"【OA重定向处理】重定向处理成功，最终链接: {final_url}")
                return final_url
            else:
                logger.warning("【OA重定向处理】通过 doi.org 重定向处理失败")
                return None

        logger.warning("【OA重定向处理】oa_info 中既没有 url 也没有 doi")
        return None
