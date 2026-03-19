"""
PDF下载工具模块
提供OA和非OA下载器共用的基础功能
"""
import logging
import time
from pathlib import Path
from typing import Optional

import requests
from bs4 import BeautifulSoup

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


class PDFUtils:
    """PDF工具类，提供共用功能"""
    
    @staticmethod
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
    
    @staticmethod
    def generate_filename(doi: str, year: Optional[str] = None, source: Optional[str] = None) -> str:
        """
        生成安全的文件名
        格式：doi号_年份_来源.pdf
        :param doi: 文献DOI
        :param year: 年份（可选）
        :param source: 来源（可选）
        :return: 文件名
        """
        clean_doi = PDFUtils.clean_doi(doi)
        doi_slug = clean_doi.replace('/', '_').replace(':', '_')
        parts = [doi_slug]
        if year:
            parts.append(str(year))
        if source:
            parts.append(source)
        return "_".join(parts) + ".pdf"
    
    @staticmethod
    def download_pdf_direct(
        pdf_url: str,
        save_path: Path,
        timeout: int = 60,
        delay: float = 1.0
    ) -> bool:
        """
        直接下载PDF文件（流式下载，避免内存溢出）
        :param pdf_url: PDF URL
        :param save_path: 保存路径
        :param timeout: 超时时间（秒）
        :param delay: 下载后延迟（秒）
        :return: 是否成功
        """
        try:
            logger.info(f"直接下载PDF: {pdf_url}")
            
            # 跳过已存在的文件
            if save_path.exists():
                logger.info(f"文件已存在，无需重复下载: {save_path.name}")
                return True
            
            # 为特定站点添加必要的headers
            from urllib.parse import urlparse
            parsed_url = urlparse(pdf_url)
            domain = parsed_url.netloc.lower()
            
            # 准备请求headers（模拟浏览器请求头，避免被判定为爬虫）
            request_headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                "Accept": "application/pdf,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "en-US,en;q=0.5",
                "Accept-Encoding": "gzip, deflate, br",
                "Connection": "keep-alive",
            }
            
            # 为特定网站添加Referer头
            # if 'nature.com' in domain:
            #     # Nature网站需要从官网跳转的Referer
            #     request_headers['Referer'] = "https://www.nature.com/"
            #     logger.debug(f"为Nature网站添加Referer头")
            # elif 'biorxiv.org' in domain or 'medrxiv.org' in domain:
            #     # 从PDF URL构造文章页面URL作为Referer
            #     if '/content/' in pdf_url:
            #         article_url = pdf_url.replace('.full.pdf', '').replace('.pdf', '')
            #         if '/early/' in article_url:
            #             parts = article_url.split('/')
            #             if len(parts) > 0:
            #                 last_part = parts[-1]
            #                 if '10.1101' in last_part or '202' in last_part[:4]:
            #                     article_url = '/'.join(parts[:-1])
            #         request_headers['Referer'] = article_url
            #         logger.debug(f"为bioRxiv/medRxiv添加Referer头: {article_url}")
            
            # 延迟请求，模拟真人操作
            time.sleep(delay)
            
            # 使用requests.get()进行流式下载
            response = requests.get(
                pdf_url,
                headers=request_headers,
                stream=True,
                timeout=timeout,
                allow_redirects=True
            )
            
            # 记录响应状态和内容类型
            logger.debug(f"HTTP状态码: {response.status_code}, Content-Type: {response.headers.get('Content-Type', 'unknown')}")
            
            response.raise_for_status()  # 捕获HTTP错误（如403、404）
            
            # 获取文件大小（可选，用于进度提示）
            content_length = response.headers.get("Content-Length")
            file_size_mb = 0
            if content_length:
                file_size_mb = int(content_length) / (1024 * 1024)
                logger.info(f"文件大小约：{file_size_mb:.2f} MB")
            
            # 检查是否为PDF（先检查Content-Type）
            content_type = response.headers.get("Content-Type", "").lower()
            is_pdf_by_content_type = "pdf" in content_type
            
            # 分块写入文件（每次1MB，避免内存溢出）
            first_chunk_received = False
            first_bytes = b""
            downloaded_size_mb = 0
            with open(save_path, 'wb') as f:
                for chunk in response.iter_content(chunk_size=1024*1024):  # 每次1MB
                    if chunk:
                        # 保存第一个chunk的前4个字节用于验证
                        if not first_chunk_received:
                            first_bytes = chunk[:4]
                            first_chunk_received = True
                        f.write(chunk)
                        downloaded_size_mb += len(chunk) / (1024 * 1024)
                        # 实时打印下载进度（如果知道文件大小）
                        if file_size_mb > 0:
                            logger.debug(f"下载进度：{downloaded_size_mb:.2f} MB / {file_size_mb:.2f} MB")
            
            # 验证是否为PDF（通过文件内容）
            if not is_pdf_by_content_type and first_bytes != b"%PDF":
                logger.warning(f"响应内容类型为 {content_type}，且文件开头不是PDF格式")
                if save_path.exists():
                    save_path.unlink()
                return False
            
            # 验证文件
            file_size = save_path.stat().st_size
            if file_size < 1024:  # 小于1KB可能是错误页面
                save_path.unlink()
                logger.warning(f"下载的文件太小 ({file_size} bytes)")
                return False
            
            # 再次验证文件是否为PDF格式
            # with open(save_path, 'rb') as f:
            #     if f.read(4) != b"%PDF":
            #         save_path.unlink()
            #         logger.warning(f"文件不是PDF格式")
            #         return False
            
            logger.info(f"PDF下载成功: {save_path} ({file_size/1024/1024:.2f} MB)")
            return True
            
        except requests.exceptions.HTTPError as e:
            status_code = e.response.status_code if hasattr(e, 'response') and e.response else 'unknown'
            logger.error(f"直接下载PDF失败 - HTTP错误 {status_code}: {e}")
            if hasattr(e, 'response') and e.response:
                logger.error(f"响应内容: {e.response.text[:500]}")
            # 清理未下载完成的文件
            if save_path.exists():
                save_path.unlink()
            return False
        except requests.exceptions.Timeout as e:
            logger.error(f"直接下载PDF失败 - 请求超时: {e}")
            # 清理未下载完成的文件
            if save_path.exists():
                save_path.unlink()
            return False
        except requests.exceptions.ConnectionError as e:
            logger.error(f"直接下载PDF失败 - 连接错误: {e}")
            # 清理未下载完成的文件
            if save_path.exists():
                save_path.unlink()
            return False
        except Exception as e:
            logger.error(f"直接下载PDF失败 - 未知错误: {type(e).__name__}: {e}")
            import traceback
            logger.debug(f"详细错误信息:\n{traceback.format_exc()}")
            # 清理未下载完成的文件
            if save_path.exists():
                save_path.unlink()
            return False
    
    @staticmethod
    def extract_pdf_from_html(
        html_url: str,
        timeout: int = 60
    ) -> Optional[str]:
        """
        从HTML页面提取PDF链接
        :param html_url: HTML页面URL
        :param timeout: 超时时间（秒）
        :return: PDF URL或None
        """
        try:
            logger.info(f"从HTML页面提取PDF: {html_url}")
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "en-US,en;q=0.9",
            }
            response = requests.get(html_url, headers=headers, timeout=timeout, allow_redirects=True)
            response.raise_for_status()
            
            # 检查是否已经是PDF
            content_type = response.headers.get("Content-Type", "").lower()
            if "pdf" in content_type:
                return html_url
            
            # 解析HTML查找PDF链接
            soup = BeautifulSoup(response.text, 'html.parser')
            
            # 查找PDF下载链接
            pdf_links = []
            for link in soup.find_all('a', href=True):
                href = link.get('href', '')
                text = link.get_text().lower()
                if '.pdf' in href.lower() or 'pdf' in text or 'download' in text:
                    from urllib.parse import urljoin
                    full_url = urljoin(html_url, href)
                    pdf_links.append(full_url)
            
            # 返回第一个找到的PDF链接
            if pdf_links:
                return pdf_links[0]
            
            return None
            
        except Exception as e:
            logger.error(f"从HTML提取PDF失败: {e}")
            return None
    

