# Feature Branch: `dashboard_ui` — Streamlit Dashboard UI 開發成果摘要

> **開發目標**：將 ETL pipeline 寫入 MongoDB 的成果，整合成個人技能儀表板。主頁展示 Jessie Lin 的生技製藥 x 資料工程雙棲能力、技能雷達、知識庫 KPI、刷題統計與 GitHub 專案；`Knowledge Factory` 頁則展示整體專案架構、技術堆疊、ETL pipeline 與雲端部署演進藍圖。

> **完成狀態**：已完成 Streamlit 多頁式 Dashboard 雛形，並已串接 MongoDB 作為資料來源。**`尚須繼續開發串接 AI agent 問答機器人`**

> **執行環境**：macOS / VS Code / pyenv (Python 3.14) / Poetry / Streamlit / MongoDB localhost / Google Chrome Browser

---

## 專案資料夾結構
    ```text
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
        │    └── knowledge_factory.py           # 頁面2 - 講述本專案架構(技術堆疊、ETL pipeline、GCP 雲端架構)
        └── utils/
                ├── interact_with_mongodb.py    # 與 MongoDB 連線，透過各 collection 查詢函式取得文檔資料
                ├── precomputing.py             # Dashboard 顯示前的資料格式化、delta 計算、題型比例轉換
                └── ui_elements.py              # 共用 UI 元件：sidebar、雷達圖、任務明細表、色票設定，供 app.py 與 pages/ 使用
    ```

## streamlit page 瀏覽方式
    1. Start runing web service. 
    ```bash
        poetry run streamlit run dashboard_ui/app.py
    ```
    2. Stop the service.
        - Exit the web browser.
        - Go to terminal, press `ctrl + C` to exit

## Page 01 — `app.py` 主儀表板

### 主頁資料流

```text
MongoDB collections
    ↓
utils/interact_with_mongodb.py
    ↓
utils/precomputing.py
    ↓
app.py
    ↓
Plotly charts / Streamlit metrics / dataframe / HTML cards
```

### 畫面區塊

| 區塊 | 功能 |
|------|------|
| Hero 區 | 顯示 Jessie Lin 個人定位、生技製藥 x 資料工程主題、GitHub / LinkedIn 連結 |
| 技能雷達 | 生技製藥技能雷達 + 資料工程技能雷達 |
| 雷達軸任務明細 | 點選雷達圖或下拉選單後，顯示該軸向對應的「經手任務」 |
| KPI 總覽 | Obsidian 知識節點、GitHub 專案數、LeetCode SQL、LeetCode Python |
| Obsidian 主題分佈 | 以橫向 bar chart 呈現知識文檔 topic 統計 |
| 刷題三相 Donut | ccClub Python / LeetCode SQL / LeetCode Python 題數分佈 |
| 題目特徵明細 | 可用 selectbox + radio 切換平台與 Top 區間，使用 dataframe + progress column 呈現 |
| GitHub 最近專案 | 橫向滑動 repo cards，顯示 repo name、language、commits、last push、README link |
| Footer | 資料來源與社群連結 |

### 查詢之 MongoDB Collections

```text
skill_radar_summary
skill_scores_biotech
skill_scores_data_eng
obsidian_summary
github_summary
github_repos
ccClub&leetcode_summary
```

### 視覺化元件

| 元件 | 套件 / API |
|------|------------|
| 雷達圖 | Plotly `go.Scatterpolar` |
| Obsidian topic bar chart | Plotly `go.Bar` |
| 刷題 donut chart | Plotly `go.Pie` |
| KPI 卡片 | Streamlit `st.metric` |
| 題目特徵表 | Streamlit `st.dataframe` + `ProgressColumn` |
| GitHub 專案卡片 | HTML + CSS inline rendering |

---
## Page 02 — `pages/knowledge_factory.py`

### 資料流
No connected with MongoDB or external dataset. Only streamtlit for architecture demonstration.

### 畫面區塊

| 區塊 | 功能 |
|------|------|
| Hero 區 | 顯示 Knowledge Factory 主題與 GitHub / LinkedIn 連結 |
| Tech Stack | 以卡片呈現 Frontend、Backend、Database、Container、Cloud、CI/CD、AI Layer、Tool Management |
| ETL Pipeline 總覽 | 展示 5 條資料管道：task01、task02、task03、task05、task06 |
| Four Milestones | 以 radio 切換 Phase I ~ IV，呈現專案演進時程 |
| GCP 雲端架構 | 顯示 CI/CD、Cloud Run Jobs、Cloud Run Service、GCS、Secret Manager、MongoDB Atlas |
| Footer | LinkedIn 聯絡資訊 |

---
## .env 需求

```text
MONGO_URI=
MONGO_DB_NAME=
```

---

## 待整理事項
- scripts 尚有少量 import 未實際調用函式，可清理，包含：`UpdateOne`、`Collection`、`plotly.express as px`
