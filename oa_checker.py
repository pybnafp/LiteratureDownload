"""
OA（开放获取）判定模块
整合 Unpaywall、Crossref、PMC、Europe PMC 四类数据源以判断是否为OA，并尽可能返回可下载链接
"""
import logging
import time
from typing import Optional, Dict

import requests

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


class OAChecker:
    """统一OA判定器"""
    
    def __init__(self, email: str = "your_email@example.com", timeout: int = 60, delay: float = 0.34):
        """
        :param email: 用于Unpaywall/Crossref的User-Agent/参数
        :param timeout: 网络请求超时
        :param delay: 针对API限速的轻微延迟（NCBI建议每秒≤3次）
        """
        self.email = email
        self.timeout = timeout
        self.delay = delay
    
    def _get_headers(self) -> Dict[str, str]:
        """
        生成请求headers，模拟真实浏览器请求以避免IP封禁
        """
        return {
            'User-Agent': f'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36 (mailto:{self.email})',
            'Accept': 'application/json, text/plain, */*',
            'Accept-Language': 'en-US,en;q=0.9,zh-CN;q=0.8,zh;q=0.7',
            'Accept-Encoding': 'gzip, deflate, br',
            'Connection': 'keep-alive',
            'Referer': 'https://www.google.com/',
            'Sec-Fetch-Dest': 'empty',
            'Sec-Fetch-Mode': 'cors',
            'Sec-Fetch-Site': 'cross-site',
        }
    
    @staticmethod
    def _clean_doi(doi: str) -> str:
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
    
    def check_unpaywall(self, doi: str) -> Optional[Dict]:
        """
        Unpaywall: https://api.unpaywall.org/v2/{DOI}?email={email}
        :param doi: 文献DOI
        :return: 包含OA检查结果的字典，如果检查失败则返回None
        """
        # clean_doi = self._clean_doi(doi)
        url = f"https://api.unpaywall.org/v2/{doi}?email={self.email}"
        headers = self._get_headers()
        logger.info(f"【OA检查-Unpaywall】开始检查 DOI: {doi}")
        try:
            resp = requests.get(url, headers=headers, timeout=self.timeout)
            resp.raise_for_status()
            data = resp.json()
            is_oa = bool(data.get("is_oa"))
            best = data.get("best_oa_location") or {}
            # 规范要求使用 best_oa_location.url，同时兼容 url_for_pdf/url_for_landing_page
            best_url = best.get("url") or best.get("url_for_pdf") or best.get("url_for_landing_page")
            result = {
                "source": "unpaywall",
                "is_oa": is_oa,
                "url": best_url,
                "license": best.get("license"),
                "raw": data
            }
            logger.info(f"【OA检查-Unpaywall】检查完成 - 是否OA: {is_oa}, 有URL: {bool(best_url)}")
            return result
        except Exception as e:
            logger.info(f"【OA检查-Unpaywall】检查失败: {e}")
            return None
        finally:
            time.sleep(self.delay)
    
    def check_crossref(self, doi: str) -> Optional[Dict]:
        """Crossref: https://api.crossref.org/works/{DOI}"""
        # clean_doi = self._clean_doi(doi)
        url = f"https://api.crossref.org/works/{doi}"
        logger.info(f"【OA检查-Crossref】开始检查 DOI: {doi}")
        try:
            resp = requests.get(url, headers=self._get_headers(), timeout=self.timeout)
            resp.raise_for_status()
            data = resp.json()
            message = data.get("message", {}) if isinstance(data, dict) else {}
            access = message.get("access", {})
            is_open_access = (isinstance(access, dict) and access.get("type") == "open") or bool(message.get("license"))
            # 尝试取到可能的PDF直链
            pdf_url = None
            links = message.get("link", []) or []
            for link in links:
                ct = (link.get("content-type") or "").lower()
                u = link.get("URL")
                if ("pdf" in ct) or (u and ".pdf" in u.lower()):
                    pdf_url = u
                    break
            result = {
                "source": "crossref",
                "is_oa": bool(is_open_access),
                "url": pdf_url,
                "license": (message.get("license", [{}]) or [{}])[0].get("URL") if message.get("license") else None,
                "raw": message
            }
            logger.info(f"【OA检查-Crossref】检查完成 - 是否OA: {bool(is_open_access)}, 有URL: {bool(pdf_url)}")
            return result
        except Exception as e:
            logger.debug(f"【OA检查-Crossref】检查失败: {e}")
            return None
        finally:
            time.sleep(self.delay)
    
    def check_pmc(self, pmid: Optional[str]) -> Optional[Dict]:
        """PMC E-utilities esummary: https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi?db=pmc&id={PMID}&retmode=json"""
        if not pmid:
            logger.info(f"【OA检查-PMC】跳过检查 (无PMID)")
            return None
        url = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi"
        params = {
            "db": "pmc",
            "id": pmid,
            "retmode": "json"
        }
        logger.info(f"【OA检查-PMC】开始检查 PMID: {pmid}")
        try:
            resp = requests.get(url, params=params, headers=self._get_headers(), timeout=self.timeout)
            resp.raise_for_status()
            data = resp.json()
            result_obj = (data.get("result") or {})
            # esummary返回的键通常包含 "uids": ["XXXX"], 然后每个UID是对象
            uids = result_obj.get("uids") or []
            open_access_flag = False
            pdf_url = None
            pmcid = None
            for uid in uids:
                rec = result_obj.get(str(uid)) or {}
                # 规范中提到了 open_access 字段
                # 不同返回结构可能为 "isOpenAccess" 或 "open_access"，这里尽量兼容
                open_access_flag = bool(rec.get("open_access") or rec.get("isOpenAccess") or rec.get("is_open_access")) or open_access_flag
                pmcid = rec.get("pmcid") or pmcid
            if pmcid:
                pdf_url = f"https://www.ncbi.nlm.nih.gov/pmc/articles/{pmcid}/pdf"
            result = {
                "source": "pmc",
                "is_oa": open_access_flag,
                "url": pdf_url,
                "license": None,
                "raw": result_obj
            }
            logger.info(f"【OA检查-PMC】检查完成 - 是否OA: {open_access_flag}, PMCID: {pmcid}, 有URL: {bool(pdf_url)}")
            return result
        except Exception as e:
            logger.debug(f"【OA检查-PMC】检查失败: {e}")
            return None
        finally:
            time.sleep(self.delay)
    
    def check_europe_pmc(self, doi: Optional[str] = None, pmid: Optional[str] = None, title: Optional[str] = None) -> Optional[Dict]:
        """Europe PMC: https://www.ebi.ac.uk/europepmc/webservices/rest/search?query={}&resulttype=core"""
        # 优先使用 DOI，其次 PMID，再次标题
        query = None
        if doi:
            query = doi
            query_type = "DOI"
        elif pmid:
            query = pmid
            query_type = "PMID"
        elif title:
            query = title
            query_type = "Title"
        if not query:
            logger.info(f"【OA检查-Europe PMC】跳过检查 (无查询参数)")
            return None
        params = {
            "query": query,
            "resulttype": "core",
            "format": "json"
        }
        url = "https://www.ebi.ac.uk/europepmc/webservices/rest/search"
        logger.info(f"【OA检查-Europe PMC】开始检查 {query_type}: {query}")
        try:
            resp = requests.get(url, params=params, headers=self._get_headers(), timeout=self.timeout)
            resp.raise_for_status()
            data = resp.json()
            results = (((data or {}).get("resultList") or {}).get("result")) or []
            if not results:
                result = {
                    "source": "europe_pmc",
                    "is_oa": False,
                    "url": None,
                    "license": None,
                    "raw": data
                }
                logger.info(f"【OA检查-Europe PMC】检查完成 - 未找到结果")
                return result
            rec = results[0]
            is_open = False if rec.get("isOpenAccess") == 'N' else True
            pdf_url = None
            if rec.get("hasPDF") == 'Y':
                ft = rec.get("fullTextUrlList", {}) or {}
                ft_list = ft.get("fullTextUrl", []) or []
                for item in ft_list:
                    if (item.get("documentStyle") or "").lower() == "pdf":
                        loc = item.get("url")
                        if loc:
                            pdf_url = loc
                            break
            result = {
                "source": "europe_pmc",
                "is_oa": is_open,
                "url": pdf_url,
                "license": rec.get("license"),
                "raw": rec
            }
            logger.info(f"【OA检查-Europe PMC】检查完成 - 是否OA: {is_open}, 有URL: {bool(pdf_url)}")
            return result
        except Exception as e:
            logger.debug(f"【OA检查-Europe PMC】检查失败: {e}")
            return None
        finally:
            time.sleep(self.delay)
    
    def check_oa(self, doi: str, pmid: Optional[str] = None, title: Optional[str] = None) -> Dict:
        """
        综合判定OA。优先顺序：
        1) Unpaywall（权威、直接返回最优免费链接）
        2) PMC（医学OA收录）
        3) Europe PMC（欧洲覆盖）
        4) Crossref（用于许可/开放标签确认，偶尔可取到PDF）
        """
        logger.info(f"【OA检查-综合判定】开始综合判定OA状态 - DOI: {doi}")
        
        # 1) Unpaywall
        logger.info(f"【OA检查-综合判定】[1/4] 尝试Unpaywall...")
        upw = self.check_unpaywall(doi)
        if upw and upw.get("is_oa"):
            logger.info(f"【OA检查-综合判定】✓ Unpaywall确认OA，返回结果")
            return upw
        logger.info(f"【OA检查-综合判定】✗ Unpaywall未确认OA或检查失败")
        
        # 2) PMC（若提供PMID）
        logger.info(f"【OA检查-综合判定】[2/4] 尝试PMC...")
        pmc_res = self.check_pmc(pmid)
        if pmc_res and pmc_res.get("is_oa"):
            logger.info(f"【OA检查-综合判定】✓ PMC确认OA，返回结果")
            return pmc_res
        logger.info(f"【OA检查-综合判定】✗ PMC未确认OA或检查失败")
        
        # 3) Europe PMC
        logger.info(f"【OA检查-综合判定】[3/4] 尝试Europe PMC...")
        eu_res = self.check_europe_pmc(doi=doi, pmid=pmid, title=title)
        if eu_res and eu_res.get("is_oa"):
            logger.info(f"【OA检查-综合判定】✓ Europe PMC确认OA，返回结果")
            return eu_res
        logger.info(f"【OA检查-综合判定】✗ Europe PMC未确认OA或检查失败")
        
        # 4) Crossref
        logger.info(f"【OA检查-综合判定】[4/4] 尝试Crossref...")
        cr = self.check_crossref(doi)
        if cr and cr.get("is_oa"):
            logger.info(f"【OA检查-综合判定】✓ Crossref确认OA，返回结果")
            return cr
        logger.info(f"【OA检查-综合判定】✗ Crossref未确认OA或检查失败")
        
        # 全部否定或失败：返回最后一次成功的非OA信息或统一否定
        final_result = {
            "source": "unknown",
            "is_oa": False,
            "url": None,
            "license": None,
            "raw": None
        }
        logger.info(f"【OA检查-综合判定】所有方法均未确认OA，返回非OA结果")
        return final_result


