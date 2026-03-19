"""
非OA文献分层级合规获取模块
实现「合规优先、备选补充」的层级策略，最大化获取成功率
"""
import logging
import time
import re
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Optional, Dict, List
from urllib.parse import urlencode, quote

import requests
from bs4 import BeautifulSoup
from pdf_utils import PDFUtils

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


class NonOADownloader:
    """非OA文献分层级下载器"""
    
    def __init__(
        self,
        save_dir: str = "literature_pdfs/non_oa",
        timeout: int = 60,
        delay: float = 1.0,
        use_institutional_access: bool = False,
    ):
        """
        初始化非OA下载器
        :param save_dir: PDF保存目录
        :param timeout: 下载超时时间（秒）
        :param delay: 每次请求之间的延迟（秒）
        :param use_institutional_access: 是否使用机构权限（第一层级，暂时不支持）
        """
        self.save_dir = Path(save_dir)
        self.save_dir.mkdir(parents=True, exist_ok=True)
        self.timeout = timeout
        self.delay = delay
        self.use_institutional_access = use_institutional_access
        
        # 请求头
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,application/json,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.9',
            'Accept-Encoding': 'gzip, deflate, br',
            'Connection': 'keep-alive',
        }
        
    
    @staticmethod
    def _clean_doi(doi: str) -> str:
        """清理DOI（使用共用工具）"""
        return PDFUtils.clean_doi(doi)
    
    def _generate_filename(self, doi: str, year: Optional[str] = None, source: Optional[str] = None) -> str:
        """生成安全的文件名（使用共用工具）"""
        return PDFUtils.generate_filename(doi, year, source)
    
    def _download_pdf_direct(self, pdf_url: str, save_path: Path) -> bool:
        """直接下载PDF文件（使用共用工具）"""
        return PDFUtils.download_pdf_direct(
            pdf_url,
            save_path,
            timeout=self.timeout,
            delay=self.delay
        )
    
    # ========== 第一层级：机构权限/合法渠道 ==========
    
    def download_institutional_access(
        self,
        doi: str,
        journal: Optional[str] = None,
        publisher: Optional[str] = None,
        year: Optional[str] = None,
        title: Optional[str] = None
    ) -> Optional[str]:
        """
        第一层级：机构权限/合法渠道（零风险，首选）
        注意：目前暂时不支持，但保留接口以备后续更新
        :param doi: 文献DOI
        :param journal: 期刊名称
        :param publisher: 出版商
        :param year: 年份
        :param title: 标题
        :return: 下载的文件路径或None
        """
        if not self.use_institutional_access:
            return None
        
        logger.info(f"【第一层级】尝试机构权限访问: {doi}")
        # TODO: 实现机构权限访问逻辑
        # 1. 获取期刊来源和出版商
        # 2. 针对不同出版商的数据库，使用Selenium自动化下载
        logger.warning("机构权限访问功能尚未实现，跳过")
        return None
    
    # ========== 统一入口：分层级下载 ==========
    
    def download_non_oa(
        self,
        doi: str,
        year: Optional[str] = None,
        title: Optional[str] = None,
        journal: Optional[str] = None,
        publisher: Optional[str] = None
    ) -> Optional[str]:
        """
        非OA文献分层级下载（合规优先、备选补充）
        :param doi: 文献DOI
        :param year: 年份
        :param title: 标题
        :param journal: 期刊名称
        :param publisher: 出版商
        :return: 下载的文件路径或None
        """
        logger.info(f"开始非OA文献分层级下载: {doi}")
        
        # 第一层级：机构权限/合法渠道（零风险，首选）
        if self.use_institutional_access:
            result = self.download_institutional_access(doi, journal, publisher, year, title)
            if result:
                logger.info(f"✓ 第一层级成功: {result}")
                return result
        
        # 第二、第三层级（预印本 / Sci-Hub / LibGen）相关逻辑已移除，
        # 非OA下载目前仅保留机构权限占位逻辑（可根据需要在此扩展新的合法获取渠道）。
        
        logger.warning(f"✗ 非OA分层级下载未能获取文献: {doi}")
        return None

