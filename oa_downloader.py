"""
OA（开放获取）文献分类型批量下载模块
采用两种下载策略（一、直接下载； 二、uc下载）
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
from utils import resolve_redirect, generate_filename, _case_insensitive_xpath, _case_insensitive_button_xpath

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, WebDriverException

import undetected_chromedriver as uc

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


class OADownloader:
    """OA文献下载器"""
    
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
        download_dir: str = "literature_pdfs/oa",
        email: str = "your_email@example.com",
        timeout: int = 60,
        delay: float = 1.0,
        selenium_headless: bool = True,
    ):
        """
        初始化OA下载器
        :param download_dir: PDF保存目录
        :param email: 邮箱地址（用于API调用）
        :param timeout: 下载超时时间（秒）
        :param delay: 每次请求之间的延迟（秒），遵守robots.txt规则（≥1秒/次）
        :param selenium_headless: Selenium是否使用无头模式
        """

        self.download_dir = Path(download_dir)
        self.download_dir.mkdir(parents=True, exist_ok=True)

        self.email = email
        self.timeout = timeout
        self.delay = delay

        self.selenium_headless = selenium_headless

        logger.info("使用 undetected-chromedriver 初始化 Chrome")
        # 初始化浏览器
        # 1、配置Chrome浏览器选项
        chrome_options = uc.ChromeOptions()  # 使用uc时
        # chrome_options = Options()  # 使用标准selenium
        chrome_options.add_argument("--headless")
        chrome_options.add_argument("--disable-gpu")
        chrome_options.add_argument("--no-sandbox")
        chrome_options.add_argument("--disable-dev-shm-usage")
        chrome_options.add_argument("--lang=en-US")
        chrome_options.add_argument("--disable-blink-features=AutomationControlled")
        # chrome_options.add_experimental_option("useAutomationExtension", False)

        # 创建临时下载目录
        self.temp_download_dir = self.download_dir / "temp_downloads"
        self.temp_download_dir.mkdir(parents=True, exist_ok=True)
        download_path = str(self.temp_download_dir.absolute())
        prefs = {
            "download.default_directory": download_path,
            "download.prompt_for_download": False,
            "plugins.always_open_pdf_externally": True
        }
        chrome_options.add_experimental_option("prefs", prefs)

        driver_path = "C:/Users/laptop/AppData/Roaming/undetected_chromedriver/undetected_chromedriver.exe"
        self.driver = uc.Chrome(
            driver_executable_path=driver_path,
            options=chrome_options,
            use_subprocess=True,
            delay_execution=True,  # 延迟启动，绕过快速检测
            suppress_welcome=True
        )
        
        
        # 记录在本次运行中「已确认难以自动下载」的 OA 出版商站点，后续直接跳过以提升整体速度
        self.failed_oa_hosts = set()
    
    
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
            headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,application/pdf,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
            "Accept-Encoding": "gzip, deflate, br",
            "Connection": "keep-alive",
        }
            
            # 为特定网站添加Referer头
            # if 'nature.com' in domain:
            #     # Nature网站需要从官网跳转的Referer
            #     headers['Referer'] = "https://www.nature.com/"
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
            #         headers['Referer'] = article_url
            #         logger.debug(f"为bioRxiv/medRxiv添加Referer头: {article_url}")
            
            # 延迟请求，模拟真人操作
            time.sleep(delay)
            
            # 使用requests.get()进行流式下载
            response = requests.get(
                pdf_url,
                headers=headers,
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

    
    def _download_with_selenium(
        self,
        url: str,
        doi: Optional[str] = None,
        year: Optional[str] = None,
        title: Optional[str] = None,
        source: str = "oa_selenium"
    ) -> Optional[str]:
        """
        使用undetected-chromedriver模拟浏览器来下载PDF
        :param url: HTML页面或PDF预览页或其他
        :param doi: 文献DOI
        :param year: 年份
        :param title: 标题
        :param source: 来源标识（用于生成文件名）
        :return: 下载成功或失败
        # :return: 下载的文件路径或None 
        """
        if url is None:
            return None
        # 创建临时下载目录
        temp_download_dir = self.download_dir / "temp_downloads"
        temp_download_dir.mkdir(parents=True, exist_ok=True)

        # 使用PDFUtils生成文件名，确保一致性
        filename = generate_filename(doi, year, source)

        # 确定保存目录
        if source:
            save_dir = self.download_dir / source
        else:
            save_dir = self.download_dir
        save_dir.mkdir(parents=True, exist_ok=True)

        target_path = save_dir / filename
        
        # 如果文件已存在，直接返回
        if target_path.exists():
            logger.info(f"文件已存在，跳过下载: {filename}")
            return str(target_path)
        

        # 访问目标 URL（会在当前标签页加载，不会打开新标签页）
        self.driver.get(url)

        # 等待页面加载
        time.sleep(3)

        # 检查并处理Cloudflare验证
        cloudflare_passed = self._check_cloudflare_verification(self.driver, max_wait=15)
        if cloudflare_passed:
            logger.info("Cloudflare验证已通过，开始PDF下载处理...")
        else:
            logger.warning("Cloudflare验证可能未完全通过，继续尝试下载...")

        # 检查并处理cookie弹窗
        cookie_handled = self._handle_cookie_banner(self.driver, max_wait=10)
        if cookie_handled:
            logger.info("Cookie弹窗已处理")
        else:
            logger.warning("Cookie弹窗可能未完全处理，继续尝试下载...")

        # 检查当前URL是否是PDF文件
        current_url = self.driver.current_url
        # 如果是PDF链接，直接等待下载
        if current_url.lower().endswith('.pdf') or 'pdf' in current_url.lower():
            logger.info("当前页面已经是PDF文件，等待下载...")
        # 如果不是
        else:
            logger.info("当前页面可能不是PDF，尝试查找PDF下载按钮或链接...")
            # 尝试1：优先尝试查找并点击PDF下载按钮（针对Wiley等需要点击的页面）
            download_button = self._find_download_button(self.driver)
            if download_button:
                logger.info("找到PDF下载按钮，准备点击...")
                try:
                    # 滚动到按钮位置，确保可见
                    self.driver.execute_script(
                        "arguments[0].scrollIntoView({behavior: 'smooth', block: 'center'});",
                        download_button,
                    )
                    time.sleep(0.5)
                    # 普通点击
                    download_button.click()
                    logger.info("已点击PDF下载按钮（普通点击）")
                    time.sleep(2)  # 等待页面响应

                    # 检查普通点击后是否跳转到PDF页面或触发下载
                    new_url = self.driver.current_url
                    if new_url != current_url:
                        logger.info(f"点击后URL已变化: {new_url}")
                        current_url = new_url

                    # 如果跳转到PDF页面，继续等待下载
                    if current_url.lower().endswith('.pdf') or '/pdf' in current_url.lower():
                        logger.info("已跳转到PDF页面，等待下载...")

                except Exception as e:
                        logger.warning(f"点击PDF下载按钮失败: {e}")
                
            # 方法2：如果没找到按钮，尝试查找PDF链接
            if not current_url.lower().endswith('.pdf'):
                pdf_link = self._find_pdf_link_in_page(self.driver, current_url, check_cloudflare=False)
                if pdf_link:
                    logger.info(f"找到PDF链接，访问: {pdf_link}")
                    self.driver.get(pdf_link)
                    time.sleep(3)
                    # 再次检查Cloudflare（如果新页面也有验证）
                    self._check_cloudflare_verification(self.driver, max_wait=10)
                    current_url = self.driver.current_url
        logger.info(f"直接获得或尝试后获得当前URL: {self.driver.current_url}")
        downloaded_file = self._wait_for_download_complete(timeout=self.wait_time)
        if downloaded_file:
            # 移动文件到目标位置
            if self._move_downloaded_file(downloaded_file, target_path):
                # 验证文件
                if target_path.exists() and target_path.stat().st_size > 1024:
                    # 验证是否为PDF
                    with open(target_path, 'rb') as f:
                        header = f.read(4)
                        if header == b"%PDF":
                            logger.info(f"Selenium下载成功: {target_path} ({target_path.stat().st_size/1024/1024:.2f} MB)")
                            return str(target_path)
                        else:
                            logger.warning(f"下载的文件不是PDF格式")
                            target_path.unlink()
                            return None
            else:
                logger.error("移动下载文件失败")
                return None
        else:
            logger.warning("未检测到下载文件，可能下载失败或页面需要人工操作")
            return None
        
        return None
            
    
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
        
        pdf_url = oa_info.get('url')
        source = (oa_info.get('source') or '').lower()

        filename = generate_filename(doi, year, f"{source}_oa" if source else "oa")
        save_path = self.save_dir / filename

        # 跳过已存在的文件
        if save_path.exists():
            logger.info(f"文件已存在，跳过下载: {filename}")
            return str(save_path)
        
        # 如果 OA 检查结果中给出的 URL 所属站点，已经在本次运行中多次失败，则直接跳过该文献
        first_host_key = self._match_skip_host(pdf_url)
        if first_host_key and first_host_key in self.failed_oa_hosts:
            logger.warning(
                f"【OA下载】检测到站点 {first_host_key} 之前已多次下载失败，"
                f"当前 DOI {doi} 将直接跳过以提升整体速度"
            )
            return None

        # 1) 如果 OA 检查结果里已经有 URL，优先使用并尝试直接下载
        if pdf_url:
            logger.info(f"【OA下载】检测到OA检查结果中的URL，尝试直接下载: {pdf_url}")
            try:
                # 直接流式下载
                if self.download_pdf_direct(pdf_url, save_path, timeout=self.timeout, delay=self.delay):
                    logger.info("【OA下载】直接流式下载成功")
                    return str(save_path)
            except Exception as e:
                logger.error(f"【OA下载】直接流式下载失败，将继续其它策略: {e}")

        # 2) 使用 utils中的resolve_redirect
        final_url: Optional[str] = None
        try:
            final_url = resolve_redirect(doi, source)
            if final_url:
                logger.info(f"【OA下载】ArticleProcessor重定向处理成功，最终链接: {final_url}")
        except Exception as e:
            logger.error(f"【OA下载】通过 ArticleProcessor重定向失败: {e}")
            final_url = pdf_url

            
        # 3) 使用uc基于url来提取PDF
        try:
            logger.info(f"【OA下载】尝试使用uc进行下载: {final_url}")
            result = self._download_with_selenium(final_url, doi, year, title, source)
            if result:
                return str(result)
        except TimeoutException as e:
            logger.error(f"页面加载超时（{self.timeout}秒）: {e}")
            return None
        except WebDriverException as e:
            logger.error(f"浏览器操作出错: {e}")
            return None
        except Exception as e:
            logger.error(f"uc下载PDF时出错: {e}")
            return None
        finally:
            pass

        # 到这里说明该 DOI 在当前出版商站点上的 OA 自动下载已失败；
        # 若属于配置的“高成本站点”，则在本次运行中将该站点加入跳过列表
        # if final_host_key:
        #     self.failed_oa_hosts.add(final_host_key)
        #     logger.warning(
        #         f"【OA下载】站点 {final_host_key} 的 OA 自动下载失败，"
        #         f"本次运行后续将跳过该站点上的 OA 文献（仅跳过 OA 通道，不影响其它下载层级）"
        #     )
        return None


    def _check_cloudflare_verification(self, driver: webdriver.Chrome, max_wait: int = 15) -> bool:
        """
        检查并处理Cloudflare验证页面
        参考用户提供的代码，使用更精确的选择器和WebDriverWait
        :param driver: WebDriver实例
        :param max_wait: 最大等待时间（秒，默认15秒，已优化为更短的等待时间）
        :return: 是否成功通过验证
        """
        try:
            # 检查是否在Cloudflare验证页面
            cloudflare_indicators = [
                "cloudflare",
                "checking your browser",
                "请完成以下操作",
                "验证您是真人",
                "确认您是真人",
                "Just a moment",
                "DDoS protection by Cloudflare"
            ]
            
            page_text = driver.page_source.lower()
            page_title = driver.title.lower()
            current_url = driver.current_url.lower()
            
            is_cloudflare = any(indicator in page_text or indicator in page_title or indicator in current_url 
                                for indicator in cloudflare_indicators)
            
            if not is_cloudflare:
                return True  # 不在Cloudflare验证页面
            
            logger.info("检测到Cloudflare验证页面，等待验证元素加载...")
            
            # 使用WebDriverWait等待验证复选框出现并点击
            # 按优先级尝试多个选择器（减少等待时间以提高速度）
            checkbox_selectors = [
                "//input[@type='checkbox' and @aria-label='确认您是真人']",  # 中文验证框
                "//input[@type='checkbox' and @aria-label='Confirm you are human']",  # 英文验证框
                "//input[@type='checkbox' and contains(@aria-label, '确认')]",  # 包含"确认"的验证框
                "//input[@type='checkbox' and contains(@aria-label, 'Confirm')]",  # 包含"Confirm"的验证框
                "//input[@type='checkbox' and @id='challenge-form-checkbox']",  # 通过ID定位
                "//input[@type='checkbox']",  # 通用复选框（最后尝试）
            ]
            
            clicked = False
            checkbox_wait_time = 5  # 减少等待复选框的时间（从10秒减到5秒）
            for selector in checkbox_selectors:
                try:
                    logger.debug(f"尝试使用选择器: {selector}")
                    # 使用WebDriverWait等待元素可点击（缩短等待时间）
                    verify_checkbox = WebDriverWait(driver, checkbox_wait_time).until(
                        EC.element_to_be_clickable((By.XPATH, selector))
                    )
                    # 使用普通click（而不是JavaScript click），更接近真人行为
                    verify_checkbox.click()
                    logger.info("已点击Cloudflare验证复选框")
                    clicked = True
                    time.sleep(1)
                    break
                except TimeoutException:
                    logger.debug(f"选择器 {selector} 未找到元素，尝试下一个")
                    continue
                except Exception as e:
                    logger.debug(f"使用选择器 {selector} 时出错: {e}")
                    continue
            
            if not clicked:
                logger.warning("未找到可点击的验证复选框，可能验证页面结构已变化或验证会自动通过")
                # 继续等待，可能验证会自动通过
            
            # 等待验证通过（通过页面标题变化或URL变化来判断）
            logger.info("等待Cloudflare验证通过...")
            try:
                # 等待页面标题变化（不再包含验证相关文本）或URL变化
                # 对于PDF页面，标题可能包含"PDF"或页面URL包含"pdf"
                # 使用轮询间隔，每0.5秒检查一次，而不是默认的0.5秒
                WebDriverWait(driver, max_wait, poll_frequency=0.5).until(
                    lambda d: self._is_verification_passed(d, cloudflare_indicators)
                )
                logger.info("Cloudflare验证已通过，页面已跳转")
                time.sleep(1)
                return True
            except TimeoutException:
                logger.warning(f"Cloudflare验证等待超时（{max_wait}秒）")
                # 最后检查一次是否还在验证页面
                if not self._is_verification_page(driver, cloudflare_indicators):
                    logger.info("验证可能已通过（页面已变化）")
                    return True
                return False
            
        except Exception as e:
            logger.warning(f"检查Cloudflare验证时出错: {e}")
            return True  # 假设验证通过，继续执行
        


    def _handle_cookie_banner(self, driver: webdriver.Chrome, max_wait: int = 10) -> bool:
        """
        检测并处理cookie同意弹窗
        针对Elsevier、Springer等常见出版商的cookie弹窗进行优化。
        为避免长时间卡在“检测到cookie弹窗，尝试自动处理...”阶段，这里增加整体超时控制，
        并缩短单个选择器的等待时间，保证总耗时不超过 max_wait 秒。
        :param driver: WebDriver实例
        :param max_wait: 最大等待时间（秒）
        :return: 是否成功处理cookie弹窗
        """
        try:
            start_time = time.time()
            # 简短等待页面渲染出弹窗元素
            try:
                WebDriverWait(driver, min(5, max_wait)).until(
                    EC.presence_of_element_located((By.TAG_NAME, "body"))
                )
            except Exception:
                pass

            # 检查是否存在cookie弹窗
            cookie_indicators = [
                "cookie",
                "cookies",
                "我们使用cookies",
                "我们使用cookie",
                "we use cookies",
                "we use cookie",
                "接受Cookies",
                "接受Cookie",
                "全部接受",
                "Accept Cookies",
                "Accept Cookie",
                "Accept All",
                "accept all",
                "Cookie设置",
                "Cookie Settings",
                "Cookie通知",
                "Cookie Notice",
                "同意",
                "Accept",
                "同意Cookies"
            ]
            
            page_text = driver.page_source
            page_text_lower = page_text.lower()
            
            # 检查页面是否包含cookie相关内容
            has_cookie_banner = any(indicator.lower() in page_text_lower for indicator in cookie_indicators)
            
            if not has_cookie_banner:
                logger.debug("未检测到cookie弹窗")
                return True  # 没有cookie弹窗，认为已处理
            
            logger.info("检测到cookie弹窗，尝试自动处理...")
            
            # 多种选择器策略查找"接受Cookies"或"全部接受"按钮（按优先级排序）
            accept_button_selectors = [
                # 高优先级中文
                (By.XPATH, "//button[contains(text(), '全部接受')]"),
                (By.XPATH, _case_insensitive_button_xpath(['全部', '接受'], require_all=True)),

                # 高优先级英文
                (By.XPATH, "//button[contains(text(), 'Accept All')]"),
                (By.XPATH, _case_insensitive_button_xpath(['accept', 'all'], require_all=True)),

                # 常见文本模式
                (By.XPATH, "//button[" + _case_insensitive_xpath('accept') + "]"),
                (By.XPATH, "//button[" + _case_insensitive_xpath('同意') + "]"),

                # 通过类名和ID（常见模式）
                (By.CSS_SELECTOR, "button[class*='accept-all'], button[class*='acceptAll']"),
                (By.CSS_SELECTOR, "button[id*='accept-all'], button[id*='acceptAll']"),

                # Cookie弹窗内的按钮
                (By.XPATH, "//div[contains(@class, 'cookie')]//button[" + _case_insensitive_xpath('accept') + "]"),
                (By.XPATH, "//div[contains(@class, 'cookie-banner')]//button"),
            ]
            
            clicked = False
            for by, selector in accept_button_selectors:
                # 整体耗时超过 max_wait 时直接放弃进一步尝试，避免长时间阻塞下载流程
                elapsed = time.time() - start_time
                if elapsed >= max_wait:
                    logger.warning(
                        "处理cookie弹窗已耗时 %.1f 秒，停止进一步尝试，继续后续下载流程", elapsed
                    )
                    break

                try:
                    logger.debug(f"尝试使用选择器查找接受Cookies按钮: {selector}")
                    # 每个选择器最多等待 2 秒，且不超过剩余时间
                    remaining = max(0.5, max_wait - elapsed)
                    per_selector_timeout = min(2, remaining)
                    accept_button = WebDriverWait(driver, per_selector_timeout).until(
                        EC.element_to_be_clickable((by, selector))
                    )
                    
                    # 检查元素是否可见
                    if accept_button.is_displayed():
                        # 滚动到按钮位置，确保可见
                        driver.execute_script("arguments[0].scrollIntoView({behavior: 'smooth', block: 'center'});", accept_button)
                        time.sleep(0.5)
                        
                        # 尝试点击按钮
                        try:
                            accept_button.click()
                            logger.info("已点击接受Cookies按钮（普通点击）")
                            clicked = True
                            time.sleep(1)  # 等待弹窗消失
                            break
                        except Exception as e:
                            logger.debug(f"普通点击失败: {e}，尝试JavaScript点击")
                            # 使用JavaScript点击
                            try:
                                driver.execute_script("arguments[0].click();", accept_button)
                                logger.info("已点击接受Cookies按钮（JavaScript点击）")
                                clicked = True
                                time.sleep(1)
                                break
                            except Exception as js_e:
                                logger.debug(f"JavaScript点击也失败: {js_e}")
                                continue
                except TimeoutException:
                    logger.debug(f"选择器 {selector} 未找到元素，尝试下一个")
                    continue
                except Exception as e:
                    logger.debug(f"使用选择器 {selector} 时出错: {e}")
                    continue
            
            if clicked:
                # 验证cookie弹窗是否已关闭
                time.sleep(0.5)
                # 再次检查页面，确认弹窗是否消失
                try:
                    _ = driver.page_source
                    logger.info("Cookie弹窗处理完成")
                    return True
                except Exception:
                    return True
            else:
                logger.warning("未找到可点击的接受Cookies按钮，可能cookie弹窗结构已变化或无需显式同意")
                # 不再做额外复杂尝试，避免长时间阻塞，直接返回 False 让后续逻辑继续
                return False
            
        except Exception as e:
            logger.warning(f"处理cookie弹窗时出错: {e}")
            return False  # 出错时返回False，但继续执行后续流程
        

    def _find_download_button(self, driver: webdriver.Chrome) -> Optional[object]:
        """
        在页面中查找Download PDF按钮
        针对Wiley、Springer、Elsevier等常见出版商优化
        :param driver: WebDriver实例
        :return: 按钮元素或None
        """
        try:
            # 等待页面加载
            WebDriverWait(driver, 10).until(
                EC.presence_of_element_located((By.TAG_NAME, "body"))
            )
            
            # 多种选择器策略查找下载按钮（按优先级排序）
            button_selectors = [
                # 高优先级：aria-label和title
                (By.XPATH, "//a[contains(@aria-label, 'PDF') or contains(@title, 'PDF')]"),
                (By.XPATH, "//button[contains(@aria-label, 'PDF') or contains(@title, 'PDF')]"),

                # 通过类名和href（合并重复）
                (By.CSS_SELECTOR, "a[href*='.pdf'], a[href*='/pdf'], a[href*='/epdf']"),
                (By.CSS_SELECTOR, "a[class*='pdf'], a[class*='PDF'], a[download]"),

                # 文本内容（使用辅助函数）
                (By.XPATH, "//a[" + _case_insensitive_xpath('pdf') + "]"),
                (By.XPATH, "//button[" + _case_insensitive_xpath('download') + "]"),

                # 通过ID
                (By.CSS_SELECTOR, "#download-pdf, #pdf-download, #pdf"),
            ]
            
            for by, selector in button_selectors:
                try:
                    elements = driver.find_elements(by, selector)
                    for element in elements:
                        try:
                            # 检查元素是否可见和可点击
                            if element.is_displayed() and element.is_enabled():
                                # 获取元素的文本或属性，用于日志
                                element_text = element.text or element.get_attribute('aria-label') or element.get_attribute('title') or ''
                                element_href = element.get_attribute('href') or ''
                                logger.info(f"找到PDF下载按钮: {selector}, 文本: {element_text[:50]}, href: {element_href[:100]}")
                                return element
                        except Exception as e:
                            logger.debug(f"检查元素时出错: {e}")
                            continue
                except Exception as e:
                    logger.debug(f"选择器 {selector} 未找到元素: {e}")
                    continue
            
            logger.warning("未找到PDF下载按钮")
            return None
        except Exception as e:
            logger.warning(f"查找下载按钮时出错: {e}")
            return None
        

    def _wait_for_download_complete(self, timeout: int = 60) -> Optional[Path]:
        """
        等待下载完成
        改进版本：监控文件大小变化，确保下载完成
        :param timeout: 超时时间（秒）
        :return: 下载的文件路径，如果超时则返回None
        """
        start_time = time.time()
        last_file_count = 0
        last_file_size = 0
        stable_count = 0  # 文件大小稳定的次数
        
        logger.info(f"开始监控下载目录: {self.temp_download_dir}")
        
        while time.time() - start_time < timeout:
            # 检查临时下载目录中的所有文件（包括正在下载的）
            all_files = list(self.temp_download_dir.glob("*"))
            pdf_files = [f for f in all_files if f.is_file() and (f.name.endswith('.pdf') or f.name.endswith('.crdownload') or f.name.endswith('.tmp'))]
            
            if pdf_files:
                # 检查文件是否还在下载中（.crdownload或.tmp扩展名）
                completed_files = [f for f in pdf_files if not f.name.endswith('.crdownload') and not f.name.endswith('.tmp')]
                
                if completed_files:
                    # 返回最新的文件
                    latest_file = max(completed_files, key=lambda f: f.stat().st_mtime)
                    try:
                        current_size = latest_file.stat().st_size
                        
                        # 检查文件大小是否稳定（文件写入完成）
                        if current_size == last_file_size:
                            stable_count += 1
                            # 文件大小连续3次检查都稳定，且大于1KB，认为下载完成
                            if stable_count >= 3 and current_size > 1024:
                                logger.info(f"检测到下载完成的文件: {latest_file} ({current_size/1024/1024:.2f} MB)")
                                time.sleep(1)  # 额外等待确保文件写入完成
                                return latest_file
                        else:
                            # 文件大小还在变化，重置稳定计数
                            stable_count = 0
                            logger.debug(f"文件还在下载中: {latest_file.name}, 当前大小: {current_size/1024:.2f} KB")
                            last_file_size = current_size
                    except Exception as e:
                        logger.debug(f"检查文件大小时出错: {e}")
                else:
                    # 有文件正在下载中
                    downloading_files = [f for f in pdf_files if f.name.endswith('.crdownload') or f.name.endswith('.tmp')]
                    if downloading_files:
                        latest_downloading = max(downloading_files, key=lambda f: f.stat().st_mtime)
                        try:
                            current_size = latest_downloading.stat().st_size
                            if current_size != last_file_size:
                                logger.debug(f"文件正在下载: {latest_downloading.name}, 当前大小: {current_size/1024:.2f} KB")
                                last_file_size = current_size
                                stable_count = 0  # 重置稳定计数
                        except:
                            pass
            
            time.sleep(1)
        
        # 超时后，检查是否有任何PDF文件（即使可能还在下载）
        pdf_files = list(self.temp_download_dir.glob("*.pdf"))
        if pdf_files:
            completed_files = [f for f in pdf_files if not f.name.endswith('.crdownload') and not f.name.endswith('.tmp')]
            if completed_files:
                latest_file = max(completed_files, key=lambda f: f.stat().st_mtime)
                try:
                    file_size = latest_file.stat().st_size
                    if file_size > 1024:
                        logger.warning(f"等待超时，但找到可能的下载文件: {latest_file} ({file_size/1024/1024:.2f} MB)")
                        return latest_file
                except:
                    pass
        
        logger.warning(f"等待下载超时（{timeout}秒），未检测到下载文件")
        return None
    
    def _move_downloaded_file(self, temp_file: Path, target_path: Path) -> bool:
        """
        将下载的文件移动到目标位置
        :param temp_file: 临时文件路径
        :param target_path: 目标文件路径
        :return: 是否成功
        """
        try:
            # 确保目标目录存在
            target_path.parent.mkdir(parents=True, exist_ok=True)
            
            # 如果目标文件已存在，先删除
            if target_path.exists():
                target_path.unlink()
            
            # 移动文件
            shutil.move(str(temp_file), str(target_path))
            logger.info(f"文件已移动到: {target_path}")
            return True
        except Exception as e:
            logger.error(f"移动文件时出错: {e}")
            return False