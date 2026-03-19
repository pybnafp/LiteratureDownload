"""
批量下载言语障碍测评和干预相关文献的脚本
基于main.py，支持多个PubMed搜索关键词的批量搜索和下载

设计思路：
- 使用多个搜索关键词组合，覆盖言语障碍的测评和干预主题
- 每个关键词设置合适的最大搜索结果数，总计目标上万篇文献
- 自动去重，避免重复下载相同的DOI
- 支持断点续传，如果中断可以继续执行
"""

import pandas as pd
from pathlib import Path
from typing import List, Dict, Set, Tuple
from collections import deque
import datetime
import logging
import time
from main import LiteratureDownloader
from logging_config import setup_logging

logger = logging.getLogger(__name__)


# ========== PubMed 搜索关键词配置（分层 BFS 用种子关键词） ==========
# 设计目标：
# - 根：Speech Disorder
# - 核心病症：Aphasia, Dysarthria, Autism Spectrum Disorder (ASD), Developmental Language Disorder (DLD)
# - 聚焦维度：诊断 / 评估 / 干预 / 治疗
# - 跨学科扩量：AI / 深度学习 / 工程 / 语音处理
# - 删除：嗓音障碍、听力相关、口吃、失用症等，仅保留指定 4 类
# - 总第一层种子文献数：约 800 篇
#   * 核心关键词：600 篇（12 个，每个 50）
#   * 重要关键词：160 篇（8 个，每个 20）
#   * 次要 / 扩量关键词：40 篇（8 个，每个 5）

SEARCH_QUERIES = [
    # ---------- 核心基础类（Core base）: 600 篇（12×50） ----------
    # 1) 根：speech disorder + 诊断/评估
    {
        "query": "speech disorder AND (diagnosis OR assessment OR evaluation)",
        "max_results": 50,
        "description": "言语障碍 - 诊断/评估（核心）",
    },
    # 2) 根：speech disorder + 干预/治疗
    {
        "query": "speech disorder AND (intervention OR therapy OR treatment OR rehabilitation)",
        "max_results": 50,
        "description": "言语障碍 - 干预/治疗（核心）",
    },
    # 3) Aphasia 诊断/评估
    {
        "query": "aphasia AND (diagnosis OR assessment OR evaluation)",
        "max_results": 50,
        "description": "失语症 - 诊断/评估（核心）",
    },
    # 4) Aphasia 干预/治疗
    {
        "query": "aphasia AND (intervention OR therapy OR treatment OR rehabilitation)",
        "max_results": 50,
        "description": "失语症 - 干预/治疗（核心）",
    },
    # 5) Dysarthria 诊断/评估
    {
        "query": "dysarthria AND (diagnosis OR assessment OR evaluation)",
        "max_results": 50,
        "description": "构音障碍 - 诊断/评估（核心）",
    },
    # 6) Dysarthria 干预/治疗
    {
        "query": "dysarthria AND (intervention OR therapy OR treatment OR rehabilitation)",
        "max_results": 50,
        "description": "构音障碍 - 干预/治疗（核心）",
    },
    # 7) ASD + 言语/语言 + 诊断/评估
    {
        "query": "\"autism spectrum disorder\" AND (speech OR language) AND (assessment OR diagnosis OR evaluation)",
        "max_results": 50,
        "description": "ASD 言语/语言 - 诊断/评估（核心）",
    },
    # 8) ASD + 言语/语言 + 干预/治疗
    {
        "query": "\"autism spectrum disorder\" AND (speech OR language) AND (intervention OR therapy OR treatment)",
        "max_results": 50,
        "description": "ASD 言语/语言 - 干预/治疗（核心）",
    },
    # 9) DLD 诊断/评估
    {
        "query": "\"developmental language disorder\" AND (assessment OR diagnosis OR evaluation)",
        "max_results": 50,
        "description": "DLD - 诊断/评估（核心）",
    },
    # 10) DLD 干预/治疗
    {
        "query": "\"developmental language disorder\" AND (intervention OR therapy OR treatment OR rehabilitation)",
        "max_results": 50,
        "description": "DLD - 干预/治疗（核心）",
    },
    # 11) Speech language pathology - 综合
    {
        "query": "\"speech language pathology\" AND (assessment OR diagnosis OR intervention OR therapy OR treatment)",
        "max_results": 50,
        "description": "言语语言病理学 - 综合诊断/干预（核心）",
    },
    # 12) Communication disorder + speech/language
    {
        "query": "\"communication disorder\" AND (speech OR language) AND (assessment OR therapy OR treatment)",
        "max_results": 50,
        "description": "沟通障碍（言语/语言）- 诊断/治疗（核心）",
    },

    # ---------- 重要类（Important）: 160 篇（8×20） ----------
    # 13) speech disorder + 早期筛查
    {
        "query": "speech disorder AND (screening OR \"early detection\")",
        "max_results": 20,
        "description": "言语障碍 - 筛查/早期发现（重要）",
    },
    # 14) language disorder + 评估
    {
        "query": "language disorder AND (assessment OR evaluation)",
        "max_results": 20,
        "description": "语言障碍 - 评估（重要）",
    },
    # 15) ASD 言语治疗
    {
        "query": "\"autism spectrum disorder\" AND \"speech therapy\"",
        "max_results": 20,
        "description": "ASD - 言语治疗（重要）",
    },
    # 16) Aphasia 言语治疗
    {
        "query": "aphasia AND \"speech therapy\"",
        "max_results": 20,
        "description": "失语症 - 言语治疗（重要）",
    },
    # 17) Dysarthria 言语治疗
    {
        "query": "dysarthria AND \"speech therapy\"",
        "max_results": 20,
        "description": "构音障碍 - 言语治疗（重要）",
    },
    # 18) DLD 言语治疗
    {
        "query": "\"developmental language disorder\" AND \"speech therapy\"",
        "max_results": 20,
        "description": "DLD - 言语治疗（重要）",
    },
    # 19) Speech language pathology 指南
    {
        "query": "\"speech language pathology\" AND (guidelines OR \"best practice\")",
        "max_results": 20,
        "description": "言语语言病理学 - 指南/共识（重要）",
    },
    # 20) Communication disorder 康复
    {
        "query": "\"communication disorder\" AND rehabilitation",
        "max_results": 20,
        "description": "沟通障碍 - 康复（重要）",
    },

    # ---------- 次要 / 跨学科 AI 扩量类（Secondary / AI）: 40 篇（8×5） ----------
    # 21) 统合：speech/language disorder + AI
    {
        "query": "(\"speech disorder\" OR \"language disorder\") AND (\"machine learning\" OR \"deep learning\" OR \"artificial intelligence\")",
        "max_results": 5,
        "description": "言语/语言障碍 × AI/ML（扩量）",
    },
    # 22) ASD 言语/语言 × AI
    {
        "query": "\"autism spectrum disorder\" AND (speech OR language) AND (\"machine learning\" OR \"deep learning\")",
        "max_results": 5,   
        "description": "ASD 言语/语言 × AI（扩量）",
    },
    # 23) Aphasia × NLP/语音识别
    {
        "query": "aphasia AND (\"natural language processing\" OR \"speech recognition\")",
        "max_results": 5,
        "description": "失语症 × NLP/语音识别（扩量）",
    },
    # 24) Dysarthria × 语音信号/声学
    {
        "query": "dysarthria AND (\"acoustic analysis\" OR \"speech signal\" OR \"speech processing\")",
        "max_results": 5,
        "description": "构音障碍 × 声学/语音信号（扩量）",
    },
    # 25) DLD × AI
    {
        "query": "\"developmental language disorder\" AND (\"machine learning\" OR \"deep learning\")",
        "max_results": 5,
        "description": "DLD × AI/ML（扩量）",
    },
    # 26) Speech disorder × 脑影像
    {
        "query": "\"speech disorder\" AND \"brain imaging\"",
        "max_results": 5,
        "description": "言语障碍 × 脑影像（扩量）",
    },
    # 27) Speech disorder × EEG
    {
        "query": "\"speech disorder\" AND EEG AND (speech OR language)",
        "max_results": 5,
        "description": "言语障碍 × EEG（扩量）",
    },
    # 28) Speech disorder × 可穿戴/工程
    {
        "query": "\"speech disorder\" AND wearable AND (speech OR language)",
        "max_results": 5,
        "description": "言语障碍 × 可穿戴/工程（扩量）",
    },
]

# ========== 全局下载目标与分层参数 ==========
# 目标：最终成功下载约 30 万篇相关文献（包括各层参考文献）
# TARGET_TOTAL_PDFS = 300_000
TARGET_TOTAL_PDFS = 300_000

# BFS 分层最大深度（1=原始PubMed结果，2=第一层引用，3=第二层引用）
MAX_BFS_DEPTH = 3

# 经验参数：用于估算初始搜索量是否足够
AVG_REFS_PER_ARTICLE = 10     # 单篇文献平均参考文献数
DOWNLOAD_FAIL_RATE = 0.30     # 下载失败率预估

# 原始配置的总搜索目标（未考虑分层扩展）
TOTAL_TARGET_SEEDS = sum(q["max_results"] for q in SEARCH_QUERIES)
print(f"原始配置的总搜索目标(第一层种子): {TOTAL_TARGET_SEEDS} 篇文献")


class BatchSpeechDisorderDownloader:
    """批量言语障碍文献下载器"""
    
    def __init__(
        self,
        email: str = "your_email@example.com",
        api_key: str = None,
        pdf_save_dir: str = "literature_pdfs",
        download_delay: float = 1.0,
        timeout: int = 60,
        use_selenium_fallback: bool = True,
        selenium_headless: bool = False,
        use_llm_for_references: bool = True,
    ):
        """
        初始化批量下载器
        :param email: 你的邮箱（用于PubMed API和Unpaywall API）
        :param api_key: PubMed API密钥（可选）
        :param pdf_save_dir: PDF保存目录
        :param download_delay: 下载延迟（秒）
        :param timeout: 下载超时时间（秒）
        :param use_selenium_fallback: 是否在requests失败时使用Selenium作为备选方案
        :param selenium_headless: Selenium是否使用无头模式
        :param use_llm_for_references: 是否使用 LLM 解析参考文献（关闭可加快全流程测试）
        """
        self.downloader = LiteratureDownloader(
            email=email,
            api_key=api_key,
            pdf_save_dir=pdf_save_dir,
            download_delay=download_delay,
            timeout=timeout,
            use_selenium_fallback=use_selenium_fallback,
            selenium_headless=selenium_headless,
            use_llm_for_references=use_llm_for_references,
        )
        self.pdf_save_dir = Path(pdf_save_dir)
        self.all_dois: Set[str] = set()  # 用于去重的DOI集合
        # 本次批量运行的日志文件（记录加载与汇总统计）
        self.run_start_time = datetime.datetime.now()
        ts = self.run_start_time.strftime("%Y%m%d_%H%M%S")
        self.run_log_file = self.pdf_save_dir / f"batch_bfs_log_{ts}.txt"
        
        # 加载已有的DOI记录，实现去重
        self._load_existing_dois()

    def _append_run_log(self, line: str):
        """向本次运行的批量日志文件追加一行文本。"""
        try:
            self.pdf_save_dir.mkdir(parents=True, exist_ok=True)
            with open(self.run_log_file, "a", encoding="utf-8") as f:
                f.write(line.rstrip("\n") + "\n")
        except Exception as e:
            logger.warning(f"写入批量运行日志失败: {e}")

    # ========== 初始化/统计相关工具函数 ==========
    
    def _load_existing_dois(self):
        """加载已有的DOI记录，用于去重。
        - 从 download_results.csv 加载所有成功下载的DOI；
        - 从 download_errors.csv 加载所有曾经下载失败的DOI；
        后续批量下载时，这两类DOI都视为“已处理”，不会再次尝试，提高整体效率。
        """
        loaded_from_results = 0
        loaded_from_errors = 0
        
        # 1) 从 download_results.csv 加载成功下载的DOI
        download_results_file = self.pdf_save_dir / "download_results.csv"
        if download_results_file.exists():
            try:
                df = pd.read_csv(download_results_file, encoding="utf-8-sig")
                if 'doi' in df.columns:
                    for _, row in df.iterrows():
                        doi = row.get('doi')
                        if pd.notna(doi):
                            # 只加载成功下载的记录（success为True或有有效的filepath）
                            success = row.get('success', False)
                            filepath = row.get('filepath') or row.get('file_path')
                            
                            if success or (filepath and pd.notna(filepath) and str(filepath).strip()):
                                normalized = self.downloader.recorder._normalize_doi(str(doi))
                                if normalized not in self.all_dois:
                                    self.all_dois.add(normalized)
                                    loaded_from_results += 1
            except Exception as e:
                logger.warning(f"加载 download_results.csv 失败: {e}")
        
        # 2) 从 download_errors.csv 加载失败的DOI，视为“已处理过”
        download_errors_file = self.pdf_save_dir / "download_errors.csv"
        if download_errors_file.exists():
            try:
                df_err = pd.read_csv(download_errors_file, encoding="utf-8-sig")
                if "doi" in df_err.columns:
                    for _, row in df_err.iterrows():
                        doi = row.get("doi")
                        if pd.notna(doi):
                            normalized = self.downloader.recorder._normalize_doi(str(doi))
                            if normalized not in self.all_dois:
                                self.all_dois.add(normalized)
                                loaded_from_errors += 1
            except Exception as e:
                logger.warning(f"加载 download_errors.csv 失败: {e}")
        
        summary = (
            f"已加载 {len(self.all_dois)} 个已处理DOI记录（成功: {loaded_from_results} 个，失败: {loaded_from_errors} 个）"
        )
        logger.info(summary)
        self._append_run_log(
            f"[INIT] {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')} - {summary}"
        )

    def _estimate_coverage_factor(self) -> float:
        """
        估算“单篇种子文献”在多层引用扩展后，理论上能带来的总文献量倍数。
        使用几何级数近似：
            有效分支因子 r = 平均参考文献数 * (1 - 失败率)
            覆盖倍数 ~= 1 + r + r^2 + ... + r^(MAX_BFS_DEPTH-1)
        """
        r = AVG_REFS_PER_ARTICLE * (1.0 - DOWNLOAD_FAIL_RATE)
        factor = 0.0
        current = 1.0
        for _ in range(MAX_BFS_DEPTH):
            factor += current
            current *= r
        return factor

    def _compute_adjusted_search_limits(
        self, search_queries: List[Dict], target_total_pdfs: int
    ) -> List[Dict]:
        """
        根据目标下载总量 + 分层扩展倍数，估算是否需要“放大”初始搜索量。
        - 若当前配置理论上已足够覆盖 30 万篇，则不缩减，只记录说明；
        - 若明显不足，则按统一比例放大每个关键词的 max_results。
        """
        raw_seed_total = sum(q["max_results"] for q in search_queries)
        coverage_factor = self._estimate_coverage_factor()
        if raw_seed_total <= 0 or coverage_factor <= 0:
            return search_queries

        # 理论上：总覆盖量 ≈ raw_seed_total * coverage_factor
        theoretical_total = raw_seed_total * coverage_factor
        logger.info(
            f"按经验参数估算：当前种子量约可覆盖 {int(theoretical_total):,} 篇文献 "
            f"(种子数={raw_seed_total}, 覆盖倍数≈{coverage_factor:.1f})"
        )

        scale = target_total_pdfs / theoretical_total

        # 如果 scale <= 1，说明现有种子量理论上已经足够或偏多，不做缩减，避免漏掉文献
        if scale <= 1.0:
            logger.info(
                f"理论上当前配置已足够覆盖目标 {target_total_pdfs:,} 篇，不调整各关键词的 max_results。"
            )
            return search_queries

        # 需要适当放大每个关键词的 max_results
        logger.info(
            f"理论上当前种子量偏少，将按比例放大各关键词 max_results，放大倍数≈{scale:.2f}"
        )

        adjusted = []
        for cfg in search_queries:
            new_cfg = cfg.copy()
            base = cfg["max_results"]
            adjusted_max = int(base * scale)
            # 限制上界，避免单次请求过大（PubMed 通常建议单次 retmax 不要太夸张）
            adjusted_max = max(base, min(adjusted_max, 10_000))
            new_cfg["adjusted_max_results"] = adjusted_max
            adjusted.append(new_cfg)

        return adjusted

    def batch_search_and_download(
        self,
        search_queries: List[Dict],
        skip_existing: bool = True,
        batch_size: int = 50
    ):
        """
        批量搜索和下载文献
        :param search_queries: 搜索查询列表，每个元素包含query、max_results和description
        :param skip_existing: 是否跳过已存在的DOI
        :param batch_size: 每个批次处理的文献数量（默认50篇）
        """
        print("\n" + "=" * 80)
        print("开始批量搜索和下载言语障碍相关文献")
        print("=" * 80)
        print(f"共 {len(search_queries)} 个搜索关键词")
        print(f"总目标文献数: {sum(q['max_results'] for q in search_queries)} 篇")
        print(f"已有DOI记录: {len(self.all_dois)} 个")
        print("=" * 80 + "\n")
        
        all_results = []
        total_found = 0
        total_new_dois = 0
        
        for idx, search_config in enumerate(search_queries, 1):
            query = search_config["query"]
            max_results = search_config["max_results"]
            description = search_config.get("description", query)
            
            print("\n" + "=" * 80)
            print(f"[{idx}/{len(search_queries)}] 搜索: {query}")
            print(f"描述: {description}")
            print(f"最大结果数: {max_results}")
            print("=" * 80)
            
            try:
                # 搜索文献：启用 random_start，尽量在允许范围内随机选取窗口，减少多次运行时的结果重叠
                articles = self.downloader.pubmed_searcher.search(
                    query,
                    max_results=max_results,
                    random_start=True,
                )
                
                if not articles:
                    logger.warning(f"未找到相关文献: {query}")
                    continue
                
                print(f"\n找到 {len(articles)} 篇文献")
                
                # 提取DOI并去重（只跳过成功下载的记录）
                new_articles = []
                for article in articles:
                    doi = article.get("doi")
                    if not doi:
                        continue
                    normalized_doi = self.downloader.recorder._normalize_doi(doi)
                    # 对于已成功或已失败的DOI，一律视为“已处理”，在批量下载中跳过
                    if skip_existing and (
                        self.downloader.recorder.is_downloaded(doi)
                        or self.downloader.recorder.is_failed(doi)
                    ):
                        continue
                    
                    # 注意：这里不添加到 all_dois，因为 all_dois 只用于记录成功下载的DOI
                    # 只有当成功下载后，才会通过 process_article 内部的 recorder.mark_downloaded 添加到 all_dois
                    new_articles.append(article)
                
                print(f"其中 {len(new_articles)} 篇为新文献（去重后）")
                total_found += len(articles)
                total_new_dois += len(new_articles)
                
                if not new_articles:
                    print("所有文献均已存在，跳过下载")
                    continue
                
                # 将新文献分成多个批次
                total_batches = (len(new_articles) + batch_size - 1) // batch_size
                print(f"\n将 {len(new_articles)} 篇新文献分成 {total_batches} 个批次进行处理（每批 {batch_size} 篇）")
                
                # 关键词级别的统计
                keyword_batch_results = []
                keyword_success_count = 0
                keyword_fail_count = 0
                
                # 对每个批次进行处理
                for batch_idx in range(total_batches):
                    start_idx = batch_idx * batch_size
                    end_idx = min(start_idx + batch_size, len(new_articles))
                    current_batch = new_articles[start_idx:end_idx]
                    
                    print(f"\n" + "=" * 80)
                    print(f"处理批次 {batch_idx + 1}/{total_batches} (文献 {start_idx + 1}-{end_idx} / 共 {len(new_articles)} 篇)")
                    print("=" * 80)
                    
                    # 批次级别的统计
                    batch_results = []
                    batch_success_count = 0
                    batch_fail_count = 0
                    
                    # 处理当前批次中的每一篇文献
                    for article_idx, article in enumerate(current_batch, 1):
                        doi = article.get("doi")
                        if not doi:
                            continue
                        
                        # 在处理每个DOI之前，再次检查是否已处理过（成功或失败）
                        normalized_doi = self.downloader.recorder._normalize_doi(doi)
                        if self.downloader.recorder.is_downloaded(doi) or self.downloader.recorder.is_failed(doi):
                            logger.info(f"DOI {doi} 已在历史记录中处理过（成功/失败），批次处理时跳过")
                            print(f"\n[批次{batch_idx + 1}-{article_idx}/{len(current_batch)}] 跳过: {article.get('title', 'N/A')[:60]}...")
                            print(f"  → DOI {doi} 已成功下载，跳过")
                            # 确保在 all_dois 中（虽然应该已经在了，但为了保险）
                            if normalized_doi not in self.all_dois and self.downloader.recorder.is_downloaded(doi):
                                # 仅把成功下载的 DOI 补充到 all_dois，用于统计
                                self.all_dois.add(normalized_doi)
                            continue
                        
                        global_idx = start_idx + article_idx
                        
                        print(
                            f"\n[批次{batch_idx + 1}-{article_idx}/{len(current_batch)}] "
                            f"(总进度: {global_idx}/{len(new_articles)}) 处理: {article.get('title', 'N/A')[:60]}..."
                        )
                        logger.info(f"开始处理DOI: {doi} (批次 {batch_idx + 1}/{total_batches})")
                        
                        # 处理DOI（使用ArticleProcessor统一处理）
                        result = self.downloader.article_processor.process_article(doi, article)
                        batch_results.append(result)
                        keyword_batch_results.append(result)
                        all_results.append(result)
                        
                        # 如果成功下载，将DOI添加到 all_dois 集合中（用于后续去重）
                        # 失败的不添加到 all_dois，允许重新尝试
                        if result.get('success'):
                            # 确保在 all_dois 中（用于后续的去重检查）
                            if normalized_doi not in self.all_dois:
                                self.all_dois.add(normalized_doi)
                            batch_success_count += 1
                            keyword_success_count += 1
                        else:
                            batch_fail_count += 1
                            keyword_fail_count += 1
                        
                        # 添加延迟避免请求过快
                        time.sleep(self.downloader.download_delay)
                    
                    # 显示当前批次的处理统计
                    print(f"\n" + "-" * 80)
                    print(f"批次 {batch_idx + 1}/{total_batches} 处理完成:")
                    print(f"  成功: {batch_success_count} 篇")
                    print(f"  失败: {batch_fail_count} 篇")
                    print(f"  总计: {len(batch_results)} 篇")
                    print("-" * 80)
                    
                    # 批次处理完成后，立即更新下载结果（确保进度实时保存）
                    if batch_results:
                        self.downloader._update_download_results(batch_results)
                        logger.info(f"批次 {batch_idx + 1}/{total_batches} 的结果已更新到 download_results.csv")
                    
                    # 如果还有下一个批次，显示提示信息
                    if batch_idx < total_batches - 1:
                        print(f"\n等待 {self.downloader.download_delay} 秒后开始处理下一个批次...\n")
                        time.sleep(self.downloader.download_delay)
                
                # 显示当前关键词的所有批次处理统计
                print(f"\n" + "=" * 80)
                print(f"关键词 '{query}' 的所有批次处理完成:")
                print(f"  总批次: {total_batches} 个")
                print(f"  成功: {keyword_success_count} 篇")
                print(f"  失败: {keyword_fail_count} 篇")
                print(f"  总计: {len(keyword_batch_results)} 篇")
                print("=" * 80)
                
                # 保存当前关键词的搜索结果
                if new_articles:
                    batch_csv_file = self.pdf_save_dir / f"batch_search_{query.replace(' ', '_').replace('/', '_')}.csv"
                    df_batch = pd.DataFrame(new_articles)
                    df_batch.to_csv(batch_csv_file, index=False, encoding="utf-8-sig")
                    logger.info(f"关键词 '{query}' 的搜索结果已保存到: {batch_csv_file}")
                
                print(f"\n✓ 关键词 '{query}' 的所有批次处理完成，继续下一个关键词...\n")
                
            except Exception as e:
                logger.error(f"处理搜索关键词 '{query}' 时出错: {e}")
                continue
        
        # 最终统计
        print("\n" + "=" * 80)
        print("批量搜索和下载完成！")
        print("=" * 80)
        print(f"总搜索到文献: {total_found} 篇")
        print(f"新文献（去重后）: {total_new_dois} 篇")
        print(f"当前总DOI记录: {len(self.all_dois)} 个")
        print("=" * 80 + "\n")
        
        # 保存汇总结果
        self._save_summary_report(search_queries, total_found, total_new_dois)

    # ========== BFS 分层下载实现 ==========

    def bfs_search_and_download(
        self,
        search_queries: List[Dict],
        target_total_pdfs: int = TARGET_TOTAL_PDFS,
        max_depth: int = MAX_BFS_DEPTH,
    ):
        """
        使用广度优先遍历（非递归）实现分层下载：
        - 第 1 层：原始 PubMed 搜索结果（种子文献）；
        - 第 2 层：第 1 层文献的参考文献；
        - 第 3 层：第 2 层文献的参考文献；
        - ...，直到达到 max_depth 或成功下载数接近 target_total_pdfs。
        """
        start_time_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        print("\n" + "=" * 80)
        print("开始基于 BFS 的分层下载（言语障碍相关文献）")
        print("=" * 80)
        print(f"目标总成功下载量: {target_total_pdfs:,} 篇")
        print(f"最大分层深度: {max_depth} 层")
        print(f"当前已成功下载: {len(self.downloader.recorder.downloaded_dois):,} 篇")
        print("=" * 80 + "\n")

        # 记录本次 BFS 运行的起始信息到独立日志文件
        self._append_run_log("=" * 80)
        self._append_run_log(f"[BFS-START] {start_time_str}")
        self._append_run_log(
            f"目标总成功下载量: {target_total_pdfs:,} 篇, 最大分层深度: {max_depth}, "
            f"当前已成功下载: {len(self.downloader.recorder.downloaded_dois):,} 篇, "
            f"历史失败记录数: {len(self.downloader.recorder.failed_dois):,} 条"
        )

        # 1. 根据经验参数调整各关键词的初始搜索数量
        adjusted_queries = self._compute_adjusted_search_limits(
            search_queries, target_total_pdfs
        )

        # 2. 准备 BFS 队列：元素为 (doi, article_info, level)
        queue: deque[Tuple[str, Dict, int]] = deque()
        visited_dois: Set[str] = set()  # 防止在 BFS 过程中重复入队（图中回环）

        # 3. 第一层：执行各关键词的 PubMed 搜索，构造种子节点
        for idx, cfg in enumerate(adjusted_queries, 1):
            query = cfg["query"]
            base_max = cfg["max_results"]
            effective_max = cfg.get("adjusted_max_results", base_max)

            print("\n" + "=" * 80)
            print(f"[种子 {idx}/{len(adjusted_queries)}] 搜索: {query}")
            print(f"  原始 max_results: {base_max}")
            print(f"  实际使用的 max_results: {effective_max}")
            print("=" * 80)

            try:
                articles = self.downloader.pubmed_searcher.search(
                    query, max_results=effective_max
                )
            except Exception as e:
                logger.error(f"执行 PubMed 搜索 '{query}' 时出错: {e}")
                continue

            if not articles:
                logger.warning(f"未找到相关文献: {query}")
                continue

            print(f"  找到 {len(articles)} 篇文献（第 1 层种子）")

            seed_added = 0
            for art in articles:
                doi = art.get("doi")
                if not doi:
                    continue
                normalized = self.downloader.recorder._normalize_doi(doi)
                # 若该 DOI ...
                if normalized in visited_dois:
                    continue
                # 入队作为第 1 层节点
                queue.append((doi, art, 1))
                visited_dois.add(normalized)
                seed_added += 1

            print(f"  作为 BFS 种子入队的文献数: {seed_added}")

        if not queue:
            print("未能构造任何 BFS 种子节点，流程结束。")
            return

        # 4. BFS 主循环
        print("\n" + "=" * 80)
        print("开始 BFS 分层下载...")
        print("=" * 80)

        start_downloaded = len(self.downloader.recorder.downloaded_dois)
        target_absolute = target_total_pdfs  # 目标是“绝对总量” 30 万

        processed_nodes = 0
        last_report_time = time.time()

        while queue and len(self.downloader.recorder.downloaded_dois) < target_absolute:
            doi, article_info, level = queue.popleft()
            processed_nodes += 1

            normalized = self.downloader.recorder._normalize_doi(doi)

            print(
                f"\n[BFS 节点 {processed_nodes}] 层级={level}, "
                f"DOI={doi}, 队列剩余={len(queue)}"
            )

            # 4.1 下载当前节点对应文献：
            # - 若该文献尚未处理（既不在成功列表也不在失败列表），则尝试下载一次；
            # - 若已在 download_results.csv 或 download_errors.csv 中出现过，则跳过下载，
            #   但仍会在后续 4.3 中扩展其参考文献，保证引用可以继续进入队列。
            if self.downloader.recorder.is_downloaded(doi):
                logger.info(
                    f"BFS 节点 DOI {doi} 已成功下载（历史记录），跳过本次下载，仅扩展引用。"
                )
            elif self.downloader.recorder.is_failed(doi):
                logger.info(
                    f"BFS 节点 DOI {doi} 之前已下载失败（历史记录），跳过本次下载，仅扩展引用。"
                )
            else:
                self.downloader.article_processor.process_article(doi, article_info)

            # 4.2 若达到最大深度，不再扩展引用
            if level >= max_depth:
                continue

            # 4.3 扩展当前文献的参考文献作为下一层节点
            refs = article_info.get("references") or []
            if not refs:
                continue

            logger.info(
                f"扩展参考文献：当前文献层级={level}, 引用数={len(refs)}"
            )

            for ref in refs:
                ref_title = ref.get("title") or ref.get("raw_citation") or ""
                ref_pmid = ref.get("pmid")
                ref_doi = ref.get("doi")

                child_article = None
                child_doi = None

                # (1) 有 DOI：直接作为下一层节点
                if ref_doi:
                    child_doi = ref_doi
                    child_article = {
                        "doi": ref_doi,
                        "pmid": ref_pmid,
                        "title": ref_title,
                        "year": None,
                        "journal": None,
                        "author": None,
                        # 参考文献的参考文献将在后续通过 PubMed 再查时补全
                        "references": [],
                    }

                # (2) 无 DOI 但有 PMID：尝试通过 PubMed 补全
                elif ref_pmid:
                    pmid_article = self.downloader.pubmed_searcher.fetch_by_pmid(
                        ref_pmid
                    )
                    if pmid_article and pmid_article.get("doi"):
                        child_doi = pmid_article["doi"]
                        child_article = pmid_article

                # (3) 仅有标题：用标题在 PubMed 中检索
                elif ref_title:
                    title_article = (
                        self.downloader.pubmed_searcher.find_article_by_title(
                            ref_title
                        )
                    )
                    if title_article and title_article.get("doi"):
                        child_doi = title_article["doi"]
                        child_article = title_article

                if not child_doi or not child_article:
                    # 可能为非 PubMed 来源或未被收录
                    continue

                child_norm = self.downloader.recorder._normalize_doi(child_doi)
                if child_norm in visited_dois:
                    continue

                visited_dois.add(child_norm)
                queue.append((child_doi, child_article, level + 1))

            # 控制请求速率
            time.sleep(self.downloader.download_delay)

            # 适时打印总体进度
            now = time.time()
            if now - last_report_time > 30:
                downloaded_now = len(self.downloader.recorder.downloaded_dois)
                print(
                    f"\n>>> 进度汇总：已处理 BFS 节点 {processed_nodes} 个，"
                    f"当前总成功下载数={downloaded_now:,} / 目标 {target_absolute:,}"
                )
                last_report_time = now

        # 5. 结束统计
        final_downloaded = len(self.downloader.recorder.downloaded_dois)
        print("\n" + "=" * 80)
        print("BFS 分层下载完成！")
        print("=" * 80)
        print(f"总处理 BFS 节点数: {processed_nodes}")
        print(f"当前总成功下载文献数: {final_downloaded:,}")
        print(f"本次新增成功下载数: {final_downloaded - start_downloaded:,}")
        print("=" * 80 + "\n")

        # 将结束统计写入本次运行日志文件
        end_time_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self._append_run_log(f"[BFS-END] {end_time_str}")
        self._append_run_log(f"总处理 BFS 节点数: {processed_nodes}")
        self._append_run_log(
            f"当前总成功下载文献数: {final_downloaded:,}，"
            f"本次新增成功下载数: {final_downloaded - start_downloaded:,}"
        )
        self._append_run_log("=" * 80)

    
    def _save_summary_report(
        self,
        search_queries: List[Dict],
        total_found: int,
        total_new_dois: int
    ):
        """保存汇总报告"""
        summary_file = self.pdf_save_dir / "batch_download_summary.txt"
        
        with open(summary_file, 'w', encoding='utf-8') as f:
            f.write("批量下载汇总报告\n")
            f.write("=" * 80 + "\n")
            f.write(f"生成时间: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
            f.write(f"总搜索关键词数: {len(search_queries)}\n")
            f.write(f"总搜索到文献: {total_found} 篇\n")
            f.write(f"新文献（去重后）: {total_new_dois} 篇\n")
            f.write(f"当前总DOI记录: {len(self.all_dois)} 个\n")
            f.write("\n搜索关键词列表:\n")
            f.write("-" * 80 + "\n")
            for idx, sq in enumerate(search_queries, 1):
                f.write(f"{idx}. {sq['query']} ({sq.get('description', '')}) - 最大结果数: {sq['max_results']}\n")
        
        logger.info(f"汇总报告已保存到: {summary_file}")


if __name__ == "__main__":
    # ========== 日志配置 ==========
    # 所有日志同时输出到控制台和文件（位于项目根目录或当前工作目录）
    setup_logging(log_file="download-batch.log")

    # ========== 配置参数 ==========
    # 请修改以下参数
    YOUR_EMAIL = "gl6673258@gmail.com"  # 替换为你的邮箱
    API_KEY = '8ae8dff75b1ee2d143685b8ba71b3b8cff09'  # 可选：PubMed API密钥
    
    PDF_SAVE_DIR = "literature_pdfs"  # PDF保存目录
    DOWNLOAD_DELAY = 2.0  # 下载延迟（秒），建议1.0-2.0秒，避免请求过快
    TIMEOUT = 60  # 下载超时时间（秒）
    
    # Selenium设置
    USE_SELENIUM_FALLBACK = True  # 是否使用Selenium作为备选方案
    SELENIUM_HEADLESS = False  # Selenium是否使用无头模式
    
    # 参考文献解析：是否使用通义 LLM 从 raw_citation 提取标题等（关闭则仅用 XML/正则，加快测试）
    USE_LLM_FOR_REFERENCES = True  # 测试全流程时可设为 False；需要更准的引用解析时设为 True
    
    # 批次处理设置
    BATCH_SIZE = 50  # 每个批次处理的文献数量（建议20-100之间，可根据实际情况调整）
    
    # ========== 执行批量下载 ==========
    batch_downloader = BatchSpeechDisorderDownloader(
        email=YOUR_EMAIL,
        api_key=API_KEY,
        pdf_save_dir=PDF_SAVE_DIR,
        download_delay=DOWNLOAD_DELAY,
        timeout=TIMEOUT,
        use_selenium_fallback=USE_SELENIUM_FALLBACK,
        selenium_headless=SELENIUM_HEADLESS,
        use_llm_for_references=USE_LLM_FOR_REFERENCES,
    )
    
    # 方式一（原有）：按关键词批次顺序处理（不分层扩展引用）
    # batch_downloader.batch_search_and_download(
    #     search_queries=SEARCH_QUERIES,
    #     skip_existing=True,
    #     batch_size=BATCH_SIZE,
    # )

    # 方式二（推荐）：使用非递归 BFS 分层下载（包含多层参考文献）
    batch_downloader.bfs_search_and_download(
        search_queries=SEARCH_QUERIES,
        target_total_pdfs=TARGET_TOTAL_PDFS,
        max_depth=MAX_BFS_DEPTH,
    )

