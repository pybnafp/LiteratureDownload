"""
下载记录模块
用于记录已下载的DOI，防止重复下载
使用CSV文件替代JSON文件进行记录管理
"""
import logging
import pandas as pd
from pathlib import Path
from typing import Set, Optional, Dict

# 配置日志
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


class DownloadRecorder:
    """下载记录器，用于跟踪已下载的DOI"""
    
    def __init__(self, pdf_save_dir: str = "literature_pdfs"):
        """
        初始化下载记录器
        :param pdf_save_dir: PDF保存目录，用于查找CSV文件
        """
        self.pdf_save_dir = Path(pdf_save_dir)
        self.pdf_save_dir.mkdir(parents=True, exist_ok=True)
        
        # 主记录文件：所有成功下载的文献
        self.download_results_file = self.pdf_save_dir / "download_results.csv"
        # 失败记录文件：所有下载失败的文献
        self.download_errors_file = self.pdf_save_dir / "download_errors.csv"
        
        self.downloaded_dois: Set[str] = set()
        self.failed_dois: Set[str] = set()
        self.downloaded_records: Dict[str, Dict] = {}  # 存储详细的下载记录 {doi: {filepath, source, year, ...}}
        self.failed_records: Dict[str, Dict] = {}  # 存储详细的失败记录 {doi: {reason, title, journal, ...}}
        self._load_records()
    
    def _load_records(self):
        """从CSV文件加载已下载和已失败的DOI记录（download_results.csv 与 download_errors.csv）"""
        self._load_records_from_download_results()
        self._load_failed_records()
    
    def _load_records_from_download_results(self):
        """从 download_results.csv 加载所有成功下载的记录"""
        if not self.download_results_file.exists():
            logger.info("download_results.csv 文件不存在，将创建新记录")
            return
        
        try:
            df = pd.read_csv(self.download_results_file, encoding="utf-8-sig")
            
            if 'doi' not in df.columns:
                logger.warning("download_results.csv 中缺少 'doi' 列")
                return
            
            loaded_count = 0
            for _, row in df.iterrows():
                doi = row.get('doi')
                if pd.notna(doi) and str(doi).strip():
                    doi = str(doi).strip()
                    normalized_doi = self._normalize_doi(doi)
                    
                    # 检查是否成功下载
                    success = row.get('success', False)
                    filepath = row.get('filepath') or row.get('file_path')
                    
                    if success or (filepath and pd.notna(filepath) and str(filepath).strip()):
                        self.downloaded_dois.add(normalized_doi)
                        
                        # 保存详细记录
                        record = {
                            'doi': normalized_doi,
                            'filepath': str(filepath) if pd.notna(filepath) else None,
                            'source': row.get('source') or row.get('download_source'),
                            'year': row.get('year'),
                            'title': row.get('title'),
                            'journal': row.get('journal'),
                            'author': row.get('author'),
                            'pmid': row.get('pmid')
                        }
                        self.downloaded_records[normalized_doi] = record
                        loaded_count += 1
            
            logger.info(f"从 download_results.csv 加载了 {loaded_count} 个已下载记录")
        except Exception as e:
            logger.warning(f"加载 download_results.csv 失败: {e}")
    
    
    def _load_failed_records(self):
        """从 download_errors.csv 加载失败记录"""
        if not self.download_errors_file.exists():
            logger.info("download_errors.csv 文件不存在，将创建新记录")
            return
        
        try:
            df = pd.read_csv(self.download_errors_file, encoding="utf-8-sig")
            
            if 'doi' not in df.columns:
                logger.warning("download_errors.csv 中缺少 'doi' 列")
                return
            
            loaded_count = 0
            for _, row in df.iterrows():
                doi = row.get('doi')
                if pd.notna(doi) and str(doi).strip():
                    doi = str(doi).strip()
                    normalized_doi = self._normalize_doi(doi)
                    
                    self.failed_dois.add(normalized_doi)
                    
                    # 保存详细记录
                    record = {
                        'doi': normalized_doi,
                        'reason': row.get('reason') or row.get('error'),
                        'title': row.get('title'),
                        'journal': row.get('journal'),
                        'author': row.get('author'),
                        'year': row.get('year'),
                        'pmid': row.get('pmid'),
                        'source': row.get('source')
                    }
                    self.failed_records[normalized_doi] = record
                    loaded_count += 1
            
            logger.info(f"从 download_errors.csv 加载了 {loaded_count} 个失败记录")
        except Exception as e:
            logger.warning(f"加载 download_errors.csv 失败: {e}")
    
    def _save_records(self):
        """保存记录到CSV文件（此方法保留用于兼容，实际保存由main.py处理）"""
        # 不再使用JSON文件，保存逻辑由main.py统一处理
        pass
    
    def _normalize_doi(self, doi: str) -> str:
        """
        标准化DOI格式
        :param doi: 原始DOI
        :return: 标准化后的DOI
        """
        doi = doi.strip()
        # 移除URL前缀
        if doi.startswith('http'):
            if 'doi.org/' in doi:
                doi = doi.split('doi.org/')[-1]
            elif 'doi/' in doi:
                doi = doi.split('doi/')[-1]
        # 移除查询参数
        if '?' in doi:
            doi = doi.split('?')[0]
        return doi
    
    def is_downloaded(self, doi: str) -> bool:
        """
        检查DOI是否已下载
        :param doi: 文献DOI
        :return: 是否已下载
        """
        normalized_doi = self._normalize_doi(doi)
        return normalized_doi in self.downloaded_dois
    
    def is_failed(self, doi: str) -> bool:
        """
        检查DOI是否之前下载失败
        :param doi: 文献DOI
        :return: 是否之前失败
        """
        normalized_doi = self._normalize_doi(doi)
        return normalized_doi in self.failed_dois
    
    def mark_downloaded(self, doi: str, filepath: Optional[str] = None, source: Optional[str] = None, year: Optional[str] = None, 
                        title: Optional[str] = None, journal: Optional[str] = None, author: Optional[str] = None, 
                        pmid: Optional[str] = None):
        """
        标记DOI为已下载，并实时保存到CSV文件
        :param doi: 文献DOI
        :param filepath: 下载的文件路径（可选）
        :param source: 下载方式（可选）
        :param year: 年份（可选）
        :param title: 标题（可选）
        :param journal: 期刊（可选）
        :param author: 作者（可选）
        :param pmid: PMID（可选）
        """
        normalized_doi = self._normalize_doi(doi)
        self.downloaded_dois.add(normalized_doi)
        # 如果之前在失败列表中，移除它
        self.failed_dois.discard(normalized_doi)
        
        # 保存详细记录
        if normalized_doi not in self.downloaded_records:
            self.downloaded_records[normalized_doi] = {}
        self.downloaded_records[normalized_doi].update({
            'doi': normalized_doi,
            'filepath': filepath,
            'source': source,
            'year': year,
            'title': title,
            'journal': journal,
            'author': author,
            'pmid': pmid
        })
        
        # 实时保存到CSV文件
        self._save_downloaded_record(normalized_doi, source)
        
        logger.info(f"标记DOI为已下载: {normalized_doi}")
    
    def mark_failed(self, doi: str, reason: Optional[str] = None, title: Optional[str] = None, 
                    journal: Optional[str] = None, author: Optional[str] = None, 
                    year: Optional[str] = None, pmid: Optional[str] = None, 
                    source: Optional[str] = None):
        """
        标记DOI为下载失败，并保存到download_errors.csv
        :param doi: 文献DOI
        :param reason: 失败原因（可选）
        :param title: 标题（可选）
        :param journal: 期刊（可选）
        :param author: 作者（可选）
        :param year: 年份（可选）
        :param pmid: PMID（可选）
        :param source: 尝试的下载方式（可选）
        """
        normalized_doi = self._normalize_doi(doi)
        self.failed_dois.add(normalized_doi)
        
        # 保存详细记录
        if normalized_doi not in self.failed_records:
            self.failed_records[normalized_doi] = {}
        self.failed_records[normalized_doi].update({
            'doi': normalized_doi,
            'reason': reason,
            'title': title,
            'journal': journal,
            'author': author,
            'year': year,
            'pmid': pmid,
            'source': source
        })
        
        # 保存到 download_errors.csv 失败记录文件
        self._save_failed_records()
        # 同时在 download_results.csv 中以失败记录的形式写入一行，保持统一格式
        try:
            fail_record = {
                'doi': normalized_doi,
                'title': title,
                'journal': journal,
                'author': author,
                'year': year,
                'pmid': pmid,
                'source': source or 'unknown',
                'filepath': None,
            }
            self._save_to_download_results_csv(fail_record, success=False)
        except Exception as e:
            logger.error(f"在 download_results.csv 中记录失败结果时出错: {e}")
        
        logger.warning(f"标记DOI为下载失败: {normalized_doi}" + (f" (原因: {reason})" if reason else ""))
    
    def _save_failed_records(self):
        """保存失败记录到download_errors.csv（实时更新）"""
        try:
            # 读取现有记录
            existing_records = []
            if self.download_errors_file.exists():
                try:
                    df_existing = pd.read_csv(self.download_errors_file, encoding="utf-8-sig")
                    existing_records = df_existing.to_dict('records')
                except Exception as e:
                    logger.warning(f"读取 download_errors.csv 失败: {e}")
            
            # 创建DOI到记录的映射
            existing_doi_map = {}
            for record in existing_records:
                doi = record.get('doi')
                if doi:
                    normalized_doi = self._normalize_doi(str(doi))
                    existing_doi_map[normalized_doi] = record
            
            # 更新或添加新记录
            for normalized_doi, record in self.failed_records.items():
                existing_doi_map[normalized_doi] = {
                    'pmid': record.get('pmid', ''),
                    'title': record.get('title', ''),
                    'doi': record.get('doi', normalized_doi),
                    'journal': record.get('journal', ''),
                    'author': record.get('author', ''),
                    'year': record.get('year', ''),
                    'reason': record.get('reason', ''),
                    'source': record.get('source', '')
                }
            
            # 保存到CSV文件
            if existing_doi_map:
                df_errors = pd.DataFrame(list(existing_doi_map.values()))
                df_errors.to_csv(self.download_errors_file, index=False, encoding="utf-8-sig")
                logger.debug(f"已更新 download_errors.csv，共 {len(existing_doi_map)} 条失败记录")
        except Exception as e:
            logger.error(f"保存失败记录到 download_errors.csv 失败: {e}")
    
    def _save_downloaded_record(self, normalized_doi: str, source: Optional[str] = None):
        """
        实时保存单个下载记录到CSV文件（主文件和子目录文件）
        :param normalized_doi: 标准化后的DOI
        :param source: 下载方式（可选）
        """
        try:
            record = self.downloaded_records.get(normalized_doi, {})
            if not record:
                return
            
            # 如果之前有失败记录，需要从失败记录中移除（因为现在成功了）
            if normalized_doi in self.failed_records:
                # 从失败记录中移除
                del self.failed_records[normalized_doi]
                # 更新失败记录的CSV文件（移除该记录）
                self._save_failed_records()
            
            # 更新主记录文件 download_results.csv（成功标记）
            self._save_to_download_results_csv(record, success=True)
                
        except Exception as e:
            logger.error(f"实时保存下载记录失败: {e}")
    
    def _save_to_download_results_csv(self, record: Dict, success: bool = True):
        """
        保存到主记录文件 download_results.csv
        :param record: 记录字典
        :param success: 是否下载成功（True/False）
        """
        try:
            # 读取现有记录
            existing_records = []
            if self.download_results_file.exists():
                try:
                    df_existing = pd.read_csv(self.download_results_file, encoding="utf-8-sig")
                    existing_records = df_existing.to_dict('records')
                except Exception as e:
                    logger.warning(f"读取 download_results.csv 失败: {e}")
            
            # 创建DOI到记录的映射
            existing_doi_map = {}
            for r in existing_records:
                doi = r.get('doi')
                if doi:
                    normalized_doi = self._normalize_doi(str(doi))
                    existing_doi_map[normalized_doi] = r
            
            # 添加或更新当前记录
            normalized_doi = record.get('doi', '')
            new_record = {
                'pmid': record.get('pmid', ''),
                'title': record.get('title', ''),
                'doi': normalized_doi,
                'journal': record.get('journal', ''),
                'author': record.get('author', ''),
                'year': record.get('year', ''),
                # 对于失败记录，success 显式为 False
                'success': bool(success),
                'source': record.get('source', ''),
                'filepath': record.get('filepath', '')
            }
            existing_doi_map[normalized_doi] = new_record
            
            # 保存到CSV文件
            df_all = pd.DataFrame(list(existing_doi_map.values()))
            df_all.to_csv(self.download_results_file, index=False, encoding="utf-8-sig")
            logger.debug(f"已实时更新 download_results.csv")
        except Exception as e:
            logger.error(f"保存到 download_results.csv 失败: {e}")
    
    
    def get_statistics(self) -> dict:
        """
        获取统计信息
        :return: 包含统计信息的字典
        """
        return {
            'downloaded_count': len(self.downloaded_dois),
            'failed_count': len(self.failed_dois),
            'total_processed': len(self.downloaded_dois) + len(self.failed_dois)
        }
    

