# Feature Branch: `feature/etl-pipeline` — 第一層開發執行成果摘要

> **開發目標**：大範圍展示一個從生技領域跨足到資料工程的雙棲求職者所具備的知識庫與資料工程技術。

> **完成日期**：2026-05-05

> **執行環境**：macOS / VS Code / pyenv (Python 3.14) / Poetry / MongoDB localhost

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
└── tests/
    ├── test_task01_obsidian_etl.py
    ├── test_task02_github_restapi_etl.py
    └── test_task03_leetcode_ccClub_etl.py
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
- **Extract**：`GET /user/repos?type=all` 一次涵蓋 owner + collaborator；逐 repo 呼叫 `/commits` 與 `/readme`；分頁器 `_paginate()` 每頁 100 筆
- **Rate Limit 控制**：每次 response 後讀取 `x-ratelimit-remaining` 與 `x-ratelimit-reset`；剩餘配額低於緩衝值（100）時，精準 sleep 至 reset 時間點；優先處理 `retry-after` header（secondary rate limit）
- **Transform**：以 `owner.login == username` 判斷 role（owner / collaborator）；README 取 base64 解碼後前 300 字；`readme_html_url` 直接從 `/readme` endpoint 回傳的 `html_url` 取得
- **Load**：以 `repo_id` 為唯一鍵 upsert；summary 以 `snapshot_date` 為鍵每日更新

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

## 第一層整體架構總覽

```
資料來源                    Extract                 Transform               Load（MongoDB）
────────────────────────────────────────────────────────────────────────────────────────────
Obsidian vault          e_scan_obsidian.py      t_transform_obsidian    obsidian_notes
  本地 .md 檔案掃描                               .py                     obsidian_summary

GitHub REST API         e_request_github_api    t_transform_github      github_repos
  /user/repos           .py                     .py                     github_summary
  /repos/{}/commits
  /repos/{}/readme

LeetCode GraphQL        e_query_leetcode_       t_transform_leetcode    solved_problems_on_leetcode
  problemsetQuestion    graphql.py              .py                     ccClub&leetcode_summary
  List
  getUserProfile

ccClub REST API         e_crawler_ccClub.py     t_transform_ccClub      solved_problems_on_ccClub
  /api/login                                    .py                     ccClub&leetcode_summary
  /api/profile
  /api/problem
```

---

## MongoDB Collections 彙整

| Collection 名稱 | 所屬 Task | upsert 唯一鍵 | 用途 |
|----------------|-----------|--------------|------|
| `obsidian_notes` | Task 01 | `file_path` | 每份筆記的 metadata |
| `obsidian_summary` | Task 01 | `snapshot_date` | 每日筆記數量快照 |
| `github_repos` | Task 02 | `repo_id` | 每個 repo 的詳細資訊 |
| `github_summary` | Task 02 | `snapshot_date` | 每日 repo 統計快照 |
| `solved_problems_on_leetcode` | Task 03 | `frontendQuestionId` | 每道 AC 題目 |
| `solved_problems_on_ccClub` | Task 03 | `problem_id` | 每道已解 ccClub 題目 |
| `ccClub&leetcode_summary` | Task 03 | `snapshot_date` | 兩平台刷題統計快照 |

---

## 待辦事項（Task 04 以後）

- [ ] **Task 04**：Udemy 學習歷程 ETL（購買課程數、觀看進度）→ 存入 MySQL
- [ ] **Task 05**：Docker Compose 容器化（MongoDB + MySQL + 4 支 ETL 腳本），並 export `requirements.txt` + `Dockerfile` + `docker-compose.yml`
- [ ] **Streamlit Dashboard**：以上述 MongoDB collections 為資料來源，繪製雙雷達圖、KPI 卡片、圓餅圖

---

*本摘要由 `feature/etl-pipeline` 分支第一層開發完成時，創建 dashboard UI 前匯出。*
