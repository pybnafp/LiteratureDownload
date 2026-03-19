"""
OA（开放获取）文献分类型批量下载模块
根据OA类型（金色OA、绿色OA、预印本OA）采用不同的下载策略
"""
import logging
import time
import re
import shutil
from pathlib import Path
from typing import Optional, Dict
from urllib.parse import urlparse, urljoin

import requests
from bs4 import BeautifulSoup
from pdf_utils import PDFUtils
from redirect_handler import RedirectHandler

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


class OADownloader:
    """OA文献分类型下载器"""
    
    # 需要在 OA 下载失败后整站跳过的出版商域名（主域即可，子域用 endswith 匹配）
    SKIP_OA_HOSTS = [
        "onlinelibrary.wiley.com",          # Wiley，包括 movementdisorders.onlinelibrary.wiley.com
        "linkinghub.elsevier.com",         # Elsevier Linking Hub
        "sciencedirect.com",               # ScienceDirect
        "link.springer.com",               # SpringerLink
        "journals.sagepub.com",            # SAGE Journals
        "karger.com",                      # Karger
    ]
    
    def __init__(
        self,
        save_dir: str = "literature_pdfs/oa",
        email: str = "your_email@example.com",
        timeout: int = 60,
        delay: float = 1.0,
        use_selenium_fallback: bool = False,
        selenium_headless: bool = False
    ):
        """
        初始化OA下载器
        :param save_dir: PDF保存目录
        :param email: 邮箱地址（用于API调用）
        :param timeout: 下载超时时间（秒）
        :param delay: 每次请求之间的延迟（秒），遵守robots.txt规则（≥1秒/次）
        :param use_selenium_fallback: 是否在requests失败时使用Selenium作为备选方案
        :param selenium_headless: Selenium是否使用无头模式
        """
        self.save_dir = Path(save_dir)
        self.save_dir.mkdir(parents=True, exist_ok=True)
        self.email = email
        self.timeout = timeout
        self.delay = delay
        self.use_selenium_fallback = use_selenium_fallback
        self.selenium_headless = selenium_headless
        
        # 重定向处理器
        self.redirect_handler = RedirectHandler(timeout=timeout, max_redirects=10)
        
        # 记录在本次运行中「已确认难以自动下载」的 OA 出版商站点，后续直接跳过以提升整体速度
        self.failed_oa_hosts = set()
    
    @staticmethod
    def _clean_doi(doi: str) -> str:
        """清理DOI（使用共用工具）"""
        return PDFUtils.clean_doi(doi)
    
    def _generate_filename(self, doi: str, year: Optional[str] = None, oa_type: Optional[str] = None) -> str:
        """生成安全的文件名（使用共用工具）"""
        return PDFUtils.generate_filename(doi, year, oa_type)
    
    @classmethod
    def _match_skip_host(cls, url: Optional[str]) -> Optional[str]:
        """
        根据 URL 判断是否属于需要跳过的出版商站点。
        :param url: 待检查的 URL
        :return: 命中的站点标识（按主域名），未命中返回 None
        """
        if not url:
            return None
        try:
            parsed = urlparse(url)
            host = (parsed.netloc or "").lower()
            if not host:
                return None
            for pattern in cls.SKIP_OA_HOSTS:
                pattern = pattern.lower()
                if host == pattern or host.endswith("." + pattern):
                    return pattern
        except Exception:
            return None
        return None
    
    def _download_pdf_direct(self, pdf_url: str, save_path: Path) -> bool:
        """
        直接下载PDF文件（使用共用工具）
        :param pdf_url: PDF URL
        :param save_path: 保存路径
        :return: 是否成功
        """
        return PDFUtils.download_pdf_direct(
            pdf_url,
            save_path,
            timeout=self.timeout,
            delay=self.delay
        )
    
    def _extract_pdf_from_html(
        self,
        html_url: str,
        save_path: Path,
        doi: Optional[str] = None,
        year: Optional[str] = None,
        title: Optional[str] = None
    ) -> Optional[str]:
        """
        从HTML页面提取PDF链接或使用无头浏览器保存为PDF
        :param html_url: HTML页面URL
        :param save_path: 保存路径
        :param doi: 文献DOI（可选，用于Selenium下载）
        :param year: 年份（可选）
        :param title: 标题（可选）
        :return: 提取到的PDF直链URL，失败返回None
        """
        try:
            logger.info(f"从HTML页面提取PDF: {html_url}")
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "en-US,en;q=0.9",
            }
            response = requests.get(html_url, headers=headers, timeout=self.timeout, allow_redirects=True)
            response.raise_for_status()
            
            # 检查是否已经是PDF，如果是则直接返回该URL，由调用方负责下载
            content_type = response.headers.get("Content-Type", "").lower()
            if "pdf" in content_type:
                logger.info("页面响应已是PDF内容，直接返回该URL")
                return html_url
            
            # 解析HTML查找PDF链接
            soup = BeautifulSoup(response.text, 'html.parser')
            
            # 查找PDF下载链接
            pdf_links = []
            # 查找<a>标签中的PDF链接
            for link in soup.find_all('a', href=True):
                href = link.get('href', '')
                text = link.get_text().lower()
                
                # 匹配包含pdf、download、full-text等关键词的链接
                if ('.pdf' in href.lower() or 
                    'pdf' in text or 
                    'download' in text or 
                    'full-text' in text or
                    'fulltext' in text):
                    full_url = urljoin(html_url, href)
                    if full_url not in pdf_links:
                        pdf_links.append(full_url)
            
            # 查找<iframe>标签中的PDF链接
            for iframe in soup.find_all('iframe', src=True):
                src = iframe.get('src', '')
                if '.pdf' in src.lower() or 'pdf' in src.lower():
                    full_url = urljoin(html_url, src)
                    if full_url not in pdf_links:
                        pdf_links.append(full_url)

            if pdf_links:
                # 返回第一个候选PDF链接，由调用方负责下载
                return pdf_links[0]
            
            logger.warning("未在HTML页面中找到PDF链接")
            return None
            
        except Exception as e:
            logger.error(f"从HTML页面提取PDF失败: {e}")
            return None

    
    def _download_with_selenium(
        self,
        url: str,
        doi: Optional[str] = None,
        year: Optional[str] = None,
        title: Optional[str] = None,
        source: str = "oa_selenium"
    ) -> Optional[str]:
        """
        使用Selenium下载器下载PDF（直接使用undetected-chromedriver绕过Cloudflare检测）
        :param url: 页面URL或PDF URL
        :param doi: 文献DOI
        :param year: 年份
        :param title: 标题
        :param source: 来源标识（用于生成文件名）
        :return: 下载的文件路径或None
        """
        try:
            from selenium_pdf_downloader import SeleniumDownloader
            
            # 创建Selenium下载器，直接使用undetected-chromedriver
            selenium_downloader = SeleniumDownloader(
                download_dir=str(self.save_dir),
                timeout=self.timeout,
                headless=self.selenium_headless,
                wait_time=20,
                use_undetected=True,  # 直接使用undetected-chromedriver
                auto_fallback=False  # 不再降级
            )
            
            result = selenium_downloader.download_pdf(
                pdf_url=url,
                doi=doi,
                year=year,
                title=title,
                source=source
            )
            
            selenium_downloader._close_driver()
            
            if result and Path(result).exists():
                return str(result)
            
            return None
            
        except ImportError:
            logger.error("无法导入SeleniumDownloader，请确保已安装selenium库")
            return None
        except Exception as e:
            logger.error(f"Selenium下载失败: {e}")
            return None
    
    
    # 预印本（bioRxiv/medRxiv）专用下载逻辑已移除；OA 下载统一走 RedirectHandler/直接 PDF 下载路径*** End Patch```}  !*** End Patch  CurlException('Unexpected EOF',)  !*** Begin Patch
    
    def download_oa(
        self,
        oa_info: Dict,
        doi: str,
        year: Optional[str] = None,
        title: Optional[str] = None,
        pmid: Optional[str] = None
    ) -> Optional[str]:
        """
        根据OA信息自动选择下载策略
        :param oa_info: OA检查结果（来自OAChecker）
        :param doi: 文献DOI
        :param year: 年份
        :param title: 标题
        :param pmid: PMID（用于PMC下载）
        :return: 下载的文件路径或None
        """
        if not oa_info or not oa_info.get('is_oa'):
            logger.warning(f"文献不是OA: {doi}")
            return None
        
        clean_doi = self._clean_doi(doi)
        pdf_url = oa_info.get('url')
        source = (oa_info.get('source') or '').lower()
        
        # 如果 OA 检查结果中给出的 URL 所属站点，已经在本次运行中多次失败，则直接跳过该文献
        first_host_key = self._match_skip_host(pdf_url)
        if first_host_key and first_host_key in self.failed_oa_hosts:
            logger.warning(
                f"【OA下载】检测到站点 {first_host_key} 之前已多次下载失败，"
                f"当前 DOI {doi} 将直接跳过以提升整体速度"
            )
            return None

        # 统一使用 RedirectHandler 进行链接解析
        final_url: Optional[str] = None

        # 1) 如果 OA 检查结果里已经有 URL，优先使用并尝试直接下载
        if pdf_url:
            logger.info(f"【OA下载】检测到OA检查结果中的URL，尝试直接下载: {pdf_url[:100] if len(pdf_url) > 100 else pdf_url}")
            try:
                filename = self._generate_filename(clean_doi, year, f"{source}_oa" if source else "oa")
                save_path = self.save_dir / filename

                # 跳过已存在的文件
                if save_path.exists():
                    logger.info(f"文件已存在，跳过下载: {filename}")
                    return str(save_path)

                # 直接流式下载
                if self._download_pdf_direct(pdf_url, save_path):
                    logger.info("【OA下载】直接流式下载成功")
                    return str(save_path)
            except Exception as e:
                logger.error(f"【OA下载】直接流式下载失败，将继续尝试重定向策略: {e}")

        # 2) 使用 RedirectHandler.get_oa_link() 根据 oa_info 和 doi 解析最终链接
        try:
            final_url = self.redirect_handler.get_oa_link(oa_info)
        except Exception as e:
            logger.error(f"【OA下载】通过 RedirectHandler.get_oa_link 解析链接失败: {e}")
            final_url = None

        # 3) 如果依然没有得到链接，最后再通过 DOI 做一次通用重定向解析
        if not final_url and doi:
            try:
                logger.info(f"【OA下载】未从 oa_info 获取到URL，尝试使用 DOI 通用重定向: {doi}")
                redirect_result = self.redirect_handler.resolve_redirect(doi, source=source or "unknown")
                if redirect_result and redirect_result.get("final_url"):
                    final_url = redirect_result.get("final_url")
                    logger.info(f"【OA下载】通用重定向解析成功，最终链接: {final_url}")
            except Exception as e:
                logger.error(f"【OA下载】通过通用重定向解析 DOI 失败: {e}")

        # 4) 如果仍然没有任何可用链接，直接返回
        if not final_url:
            logger.warning(f"【OA下载】无法为 DOI {doi} 解析到可用的 OA 链接")
            return None

        # 根据最终 URL 判断是否属于需要跳过/记录的出版商站点
        final_host_key = self._match_skip_host(final_url)

        filename = self._generate_filename(clean_doi, year, f"{source}_oa" if source else "oa")
        save_path = self.save_dir / filename

        # 5) 对于重定向后的URL，首先使用静态PDF提取进行处理
        if final_url:
            # 如果该站点此前已被标记为“难以自动下载”，直接跳过后续静态/动态处理
            if final_host_key and final_host_key in self.failed_oa_hosts:
                logger.warning(
                    f"【OA下载】站点 {final_host_key} 已被标记为自动下载失败站点，"
                    f"当前 DOI {doi} 将直接跳过 OA 下载流程"
                )
                return None

            # 对于重定向后的URL，首先使用静态PDF提取进行处理
            logger.info(f"【OA下载】开始静态PDF提取: {final_url}")
            extracted_pdf_url = self._extract_pdf_from_html(final_url, save_path, clean_doi, year, title)
            # 尝试下载找到的PDF链接
            if extracted_pdf_url:
                try:
                    if self._download_pdf_direct(extracted_pdf_url, save_path):
                        return str(save_path)
                except Exception as e:
                    logger.error(f"【OA下载】静态提取到的PDF直链下载失败: {e}")
            
        # 静态提取失败，使用动态PDF提取（Selenium）
        logger.info(f"【OA下载】静态PDF提取失败，尝试使用Selenium进行动态下载: {final_url}")
        result = self._download_with_selenium(final_url, clean_doi, year, title, source=source)
        if result:
            return str(result)

        # 到这里说明该 DOI 在当前出版商站点上的 OA 自动下载已失败；
        # 若属于配置的“高成本站点”，则在本次运行中将该站点加入跳过列表
        if final_host_key:
            self.failed_oa_hosts.add(final_host_key)
            logger.warning(
                f"【OA下载】站点 {final_host_key} 的 OA 自动下载失败，"
                f"本次运行后续将跳过该站点上的 OA 文献（仅跳过 OA 通道，不影响其它下载层级）"
            )
        return None

