"""
文献处理器模块
处理OA判断、下载策略选择和下载协调
"""
import logging
from typing import Optional, Dict
from pathlib import Path

from oa_checker import OAChecker
from oa_downloader import OADownloader
from non_oa_downloader import NonOADownloader
from download_recorder import DownloadRecorder
from google_scholar_client import GoogleScholarClient

logger = logging.getLogger(__name__)


class ArticleProcessor:
    """文献处理器，协调OA判断和下载"""
    
    def __init__(
        self,
        oa_checker: OAChecker,
        oa_downloader: OADownloader,
        non_oa_downloader: NonOADownloader,
        recorder: DownloadRecorder,
        google_scholar_client: Optional[GoogleScholarClient] = None,
    ):
        """
        初始化文献处理器
        :param oa_checker: OA判定器
        :param oa_downloader: OA下载器
        :param non_oa_downloader: 非OA下载器
        :param recorder: 下载记录器
        """
        self.oa_checker = oa_checker
        self.oa_downloader = oa_downloader
        self.non_oa_downloader = non_oa_downloader
        self.recorder = recorder
        # Google Scholar API 客户端，用于在 OA 下载失败后根据标题再尝试一次
        self.google_scholar_client = google_scholar_client
    
    def check_oa_status(self, doi: str, article_info: Optional[Dict] = None) -> Dict:
        """
        检查文献的OA状态（详细记录过程）
        :param doi: 文献DOI
        :param article_info: 文献信息（包含pmid, title等）
        :return: OA检查结果字典
        """
        pmid = (article_info or {}).get('pmid') if article_info else None
        title = (article_info or {}).get('title') if article_info else None
        
        logger.info(f"【OA检查】调用OAChecker.check_oa - DOI: {doi}, PMID: {pmid}, Title: {title if title else None}")
        
        # 详细记录OAChecker内部调用的方法
        logger.info(f"【OA检查】OAChecker将按顺序尝试以下方法:")
        logger.info(f"  [1] check_unpaywall - Unpaywall API检查")
        if pmid:
            logger.info(f"  [2] check_pmc - PMC检查 (PMID: {pmid})")
        else:
            logger.info(f"  [2] check_pmc - 跳过 (无PMID)")
        logger.info(f"  [3] check_europe_pmc - Europe PMC检查")
        logger.info(f"  [4] check_crossref - Crossref检查")
        
        oa_check = self.oa_checker.check_oa(doi, pmid=pmid, title=title)
        
        # 记录检查结果
        if oa_check.get('source') is not None:
            logger.info(f"【OA检查】OAChecker返回结果 - 来源: {oa_check.get('source', 'unknown')}, "
                      f"是否OA: {oa_check.get('is_oa', False)}")
        else:
            logger.warning(f"【OA检查】OAChecker返回None，返回非OA结果")
        
        return {
            'is_oa': oa_check.get('is_oa', False) if oa_check else False,
            'oa_info': oa_check,
            'source': oa_check.get('source') if oa_check else None,
            'pdf_url': oa_check.get('url') if oa_check else None
        }
    
    def process_oa_article(
        self,
        doi: str,
        oa_info: Dict,
        article_info: Optional[Dict] = None
    ) -> Optional[str]:
        """
        处理OA文献下载
        :param doi: 文献DOI
        :param oa_info: OA信息
        :param article_info: 文献信息
        :return: 下载的文件路径或None
        """
        logger.info(f"处理OA文献: {doi}")
        
        year = (article_info or {}).get('year')
        title = (article_info or {}).get('title')
        pmid = (article_info or {}).get('pmid')
        
        filepath = self.oa_downloader.download_oa(
            oa_info=oa_info,
            doi=doi,
            year=year,
            title=title,
            pmid=pmid
        )
        
        return filepath
    
    def process_non_oa_article(
        self,
        doi: str,
        article_info: Optional[Dict] = None
    ) -> Optional[str]:
        """
        处理非OA文献下载
        :param doi: 文献DOI
        :param article_info: 文献信息
        :return: 下载的文件路径或None
        """
        logger.info(f"处理非OA文献: {doi}")
        
        year = (article_info or {}).get('year')
        title = (article_info or {}).get('title')
        journal = (article_info or {}).get('journal')
        publisher = (article_info or {}).get('publisher')
        
        filepath = self.non_oa_downloader.download_non_oa(
            doi=doi,
            year=year,
            title=title,
            journal=journal,
            publisher=publisher
        )
        
        return filepath
    
    def extract_source_from_filepath(self, filepath: str) -> str:
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
        
        # 检查是否已下载
        if self.recorder.is_downloaded(doi):
            logger.info(f"DOI {doi} 已下载，跳过")
            normalized_doi = self.recorder._normalize_doi(doi)
            record = self.recorder.downloaded_records.get(normalized_doi)
            if record:
                result['success'] = True
                result['filepath'] = record.get('filepath')
                result['source'] = record.get('source')
                result['year'] = record.get('year') or result.get('year')
            else:
                result['success'] = True
            return result
        
        try:
            # 步骤1: 检查OA状态（详细记录过程）
            logger.info(f"【OA检查】开始检查DOI {doi} 的OA状态...")
            oa_status = self.check_oa_status(doi, article_info)
            result['is_oa'] = oa_status['is_oa']
            
            # 详细记录OA检查结果
            if oa_status.get('oa_info').get('source') is not None:
                oa_info = oa_status['oa_info']
                logger.info(f"【OA检查】检查结果 - 来源: {oa_info.get('source', 'unknown')}, "
                          f"是否OA: {oa_info.get('is_oa', False)}, "
                          f"是否有URL: {bool(oa_info.get('url'))}")
            else:
                logger.info(f"【OA检查】检查结果 - 未找到OA信息，返回非OA结果")
            
            # 步骤2: 根据OA状态选择下载策略
            if oa_status['oa_info'].get('is_oa'):
                # ===== 情况一：文献为 OA =====
                # 先按照既有流程，通过 OA 下载器（包括 undetected-chromedriver）尝试下载
                filepath = self.process_oa_article(doi, oa_status['oa_info'], article_info)
                if filepath:
                    result['success'] = True
                    result['filepath'] = filepath
                    result['source'] = oa_status['oa_info'].get('source')
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

