# Feature Branch: `feature/html-to-markdown` — 新支線開發執行成果摘要

> **開發目標**：展示一個從生技領域跨足到資料工程的雙棲求職者所具備的知識庫與資料工程技術。既定計劃從LeetCode、ccClub、GitHub、 Google Sheet、local Obsidian 盤點個人技能範疇，並寫入 MongoDB Altas，local Obsidian vault 作為學習機器人的 RAG 來源。而後自 2026-05-30 起，計畫新增支線將 Microsoft OneNote 筆記萃取、清洗/轉換、存於 MongoDB Altas，此 ETL 數據管道在於為慣用微軟 OneNote 筆記軟體但不習慣/尚未學習 markdown 語法做筆記的使用者/單位，清理出適合用於機器學習、AI 模型閱讀的形式，以長遠更能有效擴展 RAG 外部知識庫的可用性，減少因為過往檔案格式與 現代 AI 工具不全相容而導致知識無法有效管理、保留、被 AI 理解後服務人類的窘境。

> **完成日期**：2026-06-12

> **執行環境**：macOS / VS Code / pyenv (Python 3.14) / Poetry / MongoDB localhost 

---

## 專案資料夾結構

```
feature/html-to-markdown/
├── .env                         
├── poetry.lock
├── pyproject.toml
│
├── .agents/                     # Workspace harmonizing muilti-AI agents in the same project such as sharing the skills btw agents. The internal structure is totally identical with the "./.claude/" (see bellows).
│
├── .claude/
│   ├── commands/                # project-level commands
│   ├── hooks/                   # project-level hooks
│   └── skills/                  # project-level skills
│    ├── openspec-apply-change/  # One of 11 Skills for SDD
│    ├── openspec-onboard/       # One of 11 Skills for SDD
│    └── ..../
│
├── task07_obsidian_etl/
│   ├── e_fetch_onenote.py       # Extract raw notes from Azure Graph API
│   ├── t_html_to_md.py          # Parsing raw .html file to lightweight of .md files and keyword extraction by LLM
│   ├── l_load_to_gcs.py         # Storage .md files to GCS
│   ├── l_load_to_mongodb.py     # Chunck, embed and load to db
│   └── main.py                  # 串接 Extract / Transform / Load
│
└── tests/

```

---

## Task 07 — OneNote ETL

### 資料來源
Azure graph API


### Brown layer - Storage of raw notes
- Hierarchy of blobs
```
gcs://onenote-vault
├── metadata.csv       # metadata of all pages in all notebooks
├── <Notebook1_name>/
│       ├── <Section1_name_of_NB1>/  
│       │        ├── Page1_name_of_sec1.html  
│       │        ├── Page2_name_of_sec1.html  
│       │        ├── ....
│       │        ├── PageN_name_of_sec1.html  
│       │        └── _images/
│       │               ├── image01.PNG
│       │               ├── image02.PNG
│       │               └── image0x.PNG
│       │
│       ├── <Section2_name_of_NB1>/
│       │        ├── Page1_name_of_sec2.html  
│       │        ├── ....
│       │        └── _images/
│       │
│       ├── <Section3_name_of_NB1>/  
│       │        ├── ....
│       │        └── _images/
│       │
│       └── <SectionN_name_of_NB1>/
│                ├── ....
│                └── _images/
│
├── <Notebook2_name>/
│       ├── <Section1_name_of_NB2>/  
│       │        ├── Page1_name_of_sec1.html  
│       │        ├── Page2_name_of_sec1.html  
│       │        ├── ....
│       │        ├── PageN_name_of_sec1.html  
│       │        └── _images/
│       └── <SectionN_name_of_NB2>/
│                └── .....
```
- Metadata schema
    - title: page name in a section of a notebook.  
    e.g., "SQL 基本資訊"
    - created_datetime:  Creation date and time in UTC+0 of this page.  
    e.g., 2025-12-20T00:46:09.898Z
    - modified_datetime:  Last modified date and time in UTC+0 of this page.  
    e.g., 2025-12-21T00:51:00.121Z
    - html_path:  <gcspath>/<to>/<blob>.html
    - markdownExportDateTime: exported date and time of markdown file.
    - markdown_path:  <gcspath>/<to>/<blob>.md

### Silver layer - Storage of transformed notes
```
gcs://onenote-vault
├── metadata.csv       # metadata of all pages in all notebooks
├── <Notebook1_name>/
│       ├── <Section1_name_of_NB1>/  
│       │        ├── Page1_name_of_sec1.html  
│       │        ├── Page1_name_of_sec1.md      ⬅️ Inserted
│       │        ├── Page2_name_of_sec1.html  
│       │        ├── Page2_name_of_sec1.md      ⬅️ Inserted
│       │        ├── ....
│       │        ├── PageN_name_of_sec1.html 
│       │        ├── PageN_name_of_sec1.md      ⬅️ Inserted 
│       │        └── _images/
│       │               ├── image01.PNG
│       │               ├── image02.PNG
│       │               └── image0x.PNG
│       │
│       ├── <Section2_name_of_NB1>/
│       │        ├── Page1_name_of_sec2.html  
│       │        ├── Page1_name_of_sec2.md      ⬅️ Inserted  
│       │        ├── ....
│       │        └── _images/
│       │
.....   .....
...     ...

```

### Gold layer - Load to MongoDB Altas after Embedding
> Schema design follows [the definitions of task05](./branch_etl_pipeline_summary.md)


### Audit log
> 遵守人事時地物
```jsonl
{
  "event_id": "e9c0d4e7",  // primary key
  "timestamp": "2026-06-12T10:30:00Z",  // event datetime, utc+0
  "session_id": "trace_001",  // 同一次操作追蹤
  "user_id": "u123",  // 誰發起 (agent skill | mac user | service account)
  "method": "POST",  // GET | POST
  "api_endpoint": "/v1/chat/completions",  // URL
  "attemp_id": 1,  // 第幾次請求(第一次為 1、第一次重試為 2)
  "status": "success",  //  success | fail   
  "status_code": 200,  // HTTP Code
  "latency_ms": 1280,  // 耗時
  "error_msg": "Service Unavailable.....xx",  // 伺服器回應的訊息
  "application": "onenote-to-obsidian-sync", // python script name
  "created_at": "2026-06-12T10:30:00Z" // log datetime, utc+0
}
```