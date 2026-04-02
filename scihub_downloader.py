# """
# SciHub下载模块
# 基于DOI从SciHub下载PDF文件
# 参考 PubMedSciHubDownloader 的实现逻辑进行优化
# """
# import requests
# import re
# import time
# import logging
# from pathlib import Path
# from typing import Optional, Dict, List
# from bs4 import BeautifulSoup

# logger = logging.getLogger(__name__)


# class SciHubDownloader:
#     """SciHub PDF下载器（优化版）"""
    
#     # SciHub镜像站点列表（按优先级排序）
#     MIRRORS = [
#         "https://sci-hub.se",
#         "https://sci-hub.st",
#         "https://sci-hub.ru",
#         "https://www.sci-hub.ren"
#     ]
    
#     def __init__(
#         self,
#         save_dir: str = "literature_pdfs/scihub",
#         timeout: int = 60,
#         delay: float = 3.0,
#         proxy_host: str = "127.0.0.1",
#         proxy_port: int = 7890,
#         use_proxy: bool = True
#     ):
#         """
#         初始化SciHub下载器
#         :param save_dir: PDF保存目录
#         :param timeout: 下载超时时间（秒）
#         :param delay: 每次下载之间的延迟（秒）
#         :param proxy_host: 代理服务器地址
#         :param proxy_port: 代理服务器端口
#         :param use_proxy: 是否使用代理
#         """
#         self.save_dir = Path(save_dir)
#         self.save_dir.mkdir(parents=True, exist_ok=True)
#         self.timeout = timeout
#         self.delay = delay
        
#         # 设置代理
#         self.use_proxy = use_proxy
#         if self.use_proxy:
#             self.proxies = {
#                 'http': f'http://{proxy_host}:{proxy_port}',
#                 'https': f'http://{proxy_host}:{proxy_port}'
#             }
#             logger.info(f"已启用代理: {proxy_host}:{proxy_port}")
#         else:
#             self.proxies = None
        
#         # 设置请求头，防止HTTP403错误
#         self.headers = {
#             'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
#             'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
#             'Accept-Language': 'en-US,en;q=0.5',
#             'Accept-Encoding': 'gzip, deflate',
#             'Connection': 'keep-alive',
#         }
        
#         # 当前可用的域名
#         self.current_domain = None
    
#     def get_available_scihub_domain(self, exclude_domains: Optional[list] = None) -> Optional[str]:
#         """
#         检测当前可用的Sci-Hub域名
#         :param exclude_domains: 要排除的域名列表（已尝试过的域名）
#         Returns: 可用的域名或None
#         """
#         if exclude_domains is None:
#             exclude_domains = []
        
#         for domain in self.MIRRORS:
#             # 跳过已排除的域名
#             if domain in exclude_domains:
#                 continue
            
#             try:
#                 response = requests.get(domain, headers=self.headers, timeout=10, proxies=self.proxies)
#                 if response.status_code == 200:
#                     logger.info(f"找到可用的Sci-Hub域名: {domain}")
#                     return domain
#             except requests.RequestException as e:
#                 logger.debug(f"域名 {domain} 不可用: {e}")
#                 continue
        
#         # 如果所有域名都被排除了，尝试使用第一个（即使之前失败过）
#         if exclude_domains and self.MIRRORS:
#             logger.warning("所有未尝试的Sci-Hub域名都不可用，将尝试使用列表中的第一个")
#             return self.MIRRORS[0]
        
#         logger.warning("所有Sci-Hub域名都不可用，将尝试使用列表中的第一个")
#         return self.MIRRORS[0] if self.MIRRORS else None
    
#     def _clean_doi(self, doi: str) -> str:
#         """
#         清理DOI（移除URL前缀等）
#         :param doi: 原始DOI
#         :return: 清理后的DOI
#         """
#         doi = doi.strip()
#         if doi.startswith('http'):
#             if 'doi.org/' in doi:
#                 doi = doi.split('doi.org/')[-1]
#             elif 'doi/' in doi:
#                 doi = doi.split('doi/')[-1]
#         # 移除可能的查询参数
#         if '?' in doi:
#             doi = doi.split('?')[0]
#         return doi
    
#     def get_pdf_url(self, doi: str, max_retries: int = 1) -> Optional[Dict]:
#         """
#         获取PDF链接（不下载）
#         :param doi: 文献DOI
#         :param max_retries: 最大重试次数
#         :return: 包含PDF链接信息的字典，如果未找到则返回None
#         """
#         if not doi or not isinstance(doi, str):
#             logger.error(f"无效的DOI：{doi}")
#             return None
        
#         # 清理DOI
#         doi = self._clean_doi(doi)
#         logger.info(f"尝试从SciHub获取PDF链接: {doi}")
        
#         # 记录已尝试的域名
#         tried_domains = []
        
#         # 尝试获取PDF链接
#         for attempt in range(max_retries):
            
#             logger.info(f"第 {attempt + 1} 次尝试...")
            
#             # 获取可用的域名（排除已尝试的）
#             current_domain = self.get_available_scihub_domain(exclude_domains=tried_domains)
#             if current_domain is None:
#                 logger.error("无法获取可用的Sci-Hub域名")
#                 break
            
#             # 记录当前尝试的域名
#             tried_domains.append(current_domain)
            
#             try:
#                 # 构造SciHub URL
#                 scihub_url = f"{current_domain.rstrip('/')}/{doi}"
#                 logger.info(f"访问Sci-Hub: {scihub_url} (域名: {current_domain})")
                
#                 # 发送请求获取页面
#                 response = requests.get(
#                     scihub_url,
#                     headers=self.headers,
#                     timeout=self.timeout,
#                     allow_redirects=True,
#                     proxies=self.proxies
#                 )
#                 response.raise_for_status()
                
#                 # 提取PDF链接
#                 download_url = self._extract_pdf_url(response.text, current_domain)
#                 if not download_url:
#                     logger.warning(f"未在Sci-Hub页面中找到PDF链接")
#                     continue
                
#                 # 确保URL完整
#                 if download_url.startswith('//'):
#                     download_url = 'https:' + download_url
#                 elif not download_url.startswith('http'):
#                     download_url = current_domain.rstrip('/') + '/' + download_url.lstrip('/')
                
#                 logger.info(f"找到PDF链接: {download_url}")
#                 # 更新当前域名（成功时）
#                 self.current_domain = current_domain
#                 return {
#                     'pdf_url': download_url,
#                     'source': 'scihub'
#                 }
                
#             except requests.exceptions.RequestException as e:
#                 logger.warning(f"请求错误 (尝试 {attempt + 1}/{max_retries}, 域名: {current_domain}): {e}")
#                 if attempt < max_retries - 1:
#                     time.sleep(2)
#             except Exception as e:
#                 logger.error(f"处理时出错: {e}")
#                 if attempt < max_retries - 1:
#                     time.sleep(2)
        
#         logger.error(f"经过{max_retries}次尝试后仍无法获取PDF链接: {doi}")
#         return None
    
#     def _extract_pdf_url(self, html_content: str, base_url: str) -> Optional[str]:
#         """
#         从SciHub页面HTML中提取PDF下载链接（参考用户提供的代码，使用多种方法）
#         :param html_content: HTML内容
#         :param base_url: 基础URL
#         :return: PDF URL或None
#         """
#         try:
#             soup = BeautifulSoup(html_content, "html.parser")
#             pdf_url = None
            
#             # 方法1: 查找iframe中的PDF（最常见的方式）
#             iframe = soup.find('iframe')
#             if iframe and 'src' in iframe.attrs:
#                 pdf_url = iframe['src']
#                 if pdf_url.startswith('//'):
#                     pdf_url = 'https:' + pdf_url
#                 elif pdf_url.startswith('/'):
#                     pdf_url = base_url.rstrip('/') + pdf_url
#                 elif not pdf_url.startswith('http'):
#                     pdf_url = base_url.rstrip('/') + '/' + pdf_url.lstrip('/')
#                 logger.debug(f"从iframe中找到PDF链接: {pdf_url}")
#                 return pdf_url
            
#             # 方法2: 查找embed标签
#             embed = soup.find('embed')
#             if embed and 'src' in embed.attrs:
#                 pdf_url = embed['src']
#                 if pdf_url.startswith('//'):
#                     pdf_url = 'https:' + pdf_url
#                 elif pdf_url.startswith('/'):
#                     pdf_url = base_url.rstrip('/') + pdf_url
#                 elif not pdf_url.startswith('http'):
#                     pdf_url = base_url.rstrip('/') + '/' + pdf_url.lstrip('/')
#                 logger.debug(f"从embed中找到PDF链接: {pdf_url}")
#                 return pdf_url
            
#             # 方法3: 查找PDF按钮或链接（通过onclick事件）
#             if not pdf_url:
#                 pdf_button = soup.find('button', onclick=re.compile(r'location\.href'))
#                 if pdf_button:
#                     match = re.search(r"location\.href=['\"]([^'\"]+)['\"]", pdf_button.get('onclick', ''))
#                     if match:
#                         pdf_url = match.group(1)
#                         if pdf_url.startswith('//'):
#                             pdf_url = 'https:' + pdf_url
#                         elif not pdf_url.startswith('http'):
#                             pdf_url = base_url.rstrip('/') + '/' + pdf_url.lstrip('/')
#                         logger.debug(f"从button onclick中找到PDF链接: {pdf_url}")
#                         return pdf_url
            
#             # 方法4: 查找所有可能的PDF链接
#             if not pdf_url:
#                 for link in soup.find_all('a', href=True):
#                     href = link['href']
#                     if href.endswith('.pdf') or 'pdf' in href.lower():
#                         pdf_url = href
#                         if pdf_url.startswith('//'):
#                             pdf_url = 'https:' + pdf_url
#                         elif not pdf_url.startswith('http'):
#                             pdf_url = base_url.rstrip('/') + '/' + pdf_url.lstrip('/')
#                         logger.debug(f"从链接中找到PDF链接: {pdf_url}")
#                         return pdf_url
            
#             # 方法5: 查找id为"pdf"的元素
#             pdf_element = soup.find(id='pdf')
#             if pdf_element and pdf_element.get('src'):
#                 pdf_url = pdf_element['src']
#                 if pdf_url.startswith('//'):
#                     pdf_url = 'https:' + pdf_url
#                 elif not pdf_url.startswith('http'):
#                     pdf_url = base_url.rstrip('/') + '/' + pdf_url.lstrip('/')
#                 logger.debug(f"从id=pdf元素中找到PDF链接: {pdf_url}")
#                 return pdf_url
            
#             logger.warning("未在SciHub页面中找到PDF链接")
#             return None
            
#         except Exception as e:
#             logger.error(f"解析HTML时出错：{e}")
#             return None
    
#     def download_by_doi(
#         self,
#         doi: str,
#         year: Optional[str] = None,
#         title: Optional[str] = None,
#         max_retries: int = 1
#     ) -> Optional[str]:
#         """
#         根据DOI从SciHub下载PDF
#         :param doi: 文献DOI
#         :param year: 年份（可选）
#         :param title: 标题（可选）
#         :param max_retries: 最大重试次数
#         :return: 下载的文件路径或None
#         """
#         if not doi or not isinstance(doi, str):
#             logger.error(f"无效的DOI：{doi}")
#             return None
        
#         # 清理DOI
#         from pdf_utils import PDFUtils
#         clean_doi = PDFUtils.clean_doi(doi)
#         logger.info(f"开始处理DOI: {clean_doi}")
        
#         # 生成安全的文件名
#         filename = PDFUtils.generate_filename(clean_doi, year, "scihub")
#         save_path = self.save_dir / filename
        
#         # 跳过已存在的文件
#         if save_path.exists():
#             logger.info(f"文件已存在，跳过下载：{filename}")
#             return str(save_path)
        
#         download_url = None
#         last_error = None
#         tried_domains = []  # 记录已尝试的域名
        
#         # 尝试下载
#         for attempt in range(max_retries):
#             # 如果重试，尝试切换域名
#             if attempt > 0:
#                 logger.info(f"第 {attempt + 1} 次尝试，切换域名...")
            
#             # 获取可用的域名（排除已尝试的）
#             current_domain = self.get_available_scihub_domain(exclude_domains=tried_domains)
#             if current_domain is None:
#                 logger.error("无法获取可用的Sci-Hub域名")
#                 break
            
#             # 记录当前尝试的域名
#             tried_domains.append(current_domain)
#             self.current_domain = current_domain
            
#             try:
#                 # 构造SciHub URL
#                 scihub_url = f"{current_domain.rstrip('/')}/{clean_doi}"
#                 logger.info(f"尝试从Sci-Hub下载: {scihub_url} (域名: {current_domain})")
                
#                 # 发送请求获取页面
#                 response = requests.get(
#                     scihub_url,
#                     headers=self.headers,
#                     timeout=self.timeout,
#                     allow_redirects=True,
#                     proxies=self.proxies
#                 )
#                 response.raise_for_status()
                
#                 # 提取PDF链接
#                 download_url = self._extract_pdf_url(response.text, current_domain)
#                 if not download_url:
#                     last_error = "未找到PDF链接"
#                     logger.warning(f"未在Sci-Hub页面中找到PDF链接")
#                     continue
                
#                 # 确保URL完整
#                 if download_url.startswith('//'):
#                     download_url = 'https:' + download_url
#                 elif not download_url.startswith('http'):
#                     download_url = current_domain.rstrip('/') + '/' + download_url.lstrip('/')
                
#                 logger.info(f"找到PDF链接: {download_url}")
                
#                 # 下载PDF文件
#                 logger.info(f"开始下载PDF: {filename}")
#                 pdf_response = requests.get(
#                     download_url,
#                     headers=self.headers,
#                     timeout=self.timeout,
#                     stream=True,
#                     allow_redirects=True,
#                     proxies=self.proxies
#                 )
#                 pdf_response.raise_for_status()
                
#                 # 检查响应内容是否为PDF
#                 content_type = pdf_response.headers.get("Content-Type", "").lower()
#                 first_bytes = b""
#                 if pdf_response.content:
#                     first_bytes = pdf_response.content[:4]
                
#                 if "pdf" not in content_type and first_bytes != b"%PDF":
#                     last_error = "下载的内容不是PDF文件"
#                     logger.warning(f"下载的内容不是PDF文件 (Content-Type: {content_type})")
#                     continue
                
#                 # 保存文件
#                 with open(save_path, 'wb') as f:
#                     for chunk in pdf_response.iter_content(chunk_size=8192):
#                         if chunk:
#                             f.write(chunk)
                
#                 # 验证文件大小（防止下载到错误页面）
#                 file_size = save_path.stat().st_size
#                 if file_size < 1024:  # 小于1KB可能是错误页面
#                     save_path.unlink()
#                     last_error = "下载的文件太小，可能是错误页面"
#                     logger.warning(f"下载的文件太小 ({file_size} bytes)，可能是错误页面")
#                     continue
                
#                 logger.info(f"文献已成功下载: {save_path} ({file_size/1024/1024:.2f} MB)")
#                 time.sleep(self.delay)
#                 return str(save_path)
                
#             except requests.exceptions.Timeout:
#                 last_error = "请求超时"
#                 logger.warning(f"请求超时 (尝试 {attempt + 1}/{max_retries})")
#             except requests.exceptions.ConnectionError:
#                 last_error = "连接错误"
#                 logger.warning(f"连接错误 (尝试 {attempt + 1}/{max_retries})")
#             except requests.exceptions.RequestException as e:
#                 last_error = f"请求错误: {str(e)}"
#                 logger.warning(f"请求错误 (尝试 {attempt + 1}/{max_retries}): {e}")
#             except Exception as e:
#                 last_error = f"未知错误: {str(e)}"
#                 logger.error(f"处理PDF下载时出错: {e}")
            
#             if attempt < max_retries - 1:
#                 time.sleep(2)  # 等待后重试
        
#         logger.error(f"经过{max_retries}次尝试后仍无法下载DOI: {clean_doi}，最后错误: {last_error}")
#         return None
    
#     def batch_download(self, doi_list: list, save_dir: Optional[str] = None):
#         """
#         批量下载PDF（参考用户提供的代码）
#         :param doi_list: DOI列表
#         :param save_dir: 保存目录（可选，覆盖默认目录）
#         :return: 下载结果列表
#         """
#         if save_dir:
#             self.save_dir = Path(save_dir)
#             self.save_dir.mkdir(parents=True, exist_ok=True)
        
#         results = []
#         logger.info(f"开始从SciHub批量下载 {len(doi_list)} 个PDF...")
        
#         for idx, doi in enumerate(doi_list, 1):
#             logger.info(f"处理第 {idx}/{len(doi_list)} 个文献: {doi}")
#             filepath = self.download_by_doi(doi)
#             results.append({
#                 'doi': doi,
#                 'success': filepath is not None,
#                 'filepath': filepath
#             })
#             time.sleep(1)  # 避免请求过快
        
#         # 打印结果统计
#         success_count = sum(1 for r in results if r['success'])
#         fail_count = len(results) - success_count
#         logger.info(f"批量下载完成: {success_count}/{len(doi_list)} 成功")
#         print(f"\n===== SciHub下载完成 =====")
#         print(f"成功下载：{success_count} 个PDF")
#         print(f"下载失败：{fail_count} 个PDF")
#         print(f"PDF文件保存目录：{self.save_dir.absolute()}")
        
#         return results


# if __name__ == "__main__":
#     """
#     简单的命令行入口：
#     - 从用户输入或命令行参数读取一个或多个 DOI；
#     - 使用 SciHubDownloader 独立下载 PDF；
#     - 不依赖项目中其它模块（如 NonOADownloader / ArticleProcessor）。
#     用法示例（在项目根目录运行）：
#         python scihub_downloader.py 10.1000/xyz 10.1001/abc
#     或直接运行后按提示粘贴 DOI 列表。
#     """
#     import sys

#     logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

#     # 收集 DOI 列表：优先从命令行参数读取，否则从标准输入读取换行分隔的 DOI
#     cli_dois: List[str] = [arg for arg in sys.argv[1:] if arg.strip()]
#     if not cli_dois:
#         print("请输入要从 Sci-Hub 下载的 DOI（每行一个），输入空行结束：")
#         lines: List[str] = []
#         while True:
#             try:
#                 line = input().strip()
#             except EOFError:
#                 break
#             if not line:
#                 break
#             lines.append(line)
#         cli_dois = lines

#     if not cli_dois:
#         print("未提供任何 DOI，程序结束。")
#         sys.exit(0)

#     downloader = SciHubDownloader()
#     downloader.batch_download(cli_dois)

