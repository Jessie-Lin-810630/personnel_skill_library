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

### ETL Tasks 索引與漸進式揭露

下表只做**路由**：認得資料夾、一句話職責與所屬分支即可。**資料來源、輸出的 collection／bucket、schema 欄位、ETL 邏輯、冪等策略等細節一律不寫在此**，改依下方閱讀順序去讀。

| Task | 資料夾 | 一句話職責 | 開發分支 |
|------|--------|-----------|---------|
| task01 | `task01_obsidian_etl_v2/` | Obsidian 筆記清洗歸檔，並維護筆記 metadata | `feature/etl-pipeline` |
| task02 | `task02_github_restapi_etl/` | 抓 GitHub repo 活動 | `feature/etl-pipeline` |
| task03 | `task03_leetcode_ccClub_etl/` | 抓 LeetCode／ccClub 刷題紀錄 | `feature/etl-pipeline` |
| task05 | `task05_googlesheet_skill_etl/` | 抓 Google Sheets 技能評分、算雷達圖分數 | `feature/etl-pipeline` |
| task06 | `task06_obsidian_embed_etl_v2/` | 把 Obsidian 歸檔筆記向量化 | `feature/etl-pipeline` |
| task07 Bronze | `task07_onenote_to_markdown_lazy_loading/` | 下載 OneNote html 存 Bronze，不呼叫 LLM | `feature/html-to-markdown` |
| task07 Silver | `task07_silver_service/` | on-demand enrich 端點（8002），html → md | 見下方「分支職責」 |
| task07 Gold | `task07_gold_service/` | approve／reject 歸檔端點（8003） | 見下方「分支職責」 |
| task07 共用 | `task07_common/` | 三服務共用的 `gcs`／`audit_log`／`hashing`／`topic` | 同上 |
| task08 | `task08_onenote_embed_etl/` | 把 OneNote 歸檔筆記向量化 | `feature/html-to-markdown` |

**漸進式揭露**：要動哪個 task，就照下列順序讀，資訊夠了就停，不要一開始就翻腳本。

1. **該資料夾的 `README.md`**（每個 task 與 `dashboard_ui/` 都有）— 資料來源、輸出目的地、DataFlow、Configuration、collection schema、啟動方式都在這層，多數改動讀到這裡就足夠。
2. **`doc/*_summary.md`**（README 不足時才讀，取分支層級的設計脈絡與決策理由）— task01–task06 讀 [`branch_etl_pipeline_summary.md`](doc/branch_etl_pipeline_summary.md)；task07／task08 讀 [`branch_onenote_lazy_loading_summary.md`](doc/branch_onenote_lazy_loading_summary.md)；Streamlit 與 AI Agent 讀 [`branch_dashboard_ui_summary.md`](doc/branch_dashboard_ui_summary.md)。
3. **`.py` 腳本本體**（前兩層都沒寫到的實作細節才進來）— 入口從 `main.py`／`app.py` 往下追。

跨 task 的常駐約束（不必翻文件就該記得的）：

- 所有 task 的 Load 一律以唯一欄位 `upsert`，支援冪等重跑。
- task06 與 task08 共寫**同一張**向量表（見下方「向量搜尋」一節）。task07 歸檔完才輪到 task08 向量化，兩者前後依存，**改一邊時要一起更新記憶**。
- Streamlit（`dashboard_ui/`）僅讀 MongoDB＋POST Silver／Gold 端點，**不 import 任何 `task07_*` 套件**。
- 動 task07 前先確認要改的是 Bronze ETL、Silver 服務、Gold 服務還是共用的 `task07_common`——四者各自獨立部署。

> **v1 已除役、v2／lazy_loading 扶正**：`task01_obsidian_etl`、`task06_obsidian_embed_etl`、`task07_onenote_to_markdown` 三個 v1 資料夾均已淘汰，上表即為扶正後的版本。task01 過渡期仍並寫 v1 的 `obsidian_summary`，待 backfill 到 `notes_summary` 後擇期淘汰。

> **分支職責**：
> - `main` — 一切分支的最終彙整；push 到此觸發 **prod** 環境部署。
> - `develop` — feature 分支的整合處；push 到此觸發 **dev** 環境部署。
> - task01–task06（含 task01_v2、task06_v2）：`feature/etl-pipeline`
> - task07（lazy_loading）的 Bronze ETL、task08：`feature/html-to-markdown`
> - task07（lazy_loading）的 Silver／Gold 服務本體：`feature/html-to-markdown` 起草 → `feature/dashboard-ui` 定稿 → 合併回 `feature/html-to-markdown`
> - Streamlit、AI agent 串接、task07 Silver 端口（8002）與 Gold 端口（8003）實作：`feature/dashboard-ui`

### Dashboard UI（`dashboard_ui/`）

- `app.py` — 首頁（HOME）：讀取所有 MongoDB collections，繪製雷達圖（plotly）、KPI 卡片、GitHub 最近專案、刷題三相 donut chart
- `pages/knowledge_factory.py` — 第二頁「Chasing Data Engineering」：Tech Stack Overview（13 層技術堆疊卡片，見 `utils/tech_stack_diagram.py`）＋ Data Lineage（9 張 DAG SVG，從 GCS `personal-vaults` 讀取並以 `st.cache_data` 快取、失敗顯示 Image Not Found）。此頁為原 `knowledge_factory2.py` 扶正而來，舊版 `knowledge_factory.py`（ETL 架構圖／里程碑）已除役
- `utils/` — MongoDB 查詢封裝（`interact_with_mongodb.py`）、資料預處理（`precomputing.py`）、UI 元件（`ui_elements.py`）、Tech Stack 技術堆疊圖（`tech_stack_diagram.py`，純 inline style + base64 SVG，供 `st.html`）、GCS 讀取（`gcs_reader.py`，`read_text` / `read_bytes_as_base64`）
- `agents/` / `agent_tools/` — Phase III AI Agent（使用 Google Agent Platform Gemini + MongoDB Atlas Vector Search）

### 向量搜尋（task06 / task08 共用）

- Embedding model：`gemini-embedding-2`（Agent Platform，多模態，維度 1536、L2 normalize）
- Vector collection：`note_vectors_multimodal`（task06 與 task08 共寫，血緣欄統一 `md_path`）
- Vector index name：`obsidian_vectors_index2`，在 MongoDB Atlas Console 手動建立
- 查詢方式：`$vectorSearch` stage，similarity = cosine

### GCS 整合

task01 / task06 的 Extract 步驟在 Phase II 之後改為從 GCS bucket `personal-vaults` 讀取 `.md` 檔；憑證由 `GCS_USER_CREDENTIALS` 指定 service account JSON（地端解除 `main.py` 內註解後轉寫成 `GOOGLE_APPLICATION_CREDENTIALS`，雲端走 ADC）。

## 環境變數

變數定義於 `.env`（本地開發，詳見 `.env.example`）或 GCP Secret Manager（部署）。**每個變數的必填／選填、預設值與取得方式，寫在該 task 資料夾 README 的 `Configuration` 章節**；此處只列全貌與跨 task 的共用約束。

**MongoDB（所有 task 與 dashboard 都要）**
- `MONGO_ALTAS_URI`、`MONGO_DB_NAME`

**GCP 憑證**
- `GCS_USER_CREDENTIALS` — GCS service account JSON key 的路徑。task01／task06／task08 在 `main.py` 的 `if __name__ == "__main__"` 區塊把它轉寫成 `GOOGLE_APPLICATION_CREDENTIALS`；task07 三服務由 `task07_common/gcs.py` 的 `get_client_on_premise()` 直接讀。兩條路徑都**只有地端需要、且需先解除腳本內的註解**，雲端改由 Cloud Run runtime SA 的 ADC 供給。
- `AGENT_PLATFORM_USER_CREDENTIALS` — Agent Platform（前身是 Vertex AI）service account JSON key 的路徑，同樣是地端解除註解才生效（task06、task07 Silver、task08、`dashboard_ui/agent_tools/`）。
- `GCP_PROJECT_ID` — 呼叫 Agent Platform 的 GCP 專案 ID（雲端與地端都要）。
- `GOOGLE_APPLICATION_CREDENTIALS` — 不需為 ETL 手動填寫：它是上述轉寫的產物，或 dashboard／task07 服務在地端走 ADC 時的憑證來源。

**各來源系統的憑證**
- `GITHUB_TOKEN`、`GITHUB_USERNAME`、`GITHUB_MAIL`（task02）
- `LEETCODE_USERNAME`、`LEETCODE_SESSION`、`CSRF_TOKEN`（task03 的 LeetCode 端）
- `CCCLUB_USERNAME`、`CCCLUB_PASSWORD`（task03 的 ccClub 端）
- `GOOGLE_SHEET_KEY`（task05）— 可填 service account JSON key 的路徑（地端），或直接存 decode 後的 JSON 字串（雲端）；程式以 `os.path.isfile()` 判斷走哪一條
- `ONENOTE_CLIENT_ID`（task07 Bronze）— Azure App Registration Client ID（公用用戶端、`Notes.Read`）

**資料湖與稽核**
- `ONENOTE_GCS_BUCKET`（task07／task08，選填）— 資料湖 bucket 名稱，未宣告則預設 `onenote-vaults`。task01／task06 的 `personal-vaults` 是寫死在程式常數裡的，沒有對應變數。
- `ENVIRONMENT`（task07 Bronze／Silver 必填）— 只能是 `local`／`dev`／`prod`，會寫進 audit log；未知值會 raise。task07 Gold 不讀此變數。Silver 在雲端由 workflow 依分支寫入（`--set-env-vars ENVIRONMENT=<env>`），地端才需自己填進 `.env`。

**Dashboard（`dashboard_ui/`）**
- `SILVER_ENDPOINT_URL`、`GOLD_ENDPOINT_URL` — 審查頁 POST 的端點（本機預設 `http://localhost:8002/enrich`、`http://localhost:8003/archive`）
- `COHERE_API_KEY` — RAG reranker
- `ERD_LINK` — 第二頁「Chasing Data Engineering」的 ERD 外部連結
- `ROLE_ML_USERNAME`／`ROLE_ML_PASSWORD`、`ROLE_OWNER_*`、`ROLE_SENIOR_*`、`ROLE_GUEST_*` — 四種角色的登入帳密（共 8 個），AI Agent 頁與審查頁共用
- `AI_AGENT_RATE_LIMIT` — 單次對話的 LLM 呼叫上限，選填、預設 20

## 部署架構（Phase II+）

每個 task 與服務各自打包 Docker image，由 `.github/workflows/deploy_*.yml`（九支，一支對一個資源）推送到 Artifact Registry repo `personal-skill-dashboard`，機密由 GCP Secret Manager 管理。

**環境由分支決定**：push 到 `main` → `prod`，其餘分支（`develop`）→ `dev`。Cloud Run 資源以後綴區分（`task01-obsidian-etl-prod`／`-dev`、`dashboard-ui-prod`／`-dev`）。兩環境共用同一組 Secret Manager secrets。

**Image tag 一律不可變**：同一份 image 貼三個 tag——`<sha7>`、`<env>-latest`、`<env>-<sha7>`；部署一律指定 `<env>-<sha7>`，`latest` 已停用，以保留回滾與除錯的可追溯性。

**資源型態**：task01–06、task08 是 Cloud Run **Job**（Cloud Scheduler 觸發）；`dashboard_ui`、task07 Silver／Gold 是 Cloud Run **Service**（8080）。dashboard 對外開放，Silver／Gold 需 ID token 驗證、由 dashboard 的 runtime SA 以 Cloud Run Invoker 呼叫；dashboard 的 `SILVER_ENDPOINT_URL`／`GOLD_ENDPOINT_URL` 由 workflow 在部署前查出同環境 Service URL 動態帶入。**task07 Bronze ETL 不納入部署**（互動式裝置流程授權，僅地端執行）。

**沒有檔案變更就不會觸發**（`paths` 過濾只對 push 生效）；要以同一份程式碼重新部署時，走各 workflow 的 `workflow_dispatch` 手動觸發。
