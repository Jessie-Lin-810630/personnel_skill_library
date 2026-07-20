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

# 啟動 Silver enrich 端點（task07 on-demand enrichment 服務，localhost:8002）
# 供審查頁（pages/onenote_review.py）on-demand 觸發；需與 dashboard 同時啟動
poetry run python -m task07_silver_service.app

# 啟動 Gold 歸檔/退件端點（task07 核可後歸檔服務，localhost:8003）
# 審查頁 approve/reject 呼叫；與 dashboard、task07_silver_service 同時啟動
poetry run python -m task07_gold_service.app

# 執行個別 ETL task（從專案根目錄；task01/06/07 為扶正後的 v2 / lazy_loading 版本，v1 已除役）
poetry run python -m task01_obsidian_etl_v2.main
poetry run python -m task02_github_restapi_etl.main
poetry run python -m task03_leetcode_ccClub_etl.main
poetry run python -m task05_googlesheet_skill_etl.main
poetry run python -m task06_obsidian_embed_etl_v2.main               # Obsidian archived → note_vectors_multimodal
poetry run python -m task07_onenote_to_markdown_lazy_loading.main    # task07 Bronze ETL（只到 raw-notes，不呼叫 LLM；Silver/Gold 見上方 8002/8003 端點）
poetry run python -m task08_onenote_embed_etl.main                   # OneNote archived → note_vectors_multimodal（多模態向量化）

# 執行所有測試
poetry run python -m unittest discover -s tests

# 執行單一測試檔
poetry run python -m unittest tests.test_task03_leetcode_ccClub_etl -v
```

## Git commit 慣例

- **環境變數檔一律由人類自行 `git add` / `git commit`。** 當 `git status` 或 `git diff` 出現 `.env`、`.env.example`、`env/` 等敏感檔時，Claude **一律跳過、不要 stage、不要 commit**，並主動提醒使用者自行處理。這是專案刻意設下的限制（有 protect-env pre-commit hook 會擋住 diff／commit），不是臨時狀況——不需要每次等使用者說「.env 我自己來」。

## 架構說明

### ETL 命名規則

每個 task 資料夾內的檔名以前綴區分 ETL 階段。**前綴依「要處理的資料本體的流向」歸類，不是依「有沒有碰某個資料庫」**：
- `e_*.py` — Extract（資料本體的 ingestion：抓取來源資料）
- `t_*.py` — Transform（資料本體的清洗、轉換）
- `l_*.py` — Load（把資料本體**寫入**目的地 folder／datalake／database；多數為 MongoDB，task07 寫 GCS 資料湖 `onenote-vaults` 的 `.md`／`.html`／`.png` 與 MongoDB）
- `main.py` — 串接 E → T → L 的入口

> **歸類準則**：判斷依據是「這支函式服務的是哪一段資料本體的流向」，而非「它讀寫哪個系統」。例：CDC 做增量 ingestion 時，需要先讀 MongoDB 撈既有 md5 來決定「哪些 GCS blob 要抓」——這個讀取雖然碰 MongoDB，但回傳值只服務 ingestion 判斷、**不寫入任何 collection**，故歸 `e_` 而非 `l_`。`l_` 只保留「把資料本體載入目的地」的寫入。（範例：`task01_obsidian_etl_v2/silver_transform_markdown/e_get_changed_files.py` 的 `get_existing_md5_map()`。）

### Module Docstring 規範

每個 `.py`（`__init__.py` 除外）的 module docstring 一律採以下樣板：**中文寫摘要與執行流程，env variable / 依賴項說明用英文**。

```python
"""<一句中文摘要，緊貼三引號、同一行、以「。」結尾>。

<中文執行流程，可多行；用編號1.、2.、3...串主要步驟>：
1. 函式 upsert_note 以 raw_md_path 為唯一鍵 (Upsert key) 寫入並設 status=archived。
2. 函式 mark_note_error 對失敗者記 status=error。
3. 函式 soft_delete_missing 對已從 GCS 上消失的檔案，標上 status=deleted。

Required .env keys:
    ONENOTE_CLIENT_ID      Azure App Registration Client ID (Notes.Read scope).
    ONENOTE_GCS_BUCKET     GCS bucket for the data lake.

Optional .env keys:
    ONENOTE_NOTEBOOK_IDS   JSON array of notebook IDs; interactive select if omitted.
"""
```

規則（違反會被 ruff `D` / pre-commit 擋下，本專案 `convention = "google"`）：
- **D212**：摘要必須緊貼 `"""` 同一行，不可 `"""` 後換行才寫摘要。
- **D205**：摘要與後續段落之間必須空一行。
- 中文摘要以「。」結尾即可（`D415` 已在 `pyproject.toml` 停用，因其誤判全形句號）；英文說明以「.」結尾。
- `Usage` / `Required .env keys` / `Optional .env keys` 三個區塊**視情況取捨**：無 env 依賴或非執行入口的檔案可省略對應區塊。

### ETL Tasks 與輸出目的地

> 下表以扶正後的正宗版本為準（task01=`task01_obsidian_etl_v2`、task06=`task06_obsidian_embed_etl_v2`、task07=lazy_loading 三服務）；已除役的 v1 見表格下方註解。

| Task | 資料來源 | 輸出目的地 | 開發分支 |
|------|---------|-----------|---------|
| task01（`task01_obsidian_etl_v2`） | GCS `personal-vaults` `raw-notes/` 的 `.md`＋圖片（Object Versioning 保歷史、刻意不做 `dt=` 分區）→ CDC gate 只抓新增/內文或引用圖片變更者 → 清洗歸檔到 `archived-notes/` | MongoDB：`obsidian_note_metadata`（唯一鍵 `raw_md_path`；`attached_images` 單表內嵌血緣、`archived_md_path`、`status` archived/deleted/error、`embedded_status`）、`notes_summary`（每週一次快照、唯一鍵 `snapshot_date`；Gold 層同時快照 obsidian＋onenote metadata 兩表）。軟刪除以 `status=deleted` 標記、保留 archived 副本供稽核 | `feature/etl-pipeline` |
| task02 | GitHub REST API | MongoDB：`github_repos`, `github_summary` | `feature/etl-pipeline` |
| task03 | LeetCode GraphQL API + ccClub REST API | MongoDB：`solved_problems_on_ccClub`, `solved_problems_on_leetcode`, `ccClub&leetcode_summary` | `feature/etl-pipeline` |
| task05 | Google Sheets API（service account） | MongoDB：`skill_scores_biotech`, `skill_scores_data_eng`, `skill_radar_summary` | `feature/etl-pipeline` |
| task06（`task06_obsidian_embed_etl_v2`） | GCS `archived-notes/` 的歸檔 `.md`＋圖片 → chunking → 多模態 embedding（`gemini-embedding-2`，1536 維、L2 normalize） | MongoDB：`note_vectors_multimodal`（Atlas Vector Search）。gate 讀 `obsidian_note_metadata`（`status=archived AND embedded_status=false`）；向量 doc 血緣欄 `md_path`＝archived md 路徑、`image_paths`＝archived 圖片；`md5` 守衛 CAS 翻 `embedded_status`；消費軟刪除訊號 purge | `feature/etl-pipeline` |
| task07（`task07_onenote_to_markdown_lazy_loading` ＋ `task07_silver_service` ＋ `task07_gold_service`，共用 `task07_common`） | Microsoft OneNote（Graph API）→ HTML → 多模態 Gemini LLM（純 Lazy Loading，on-demand 觸發） | GCS 資料湖 `onenote-vaults`（Bronze `raw-notes/`、Silver `processed-notes/`、Gold `archived-notes/`，以 `dt=` 分區保留多版本）；MongoDB：`onenote_graph_api_logs`、`multimodal_llm_enrichment_logs`、`onenote_note_metadata`（主鍵 `page_id`+`dt`）。Bronze ETL 只到 raw-notes；Silver 由 `task07_silver_service`（8002）on-demand 觸發、Gold 由 `task07_gold_service`（8003）approve/reject 觸發；向量化解耦至 task08 | Bronze：`feature/html-to-markdown`；Silver/Gold：見下方「分支職責」註 |
| task08（`task08_onenote_embed_etl`） | GCS `onenote-vaults/archived-notes/` 的歸檔 `.md`＋`_images/` → chunking → 多模態 embedding（`gemini-embedding-2`，1536 維、L2 normalize） | MongoDB：`note_vectors_multimodal`（與 task06 共用同一張向量表）。gate 讀 `onenote_note_metadata`（`status=archived AND embedded_status=false`）；向量 doc 血緣欄 `md_path`＝archived md 路徑、`image_paths`＝archived 圖片；`md_md5_hash` 守衛 CAS 翻 `embedded_status`；OneNote 無軟刪除故不含 purge | `feature/html-to-markdown` |

所有 task 的 Load 步驟均以唯一欄位做 `upsert`，支援冪等重複執行。

> **v1 已除役、v2/lazy_loading 扶正**：`task01_obsidian_etl`（v1，寫 `obsidian_notes`／`obsidian_summary`、CDC 增量同步）、`task06_obsidian_embed_etl`（v1）、`task07_onenote_to_markdown`（v1，本機磁碟、ETL 主動逐頁呼叫 LLM）均已淘汰；上表 task01／06／07 各列即為扶正後的版本。task01 過渡期仍並寫 v1 的 `obsidian_summary`，待 backfill 到 `notes_summary` 後擇期淘汰。

> **task06 與 task08 共寫 `note_vectors_multimodal`**：Obsidian（task01 歸檔）走 task06、OneNote（task07 歸檔）走 task08，兩者向量化後寫入**同一張** `note_vectors_multimodal`（同一 Atlas index `obsidian_vectors_index2`）。向量 doc 的血緣鍵統一為 `md_path`，值＝人工核可後的 archived md 路徑（已全面定調 `md_path`，無 `raw_md_path`／`md_path` 並存）。RAG 讀取端亦以 `md_path` 為血緣欄。

> **task07 lazy_loading 三服務拆分**（未來各自部署容器）：
> - `task07_onenote_to_markdown_lazy_loading/` — Bronze ETL（下載 html、算 hash、存 raw-notes、upsert C3，不呼叫 LLM）。
> - `task07_silver_service/` — Silver enrich Flask 端點（`POST /enrich`，8002），on-demand 觸發 `t_enrich_html_to_markdown` 生成 md 到 processed-notes。
> - `task07_gold_service/` — Gold Flask 端點（`POST /archive`，8003），approve 歸檔到 archived-notes、reject 標記；兩者都回寫 `md_frontmatter`。
> - `task07_common/` — 三者共用的 `gcs.py`、`audit_log.py`、`hashing.py`。
> Streamlit（`dashboard_ui/`）僅讀 MongoDB＋POST 上述端點，不 import 任何 `task07_*` 套件。

> **分支職責**：
> - task01–task06（含 task01_v2、task06_v2）：`feature/etl-pipeline`
> - task07（lazy_loading）的 Bronze ETL、task08：`feature/html-to-markdown`
> - task07（lazy_loading）的 Silver／Gold 服務本體：`feature/html-to-markdown` 起草 → `feature/dashboard-ui` 定稿 → 合併回 `feature/html-to-markdown`
> - Streamlit、AI agent 串接、task07 Silver 端口（8002）與 Gold 端口（8003）實作：`feature/dashboard-ui`

> **需要修改 task01–task06 時**，請先閱讀 [`doc/branch_etl_pipeline_summary.md`](doc/branch_etl_pipeline_summary.md) 了解各 task 的資料來源、ETL 邏輯與 MongoDB schema。
>
> **需要修改 task07 或 task08 時**（兩者前後依存、一邊更新時一起更新記憶），讀 [`doc/branch_onenote_lazy_loading_summary.md`](doc/branch_onenote_lazy_loading_summary.md)（Bronze/Silver/Gold medallion 分層、`html_hash` 冪等快取、on-demand enrichment、LLM 服務級斷路器、task08 向量化）；並先確認要動的是 Bronze ETL、`task07_silver_service`、`task07_gold_service`、共用的 `task07_common` 還是 `task08_onenote_embed_etl`。

### Dashboard UI（`dashboard_ui/`）

- `app.py` — 首頁（HOME）：讀取所有 MongoDB collections，繪製雷達圖（plotly）、KPI 卡片、GitHub 最近專案、刷題三相 donut chart
- `pages/knowledge_factory.py` — 第二頁「Chasing Data Engineering」：Tech Stack Overview（13 層技術堆疊卡片，見 `utils/tech_stack_diagram.py`）＋ Data Lineage（9 張 DAG SVG，從 GCS `personal-vaults` 讀取並以 `st.cache_data` 快取、失敗顯示 Image Not Found）。此頁為原 `knowledge_factory2.py` 扶正而來，舊版 `knowledge_factory.py`（ETL 架構圖／里程碑）已除役
- `utils/` — MongoDB 查詢封裝（`interact_with_mongodb.py`）、資料預處理（`precomputing.py`）、UI 元件（`ui_elements.py`）、Tech Stack 技術堆疊圖（`tech_stack_diagram.py`，純 inline style + base64 SVG，供 `st.html`）、GCS 讀取（`gcs_reader.py`，`read_text` / `read_bytes_as_base64`）
- `agents/` / `agent_tools/` — Phase III AI Agent（使用 Google Vertex AI Gemini + MongoDB Atlas Vector Search）

### 向量搜尋（task06 / task08 共用）

- Embedding model：`gemini-embedding-2`（Vertex AI，多模態，維度 1536、L2 normalize）
- Vector collection：`note_vectors_multimodal`（task06 與 task08 共寫，血緣欄統一 `md_path`）
- Vector index name：`obsidian_vectors_index2`，在 MongoDB Atlas Console 手動建立
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
- `SILVER_ENDPOINT_URL` — task07 lazy_loading 多版本審查頁呼叫 Silver enrich 端點的 URL（本機預設 `http://localhost:8002/enrich`）
- `GOLD_ENDPOINT_URL` — task07 lazy_loading 多版本審查頁 approve/reject 呼叫 Gold/Archive 端點的 URL（本機預設 `http://localhost:8003/archive`）

## 部署架構（Phase II+）

ETL tasks 各自打包為 Docker image，透過 GitHub Actions 推送至 GCP Artifact Registry，以 Cloud Run Job 執行。Dashboard 以 Cloud Run Service 部署，開放 8080 port。機密改由 GCP Secret Manager 管理。
