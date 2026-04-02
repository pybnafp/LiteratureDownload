"""
文献处理器
处理OA判断、下载策略选择和下载协调
"""
import logging
from typing import Optional, Dict
from pathlib import Path
from urllib.parse import urlparse, urljoin

import requests
from bs4 import BeautifulSoup
from oa_checker import OAChecker
from oa_downloader import OADownloader
from download_recorder import DownloadRecorder
from google_scholar_client import GoogleScholarClient

logger = logging.getLogger(__name__)


class ArticleProcessor:
    """文献处理器，协调OA判断和下载"""
    
    def __init__(
        self,
        oa_checker: OAChecker,
        oa_downloader: OADownloader,
        recorder: DownloadRecorder,
        google_scholar_client: Optional[GoogleScholarClient] = None,
        test_mode: bool = False,
    ):
        """
        初始化文献处理器
        :param oa_checker: OA判定器
        :param oa_downloader: OA下载器
        :param recorder: 下载记录器
        :param google_scholar_client: Google Scholar API 客户端（可选）
        :param test_mode: 测试模式（强制重新下载所有文献，不跳过已下载的）
        """
        self.oa_checker = oa_checker
        self.oa_downloader = oa_downloader
        self.recorder = recorder
        # Google Scholar API 客户端，用于在 OA 下载失败后根据标题再尝试一次
        self.google_scholar_client = google_scholar_client
        self.test_mode = test_mode

    
    def process_article(
        self,
        doi: str,
        article_info: Optional[Dict] = None
    ) -> Dict:
        """
        处理单篇文献的完整流程
        :param doi: 文献DOI
        :param article_info: 文献信息
        :return: 处理结果字典
        """
        result = {
            'doi': doi,
            'success': False,
            'filepath': None,
            'source': None,
            'error': None,
            'is_oa': False,
            'year': (article_info or {}).get('year'),
            'title': (article_info or {}).get('title'),
            'journal': (article_info or {}).get('journal'),
            'author': (article_info or {}).get('author'),
            'pmid': (article_info or {}).get('pmid')
        }
        
        # 检查是否已下载（测试模式下跳过此检查）
        if not self.test_mode and self.recorder.is_downloaded(doi):
            logger.info(f"DOI {doi} 已下载，跳过")
            record = self.recorder.downloaded_records.get(doi)
            if record:
                result['success'] = True
                result['filepath'] = record.get('filepath')
                result['source'] = record.get('source')
                result['year'] = record.get('year') or result.get('year')
            else:
                result['success'] = True
            return result
        
        try:
            # 步骤1: 检查OA状态
            logger.info(f"【OA检查】开始检查DOI {doi} 的OA状态...")
            pmid = article_info.get('pmid', None) if article_info else None
            title = article_info.get('title', None) if article_info else None
            year = article_info.get('year', None)
            oa_check = self.oa_checker.check_oa(doi, pmid=pmid, title=title)
            result['is_oa'] = oa_check['is_oa']

            # 步骤2: 根据OA状态选择下载策略
            if oa_check.get('is_oa'):
                # ===== 情况一：文献为 OA =====
                # 通过 OA 下载器 进行下载
                filepath = self.oa_downloader.download_oa(
                    oa_info=oa_check,
                    doi=doi,
                    year=year,
                    title=title,
                    pmid=pmid
                )
                if filepath:
                    result['success'] = True
                    result['filepath'] = filepath
                    result['source'] = oa_check.get('source')
                else:
                    # OA 下载失败后，严格按需求：使用 Google Scholar API 根据标题再尝试一次
                    title = (article_info or {}).get('title')
                    if self.google_scholar_client and title:
                        logger.info("【OA下载】OA 下载失败，尝试使用 Google Scholar API 根据标题下载")
                        gs_res = self.google_scholar_client.download_by_title(
                            title=title,
                            doi=doi,
                            year=result.get('year'),
                        )
                        if gs_res.get("success") and gs_res.get("filepath"):
                            result['success'] = True
                            result['filepath'] = gs_res['filepath']
                            # 来源标记为 google_scholar，便于统计（也用于区分是 Google Scholar API 下载成功）
                            result['source'] = "google_scholar"
                            result['error'] = None
                            logger.info(
                                f"【Google Scholar】下载成功，来源标记为 google_scholar，"
                                f"DOI={doi}, 文件路径={result['filepath']}"
                            )
                        else:
                            result['error'] = gs_res.get("error") or "OA下载失败且 Google Scholar 下载失败"
                            logger.error(f"【Google Scholar】下载失败: {result['error']}")
                    else:
                        # 无法调用 Google Scholar（缺少 client 或标题），直接标记为失败
                        result['error'] = "OA下载失败，且无法通过 Google Scholar 继续尝试（缺少客户端或标题）"
            else:
                # ===== 情况二：文献为非 OA =====
                # 按需求：判定为非 OA 后，直接标记为下载失败，不再尝试其它下载通道
                result['error'] = "文献为非OA，未进行下载"
            
            # 步骤3: 记录下载结果
            if result['success']:
                self.recorder.mark_downloaded(
                    doi,
                    result['filepath'],
                    source=result['source'],
                    year=result['year'],
                    title=result['title'],
                    journal=result['journal'],
                    author=result['author'],
                    pmid=result['pmid']
                )
                logger.info(f"✓ 文献处理成功: {result['filepath']}")
            else:
                self.recorder.mark_failed(
                    doi,
                    reason=result.get('error', "下载失败"),
                    title=result['title'],
                    journal=result['journal'],
                    author=result['author'],
                    year=result['year'],
                    pmid=result['pmid'],
                    source=result.get('source', 'unknown')
                )
                logger.error(f"✗ 文献处理失败: {result.get('error')}")
        
        except Exception as e:
            result['error'] = str(e)
            logger.error(f"处理DOI {doi} 时出错: {e}")
            self.recorder.mark_failed(
                doi,
                reason=str(e),
                title=result['title'],
                journal=result['journal'],
                author=result['author'],
                year=result['year'],
                pmid=result['pmid']
            )
        
        return result


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
        