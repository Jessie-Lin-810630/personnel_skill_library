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

一律從專案根目錄執行。

```bash
# Streamlit dashboard
poetry run streamlit run dashboard_ui/app.py

# task07 的 Silver（8002）與 Gold（8003）端點，審查頁會呼叫，需與 dashboard 同時啟動
poetry run python -m task07_silver_service.app
poetry run python -m task07_gold_service.app

# 個別 ETL task 一律是 `poetry run python -m <task 資料夾>.main`，資料夾名見下方 ETL Tasks 索引
poetry run python -m task01_obsidian_etl_v2.main

# 測試：全部／單檔
poetry run python -m unittest discover -s tests
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

### Function Docstring 規範

函式層級（含 `_` 開頭的私有函式）一律 Google style、中文書寫，章節順序固定為
摘要 → 正文 → `Note:` → `Args:` → `Returns:` → `Raises:`。

1. **正文只講主流程**。取捨、風險、過渡期狀態、非顯而易見的前提一律進 `Note:`，且 `Note:` 放在 `Args:` 之前，
   讓「敘述 → 警示 → 結構化參考」形成三個閱讀區塊。
2. **機制與後果分開寫**。例外「怎麼拋」寫在 `Raises:`，「拋了之後呼叫端會處在什麼狀態」寫在 `Note:`，同一句話不出現兩次。
3. **就地修改一定在 `Returns:` 講明**，例如「這是就地修改，回傳的與傳入的是同一個物件」。
   本專案多處呼叫端根本沒接回傳值（如 `archive_note`），不寫明會讓讀者以為回傳的是另一份資料。
4. **不造集合名詞**。禁用 `archived 端`／`raw 端`／`落地`／`側` 這類中文讀不順的行話，該講欄位就直接列欄位名。
5. **不自創術語**。領域通用語照用（`data lineage`、`upsert`、`CDC`、`cross-encoder`），
   但**不可自行拼接成中文複合詞**——`血緣鍵`、`冪等鍵` 都是造出來的，不是通用語。
   通用語在中文語境確實難讀時才改寫成白話，改寫前不得先造詞。
6. **有該行為就不可漏 section**。有參數就要有 `Args:`；有回傳值就要有 `Returns:`，
   回傳 `None` 也要寫，並交代結果寫到哪裡去了（MongoDB／GCS／就地修改的參數）；會拋例外就要有 `Raises:`。
   函式本身沒有該行為才可省略，不硬補。

> 完整範例見 [`task01_obsidian_etl_v2/silver_transform_markdown/l_archive_markdown.py`](/task01_obsidian_etl_v2/silver_transform_markdown/l_archive_markdown.py) 的 `archive_note()`。

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
| task07 共用 | `task07_common/` | 三服務共用的 `gcs`／`audit_log`／`hashing`／`topic`／`auth` | 同上 |
| task08 | `task08_onenote_embed_etl/` | 把 OneNote 歸檔筆記向量化 | `feature/html-to-markdown` |

**漸進式揭露**：要動哪個 task，就照下列順序讀，資訊夠了就停，不要一開始就翻腳本。

1. **該資料夾的 `README.md`**（每個 task 與 `dashboard_ui/` 都有）— 資料來源、輸出目的地、DataFlow、Configuration、collection schema、啟動方式都在這層，多數改動讀到這裡就足夠。
2. **`doc/*_summary.md`**（README 不足時才讀，取分支層級的設計脈絡與決策理由）— task01–task06 讀 [`branch_etl_pipeline_summary.md`](doc/branch_etl_pipeline_summary.md)；task07／task08 讀 [`branch_onenote_lazy_loading_summary.md`](doc/branch_onenote_lazy_loading_summary.md)；Streamlit 與 AI Agent 讀 [`branch_dashboard_ui_summary.md`](doc/branch_dashboard_ui_summary.md)。
3. **`.py` 腳本本體**（前兩層都沒寫到的實作細節才進來）— 入口從 `main.py`／`app.py` 往下追。

跨 task 的常駐約束（不必翻文件就該記得的）：

- 所有 task 的 Load 一律以唯一欄位 `upsert`，支援冪等重跑。
- task06 與 task08 共寫**同一張**向量表 `note_vectors_multimodal`，並共用同一個 Atlas index。task07 歸檔完才輪到 task08 向量化，兩者前後依存，**改一邊時要一起更新記憶**。embedding 模型、維度、index 名稱與建立方式見 [`branch_etl_pipeline_summary.md`](doc/branch_etl_pipeline_summary.md)。
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
- `utils/` — MongoDB 查詢封裝（`interact_with_mongodb.py`）、資料預處理（`precomputing.py`）、UI 元件（`ui_elements.py`）、Tech Stack 技術堆疊圖（`tech_stack_diagram.py`，純 inline style + base64 SVG，供 `st.html`）、GCS 讀取（`gcs_reader.py`，`read_text` / `read_bytes_as_base64`）、登入 gate 與角色推導（`auth_gate.py`，兩頁共用的登入畫面也在此）、簽發呼叫 Silver／Gold 用的 `X-User-Token`（`user_token_for_silver_and_gold.py`）
- `agents/` / `agent_tools/` — Phase III AI Agent（使用 Google Agent Platform Gemini + MongoDB Atlas Vector Search）

## 環境變數

變數定義於 `.env`（本地開發，詳見 `.env.example`）或 GCP Secret Manager（部署）。**每個變數的必填／選填、預設值與取得方式，寫在該 task 資料夾 README 的 `Configuration` 章節**；此處只列跨 task 的共用約束。

- `MONGO_ALTAS_URI`、`MONGO_DB_NAME` — 所有 task 與 dashboard 都要。
- `GCS_USER_CREDENTIALS`、`AGENT_PLATFORM_USER_CREDENTIALS` — service account JSON key 的路徑，**只有地端需要，且需先解除腳本內的註解**才生效；雲端一律改由 Cloud Run runtime SA 的 ADC 供給。task01／06／08 在 `main.py` 把前者轉寫成 `GOOGLE_APPLICATION_CREDENTIALS`，task07 三服務則由 `task07_common/gcs.py` 直接讀。
- `GOOGLE_APPLICATION_CREDENTIALS` — 不需手動填寫，它是上述轉寫的產物，或地端走 ADC 時的憑證來源。
- `GCP_PROJECT_ID` — 呼叫 Agent Platform 用，雲端與地端都要。
- `ENVIRONMENT` — task07 Bronze／Silver 必填，只能是 `local`／`dev`／`prod`，未知值會 raise；task07 Gold 不讀。Silver 在雲端由 workflow 依分支寫入，地端才需自己填。
- 資料湖 bucket：task07／08 可用 `ONENOTE_GCS_BUCKET` 覆寫，未宣告則預設 `onenote-vaults`；task01／06 的 `personal-vaults` 寫死在程式常數裡，**沒有對應變數**。
- `USER_ALLOWLIST`、`TOKEN_ISSUER_SA` — dashboard、Silver、Gold 三者都要。

各來源系統的憑證（`GITHUB_*`、`LEETCODE_*`、`CCCLUB_*`、`GOOGLE_SHEET_KEY`、`ONENOTE_CLIENT_ID`）與 dashboard 專用變數（兩個端點 URL、`COHERE_API_KEY`、`ERD_LINK`、`AI_AGENT_RATE_LIMIT`、OIDC 登入設定）見各自 README 的 `Configuration`。

## 部署架構（Phase II+）

每個 task 與服務各自打包 image、各有一支 `.github/workflows/deploy_*.yml`，機密走 GCP Secret Manager。
image tag 規則、Artifact Registry 位置、Secret 對應、workflow 觸發條件與手動重跑方式，見
[`branch_developd_gcp_deploy_hand_over.md`](doc/branch_developd_gcp_deploy_hand_over.md)；各資源的部署步驟見該 task README 的 Get Started。

不翻文件就該記得的約束：

- **環境由分支決定**：push 到 `main` → `prod`，其餘分支（含 `develop`）→ `dev`；Cloud Run 資源以 `-prod`／`-dev` 後綴區分，兩環境共用同一組 secrets。
- **資源型態**：task01–06、task08 是 Cloud Run **Job**（Cloud Scheduler 觸發）；`dashboard_ui`、task07 Silver／Gold 是 Cloud Run **Service**（8080）。
- **Silver／Gold 不對外**：由 `dashboard_ui` 的 runtime SA 以 Cloud Run Invoker 呼叫並用 ID token 驗證 `dashboard_ui`；端點自身 URL 由 github workflow 部署時動態帶入，**不可寫死**。
- **task07 Bronze ETL 不納入部署**：互動式裝置流程授權，僅地端執行。
