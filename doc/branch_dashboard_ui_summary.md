# Feature Branch: `feature/dashboard-ui` — 第二層開發執行成果摘要

> **開發目標**：將"個人技能雷達與追蹤儀表板"、"本專案的從ETL管道邏輯建構至部署到雲端服務的流程與專案架構"、"知識摘要問答機器人"分別編寫成三個網頁入口。

> **開發狀態**：更新至 2026-05-13，持續開發中

> **執行環境**：macOS / VS Code / pyenv (Python 3.14) / Poetry / MongoDB localhost / Port No. 8501 for streamlit / Safari or Google Chrome Browser

---
## 專案資料夾結構

    ```
    feature/dashboard_ui/
    ├── .env                                    # 金鑰集中管理
    ├── poetry.lock                             # from branch feature/etl-pipeline, add streamlit&plotly
    ├── pyproject.toml                          # from branch feature/etl-pipeline, add streamlit&plotly
    ├── task01_obsidian_etl/                    # from branch feature/etl-pipeline
    ├── task02_github_restapi_etl/              # from branch feature/etl-pipeline
    ├── task03_leetcode_ccClub_etl/             # from branch feature/etl-pipeline
    ├── task05_googlesheet_skill_etl/           # from branch feature/etl-pipeline
    ├── tests/                                  # from branch feature/etl-pipeline
    │
    ├── .streamlit/  
    │        └──  config.toml                   # streamlit configuration                       
    └── dashboard_ui/
        ├── app.py                              # 網頁入口，主頁面
        ├── pages/
        │    └── knowledge_factory.py           # 頁面2 - 講述本專案架構
        └── utils/
                ├── interact_with_mongodb.py    # 與 MongoDB 連線，取得文檔
                ├── precomputing.py             # 定義取得文檔後的輕量計算，作為前端製圖的準備
                └── ui_elements.py              # 定義網頁UI元件，供 app.py 與 pages/ 使用
    ```

## streamlit page 瀏覽方式
    1. Start runing web service. 
    ```bash
        poetry run streamlit run dashboard_ui/app.py
    ```
    2. Stop the service.
        - Exit the web browser.
        - Go to terminal, press `ctrl + C` to exit