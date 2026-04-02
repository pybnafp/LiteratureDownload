"""
文献下载主程序
整体流程：
1. 使用PubMed搜索器进行检索，批量检索到文献
2. 在处理每一个文献时：
   a. 通过下载记录器判断是否被处理过，若处理过就跳过
   b. 若未处理过，首先判断是否为OA
   c. 若是OA文献，则使用OA下载器处理
   d. 否则使用非OA下载器处理
   e. 在处理过程中，通过下载记录器进行实时记录（更新CSV文件）
"""
import pandas as pd
from pathlib import Path
from typing import Optional, List, Dict
import datetime
from pubmed_search import PubMedSearcher
from download_recorder import DownloadRecorder
from oa_checker import OAChecker
from oa_downloader import OADownloader
from article_processor import ArticleProcessor
from google_scholar_client import GoogleScholarClient
from logging_config import setup_logging
import os
import time
import logging
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)


class LiteratureDownloader:
    """文献下载器主类（新版本）"""
    
    def __init__(
        self,
        email: str = "your_email@example.com",
        api_key: Optional[str] = None,
        google_scholar_api_key: Optional[str] = None,
        pdf_save_dir: str = "literature_pdfs",
        download_delay: float = 1.0,
        timeout: int = 60,
        selenium_headless: bool = True,
        use_llm_for_references: bool = True,
        test_mode: bool = False,
    ):
        """
        初始化文献下载器
        :param email: 你的邮箱（用于PubMed API和Unpaywall API）
        :param api_key: PubMed API密钥（可选）
        :param pdf_save_dir: PDF保存目录
        :param download_delay: 下载延迟（秒）
        :param timeout: 下载超时时间（秒）
        :param selenium_headless: Selenium是否使用无头模式（不显示浏览器窗口）
        :param use_llm_for_references: 是否使用 LLM 解析参考文献 raw_citation（关闭可加快测试）
        :param test_mode: 测试模式（强制重新下载所有文献，不跳过已下载的，用于快速测试）
        """
        # PubMed搜索器（LLM 解析缓存放在 literature_pdfs 下，以 raw_citation/title/pmid/doi 复用结果）
        llm_cache_path = str(Path(pdf_save_dir) / "llm_reference_cache.csv")
        self.pubmed_searcher = PubMedSearcher(
            email=email,
            api_key=api_key,
            use_llm_for_references=use_llm_for_references,
            llm_reference_cache_path=llm_cache_path,
        )
        
        # OA判定器
        self.oa_checker = OAChecker(email=email, timeout=timeout, delay=download_delay)
        
        # OA下载器（用于OA文献的分类型批量下载）
        self.oa_downloader = OADownloader(
            download_dir=str(Path(pdf_save_dir) / "oa"),
            email=email,
            timeout=timeout,
            delay=download_delay,
            selenium_headless=selenium_headless
        )

        # 下载记录器（使用CSV文件替代JSON）
        self.recorder = DownloadRecorder(pdf_save_dir=pdf_save_dir)

        # Google Scholar API 客户端（仅当提供 API Key 时启用）
        if google_scholar_api_key:
            self.google_scholar_client = GoogleScholarClient(
                api_key=google_scholar_api_key,
                save_dir=str(Path(pdf_save_dir) / "google_scholar"),
                timeout=timeout,
                delay=download_delay,
                selenium_headless=selenium_headless,
            )
        else:
            self.google_scholar_client = None
        
        # 文献处理器（协调OA判断和下载）
        self.article_processor = ArticleProcessor(
            oa_checker=self.oa_checker,
            oa_downloader=self.oa_downloader,
            recorder=self.recorder,
            google_scholar_client=self.google_scholar_client,
            test_mode=test_mode,
        )
        
        self.pdf_save_dir = Path(pdf_save_dir)
        self.pdf_save_dir.mkdir(exist_ok=True)
        self.download_delay = download_delay
        self.timeout = timeout
        
        # 初始化时分析已下载记录和失败记录
        self._analyze_existing_records()
    
    def _analyze_existing_records(self):
        """分析已下载记录和失败记录"""
        print("\n" + "=" * 60)
        print("分析已存在的下载记录...")
        print("=" * 60)
        
        stats = self.recorder.get_statistics()
        print(f"已下载记录: {stats['downloaded_count']} 个")
        print(f"失败记录: {stats['failed_count']} 个")
        print(f"总计处理: {stats['total_processed']} 个")
        
        # 统计各来源的下载数量
        source_count = {}
        for record in self.recorder.downloaded_records.values():
            source = record.get('source', 'unknown')
            source_count[source] = source_count.get(source, 0) + 1
        
        if source_count:
            print("\n按下载方式统计:")
            for source, count in sorted(source_count.items()):
                print(f"  {source}: {count} 个")
        
        print("=" * 60 + "\n")
    
    def _update_download_results(self, results: List[Dict]):
        """
        更新 download_results.csv（仅根目录主记录，不再写入子目录）
        :param results: 下载结果列表
        """
        # 1. 更新主记录文件 download_results.csv
        download_results_file = self.pdf_save_dir / "download_results.csv"
        
        # 读取现有记录
        existing_records = []
        if download_results_file.exists():
            try:
                df_existing = pd.read_csv(download_results_file, encoding="utf-8-sig")
                existing_records = df_existing.to_dict('records')
            except Exception as e:
                logger.warning(f"读取 download_results.csv 失败: {e}")
        
        # 创建DOI到记录的映射
        existing_doi_map = {}
        for record in existing_records:
            doi = record.get('doi')
            if doi:
                normalized_doi = self.recorder._normalize_doi(str(doi))
                existing_doi_map[normalized_doi] = record
        
        # 更新或添加新记录
        for result in results:
            if not result.get('success'):
                continue  # 只保存成功下载的记录
            
            normalized_doi = self.recorder._normalize_doi(result['doi'])
            
            # 创建或更新记录
            record = {
                'pmid': result.get('pmid', ''),
                'title': result.get('title', ''),
                'doi': result['doi'],
                'journal': result.get('journal', ''),
                'author': result.get('author', ''),
                'year': result.get('year', ''),
                'success': True,
                'source': result.get('source', ''),
                'filepath': result.get('filepath', '')
            }
            
            existing_doi_map[normalized_doi] = record
        
        # 保存到download_results.csv
        if existing_doi_map:
            df_all = pd.DataFrame(list(existing_doi_map.values()))
            df_all.to_csv(download_results_file, index=False, encoding="utf-8-sig")
            logger.info(f"已更新 download_results.csv，共 {len(existing_doi_map)} 条记录")
        
    
    def search_and_download(
        self,
        query: str,
        max_results: int = 100,
        save_search_results: bool = True
    ):
        """
        搜索并下载文献（新流程）
        :param query: PubMed搜索关键词
        :param max_results: 最大搜索结果数
        :param save_search_results: 是否保存搜索结果到CSV
        """
        print("=" * 60)
        print("开始文献搜索和下载流程（新版本）")
        print("=" * 60)
        
        # 第一步：在PubMed搜索
        print("\n【步骤1】在PubMed搜索文献...")
        articles = self.pubmed_searcher.search(query, max_results=max_results)
        
        if not articles:
            print("未找到任何文献，流程结束")
            return
        
        print(f"共找到 {len(articles)} 篇文献")
        
        
        # 提取DOI列表和对应的文章信息
        doi_article_map = {}
        for article in articles:
            doi = article.get("doi")
            if doi:
                doi_article_map[doi] = article
        
        doi_list = list(doi_article_map.keys())
        print(f"其中 {len(doi_list)} 篇文献有DOI")
        if not doi_list:
            print("没有找到包含DOI的文献，无法下载")
            return
        
        # 第二步：处理每个DOI
        print(f"\n【步骤2】开始处理 {len(doi_list)} 个DOI...")
        print("=" * 60)
        
        # 记录处理前的已下载DOI集合（用于区分原本就存在的文献）
        pre_existing_dois = set(self.recorder.downloaded_dois)
        
        results = []
        for idx, doi in enumerate(doi_list, 1):
            print(f"\n[{idx}/{len(doi_list)}] 处理DOI: {doi}")
            
            # 检查是否已处理过
            if self.recorder.is_downloaded(doi):
                logger.info(f"DOI {doi} 已下载，跳过")
                normalized_doi = self.recorder._normalize_doi(doi)
                record = self.recorder.downloaded_records.get(normalized_doi)
                if record:
                    result = {
                        'doi': doi,
                        'success': True,
                        'filepath': record.get('filepath'),
                        'source': record.get('source'),
                        'year': record.get('year'),
                        'title': record.get('title') or doi_article_map.get(doi, {}).get('title'),
                        'journal': record.get('journal') or doi_article_map.get(doi, {}).get('journal'),
                        'author': record.get('author') or doi_article_map.get(doi, {}).get('author'),
                        'pmid': record.get('pmid') or doi_article_map.get(doi, {}).get('pmid'),
                        'error': None
                    }
                else:
                    result = {
                        'doi': doi,
                        'success': True,
                        'filepath': None,
                        'source': 'unknown',
                        'year': doi_article_map.get(doi, {}).get('year'),
                        'title': doi_article_map.get(doi, {}).get('title'),
                        'journal': doi_article_map.get(doi, {}).get('journal'),
                        'author': doi_article_map.get(doi, {}).get('author'),
                        'pmid': doi_article_map.get(doi, {}).get('pmid'),
                        'error': None
                    }
                results.append(result)
                continue
            
            # 处理单个DOI（使用ArticleProcessor统一处理）
            article_info = doi_article_map.get(doi, {})
            result = self.article_processor.process_article(doi, article_info)
            results.append(result)
            
            # 延迟避免请求过快
            time.sleep(self.download_delay)
        
        
        # 第五步：统计结果
        print("\n" + "=" * 60)
        print("处理完成！统计结果：")
        print("=" * 60)
        
        # 统计本次下载的结果
        # 本次新下载成功的：成功但不在处理前的已下载记录中
        new_success_count = sum(1 for r in results if r['success'] and self.recorder._normalize_doi(r['doi']) not in pre_existing_dois)
        # 本次下载失败的
        new_fail_count = sum(1 for r in results if not r['success'])
        
        print(f"本次下载成功: {new_success_count} 个PDF")
        print(f"本次下载失败: {new_fail_count} 个PDF")
        
        # 从download_results.csv获取所有已下载文献个数
        all_downloaded_count = self._get_all_downloaded_count()
        print(f"所有已下载文献个数: {all_downloaded_count} 个")
        
        print("\n" + "=" * 60)
    
    def _get_all_downloaded_count(self) -> int:
        """从download_results.csv获取所有已下载文献个数"""
        download_results_file = self.pdf_save_dir / "download_results.csv"
        if not download_results_file.exists():
            return 0
        
        try:
            df = pd.read_csv(download_results_file, encoding="utf-8-sig")
            # 统计成功下载的记录
            if 'success' in df.columns:
                return int(df['success'].sum())
            else:
                # 如果没有success列，统计所有记录
                return len(df)
        except Exception as e:
            logger.warning(f"读取 download_results.csv 统计失败: {e}")
            return 0

    def _process_references_for_article(self, article: Dict):
        """
        在主文献处理流程中，额外处理其参考文献：
        - 有DOI的：直接走现有的 ArticleProcessor 流程；
        - 没有DOI但有PMID：通过PubMed补全信息后再处理；
        - 仅有标题：尝试用标题在PubMed中检索以获取DOI，再处理。
        只处理“该主文献的直接参考文献”，不做递归下载。
        """
        refs = article.get("references") or []
        if not refs:
            return

        parent_doi = article.get("doi")
        parent_title = article.get("title")
        parent_pmid = article.get("pmid")

        logger.info(
            f"开始处理主文献参考文献: DOI={parent_doi}, PMID={parent_pmid}, "
            f"Title={parent_title}, 引用数={len(refs)}"
        )

        for idx, ref in enumerate(refs, 1):
            ref_title = ref.get("raw_citation") or ""
            ref_pmid = ref.get("pmid")
            ref_doi = ref.get("doi")

            if not (ref_title or ref_pmid or ref_doi):
                continue

            logger.info(
                f"[参考文献 {idx}/{len(refs)}] "
                f"DOI={ref_doi}, PMID={ref_pmid}, Title={ref_title[:80]}..."
            )

            doi_to_use = None
            article_info = {
                "pmid": ref_pmid,
                "title": ref_title,
                "year": None,
                "journal": None,
                "author": None,
            }

            if ref_doi:
                doi_to_use = ref_doi
            else:
                # 先尝试通过 PMID 在PubMed 中补全
                if ref_pmid:
                    pmid_article = self.pubmed_searcher.fetch_by_pmid(ref_pmid)
                    if pmid_article and pmid_article.get("doi"):
                        doi_to_use = pmid_article["doi"]
                        article_info.update(
                            {
                                "pmid": pmid_article.get("pmid"),
                                "title": pmid_article.get("title") or ref_title,
                                "year": pmid_article.get("year"),
                                "journal": pmid_article.get("journal"),
                                "author": pmid_article.get("author"),
                            }
                        )
                        logger.info(
                            f"参考文献通过PMID补全到DOI: PMID={ref_pmid} -> DOI={doi_to_use}"
                        )

                # 若仍然没有DOI，则尝试用标题在PubMed中检索
                if not doi_to_use and ref_title:
                    title_article = self.pubmed_searcher.find_article_by_title(ref_title)
                    if title_article and title_article.get("doi"):
                        doi_to_use = title_article["doi"]
                        article_info.update(
                            {
                                "pmid": title_article.get("pmid"),
                                "title": title_article.get("title") or ref_title,
                                "year": title_article.get("year"),
                                "journal": title_article.get("journal"),
                                "author": title_article.get("author"),
                            }
                        )
                        logger.info(
                            f"参考文献通过标题在PubMed中补全到DOI: "
                            f"Title='{ref_title[:60]}...' -> DOI={doi_to_use}"
                        )

            if not doi_to_use:
                # 对于非PubMed来源且无法在PubMed补全到DOI的，只记录日志，暂不进入下载管线
                logger.warning(
                    f"参考文献无法获取DOI，跳过自动下载（可能为非PubMed来源或未被收录）: "
                    f"Title='{ref_title[:80]}...'"
                )
                continue

            try:
                self.article_processor.process_article(doi_to_use, article_info)
            except Exception as e:
                logger.error(f"处理参考文献 DOI={doi_to_use} 时出错: {e}")

    def download_from_csv(
        self,
        csv_file: str,
        doi_column: str = "doi"
    ):
        """
        从CSV文件读取DOI并下载
        :param csv_file: CSV文件路径
        :param doi_column: DOI列名
        """
        try:
            df = pd.read_csv(csv_file, encoding="utf-8-sig")
        except FileNotFoundError:
            print(f"CSV文件未找到：{csv_file}")
            return
        except Exception as e:
            print(f"读取CSV文件失败：{e}")
            return
        
        if doi_column not in df.columns:
            print(f"CSV文件中缺少'{doi_column}'字段")
            return
        
        # 提取DOI列表和对应的文章信息
        doi_article_map = {}
        for _, row in df.iterrows():
            doi = row.get(doi_column)
            if pd.notna(doi) and str(doi).strip():
                doi = str(doi).strip()
                doi_article_map[doi] = row.to_dict()
        
        doi_list = list(doi_article_map.keys())
        
        if not doi_list:
            print("未找到有效的DOI")
            return
        
        print(f"从CSV文件读取到 {len(doi_list)} 个DOI，开始处理...")
        
        # 记录处理前的已下载DOI集合
        pre_existing_dois = set(self.recorder.downloaded_dois)
        
        # 处理每个DOI
        results = []
        for idx, doi in enumerate(doi_list, 1):
            print(f"\n[{idx}/{len(doi_list)}] 处理DOI: {doi}")
            
            # 检查是否已处理过
            if self.recorder.is_downloaded(doi):
                logger.info(f"DOI {doi} 已下载，跳过")
                normalized_doi = self.recorder._normalize_doi(doi)
                record = self.recorder.downloaded_records.get(normalized_doi)
                if record:
                    result = {
                        'doi': doi,
                        'success': True,
                        'filepath': record.get('filepath'),
                        'source': record.get('source'),
                        'year': record.get('year'),
                        'title': record.get('title') or doi_article_map.get(doi, {}).get('title'),
                        'journal': record.get('journal') or doi_article_map.get(doi, {}).get('journal'),
                        'author': record.get('author') or doi_article_map.get(doi, {}).get('author'),
                        'pmid': record.get('pmid') or doi_article_map.get(doi, {}).get('pmid'),
                        'error': None
                    }
                else:
                    result = {
                        'doi': doi,
                        'success': True,
                        'filepath': None,
                        'source': 'unknown',
                        'year': doi_article_map.get(doi, {}).get('year'),
                        'title': doi_article_map.get(doi, {}).get('title'),
                        'journal': doi_article_map.get(doi, {}).get('journal'),
                        'author': doi_article_map.get(doi, {}).get('author'),
                        'pmid': doi_article_map.get(doi, {}).get('pmid'),
                        'error': None
                    }
                results.append(result)
                continue
            
            # 处理单个DOI（使用ArticleProcessor统一处理）
            article_info = doi_article_map.get(doi, {})
            result = self.article_processor.process_article(doi, article_info)
            results.append(result)
            
            # 延迟避免请求过快
            time.sleep(self.download_delay)
        
        # 保存结果到CSV文件（更新原文件）
        csv_path = Path(csv_file)
        for result in results:
            doi = result['doi']
            article_info = doi_article_map.get(doi, {})
            # 更新DataFrame中的对应行
            mask = df[doi_column] == doi
            if mask.any():
                df.loc[mask, 'success'] = result['success']
                df.loc[mask, 'source'] = result.get('source', '')
                df.loc[mask, 'filepath'] = result.get('filepath', '')
                df.loc[mask, 'error'] = result.get('error', '')
                if result.get('year'):
                    df.loc[mask, 'year'] = result.get('year')
        
        # 保存更新后的CSV
        df.to_csv(csv_path, index=False, encoding="utf-8-sig")
        print(f"\n结果已更新到: {csv_path}")
        
        # 统计结果
        existing_count = sum(1 for r in results if r['success'] and self.recorder._normalize_doi(r['doi']) in pre_existing_dois)
        new_success_count = sum(1 for r in results if r['success'] and self.recorder._normalize_doi(r['doi']) not in pre_existing_dois)
        new_fail_count = sum(1 for r in results if not r['success'])
        total_success = sum(1 for r in results if r['success'])
        
        print(f"\n处理完成！统计结果：")
        print(f"本次下载成功: {new_success_count} 个PDF")
        print(f"本次下载失败: {new_fail_count} 个PDF")
        print(f"原本已存在: {existing_count} 个PDF")
        print(f"总计成功: {total_success} 个PDF")


if __name__ == "__main__":
    # ========== 日志配置 ==========
    # 所有日志同时输出到控制台和文件（位于项目根目录或当前工作目录）
    setup_logging(log_file="download.log")

    # ========== 配置参数 ==========
    # 敏感信息从 .env 读取（参见 .env.example）
    YOUR_EMAIL = os.getenv("EMAIL", "your_email@example.com")
    API_KEY = os.getenv("PUBMED_API_KEY") or None
    GOOGLE_SCHOLAR_API_KEY = os.getenv("GOOGLE_SCHOLAR_API_KEY") or None
    
    SEARCH_QUERY = "speech language pathology"  # PubMed搜索关键词 speech disorder/speech disorder assessment
    MAX_RESULTS = 50  # 最大搜索结果数
    
    PDF_SAVE_DIR = "literature_pdfs"  # PDF保存目录
    DOWNLOAD_DELAY = 1.0  # 下载延迟（秒）
    TIMEOUT = 60  # 下载超时时间（秒）
    
    # Selenium设置（用于解决反爬虫限制）
    # 默认无头、不弹 Chrome 窗口；本地调试可在 .env 设置 SELENIUM_HEADLESS=false
    _hl = (os.getenv("SELENIUM_HEADLESS", "true") or "true").strip().lower()
    SELENIUM_HEADLESS = _hl not in ("0", "false", "no", "off")
    logger.info(
        "主程序启动：Selenium 无头模式=%s（环境变量 SELENIUM_HEADLESS，默认 true）",
        SELENIUM_HEADLESS,
    )
    
    # 是否使用 LLM 解析参考文献 raw_citation（关闭可加快测试，不依赖通义 API）
    USE_LLM_FOR_REFERENCES = False
    
    # ========== 执行下载 ==========
    downloader = LiteratureDownloader(
        email=YOUR_EMAIL,
        api_key=API_KEY,
        google_scholar_api_key=GOOGLE_SCHOLAR_API_KEY,
        pdf_save_dir=PDF_SAVE_DIR,
        download_delay=DOWNLOAD_DELAY,
        timeout=TIMEOUT,
        selenium_headless=SELENIUM_HEADLESS,
        use_llm_for_references=USE_LLM_FOR_REFERENCES,
    )
    
    # 方式1：通过关键词搜索并下载
    downloader.search_and_download(
        query=SEARCH_QUERY,
        max_results=MAX_RESULTS
    )
    
    # 方式2：从已有CSV文件读取DOI并下载（取消注释以使用）
    # downloader.download_from_csv(
    #     csv_file="literature_pdfs/search_results_speech_disorder.csv",
    #     doi_column="doi"
    # )
