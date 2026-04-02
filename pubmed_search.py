"""
PubMed 搜索模块
通过关键词在 PubMed 搜索，获取文献的 DOI 等
"""
import requests
import time
import random
from typing import List, Dict, Optional
import xml.etree.ElementTree as ET

from llm_reference_parser import LLMReferenceParser


class PubMedSearcher:
    """PubMed搜索器，使用NCBI Entrez API"""
    
    BASE_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
    SEARCH_URL = f"{BASE_URL}/esearch.fcgi"
    FETCH_URL = f"{BASE_URL}/efetch.fcgi"
    
    def __init__(
        self,
        email: str = "your_email@example.com",
        api_key: Optional[str] = None,
        use_llm_for_references: bool = True,
        llm_reference_cache_path: Optional[str] = None,
    ):
        """
        初始化PubMed搜索器
        :param email: 你的邮箱（NCBI要求提供邮箱）
        :param api_key: 可选的API密钥（可提高请求速率限制）
        :param use_llm_for_references: 是否使用 LLM 解析 raw_citation（无 DOI/PMID 时）；关闭可加快测试、避免依赖通义 API
        :param llm_reference_cache_path: 可选，LLM 解析结果缓存 CSV 路径（如 literature_pdfs/llm_reference_cache.csv），命中则不再调 API
        """
        self.email = email
        self.api_key = api_key
        self.use_llm_for_references = use_llm_for_references
        # 有 API key 时 NCBI 允许 10 次/秒，否则 3 次/秒
        self.delay = 0.12 if api_key else 0.34

        # 仅当开启 LLM 时创建解析器；传入缓存路径则相同 raw_citation/title/pmid/doi 直接读缓存
        self.llm_reference_parser = (
            LLMReferenceParser(model="qwen-turbo", cache_path=llm_reference_cache_path)
            if use_llm_for_references
            else None
        )
        # BFS 时同一 PMID/标题可能被多次查询，缓存以避免重复请求
        self._pmid_cache: Dict[str, Optional[Dict]] = {}
        self._title_cache: Dict[str, Optional[Dict]] = {}
        self._cache_max = 5000  # 单次运行内缓存上限，超出后清空
    
    def search(
        self,
        query: str,
        max_results: int = 100,
        retstart: int = 0,
        random_start_max: int = 10,
    ) -> List[Dict]:
        """
        在PubMed中搜索文献
        :param query: 搜索关键词（如 "speech disorder"）
        :param max_results: 最大返回结果数
        :param retstart: 起始位置（用于分页）
        :param random_start_max: 在指定范围内随机选择起始位置
        :return: 文献信息列表，每个包含pmid, title, doi等
        """
        print(f"正在PubMed搜索：{query}")
        
        # 在random_start_max范围内随机一个起点，尽量避免每次都是第一页
        retstart = random.randint(0, random_start_max)
         
        # 第一步：搜索获取PMID列表
        search_params = {
            "db": "pubmed",
            "term": query,
            "retmode": "json",
            "retmax": max_results,
            "retstart": retstart,
            "email": self.email
        }
        if self.api_key:
            search_params["api_key"] = self.api_key
        
        try:
            response = requests.get(self.SEARCH_URL, params=search_params, timeout=30)
            response.raise_for_status()
            search_data = response.json()
                               
            pmids = search_data.get("esearchresult", {}).get("idlist", [])
            if not pmids:
                print("未找到相关文献")
                return []
            
            print(f"找到 {len(pmids)} 篇文献，正在获取详细信息...")
            time.sleep(self.delay)
            
            # 第二步：批量获取文献详细信息（包括DOI）
            articles = self._fetch_article_details(pmids)
            return articles
            
        except requests.exceptions.RequestException as e:
            print(f"PubMed搜索失败：{e}")
            return []
        except Exception as e:
            print(f"处理PubMed搜索结果时出错：{e}")
            return []
    
    def _fetch_article_details(self, pmids: List[str], batch_size: int = 200) -> List[Dict]:
        """
        根据PMID列表获取文献详细信息
        :param pmids: PMID列表
        :param batch_size: 每批处理的PMID数量（默认200，避免URL过长）
        :return: 文献信息列表
        """
        if not pmids:
            return []
        
        all_articles = []
        total_batches = (len(pmids) + batch_size - 1) // batch_size
        
        # 将PMID列表分成小批次处理，避免URL过长
        for batch_idx in range(0, len(pmids), batch_size):
            batch_pmids = pmids[batch_idx:batch_idx + batch_size]
            current_batch = (batch_idx // batch_size) + 1
            
            if total_batches > 1:
                print(f"  处理批次 {current_batch}/{total_batches} ({len(batch_pmids)} 个PMID)...")
            
            fetch_params = {
                "db": "pubmed",
                "id": ",".join(batch_pmids),
                "retmode": "xml",
                "email": self.email
            }
            if self.api_key:
                fetch_params["api_key"] = self.api_key
            
            try:
                response = requests.get(self.FETCH_URL, params=fetch_params, timeout=90)
                response.raise_for_status()
                time.sleep(self.delay)
                
                # 解析XML响应
                root = ET.fromstring(response.content)
                articles_elements = root.findall(".//PubmedArticle")
                n_articles = len(articles_elements)
                for i, article in enumerate(articles_elements):
                    if n_articles > 20 and (i + 1) % 50 == 0:
                        print(f"    已解析 {i + 1}/{n_articles} 篇...")
                    article_info = self._parse_article(article)
                    if article_info:
                        all_articles.append(article_info)
                
            except requests.exceptions.HTTPError as e:
                if e.response.status_code == 414:
                    print(f"  警告：批次 {current_batch} URL过长，尝试减小批次大小...")
                    # 如果仍然失败，尝试更小的批次（递归调用）
                    if batch_size > 50:
                        batch_articles = self._fetch_article_details(batch_pmids, batch_size // 2)
                        all_articles.extend(batch_articles)
                    else:
                        print(f"  错误：批次 {current_batch} 处理失败（URL仍然过长）")
                else:
                    print(f"  错误：批次 {current_batch} 获取文献详情失败：{e}")
            except Exception as e:
                print(f"  错误：批次 {current_batch} 处理失败：{e}")
        
        return all_articles

    def fetch_by_pmid(self, pmid: str) -> Optional[Dict]:
        """
        根据单个PMID获取文献详细信息（包括DOI、参考文献等）。结果会缓存，避免 BFS 中重复请求。
        :param pmid: PMID
        :return: 文献信息字典或None
        """
        if not pmid:
            return None
        pk = str(pmid).strip()
        if pk in self._pmid_cache:
            return self._pmid_cache[pk]
        if len(self._pmid_cache) >= self._cache_max:
            self._pmid_cache.clear()

        fetch_params = {
            "db": "pubmed",
            "id": str(pmid),
            "retmode": "xml",
            "email": self.email,
        }
        if self.api_key:
            fetch_params["api_key"] = self.api_key

        try:
            response = requests.get(self.FETCH_URL, params=fetch_params, timeout=60)
            response.raise_for_status()
            time.sleep(self.delay)

            root = ET.fromstring(response.content)
            article = root.find(".//PubmedArticle")
            if article is None:
                self._pmid_cache[pk] = None
                return None
            result = self._parse_article(article)
            self._pmid_cache[pk] = result
            return result
        except Exception as e:
            print(f"根据PMID获取文献失败（PMID={pmid}）：{e}")
            self._pmid_cache[pk] = None
            return None

    def find_article_by_title(self, title: str) -> Optional[Dict]:
        """
        通过标题在 Crossref API 中查找文献，返回最相似的一篇（含 DOI、作者、期刊、出版年份等）。
        用于补全仅有标题的参考文献的 DOI。API: https://api.crossref.org/works?query.title=TITLE
        :param title: 文献标题（中英文均可）
        :return: 与 PubMed 文献信息结构兼容的字典（doi, title, journal, author, year, references），或 None
        """
        if not title or not title.strip():
            return None
        key = title.strip().lower()[:200]  # 归一化并截断，避免 key 过长
        if key in self._title_cache:
            return self._title_cache[key]
        if len(self._title_cache) >= self._cache_max:
            self._title_cache.clear()

        url = "https://api.crossref.org/works"
        params = {
            "query.title": title.strip(),
            "rows": 1,  # 只需最相似一条，减少响应体积与延迟
        }

        try:
            response = requests.get(url, params=params, timeout=30)
            response.raise_for_status()
            data = response.json()
            items = data.get("message", {}).get("items", [])
            if not items:
                self._title_cache[key] = None
                return None

            first = items[0]
            raw_title = first.get("title", [""])
            title_str = raw_title[0] if raw_title else ""
            doi = first.get("DOI")
            if not doi:
                self._title_cache[key] = None
                return None

            # 期刊/容器标题
            container = first.get("container-title", [""])
            journal = container[0] if container else ""

            # 出版年份：优先 published-print，否则 issued
            year = None
            for key in ("published-print", "published", "issued", "published-online"):
                parts = first.get(key, {}).get("date-parts", [[]])
                if parts and parts[0]:
                    year = parts[0][0] if parts[0][0] is not None else None
                    break

            # 作者：格式化为 "LastName FirstName" 或 "Family Given"
            author_parts = []
            for author in first.get("author", [])[:5]:
                family = author.get("family", "")
                given = author.get("given", "")
                if family or given:
                    author_parts.append(f"{family} {given}".strip())
            author_str = "; ".join(author_parts) if author_parts else ""

            out = {
                "doi": doi,
                "title": title_str,
                "journal": journal,
                "author": author_str,
                "year": str(year) if year is not None else "",
                "pmid": "",
                "references": [],
            }
            self._title_cache[key] = out
            return out
        except requests.exceptions.RequestException as e:
            print(f"根据标题在 Crossref 查找文献失败（网络/请求）：{e}")
            self._title_cache[key] = None
            return None
        except Exception as e:
            print(f"根据标题在 Crossref 查找文献失败：{e}")
            self._title_cache[key] = None
            return None

    def parse_references(self, article_element) -> List[Dict]:
        """
        从 PubMed 的 PubmedArticle XML 元素中解析参考文献列表。
        当 use_llm_for_references=True 时才调用通义大模型。
        关闭 LLM 时，仅用 raw_citation 作为 title，便于全流程测试且不依赖 API。

        :param article_element: PubmedArticle XML 元素
        :return: 参考文献列表，每条包含 title/raw_citation/pmid/doi/author/journal
        """
        references: List[Dict] = []

        import re

        # 参考文献在 PubmedData/ReferenceList/Reference 结构中
        for ref in article_element.findall(".//PubmedData/ReferenceList/Reference"):
            # PubMed 在 Reference 里通常只给一个整体的 Citation 字符串
            ref_citation_elem = ref.find("Citation")
            raw_citation = (
                (ref_citation_elem.text or "").strip()
                if ref_citation_elem is not None
                else ""
            )

            if self.use_llm_for_references:
                parsed = self.llm_reference_parser.parse(
                    raw_citation=raw_citation
                )
            else:
                # 未启用 LLM 时仅用 raw_citation 作为 title，供后续按标题检索
                parsed = {
                    "title": raw_citation,
                    "doi": "",
                    "pmid": "",
                    "author": "",
                    "journal": "",
                }

            # 只要有任意一项信息就记录下来
            if raw_citation:
                references.append(
                    {
                        "title": parsed.get("title") or raw_citation,
                        "raw_citation": raw_citation,
                        "pmid": parsed.get("pmid") or "",
                        "doi": parsed.get("doi") or "",
                        "author": parsed.get("author") or "",
                        "journal": parsed.get("journal") or "",
                    }
                )

        return references

    def _parse_article(self, article_element) -> Optional[Dict]:
        """
        解析单个文献的XML元素，提取DOI、参考文献等信息
        :param article_element: XML元素
        :return: 文献信息字典
        """
        try:
            # 提取PMID
            pmid_elem = article_element.find(".//PMID")
            pmid = pmid_elem.text if pmid_elem is not None else ""
            
            # 提取标题
            title_elem = article_element.find(".//ArticleTitle")
            title = title_elem.text if title_elem is not None else ""
            
            # 提取DOI（可能在多个位置）
            doi = None
            # 方法1：从ArticleIdList中查找
            for article_id in article_element.findall(".//ArticleId"):
                if article_id.get("IdType") == "doi":
                    doi = article_id.text
                    break
            
            # 方法2：如果方法1没找到，尝试从ELocationID查找
            if not doi:
                for eloc in article_element.findall(".//ELocationID"):
                    if eloc.get("EIdType") == "doi":
                        doi = eloc.text
                        break
            
            # 提取期刊信息
            journal_elem = article_element.find(".//Journal/Title")
            journal = journal_elem.text if journal_elem is not None else ""
            
            # 提取作者（第一个作者）
            author_list = article_element.find(".//AuthorList/Author")
            author = ""
            if author_list is not None:
                last_name = author_list.find("LastName")
                first_name = author_list.find("ForeName")
                if last_name is not None and first_name is not None:
                    author = f"{last_name.text} {first_name.text}"
            
            # 提取发表年份
            year_elem = article_element.find(".//PubDate/Year")
            year = year_elem.text if year_elem is not None else ""

            # 提取参考文献列表（单独封装为成员函数，便于复用）
            references = self.parse_references(article_element)
            
            return {
                "pmid": pmid,
                "title": title,
                "doi": doi,
                "journal": journal,
                "author": author,
                "year": year,
                "references": references,
            }
            
        except Exception as e:
            print(f"解析文献信息时出错：{e}")
            return None
    
    def search_and_save_doi(self, query: str, output_csv: str, max_results: int = 100):
        """
        搜索并保存DOI到CSV文件
        :param query: 搜索关键词
        :param output_csv: 输出CSV文件路径
        :param max_results: 最大结果数
        """
        import pandas as pd
        
        articles = self.search(query, max_results)
        
        if not articles:
            print("未找到任何文献")
            return
        
        # 过滤出有DOI的文献
        articles_with_doi = [a for a in articles if a.get("doi")]
        print(f"\n共找到 {len(articles)} 篇文献，其中 {len(articles_with_doi)} 篇有DOI")
        
        # 保存到CSV
        df = pd.DataFrame(articles_with_doi)
        df.to_csv(output_csv, index=False, encoding="utf-8-sig")
        print(f"DOI列表已保存到：{output_csv}")
        
        return articles_with_doi
