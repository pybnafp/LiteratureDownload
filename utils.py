"""
提供一些工具
"""
import logging
import time
from pathlib import Path
import requests
from typing import Optional, Dict, List
from urllib.parse import urlparse, urljoin, quote
from bs4 import BeautifulSoup

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)



# ========== XPath 辅助函数 ==========
def _case_insensitive_xpath(keyword: str) -> str:
    """生成不区分大小写的XPath contains表达式"""
    return f"contains(translate(text(), 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), '{keyword.lower()}')"


def _case_insensitive_button_xpath(keywords: list, require_all: bool = False) -> str:
    """生成带有不区分大小写文本匹配的按钮XPath"""
    from typing import List
    if require_all:
        conditions = " and ".join([_case_insensitive_xpath(kw) for kw in keywords])
    else:
        conditions = " or ".join([_case_insensitive_xpath(kw) for kw in keywords])
    return f"//button[{conditions}]"


def clean_doi(doi: str) -> str:
    """
    清理DOI（移除URL前缀等）
    :param doi: 原始DOI
    :return: 清理后的DOI
    """
    doi = (doi or "").strip()
    if doi.startswith("http"):
        if "doi.org/" in doi:
            doi = doi.split("doi.org/")[-1]
        elif "dx.doi.org/" in doi:
            doi = doi.split("dx.doi.org/")[-1]
        elif "/doi/" in doi:
            doi = doi.split("/doi/")[-1]
    if "?" in doi:
        doi = doi.split("?")[0]
    return doi


def generate_filename(doi: str, year: Optional[str] = None, source: Optional[str] = None) -> str:
    """
    生成安全的文件名
    格式：doi号_年份_来源.pdf
    :param doi: 文献DOI
    :param year: 年份（可选）
    :param source: 来源（可选）
    :return: 文件名
    """
    doi_clean = clean_doi(doi)
    doi_slug = doi_clean.replace('/', '_').replace(':', '_')
    parts = [doi_slug]
    if year:
        parts.append(str(year))
    if source:
        parts.append(source)
    return "_".join(parts) + ".pdf"


def extract_source_from_filepath(filepath: str) -> str:
    """
    从文件路径中提取来源标识
    :param filepath: 文件路径
    :return: 来源标识
    """
    filepath_lower = filepath.lower()
    
    # 预印本 / Sci-Hub / LibGen 等来源标签已移除，这里仅区分 OA 与 non_oa
    if 'oa' in filepath_lower:
        return 'oa'
    elif 'non_oa' in filepath_lower:
        return 'non_oa'
    else:
        return 'unknown'
        

def resolve_redirect(
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
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,application/pdf,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
            "Accept-Encoding": "gzip, deflate, br",
            "Connection": "keep-alive",
        }
        
        # 关键参数：allow_redirects=True（自动跟踪所有重定向）
        # GET请求 使用requests.get()进行请求
        response = requests.get(
            initial_url,
            headers=headers,
            allow_redirects=True,  # 核心：自动处理重定向
            timeout=15,
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