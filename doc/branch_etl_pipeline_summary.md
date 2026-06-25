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

## 此分支待辦事項（Task 04）

- [ ] **Task 04**：Udemy 學習歷程 ETL（購買課程數、觀看進度）→ 存入 MySQL

---

## 增量 Embedding（CDC）成果（Task 01 & Task 06）

> 狀態：**已實作並落地**。本節原為「GCS 增量 embedding（CDC）」的設計與決策記錄，現已完成實作；以下保留設計原因，並補上對應的實際函式與檔案。

### 實作對應

| 設計 | 實際落點 |
|---|---|
| 掃 GCS 取每檔 `file_md5_hash` ＋圖片血緣 | `task01/e_scan_obsidian.py`：`scan_vault_gs()`、`extract_attached_images()`、`resolve_image_blob_path()` |
| task01 CDC 狀態機（insert/update/skip/delete，並維護 `embedding_done`） | `task01/l_load_to_mongodb.py`：`sync_notes()`、`_images_changed()` |
| task06 讀 `obsidian_notes` 狀態做 gate | `task06/l_load_to_mongodb.py`：`get_notes_state()`；gate 判斷在 `task06/main.py` |
| task06 先刪後插 ＋ 帶 `file_md5_hash` 守衛的 CAS 翻 `embedding_done` | `task06/l_load_to_mongodb.py`：`load_vectors_incremental()` |

### 問題

task06 全量 embedding 會對每份 `.md` 燒 Vertex `gemini-embedding-2` API。但 GCS 上多數筆記是靜態未更新的，全量重跑等於浪費前面的 model calls。目標：**只對新增/修改過的檔做 embedding（Change Data Capture）**。

### 核心訊號：GCS object 的 `md5_hash`

- `list_blobs()` 回傳的每個 blob 在 metadata 即帶 `md5_hash`（**內容 MD5，不需下載檔案內容**），是「內容是否變更」最可靠的訊號。
- `md5_hash` 是 **GCS object（整份檔）層級**屬性：一個 blob = 一個 md5。chunk 是下載後才在 pipeline 切的，GCS 不知道 chunk 存在，故 chunk 沒有自己的 md5。
- **可靠度**：`md5_hash` 由 GCS 伺服器端依實際存下的 bytes 計算，與上傳用的 client 無關。唯一會是 `None` 的情況是 composite object / 平行組合上傳（門檻約 150 MiB 的大檔）；本專案的 `.md`、`.png` 都是小檔，`md5_hash` 保證存在。

### 決策與原因

| 決策 | 原因 |
|---|---|
| md5 存進 `obsidian_notes`，**不存** `obsidian_vectors_multimodal` | 顆粒度貼近（md5 是「一份檔」層級，notes 也是一份檔一筆）；避免在 vectors 幾萬筆 chunk 重複存同一個 hash |
| 由 **task01 擁有 md5 的真實來源**，task06 只跟隨 | task01 是定期 Cloud Run、負責寫 metadata；task06 只在「task01 已記錄的版本」上做 embedding，狀態單一來源、好推理 |
| 共用的「`.md` → 圖片 GCS 路徑」解析邏輯**以 task01 腳本內函式為準**，task06 包圖片時再 copy 過去 | 規則集中在 task01；task06 沿用同一套（取捨：選 copy 而非 import，需留意日後規則改動要兩邊同步） |

### `obsidian_notes` schema 變更（task01 寫入）

在現有欄位（`file_path`、`file_name`、`note_type`、`tags`、`alias`、`date`、`topic`、`word_count`、`created_at`）之外新增：

```jsonc
{
  // ...既有欄位...
  "file_md5_hash": "abc123==",            // 該 .md 的 GCS md5_hash
  "attached_images": [               // 該 .md 引用的圖片血緣（可查「哪張圖不見了會影響哪些筆記」）
    { "image_path": "lucky460721/from-obsidian/01-daily-logs/_attachment/xxx.png",
      "image_md5_hash": "def456==" }
  ],
  "embedding_done": false,           // task06 是否已完成此版本的 embedding
  "updated_at": ISODate("..."),      // 內容變更時更新（task01）；created_at 不動
  "embedded_at": ISODate("...")      // 本版 embedding 完成時間，UTC（task06 翻 embedding_done=true 時蓋）
}
```
> `file_md5_hash`、`attached_images`、`embedding_done`、`updated_at` 由 **task01** 寫入；`embedded_at` 由 **task06** 在 CAS 翻 `embedding_done=true` 時一併蓋上，語意與 `updated_at`（內容變更時間）切開、互不覆蓋。

### task01 狀態機（每次 Cloud Run 掃 GCS 後）

以 GCS 現況 vs `obsidian_notes` 比對，逐檔決定動作：

| 情境 | 判斷依據 | 動作 |
|---|---|---|
| **新增** `.md` | GCS 有、notes 無 | `insert`，`embedding_done=false` |
| **修改** | `.md` md5 變 **或** 任一 `attached_images[].image_md5_hash` 變 **或** 圖片增減 | `update` metadata/md5/attached_images + `updated_at`，並 **`embedding_done=false`** |
| **未變更** | 所有 md5 都相同 | **完全不動該 doc**（尤其不可每次無腦設 `embedding_done=false`，否則 CDC 失效） |
| **`.md` 被刪** | notes 有、GCS 無此 `.md` | `deleteOne`/`deleteMany` 該 note doc |
| **`.png` 被刪（`.md` 還在）** | 該圖在 GCS 消失，但 owning `.md` 仍在 | **不是刪 note**：`update` 把該圖移出 `attached_images` + **`embedding_done=false`**（向量引用了不存在的圖，需重 embed 成無圖版本） |

> 關鍵：「圖片變更/刪除」也要翻 `embedding_done=false`——因為是多模態 embedding，向量含圖片語意，只看 `.md` md5 會漏掉「換圖但文字沒動」的情況。為求省事，採「一份筆記任一 md5（.md 或 png）變了就一起翻 false」。

### task06 embedding 流程（gate + CAS）

`obsidian_vectors_multimodal` 的 schema **不變**（不存 hash）。task06 實作（`main.py` 串接 E→Gate→T→L）：

1. `scan_vault_gs()`（task01）回傳值已帶每檔的 GCS `md5_hash`，由 task01 `sync_notes()` 寫進 `obsidian_notes.file_md5_hash`。
2. `get_notes_state()` 讀取 `obsidian_notes` 的 `{file_path: {file_md5_hash, embedding_done}}`。
3. **Gate（進入 embedding 的條件，在 `main.py`）**：GCS blob 的 `md5_hash` **等於** `obsidian_notes` 的 `file_md5_hash` **且** `embedding_done is False` 才做。
   - GCS 有新檔但 notes 沒有 → 等下次 task01 `insert`（屆時 `embedding_done=false`）後才輪到。
   - GCS 已刪檔但 notes 殘留 → 等下次 task01 `delete_many`。
4. embedding 完成、chunks 寫入 `obsidian_vectors_multimodal` 後，`load_vectors_incremental()` **翻 `embedding_done=true` 並蓋 `embedded_at`，且是帶 `file_md5_hash` 守衛的 compare-and-swap**：

```js
db.obsidian_notes.updateOne(
  { file_path: fp, file_md5_hash: embeddedMd5, embedding_done: false },  // 守衛：file_md5_hash 仍是我embed的那版
  { $set: { embedding_done: true } }
)
// matchedCount === 0 → task01 中途改了 file_md5_hash，放著讓下輪重 embed（避免舊向量被誤標 done）
```

5. **改過的檔重 embed 前要先刪後插**：`obsidian_vectors_multimodal.delete_many({file_path})` 再 insert，避免 chunk 數變少（例 6→4）時殘留舊 chunk 孤兒。新檔不受影響。

### 已接受的取捨

- **embedding 延遲 ≈ task01 排程間隔**：task06 只 embed「task01 已記錄的版本」，剛改的檔最多慢一個 task01 週期才進向量。以一致性換延遲，可接受。
- **TOCTOU 微窗**：task06 比對 md5 後到真正下載內容之間檔又被改 → 會 embed 比 md5 新的內容；下輪 task01 `update` 會修正，至多浪費一次。可接受。

### 孤兒 chunk 清理（未來獨立維護 job）

若 `obsidian_vectors_multimodal` 殘留已刪檔案的 chunk，用 `$lookup`（或更簡單：`obsidian_vectors_multimodal` distinct `file_path` 集合 − `obsidian_notes` file_path 集合 = 失效集合 → `delete_many`）定期清理即可，不必每次 ETL 都做，避免 data swamp。

---

*本摘要由 `feature/etl-pipeline` 分支 task01 - 04 開發完成且於 `feature/dashboard-ui` 分支創建 dashboard UI 後完成，而後再於修改了 task 06 的 embedding model 為多模態後擴充摘要，最後完成 task01／task06 的 GCS 增量 embedding（CDC）實作並回填本摘要。*
