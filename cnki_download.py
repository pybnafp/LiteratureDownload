# Made by Ofnoname && Wanakachi
"""
CNKI 文献抓取与下载脚本（基于 Selenium）

功能：
1. 根据关键词在知网搜索，抓取结果链接到 cnki_pdfs/links/<关键词>.csv（链接按关键词区分）；
2. 所有下载的 PDF/CAJ 文献（不区分关键词）统一保存到 cnki_pdfs/saves 目录下；
3. 在初始化时遍历 cnki_pdfs/saves 下所有文件（文件命名为 文献名_作者.pdf），将文献名写入 cnki_pdfs/download_records.csv，并保证一一对应；
4. 所有文献下载记录统一保存在 cnki_pdfs/download_records.csv 中，仅保存文献名，每次下载前通过文献名称 name 去重，避免重复下载。
"""

import os
import time
import random
import logging
import csv
from datetime import datetime
from typing import List, Tuple, Set

from bs4 import BeautifulSoup
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver import ActionChains
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager

try:
    import undetected_chromedriver as uc
    UC_AVAILABLE = True
except ImportError:
    uc = None  # type: ignore[assignment]
    UC_AVAILABLE = False

# 知网搜索：起点 https://kns.cnki.net/kns8s/defaultresult/index
# 主题检索：?korder=SU&kw=关键词；关键词检索：?korder=KY&kw=关键词；作者搜索：?korder=AU&kw=关键词（korder 可手动搜索后从地址栏获取）
# 结果页：文献标题链接 class="fz14"，用 BeautifulSoup 提取 .fz14 的链接，保存 文献名、年代、详情页链接

# 基本目录配置
BASE_DIR = 'cnki_pdfs'
SAVE_DIR = os.path.join(BASE_DIR, 'saves')
LINK_DIR = os.path.join(BASE_DIR, 'links')
KEYWORDS = {'失语症治疗'}  # 待搜索关键词集合
RESULT_COUNT = 100  # 每个关键词搜索结果数量

# 搜索类型：SU=主题检索（默认），KY=关键词检索，AU=作者，可从知网地址栏复制
KORDER = 'SU'  # 默认主题检索；设为 'KY' 则为关键词检索

# 下载配置
FILE_TYPE = 'pdf'       # 可选 'pdf' 或 'caj'
MAX_RETRIES = 2         # 单篇文章最大重试次数
DOWNLOAD_BATCH_SIZE = 10  # 每下载多少篇后进行长时间休息
DOWNLOAD_BATCH_SLEEP = 60  # 批次之间休息秒数
MAX_CONSECUTIVE_CAPTCHAS = 5  # 连续多少篇因拼图验证码失败后重启浏览器
DOWNLOAD_CAPTCHA_WAIT_TIMEOUT = 120  # 等待下载拼图验证通过的最长时间
DOWNLOAD_CAPTCHA_POLL_INTERVAL = 1   # 轮询拼图验证状态的间隔秒数

# 浏览器反爬配置
USE_UNDETECTED_CHROME = False  # 若安装了 undetected-chromedriver，则优先使用 UC

# 下载记录配置（download_records.csv 仅保存文献名 name）
DOWNLOAD_RECORDS_CSV = os.path.join(BASE_DIR, 'download_records.csv')
DOWNLOADED_URLS: Set[str] = set()
DOWNLOADED_NAMES: Set[str] = set()

# 安全验证页 URL 特征（滑块拼图）
VERIFY_URL_MARKER = '/verify/home'
# 等待用户完成验证的最长时间（秒）
CAPTCHA_WAIT_TIMEOUT = 120
CAPTCHA_POLL_INTERVAL = 1

driver = None

# 配置日志记录
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)

# 降低第三方库（尤其是网络层 http/2）的日志噪音，只保留 WARNING 以上
for noisy_logger in [
    'urllib3',
    'h2',
    'hpack',
]:
    logging.getLogger(noisy_logger).setLevel(logging.WARNING)


def ensure_directory_exists(directory: str) -> None:
    """
    确保指定目录存在，若不存在则创建。
    """
    if not os.path.exists(directory):
        os.makedirs(directory)
        logging.debug(f"目录 {directory} 创建成功。")
    else:
        logging.debug(f"目录 {directory} 已存在。")


def load_download_records() -> None:
    """
    从 download_records.csv 中加载已下载文章，用于去重。
    - 只要 url 不为空，就加入 DOWNLOADED_URLS（备用）；
    - 只要 name 不为空，就加入 DOWNLOADED_NAMES（按标题去重的主依据）。
    """
    DOWNLOADED_URLS.clear()
    DOWNLOADED_NAMES.clear()
    if not os.path.exists(DOWNLOAD_RECORDS_CSV):
        return

    try:
        with open(DOWNLOAD_RECORDS_CSV, 'r', encoding='utf-8-sig', newline='') as f:
            reader = csv.DictReader(f)
            count_urls = 0
            count_names = 0
            for row in reader:
                url = (row.get('url') or '').strip()
                name = (row.get('name') or '').strip()
                if url:
                    DOWNLOADED_URLS.add(url)
                    count_urls += 1
                if name:
                    DOWNLOADED_NAMES.add(name)
                    count_names += 1
        logging.info(
            f"已从 {DOWNLOAD_RECORDS_CSV} 加载 {count_names} 条已下载文献名称记录、"
            f"{count_urls} 条已下载 URL 记录，用于去重。"
        )
    except Exception as e:
        logging.error(f"加载下载记录文件失败：{e}")


def append_download_records(rows: List[dict]) -> None:
    """
    将新的下载记录追加写入 download_records.csv。
    当前设计：CSV 中仅保存文献名 name，其它字段不再持久化。
    rows 中的每个 dict 至少包含：name。
    """
    if not rows:
        return

    file_exists = os.path.exists(DOWNLOAD_RECORDS_CSV)
    fieldnames = ['name']
    try:
        with open(DOWNLOAD_RECORDS_CSV, 'a', encoding='utf-8-sig', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            if not file_exists:
                writer.writeheader()
            for row in rows:
                name = (row.get('name') or '').strip()
                if not name:
                    continue
                writer.writerow({'name': name})
                DOWNLOADED_NAMES.add(name)
    except Exception as e:
        logging.error(f"写入下载记录失败：{e}")


def sync_existing_files_to_records() -> None:
    """
    扫描 SAVE_DIR（cnki_pdfs/saves）目录下所有已存在的 PDF/CAJ 文件，
    文件命名方式为：文献名_作者.pdf（或 .caj），将“文献名”部分写入 download_records.csv。
    要求：csv 中的每一条 name 与实际已下载文献一一对应：
    - 若 csv 中 name 在实际文件集合中不存在，则丢弃该条记录；
    - 若某个已下载文献名在 csv 中不存在，则在 csv 末尾新增该文献名。
    """
    ensure_directory_exists(SAVE_DIR)

    # 第一步：从文件名解析文献名集合：文件名形如 “文献名_作者.pdf”，取最后一个下划线之前的部分作为文献名
    file_names: Set[str] = set()
    for root, _, files in os.walk(SAVE_DIR):
        for filename in files:
            lower = filename.lower()
            if not (lower.endswith('.pdf') or lower.endswith('.caj')):
                continue
            base, _ext = os.path.splitext(filename)
            if '_' in base:
                name_part = base.rsplit('_', 1)[0]
            else:
                name_part = base
            name_part = name_part.strip()
            if name_part:
                file_names.add(name_part)

    # 第二步：读取现有 CSV 中按顺序保存的文献名，只保留那些在 file_names 集合中的 name
    kept_names_ordered: List[str] = []
    kept_names_set: Set[str] = set()
    if os.path.exists(DOWNLOAD_RECORDS_CSV):
        try:
            with open(DOWNLOAD_RECORDS_CSV, 'r', encoding='utf-8-sig', newline='') as f:
                reader = csv.DictReader(f)
                for row in reader:
                    name = (row.get('name') or '').strip()
                    if not name:
                        continue
                    if name in file_names and name not in kept_names_set:
                        kept_names_ordered.append(name)
                        kept_names_set.add(name)
        except Exception as e:
            logging.error(f"读取现有下载记录失败：{e}")

    # 第三步：将未被记录的已下载文献名追加到末尾
    missing_names = sorted(file_names - kept_names_set)
    all_names_ordered = kept_names_ordered + missing_names

    # 重写 download_records.csv，仅保存一列 name，并更新内存中的 DOWNLOADED_NAMES
    DOWNLOADED_NAMES.clear()
    try:
        with open(DOWNLOAD_RECORDS_CSV, 'w', encoding='utf-8-sig', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=['name'])
            writer.writeheader()
            for name in all_names_ordered:
                writer.writerow({'name': name})
                DOWNLOADED_NAMES.add(name)
        logging.info(
            "已根据 cnki_pdfs/saves 中的文件，将 %d 条文献名与实际下载文件一一对应同步到 %s。",
            len(all_names_ordered),
            DOWNLOAD_RECORDS_CSV,
        )
    except Exception as e:
        logging.error(f"重写下载记录文件失败：{e}")


def _detect_new_file(output_dir: str, before_files: Set[str], timeout: int = 30) -> str | None:
    """
    在下载触发后，轮询检测 output_dir 中新增的 PDF/CAJ 文件，用于记录到 download_records.csv。
    返回新文件的绝对路径；若在 timeout 内未检测到则返回 None。
    """
    deadline = time.time() + timeout
    before_files = {f for f in before_files}
    while time.time() < deadline:
        try:
            current_files = {
                f for f in os.listdir(output_dir)
                if f.lower().endswith('.pdf') or f.lower().endswith('.caj')
            }
        except FileNotFoundError:
            break
        new_files = current_files - before_files
        if new_files:
            # 取修改时间最新的一个，认为是刚下载完成的文件
            newest = max(
                new_files,
                key=lambda fn: os.path.getmtime(os.path.join(output_dir, fn))
            )
            return os.path.abspath(os.path.join(output_dir, newest))
        time.sleep(1)
    return None

def _setup_chrome_options(download_dir: str = None):
    """
    仿照 selenium_pdf_downloader.py，配置 Chrome 浏览器选项。
    """
    # 根据是否使用 UC 选择 Options 类型
    if USE_UNDETECTED_CHROME and UC_AVAILABLE:
        chrome_options = uc.ChromeOptions()
    else:
        chrome_options = Options()

    # 若你希望完全隐藏浏览器，可将此行改为注释
    # 注意：undetected-chromedriver 在无头模式下效果可能变差，这里默认不开启 headless
    # chrome_options.add_argument('--headless=new')

    # 基本浏览器设置：仅在使用标准 Selenium 时添加，UC 自己会做伪装处理
    if not (USE_UNDETECTED_CHROME and UC_AVAILABLE):
        chrome_options.add_argument('--no-sandbox')
        chrome_options.add_argument('--disable-dev-shm-usage')
        chrome_options.add_argument('--disable-gpu')
        chrome_options.add_argument('--disable-blink-features=AutomationControlled')
        chrome_options.add_experimental_option("excludeSwitches", ["enable-automation"])
        chrome_options.add_experimental_option('useAutomationExtension', False)
        chrome_options.add_argument(
            "user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )

    # 配置下载目录
    target_dir = download_dir if download_dir else SAVE_DIR
    abs_save_dir = os.path.abspath(target_dir)
    prefs = {
        "download.default_directory": abs_save_dir,
        "download.prompt_for_download": False,
        "download.directory_upgrade": True,
        "safebrowsing.enabled": True,
        "plugins.always_open_pdf_externally": True,
        "profile.default_content_setting_values.automatic_downloads": 1,
    }
    chrome_options.add_experimental_option("prefs", prefs)
    return chrome_options


def load_chrome_driver(download_dir: str = None) -> webdriver.Chrome:
    """
    初始化并返回 Chrome 驱动实例，同时配置下载目录等参数。
    仿照 selenium_pdf_downloader.py 的初始化方式，避免额外调试输出。
    """
    options = _setup_chrome_options(download_dir)

    # 若安装了 UC 且配置为使用，则优先通过 undetected-chromedriver 启动浏览器，
    # 减少 window.navigator.webdriver 等自动化特征，降低触发知网验证码的概率。
    if USE_UNDETECTED_CHROME and UC_AVAILABLE:
        logging.info("使用 undetected-chromedriver 初始化 Chrome 浏览器（降低被知网识别概率）")
        # 通过 webdriver-manager 获取与本机 Chrome 版本匹配的驱动路径，
        # 统一由它管理 ChromeDriver 的下载与更新，避免版本不匹配导致的 session not created 错误。
        driver_path = ChromeDriverManager().install()
        driver_instance = uc.Chrome(
            driver_executable_path=driver_path,
            options=options,
            use_subprocess=True,
            auto_update=False,  # 由 webdriver-manager 负责版本管理
        )
    else:
        logging.info("使用标准 Selenium Chrome 初始化浏览器")
        driver_instance = webdriver.Chrome(options=options)

    driver_instance.set_page_load_timeout(60)
    try:
        driver_instance.maximize_window()
    except Exception:
        pass

    # 对于标准 Selenium，尽量绕过 webdriver 检测；UC 自身已做处理，可跳过失败
    try:
        driver_instance.execute_script(
            "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
        )
    except Exception:
        pass

    return driver_instance


def _search_url(keyword: str) -> str:
    """构造知网搜索 URL：主题检索 korder=SU&kw=关键词；关键词检索 korder=KY&kw=关键词；作者 korder=AU&kw=关键词。"""
    base = 'https://kns.cnki.net/kns8s/defaultresult/index'
    k = KORDER.strip() if KORDER else 'SU'
    return f'{base}?korder={k}&kw={keyword}'


def _is_chinese_literature(title: str) -> bool:
    """
    根据文献标题判断是否为中文文献（筛掉外文文献）。
    规则：标题中至少包含一定数量的中文字符（CJK 统一汉字）则视为中文文献。
    """
    if not title or not title.strip():
        return False
    chinese_count = sum(
        1 for c in title
        if '\u4e00' <= c <= '\u9fff' or '\u3400' <= c <= '\u4dbf'
    )
    # 至少 2 个汉字视为中文文献，否则视为外文并筛掉
    return chinese_count >= 2


def _is_on_verify_page(driver: webdriver.Chrome) -> bool:
    """判断当前是否在知网安全验证（滑块）页面。"""
    try:
        return VERIFY_URL_MARKER in (driver.current_url or '')
    except Exception:
        return False


def wait_for_captcha_done(driver: webdriver.Chrome, timeout: float = CAPTCHA_WAIT_TIMEOUT) -> bool:
    """
    若当前在安全验证页，则等待用户完成滑块验证后再继续。
    :return: True 表示已离开验证页或未在验证页；False 表示超时仍停留在验证页。
    """
    if not _is_on_verify_page(driver):
        return True
    logging.info('检测到知网安全验证页，请在浏览器中完成「向右滑动」验证，完成后脚本将自动继续…')
    deadline = time.time() + timeout
    while time.time() < deadline:
        time.sleep(CAPTCHA_POLL_INTERVAL)
        try:
            if not _is_on_verify_page(driver):
                logging.info('验证已完成，继续执行。')
                return True
        except Exception:
            pass
    logging.warning('等待验证超时，请重试或关闭无头模式以便手动完成验证。')
    return False


def scrape_keyword(keyword: str, result_count: int) -> None:
    """
    根据关键词或主题爬取检索结果，仅保留中文文献，并只保存固定数量（由 result_count 决定）到 links/关键词.csv。
    搜索类型由 KORDER 控制：SU=主题检索（默认），KY=关键词检索，AU=作者等。
    会翻页直到凑足 result_count 篇中文文献（或无更多页）；写入 CSV 时最多保存 result_count 篇。若被重定向到安全验证页，会等待用户完成验证后再继续。

    :param keyword: 搜索关键词
    :param result_count: 要保存的中文文献固定数量（由 RESULT_COUNT 决定，如 60 篇）
    """
    # 先打开知网检索首页并刷新，再跳转到带关键词的检索 URL（与原 load_chrome_driver 中的逻辑一致）
    driver.get('https://kns.cnki.net/kns8s/defaultresult/index')
    driver.refresh()
    time.sleep(1)

    url = _search_url(keyword)
    driver.get(url)
    time.sleep(2)

    # 若被重定向到安全验证页，等待用户完成「向右滑动」验证
    if not wait_for_captcha_done(driver):
        logging.warning('未在限定时间内完成验证，当前关键词可能无法获取完整结果。')

    links: List[str] = []
    dates: List[str] = []
    names: List[str] = []

    # 仅保存中文文献，筛掉外文；翻页直到凑足 result_count 篇中文文献（或无更多页）。

    while len(links) < result_count:
        # 翻页后可能再次出现验证，先等待离开验证页再解析
        if _is_on_verify_page(driver):
            if not wait_for_captcha_done(driver):
                break
        page_source = driver.page_source
        soup = BeautifulSoup(page_source, 'html.parser')
        fz14_links = soup.select('.fz14')
        date_cells = soup.select('.date')

        # 遍历当前页面的所有搜索结果，只保留中文文献
        for link_tag, date_cell, name_tag in zip(fz14_links, date_cells, fz14_links):
            if len(links) >= result_count:
                break
            if not link_tag.has_attr('href'):
                continue
            name = name_tag.get_text(strip=True)
            if not _is_chinese_literature(name):
                continue
            date_text = date_cell.get_text(strip=True)
            year = date_text.split('-')[0]
            links.append(link_tag['href'])
            dates.append(year)
            names.append(name)

        if len(links) < result_count:
            if _is_on_verify_page(driver):
                if not wait_for_captcha_done(driver):
                    break
            try:
                next_button = WebDriverWait(driver, 10).until(
                    EC.presence_of_element_located((By.ID, 'PageNext'))
                )
                if 'disabled' in next_button.get_attribute('class'):
                    break
                next_button.click()
                time.sleep(1.5)
            except Exception as e:
                logging.error(f"翻页失败: {e}")
                if _is_on_verify_page(driver):
                    wait_for_captcha_done(driver)
                break

    # 只保存固定数量（由 result_count 决定）的中文文献到 CSV，超出部分不写入
    n_to_save = min(len(links), result_count)
    save_links = links[:n_to_save]
    save_dates = dates[:n_to_save]
    save_names = names[:n_to_save]

    output_file = os.path.join(LINK_DIR, f"{keyword}.csv")
    ensure_directory_exists(LINK_DIR)
    try:
        with open(output_file, 'w', encoding='utf-8-sig', newline='') as f:
            writer = csv.writer(f)
            writer.writerow(['name', 'year', 'url'])
            for link, year, name in zip(save_links, save_dates, save_names):
                writer.writerow([name, year, link])
        if n_to_save >= result_count:
            logging.info(f"关键词[{keyword}]：已保存 {n_to_save} 篇中文文献到 {output_file}（固定数量 {result_count} 篇）")
        else:
            logging.warning(f"关键词[{keyword}]：已保存 {n_to_save} 篇中文文献到 {output_file}（不足固定数量 {result_count} 篇，可能无更多中文结果）")
    except Exception as e:
        logging.error(f"写入链接 CSV 文件失败：{e}")


def _switch_to_main_window(driver: webdriver.Chrome, main_handle: str) -> None:
    """安全切回主窗口；若当前窗口已关闭，从当前 window_handles 中选第一个。"""
    try:
        driver.switch_to.window(main_handle)
        return
    except Exception:
        pass
    try:
        handles = driver.window_handles
        if handles:
            driver.switch_to.window(handles[0])
    except Exception as e:
        logging.debug(f"切回主窗口时忽略错误: {e}")


def _wait_download_captcha_solved(
    driver: webdriver.Chrome,
    captcha_handle: str,
    timeout: int = DOWNLOAD_CAPTCHA_WAIT_TIMEOUT
) -> bool:
    """
    下载阶段的拼图验证码等待逻辑：
    - 若窗口关闭，认为验证和下载已触发，返回 True；
    - 若窗口仍在，但页面中不再包含“拼图校验”，也认为验证已通过；
    - 超时仍停留在拼图页则返回 False。
    """
    start = time.time()
    while time.time() - start < timeout:
        time.sleep(DOWNLOAD_CAPTCHA_POLL_INTERVAL)
        try:
            handles = driver.window_handles
            if captcha_handle not in handles:
                return True
            driver.switch_to.window(captcha_handle)
            page_src = driver.page_source
            if "拼图校验" not in page_src:
                return True
        except Exception:
            # 窗口句柄失效/已关闭，也视为通过
            return True
    return False


def attempt_download(
    driver: webdriver.Chrome,
    link: str,
    index: int,
    name: str,
    year: str
) -> Tuple[bool, bool]:
    """
    尝试下载单篇文章，支持重试机制。
    通过多次刷新 + redirectNewLink() 绕过前端验证码。

    :return: (success, hit_captcha)
             success=True 表示认为下载已触发；
             hit_captcha=True 表示本次失败主要因为拼图验证码拦截。
    """
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            driver.get(link)
            time.sleep(1)

            # 通过页面中的 redirectNewLink() 函数跳过前端验证码
            try:
                driver.execute_script("redirectNewLink()")
            except Exception:
                pass

            # 多次刷新，模拟人类在详情页停留
            for _ in range(2):
                driver.refresh()
                time.sleep(1)
                try:
                    driver.execute_script("redirectNewLink()")
                except Exception:
                    pass

            time.sleep(0.5)

            css_selector = '.btn-dlpdf a' if FILE_TYPE == 'pdf' else '.btn-dlcaj a'
            link_element = WebDriverWait(driver, 10).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, css_selector))
            )
            download_link = link_element.get_attribute('href')
            if download_link:
                # 模拟鼠标移动并点击下载链接
                main_handle = driver.current_window_handle
                ActionChains(driver).move_to_element(link_element).click(link_element).perform()
                time.sleep(0.8)

                # 新标签可能在下载开始后被浏览器自动关闭，需安全切换并处理已关闭窗口
                try:
                    if len(driver.window_handles) <= 1:
                        # 未打开新窗口或新窗口已立即关闭，视为可能已触发下载，留在当前页
                        logging.info(f"{name} {year} 第 {index + 1} 篇：第 {attempt} 次尝试下载已触发（无新窗口或已关闭）")
                        return True, False
                    # 切换到新打开的窗口
                    new_handle = [h for h in driver.window_handles if h != main_handle][-1]
                    driver.switch_to.window(new_handle)
                    WebDriverWait(driver, 5).until(
                        EC.presence_of_element_located((By.TAG_NAME, 'html'))
                    )
                    # 新窗口可能在此刻已被关闭，获取 page_source 时可能抛 "target window already closed"
                    page_src = driver.page_source
                    if "拼图校验" in page_src:
                        logging.warning(f"{name} {year} 第 {index + 1} 篇：第 {attempt} 次尝试触发拼图验证码，等待验证结果…")
                        solved = _wait_download_captcha_solved(driver, new_handle)
                        if solved:
                            logging.info(f"{name} {year} 第 {index + 1} 篇：拼图验证已通过，认为下载已触发")
                            try:
                                driver.close()
                            except Exception:
                                pass
                            _switch_to_main_window(driver, main_handle)
                            return True, True

                        # 验证未在限定时间内完成，认为本次尝试因验证码失败
                        logging.warning(f"{name} {year} 第 {index + 1} 篇：拼图验证超时，本次尝试失败")
                        try:
                            driver.close()
                        except Exception:
                            pass
                        _switch_to_main_window(driver, main_handle)
                        return False, True
                    logging.info(f"{name} {year} 第 {index + 1} 篇：第 {attempt} 次尝试下载成功")
                    try:
                        driver.close()
                    except Exception:
                        pass
                    _switch_to_main_window(driver, main_handle)
                    return True, False
                except Exception as win_e:
                    err_msg = str(win_e).lower()
                    if "no such window" in err_msg or "target window already closed" in err_msg or "web view not found" in err_msg:
                        logging.warning(f"{name} {year} 第 {index + 1} 篇：新窗口已关闭（可能已开始下载），切回主窗口继续")
                        _switch_to_main_window(driver, main_handle)
                        return True, False
                    raise
        except Exception as e:
            logging.error(f"{name} {year} 第 {index + 1} 篇：第 {attempt} 次尝试出错: {e}")
            time.sleep(random.uniform(2, 4))

    # 多次重试仍失败，且未能确认是否因验证码导致
    return False, False


def parse_links_file(keyword: str) -> List[Tuple[str, str, str]]:
    """
    读取 links/<关键词>.csv 文件，解析为 (name, year, url) 列表。
    CSV 列至少包含：name, year, url。
    若不存在对应 CSV，则回退尝试解析旧版 TXT 文件（文献名 -||- 年代 -||- 详情页链接）。
    """
    csv_path = os.path.join(LINK_DIR, f"{keyword}.csv")
    txt_path = os.path.join(LINK_DIR, f"{keyword}.txt")

    entries: List[Tuple[str, str, str]] = []

    if os.path.exists(csv_path):
        try:
            with open(csv_path, 'r', encoding='utf-8-sig', newline='') as f:
                reader = csv.DictReader(f)
                for row in reader:
                    name = (row.get('name') or '').strip()
                    year = (row.get('year') or '').strip()
                    url = (row.get('url') or '').strip()
                    if not url:
                        continue
                    entries.append((name, year, url))
            logging.info(f"关键词[{keyword}]：从 {csv_path} 解析到 {len(entries)} 条链接")
            return entries
        except Exception as e:
            logging.error(f"解析链接 CSV 文件失败：{e}")


    logging.error(f"关键词[{keyword}] 的链接文件不存在：{csv_path} 或 {txt_path}")
    return entries


def download_by_keyword(keyword: str, driver: webdriver.Chrome) -> None:
    """
    为指定关键词下载文献。
    使用 links/<关键词>.csv 中的链接，并降低验证码出现概率。
    """
    entries = parse_links_file(keyword)
    if not entries:
        return

    # 所有关键词的文献统一保存到 SAVE_DIR 目录下
    output_dir = SAVE_DIR
    ensure_directory_exists(output_dir)
    logging.info(f"开始下载关键词[{keyword}]的文献，目标目录统一为：{output_dir}")

    num_success = 0
    num_skipped = 0
    consecutive_captchas = 0

    try:
        for idx, (name, year, url) in enumerate(entries):
            # 根据下载记录中的文献名称去重，避免重复下载
            if name and name in DOWNLOADED_NAMES:
                logging.info(
                    f"关键词[{keyword}]：第 {idx + 1} 篇 [{name}] {year} 已在 download_records.csv 中记录，按名称去重跳过下载"
                )
                continue

            # 下载前记录当前已有的文件，用于后续检测新增文件
            try:
                before_files = {
                    f for f in os.listdir(output_dir)
                    if f.lower().endswith('.pdf') or f.lower().endswith('.caj')
                }
            except FileNotFoundError:
                before_files = set()

            success, hit_captcha = attempt_download(driver, url, idx, name, year)

            if not success:
                num_skipped += 1
                if hit_captcha:
                    consecutive_captchas += 1
                else:
                    consecutive_captchas = 0
            else:
                num_success += 1
                consecutive_captchas = 0

                # 监测新下载的文件，并写入下载记录 CSV
                new_file_path = _detect_new_file(output_dir, before_files)
                if not new_file_path:
                    logging.warning(
                        f"关键词[{keyword}]：第 {idx + 1} 篇 [{name}] {year} 下载成功但未检测到新文件，将仅标记 URL 已下载。"
                    )
                    new_file_path = ''

                record = {
                    'keyword': keyword,
                    'name': name,
                    'year': year,
                    'url': url,
                    'file_path': new_file_path,
                    'created_at': datetime.now().isoformat(timespec='seconds'),
                }
                append_download_records([record])

            # 连续多篇因拼图验证码失败，尝试重启浏览器以“降温”
            if consecutive_captchas >= MAX_CONSECUTIVE_CAPTCHAS:
                logging.warning(
                    f"连续 {consecutive_captchas} 篇因拼图验证码失败，准备重启浏览器以降低拦截概率…"
                )
                try:
                    driver.quit()
                except Exception as e:
                    logging.debug(f"重启浏览器前关闭旧实例出错：{e}")
                driver = load_chrome_driver()
                consecutive_captchas = 0

            # 简单节流：每下载一定数量后进行一次较长休息
            if (idx + 1) % DOWNLOAD_BATCH_SIZE == 0:
                logging.info(
                    f"关键词[{keyword}]：已处理 {idx + 1} 篇，休息 {DOWNLOAD_BATCH_SLEEP} 秒以降低触发验证码概率…"
                )
                time.sleep(DOWNLOAD_BATCH_SLEEP)

    except Exception as e:
        logging.error(f"关键词[{keyword}] 下载过程中出现错误：{e}")

    logging.info(f"关键词[{keyword}] 下载结束：成功 {num_success} 篇，失败 {num_skipped} 篇。")


def main() -> None:
    """
    主函数：
    1. 兼容性迁移：如存在旧目录结构（根目录下的 saves/、links/、saves/download_records.csv），迁移到 cnki_pdfs 下；
    2. 先按关键词抓取知网搜索结果，生成 cnki_pdfs/links/<关键词>.csv（name, year, url）；
    3. 初始化下载记录：遍历 cnki_pdfs/saves 下所有 PDF/CAJ，与 cnki_pdfs/download_records.csv 一一对应；
    4. 再读取这些链接文件，批量下载文献，并在 download_records.csv 中记录，避免重复下载。
    """
    global driver
    # 确保基础目录、保存目录和链接目录存在
    ensure_directory_exists(BASE_DIR)
    ensure_directory_exists(SAVE_DIR)
    ensure_directory_exists(LINK_DIR)

    # 初始化下载记录：扫描 SAVE_DIR 目录并加载 download_records.csv，
    # 之后根据 URL 进行去重，避免重复下载。
    sync_existing_files_to_records()
    load_download_records()

    driver = load_chrome_driver()

    try:
        # 先抓取搜索结果链接
        for keyword in KEYWORDS:
            scrape_keyword(keyword, RESULT_COUNT)

        # 链接抓取完成后，按关键词批量下载文献
        for keyword in KEYWORDS:
            download_by_keyword(keyword, driver)
    finally:
        if driver:
            driver.quit()
            logging.info("驱动已关闭。")


if __name__ == "__main__":
    main()
