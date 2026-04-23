# Purose
Customize and demonstrate a personnel skill dashboard with AI-agent serving as learning assistant.

# Architectures
- To deliver three web pages:
    1. `HOME`: An overview about your personnel skills in two domains (e.g. biotechnoloy + data engineering). For each domain it represents a radar chart containing the proficieny in 5-8 subjects. In the middle layer of page, five KPI cards represent, note nodes in  Obsidian vault, experienced project amount shown on Github, finished problems about SQL on leetcode, finished problems about python on leetcode, learning progress on Udemy.
    To generate two radar charts and five KPI cards, we need to perform at least four ETL processes.
    ```
        資料來源（ETL）          存儲             呈現
        ─────────────────────────────────────────────
        Obsidian vault     →  MongoDB        ↘
        （本地資料夾掃描）      （筆記 metadata）
        GitHub API         →  MySQL          → Streamlit
        （REST API 抓取）       （進度數字）     （plotly 圖表）
        LeetCode（手動輸入） →  MySQL
        Udemy（手動輸入）    →  MySQL
    ```
    2. `Knowledge Factory`: A graph describes the technique used in this project. Some flowchart of ETL pipeline showing the steps from extracting from data sources, transformining, loading to database, data visualization and final deployment. The number of flowchart depends on the required processes. A block showning three milestones, executing the ETL and frontend web pages in docker containers on premises, deploying web service to GCP cloud run and cloud scheduler, adding Github Actions to perform CI/CD workflow.
    ```
    部署架構圖：

    本地開發環境
    └─ Docker Compose
        ├─ streamlit app (port 8501)
        ├─ flask api    (port 5000)
        ├─ mongodb      (port 27017)
        └─ mysql        (port 3306)
            ↓ docker push
    GCP Cloud Run
    └─ Container Registry 存放 image
        ├─ Cloud Scheduler（定時觸發 ETL 腳本）
        └─ Cloud Storage（存放靜態資源）
    ```
    3. `AI knowledge agent`: A session to search for the abstract or text from your library in the vault of Obsidian. A suggesetion of learing map generated on basis of mindset that your are used. A session to automatically record the history between you and AI agent.
    ```
    Obsidian .md 檔案
      ↓ Python 讀取 + 切塊 chunking
    向量化（Embedding）
        ↓ Google text-embedding-004（免費額度高）
    向量資料庫 MongoDB Atlas Vector Search
        ↓ 語意檢索 top-K 相關筆記片段
    Claude API（claude-sonnet-4）
        ↓ 傳入：使用者問題 + 檢索到的筆記片段
        ↓ 輸出：摘要回答 / 學習地圖
    Streamlit Chat UI
        └─ st.chat_message + st.chat_input
    ```
- Planned technique stacks:
    1. Frontend:  Streamlit
    2. Backend:   Python + Flask API
    3. Database:  MongoDB（存筆記metadata） + MySQL（結構化進度數據）
    4. Cloud:     GCP（Cloud Run 部署容器）
    5. Container: Docker
    6. AI Layer:  Claude API（第三層 agent）
    7. Workflow: Github Actions

- Planned branches:
    1. main     # release the branch2`develop` once it pass the tests.
    2. develop  # use Github Actions to deploy to UAT once the branches 3 `feature/*` completed.
    3. feature/etl-pipeline
    4. feature/dashboard-ui
    5. feature/knowledge-factory
    6. feature/ai-agent

# Working Items
    | Week | Task description                                    |
    |------|-----------------------------------------------------|
    | 1-2  | 建 Docker Compose 環境，寫 Obsidian/GitHub ETL 腳本   |
    | 3-4  | 完成第一層 Streamlit 頁面與圖表                        |
    | 5    | 完成第二層架構圖與進度看板                              |
    | 6-8  | 建立向量索引，串接 Claude API，完成第三層                |
    | 9    | Docker 打包，部署 GCP Cloud Run                      |