# 個人技能演進看版 × 具追溯性保證之知識庫文件檢索系統  × 知識檢索 Agent

![Python](https://img.shields.io/badge/Python-3.14-3776AB?style=plastic&logo=python&logoColor=white)
![Poetry](https://img.shields.io/badge/deps-Poetry-60A5FA?style=plastic&logo=poetry&logoColor=white)
![MongoDB Atlas](https://img.shields.io/badge/DB-MongoDB%20Atlas-47A248?style=plastic&logo=mongodb&logoColor=white)
![FastAPI](https://img.shields.io/badge/backend-FastAPI-009688?style=plastic&logo=fastapi&logoColor=white)
![Streamlit](https://img.shields.io/badge/UI-Streamlit-FF4B4B?style=plastic&logo=streamlit&logoColor=white)
![Plotly](https://img.shields.io/badge/analytics-Plotly-%233F4F75.svg?style=plastic&logo=plotly&logoColor=white)
![SSD](https://img.shields.io/badge/SSD-OpenSpec-%23015A69.svg?style=plastic&logo=WCAG&logoColor=white)
![Mermaid](https://img.shields.io/badge/dataflow-Mermaid-FF3670?style=plastic&logo=mermaid&logoColor=white)
![ERD](https://img.shields.io/badge/ERD-Lucid%20chart-FFCE1B?style=plastic&logo=lucid&logoColor=white)
![Google Cloud](https://img.shields.io/badge/SaaS-GCP%20Cloud%20Platform-4285F4?style=plastic&logo=googlecloud&logoColor=white)
![Docker](https://img.shields.io/badge/Container-Docker-2496ED?style=plastic&logo=docker&logoColor=white)
![GitHub Actions](https://img.shields.io/badge/CI%2FCD-GitHub%20Actions-000000?style=plastic&logo=githubactions&logoColor=white)
![Ruff](https://img.shields.io/badge/lint-Ruff-D7FF64?style=plastic&logo=ruff&logoColor=black)
![Claude Code](https://img.shields.io/badge/AI-Claude%20Code-D97757?style=plastic&logo=claudecode&logoColor=white)
![Google Gemini](https://img.shields.io/badge/AI-google%20gemini-E4A0F7?style=plastic&logo=google%20gemini&logoColor=white)
![LangChain](https://img.shields.io/badge/AI-langchain-%231C3C3C.svg?style=plastic&logo=langchain&logoColor=white)  \
![Google Sheets](https://img.shields.io/badge/data%20source-Google%20Sheets-%2334A853?style=plastic&logo=googlesheets&logoColor=white)
![Microsoft](https://img.shields.io/badge/data%20source-Microsoft%20OneNote-0078D4?style=plastic&logo=microsoft&logoColor=white)
![LeetCode](https://img.shields.io/badge/data%20source-LeetCode-000000?style=plastic&logo=LeetCode&logoColor=#d16c06)
![Obsidian](https://img.shields.io/badge/data%20source-Obsidian-%23483699.svg?style=plastic&logo=obsidian&logoColor=white)


## About

**Personnel Skill Library** 是一套以資料工程手法打造的**個人技能看板**：把散落在多個平台的學習與工作足跡（Obsidian／OneNote 筆記、GitHub、LeetCode／ccClub 刷題、Google Sheet 個人 KPI 統整表）透過 ETL 任務組合多條 data pipelines 匯整進 MongoDB Atlas 與 GCS 資料湖，再以 Streamlit 呈現技能雷達、專案架構、資料管線健康度等頁面，最後串接一個以向量檢索為基礎的 **AI 知識 Agent**，用自然語言查詢知識庫。

**運作概念**：運行 7 支 data pipelines，其中有 2 支中型資料管道 [task01](#feature)、[task07](#feature)，這 2 支 data pipeline 按照期待的資料產出品質，切出 **Bronze、Silver、Gold** medallion 架構三層，每一層根據資料治理目標有各自的 ETL 實作步驟。Bronze 層為原始資料萃取與導入 GCS 資料湖，即 data ingestion。Silver 層之後為乾淨的知識文檔，Gold 層則以一個將乾淨文檔執行歸檔任務。歸檔的文檔將會銜接下游 2 支資料管道 [task06](#feature)、[task08](#feature) ，執行向量化任務，供 RAG Agent 檢索。  \
RAG 檢索系統是透過 Python-Streamlit 製成的介面來與使用者互動，並實作前端、後端服務讀寫權限分離，避免資料表誤改、誤刪等污染風險。各 data pipelines 與前端介面的實作引導連結，詳見 [Feature Table](#feature)。

**設計要點**：data pipelines 程式腳本大量使用資料的 hash 演算結果保證管道重試時的冪等性 (idempotency)，資料表設計則強調資料血緣的可追溯性，例如：主要文本的版本號碼、主要文本引用的圖片指向哪個路徑、清理完成的文本來自於哪份原始文本，從而**保護向量檢索庫的 grounding 指向 single truth、故障排查時也會比較精準。這亦是本專案所希望強調的資料治理品質**。最後，因應長文本的資料特性會使得輸入的 tokens 較多，data pipelines 亦謹慎採用**增量載入 (incremental load) 設計模式**，避免無意義的重複請求 APIs 端口。

> [Demo Video for task01, task06, task07 and task08 on Youtube](https://youtu.be/U-Fm0WrquWU)

> [Live Implementation (all tasks)](https://dashboard-ui-219985522999.asia-east1.run.app)

## Feature

每個子資料夾都是一塊可獨立執行的功能，並附專屬 README 說明資料來源、schema 與啟動方式：

| 功能 | README | 說明 |
| ---- | ------ | ---- |
| Obsidian Medallion ETL | [task01_obsidian_etl_v2](./task01_obsidian_etl_v2/README.md) | 從 GCS 資料湖掃出新增或變更的 Obsidian 筆記，清洗成帶 frontmatter、分類、標籤與圖片引用的乾淨 markdown 歸檔回 GCS，中繼資料與軟刪除狀態寫入 MongoDB Atlas，供下游 task06 挑出待向量化筆記。<br>另對筆記現況做每日快照，供看板首頁讀取。 |
| GitHub ETL | [task02_github_restapi_etl](./task02_github_restapi_etl/README.md) | 從 GitHub REST API 抓本人持有與協作的 repo、本人 commit 與 README，清洗成每個 repo 一筆的文檔與一份彙整摘要。<br>寫入 MongoDB Atlas，供看板首頁呈現最近專案與語言／角色分佈。 |
| LeetCode + ccClub ETL | [task03_leetcode_ccClub_etl](./task03_leetcode_ccClub_etl/README.md) | 從 LeetCode GraphQL 與 ccClub REST API 抓已解題目，清洗成每題一筆的文檔並統計難度／主題分佈。<br>寫入 MongoDB Atlas，供看板首頁的刷題 donut chart 讀取。 |
| Skill Radar ETL | [task05_googlesheet_skill_etl](./task05_googlesheet_skill_etl/README.md) | 從 Google Sheet 讀「生技」「資料工程」兩張技能盤點表，把能力勾選依複雜性／獨立性／影響力加權算成分數與雷達軸層級。<br>寫入 MongoDB Atlas，供看板首頁繪製技能雷達圖。 |
| Obsidian 向量化 | [task06_obsidian_embed_etl_v2](./task06_obsidian_embed_etl_v2/README.md) | 挑出 task01 已歸檔但尚未向量化的筆記，從 GCS 下載歸檔內文與圖片後切塊、多模態向量化。<br>向量寫入 MongoDB Atlas 並清除軟刪除筆記的過期向量，供 AI 知識 Agent 做 RAG 檢索。 |
| OneNote Bronze ETL | [task07_onenote_to_markdown_lazy_loading](./task07_onenote_to_markdown_lazy_loading/README.md) | 從 Microsoft Graph API 下載 OneNote 每頁筆記的 HTML 原文與內嵌圖片，以日期分區保留多版本存進 GCS 資料湖。<br>版本中繼資料、資料血緣與 API 稽核紀錄寫入 MongoDB Atlas，交給下游 Silver 服務做語意擴寫。 |
| OneNote Silver 服務 | [task07_silver_service](./task07_silver_service/README.md) | 由看板審查頁 on-demand 呼叫的 FastAPI 端點，把指定版本的 HTML 原文連同內嵌圖片送多模態 LLM，產出冠上 frontmatter 的 enriched markdown 存回 GCS。<br>更新 Bronze 寫入 MongoDB Atlas 的中繼資料，LLM 呼叫紀錄一併寫入，交給下游 Gold 服務做人工審查與歸檔。 |
| OneNote Gold 服務 | [task07_gold_service](./task07_gold_service/README.md) | 接收審查頁的核可／退件決定：核可時把 Silver 產出的 markdown 與引用圖片複製到 GCS 歸檔層，退件時只更新 MongoDB Atlas 的中繼資料。<br>最終，歸檔層存下的文件交給下游 task08 向量化。 |
| OneNote 向量化 | [task08_onenote_embed_etl](./task08_onenote_embed_etl/README.md) | 挑出 task07 已歸檔但尚未向量化的 OneNote 筆記，從 GCS 下載歸檔內文與圖片後切塊、多模態向量化。<br>與 task06 共寫 MongoDB Atlas 的同一張向量表，供 AI 知識 Agent 做 RAG 檢索。 |
| Dashboard UI | [dashboard_ui](./dashboard_ui/README.md) | 六頁 Streamlit 看板：讀取各 task 寫入 MongoDB／GCS 的成果，呈現技能雷達、專案架構、攝取與檢索品質等圖表。<br>另提供 OneNote 人工審查頁，從這裡請求 Silver／Gold 服務做語意擴寫與歸檔，以及 AI 知識 Agent 的向量檢索問答入口。 |


## Tech Stack

| Layer | 技術 | 目的 |
| ----- | ---- | ---- |
| 01 Frontend | Streamlit、Plotly、Pandas、CSS (`st.markdown`) | 多頁看板、互動圖表與版面 |
| 02 APIs & Backend Logic | FastAPI、GitHub REST／LeetCode GraphQL／Microsoft Graph／Google Sheets API、BeautifulSoup4、Requests、RapidFuzz | Silver/Gold 服務端點與各來源資料抓取／解析 |
| 03 Database & Storage | MongoDB Atlas、GCS、Atlas Vector Search、PyMongo | 文檔資料庫、資料湖、向量檢索索引 |
| 04 Auth & Permissions | GCP Workload Identity Federation、Service Account、MSAL (Azure OAuth)、Google OAuth、GitHub PAT、Cookie 驗證 | CI/CD 與各服務／來源的身分驗證 |
| 05 Hosting & Deployment | Cloud Run Service／Job、Artifact Registry、Docker | 容器化與雲端執行 |
| 06 Cloud & Compute (AI/ML) | Google Cloud Platform、Agent Platform（Gemini）、Cohere、LangChain | LLM enrichment、多模態向量化、切塊與重排序 |
| 07 CI/CD & Version Control | Git、GitHub Actions、多分支策略、Poetry、pyenv | 自動 build/push/deploy（Cloud Run Job）與環境管理 |
| 08 Security | GCP Secret Manager、pre-commit hooks、python-dotenv、Claude Code hooks | 機密管理與提交前防護 |
| 09 Rate Limiting & Flow Control | LLM 斷路器、Incremental loads、Lazy Loading／on-demand 觸發 | 保護外部 API、只處理變更、tokens 消耗量管制 |
| 10 Caching | `st.cache_resource`、`sha256 hash`、`md5 hash` | 減少重算與重複 LLM 呼叫、防競態 |
| 11 Scaling | Cloud Run 自動擴展、微服務拆分（:8002／:8003） | 水平擴展與權限／部署隔離 |
| 12 Error Tracking & Logs | Ruff、Loguru、`onenote graph api logs`、`multimodal LLM calling logs` | 結構化日誌、API/LLM 稽核、靜態檢查 |
| 13 Availability & Recovery | Upsert 手法 | 可重跑、可稽核、可回溯 |


## Architecture

### Request Flow between Tasks
![image](./doc/architecture.png)

### Entity-Relationship Diagram
各 task 寫入 MongoDB Atlas 的 collection 之實體關係圖 (ERD) 可見 [Lucid chart](https://lucid.app/lucidchart/d8a25860-ca13-46fd-9286-672e9530c4f7/edit?viewport_loc=-31462%2C-6017%2C5049%2C2318%2C0_0&invitationId=inv_1f645ec2-306a-43af-a8ef-9650a6e8e9b7)。

## Project Structure

```plaintext
personnel_skill_library/                      # 專案根目錄
├── task01_obsidian_etl_v2/                   # Obsidian Medallion ETL
│   ├── silver_transform_markdown/              # 清洗 → 歸檔 → 軟刪除
│   └── gold_notes_metadata_snapshot/           # 每日快照
├── task02_github_restapi_etl/                # GitHub ETL
├── task03_leetcode_ccClub_etl/               # LeetCode + ccClub ETL
├── task05_googlesheet_skill_etl/             # Skill Radar ETL
├── task06_obsidian_embed_etl_v2/             # Obsidian 向量化
├── task07_onenote_to_markdown_lazy_loading/  # OneNote Bronze ETL（地端）
├── task07_silver_service/                    # OneNote Silver 服務（:8002）
├── task07_gold_service/                      # OneNote Gold 服務（:8003）
├── task07_common/                            # Bronze／Silver／Gold 共用工具
├── task08_onenote_embed_etl/                 # OneNote 向量化
├── dashboard_ui/                             # Dashboard UI
│   ├── pages/                                  # 六頁看板（HOME 為 app.py）
│   ├── agents/                                 # AI 知識 Agent
│   ├── agent_tools/                            # 向量檢索與重排序
│   └── utils/                                  # MongoDB／GCS 讀取、繪圖、登入與身分憑證
├── .streamlit/                               # Streamlit 主題設定與 OIDC 登入設定
├── .github/workflows/                        # 各 task 與 dashboard 的部署 workflow
├── docker/                                   # 各 task 與 dashboard 的 Dockerfile
├── doc/                                      # 分支摘要、schema 定義、README 模板
├── openspec/                                 # OpenSpec 變更流程
├── tests/                                    # unittest（全 mock，不連外部服務）
├── .env.example                              # 環境變數示範檔 (填值後改名為 .env)
├── pyproject.toml                            # Poetry 依賴
├── poetry.lock                               # Poetry 依賴
└── CLAUDE.md                                 # Claude Code 專案指引
```

## Get Started

### 1. Clone 與環境建置

先 clone：

```bash
git clone -b main --single-branch --depth 1 https://github.com/Jessie-Lin-810630/personnel_skill_library.git

cd personnel_skill_library
```

依照使用目的擇一路徑：

#### 路徑 A — Guest：只想用 Docker 快速跑其中一支 task

適合不打算參與開發、只想跑單一 task 看結果的人。只需要 Docker，本機不必裝 Python／Poetry。

1. 備妥該 task 需要的環境變數，寫進專案根目錄 `.env`（見 [第 2 節](#2-環境變數與外部設定)）。
2. build 並執行該 task 的 image，見 task 各自的 [README.md](#feature) 章節「Run on-premise with Docker Container」：
    ```bash
    docker build -f docker/Dockerfile.task02 -t task02:latest .
    docker run --rm --env-file ./.env task02:latest
    ```

> task07 Bronze 需互動式瀏覽器授權，目前僅設計為地端直接執行、無 Docker（見其 [README.md](./task07_onenote_to_markdown_lazy_loading/README.md)）。

#### 路徑 B — Developer：完整重現開發環境（pyenv + Poetry）

適合想完整重現作者環境、參與開發者。

- (非必要) 如您的機器沒安裝 python 3.14.x 版本，建議使用 pyenv 安裝。
    ```bash
    pyenv install 3.14.2
    ```

- 找尋 pyenv 把 python 3.14.2 安裝在哪
    ```bash
    for v in $(pyenv versions --bare); do echo "$(pyenv root)/versions/$v/bin/python"; done
    ```
    執行以上指令後您可能會看到至少一行這種結構的路徑字串：
    ```bash
    /.../.../.pyenv/versions/3.12.8/bin/python
    /.../.../.pyenv/versions/3.14.2/bin/python
    ```

- (非必要) 如您的機器尚未安裝 poetry 套件管理工具，參考[官方指令安裝 poetry](https://python-poetry.org/docs/#installing-with-the-official-installer).

- 鎖定 poetry 使用 python 3.14 建立虛擬環境
    ```bash
    poetry env use <the-path-to-python-3.14-by-pyenv>
    ```

- 建立並啟用虛擬環境
    ```bash
    poetry install --no-root
    poetry shell
    ```

---

### 2. 環境變數與外部設定

```bash
cp .env.example .env      # cp 後於 .env 填入真實值
```
- .env.example 變數大致上有:
    - **資料庫**：在 [MongoDB Atlas](https://www.mongodb.com/atlas) 建立免費叢集、database user 與 Network Access，把連線字串填入 `MONGO_ALTAS_URI`、資料庫名填 `MONGO_DB_NAME`（本專案統一預設 skill_dashboard）。向量搜尋另需在 Atlas Console 手動建立 Vector Search index（見 task06／task08 README）。
    - **雲端 JSON 憑證**：若您在*地端*運行任一 task，建議將 task 所需要的雲端服務帳戶 (各 service account) 的 JSON key 放在 `./env/`（如 `env/gcs-user.json`、`env/agent-platform-user.json`），並在 `.env` 以獨立變數指向憑證檔案路徑。
    - 其餘專屬單一 task 的環境變數，建議直接詳見各自 [README.md](#feature) 的 Configuration 節。

```bash
cp .streamlit/secrets.toml.example .streamlit/secrets.toml  # 於 secrets.toml 填入真實值
```
- secrets.toml.example 裡的變數專門處理 dashboard 部分頁面需要的 Google 帳號登入設定，見 [`dashboard_ui/README.md`](./dashboard_ui/README.md) 的 Get Started。

### 3. 執行

```bash
# 跑一支 ETL（以 task02 為例）
poetry run python -m task02_github_restapi_etl.main

# 啟動 streamlit app
poetry run streamlit run dashboard_ui/app.py

# FastAPI services called by OneNote review page of streamlit app
poetry run python -m task07_silver_service.app
poetry run python -m task07_gold_service.app

# 執行全部測試
poetry run python -m unittest discover -s tests
```

各 task／dashboard 的 Docker 與 Cloud Run 部署方式，見各自 README 的 Get Started。

### 4. （選用）OpenSpec 變更流程

本專案以 [OpenSpec](https://github.com/Fission-AI/OpenSpec) 管理規格變更。若要沿用：

```bash
npm install @fission-ai/openspec@latest
```

```bash
openspec update
```

```bash
openspec init
```

### 5. （選用）以 Claude Code 接手開發

在 repo 根目錄直接啟動 `claude`，即會自動載入根目錄的 [`CLAUDE.md`](./CLAUDE.md)（專案指引：ETL 命名規則、module docstring 規範、各 task 的資料流與 schema 指路）作為 context。


## What's Next?

- [x] **AI Knowledge Agent 的 OAuth2 驗證**：已改為 Google 帳號登入（`st.login()`），取代原本粗分四層的帳密。角色由 email 允許清單推導，審查頁的操作另以 `X-User-Token` 讓後端端點自行驗證是哪一位使用者下的指令。
- [ ] **告警機制**：Cloud Run Job 執行 ETL 遇 4xx/5xx 時捕捉例外並發送通知（Email／Pub/Sub）。
- [ ] **淘汰 v1 過渡並寫**：task01 v2 過渡期同時並寫 v1 `obsidian_summary`，待 backfill 到 `notes_summary` 後淘汰。
