# """
# 基于Selenium的PDF下载模块
# 使用真实的浏览器模拟来下载PDF，解决反爬虫限制
# 支持Cloudflare验证自动处理

# 重构后的模块，使用已有工具类，提供统一的下载接口
# """
# import os
# import re
# import subprocess
# import time
# import logging
# import shutil
# from pathlib import Path
# from typing import Optional, Dict
# from urllib.parse import urlparse

# # 减少 webdriver-manager 重复联网检查；驱动仍缓存在 ~/.wdm
# os.environ.setdefault("WDM_LOG_LEVEL", "0")
# from selenium import webdriver
# from selenium.webdriver.chrome.options import Options
# from selenium.webdriver.chrome.service import Service
# from selenium.webdriver.common.by import By
# from selenium.webdriver.common.keys import Keys
# from selenium.webdriver.support.ui import WebDriverWait
# from selenium.webdriver.support import expected_conditions as EC
# from selenium.common.exceptions import TimeoutException, WebDriverException

# # 导入已有工具类
# from pdf_utils import PDFUtils

# # 配置日志
# logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
# logger = logging.getLogger(__name__)


# # ========== XPath 辅助函数 ==========
# def _case_insensitive_xpath(keyword: str) -> str:
#     """生成不区分大小写的XPath contains表达式"""
#     return f"contains(translate(text(), 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), '{keyword.lower()}')"


# def _case_insensitive_button_xpath(keywords: list, require_all: bool = False) -> str:
#     """生成带有不区分大小写文本匹配的按钮XPath"""
#     from typing import List
#     if require_all:
#         conditions = " and ".join([_case_insensitive_xpath(kw) for kw in keywords])
#     else:
#         conditions = " or ".join([_case_insensitive_xpath(kw) for kw in keywords])
#     return f"//button[{conditions}]"


# # 尝试导入 undetected-chromedriver（用于绕过 Cloudflare 检测）
# try:
#     import undetected_chromedriver as uc
#     UC_AVAILABLE = True
#     logger.info("undetected-chromedriver 可用")
# except ImportError:
#     uc = None  # type: ignore[assignment]
#     UC_AVAILABLE = False
#     logger.warning("undetected-chromedriver 未安装，将仅使用标准 selenium；建议: pip install undetected-chromedriver")

# # 尝试导入 webdriver-manager（用于与本机 Chrome 版本匹配的 ChromeDriver，避免 session not created 版本错误）
# try:
#     from webdriver_manager.chrome import ChromeDriverManager
#     WDM_AVAILABLE = True
#     logger.info("webdriver-manager 可用，将使用其管理 ChromeDriver 版本")
# except ImportError:
#     ChromeDriverManager = None  # type: ignore[misc, assignment]
#     WDM_AVAILABLE = False
#     logger.warning("webdriver-manager 未安装，ChromeDriver 版本需与本地 Chrome 一致；建议: pip install webdriver-manager")


# def _find_chrome_binary() -> Optional[str]:
#     """在 Linux / Windows / macOS 上解析 Chrome/Chromium 可执行文件路径。"""
#     for name in (
#         "google-chrome",
#         "google-chrome-stable",
#         "chromium-browser",
#         "chromium",
#         "microsoft-edge",
#     ):
#         p = shutil.which(name)
#         if p:
#             return p
#     for path in (
#         r"C:\Program Files\Google\Chrome\Application\chrome.exe",
#         r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
#         "/usr/bin/google-chrome",
#         "/usr/bin/google-chrome-stable",
#         "/usr/bin/chromium-browser",
#         "/usr/bin/chromium",
#         "/snap/bin/chromium",
#     ):
#         if path and os.path.isfile(path) and os.access(path, os.X_OK):
#             return path
#     return None


# def _chrome_major_version(binary: Optional[str]) -> Optional[int]:
#     """从 `google-chrome --version` 解析主版本号，供 undetected_chromedriver 匹配驱动。"""
#     if not binary:
#         return None
#     try:
#         proc = subprocess.run(
#             [binary, "--version"],
#             capture_output=True,
#             text=True,
#             timeout=15,
#         )
#         text = (proc.stdout or "") + (proc.stderr or "")
#         m = re.search(r"(\d+)\.", text)
#         if m:
#             return int(m.group(1))
#     except Exception:
#         pass
#     return None


# def _install_chromedriver_via_wdm() -> Optional[str]:
#     """使用 webdriver-manager 安装/复用缓存中的 chromedriver，尽量延长校验周期减少重复下载。"""
#     if not WDM_AVAILABLE or ChromeDriverManager is None:
#         return None
#     try:
#         # webdriver-manager 4.x
#         path = ChromeDriverManager(driver_cache_valid_range=365).install()
#         return str(Path(path).resolve())
#     except TypeError:
#         try:
#             path = ChromeDriverManager(cache_valid_range=365).install()
#             return str(Path(path).resolve())
#         except Exception:
#             pass
#     except Exception as e:
#         logger.debug(f"ChromeDriverManager(长缓存) 失败: {e}")
#     try:
#         path = ChromeDriverManager().install()
#         return str(Path(path).resolve())
#     except Exception as e:
#         logger.warning(f"webdriver-manager 获取 ChromeDriver 失败: {e}")
#         return None


# class SeleniumDownloader:
#     """基于Selenium的PDF下载器（重构版）"""
    
#     def __init__(
#         self,
#         download_dir: str = "literature_pdfs",
#         timeout: int = 60,
#         headless: bool = True,
#         wait_time: int = 10,
#         use_undetected: bool = False,
#         auto_fallback: bool = True
#     ):
#         """
#         初始化Selenium下载器
#         :param download_dir: 下载目录
#         :param timeout: 页面加载超时时间（秒）
#         :param headless: 是否使用无头模式（不显示浏览器窗口）
#         :param wait_time: 等待下载完成的时间（秒）
#         :param use_undetected: 是否直接使用undetected-chromedriver（默认False，优先使用标准selenium）
#         :param auto_fallback: 是否在普通selenium失败时自动降级到undetected-chromedriver（默认True）
#         """
        
    
#     def _setup_chrome_options(self, force_standard: bool = False):
#         """
#         配置 Chrome 浏览器选项（参考 test.py）。
#         :param force_standard: 为 True 时强制使用标准 Options（用于 UC 失败后降级到标准 Selenium）
#         :return: Chrome 选项对象（可能是 Options 或 uc.ChromeOptions）
#         """
       

#         # 无头模式：标准 Selenium 与 undetected-chromedriver 均需显式添加，否则会弹出可见窗口
#         if self.headless:
#             chrome_options.add_argument("--headless=new")
    
#             chrome_options.add_argument("--disable-gpu")
#             # Ubuntu/SSH 无 DISPLAY 或 CI 环境下，UC 同样需要这些参数才能稳定运行
#             if use_uc:
                
#                 if os.name != "nt":
#                     chrome_options.add_argument("--disable-setuid-sandbox")
#                 # Windows 上部分 Chrome/UC 组合仍会短暂出现宿主窗口；移出屏幕作兜底（见 UC issue #2030 等）
#                 if os.name == "nt":
#                     chrome_options.add_argument("--window-position=-2400,-2400")
#                 logger.info("undetected-chromedriver 使用无头模式（不显示浏览器窗口）")
#             else:
#                 logger.info("标准 Selenium 使用无头模式（不显示浏览器窗口）")

#         # 防止打开空白标签页的配置（适用于 UC 和标准 Selenium）
#         chrome_options.add_argument("--no-first-run")
#         chrome_options.add_argument("--no-default-browser-check")
#         if use_uc:
#             # UC 特定配置：避免打开额外的空白标签页
#             chrome_options.add_argument("--disable-extensions")
#             chrome_options.add_argument("--disable-backgrounding-occluded-windows")
#             chrome_options.add_argument("--disable-renderer-backgrounding")
#             # 添加更多参数防止空白标签页
#             chrome_options.add_argument("--disable-new-tab-in-rendering-process")
#             chrome_options.add_argument("--disable-features=BlinkGenPropertyTrees")
#             chrome_options.add_experimental_option("useAutomationExtension", False)
#             # 禁用自动打开欢迎页面
#             chrome_options.add_experimental_option("prefs", {
#                 "profile.default_content_setting_values": {},
#                 "profile.managed_default_content_settings": {},
#             })

       

#         return chrome_options
    
#     def _init_driver(self) -> webdriver.Chrome:
#         """
#         初始化 Chrome 浏览器驱动（参考 test.py）。
#         - 使用 webdriver-manager 获取与本机 Chrome 版本匹配的 ChromeDriver，避免 session not created 版本错误。
#         - 若 use_undetected 且 UC 可用：优先用 undetected-chromedriver + 版本匹配的驱动；失败且 auto_fallback 时降级为标准 Selenium。
#         - 标准 Selenium 时：通过 ChromeDriverManager 或系统 PATH 中的 ChromeDriver 创建驱动。
#         :return: WebDriver 实例
#         """
#         if self.driver is not None:
#             return self.driver

#         chrome_options = self._setup_chrome_options()

#         # 标准 Selenium 使用的 chromedriver（长缓存，避免每次运行都联网拉驱动）
#         driver_path: Optional[str] = None

#         # 优先：使用 undetected-chromedriver（可绕过 Cloudflare 等检测）
#         # 注意：不要与 webdriver-manager 的 chromedriver 混用（易触发 patch 后 “Binary Location Must be a String” 等错误），
#         # 由 UC 自行下载并缓存与当前 Chrome 主版本匹配的驱动。
#         if self.use_undetected and UC_AVAILABLE:
#             logger.info("使用 undetected-chromedriver 初始化 Chrome（可绕过 Cloudflare 检测）")
#             try:
#                 chrome_bin = _find_chrome_binary()
#                 version_main = _chrome_major_version(chrome_bin)

#                 # 创建临时选项用于 UC 初始化（添加更多防止空白标签页的参数）
#                 uc_options = chrome_options

#                 uc_kwargs: Dict = {
#                     "options": uc_options,
#                     "use_subprocess": True,
#                     # 仅加 --headless 到 options 不够：UC 打补丁时常会忽略，必须在构造函数显式传入（否则 Windows 仍会弹出完整 Chrome）
#                     "headless": self.headless,
#                     "version_main": version_main if version_main else None,  # 指定 Chrome 主版本，避免 UC 下载驱动
#                 }
#                 if chrome_bin:
#                     uc_kwargs["browser_executable_path"] = str(chrome_bin)

#                 # 创建 UC driver
#                 self.driver = uc.Chrome(**uc_kwargs)
#                 self.driver.set_page_load_timeout(self.timeout)

#                 # 强制关闭所有空白标签页（更激进的方法）
#                 try:
#                     # 等待浏览器完全初始化
#                     time.sleep(1.5)

#                     # 获取所有标签页
#                     all_handles = self.driver.window_handles
#                     logger.debug(f"UC 初始化后的标签页数量: {len(all_handles)}, handles: {all_handles}")

#                     # 收集需要关闭的空白标签页
#                     blank_handles = []
#                     for handle in all_handles:
#                         try:
#                             self.driver.switch_to.window(handle)
#                             url = self.driver.current_url
#                             logger.debug(f"标签页 {handle}: URL={url}")

#                             # 检查是否是空白页面（放宽判断条件）
#                             if (url in ["about:blank", "data:,", "", "chrome://newtab/"] or
#                                 not url or
#                                 not url.strip() or
#                                 url.startswith("about:blank") or
#                                 url.startswith("data:,")):
#                                 blank_handles.append(handle)
#                                 logger.debug(f"标记为空白标签页: {handle} with URL: {url}")
#                         except Exception as e:
#                             logger.debug(f"检查标签页 {handle} 时出错: {e}")

#                     # 关闭所有空白标签页
#                     for handle in blank_handles:
#                         try:
#                             self.driver.switch_to.window(handle)
#                             self.driver.close()
#                             logger.debug(f"已关闭空白标签页: {handle}")
#                         except Exception as e:
#                             logger.debug(f"关闭标签页 {handle} 时出错: {e}")

#                     # 检查剩余标签页
#                     remaining_handles = self.driver.window_handles
#                     logger.debug(f"关闭空白标签页后剩余: {len(remaining_handles)} 个标签页")

#                     if len(remaining_handles) == 0:
#                         # 所有标签页都被关闭了，需要创建一个新的
#                         logger.debug("所有标签页已关闭，创建新标签页")
#                         self.driver.get("about:blank")
#                         time.sleep(0.5)
#                     elif len(remaining_handles) > 0:
#                         # 切换到第一个剩余标签页
#                         self.driver.switch_to.window(remaining_handles[0])
#                         logger.debug(f"切换到第一个剩余标签页: {remaining_handles[0]}, URL: {self.driver.current_url}")

#                 except Exception as e:
#                     logger.warning(f"处理空白标签页时出错（可忽略）: {e}")
#                     # 确保有一个可用的标签页
#                     try:
#                         handles = self.driver.window_handles
#                         if handles:
#                             self.driver.switch_to.window(handles[0])
#                     except:
#                         pass

#                 if not self.headless:
#                     try:
#                         self.driver.maximize_window()
#                     except Exception:
#                         pass
#                 logger.info("undetected-chromedriver 初始化成功")
#                 return self.driver
#             except Exception as e:
#                 logger.warning(f"undetected-chromedriver 初始化失败: {e}")
#                 if self.auto_fallback:
#                     logger.info("将自动降级为标准 Selenium Chrome（使用版本匹配的 ChromeDriver）")
#                     chrome_options = self._setup_chrome_options(force_standard=True)
#                 else:
#                     raise

#         # 降级或默认：标准 Selenium，此时再调用 webdriver-manager（365 天内复用缓存）
#         if driver_path is None:
#             driver_path = _install_chromedriver_via_wdm()
#             if driver_path:
#                 logger.info("已通过 webdriver-manager 获取 ChromeDriver（优先使用本地缓存）")

#         # 标准 Selenium Chrome（或 UC 失败后的降级）
#         logger.info("使用标准 Selenium Chrome 初始化浏览器")
#         try:
#             if driver_path:
#                 service = Service(executable_path=str(driver_path))
#                 self.driver = webdriver.Chrome(service=service, options=chrome_options)
#             else:
#                 self.driver = webdriver.Chrome(options=chrome_options)
#         except WebDriverException as e:
#             logger.error(f"初始化 Chrome 驱动失败: {e}")
#             logger.error("请确保已安装 Chrome 浏览器；若未安装 webdriver-manager，请将 ChromeDriver 添加到 PATH 或执行: pip install webdriver-manager")
#             raise

#         self.driver.set_page_load_timeout(self.timeout)
#         if not self.headless:
#             try:
#                 self.driver.maximize_window()
#             except Exception:
#                 pass
#         try:
#             self.driver.execute_script(
#                 "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
#             )
#         except Exception:
#             pass
#         logger.info("Chrome 浏览器驱动初始化成功")
#         return self.driver
    
#     def _close_driver(self):
#         """关闭浏览器驱动"""
#         if self.driver:
#             try:
#                 self.driver.quit()
#                 logger.info("浏览器驱动已关闭")
#             except Exception as e:
#                 logger.warning(f"关闭浏览器驱动时出错: {e}")
#             finally:
#                 self.driver = None
    
#     def _check_cloudflare_verification(self, driver: webdriver.Chrome, max_wait: int = 15) -> bool:
#         """
#         检查并处理Cloudflare验证页面
#         参考用户提供的代码，使用更精确的选择器和WebDriverWait
#         :param driver: WebDriver实例
#         :param max_wait: 最大等待时间（秒，默认15秒，已优化为更短的等待时间）
#         :return: 是否成功通过验证
#         """
#         try:
#             # 检查是否在Cloudflare验证页面
#             cloudflare_indicators = [
#                 "cloudflare",
#                 "checking your browser",
#                 "请完成以下操作",
#                 "验证您是真人",
#                 "确认您是真人",
#                 "Just a moment",
#                 "DDoS protection by Cloudflare"
#             ]
            
#             page_text = driver.page_source.lower()
#             page_title = driver.title.lower()
#             current_url = driver.current_url.lower()
            
#             is_cloudflare = any(indicator in page_text or indicator in page_title or indicator in current_url 
#                                for indicator in cloudflare_indicators)
            
#             if not is_cloudflare:
#                 return True  # 不在Cloudflare验证页面
            
#             logger.info("检测到Cloudflare验证页面，等待验证元素加载...")
            
#             # 使用WebDriverWait等待验证复选框出现并点击
#             # 按优先级尝试多个选择器（减少等待时间以提高速度）
#             checkbox_selectors = [
#                 "//input[@type='checkbox' and @aria-label='确认您是真人']",  # 中文验证框
#                 "//input[@type='checkbox' and @aria-label='Confirm you are human']",  # 英文验证框
#                 "//input[@type='checkbox' and contains(@aria-label, '确认')]",  # 包含"确认"的验证框
#                 "//input[@type='checkbox' and contains(@aria-label, 'Confirm')]",  # 包含"Confirm"的验证框
#                 "//input[@type='checkbox' and @id='challenge-form-checkbox']",  # 通过ID定位
#                 "//input[@type='checkbox']",  # 通用复选框（最后尝试）
#             ]
            
#             clicked = False
#             checkbox_wait_time = 5  # 减少等待复选框的时间（从10秒减到5秒）
#             for selector in checkbox_selectors:
#                 try:
#                     logger.debug(f"尝试使用选择器: {selector}")
#                     # 使用WebDriverWait等待元素可点击（缩短等待时间）
#                     verify_checkbox = WebDriverWait(driver, checkbox_wait_time).until(
#                         EC.element_to_be_clickable((By.XPATH, selector))
#                     )
#                     # 使用普通click（而不是JavaScript click），更接近真人行为
#                     verify_checkbox.click()
#                     logger.info("已点击Cloudflare验证复选框")
#                     clicked = True
#                     time.sleep(1)
#                     break
#                 except TimeoutException:
#                     logger.debug(f"选择器 {selector} 未找到元素，尝试下一个")
#                     continue
#                 except Exception as e:
#                     logger.debug(f"使用选择器 {selector} 时出错: {e}")
#                     continue
            
#             if not clicked:
#                 logger.warning("未找到可点击的验证复选框，可能验证页面结构已变化或验证会自动通过")
#                 # 继续等待，可能验证会自动通过
            
#             # 等待验证通过（通过页面标题变化或URL变化来判断）
#             logger.info("等待Cloudflare验证通过...")
#             try:
#                 # 等待页面标题变化（不再包含验证相关文本）或URL变化
#                 # 对于PDF页面，标题可能包含"PDF"或页面URL包含"pdf"
#                 # 使用轮询间隔，每0.5秒检查一次，而不是默认的0.5秒
#                 WebDriverWait(driver, max_wait, poll_frequency=0.5).until(
#                     lambda d: self._is_verification_passed(d, cloudflare_indicators)
#                 )
#                 logger.info("Cloudflare验证已通过，页面已跳转")
#                 time.sleep(1)
#                 return True
#             except TimeoutException:
#                 logger.warning(f"Cloudflare验证等待超时（{max_wait}秒）")
#                 # 最后检查一次是否还在验证页面
#                 if not self._is_verification_page(driver, cloudflare_indicators):
#                     logger.info("验证可能已通过（页面已变化）")
#                     return True
#                 return False
            
#         except Exception as e:
#             logger.warning(f"检查Cloudflare验证时出错: {e}")
#             return True  # 假设验证通过，继续执行
    
#     def _is_verification_page(self, driver: webdriver.Chrome, indicators: list) -> bool:
#         """
#         检查当前页面是否是Cloudflare验证页面
#         :param driver: WebDriver实例
#         :param indicators: Cloudflare验证页面标识符列表
#         :return: 是否是验证页面
#         """
#         try:
#             page_text = driver.page_source.lower()
#             page_title = driver.title.lower()
#             current_url = driver.current_url.lower()
#             return any(indicator in page_text or indicator in page_title or indicator in current_url 
#                       for indicator in indicators)
#         except:
#             return False
    
#     def _is_verification_passed(self, driver: webdriver.Chrome, indicators: list) -> bool:
#         """
#         检查验证是否已通过
#         :param driver: WebDriver实例
#         :param indicators: Cloudflare验证页面标识符列表
#         :return: 验证是否已通过
#         """
#         try:
#             # 如果不再是验证页面，认为验证通过
#             if not self._is_verification_page(driver, indicators):
#                 return True
            
#             # 如果URL包含"pdf"或标题包含"PDF"，也可能表示验证通过并跳转到PDF页面
#             current_url = driver.current_url.lower()
#             page_title = driver.title.lower()
#             if 'pdf' in current_url or 'pdf' in page_title:
#                 return True
            
#             return False
#         except:
#             return False
    
#     def _handle_cookie_banner(self, driver: webdriver.Chrome, max_wait: int = 10) -> bool:
#         """
#         检测并处理cookie同意弹窗
#         针对Elsevier、Springer等常见出版商的cookie弹窗进行优化。
#         为避免长时间卡在“检测到cookie弹窗，尝试自动处理...”阶段，这里增加整体超时控制，
#         并缩短单个选择器的等待时间，保证总耗时不超过 max_wait 秒。
#         :param driver: WebDriver实例
#         :param max_wait: 最大等待时间（秒）
#         :return: 是否成功处理cookie弹窗
#         """
#         try:
#             start_time = time.time()
#             # 简短等待页面渲染出弹窗元素
#             try:
#                 WebDriverWait(driver, min(5, max_wait)).until(
#                     EC.presence_of_element_located((By.TAG_NAME, "body"))
#                 )
#             except Exception:
#                 pass

#             # 检查是否存在cookie弹窗
#             cookie_indicators = [
#                 "cookie",
#                 "cookies",
#                 "我们使用cookies",
#                 "我们使用cookie",
#                 "we use cookies",
#                 "we use cookie",
#                 "接受Cookies",
#                 "接受Cookie",
#                 "全部接受",
#                 "Accept Cookies",
#                 "Accept Cookie",
#                 "Accept All",
#                 "accept all",
#                 "Cookie设置",
#                 "Cookie Settings",
#                 "Cookie通知",
#                 "Cookie Notice",
#                 "同意",
#                 "Accept",
#                 "同意Cookies"
#             ]
            
#             page_text = driver.page_source
#             page_text_lower = page_text.lower()
            
#             # 检查页面是否包含cookie相关内容
#             has_cookie_banner = any(indicator.lower() in page_text_lower for indicator in cookie_indicators)
            
#             if not has_cookie_banner:
#                 logger.debug("未检测到cookie弹窗")
#                 return True  # 没有cookie弹窗，认为已处理
            
#             logger.info("检测到cookie弹窗，尝试自动处理...")
            
#             # 多种选择器策略查找"接受Cookies"或"全部接受"按钮（按优先级排序）
#             accept_button_selectors = [
#                 # 高优先级中文
#                 (By.XPATH, "//button[contains(text(), '全部接受')]"),
#                 (By.XPATH, _case_insensitive_button_xpath(['全部', '接受'], require_all=True)),

#                 # 高优先级英文
#                 (By.XPATH, "//button[contains(text(), 'Accept All')]"),
#                 (By.XPATH, _case_insensitive_button_xpath(['accept', 'all'], require_all=True)),

#                 # 常见文本模式
#                 (By.XPATH, "//button[" + _case_insensitive_xpath('accept') + "]"),
#                 (By.XPATH, "//button[" + _case_insensitive_xpath('同意') + "]"),

#                 # 通过类名和ID（常见模式）
#                 (By.CSS_SELECTOR, "button[class*='accept-all'], button[class*='acceptAll']"),
#                 (By.CSS_SELECTOR, "button[id*='accept-all'], button[id*='acceptAll']"),

#                 # Cookie弹窗内的按钮
#                 (By.XPATH, "//div[contains(@class, 'cookie')]//button[" + _case_insensitive_xpath('accept') + "]"),
#                 (By.XPATH, "//div[contains(@class, 'cookie-banner')]//button"),
#             ]
            
#             clicked = False
#             for by, selector in accept_button_selectors:
#                 # 整体耗时超过 max_wait 时直接放弃进一步尝试，避免长时间阻塞下载流程
#                 elapsed = time.time() - start_time
#                 if elapsed >= max_wait:
#                     logger.warning(
#                         "处理cookie弹窗已耗时 %.1f 秒，停止进一步尝试，继续后续下载流程", elapsed
#                     )
#                     break

#                 try:
#                     logger.debug(f"尝试使用选择器查找接受Cookies按钮: {selector}")
#                     # 每个选择器最多等待 2 秒，且不超过剩余时间
#                     remaining = max(0.5, max_wait - elapsed)
#                     per_selector_timeout = min(2, remaining)
#                     accept_button = WebDriverWait(driver, per_selector_timeout).until(
#                         EC.element_to_be_clickable((by, selector))
#                     )
                    
#                     # 检查元素是否可见
#                     if accept_button.is_displayed():
#                         # 滚动到按钮位置，确保可见
#                         driver.execute_script("arguments[0].scrollIntoView({behavior: 'smooth', block: 'center'});", accept_button)
#                         time.sleep(0.5)
                        
#                         # 尝试点击按钮
#                         try:
#                             accept_button.click()
#                             logger.info("已点击接受Cookies按钮（普通点击）")
#                             clicked = True
#                             time.sleep(1)  # 等待弹窗消失
#                             break
#                         except Exception as e:
#                             logger.debug(f"普通点击失败: {e}，尝试JavaScript点击")
#                             # 使用JavaScript点击
#                             try:
#                                 driver.execute_script("arguments[0].click();", accept_button)
#                                 logger.info("已点击接受Cookies按钮（JavaScript点击）")
#                                 clicked = True
#                                 time.sleep(1)
#                                 break
#                             except Exception as js_e:
#                                 logger.debug(f"JavaScript点击也失败: {js_e}")
#                                 continue
#                 except TimeoutException:
#                     logger.debug(f"选择器 {selector} 未找到元素，尝试下一个")
#                     continue
#                 except Exception as e:
#                     logger.debug(f"使用选择器 {selector} 时出错: {e}")
#                     continue
            
#             if clicked:
#                 # 验证cookie弹窗是否已关闭
#                 time.sleep(0.5)
#                 # 再次检查页面，确认弹窗是否消失
#                 try:
#                     _ = driver.page_source
#                     logger.info("Cookie弹窗处理完成")
#                     return True
#                 except Exception:
#                     return True
#             else:
#                 logger.warning("未找到可点击的接受Cookies按钮，可能cookie弹窗结构已变化或无需显式同意")
#                 # 不再做额外复杂尝试，避免长时间阻塞，直接返回 False 让后续逻辑继续
#                 return False
            
#         except Exception as e:
#             logger.warning(f"处理cookie弹窗时出错: {e}")
#             return False  # 出错时返回False，但继续执行后续流程
    
#     def _find_download_button(self, driver: webdriver.Chrome) -> Optional[object]:
#         """
#         在页面中查找Download PDF按钮
#         针对Wiley、Springer、Elsevier等常见出版商优化
#         :param driver: WebDriver实例
#         :return: 按钮元素或None
#         """
#         try:
#             # 等待页面加载
#             WebDriverWait(driver, 10).until(
#                 EC.presence_of_element_located((By.TAG_NAME, "body"))
#             )
            
#             # 多种选择器策略查找下载按钮（按优先级排序）
#             button_selectors = [
#                 # 高优先级：aria-label和title
#                 (By.XPATH, "//a[contains(@aria-label, 'PDF') or contains(@title, 'PDF')]"),
#                 (By.XPATH, "//button[contains(@aria-label, 'PDF') or contains(@title, 'PDF')]"),

#                 # 通过类名和href（合并重复）
#                 (By.CSS_SELECTOR, "a[href*='.pdf'], a[href*='/pdf'], a[href*='/epdf']"),
#                 (By.CSS_SELECTOR, "a[class*='pdf'], a[class*='PDF'], a[download]"),

#                 # 文本内容（使用辅助函数）
#                 (By.XPATH, "//a[" + _case_insensitive_xpath('pdf') + "]"),
#                 (By.XPATH, "//button[" + _case_insensitive_xpath('download') + "]"),

#                 # 通过ID
#                 (By.CSS_SELECTOR, "#download-pdf, #pdf-download, #pdf"),
#             ]
            
#             for by, selector in button_selectors:
#                 try:
#                     elements = driver.find_elements(by, selector)
#                     for element in elements:
#                         try:
#                             # 检查元素是否可见和可点击
#                             if element.is_displayed() and element.is_enabled():
#                                 # 获取元素的文本或属性，用于日志
#                                 element_text = element.text or element.get_attribute('aria-label') or element.get_attribute('title') or ''
#                                 element_href = element.get_attribute('href') or ''
#                                 logger.info(f"找到PDF下载按钮: {selector}, 文本: {element_text[:50]}, href: {element_href[:100]}")
#                                 return element
#                         except Exception as e:
#                             logger.debug(f"检查元素时出错: {e}")
#                             continue
#                 except Exception as e:
#                     logger.debug(f"选择器 {selector} 未找到元素: {e}")
#                     continue
            
#             logger.warning("未找到PDF下载按钮")
#             return None
#         except Exception as e:
#             logger.warning(f"查找下载按钮时出错: {e}")
#             return None
    
#     def _find_pdf_link_in_page(self, driver: webdriver.Chrome, url: str, check_cloudflare: bool = False) -> Optional[str]:
#         """
#         在页面中查找PDF下载链接
#         :param driver: WebDriver实例
#         :param url: 当前页面URL
#         :param check_cloudflare: 是否检查Cloudflare验证（默认False，避免重复检测）
#         :return: PDF链接，如果未找到则返回None
#         """
#         try:
#             # 只在明确需要时检查Cloudflare验证（避免重复检测）
#             if check_cloudflare:
#                 self._check_cloudflare_verification(driver, max_wait=15)
            
#             # 等待页面加载
#             WebDriverWait(driver, 10).until(
#                 EC.presence_of_element_located((By.TAG_NAME, "body"))
#             )
            
#             # 查找PDF链接
#             pdf_keywords = ['pdf', 'download', 'full text', 'article', 'download pdf']
#             selectors = [
#                 "//a[contains(@href, '.pdf')]",
#                 "//a[contains(translate(text(), 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'pdf')]",
#                 "//a[contains(translate(text(), 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'download')]",
#             ]
            
#             for selector in selectors:
#                 try:
#                     elements = driver.find_elements(By.XPATH, selector)
#                     for element in elements:
#                         href = element.get_attribute('href')
#                         if href and ('.pdf' in href.lower() or 'pdf' in href.lower()):
#                             logger.info(f"在页面中找到PDF链接: {href}")
#                             return href
#                 except Exception as e:
#                     logger.debug(f"使用选择器 {selector} 查找失败: {e}")
#                     continue
            
#             # 检查URL是否为Sage出版社，尝试构造PDF URL
#             parsed_url = urlparse(url)
#             if 'sagepub.com' in parsed_url.netloc and '/doi/' in url and '/doi/pdf/' not in url:
#                 pdf_url = url.replace('/doi/', '/doi/pdf/')
#                 logger.info(f"尝试构造Sage出版社PDF URL: {pdf_url}")
#                 return pdf_url
            
#             return None
#         except TimeoutException:
#             logger.warning("页面加载超时")
#             return None
#         except Exception as e:
#             logger.warning(f"查找PDF链接时出错: {e}")
#             return None
    
#     def _wait_for_download_complete(self, timeout: int = 60) -> Optional[Path]:
#         """
#         等待下载完成
#         改进版本：监控文件大小变化，确保下载完成
#         :param timeout: 超时时间（秒）
#         :return: 下载的文件路径，如果超时则返回None
#         """
#         start_time = time.time()
#         last_file_count = 0
#         last_file_size = 0
#         stable_count = 0  # 文件大小稳定的次数
        
#         logger.info(f"开始监控下载目录: {self.temp_download_dir}")
        
#         while time.time() - start_time < timeout:
#             # 检查临时下载目录中的所有文件（包括正在下载的）
#             all_files = list(self.temp_download_dir.glob("*"))
#             pdf_files = [f for f in all_files if f.is_file() and (f.name.endswith('.pdf') or f.name.endswith('.crdownload') or f.name.endswith('.tmp'))]
            
#             if pdf_files:
#                 # 检查文件是否还在下载中（.crdownload或.tmp扩展名）
#                 completed_files = [f for f in pdf_files if not f.name.endswith('.crdownload') and not f.name.endswith('.tmp')]
                
#                 if completed_files:
#                     # 返回最新的文件
#                     latest_file = max(completed_files, key=lambda f: f.stat().st_mtime)
#                     try:
#                         current_size = latest_file.stat().st_size
                        
#                         # 检查文件大小是否稳定（文件写入完成）
#                         if current_size == last_file_size:
#                             stable_count += 1
#                             # 文件大小连续3次检查都稳定，且大于1KB，认为下载完成
#                             if stable_count >= 3 and current_size > 1024:
#                                 logger.info(f"检测到下载完成的文件: {latest_file} ({current_size/1024/1024:.2f} MB)")
#                                 time.sleep(1)  # 额外等待确保文件写入完成
#                                 return latest_file
#                         else:
#                             # 文件大小还在变化，重置稳定计数
#                             stable_count = 0
#                             logger.debug(f"文件还在下载中: {latest_file.name}, 当前大小: {current_size/1024:.2f} KB")
#                             last_file_size = current_size
#                     except Exception as e:
#                         logger.debug(f"检查文件大小时出错: {e}")
#                 else:
#                     # 有文件正在下载中
#                     downloading_files = [f for f in pdf_files if f.name.endswith('.crdownload') or f.name.endswith('.tmp')]
#                     if downloading_files:
#                         latest_downloading = max(downloading_files, key=lambda f: f.stat().st_mtime)
#                         try:
#                             current_size = latest_downloading.stat().st_size
#                             if current_size != last_file_size:
#                                 logger.debug(f"文件正在下载: {latest_downloading.name}, 当前大小: {current_size/1024:.2f} KB")
#                                 last_file_size = current_size
#                                 stable_count = 0  # 重置稳定计数
#                         except:
#                             pass
            
#             time.sleep(1)
        
#         # 超时后，检查是否有任何PDF文件（即使可能还在下载）
#         pdf_files = list(self.temp_download_dir.glob("*.pdf"))
#         if pdf_files:
#             completed_files = [f for f in pdf_files if not f.name.endswith('.crdownload') and not f.name.endswith('.tmp')]
#             if completed_files:
#                 latest_file = max(completed_files, key=lambda f: f.stat().st_mtime)
#                 try:
#                     file_size = latest_file.stat().st_size
#                     if file_size > 1024:
#                         logger.warning(f"等待超时，但找到可能的下载文件: {latest_file} ({file_size/1024/1024:.2f} MB)")
#                         return latest_file
#                 except:
#                     pass
        
#         logger.warning(f"等待下载超时（{timeout}秒），未检测到下载文件")
#         return None
    
#     def _move_downloaded_file(self, temp_file: Path, target_path: Path) -> bool:
#         """
#         将下载的文件移动到目标位置
#         :param temp_file: 临时文件路径
#         :param target_path: 目标文件路径
#         :return: 是否成功
#         """
#         try:
#             # 确保目标目录存在
#             target_path.parent.mkdir(parents=True, exist_ok=True)
            
#             # 如果目标文件已存在，先删除
#             if target_path.exists():
#                 target_path.unlink()
            
#             # 移动文件
#             shutil.move(str(temp_file), str(target_path))
#             logger.info(f"文件已移动到: {target_path}")
#             return True
#         except Exception as e:
#             logger.error(f"移动文件时出错: {e}")
#             return False
    
    
#     def download_pdf(
#         self,
#         pdf_url: str,
#         doi: str,
#         year: Optional[str] = None,
#         source: Optional[str] = None,
#         title: Optional[str] = None,
#         journal: Optional[str] = None,
#         author: Optional[str] = None,
#         pmid: Optional[str] = None
#     ) -> Optional[str]:
#         """
#         使用Selenium下载PDF（直接使用undetected-chromedriver绕过Cloudflare检测）
#         :param pdf_url: PDF链接（可能是DOI链接或直接PDF链接）
#         :param doi: 文献DOI
#         :param year: 年份（可选）
#         :param source: 来源（可选）
#         :param title: 标题（可选）
#         :param journal: 期刊（可选）
#         :param author: 作者（可选）
#         :param pmid: PMID（可选）
#         :return: 下载的文件路径或None
#         """
        
        
        
        
        
        
#         # 直接使用undetected-chromedriver
#         logger.info(f"使用undetected-chromedriver下载: {pdf_url}")
#         result = self._download_with_selenium_impl(
#             pdf_url=pdf_url,
#             target_path=target_path,
#             use_undetected=True
#         )
#         if result:
#             return result
        
#         logger.warning(f"Selenium下载失败: {doi}")
#         return None
    
#     def _download_with_selenium_impl(
#         self,
#         pdf_url: str,
#         target_path: Path,
#         use_undetected: bool = False
#     ) -> Optional[str]:
#         """
#         使用Selenium下载PDF的具体实现
#         :param pdf_url: PDF链接
#         :param target_path: 目标文件路径
#         :param use_undetected: 是否使用undetected-chromedriver
#         :return: 下载的文件路径或None
#         """
#         driver = None
#         original_use_undetected = self.use_undetected
#         try:
#             # 临时设置use_undetected标志
#             self.use_undetected = use_undetected
            
#             # 关闭之前的driver（如果存在）
#             if self.driver:
#                 try:
#                     self.driver.quit()
#                 except:
#                     pass
#                 self.driver = None
            
#             # 初始化浏览器
#             driver = self._init_driver()

           
#             logger.info(f"使用{'undetected-chromedriver' if use_undetected else '普通Selenium'}访问URL: {pdf_url}")

#             # 访问目标 URL（会在当前标签页加载，不会打开新标签页）
#             driver.get(pdf_url)
            
#             # 等待页面加载并处理Cloudflare验证
#             time.sleep(3)
            
#             # 检查并处理Cloudflare验证（在验证通过后立即进行PDF下载处理）
#             cloudflare_passed = self._check_cloudflare_verification(driver, max_wait=15)
#             if cloudflare_passed:
#                 logger.info("Cloudflare验证已通过，开始PDF下载处理...")
#             else:
#                 logger.warning("Cloudflare验证可能未完全通过，继续尝试下载...")
            
#             # 等待页面完全加载（尽量缩短总等待时间）
#             try:
#                 WebDriverWait(driver, 8).until(
#                     EC.presence_of_element_located((By.TAG_NAME, "body"))
#                 )
#                 time.sleep(1)
#             except Exception:
#                 pass
            
#             # 检查并处理cookie弹窗（在Cloudflare验证之后、开始下载之前）
#             cookie_handled = self._handle_cookie_banner(driver, max_wait=10)
#             if cookie_handled:
#                 logger.info("Cookie弹窗已处理")
#             else:
#                 logger.warning("Cookie弹窗可能未完全处理，继续尝试下载...")
            
#             # 检查当前URL是否是PDF文件
#             current_url = driver.current_url
#             parsed_url = urlparse(current_url)
            
#             # 如果是PDF文件，直接等待下载
#             if current_url.lower().endswith('.pdf') or 'pdf' in current_url.lower() and '/pdf' in current_url:
#                 logger.info("当前页面已经是PDF文件，等待下载...")
#             # 如果是DOI链接或非PDF页面，尝试查找PDF链接或下载按钮
#             elif 'doi.org' in pdf_url or (not current_url.endswith('.pdf') and 'pdf' not in current_url.lower()):
#                 logger.info("当前页面可能不是PDF，尝试查找PDF下载按钮或链接...")
                
#                 # 方法1：优先尝试查找并点击PDF下载按钮（针对Wiley等需要点击的页面）
#                 download_button = self._find_download_button(driver)
#                 if download_button:
#                     logger.info("找到PDF下载按钮，准备点击...")
#                     try:
#                         # 滚动到按钮位置，确保可见
#                         driver.execute_script(
#                             "arguments[0].scrollIntoView({behavior: 'smooth', block: 'center'});",
#                             download_button,
#                         )
#                         time.sleep(0.5)
                        
#                         # 尝试普通点击
#                         try:
#                             download_button.click()
#                             logger.info("已点击PDF下载按钮（普通点击）")
#                             time.sleep(2)  # 等待页面响应
#                         except Exception as e:
#                             logger.debug(f"普通点击失败: {e}，尝试JavaScript点击")
#                             # 使用JavaScript点击
#                             driver.execute_script("arguments[0].click();", download_button)
#                             logger.info("已点击PDF下载按钮（JavaScript点击）")
#                             time.sleep(2)
                        
#                         # 检查是否跳转到PDF页面或触发下载
#                         new_url = driver.current_url
#                         if new_url != current_url:
#                             logger.info(f"点击后URL已变化: {new_url}")
#                             current_url = new_url
                        
#                         # 如果跳转到PDF页面，继续等待下载
#                         if current_url.lower().endswith('.pdf') or '/pdf' in current_url.lower() or '/epdf' in current_url.lower():
#                             logger.info("已跳转到PDF页面，等待下载...")
#                         else:
#                             # 如果还在HTML页面，可能需要再次查找PDF链接
#                             logger.info("仍在HTML页面，尝试查找PDF链接...")
#                             pdf_link = self._find_pdf_link_in_page(driver, current_url, check_cloudflare=False)
#                             if pdf_link:
#                                 logger.info(f"找到PDF链接，访问: {pdf_link}")
#                                 driver.get(pdf_link)
#                                 time.sleep(2)
#                                 current_url = driver.current_url
#                     except Exception as e:
#                         logger.warning(f"点击PDF下载按钮失败: {e}")
#                         # 继续尝试其他方法
                
#                 # 方法2：如果没找到按钮，尝试查找PDF链接
#                 if not download_button or not current_url.lower().endswith('.pdf'):
#                     pdf_link = self._find_pdf_link_in_page(driver, current_url, check_cloudflare=False)
#                     if pdf_link:
#                         logger.info(f"找到PDF链接，访问: {pdf_link}")
#                         driver.get(pdf_link)
#                         time.sleep(3)
#                         # 再次检查Cloudflare（如果新页面也有验证）
#                         self._check_cloudflare_verification(driver, max_wait=10)
#                         current_url = driver.current_url
#                     else:
#                         # 方法3：尝试构造PDF URL（针对特定出版商）
#                         if 'wiley.com' in current_url and '/doi/' in current_url and '/epdf' not in current_url:
#                             # Wiley的PDF链接格式：/doi/epdf/10.xxx/xxx
#                             pdf_url_wiley = current_url.replace('/doi/', '/doi/epdf/')
#                             logger.info(f"尝试Wiley PDF URL: {pdf_url_wiley}")
#                             driver.get(pdf_url_wiley)
#                             time.sleep(3)
#                             self._check_cloudflare_verification(driver, max_wait=10)
#                             current_url = driver.current_url
#                         elif 'sagepub.com' in current_url and '/doi/' in current_url and '/doi/pdf/' not in current_url:
#                             pdf_url_sage = current_url.replace('/doi/', '/doi/pdf/')
#                             logger.info(f"尝试Sage出版社PDF URL: {pdf_url_sage}")
#                             driver.get(pdf_url_sage)
#                             time.sleep(3)
#                             self._check_cloudflare_verification(driver, max_wait=10)
#                             current_url = driver.current_url
            
#             # 等待下载完成
#             # 如果当前URL是PDF页面，可能需要等待浏览器自动下载
#             # 如果是点击按钮触发的下载，也需要等待
#             logger.info(f"等待PDF下载完成... (当前URL: {driver.current_url})")
            
#             # 如果当前页面是PDF页面，可能需要等待一下让浏览器开始下载
#             if current_url.lower().endswith('.pdf') or '/pdf' in current_url.lower() or '/epdf' in current_url.lower():
#                 logger.info("检测到PDF页面，等待浏览器开始下载...")
#                 time.sleep(3)  # 给浏览器一些时间开始下载
            
#             downloaded_file = self._wait_for_download_complete(timeout=self.wait_time)
            
#             if downloaded_file:
#                 # 移动文件到目标位置
#                 if self._move_downloaded_file(downloaded_file, target_path):
#                     # 验证文件
#                     if target_path.exists() and target_path.stat().st_size > 1024:
#                         # 验证是否为PDF
#                         with open(target_path, 'rb') as f:
#                             header = f.read(4)
#                             if header == b"%PDF":
#                                 logger.info(f"Selenium下载成功: {target_path} ({target_path.stat().st_size/1024/1024:.2f} MB)")
#                                 return str(target_path)
#                             else:
#                                 logger.warning(f"下载的文件不是PDF格式")
#                                 target_path.unlink()
#                                 return None
#                 else:
#                     logger.error("移动下载文件失败")
#                     return None
#             else:
#                 logger.warning("未检测到下载文件，可能下载失败或页面需要人工操作")
#                 return None
                
#         except TimeoutException as e:
#             logger.error(f"页面加载超时（{self.timeout}秒）: {e}")
#             return None
#         except WebDriverException as e:
#             logger.error(f"浏览器操作出错: {e}")
#             return None
#         except Exception as e:
#             logger.error(f"Selenium下载PDF时出错: {e}")
#             return None
#         finally:
#             # 恢复原始设置
#             self.use_undetected = original_use_undetected
            
#             # 务必关闭浏览器，避免批量下载时堆积 Chrome 窗口/进程（driver 与 self.driver 可能为同一实例）
#             # 先关闭所有标签页，再退出浏览器
#             _quit_done = set()
#             for d in (driver, self.driver):
#                 if d is not None and id(d) not in _quit_done:
#                     _quit_done.add(id(d))
#                     try:
#                         # 先关闭所有标签页（防止残留）
#                         try:
#                             window_handles = d.window_handles
#                             for handle in window_handles:
#                                 try:
#                                     d.switch_to.window(handle)
#                                     d.close()
#                                 except:
#                                     pass
#                         except:
#                             pass
#                         # 再退出浏览器
#                         d.quit()
#                         logger.debug("浏览器已退出")
#                     except Exception as e:
#                         logger.debug(f"退出浏览器时出错: {e}")
#             self.driver = None
            
#             # 清理临时下载目录中的残留文件
#             try:
#                 for temp_file in self.temp_download_dir.glob("*"):
#                     if temp_file.is_file():
#                         try:
#                             temp_file.unlink()
#                         except:
#                             pass
#             except:
#                 pass
    
#     def __enter__(self):
#         """上下文管理器入口"""
#         return self
    
#     def __exit__(self, exc_type, exc_val, exc_tb):
#         """上下文管理器出口"""
#         self._close_driver()
#         return False


# if __name__ == "__main__":
#     # 测试示例
#     downloader = SeleniumDownloader(
#         download_dir="literature_pdfs/test_selenium",
#         headless=True,  # 改为 False 可显示浏览器窗口调试
#         wait_time=15
#     )
    
#     test_doi = "10.1177/00238309251395278"
#     test_url = f"https://doi.org/{test_doi}"
    
#     result = downloader.download_pdf(
#         pdf_url=test_url,
#         doi=test_doi,
#         source="selenium"
#     )
    
#     if result:
#         print(f"下载成功: {result}")
#     else:
#         print("下载失败")
    
#     downloader._close_driver()
    
#     # 保持向后兼容
#     SeleniumPDFDownloader = SeleniumDownloader

