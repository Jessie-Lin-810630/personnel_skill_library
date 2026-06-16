# Purose
Customize and demonstrate a personnel skill dashboard with AI-agent serving as learning assistant.

# Architectures
- To deliver three web pages:
    1. `HOME`: An overview about your personnel skills in two domains (e.g. biotechnoloy + data engineering). For each domain it represents a radar chart containing the proficieny in 5-8 subjects. In the middle layer of page, five KPI cards represent, note nodes in  Obsidian vault, experienced project amount shown on Github, finished problems about SQL on leetcode, finished problems about python on leetcode, learning progress on Udemy.
    To generate two radar charts and five KPI cards, we need to perform at least four ETL processes.
        ```
            資料來源（ETL）                 存儲                               呈現
            ─────────────────────────────────────────────────────────────────────────
            Obsidian vault          →  MongoDB                            
            （本地資料夾掃描）           （筆記 metadata）

            GitHub API              →  MongoDB                             Streamlit
            （REST API 抓取）           (repo metadata& readme abstracts) （plotly 圖表）

            LeetCode&ccClub刷題紀錄   →  MongoDB

            Personal skill          →  MongoDB
            dashbaord (googlesheet)

            Microsoft OneNote       →  本地磁碟（HTML + .md）      
            （Graph API 委派授權）       MongoDB（logs + metadata）
                                       GCS（唯讀存檔）
        ```

    2. `Knowledge Factory`: A graph describes the technique used in this project. Some flowchart of ETL pipeline showing the steps from extracting from data sources, transformining, loading to database, data visualization and final deployment. The number of flowchart depends on the required processes. A block showning three milestones, executing the ETL and frontend web pages in docker containers on premises, deploying web service to GCP cloud run and cloud scheduler, adding Github Actions to perform CI/CD workflow.
        - 專案架構說明 (phase I - On-premise)
            1. 開發ETL task01: 從地端 Obisidan Vault 遞迴搜尋 .md 檔，根據 frontmatter 清洗生成兩份文檔集`obsidian_notes` 與 `obsidian_summary`。[文檔集欄位設定](./doc/branch_etl_pipeline_summary.md#mongodb-collections)。phase I 的 ETL task01 在地端執行。

            2. 開發ETL task02: phase I 的 ETL task02 在地端執行，利用 .env 定義的 token 等資訊來抓取個人 public & private repo、個人參與的 public repo 的 commmit 訊息、commit 頻率、README.md file URL、README.md abstract，經清洗生成兩份文檔集`github_repos` 與 `github_summary`。 

            3. 開發ETL task03: phase I 的 ETL task03 在地端執行，利用 .env 定義的 cookies 等資訊來抓取個人刷題紀錄，經清洗生成三份文檔集`solved_problems_on_ccClub`、`solved_problems_on_leetcode` 與 `ccClub&leetcode_summary`。

            4. 開發ETL task05: phase I 的 ETL task05 在地端執行，利用 .env 定義的 key 等資訊來抓取 google sheet 上的技能雷達資訊，經清洗生成三份文檔集`skill_scores_biotech`、`skill_scores_data_eng` 與 `skill_radar_summary`。

            5. 開發dashboard：phase I 的 dashboard UI 使用 python-streamlit 開發，設計三頁，主頁從 1~4 ETL 存入的文檔集做極輕量聚合計算或簡易查詢，總結個人知識、技能總結。第二頁繪製本網站 (本專案專案架構歷程)。第三頁使用obsidian md files 轉出的 MongoDB Altas 向量化資料庫，串接 AI文字摘要 與 學習地圖生成式 AI 機器人兩種 Agent。phase I 只開發頁1 & 2。

            6. 開發ETL task07: phase I 的 ETL task07 在地端執行，由筆記持有人透過瀏覽器完成委派授權（delegated authentication）後，透過 Microsoft Graph API 抓取 OneNote 頁面為 HTML 檔與圖片，存於地端路徑；再以 Gemini 2.5 Flash Lite 重整 HTML 結構並萃取 tags／alias，輸出附 YAML frontmatter 的 `.md` 檔至同目錄。過程中 API 請求紀錄寫入 MongoDB Altas `onenote_graph_api_logs`，LLM 呼叫紀錄寫入 `gemini_llm_logs`，每頁狀態 upsert 至 `onenote_page_metadata`。

        - 專案架構說明 (phase II - Deploying on GCP Cloud Run Service/Job, Secret Managers, GCS, Artifact Registry and MongoDB Altas)
            1. 部署ETL task01: 從 Obsidian vault 手動上傳、`gsutil rsync` 或是 `git sync` .md files 至 GCS。打包 task01 腳本透過 GitActions 打包成 image，推送到 artifact registry，而後使用 cloud run job 開啟 task01 ETL 容器，容器遞迴搜尋 GCS 的 .md檔，根據 frontmatter 清洗生成兩份文檔集`obsidian_notes` 與 `obsidian_summary`，存入 `MongoDB Altas`。

            2. 部署ETL task02: 打包 task02 腳本透過 GitActions 打包成 image，推送到 artifact registry，而後使用 cloud run job 開啟 task02 ETL 容器，利用 secret managers 定義的 token 等資訊來抓取個人 public & private repo、個人參與的 public repo 的 commmit 訊息、commit 頻率、README.md file URL、README.md abstract，經清洗生成兩份文檔集`github_repos` 與 `github_summary`，存入 `MongoDB Altas`。

            3. 部署ETL task03: 打包 task03 腳本透過 GitActions 打包成 image，推送到 artifact registry，而後使用 cloud run job 開啟 task03 ETL 容器，利用 secret managers 定義的 cookies 等資訊來抓取個人刷題紀錄，經清洗生成三份文檔集`solved_problems_on_ccClub`、`solved_problems_on_leetcode` 與 `ccClub&leetcode_summary`，存入 `MongoDB Altas`。

            4. 部署ETL task05: 打包 task05 腳本透過 GitActions 打包成 image，推送到 artifact registry，而後使用 cloud run job 開啟 task05 ETL 容器，利用 secret managers 定義的 key 等資訊來抓取 google sheet 上的技能雷達資訊，經清洗生成三份文檔集`skill_scores_biotech`、`skill_scores_data_eng` 與 `skill_radar_summary`，存入 `MongoDB Altas`。

            5. 部署streamlit web service: 打包腳本透過 GitActions 打包成 image，推送到 artifact registry，而後使用 cloud run service 開啟無伺服器服務，開放8080端口監聽外部公網，根據進站流量自動水平擴展容器。

            6. ETL task07（地端限定）: 筆記委派授權與否應尊重單位人與人 face-to-face 事前溝通資產管理重要性，實務上應取得資產持有人認同再進行 task07，故減緩將 task07 部署到雲端做腳本自動化、定期排程的計畫，phase II 僅需保證已授權下載完成的筆記檔案有被同步至 GCS，供特定權限人士透過 streamlit web service 唯讀。

        - 專案架構說明 (phase III - Establish Plugin AI agents)
            1. 開發ETL task06: 從地端 Obisidan Vault 遞迴搜尋 .md 檔，將內容資料切塊、embedding 生成文檔集`obsidian_vectors` ， upsert 存入 `MongoDB Altas`。

            2. 在 `MongDB Altas` 建立 文檔集 `chat_history`，記載 AI agent 對話紀錄。

            3. 部署ETL task06: 打包 task06 腳本透過GitActions 打包成 image，推送到 artifact registry，而後使用 cloud run job 開啟 task06 ETL 容器，容器遞迴搜尋 GCS 的 .md檔，將內容資料切塊、embedding 生成文檔集`obsidian_vectors` ， upsert 存入 `MongoDB Altas`。

            4. 串接語意檢索 top-K 相關筆記片段，Gemini 2.5 flash & 2.5 flash lite
                - 傳入：使用者問題 + 檢索到的筆記片段
                - 以streamlit輸出：摘要回答 / 學習地圖

            5. 更新dashboard：設計第三頁，串接 AI Agent。

        - 專案架構說明 (phase IV - 加入告警機制)
            1. 設計Cloud Run Job 執行 ETL calling API 過程中，如果遇回應 403或非200，捕捉例外、發送通知（Email 或 Pub/Sub）

            2. 例外原因判斷後排除問題。

    3. `AI knowledge agent`: A session to search for the abstract or text from your library in the vault of Obsidian. A suggesetion of learing map generated on basis of mindset that your are used. A session to automatically record the history between you and AI agent.
    Obsidian .md 檔案
        ```
        ↓ Python 讀取 + 切塊 chunking
        向量化（Embedding）
            ↓ Google text-embedding-004（免費額度高）
        向量資料庫 MongoDB Atlas Vector Search
            ↓ 語意檢索 top-K 相關筆記片段
        Gemini 2.5 flash lite + Gemini 2.5 flash LLM
            ↓ 傳入：使用者問題分類 + 檢索到的筆記片段
            ↓ 輸出：摘要回答 / 學習地圖
        Streamlit Chat UI
            └─ st.chat_message + st.chat_input
        ```
# Planned technique stacks:
| layer           	| tool                                                               	|
|-----------------	|--------------------------------------------------------------------	|
| frontend        	| python-streamlet, figma                                            	|
| backend         	| python, python-pymongo                                             	|
| database        	| MongoDB Atlas（Phase II 起）                                       	|
| Container       	| docker                                                             	|
| cluoud service  	| GCP：Cloud Run Service/Job、GCS、Secret Manager、Artifact Registry 	|
| CI/CD           	| GitHub Actions                                                     	|
| Tool Management 	| pyenv + poetry                                                     	|
| AI layer        	| Chat Agent using models, Gemini 2.5 flash & Gemni 2.5 flash-lite      |

# Planned branches:
    1. main     # release the branch2`develop` once it pass the tests.
        - 週期：phase II~
    2. develop  # use Github Actions to deploy to UAT once the branches 3 `feature/*` completed.
        - 週期：phase I~III
        - 整合所有 features
    3. feature/etl-pipeline
        - 週期：phase I~IV
    4. feature/dashboard-ui
        - 週期：phase I~III
    5. feature/ai-agent
        - 週期：phase III~
    6. feature/alert-monitoring  
        - 週期：Phase IV~

# Working Items
| Week | Task description                                    |
|------|-----------------------------------------------------|
| 1-2  | 建 Docker Compose 環境，寫 Obsidian/GitHub ETL 腳本   |
| 3-4  | 完成第一層 Streamlit 頁面與圖表                        |
| 5    | 完成第二層架構圖與進度看板                              |
| 5-6  | Docker 打包，第一次部署 MongoDB Altas 與 GCP Cloud Run |
| 6-8  | 建立向量索引，串接 Chat Agent + NL2SQL，完成第三層       |
| 9    | 第二次部署 GCP Cloud Run                             |