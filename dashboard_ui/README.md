# Dashboard UI — 個人技能看板（Streamlit）

> 本文件是 **dashboard_ui 專用的執行指引**，補足專案根目錄 high-level [`README.md`](../README.md) 未涵蓋的實作細節。
> dashboard 不是單一 ETL pipeline，而是把各 task 寫進 MongoDB／GCS 的成果，以 Streamlit 多頁形式呈現，並串接 Phase III 的 AI 知識 Agent。
> 環境安裝的「共用前置」（pyenv + Poetry、MongoDB Atlas 帳號、Docker Desktop）請見根目錄 [`README.md`](../README.md)。


# Purpose

個人技能看板以 Streamlit 呈現，共六頁：**HOME 技能總覽**、**Knowledge Factory 專案架構**、**Ingestion & Data Quality 攝取品質**、**Retrieval & Search Quality 檢索品質**、**OneNote 審查頁**、**AI Knowledge Agent**。前四頁純讀 MongoDB／GCS 呈現圖表，供訪客瀏覽技能雷達、專案架構與資料管線健康度；OneNote 審查頁提供登入後的多版本人工審查與歸檔；AI Knowledge Agent 則以向量檢索回答筆記查詢。`app.py` 是 HOME 兼 Streamlit 進入點，其餘五頁放在 `pages/`。


# Table of Contents
- [Purpose](#purpose)
- [Feature（各頁功能與關聯）](#feature各頁功能與關聯)
- [Project Structures](#project-structures)
- [Configuration](#configuration)
- [Schema — `chat_history`](#schema--chat_history)
- [Get Started](#get-started)
  - [(Option 1) Run on-premise without Docker Container](#option-1-run-on-premise-without-docker-container)
  - [(Option 2) Run on-premise with Docker Container](#option-2-run-on-premise-with-docker-container)
  - [(Option 3) Run as Cloud Run Service](#option-3-run-as-cloud-run-service)


---
# Feature（各頁功能與關聯）

## HOME — 個人技能技能總覽（`app.py`）

- **能看到**：雙領域兩張技能雷達圖 (本專案依照作者自身背景以生物製藥領域與資料工程領域架設範例)、KPI 卡片、GitHub 最近專案卡片、刷題比例。
- **能互動**：以下拉選單切換雷達軸對應的經手任務、檢視任務明細表。
- **登入控管**：無，開放瀏覽。
- **關聯**：task02、task03、task05。

## Knowledge Factory — 本專案架構歷程之網頁版（`pages/knowledge_factory.py`）

- **能看到**：13 層 Tech Stack Overview、以 9 張 SVG 繪製呈現的 task01-task07 DAG 流程圖。
- **能互動**：瀏覽各層技術堆疊與資料血緣圖。
- **登入控管**：無。
- **關聯**：全專案架構展示。

## Ingestion & Data Quality — 攝取品質（`pages/ingestion_data_quality.py`）

- **能看到**：運行 Task01 v2 與 Task07 的 medallion architectures 一段時日後，所結算的資料品質評分結果。包含：筆記生命週期漏斗、archived vs rejected 筆記的標籤分佈、LLM token 累計等。
- **能互動**：資料攝取與擴寫完整度圖表。
- **登入控管**：無。
- **關聯**：task01、task07、task07 Silver。

## Retrieval & Search Quality — 檢索品質（`pages/retrieval_search_quality.py`）

- **能看到**：RAG 檢索品質評分介面，包含similarity vs rerank 分數散布圖、檢索輪數分佈與冷熱資料 treemap、檢索品質健康度雷達等。
- **能互動**：檢索端效能圖表。
- **登入控管**：無。
- **關聯**：透過 [AI Knowledge Agent](#ai-knowledge-agent--知識-agentpagesai_knowledge_agentpy) 互動一段時日後，自動累積後呈現於此。

## OneNote 審查頁（`pages/onenote_review.py`）

- **能看到**：登入後檢視與比對原始筆記與LLM enriched 筆記。
- **能互動**：生成、歸檔或是退件。
- **登入控管**：**有**。
- **關聯**：task07 Silver、task07 Gold。

## AI Knowledge Agent — 知識 Agent（`pages/ai_knowledge_agent.py`）

- **能看到**：對話式介面，回答筆記語意查詢、摘要。
- **能互動**：開新對話 → 輸入問題 → intent router 分流到 RAG agent → 回覆並記錄對話。
- **登入控管**：無。
- **關聯**：agents/、agent_tools/、task06、task08。


# Project Structures

```plaintext
dashboard_ui/
├── app.py                          # HOME（技能總覽）＋ Streamlit 進入點
├── pages/                          # Streamlit 多頁（檔名即頁面）
│   ├── knowledge_factory.py        # 專案架構：Tech Stack + Data Lineage
│   ├── ingestion_data_quality.py   # 攝取品質圖表
│   ├── retrieval_search_quality.py # 檢索品質圖表
│   ├── onenote_review.py           # OneNote 多版本審查（登入 + Silver/Gold 觸發）
│   └── ai_knowledge_agent.py       # Phase III AI 知識 Agent
├── agents/                         # Agent 本體
│   ├── intent_router_agent.py      # 意圖分流（keyword / LLM 兩法）
│   ├── rag_agent.py                # RAG 檢索問答
│   └── planning_agent.py           # 學習路徑規劃
├── agent_tools/                    # Agent 工具層
│   ├── query_rewriter.py           # 查詢改寫 + 推薦 tags
│   ├── query_with_vector_search.py # $vectorSearch 向量檢索
│   ├── reranker.py                 # 重排序
│   ├── chat_history.py             # 對話紀錄讀寫
│   ├── connect_to_google_genai.py  # 建立 Agent Platform client
│   └── types_and_constants.py      # 型別與常數定義
└── utils/                          # UI／查詢／繪圖工具
    ├── interact_with_mongodb.py    # MongoDB 查詢封裝
    ├── precomputing.py             # 資料預處理
    ├── ui_elements.py              # UI 元件（側欄、雷達、表格）
    ├── tech_stack_diagram.py       # Tech Stack 堆疊圖
    └── gcs_reader.py               # GCS 讀取
```


# Configuration

- 執行 dashboard 需要以下環境變數。
- **地端開發**：把 key/value 寫進專案根目錄 `.env`（複製 `.env.example` 後填入）。
- **雲端部署**：改存 GCP Secret Manager，容器啟動時注入為環境變數（見 [(Option 3)](#option-3-run-as-cloud-run-service)）。

| 變數名稱                          | 說明                                                                | .env.example 預設值             | 必填 |
| --------------------------------- | ------------------------------------------------------------------- | ----------------- | --- |
| `MONGO_ALTAS_URI`                 | MongoDB Atlas 連線字串                                              | 無，需自訂         | ✅  |
| `MONGO_DB_NAME`                   | 目標 database 名稱                                                  | skill_dashboard | ✅  |
| `GCP_PROJECT_ID`                  | Agent Platform 專案 ID            | 無，需自訂         | ✅ |
| `AGENT_PLATFORM_USER_CREDENTIALS` | 頁面 'ai_knowledge_agent' & 'OneNote_review' 呼叫 Agent Platform 用的 service account JSON key 檔路徑。| 無，地端需自訂 | **地端執行時** |
| `COHERE_API_KEY`                  | 頁面 'ai_knowledge_agent' 使用 reranker model 時所需要的 API key | 無，需自申請 | ✅ |
| `GOOGLE_APPLICATION_CREDENTIALS`  | 用於從 GCS 讀取圖像讓頁面 'knowledge_factory'&'OneNote_review' 渲染。 | 無，地端需自訂 | **地端執行時** |
| `SILVER_ENDPOINT_URL`             | 頁面 'OneNote_review' 呼叫 Silver enrichment service URL                          | **此預設值只適用於[地端無容器狀態下](#option-1-run-on-premise-without-docker-container)執行時**: `http://localhost:8002/enrich` | ✅，且因應執行環境，應作調整：<br>**在地端以 Docker 容器執行時**: `http://host.docker.internal:8002/enrich`<br>**雲端環境執行時**: 部署實際 URL |
| `GOLD_ENDPOINT_URL`               | 頁面 'OneNote_review' 呼叫 Gold archive service URL                 | **此預設值只適用於[地端無容器狀態下](#option-1-run-on-premise-without-docker-container)執行時**: `http://localhost:8003/archive` | ✅，且因應執行環境，應作調整：<br>**在地端以 Docker 容器執行時**: `http://host.docker.internal:8003/archive`<br>**雲端環境執行時**: 部署實際 URL|
| `ERD_LINK`                        | 頁面'knowledge_factory'的 ERD 連結                                     | 無，需自訂                | 選填 |
| `ROLE_ML_USERNAME` / `ROLE_ML_PASSWORD` | 頁面 'OneNote_review' ML/DL Engineer 角色的示範登入帳密              | 無，需自訂                | 選填 |
| `ROLE_OWNER_USERNAME` / `ROLE_OWNER_PASSWORD` | 頁面 'OneNote_review' Note Owner 角色的示範登入帳密           | 無，需自訂                | ✅ |
| `ROLE_SENIOR_USERNAME` / `ROLE_SENIOR_PASSWORD` | 頁面 'OneNote_review' Dept. Senior Specialist 角色的示範登入帳密 | 無，需自訂              | 選填 |
| `ROLE_GUEST_USERNAME` / `ROLE_GUEST_PASSWORD` | 頁面 'OneNote_review'訪客角色的示範登入帳密 | 無，需自訂              | 選填 |

> **地端執行時，關於 AGENT_PLATFORM_USER_CREDENTIALS 使用方式**：憑證被使用於 `agent_tools/connect_to_google_genai.py` 與 `agent_tools/query_with_vector_search.py` 的 client 建立。當您在地端執行時，請記得解除這兩份檔案中「地端測試跑下面區塊」的註解，程式即會知道要從環境變數 AGENT_PLATFORM_USER_CREDENTIALS 取得憑證。


# Schema — `chat_history`

- 每筆 = 一則訊息（user 或 model）。

| **欄位名稱** | **欄位語意** | **資料型別** | **值來源** |
| :--- | :--- | :--- | :--- |
| `_id` | MongoDB 自動生成的唯一識別碼 | ObjectId | MongoDB 自動產生 |
| `session_id` | 使用者點「開新對話」時生成的 uuid4，區分不同次對話 | String | pages/ai_knowledge_agent.py |
| `timestamp` | 紀錄寫入時間 | ISODate | save_chat_history() 執行時間 |
| `agent_type` | 此筆發生在與 `router` / `rag` / `planning` 的互動 | String | 各 agent 傳入固定值 |
| `role` | 此筆是 `model` 或 `user` 的訊息 | String | 各 agent 流程傳入 |
| `content` | 訊息文字（router+user 為 null；rag+user 為原始查詢；rag+model 為最後答案；超 2000 字元截斷並記 warning） | String | 依 agent 流程傳入模型輸出或使用者輸入 |
| `metadata` | model 輸出的背景資訊，內嵌欄位隨 `agent_type` 不同 | Object | 依 agent 流程 |

- **`metadata` 內嵌欄位（當 `agent_type="rag"` 且 `role="model"`）**：

    | **內嵌欄位** | **欄位語意** | **資料型別** | **值來源** |
    | :--- | :--- | :--- | :--- |
    | `model` | RAG 生成回覆採用的基礎模型 | String | agent_tools.types_and_constants.py |
    | `retrieved_chunks` | 向量檢索＋重排序後得到的資料塊 | Array (Object) | vector_search() + rerank_chunks() |
    | `note_files` | 陣列 `retrieved_chunks.file_path` 去重之後 | Array (String) | rerank_chunks() |
    | `search_optimize_method` | 查詢優化方式 | String | rag_query() 傳入常數 "rewrite_expand_rerank" |
    | `rewritten_query` | query rewriter 重寫後、用於向量搜尋的查詢語句 | String | rewrite_query() |
    | `recommended_tags` | query rewriter 推薦塞入 rewritten_query 的 tags，以增強 recall | Array (String) | rewrite_query() |

- **`metadata` 內嵌欄位（當 `agent_type="router"` 且 `role="model"`）**：

    | **內嵌欄位** | **欄位語意** | **資料型別** | **值來源** |
    | :--- | :--- | :--- | :--- |
    | `method` | 意圖判斷法（`r1_keyword` 純關鍵字，或`r2_llm` 調用模型） | String | route() 傳入 |
    | `intent_score` | 意圖相似度分數 | Float | intent_router_agent.py |
    | `model` | 使用 `method="r2_llm"` 時所配合的 model | String | types_and_constants.py |
    | `user_query` | router 接收的使用者原始查詢 | String | pages/ai_knowledge_agent.py |

- 當 `role="user"` 時，`metadata` 內嵌欄位為空物件({})。


# Get Started

1. 準備 MongoDB Atlas（見根目錄 [`README.md`](../README.md)），並確認各 task 已把資料寫入對應 collection（否則圖表為空）。

2. 依 [Configuration](#configuration) 把**所有**環境變數填進 `.env`、各 service account 的 JSON key 放進 `./env/`。一次備齊，六頁才都能正常運作。service account 的 IAM 角色設定建議後文[option 1](#option-1-run-on-premise-without-docker-container)、[option 2](#option-2-run-on-premise-with-docker-container)、[option 3](#option-3-run-as-cloud-run-service)。

3. 以下三種方式擇一啟動。

## (Option 1) Run on-premise without Docker Container

1. 建立 2 支 GCP service account：
- 第一支授予 `Storage Object Viewer`、`Agent Platform User`，下載 JSON key 存到專案內（例如 `./env/person-skill-dashboard.json`），並在 `.env` 把 `AGENT_PLATFORM_USER_CREDENTIALS` 設為此檔路徑。
- 第二支授予 `Storage Object Viewer`，下載 JSON key 存到專案內（例如 `./env/gcs-viewer.json`），並在 `.env` 把 `GOOGLE_APPLICATION_CREDENTIALS` 設為此檔路徑。

2. 解除 `agent_tools/connect_to_google_genai.py` 與 `agent_tools/query_with_vector_search.py` 中「地端測試跑下面區塊」的註解，讓 AI Knowledge Agent 頁面腳本執行時，知道去哪找到step 1 備好的 AGENT_PLATFORM_USER_CREDENTIALS 憑證。

3. 開 2 個終端機，請各別啟動 OneNote review 頁面互動所需的  [Silver service](../task07_silver_service/README.md#option-1-run-on-premise-without-docker-container) 與 [Gold service](../task07_gold_service/README.md#option-1-run-on-premise-without-docker-container)。

    ```bash
    poetry run python -m task07_silver_service.app   # localhost:8002
    poetry run python -m task07_gold_service.app     # localhost:8003
    ```

4. 再開第 3 個終端機，從專案根目錄啟動 dashboard：

    ```bash
    poetry run streamlit run dashboard_ui/app.py
    ```

5. 訪問網址: **http://localhost:8501**。
---
## (Option 2) Run on-premise with Docker Container

1. 建立 2 支 GCP service account：
- 第一支授予 `Storage Object Viewer`、`Agent Platform User`，下載 JSON key 存到專案內（例如 `./env/person-skill-dashboard.json`），並在 `.env` 把 `AGENT_PLATFORM_USER_CREDENTIALS` 設為此檔路徑。
- 第二支授予 `Storage Object Viewer`，下載 JSON key 存到專案內（例如 `./env/gcs-viewer.json`），並在 `.env` 把 `GOOGLE_APPLICATION_CREDENTIALS` 設為此檔路徑。

2. 解除 `agent_tools/connect_to_google_genai.py` 與 `agent_tools/query_with_vector_search.py` 中「地端測試跑下面區塊」的註解，讓 AI Knowledge Agent 頁面腳本執行時，知道去哪找到step 1 備好的 AGENT_PLATFORM_USER_CREDENTIALS 憑證。

3. 確認 Docker Desktop 已安裝且 daemon 執行中。

4. 再次提醒：`.env` 的 `SILVER_ENDPOINT_URL` 與 `GOLD_ENDPOINT_URL` 應按照[前述](#configuration)提示改成 `http://host.docker.internal:port_no/route`，容器之間才連得到。

5. 開一個終端機，依序 build docker image 後同時以背景模式啟動 Silver（port No.: 8002）與 Gold（port No.: 8003）兩個容器服務：

    ```bash
    cd 06_personnel_skill_library

    # Silver Service（容器內 gunicorn 監聽 8080，映射到主機 8002）
    docker build -f docker/Dockerfile.task07_silver_service -t task07-silver-service:latest .
    docker run --rm -d --env-file ./.env -v "$(pwd)/env:/app/env:ro" \
        -p 8002:8080 --name task07-silver-service task07-silver-service:latest

    # Gold（容器內 gunicorn 監聽 8080，映射到主機 8003）
    docker build -f docker/Dockerfile.task07_gold_service -t task07-gold-service:latest .
    docker run --rm -d --env-file ./.env -v "$(pwd)/env:/app/env:ro" \
        -p 8003:8080 --name task07-gold-service task07-gold-service:latest
    ```

6.  build 第三個 docker image 並啟動 dashboard：

    ```bash
    docker build -f docker/Dockerfile.dashboard_ui -t dashboard-ui:latest .
    docker run --rm --env-file ./.env -v "$(pwd)/env:/app/env:ro" \
        -p 8080:8080 --name dashboard-ui dashboard-ui:latest
    ```

7. 訪問網址: **http://localhost:8080**。
---
## (Option 3) Run as Cloud Run Service

> 以下部署方法代表 Dashboard 是**對外的 Cloud Run Service**

1. 按照[task07 silver service README.md 章節 option 3](../task07_silver_service/README.md#option-3-run-as-cloud-run-service) 與 [task07 gold service README.md 章節 option 3](../task07_gold_service/README.md#option-3-run-as-cloud-run-service) 完成 cloud run services 部署，取得兩個 endpoint URL。

2. **建立 1 支 Service Account**：命名為 `person-skill-dashboard`，授予 `Agent Platform User`、`Cloud Run Invoker`、`Storage Object Viewer`、`Secret Manager Secret Accessor` 四個角色。

3. **Secret Manager**：把 `MONGO_ALTAS_URI`、`MONGO_DB_NAME`、`GCP_PROJECT_ID`、`SILVER_ENDPOINT_URL`、`GOLD_ENDPOINT_URL`（及選填的 `ERD_LINK`、各 `ROLE_*`）存為 secrets。

4. 再次提醒：`SILVER_ENDPOINT_URL` 與 `GOLD_ENDPOINT_URL` 應按照[前述](#configuration)提示改填在 step 1 取得的實際 URL。

5. **Build image**：

    ```bash
    docker build --platform=linux/amd64 \
        -f docker/Dockerfile.dashboard_ui \
        -t dashboard-ui:latest .
    ```

    > 建議加上 `--platform=linux/amd64`：Cloud Run 執行環境通常是 linux/amd64，若您在非 amd64 機器（如 Apple Silicon arm64）build image，不指定平台會導致 Cloud Run 無法啟動 container。

6. **Push 到 Artifact Registry**、**建立 Cloud Run Service**、掛載 secrets、指定 `person-skill-dashboard`、開放 public 存取、port 8080、`min-instances: 0`。取得公開 URL 後驗證畫面正常。流程參考 [官方指引](https://docs.cloud.google.com/run/docs/quickstarts/deploy-container?hl=zh-tw)。

    > **若您 fork 本專案分支**：repo 內已備好 GitHub Actions workflow（`.github/workflows/deploy_dashboard_ui.yml`），push 到 `develop` 且對應 path 有變動時，自動 **build image 並 push 到 Artifact Registry**（不含部署——把新 image 部署到 Cloud Run Service 仍需手動，見步驟 6）。要啟用它，需自行在 GCP 申請 Workload Identity Federation。若您不打算 fork，忽略本註即可——上述手動流程已足夠。
