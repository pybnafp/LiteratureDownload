"""
基于通义大模型（DashScope）的参考文献解析器。

功能：
- 输入一条原始参考文献字符串 raw_citation（通常为英文引用格式）；
- 使用通义大模型提取：纯标题 title、DOI 号 doi、PMID 号 pmid、作者 author、期刊信息 journal；
- 返回一个字典，供上层调用。
- 可选：将解析结果缓存到 CSV，以 raw_citation/title/pmid/doi 为标识符复用，减少重复调用。

注意：
- 需要安装 dashscope SDK（pip install dashscope）；
- 推荐通过环境变量 DASHSCOPE_API_KEY 提供 API Key。
"""

from typing import Optional, Dict
from http import HTTPStatus
import json
import logging
import os
import re
from pathlib import Path

logger = logging.getLogger(__name__)

try:
    import dashscope
except ImportError:  # 在未安装 dashscope 时保持兼容
    dashscope = None
    logger.warning("未安装 dashscope SDK，LLMReferenceParser 将回退为普通解析。")

# CSV 缓存列名（与 literature_pdfs 下 llm_reference_cache.csv 一致）
CACHE_COLUMNS = ["raw_citation", "title", "pmid", "doi", "author", "journal"]


def _norm(s: str) -> str:
    """归一化用于缓存 key：去首尾空白、合并连续空白。"""
    if not s or not isinstance(s, str):
        return ""
    return re.sub(r"\s+", " ", s.strip())


class LLMReferenceParser:
    """封装通义大模型调用的参考文献解析器类，支持 CSV 结果缓存。"""

    def __init__(
        self,
        api_key: Optional[str] = None,
        model: str = "qwen-turbo",
        cache_path: Optional[str] = None,
    ):
        """
        :param api_key: DashScope API Key，可为空；为空时从环境变量 DASHSCOPE_API_KEY 读取
        :param model: 使用的通义模型，默认 qwen-turbo（速度优先）；可选 qwen-plus / qwen-max
        :param cache_path: 可选，LLM 解析结果缓存 CSV 的路径（如 literature_pdfs/llm_reference_cache.csv）
        """
        self.model = model
        self.api_key = os.getenv("DASHSCOPE_API_KEY") or None
        self.cache_path = Path(cache_path) if cache_path else None
        # 以 raw_citation 为主键的缓存行；以及 title/pmid/doi -> 主键 raw_citation 的索引，便于“任一标识符相同即命中”
        self._cache_by_raw: Dict[str, Dict] = {}
        self._cache_by_title: Dict[str, str] = {}
        self._cache_by_pmid: Dict[str, str] = {}
        self._cache_by_doi: Dict[str, str] = {}
        if self.cache_path:
            self._load_cache()

    def _load_cache(self) -> None:
        """从 CSV 加载已解析结果，建立 raw_citation/title/pmid/doi 索引。"""
        if not self.cache_path or not self.cache_path.exists():
            return
        try:
            import csv
            with open(self.cache_path, "r", encoding="utf-8-sig", newline="") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    raw = _norm(row.get("raw_citation", ""))
                    if not raw:
                        continue
                    title = _norm(row.get("title", ""))
                    pmid = _norm(row.get("pmid", ""))
                    doi = _norm(row.get("doi", ""))
                    entry = {
                        "title": row.get("title", ""),
                        "doi": row.get("doi", ""),
                        "pmid": row.get("pmid", ""),
                        "author": row.get("author", ""),
                        "journal": row.get("journal", ""),
                    }
                    self._cache_by_raw[raw] = entry
                    if title:
                        self._cache_by_title[title] = raw
                    if pmid:
                        self._cache_by_pmid[pmid] = raw
                    if doi:
                        self._cache_by_doi[doi] = raw
            logger.info("已从 %s 加载 LLM 参考文献解析缓存，共 %d 条", self.cache_path, len(self._cache_by_raw))
        except Exception as e:
            logger.warning("加载 LLM 解析缓存失败 %s: %s", self.cache_path, e)

    def _lookup_cache(self, raw_citation: str, ref_doi: str = "", ref_pmid: str = "") -> Optional[Dict]:
        """按 raw_citation / title / pmid / doi 任一匹配查找缓存，返回 dict(title, doi, pmid, author, journal) 或 None。"""
        raw = _norm(raw_citation)
        if not raw and not ref_doi and not ref_pmid:
            return None
        key_raw = self._cache_by_raw.get(raw) if raw else None
        if key_raw is not None:
            return dict(key_raw)
        ref_pmid_n = _norm(ref_pmid)
        if ref_pmid_n:
            raw_k = self._cache_by_pmid.get(ref_pmid_n)
            if raw_k is not None and raw_k in self._cache_by_raw:
                return dict(self._cache_by_raw[raw_k])
        ref_doi_n = _norm(ref_doi)
        if ref_doi_n:
            raw_k = self._cache_by_doi.get(ref_doi_n)
            if raw_k is not None and raw_k in self._cache_by_raw:
                return dict(self._cache_by_raw[raw_k])
        return None

    def _save_to_cache(self, raw_citation: str, result: Dict) -> None:
        """将一条解析结果追加到 CSV 并更新内存索引。"""
        if not self.cache_path:
            return
        raw = _norm(raw_citation)
        if not raw:
            return
        title = _norm(result.get("title", ""))
        pmid = _norm(result.get("pmid", ""))
        doi = _norm(result.get("doi", ""))
        entry = {
            "title": result.get("title", ""),
            "doi": result.get("doi", ""),
            "pmid": result.get("pmid", ""),
            "author": result.get("author", ""),
            "journal": result.get("journal", ""),
        }
        self._cache_by_raw[raw] = entry
        if title:
            self._cache_by_title[title] = raw
        if pmid:
            self._cache_by_pmid[pmid] = raw
        if doi:
            self._cache_by_doi[doi] = raw
        try:
            import csv
            self.cache_path.parent.mkdir(parents=True, exist_ok=True)
            file_exists = self.cache_path.exists()
            with open(self.cache_path, "a", encoding="utf-8-sig", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=CACHE_COLUMNS)
                if not file_exists:
                    writer.writeheader()
                writer.writerow({
                    "raw_citation": raw_citation,
                    "title": entry["title"],
                    "pmid": entry["pmid"],
                    "doi": entry["doi"],
                    "author": entry["author"],
                    "journal": entry["journal"],
                })
        except Exception as e:
            logger.warning("写入 LLM 解析缓存失败 %s: %s", self.cache_path, e)

    def _build_messages(self, raw_citation: str, ref_doi: str = "", ref_pmid: str = ""):
        """构造简短对话消息，仅用于提取参考文献结构化字段，减少 token 与延迟。"""
        user_parts = [
            "从下列英文参考文献中提取 JSON，仅含字段: title, doi, pmid, author, journal。",
            "无则填空字符串。只输出一个 JSON，无解释。",
            f"Ref: {raw_citation}",
        ]
        if ref_doi or ref_pmid:
            user_parts.append(f"(已知: doi={ref_doi or ''}, pmid={ref_pmid or ''})")
        return [
            {"role": "system", "content": "Output a single valid JSON object only."},
            {"role": "user", "content": " ".join(user_parts)},
        ]

    def parse(self, raw_citation: str, ref_doi: str = "", ref_pmid: str = "") -> Dict:
        """
        使用大模型从 raw_citation 中提取结构化信息。

        :param raw_citation: 原始引用字符串
        :param ref_doi: 从结构化 XML 中已提取到的 DOI（如果有）
        :param ref_pmid: 从结构化 XML 中已提取到的 PMID（如果有）
        :return: dict(title, doi, pmid, author, journal)
        """
        # 默认结果：保持兼容性，即使大模型不可用也有合理输出
        result = {
            "title": raw_citation or "",
            "doi": ref_doi or "",
            "pmid": ref_pmid or "",
            "author": "",
            "journal": "",
        }

        if not raw_citation:
            return result

        # 若启用 CSV 缓存，先按 raw_citation / pmid / doi 任一匹配查找
        if self.cache_path:
            cached = self._lookup_cache(raw_citation, ref_doi, ref_pmid)
            if cached is not None:
                out = dict(result)
                out.update(cached)
                if ref_doi:
                    out["doi"] = ref_doi
                if ref_pmid:
                    out["pmid"] = ref_pmid
                return out

        # 若未安装 dashscope 或未配置 API Key，直接返回默认结果
        if dashscope is None or not self.api_key:
            logger.warning("dashscope SDK 不可用或未配置 DASHSCOPE_API_KEY，使用原始引用作为 title。")
            return result

        try:
            messages = self._build_messages(raw_citation, ref_doi, ref_pmid)
            # 按用户给出的官方示例方式调用：在 call 中显式传入 api_key，
            # 并要求返回 JSON 对象格式的 message.content。
            resp = dashscope.Generation.call(
                api_key=self.api_key,
                model=self.model,
                messages=messages,
                result_format="message",
                response_format={"type": "json_object"},
            )

            status_code = getattr(resp, "status_code", None)
            if status_code != HTTPStatus.OK:
                logger.warning(
                    "调用通义大模型失败，status=%s, code=%s, message=%s",
                    status_code,
                    getattr(resp, "code", ""),
                    getattr(resp, "message", ""),
                )
                return result

            # 官方示例：resp.output.choices[0].message.content 为 JSON 字符串
            choice = resp.output.choices[0]
            # 兼容字典或对象两种结构
            if isinstance(choice, dict):
                content = choice["message"]["content"]
            else:
                content = choice.message.content
            data = json.loads(content)

            title = (data.get("title") or "").strip()
            doi = (data.get("doi") or "").strip()
            pmid = (data.get("pmid") or "").strip()
            author = (data.get("author") or "").strip()
            journal = (data.get("journal") or "").strip()

            if not title:
                title = raw_citation

            # 已有的结构化 id 优先，大模型只做补充
            if ref_doi:
                doi = ref_doi
            if ref_pmid:
                pmid = ref_pmid

            result.update(
                {
                    "title": title,
                    "doi": doi,
                    "pmid": pmid,
                    "author": author,
                    "journal": journal,
                }
            )
            if self.cache_path:
                self._save_to_cache(raw_citation, result)
        except Exception as e:
            logger.error("调用通义大模型解析参考文献信息失败: %s", e)

        return result

