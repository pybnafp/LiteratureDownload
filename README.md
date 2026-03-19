# 文献下载系统

一个完整的文献搜索和下载工具，支持从 PubMed 搜索文献，按 OA/非 OA 分层获取，并从多源（OA 平台、预印本、Sci-Hub 等）下载 PDF 文件。

## 功能特点

- 🔍 **PubMed 搜索**：通过关键词在 PubMed 搜索文献，自动提取 DOI
- 📥 **多源下载**：支持 OA（Unpaywall、Europe PMC、Crossref 等）、预印本（BioRxiv、MedRxiv）、Sci-Hub、LibGen 等
- 📊 **结果保存**：自动保存搜索结果与下载记录到 CSV，支持断点续传与去重
- ⚡ **批量处理**：`main.py` 支持单次搜索下载，`batch_speech_disorder_downloader.py` 支持多关键词批量下载
- 🛡 **错误处理**：失败记录写入 `download_errors.csv`，支持重试

---

## 项目组织结构

```
LiteratureDownload/
├── main.py                           # 文献下载主程序（单次搜索/单 CSV 导入）
├── batch_speech_disorder_downloader.py # 批量文献下载脚本（多关键词、分批、去重）
├── pubmed_search.py                  # PubMed 搜索
├── download_recorder.py               # 下载记录（download_results.csv / download_errors.csv）
├── oa_checker.py                      # OA 判定（Unpaywall 等）
├── oa_downloader.py                   # OA 文献下载（Europe PMC、Crossref、预印本等）
├── non_oa_downloader.py               # 非 OA 文献分层下载（预印本 → Sci-Hub → LibGen）
├── article_processor.py              # 单篇文献处理流程（OA 判断 + 下载协调）
├── pdf_utils.py                       # PDF 下载与文件名生成
├── redirect_handler.py                # 重定向解析（OA 下载用）
├── scihub_downloader.py               # Sci-Hub 下载（被 non_oa_downloader 调用）
├── biorxiv_preprint.py               # BioRxiv 预印本
├── medrxiv_preprint.py               # MedRxiv 预印本
├── selenium_pdf_downloader.py        # Selenium 备选下载（OA 反爬时）
├── playwright_pdf_downloader.py     # Playwright 备选下载（OA 反爬时）
├── requirements.txt                  # 依赖
└── README.md                          # 说明文档
```

- **main.py**：入口脚本。流程：PubMed 搜索 → 按 DOI 逐篇判断 OA → OA 用 `oa_downloader`，非 OA 用 `non_oa_downloader`；通过 `download_recorder` 实时写入 CSV，避免重复下载。
- **batch_speech_disorder_downloader.py**：基于 `main.py` 的 `LiteratureDownloader`，对多组 PubMed 关键词批量搜索与下载，支持按批处理、跳过已成功 DOI、失败可重试，并生成每关键词的搜索结果 CSV 与汇总报告。

---

## 执行 main.py 时产生的文件

运行 `python main.py` 后，会在 **`literature_pdfs/`**（或你在代码中配置的 `pdf_save_dir`）下产生以下内容。

### 1. 目录结构（按需创建）

| 路径 | 说明 |
|------|------|
| `literature_pdfs/` | 根目录，所有 CSV 与子目录的父路径 |
| `literature_pdfs/oa/` | OA 文献 PDF 及该来源的下载记录 |
| `literature_pdfs/non_oa/` | 非 OA 文献 PDF（预印本、Sci-Hub、LibGen 等）及记录 |
| `literature_pdfs/europe_pmc/`、`crossref/` 等 | 按 `source` 分的子目录（仅当有该来源的下载时存在） |

### 2. 主记录与错误记录（根目录下）

| 文件 | 产生时机 | 说明 |
|------|----------|------|
| `download_results.csv` | 每成功下载一篇即由 `DownloadRecorder` 或 `main._update_download_results` 更新 | 所有成功下载文献的汇总表（pmid, title, doi, journal, author, year, success, source, filepath） |
| `download_errors.csv` | 某篇文献所有尝试均失败时，由 `DownloadRecorder.mark_failed` 写入/更新 | 下载失败的文献列表（含 doi, reason/error, title, journal 等），用于排查与重试 |

### 3. PDF 文件

- **OA**：保存在 `literature_pdfs/oa/`，文件名格式通常为 `{doi 规范化}_{年份}_{来源}.pdf`。
- **非 OA**：保存在 `literature_pdfs/non_oa/`（或由 non_oa_downloader 配置的目录），命名规则类似。


**说明**：`download.log`、`download1.log`、`download2.log` 等是用户在 shell 中重定向（如 `python main.py > download.log 2>&1`）产生的，**不是** main.py 内部创建的文件；若不需要可自行删除。

---

## 执行 batch_speech_disorder_downloader.py 时的额外产出

在 main.py 已有产出的基础上，批量脚本还会在 `literature_pdfs/` 下增加：

| 文件 | 说明 |
|------|------|
| `batch_download_summary.txt` | 批量运行结束后的汇总报告（关键词数、总搜索到文献数、去重后新文献数、总 DOI 记录数等） |

下载记录仍写入同一套 `download_results.csv`、`download_errors.csv`。

---

## 安装依赖

```bash
pip install -r requirements.txt
```

若遇到 `beautifulsoup4` 导入错误：

```bash
pip install beautifulsoup4
```

---

## 使用方法

### 方式 1：通过关键词搜索并下载（推荐）

1. 编辑 `main.py`，修改配置：

```python
YOUR_EMAIL = "your_email@example.com"   # 替换为你的邮箱
SEARCH_QUERY = "speech disorder"        # 搜索关键词
MAX_RESULTS = 50                        # 最大搜索结果数
PDF_SAVE_DIR = "literature_pdfs"        # PDF 保存目录
```

2. 运行：

```bash
python main.py
```

### 方式 2：从 CSV 文件读取 DOI 并下载

若已有包含 DOI 的 CSV：

```python
from main import LiteratureDownloader

downloader = LiteratureDownloader(
    email="your_email@example.com",
    pdf_save_dir="literature_pdfs"
)

downloader.download_from_csv(
    csv_file="literature_pdfs/your_doi_file.csv",
    doi_column="doi"
)
```

### 批量多关键词下载

直接运行批量脚本（内部使用 main.py 的 `LiteratureDownloader`）：

```bash
python batch_speech_disorder_downloader.py
```

在脚本内可修改 `SEARCH_QUERIES`、`BATCH_SIZE`、邮箱等配置。

---

## 配置说明

### PubMed API

- **email**：必填（NCBI 要求）
- **api_key**：可选，可提高请求速率（[NCBI API Key](https://www.ncbi.nlm.nih.gov/account/settings/)）

### 下载行为

- **download_delay**：每次请求间隔（秒），建议 ≥1
- **timeout**：单次下载超时（秒）
- **use_selenium_fallback**：OA 请求失败时是否用 Selenium 备选
- **selenium_headless**：是否无头模式

---

## 注意事项

1. 遵守各平台使用条款与版权规定，合理设置延迟，避免对服务器造成压力。
2. DOI 格式：BioRxiv/MedRxiv 多为 `10.1101/xxxxx`，其他期刊为 `10.xxxx/xxxxx`。
3. Sci-Hub 镜像可能变动，程序会尝试多个镜像；失败会记入 `download_errors.csv` 与 `scihub_errors.txt`。
4. 已成功下载的 DOI 会记录在 `download_results.csv` 中，再次运行会自动跳过，实现增量下载。

---

## 许可证

本项目仅供学习和研究使用。请遵守相关平台的使用条款和版权规定。
