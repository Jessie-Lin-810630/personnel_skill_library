# Feature Branch: `feature/etl-pipeline` — 第一層開發執行成果摘要

> **開發目標**：展示一個從生技領域跨足到資料工程的雙棲求職者所具備的知識庫與資料工程技術。從LeetCode、ccClub、GitHub、 Google Sheet、local Obsidian 盤點個人技能範疇，並寫入 MongoDB，作為後續 Dashboard 資料來源，包含轉換為可視覺化的生技與資料工程雙雷達圖。

> **完成日期**：2026-05-09

> **執行環境**：macOS / VS Code / pyenv (Python 3.14) / Poetry / MongoDB localhost / Google Sheets API service account

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
│   ├── t_transform_obsidian.py                 # 清洗、分類、統計邏輯
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
└── tests/
    ├── test_task01_obsidian_etl.py
    ├── test_task02_github_restapi_etl.py
    ├── test_task03_leetcode_ccClub_etl.py
    └── test_task05_googlesheet_skill_etl.py
```

---

## Task 01 — Obsidian Vault ETL

### 資料來源
本地 Obsidian vault，掃描三類資料夾下的 `.md` 檔案：

| 資料夾前綴 | note_type |
|-----------|-----------|
| `01_` | `daily-log` |
| `02_` | `knowledge-summary` |
| `04_` | `project` |

### ETL 設計重點
- **Extract**：`pathlib.rglob("*.md")` 遞迴掃描，以資料夾前綴過濾非目標路徑；`python-frontmatter` 解析 YAML frontmatter
- **Transform**：優先以 frontmatter `types` 欄位判斷 `note_type`，fallback 用資料夾前綴；以 `TOPIC_KEYWORDS` 字典比對 tags 與檔名，推斷所屬 topic
- **Load**：以 `file_path` 為唯一鍵做 `upsert`，支援重複執行不重複寫入

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

### 執行結果（2026-04-28）
```
共發現 36 份 .md 檔，解析完成 36 筆
obsidian_notes  upsert：新增 6  | 更新 30
obsidian_summary 快照已更新：2026-04-28

by_type   : { "project": 1, "daily-log": 20, "knowledge-summary": 15 }
by_topic  : { "python": 12, "gcp": 10, "database": 12, "dockerize": 1, "other": 1 }
```

### MongoDB Collections

**`obsidian_notes`**（每筆 = 一份 `.md` 檔）
```json
{
  "file_name": "2024-01-15_daily.md",
  "file_path": "/vault/01_daily-logs/2024-01-15_daily.md",
  "note_type": "daily-log",
  "tags": ["python", "sql"],
  "alias": "Python基礎筆記",
  "date": "2024-01-15",
  "topic": "python",
  "word_count": 342,
  "created_at": "2025-04-23T10:00:00Z"
}
```

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
pymongo, python-frontmatter, python-dotenv, loguru
```

### .env 金鑰
```
OBSIDIAN_VAULT_PATH=
MONGO_URI=
MONGO_DB_NAME=
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
- **Transform**：以 `owner.login == username` 判斷 role（owner / collaborator）；以 `if c["commit"]["committer"]["email"] == github_mail:` 過濾出committer是自己帳號的commit；README 取 base64 解碼後前 300 字；`readme_html_url` 直接從 `/readme` endpoint 回傳的 `html_url` 取得
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
  "commit_count": 42,
  "commits": [{ "sha": "abc123", "message": "init: scaffold ETL structure", "committed_at": "2025-04-20T09:00:00Z" }],
  "readme_summary": "This project is an ETL pipeline...",
  "readme_html_url": "https://github.com/yourname/etl-pipeline/blob/main/README.md",
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

## 待辦事項（Task 04 以後）

- [ ] **Task 04**：Udemy 學習歷程 ETL（購買課程數、觀看進度）→ 存入 MySQL
- [ ] **Task 06**：Docker Compose 容器化（MongoDB + MySQL + 4 支 ETL 腳本），並 export `requirements.txt` + `Dockerfile` + `docker-compose.yml`
- [ ] **Streamlit Dashboard**：以上述 MongoDB collections 為資料來源，繪製雙雷達圖、KPI 卡片、圓餅圖

---

*本摘要由 `feature/etl-pipeline` 分支第一層開發完成時，創建 dashboard UI 前匯出。*
