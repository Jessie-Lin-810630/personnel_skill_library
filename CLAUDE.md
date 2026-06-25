# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 專案簡介

個人技能看板（Personnel Skill Dashboard），以 Streamlit 呈現三個頁面：個人知識技能總覽（HOME）、專案架構歷程（Knowledge Factory）、AI 知識 Agent（phase III）。資料來自多個 ETL pipeline，統一寫入 MongoDB Atlas。

## 開發環境

使用 **pyenv + Poetry** 管理環境，Python >= 3.14。

```bash
# 安裝依賴
poetry install

# 啟動虛擬環境 shell
poetry shell
```

環境變數統一從 `.env`（本地開發）或 GCP Secret Manager（部署）讀取。本地開發複製 `.env.example` 並填入真實值。

## 常用指令

```bash
# 執行 Streamlit dashboard（從專案根目錄）
poetry run streamlit run dashboard_ui/app.py

# 執行個別 ETL task（從專案根目錄）
poetry run python -m task01_obsidian_etl.main
poetry run python -m task02_github_restapi_etl.main
poetry run python -m task03_leetcode_ccClub_etl.main
poetry run python -m task05_googlesheet_skill_etl.main
poetry run python -m task06_obsidian_embed_etl.main
poetry run python -m task07_onenote_to_markdown.main

# 執行所有測試
poetry run python -m unittest discover -s tests

# 執行單一測試檔
poetry run python -m unittest tests.test_task03_leetcode_ccClub_etl -v
```

## 架構說明

### ETL 命名規則

每個 task 資料夾內的檔名以前綴區分 ETL 階段：
- `e_*.py` — Extract（資料抓取）
- `t_*.py` — Transform（清洗、轉換）
- `l_*.py` — Load（寫入目的地；多數為 MongoDB，task07 同時寫本地 `.md` 檔與 MongoDB）
- `main.py` — 串接 E → T → L 的入口

### ETL Tasks 與輸出目的地

| Task | 資料來源 | 輸出目的地 |
|------|---------|-----------|
| task01 | 本地 / GCS Obsidian vault `.md` 檔 | MongoDB：`obsidian_notes`, `obsidian_summary` |
| task02 | GitHub REST API | MongoDB：`github_repos`, `github_summary` |
| task03 | LeetCode GraphQL API + ccClub REST API | MongoDB：`solved_problems_on_ccClub`, `solved_problems_on_leetcode`, `ccClub&leetcode_summary` |
| task05 | Google Sheets API（service account） | MongoDB：`skill_scores_biotech`, `skill_scores_data_eng`, `skill_radar_summary` |
| task06 | GCS Obsidian `.md` → chunking → embedding | MongoDB：`obsidian_vectors`（Atlas Vector Search） |
| task07 | Microsoft OneNote（Graph API）→ HTML → Gemini LLM | 本地磁碟：`ONENOTE_OUTPUT_DIR/{帳號}/{筆記本}/{章節}/` 下的 `.md` 與 HTML；MongoDB：`onenote_graph_api_logs`、`gemini_llm_logs`、`onenote_page_metadata` |

所有 task 的 Load 步驟均以唯一欄位做 `upsert`，支援冪等重複執行。

> **需要修改 task01–task06 時**，請先閱讀 [`doc/branch_etl_pipeline_summary.md`](doc/branch_etl_pipeline_summary.md) 了解各 task 的資料來源、ETL 邏輯與 MongoDB schema。
>
> **需要修改 task07 時**，請先閱讀 [`doc/branch_html_to_md_summary.md`](doc/branch_html_to_md_summary.md) 了解 OneNote Graph API 下載、Gemini LLM 轉換、三個 MongoDB collections 的設計與狀態流轉。

### Dashboard UI（`dashboard_ui/`）

- `app.py` — 首頁（HOME）：讀取所有 MongoDB collections，繪製雷達圖（plotly）、KPI 卡片、GitHub 最近專案、刷題三相 donut chart
- `pages/knowledge_factory.py` — 第二頁：ETL pipeline 架構圖與專案里程碑
- `utils/` — MongoDB 查詢封裝（`interact_with_mongodb.py`）、資料預處理（`precomputing.py`）、UI 元件（`ui_elements.py`）
- `agents/` / `agent_tools/` — Phase III AI Agent（使用 Google Vertex AI Gemini + MongoDB Atlas Vector Search）

### task06 向量搜尋

- Embedding model：`text-embedding-3-small`（OpenAI，維度 1536）
- Vector index name：`obsidian_vectors_index`，在 MongoDB Atlas Console 手動建立
- 查詢方式：`$vectorSearch` stage，similarity = cosine

### GCS 整合

task01 / task06 的 Extract 步驟在 Phase II 之後改為從 GCS bucket `personal-vaults` 讀取 `.md` 檔，透過 `GOOGLE_APPLICATION_CREDENTIALS` 指定 service account JSON。

## 環境變數

主要變數定義於 `.env`（詳見 `.env.example`）：
- `MONGO_ALTAS_URI`, `MONGO_DB_NAME` — MongoDB 連線
- `GITHUB_TOKEN` — GitHub REST API
- `GOOGLE_APPLICATION_CREDENTIALS` — GCS / Google Sheets service account（`env/googlesheet-user.json`）
- `AGENT_PLATFORM_USER_CREDENTIALS` — Vertex AI Gemini service account（`env/agent-platform-user.json`）
- `GCP_PROJECT_ID` — GCP 專案 ID
- LeetCode / ccClub 的 cookies 與 token
- `ONENOTE_CLIENT_ID` — Azure App Registration Client ID（task07）
- `ONENOTE_OUTPUT_DIR` — HTML / `.md` 輸出根目錄；實際寫入路徑為 `{ONENOTE_OUTPUT_DIR}/{帳號}/{筆記本}/{章節}/`（task07）
- `ONENOTE_NOTEBOOK_IDS` — （選填）JSON array，指定要下載的 notebook ID；省略則互動選擇（task07）
- `ONENOTE_SELECTED_NOTEBOOKS` — （選填）逗號分隔的 notebook 名稱；省略則於終端機互動選擇（task07）

## 部署架構（Phase II+）

ETL tasks 各自打包為 Docker image，透過 GitHub Actions 推送至 GCP Artifact Registry，以 Cloud Run Job 執行。Dashboard 以 Cloud Run Service 部署，開放 8080 port。機密改由 GCP Secret Manager 管理。
