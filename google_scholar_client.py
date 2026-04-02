"""
Google Scholar API 客户端封装
基于 searchapi.io 的 Google Scholar 接口，通过文献标题尝试获取 PDF 并下载
"""
import logging
import time
from pathlib import Path
from typing import Optional, Dict, Any, List

import requests

from oa_downloader import OADownloader
from utils import generate_filename

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


class GoogleScholarClient:
    """Google Scholar API 客户端（searchapi.io 封装）"""

    BASE_URL = "https://www.searchapi.io/api/v1/search"

    def __init__(
        self,
        api_key: str,
        save_dir: str = "literature_pdfs/google_scholar",
        timeout: int = 60,
        delay: float = 1.0,
        selenium_headless: bool = True,
    ):
        """
        :param api_key: searchapi.io API Key
        :param save_dir: 通过 Google Scholar 下载的 PDF 保存目录
        :param timeout: 网络请求超时时间
        :param delay: 请求间延迟，避免触发限流
        :param selenium_headless: Scholar 兜底用 Selenium 时是否无头（服务器/SSH 建议 True）
        """
        self.api_key = api_key
        self.save_dir = Path(save_dir)
        self.save_dir.mkdir(parents=True, exist_ok=True)
        self.timeout = timeout
        self.delay = delay
        self.selenium_headless = selenium_headless
        # 在直接下载失败时用 undetected-chromedriver 再尝试一次
        self.oa_downloader = OADownloader(
            download_dir=self.save_dir,
            email="",
            timeout=self.timeout,
            delay=self.delay,
            selenium_headless=selenium_headless
        )


    @staticmethod
    def _pick_best_resource_link(data: Any) -> Optional[str]:
        """
        从 organic_results 中优先选择 resource.format 为 PDF 的 link，
        若没有 PDF，则退而求其次选择第一个有 resource.link 的结果。
        """
        try:
            organic_results = (data or {}).get("organic_results") or []
            if not isinstance(organic_results, list):
                return None

            pdf_link: Optional[str] = None
            first_any_link: Optional[str] = None

            for item in organic_results:
                resource = (item or {}).get("resource") or {}
                link = resource.get("link")
                fmt = (resource.get("format") or "").lower()
                if not link:
                    continue

                if first_any_link is None:
                    first_any_link = link

                if fmt == "pdf":
                    pdf_link = link
                    break

            return pdf_link or first_any_link
        except Exception:
            return None

    def download_by_title(
        self,
        title: str,
        doi: Optional[str] = None,
        year: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        使用 Google Scholar API 根据标题搜索并尝试下载 PDF

        :param title: 文献标题
        :param doi: 文献 DOI（用于生成文件名，可选）
        :param year: 年份（可选）
        :return: 结果字典：{
            'success': bool,
            'filepath': Optional[str],
            'error': Optional[str],
        }
        """
        result: Dict[str, Any] = {
            "success": False,
            "filepath": None,
            "error": None,
        }

        title = (title or "").strip()
        if not title:
            result["error"] = "标题为空，无法调用 Google Scholar API"
            return result

        if not self.api_key:
            result["error"] = "未配置 Google Scholar API Key"
            return result

        params = {
            "api_key": self.api_key,
            "engine": "google_scholar",
            "q": title,
        }

        logger.info(f"【Google Scholar】开始根据标题搜索(使用 searchapi.io): {title}...")
        try:
            resp = requests.get(self.BASE_URL, params=params, timeout=self.timeout)
            resp.raise_for_status()
            data = resp.json()
            # 先按 organic_results.resource 选择最优链接
            candidate_url = self._pick_best_resource_link(data)
            if not candidate_url:
                result["error"] = "Google Scholar 搜索结果中未找到可用资源链接"
                logger.warning(result["error"])
                return result

            logger.info(f"【Google Scholar】选择候选资源链接(resource.link): {candidate_url}")

            # 生成文件名：优先使用 DOI，其次标题
            base_id = doi if doi else title
            filename = generate_filename(base_id, year, "google_scholar")
            save_path = self.save_dir / filename

            # 已存在则直接认为成功
            if save_path.exists():
                logger.info(f"【Google Scholar】文件已存在，跳过下载: {save_path}")
                result["success"] = True
                result["filepath"] = str(save_path)
                return result

            # 第一步：无论 resource.format 是 PDF / HTML / 其它，先直接尝试下载
            direct_ok = self.oa_downloader.download_pdf_direct(
                candidate_url,
                save_path,
                timeout=self.timeout,
                delay=self.delay,
            )

            if direct_ok:
                logger.info(f"【Google Scholar】直接下载成功(HTTP直连下载): {save_path}")
                result["success"] = True
                result["filepath"] = str(save_path)
                return result
            
            # 第二步：使用uc进行下载
            logger.info("【Google Scholar】直接下载失败，将使用 undetected-chromedriver 下载")
            
            selenium_path = self.oa_downloader._download_with_selenium(
                pdf_url=candidate_url,
                doi=base_id,
                year=year,
                source="google_scholar",
            )
            if selenium_path and Path(selenium_path).exists():
                logger.info(
                    f"【Google Scholar】Selenium 下载成功(undetected-chromedriver): {selenium_path}"
                )
                result["success"] = True
                result["filepath"] = str(selenium_path)
                return result
        except Exception as e:
            result["error"] = f"调用 Google Scholar API 失败: {e}"
            logger.error(result["error"])
        finally:
            time.sleep(self.delay)
        result["error"] = "Google Scholar 直接下载与 Selenium 下载均失败"
        logger.warning(f"【Google Scholar】{result['error']}")
        return result

