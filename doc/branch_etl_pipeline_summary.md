# Feature Branch: `feature/etl-pipeline` — 第一層開發執行成果摘要

> **開發目標**：展示一個從生技領域跨足到資料工程的雙棲求職者所具備的知識庫與資料工程技術。從LeetCode、ccClub、GitHub、 Google Sheet、local Obsidian 盤點個人技能範疇，並寫入 MongoDB，作為後續 Dashboard 資料來源，包含轉換為可視覺化的生技與資料工程雙雷達圖。

> **完成日期**：2026-06-24

> **執行環境**：macOS / VS Code / pyenv (Python 3.14) / Poetry

> **資料存儲**：MongoDB localhost (僅專案前期地端小量測試) / MongoDB Altas (自 task06 開始開發向量資料庫以及 task01、task02、task03、task05 完成第一輪部署測試後確定穩定後，均改連 Altas) / Google Cloud Storage

---

## 專案資料夾結構

```
feature/etl-pipeline/
├── .env                                        # 金鑰集中管理（不進 git）
├── poetry.lock
├── pyproject.toml
│
├── task01_obsidian_etl/
│   ├── __init__.py
│   ├── e_scan_obsidian.py                      # 掃描 vault .md 檔、解析 frontmatter
│   ├── t_clean_obsidian.py                     # 清洗、分類、統計邏輯
│   ├── l_load_to_mongodb.py                    # 寫入 MongoDB
│   └── main.py
│
├── task02_github_restapi_etl/
│   ├── __init__.py
│   ├── e_request_github_api.py                 # 呼叫 GitHub REST API
│   ├── t_transform_github.py                   # 清洗、組裝文檔
│   ├── l_load_to_mongodb.py                    # 寫入 MongoDB
│   └── main.py
│
├── task03_leetcode_ccClub_etl/
│   ├── __init__.py
│   ├── e_crawler_ccClub.py                     # ccClub REST API 登入與題目抓取
│   ├── t_transform_ccClub.py                   # 清洗、統計
│   ├── l_load_ccClub_doc_to_mongodb.py         # 寫入 MongoDB
│   ├── e_query_leetcode_graphql.py             # LeetCode GraphQL API 查詢
│   ├── t_transform_leetcode.py                 # 清洗、統計
│   ├── l_load_leetcode_doc_to_mongodb.py       # 寫入 MongoDB
│   └── main.py                                 # 串接兩支 ETL 流程
│
├──task05_googlesheet_skill_etl/
|   ├── e_fetch_google_sheet.py  # 使用 service account 讀取 Google Sheet worksheet
│   ├── t_transform_skills.py    # 任務分數計算、雷達軸彙總、level 分級
│   ├── l_load_to_mongodb.py     # 寫入 MongoDB collections
│   └── main.py                  # 串接 Extract / Transform / Load 流程
│
├──task06_obsidian_embed_etl
│   ├── t_chunk_embed.py.        # 沿用 task01_obsidian_etl/e_scan_obsidian.py 函式回傳值接續向量化。
│   ├── l_load_to_mongodb.py     # 寫入 MongoDB collections
│   └── main.py                  # 串接 Extract / Transform / Load 流程

└── tests/
    ├── test_task01_obsidian_etl.py
    ├── test_task02_github_restapi_etl.py
    ├── test_task03_leetcode_ccClub_etl.py
    ├── test_task05_googlesheet_skill_etl.py
    └── test_task06_obsidian_embed_etl.py
```

---

## Task 01 — Obsidian Vault ETL

### 資料來源
GCS bucket `personal-vaults`（本地 Obsidian vault 已同步上雲），以 `scan_vault_gs()` 掃描三類資料夾下的 `.md` 檔案；另保留 `scan_vault()` 供本地路徑掃描（legacy）：

| 資料夾前綴 | note_type |
|-----------|-----------|
| `01_` | `daily-log` |
| `02_` | `knowledge-summary` |
| `04_` | `project` |

### ETL 設計重點
- **Extract**：`scan_vault_gs()` 用 `storage.Client().list_blobs()` 列出 bucket 內所有 blob，以資料夾前綴過濾出目標 `.md`與`md5_hash`，並同時建 `image_md5_index`（{圖片 blob : md5} 字典）；`extract_attached_images()` 解析 `![[ ]]` 推算一份 `.md` 內所有圖片 GCS 路徑與圖片 md5，拼成陣列，傳給後面 Load。這三者存在一筆文檔成為一份筆記的資料血緣：`.md 路徑`、`md5_hash`、[{`圖片 GCS 路徑`, `圖片 md5`}]，見後方 schema詳列。

- **Transform**：優先以 frontmatter `type` 欄位判斷 `note_type`，fallback 用資料夾前綴；以 `TOPIC_KEYWORDS` 字典比對 tags 與檔名，推斷所屬 topic（`build_note_documents()` 目前為 passthrough，保留為清洗掛載點）

- **Load**：`sync_notes()` 為 CDC 狀態機，以 GCS 現況對比 DB 逐筆決定 **insert / update / skip / delete**，並維護 `embedding_done`／`created_at`／`updated_at`（詳見下方〈增量 Embedding（CDC）成果〉）；`upsert_note_summary()` 以 `snapshot_date` 為鍵每日覆蓋一筆統計快照

### Topic 分類對照表

| Topic | 代表關鍵字（tags / 檔名） |
|-------|--------------------------|
| `python` | python, pandas, numpy, poetry, flask, streamlit |
| `database` | sql, mysql, mongodb, redis, distribution-architecture |
| `gcp` | google-cloud-platform, gcs, bigquery, vm, compute-engine, cloud-run |
| `data-warehouse` | hive |
| `etl` | etl, elt, pipeline, airflow, dbt |
| `ml` | machine learning, ml, sklearn, model |
| `dockerize` | docker, container, image, dockerfile, docker-compose |
| `github` | git, github, github-actions |
| `linux` | os, linux, linux-command |
| `biotech` | biotech, bioreactor, gmp, technology-transfer, biopharma, perfusion, cell-culture, upstream |

### 執行結果（2026-06-24）
```bash
  # loguru logs shown on terminal:
  === Task 01: Obsidian ETL 開始 ===
  共發現 82 份 .md 檔、160 張圖片，開始解析...
  解析完成，成功 82 筆
  Built documents for 82 notes.
  Building summary documents for all notes...
  Built summary documents for 4 notes.
  obsidian_notes 同步完成 | 新增: 82 | 更新: 0 | 未變更: 0 | 刪除: 87
  obsidian_summary 快照已更新，快照日期：2026-06-24
  === Task 01: Obsidian ETL 完成 ===
```

### MongoDB Collections

**`obsidian_notes`**（每筆 = 一份 `.md` 檔）
```json
{
  "file_name": "2024-01-15_daily.md",
  "file_path": "lucky460721/from-obsidian/01-daily-logs/2024-01-15_daily.md",
  "note_type": "daily-log",
  "tags": ["python", "sql"],
  "alias": "Python基礎筆記",
  "date": "2024-01-15",
  "topic": "python",
  "word_count": 342,
  "file_md5_hash": "abc123==",
  "attached_images": [
    { "image_path": "lucky460721/from-obsidian/01-daily-logs/_attachment/x.png",
      "image_md5_hash": "def456==" }
  ],
  "embedding_done": false,
  "created_at": "2025-04-23T10:00:00Z",
  "updated_at": "2025-04-23T10:00:00Z",
  "embedded_at": "2025-04-23T10:05:00Z"
}
```
> `file_md5_hash`、`attached_images`、`embedding_done`、`created_at`、`updated_at` 由 task01 `sync_notes()` 維護；`embedded_at` 時間由 task06 在 Compare-And-Swap 翻轉狀態為 `embedding_done=true` 時一併畫押上。

**`obsidian_summary`**（每日快照）
```json
{
  "snapshot_date": "2025-04-23",
  "total_notes": 87,
  "by_type": { "daily-log": 40, "knowledge-base": 32, "project": 15 },
  "by_topic": { "python": 18, "sql": 12, "ml": 8, "cloud": 6, "biotech": 14, "other": 29 }
}
```

### 套件依賴
```
pymongo, python-frontmatter, python-dotenv, loguru, google-cloud-storage
```

### .env 金鑰
```
GOOGLE_APPLICATION_CREDENTIALS=   # GCS 讀取（list blobs / 下載 .md）
MONGO_ALTAS_URI=
MONGO_DB_NAME=                    # 應為 skill_dashboard
OBSIDIAN_VAULT_PATH=              # 僅 legacy 本地 scan_vault() 使用
```

---

## Task 01 v2 — Obsidian Vault Medallion ETL（變體，與 Task 01 並存）

> 為對照兩種設計而建的 medallion 分層變體，程式在 `task01_obsidian_etl_v2/`，與現行 `task01_obsidian_etl` 檔案並存，但對於整個專案來說先以 task01 v2 優先往後串接其他任務。刻意不做 `dt=` 分區，改用 GCS Object Versioning 保留歷史版本，藉此與 task07 的 `dt=` 分區做設計對照。

### 資料來源
GCS bucket `personal-vaults` 的 **Bronze 層 `raw-notes/`**，由本機以 `gcloud storage rsync` 覆蓋同步上雲。以 section 資料夾前綴過濾三類 `.md`：

| section 前綴 | note_type |
|-----------|-----------|
| `01_` | daily-log |
| `02_` | knowledge-summary |
| `04_` | project |

### ETL 設計重點（medallion 分層）
- **Bronze**：rsync 覆蓋 `raw-notes/`，bucket 開 Object Versioning 保留舊版；此層不清洗、不呼叫 LLM。
- **(Silver) Extract**：`list_raw_blobs()` 掃 `raw-notes/` 取每份 `.md` 與圖片的 `md5_hash`，不下載內容；`get_existing_md5_map()` 從 DB 撈既有狀態，含每筆的圖片 md5；`select_changed_blobs()` 做 CDC gate，只對新增、內文變更、或引用圖片變更的 `.md` 才 `download_as_text()`，取代 v1 的每跑全量下載。
- **(Silver) Transform**：`build_note_document()` 沿用 v1 清洗邏輯推導 note_type／topic／date／word_count，並解析 `![[ ]]` 組出單表內嵌的 `attached_images` 血緣；已於函式內預留 LLM enrichment 掛載點，本次不實作。
- **(Silver) Load**：`archive_note()` 把清洗後 `.md` 與其圖片 `copy_blob` 到 **`archived-notes/`** 乾淨隔離層並回填 archived 端 path／md5；`upsert_note()` 以 `raw_md_path` 為唯一鍵冪等 upsert `obsidian_note_metadata`；任一步失敗以 `mark_note_error()` 記 `status="error"` 與 `error_msg` 落地稽核。
- **軟刪除**：`soft_delete_missing()` 對「DB 有、raw-notes live listing 已無」的筆記標 `status="deleted"`，保留 archived 副本供稽核與供 task06 v2 purge；`present_raw_paths` 為空時防呆跳過，避免上游掃空誤刪全表。
- **(Gold)**：`build_summary` 與 `upsert_summary()` 對現況做每日快照 `notes_summary`，只計 `status="archived"` 者。
> 由於 task07 oneone-to-markdown 採用 lazy loading 設計，onenote 筆記只會在人工審閱後觸發歸檔或退件的紀錄，這行為沒有保證週期性、沒有保證 `onenote_notes_metadata` 的快照也會像 task01 v2 的 `obsidian_notes_metadata` 快照日固定，因此目前借用定期執行的 task01 v2 的 gold 層任務，來同時快照 `obsidian_notes_metadata` 與 `onenote_notes_metadata` 兩張表，將快照結果彙整一起存入 `notes_summary`，以跟隨追蹤 task07 gold 層做歸檔、退件的進度，預計 task07 gold 層執行速度會比 task01 v2 慢上許多。
> 待解決：目前，暫時維持同時寫入 `notes_summary` 與 task01 v1 的 `obsidian_summary` (follow 各自的 schema)，待 `obsidian_summary` 的舊資料 backfill 到 `notes_summary` 完全後，再視穩定性擇期淘汰 `obsidian_summary` (需修改 task01 v2 的 l_load_to_mongodb.py)。

### MongoDB Collections

**`obsidian_note_metadata`**（每筆 = 一份 `.md`，唯一鍵 `raw_md_path`）
```json
{
  "_id" : ObjectId("6a4f4f4820b3b24ebe23b72f"),
  "note_user_id": "lucky460721",
  "notebook": "data-engineering",
  "section": "01-daily-logs",
  "file_name": "20250909 xxx.md",
  "raw_md_path": "gs://personal-vaults/raw-notes/.../xxx.md",
  "raw_md_md5_hash": "abc==",
  "raw_md_updated_at": ISODate("..."),
  "archived_md_path": "gs://personal-vaults/archived-notes/.../xxx.md",
  "archived_md_md5_hash": "def==",
  "archived_at": ISODate("..."),
  "attached_images": [
    { "raw_image_path": "raw-notes/.../_attachment/x.png",
      "raw_image_md5": "...",
      "archived_image_path": "gs://.../archived-notes/.../_attachment/x.png", "archived_image_md5": "..." }
  ],
  "archived_md_frontmatter": { "tags": ["python"], "date": ISODate("..."), "type": "daily-log", "alias": [] },
  "topic": "python",
  "word_count": 1250,
  "status": "archived",           // archived / deleted / error
  "embedded_status": false,       // task06 v2 完成向量化時翻 true
  "error_msg": "",
  "created_at": ISODate("..."),
  "updated_at": ISODate("..."),
  "embedded_at": ISODate("...")   // task06 v2 CAS 翻 true 時蓋
}
```
> 決策：attachment 改**單表內嵌**而非 v1 之外的獨立 collection 加 `_id` 參考。因圖片掛在各筆記自己的 `_attachment/`、天然不跨筆記共用，正規化去重的效益低，卻要固定擔 join 與 N+1 成本。

**`notes_summary`**（固定每週一次快照，快照日之日期部分作為唯一鍵 `snapshot_date`，快照日當天只存最後一次快照資料）
```json
  {
    "_id" : ObjectId("6a4f4f4820b3b24ebe23b72f"),
    "snapshot_date" : ISODate("2026-07-09T00:00:00.000+0000"),  // 快照日當天只認一筆，故不存時、分、秒、毫秒。
    "archived_notes" : 84,
    "by_tag_in_archived_notes" : {
                                "python-installation" : 1,
                                "apple-mac" : 1,
                                },
    "by_tag_in_rejected_notes" : {},
    "by_topic_in_archived_notes" : {
                                "python" : 21,
                                "ml" : 2
                                },
    "by_topic_in_rejected_notes" : {},
    "by_type_in_archived_notes" : {
                                "daily-log" : 27,
                                "knowledge-summary" : 50,
                                },
    "by_type_in_rejected_notes" : {},
    "embedded_notes" : 4,
    "rejected_notes" : 0,
    "total_notes" : 84,
    }
```

### 套件依賴
```
pymongo, python-frontmatter, python-dotenv, loguru, google-cloud-storage
```

### .env 金鑰
```
GOOGLE_APPLICATION_CREDENTIALS=   # GCS list / download / copy_blob
MONGO_ALTAS_URI=
MONGO_DB_NAME=                    # 應為 skill_dashboard
```

---

## Task 02 — GitHub REST API ETL

### 資料來源
GitHub REST API（`https://api.github.com`），抓取範圍：

| 類型 | 說明 |
|------|------|
| Owner repos | 本人持有（public + private） |
| Collaborator repos | 身為協作者的 public repos |

### ETL 設計重點
- **Extract**：`GET /user/repos?type=all` 一次涵蓋 owner + collaborator；逐 repo 獲取 brach names；逐 repo與branch 呼叫 `/commits` 與 `/readme`；分頁器 `_paginate()` 每頁 100 筆
- **Rate Limit 控制**：每次 response 後讀取 `x-ratelimit-remaining` 與 `x-ratelimit-reset`；剩餘配額低於緩衝值（100）時，精準 sleep 至 reset 時間點；優先處理 `retry-after` header（secondary rate limit）
- **Transform**：以 `owner.login == username` 判斷 role（owner / collaborator）；以 `if c["commit"]["committer"]["email"] == github_mail:` 過濾出committer是自己帳號的commit；README 取 base64 解碼後前 300 字；`readme_url` 直接從 `/readme` endpoint 回傳的 `html_url` 取得
- **Load**：存兩份文檔集，`文檔集 github_repos`以 `repo_id` 為唯一鍵 upsert；`文檔集 github_summary` 以 `snapshot_date` 為鍵每日更新

### MongoDB Collections

**`github_repos`**（每筆 = 一個 repo）
```json
{
  "repo_id": 123456789,
  "repo_name": "etl-pipeline",
  "repo_full_name": "yourname/etl-pipeline",
  "description": "...",
  "language": "Python",
  "is_private": false,
  "role": "owner",
  "created_at": "2024-01-01T00:00:00Z",
  "pushed_at": "2025-04-23T10:00:00Z",
  "commit_counts": 42,
  "commits": [{ "sha": "abc123", "message": "init: scaffold ETL structure", "committed_at": "2025-04-20T09:00:00Z" }],
  "readme_summary": "This project is an ETL pipeline...",
  "readme_url": "https://github.com/yourname/etl-pipeline/blob/main/README.md",
  "topics": ["etl", "python", "mongodb"],
  "stars": 0,
  "fetched_at": "2026-04-28T10:00:00Z"
}
```

**`github_summary`**（每日快照）
```json
{
  "snapshot_date": "2026-04-28",
  "total_repos": 15,
  "by_role": { "owner": 12, "collaborator": 3 },
  "by_language": { "Python": 8, "SQL": 2, "Shell": 1, "other": 4 },
  "total_commits": 287,
  "recent_repos": [{ "repo_name": "...", "pushed_at": "...", "language": "..." }]
}
```

### 套件依賴
```
pymongo, requests, python-dotenv, loguru
```

### .env 金鑰
```
GITHUB_USERNAME=
GITHUB_TOKEN=           # PAT (classic)
GITHUB_MAIL=
MONGO_URI=
MONGO_DB_NAME=
```

---

## Task 03 — LeetCode GraphQL + ccClub REST API ETL

### 資料來源

| 來源 | 協定 | 認證方式 |
|------|------|---------|
| LeetCode | GraphQL（`https://leetcode.com/graphql/`） | 瀏覽器 Cookie（`LEETCODE_SESSION` + `csrftoken`） |
| ccClub Judge | REST API（`https://judge.ccclub.io/api`） | 帳號密碼登入，session 自動維持 cookie |

### ETL 設計重點

**LeetCode 側：**
- 使用兩支 GraphQL query：`problemsetQuestionList`（已解題清單）+ `serProblemsSolved`（難度擊敗百分比）
- `problemsetQuestionList` 不支援直接以 status 過濾，Python 端過濾 `status == "ac"`
- 分頁以 `skip` 遞增，每頁 `limit=100`；每頁間主動 throttle 1 秒
- Cookie 過期防呆：AC 數為 0 但題庫有題時，主動 warning 提示重新取得 cookie

**ccClub 側：**
- 以 `requests.Session` 維持登入狀態；登入後重新取得 rotate 後的 csrftoken
- 逐題呼叫 `GET /api/problem?problem_id={id}` 補齊 tags & difficulty
- difficulty 標準化：`Low/Easy → Easy`、`Mid → Med.`、`High → Hard`
- 每題請求間隔 0.3 秒 throttle，保護 ccClub server

**共用 summary collection：**
- LeetCode ETL 與 ccClub ETL 各自以 `$set` partial update 寫入 `ccClub&leetcode_summary`，以 `snapshot_date` 為唯一鍵，兩側欄位本獨立、互不覆蓋
- 執行順序，LeetCode ETL 再 ccClub ETL，或是相反也可以。

### MongoDB Collections

**`solved_problems_on_leetcode`**（每筆 = 一道 AC 題目）
```json
{
  "frontendQuestionId": "1",
  "title": "Two Sum",
  "topic": ["array", "hash-table"],
  "difficulty": "Easy"
}
```

**`solved_problems_on_ccClub`**（每筆 = 一道已解題目）
```json
{
  "problem_id": "180001",
  "problem_type": "ACM",
  "score": 0,
  "topic": ["String"],
  "difficulty": "Easy"
}
```

**`ccClub&leetcode_summary`**（每日快照，兩側合併）
```json
{
  "snapshot_date": "2026-04-28",
  "totalSolvedProblemsOnCCclub": 264,
  "totalSolvedProblemsOnLeetcode": 15,
  "problemDifficultyOnLeetcode": [
    { "difficulty": "Easy", "percentage": 81.71 },
    { "difficulty": "Medium", "percentage": 17.74 },
    { "difficulty": "Hard", "percentage": null }
  ],
  "problemDifficultyOnCCclub": [
    { "difficulty": "Easy", "percentage": 75.0 },
    { "difficulty": "Med.", "percentage": 20.0 },
    { "difficulty": "Hard", "percentage": 5.0 }
  ],
  "topicsPercentOnCCclub": { "String": 20.0, "Math": 80.0 },
  "topicsPercentOnLeetcode": { "array": 13.4, "hash-table": 12.6, "dynamic-programming": 74.0 }
}
```

### 套件依賴
```
pymongo, requests, python-dotenv, loguru
```

### .env 金鑰
```
LEETCODE_USERNAME=
LEETCODE_SESSION=       # 從瀏覽器 Cookie 取得，有時效性（數週）
LEETCODE_CSRF_TOKEN=    # 從瀏覽器 Cookie 取得
CCCLUB_USERNAME=
CCCLUB_PASSWORD=
MONGO_URI=
MONGO_DB_NAME=
```

---
## Task 05 — Google Sheet Skill Radar ETL

### 資料來源

Google Spreadsheet：`Personal Skill Radar Calculation`

| Worksheet | 說明 | 輸出雷達圖名稱 |
|-----------|------|----------------|
| `生技` | 生技領域任務與能力盤點 | `雷達圖1生技` |
| `資料工程` | 資料工程任務與能力盤點 | `雷達圖2資料工程` |

### 雷達軸設計

**生技雷達軸**

| 雷達軸 |
|--------|
| `製程技術 (細胞分注、反應器操作) 操作能力` |
| `流程設計能力` |
| `跨專案數據整合能力` |
| `文件撰寫能力` |
| `簡報口說能力` |

**資料工程雷達軸**

| 雷達軸 |
|--------|
| `ELT/ELT pipeline 操作與維護` |
| `雲端 (GCP) 服務技術` |
| `Orchestration` |
| `資料庫資料模型設計` |
| `文案設計與歸納` |
| `資料視覺化` |
| `資料品質與血緣維護` |

---

### ETL 設計重點

- **Extract** : 使用 `pygsheets.authorize(service_account_json=...)` 透過 service account JSON key 授權後，以 pygsheet 套件開啟google sheet `Personal Skill Radar Calculation`，開啟後分別讀取 `生技` 與 `資料工程` 兩張worksheets，並也是使用 pygsheet 轉為 pandas DataFrame

- **Transform** : 將欄位中標記為 `Y` 的能力旗標轉為 `1`，其他值轉為 `0`，接著每個任務以三個面向計分：
    - **複雜性**
    - **獨立性**
    - **影響力**
  由於生技與資料工程的複雜性欄位名稱不同，因此拆成 `build_biotech_task_docs()` 與 `build_de_task_docs()` 兩套轉換函式、分別產出兩個 DataFrame，然後再從中計算出單項任務總分後，映射出雷達軸層級 (level)後，生技與資料工程的映射結果則匯總存於同個 DataFrame，因此總計 Transform 階段有三個 DataFrames。其中此 level 會作為雷達圖的軸刻度。

- **Load** : 將前次步驟產出的三個 DataFrame寫入 MongoDB 文檔集`skill_scores_biotech`、`skill_scores_data_eng`、`skill_radar_summary`。前兩個文檔集以 `雷達軸` 與 `經手任務` 為 upsert 條件；文檔集skill_radar_summary則以`snapshot_date + 雷達軸 + 雷達圖名稱` 為複合 upsert 條件，支援定期快照更新。

---

### 計分規則

#### 生技任務分數

- **複雜性權重**

  | 欄位 | 權重 |
  |------|------|
  | `複雜性 - 純紀錄` | 1 |
  | `複雜性 - 執行操作` | 3 |
  | `複雜性 - 制定方向` | 3 |
  | `複雜性 - 優化與故障排除` | 3 |

- **獨立性權重**

  | 欄位 | 權重 |
  |------|------|
  | `獨立性 - 需要指導後才能照規章做` | 1 |
  | `獨立性 - 不需指導即可理解並遵照組織規章做` | 5 |
  | `獨立性 - 自訂架構` | 9 |

- **影響力權重**

  | 欄位 | 權重 |
  |------|------|
  | `影響力 -  不具備教學的經驗` | 0 |
  | `影響力 - 具備部門內教學經驗` | 1 |
  | `影響力 - 具備跨部門教學經驗` | 5 |
  | `影響力 - 具備公司外出教學經驗` | 9 |

- **單項任務總分**

  ```
  單項任務總分 = 複雜性總分 * 1 + 獨立性總分 * 1 + 影響力總分 * 2
  ```

#### 資料工程任務分數

- **複雜性權重**

  | 欄位 | 權重 |
  |------|------|
  | `複雜性 - 純紀錄與理解` | 1 |
  | `複雜性 - 開發測試` | 3 |
  | `複雜性 - 接手部署` | 3 |
  | `複雜性 - 優化與故障排除` | 3 |

- **獨立性與影響力權重**
  ```
  資料工程任務沿用生技任務的獨立性與影響力權重。
  ```

- **單項任務總分**

  ```
  單項任務總分 = 複雜性總分 * 1 + 獨立性總分 * 2 + 影響力總分 * 1
  ```

#### 雷達軸 summary 分數

- **每個雷達軸以任務數與單項任務最高分計算**

  ```
  任務經驗值 = round(log2(經手任務個數), 6)
  單軸總分 = round(各軸向任務最高分 + 任務經驗值, 2)
  ```

- **Level 分級**

  | 單軸總分區間 | level |
  |--------------|-------|
  | `< 5` | 1 |
  | `5 <= score < 12` | 2 |
  | `12 <= score < 15` | 3 |
  | `15 <= score < 23` | 4 |
  | `>= 23` | 5 |

---

### MongoDB Collections

**`skill_scores_biotech`** 每筆代表一個生技 worksheet 中的任務資料，並附加計算後的分數欄位。

```json
{
  "雷達軸": "流程設計能力",
  "經手任務": "製程流程設計與優化",
  "複雜性 - 純紀錄": 0,
  "複雜性 - 執行操作": 1,
  "複雜性 - 制定方向": 1,
  "複雜性 - 優化與故障排除": 0,
  "獨立性 - 需要指導後才能照規章做": 0,
  "獨立性 - 不需指導即可理解並遵照組織規章做": 1,
  "獨立性 - 自訂架構": 0,
  "影響力 - 具備公司外出教學經驗": 0,
  "影響力 - 具備跨部門教學經驗": 1,
  "影響力 - 具備部門內教學經驗": 0,
  "影響力 -  不具備教學的經驗": 0,
  "複雜性總分": 6,
  "獨立性總分": 5,
  "影響力總分": 5,
  "單項任務總分": 21
}
```

**`skill_scores_data_eng`** 每筆代表一個資料工程 worksheet 中的任務資料，並附加計算後的分數欄位。
```json
{
  "雷達軸": "Orchestration",
  "經手任務": "xxx project Airflow DAG pipeline 維護",
  "複雜性 - 純紀錄與理解": 0,
  "複雜性 - 開發測試": 1,
  "複雜性 - 接手部署": 0,
  "複雜性 - 優化與故障排除": 1,
  "獨立性 - 需要指導後才能照規章做": 1,
  "獨立性 - 不需指導即可理解並遵照組織規章做": 0,
  "獨立性 - 自訂架構": 1,
  "影響力 - 具備公司外出教學經驗": 0,
  "影響力 - 具備跨部門教學經驗": 0,
  "影響力 - 具備部門內教學經驗": 1,
  "影響力 -  不具備教學的經驗": 0,
  "複雜性總分": 6,
  "獨立性總分": 10,
  "影響力總分": 1,
  "單項任務總分": 27
}
```

**`skill_radar_summary`** 每筆代表某一天、某張雷達圖、某個雷達軸的彙總結果。

```json
{
  "雷達圖名稱": "雷達圖2資料工程",
  "雷達軸": "Orchestration",
  "經手任務個數": 4,
  "任務經驗值": 2.0,
  "各軸向任務最高分": 27,
  "單軸總分": 29.0,
  "level": 5,
  "snapshot_date": "2026-05-09"
}
```
### 套件依賴

```
pymongo, pygsheets, pandas, numpy, python-dotenv, loguru
```

---

### .env 金鑰

```
GS_CREDENTIAL_FILE_PATH=
MONGO_URI=
MONGO_DB_NAME=
```

---

## Task 06 — Obsidian Vector DB ETL

### 資料來源
Google Cloud Storage bucket：`personal-vaults`，沿用 Task 01 的 `scan_vault_gs()` 掃描 bucket 內三類 Obsidian `.md` 檔案 metadata，再依 `file_path` 重新下載 Markdown 內文做 chunking 與 embedding。

| 資料夾前綴 | note_type |
|-----------|-----------|
| `01_` | `daily-log` |
| `02_` | `knowledge-summary` |
| `04_` | `project` |

### ETL 設計重點
- **Extract**：沿用 `task01_obsidian_etl.e_scan_obsidian.scan_vault_gs("personal-vaults")` 取得每份筆記的 `file_path`、`file_name`、`tags`、`note_type`、`date` 等 metadata；再由 task06 新函式 `fetch_gcs_note_content()` 使用 `google.cloud.storage.Client()` 依 `file_path` 從 GCS 下載原始 Markdown，並以 `python-frontmatter` 去除 frontmatter，只保留 body 文字

- **Transform**：`preprocess_obsidian_content()` 清理 Obsidian block ID 與 wiki-link 語法（圖片嵌入 `![[ ]]` 保留不動）；`chunk_markdown()` 先用 `MarkdownHeaderTextSplitter` 依 H1-H4 保留段落上下文，再用 `RecursiveCharacterTextSplitter` 以 `chunk_size=800`、`chunk_overlap=100` 做中文友善切塊；`embed_chunks_a_mardown()` 逐 chunk 呼叫 **Vertex AI `gemini-embedding-2`（多模態）**，把 chunk 文字與其圖片（解析成 `gs://` URI）一起送入，產生 **1536 維**向量並做 L2 normalize

- **Load**：`load_vectors_incremental()`（在 `l_load_to_mongodb.py`）對本次成功處理的每個檔案，先 `delete_many({file_path})` 再 `insert_many` 寫入 MongoDB Atlas 的 `obsidian_vectors_multimodal` collection（**先刪後插**，避免重切後 chunk 數變少殘留孤兒）；完成後以「帶 `file_md5_hash` 守衛的 CAS」翻 `obsidian_notes.embedding_done=true` 並蓋 `embedded_at`。詳見下方[〈此分支改進計劃〉的增量 embedding 設計考量](#增量-embeddingcdc成果task-01--task-06)補充。

### Obsidian 語法清理規則

| 原始語法 | 處理方式 | 說明 |
|----------|----------|------|
| `^8e5a21` | 移除 | Obsidian block ID 僅作內部引用，對語意檢索無直接價值 |
| `![[image.png]]` | 保留 | 改用多模態模型，圖片於 embed 階段解析成 GCS 圖片一起向量化；wiki-link 正則加負向後查 `(?<!!)` 避免破壞圖片語法 |
| `[[note｜alias]]` | 保留 `alias` | 優先保留 alias，讓 chunk 文字更接近閱讀語意 |
| `[[note]]` | 保留 `note` | 無 alias 時保留連結名稱 |

### 多模態 Embedding（Gemini Embedding 2）

- **模型**：Vertex AI `gemini-embedding-2`（GA、多模態，文字＋圖片映射到同一向量空間），沿用 GCP 服務帳號（`AGENT_PLATFORM_USER_CREDENTIALS` + `GCP_PROJECT_ID`），`location=us-central1`
- **圖片解析**：`.md` 內圖片只寫檔名（如 `![[xxx.png]]`），不更動其寫法；embed 時依儲存結構推算 GCS 實體路徑 = `<note 所在目錄>/_attachment/<檔名>`，以各 note 自己的目錄解析，天然避開不同 `_attachment/` 同名 `.png` 衝突；圖片以 `Part.from_uri(gs://...)` 送入，私有 bucket 靠 Vertex AI 直接讀取，圖片不存在則 warning 略過
- **Task instruction**：`gemini-embedding-2` **不支援 `task_type` 參數**，改把任務型式當 instruction 寫進 prompt 文字，且不同任務型式格式不同（非寫 `RETRIEVAL_DOCUMENT` 字樣）：
    - 入庫文件（對應 `RETRIEVAL_DOCUMENT`）→ `title: {title} | text: {content}`（本檔用此；title = 筆記標題＋section）
    - 查詢端（對應 `RETRIEVAL_QUERY`）→ `task: search result | query: {query}`
    > ⚠️ 未來查詢端做 query embedding 時須對齊同模型／同維度，並用上面的 query 格式，兩端配對 cosine 分數才準
- **維度**：`output_dimensionality=1536`（MRL 截斷，落在 Atlas M0 的 2048 維上限內）；非預設維度不會自動正規化，故輸出再做 L2 normalize 以符合 cosine
- **批次**：多模態無法像純文字 batch，故每 chunk 各呼叫一次 `embed_content`

### Chunking 策略

| 階段 | 工具 | 設定 | 用途 |
|------|------|------|------|
| Header split | `MarkdownHeaderTextSplitter` | `#`、`##`、`###`、`####` | 依 Markdown 標題拆出語意段落，並產生 `section` 路徑 |
| Character split | `RecursiveCharacterTextSplitter` | `chunk_size=800`、`chunk_overlap=100` | 避免單一段落過長，並用重疊保留上下文 |
| Separators | Recursive splitter | `\n\n`、`\n`、`。`、`，`、空白、空字串 | 對中文筆記較友善的切分順序 |

### MongoDB Collections

**`obsidian_vectors_multimodal`**（每筆 = 一份 Obsidian 筆記的一個 chunk；多模態版本）
```json
{
  "file_path": "lucky460721/from-obsidian/02-knowledge/mysql-note.md",
  "file_name": "mysql-note.md",
  "chunk_index": 0,
  "chunk_total": 6,
  "tags": ["MySQL", "database"],
  "note_type": "knowledge-summary",
  "date": "2026-04-13",
  "section": "MySQL 筆記 > DQL 敘述比較",
  "content": "SELECT 查詢語句可以搭配 WHERE、GROUP BY 與 ORDER BY...![[diagram.png]]",
  "image_paths": ["gs://personal-vaults/lucky460721/from-obsidian/02-knowledge/_attachment/diagram.png"],
  "embedding": [0.0123, -0.0045, 0.0312]
}
```
> `content` 保留原始 chunk 文字（含 `![[ ]]`），方便日後把 .md 另作他用時 Obsidian/IDE 仍能解析圖片；`image_paths` 為該 chunk 圖片的 `gs://` URI（無圖為 `[]`），作為數據血緣追蹤。

### Atlas Vector Search Index

`obsidian_vectors_multimodal` 預期搭配 MongoDB Atlas Vector Search index 使用（維度仍為 1536）：

```json
{
  "fields": [
    {
      "type": "vector",
      "path": "embedding",
      "numDimensions": 1536,
      "similarity": "cosine"
    },
    {
      "type": "filter",
      "path": "tags"
    },
    {
      "type": "filter",
      "path": "note_type"
    }
  ]
}
```

### 套件依賴
```
pymongo, python-frontmatter, python-dotenv, loguru, google-cloud-storage, google-genai, langchain-text-splitters
```

### .env 金鑰
```
GOOGLE_APPLICATION_CREDENTIALS=    # GCS 讀取（scan / 下載 .md / 檢查圖片）
AGENT_PLATFORM_USER_CREDENTIALS=   # Vertex AI gemini-embedding-2 服務帳號金鑰
GCP_PROJECT_ID=                    # Vertex AI 專案
MONGO_ALTAS_URI=
MONGO_DB_NAME=                     # 應為 skill_dashboard
```

---

## Task 06 v2 — Obsidian Vector DB ETL（變體，對接 Task 01 v2 medallion）

> 程式在 `task06_obsidian_embed_etl_v2/`，與現行 `task06_obsidian_embed_etl` 並存。改吃 Task 01 v2 的 `obsidian_note_metadata` 與 `archived-notes/` 乾淨層，向量寫入 **v2 專用 `note_vectors_multimodal`**，與 v1 的 `obsidian_vectors_multimodal` 完全隔離，並新增 purge 消費端消費 Task 01 v2 的軟刪除訊號。

### 資料來源
MongoDB `obsidian_note_metadata` 作為 gate，GCS `archived-notes/` 作為內文與圖片來源。

### ETL 設計重點
- **Extract（gate）**：`get_embedding_gate_list()` 挑 `status="archived"` 且 `embedded_status=false` 的筆記；`fetch_archived_content()` 依 `archived_md_path` 從 archived 層下載 md body。取代 v1 讀 `obsidian_notes` 加 raw `.md` 的做法。
- **Transform**：沿用 v1 chunking（`MarkdownHeaderTextSplitter` ＋ `RecursiveCharacterTextSplitter`）與多模態 `gemini-embedding-2`，輸出 1536 維並 L2 normalize，document 端 prompt 用 `title: {title} | text: {content}`；**圖片來源改走 archived 層** `archived-notes/.../_attachment/`，每筆 vector doc 帶 `raw_md_path` 血緣鍵。
- **Load**：`load_vectors_incremental_v2()` 對每份筆記先 `delete_many({raw_md_path})` 再 `insert_many` 寫 `note_vectors_multimodal`，並以 **`archived_md_md5_hash` 守衛的 CAS** 翻 `obsidian_note_metadata.embedded_status=true` 並蓋 `embedded_at`。
- **Purge（消費軟刪除）**：`purge_deleted_vectors()` 查 `status="deleted"` 且 `embedded_status=true` 的筆記，`delete_many({raw_md_path})` 清 `note_vectors_multimodal` 對應向量後翻 `embedded_status=false`；不動 metadata 文件與 archived 副本，可冪等重跑。

### MongoDB Collections

**`note_vectors_multimodal`**（每筆 = 一份筆記的一個 chunk，血緣鍵 `md_path`）
```json
{
  "md_path": "gs://personal-vaults/raw-notes/.../xxx.md",
  "file_name": "xxx.md",
  "chunk_index": 0,
  "chunk_total": 6,
  "tags": ["python"],
  "note_type": "daily-log",
  "date": ISODate("..."),
  "section": "標題 > 子標題",
  "content": "chunk 文字，保留 ![[ ]] 寫法",
  "image_paths": ["gs://.../archived-notes/.../_attachment/x.png"],
  "embedding": [0.01, -0.02, "..."]
}
```
> `embedding` 長度 1536、已 L2 normalize。需在 Atlas Console 手動建 `note_vectors_multimodal` 的 Vector Search index，維度 1536、similarity cosine。

### 套件依賴
```
pymongo, python-frontmatter, python-dotenv, loguru, google-cloud-storage, google-genai, langchain-text-splitters
```

### .env 金鑰
```
GOOGLE_APPLICATION_CREDENTIALS=    # GCS 下載 archived md、檢查圖片是否存在
AGENT_PLATFORM_USER_CREDENTIALS=   # Vertex AI gemini-embedding-2 服務帳號金鑰
GCP_PROJECT_ID=                    # Vertex AI 專案
MONGO_ALTAS_URI=
MONGO_DB_NAME=                     # 應為 skill_dashboard
```

---

## 此分支待辦事項（Task 04）

- [ ] **Task 04**：Udemy 學習歷程 ETL（購買課程數、觀看進度）→ 存入 MySQL

---

## 增量 Embedding（CDC）機制：v1 vs v2 對照

> task01／task06 有兩套並存的 CDC 設計：v1（`task01_obsidian_etl` + `task06_obsidian_embed_etl`）與 v2（medallion 變體，`*_v2`）。兩者核心訊號都是 GCS object 的 `md5_hash`，差異在分層、下載時機、schema 與刪除處理。

### 共通核心訊號
- CDC 依據都是 GCS blob 的 `md5_hash`：它是 GCS object 層級屬性，`list_blobs()` 回傳即帶、不需下載內容，由伺服器端依實際 bytes 計算、與上傳 client 無關；本專案 `.md`／`.png` 都是小檔，保證存在。
- chunk 沒有自己的 md5，故 md5 存在「一份檔一筆」的 metadata collection、不存進幾萬筆 chunk 的 vectors。
- 都由 task01 擁有 md5 真實來源，task06 只在「task01 已記錄的版本」上做 embedding、跟隨其狀態，狀態單一來源好推理。

### 兩套機制對照

| 面向 | v1（`obsidian_notes`） | v2（`obsidian_note_metadata`，medallion） |
|---|---|---|
| 分層 | 單層，raw `.md` 原地讀寫 | Bronze `raw-notes/` → Silver `archived-notes/` → Gold 快照 |
| 版本控制 | 無 | GCS Object Versioning，對照 task07 的 `dt=` 分區 |
| **下載時機** | **每跑全量 `download_as_text()`**，CDC 只省 DB 寫入與 embedding | **CDC gate 先比對、只下載變更檔**（`select_changed_blobs`）|
| CDC 比對範圍 | `.md` md5 或圖片 md5 任一變 | `.md` md5 或圖片 md5 任一變，含圖片消失 |
| task01 狀態機 | `sync_notes()`：insert／update／skip／**硬刪 delete** | `upsert_note()` ＋ `soft_delete_missing()`：upsert／**軟刪除 status=deleted** |
| 向量化來源 | raw `.md`，與清洗物混存 | **archived 乾淨隔離層**，可插 LLM enrichment 不污染檢索 |
| attachment 血緣 | 內嵌 `attached_images`，只帶 raw md5 | 內嵌 `attached_images`，帶 raw ＋ archived 兩組 path/md5 |
| 向量化旗標 | `embedding_done` | `embedded_status` |
| CAS 守衛欄位 | `file_md5_hash` | `archived_md_md5_hash` |
| 向量 collection | `obsidian_vectors_multimodal` | `note_vectors_multimodal`，與 v1 完全隔離 |
| 刪除→向量清理 | 靠獨立孤兒 chunk 清理 job | **purge 消費端**：軟刪除訊號驅動 `delete_many` 即時清 |
| 失敗處理 | 檔略過、下輪重試 | 檔略過並 `mark_note_error(status=error)` 落地稽核 |

### 共通的 gate ＋ 先刪後插 ＋ CAS
兩套 task06 都遵循同一套增量寫入紀律：先做 gate，只在 GCS md5 等於 DB 記錄版本且向量化旗標仍為 false 時才 embed；embedding 後對該筆記先 `delete_many({key})` 再 insert，避免重切後 chunk 變少殘留孤兒；最後以帶 md5 守衛的 compare-and-swap 翻旗標，守衛值不符代表 embedding 期間版本又變，就不翻、留待下輪重做，避免舊向量被誤標成 done。

### 已接受的取捨（兩套共通）
- **embedding 延遲約等於 task01 排程間隔**：task06 只 embed task01 已記錄的版本，剛改的檔最多慢一個週期才進向量，以一致性換延遲。
- **TOCTOU 微窗**：比對 md5 到真正下載內容之間檔又被改，至多浪費一次，下輪 task01 更新後修正。
- **v1／v2 清洗規則各自 copy、可能漂移**：這是刻意的對照設計，差異記於 work log，不視為 bug。

---

*本摘要由 `feature/etl-pipeline` 分支 task01 - 04 開發完成且於 `feature/dashboard-ui` 分支創建 dashboard UI 後完成，而後再於修改了 task 06 的 embedding model 為多模態後擴充摘要，最後完成 task01／task06 的 GCS 增量 embedding（CDC）實作並回填本摘要。*
