# Feature Branch: `dashboard_ui` — Streamlit Dashboard UI 開發成果摘要

> **開發目標**：把各 ETL task 寫進 MongoDB Atlas／GCS 的成果，整合成一套 Streamlit 多頁式個人技能看板。除了對外展示技能雷達與專案架構，另加入三塊「資料產品」頁面：OneNote 人工審查閘門（human-in-the-loop）、攝取品質監控、RAG 檢索品質監控，以及 Phase III 的 AI 知識 Agent 問答介面。

> **完成狀態**：六頁全數完成並可運作（HOME、Knowledge Factory、OneNote Review、Ingestion Quality、Retrieval Quality、AI Knowledge Agent）。AI Agent 已串通 intent router → RAG／planning 兩條鏈路並落地 `chat_history`。登入機制目前為 `.env` 帳密的 demo gate，Google OAuth（`st.login()`）仍是 TODO（見 `pages/ai_knowledge_agent.py` 檔頭註解）。

> **執行環境**：macOS / VS Code / pyenv (Python 3.14) / Poetry / Streamlit / MongoDB Atlas / GCS / Vertex AI (Agent Platform) / Cohere Rerank API。三種啟動方式（地端裸跑、地端 Docker、Cloud Run Service）詳見 [`dashboard_ui/README.md`](../dashboard_ui/README.md#get-started)。

> **資料存儲**：
> - **MongoDB Atlas**（唯讀為主）：`skill_radar_summary`、`skill_scores_biotech`、`skill_scores_data_eng`、`notes_summary`、`github_summary`、`github_repos`、`ccClub&leetcode_summary`、`onenote_note_metadata`、`multimodal_llm_enrichment_logs`、`note_vectors_multimodal`、`obsidian_note_metadata`、`chat_history`（唯一由 dashboard 寫入的表，存 agent 的對話紀錄）。
> - **GCS**：`personal-vaults`（Knowledge Factory 的 9 張 DAG SVG）、`onenote-vaults`（OneNote 審查頁的 bronze `.html`／silver `.md`／`_images/`）。
> - **外部服務**：task07 Silver 端點（8002）、task07 Gold 端點（8003）；dashboard 只以 HTTP POST 呼叫，不 import 任何 `task07_*` 套件。

---

## 專案資料夾結構

```text
feature/dashboard-ui/
├── .env                                    # 金鑰集中管理（人工維護，不進版控）
├── .streamlit/config.toml                  # 關閉預設 sidebar nav，改用自訂側欄
├── docker/Dockerfile.dashboard_ui          # Cloud Run Service 用 image
├── task01_*, task02_*, ... task08_*/       # from branch feature/etl-pipeline、feature/html-to-markdown
│
└── dashboard_ui/
    ├── README.md                           # dashboard 專用執行指引（環境變數、三種啟動方式）
    ├── app.py                              # Page 01 — HOME，兼 Streamlit 進入點
    ├── pages/
    │   ├── knowledge_factory.py            # Page 02 — 專案架構（Tech Stack + Data Lineage）
    │   ├── onenote_review.py               # Page 03 — OneNote 多版本人工審查（登入）
    │   ├── ingestion_data_quality.py       # Page 04 — 攝取品質監控
    │   ├── retrieval_search_quality.py     # Page 05 — 檢索品質監控
    │   └── ai_knowledge_agent.py           # Page 06 — AI 知識 Agent 對話（登入）
    ├── agents/                             # Agent 本體
    │   ├── intent_router_agent.py          # 意圖分流：R1 關鍵字快篩 → R2 LLM 分類
    │   ├── rag_agent.py                    # rewrite → search → rerank → generate
    │   └── planning_agent.py               # 學習路徑規劃（generate / refine）
    ├── agent_tools/                        # Agent 工具層
    │   ├── query_rewriter.py               # 查詢改寫 + tag 推薦（含 alias→tag 對照表載入）
    │   ├── query_with_vector_search.py     # $vectorSearch 向量檢索（含 query embedding）
    │   ├── reranker.py                     # Cohere rerank-v3.5 重排序
    │   ├── chat_history.py                 # chat_history 讀寫
    │   ├── agent_helpers.py                # context 組裝、來源清單、歷史脈絡訊息
    │   ├── connect_to_google_genai.py      # 建立 Vertex AI genai client
    │   └── types_and_constants.py          # collection 名、model 名、top-K、型別別名
    ├── utils/
    │   ├── interact_with_mongodb.py        # MongoDB 連線單例 + 各頁查詢封裝
    │   ├── precomputing.py                 # 顯示前的格式化、delta 計算、百分比轉題數
    │   ├── ui_elements.py                  # color_map、側欄、雷達圖、任務表格
    │   ├── tech_stack_diagram.py           # 13 層 Tech Stack 卡片（inline style + base64 SVG）
    │   └── gcs_reader.py                   # GCS 讀取（read_text / read_*_by_uri / base64 圖片）
    └── images/
        ├── task0*_link.svg                 # DAG 圖備份（線上版從 GCS 讀取）
        └── mermaid_codes/*.md              # 各 DAG 的 mermaid 原始碼
```

側欄由 `utils/ui_elements.render_side_bar()` 統一渲染（`.streamlit/config.toml` 關閉 `showSidebarNavigation` 後改以 `st.sidebar.page_link` 自訂），六頁共用，分成「主頁」與「My artifacts」兩區。

### 瀏覽方式

```bash
# 1. 先啟動 OneNote 審查頁依賴的兩個端點（各開一個終端機）
poetry run python -m task07_silver_service.app   # localhost:8002
poetry run python -m task07_gold_service.app     # localhost:8003

# 2. 從專案根目錄啟動 dashboard
poetry run streamlit run dashboard_ui/app.py     # localhost:8501
```

停止服務：關閉瀏覽器分頁後，回終端機按 `ctrl + C`。

---

## Page 01 — `app.py` HOME 個人技能總覽

### 畫面區塊

| 區塊 | 功能 |
|------|------|
| Hero 區 | 個人定位敘事（生技製藥 → 資料工程）、GitHub／LinkedIn 連結 |
| Level 定義 | 以色票 badge 說明 Lv1–Lv5 的能力判定標準，與右側兩張雷達圖並排 |
| 技能雷達（雙圖） | 生技製藥雷達（TEAL）與資料工程雷達（PURPLE），皆開啟 `on_select="rerun"` 可點選軸向 |
| 雷達軸任務明細 | 點雷達圖上的軸或用下拉選單，列出該軸向對應的經手任務表格 |
| GitHub 最近專案 | 橫向捲動的 repo 卡片，顯示 repo 名、語言、commits、last push、README 連結 |
| KPI 總覽 | 四張卡片：知識庫節點、GitHub 專案數、LeetCode SQL、LeetCode Python，各附環比 delta 與最近更新日 |
| Obsidian 主題分佈 | 橫向 bar chart，最大值以 PINK 標示、其餘 PURPLE |
| 刷題三相 donut | ccClub Python／LeetCode SQL／LeetCode Python 題數佔比，中心標註總題數 |
| 題目特徵明細 | selectbox 切平台 + radio 切 Top 區間（Top 1-5／Top 5-10／All），以進度條欄位呈現題數與佔比 |
| Footer | 資料來源與社群連結 |

補充說明：

- 頁面在 module 層一次跑完所有查詢，再由上而下組裝畫面。`mongo_utils.get_db_atlas()` 內部是 module-level 單例，client 只建立一次、跨頁共用連線池。
- `get_radar_summary_df(db, "skill_radar_summary")` 回傳含「雷達圖名稱／雷達軸／level」的 DataFrame，再以字串包含「生技」「資料工程」拆成兩份；軸標籤逐一過 `_format_radar_label()` 換行美化，`_latest_date_from_df()` 取出最近更新日。
- `get_a_radar_detail(db, "skill_scores_biotech" | "skill_scores_data_eng")` 的明細 DataFrame 交給 `_radar_tasks_from_df()`，轉成 `{軸向: [任務...]}` 的 dict，同時餵給 `make_radar()`（做 hover 文字）與 `render_task_selectbox()` / `render_task_table()`（做下方明細表）。
- `render_task_selectbox(labels, tasks_dict, chart_event, key_prefix)` 接收 `st.plotly_chart` 回傳的 selection event，優先採用圖上點選的軸、否則採下拉選單值，輸出 `(selected_axis, tasks_dict)` 給 `render_task_table()`。
- KPI 三組數值分別來自 `get_obsidian_kpi()`（回傳 total／delta／by_topic／snapshot_date 四元組）、`get_github_kpi()`、`get_problem_kpi_donut()`；delta 字串統一由 `_format_delta(value, suffix)` 加工。
- 題目特徵由 `get_problem_features()` 取百分比後，經 `_percent_to_counts(percent_by_topic, total, include=/exclude=)` 換算成題數；LeetCode SQL 與 Python 靠 `include={"Database"}` / `exclude={"Database"}` 從同一份百分比拆開。

### 此頁面需查詢之 MongoDB collections

```text
skill_radar_summary
skill_scores_biotech
skill_scores_data_eng
notes_summary
github_summary
github_repos
ccClub&leetcode_summary
```

### 視覺化元件

| 元件 | 套件／API |
|------|-----------|
| 技能雷達（可點選） | Plotly `go.Scatterpolar`（封裝於 `ui_elements.make_radar`） |
| Obsidian 主題分佈 | Plotly `go.Bar`（horizontal） |
| 刷題三相 donut | Plotly `go.Pie`（`hole=0.55` + 中心 annotation） |
| KPI 卡片 | Streamlit `st.metric` + 自訂 CSS 底色 |
| 題目特徵表 | Streamlit `st.dataframe` + `st.column_config.ProgressColumn` / `NumberColumn` |
| GitHub 專案卡片 | 原生 HTML + inline CSS（`st.markdown(unsafe_allow_html=True)`，`overflow-x:auto` 做橫向捲動） |
| Hero／Footer | 原生 HTML + CSS linear-gradient |

### 依賴的環境變數（.env）

```text
MONGO_ALTAS_URI
MONGO_DB_NAME
```

---

## Page 02 — `pages/knowledge_factory.py` Chasing Great Data Engineering

### 畫面區塊

| 區塊 | 功能 |
|------|------|
| Hero 區 | 頁面主題與 GitHub／LinkedIn 連結 |
| Tech Stack Overview | 13 層技術堆疊卡片，每層列出所用技術 pill（含圖示） |
| DAGs for Data Lineage | 9 個 tab 切換 9 條 pipeline 的 DAG 圖（task01／02／03／05／06／07 Bronze・Silver・Gold／08），每 tab 附 ERD 外部連結 |
| Footer | 資料來源與社群連結 |

補充說明：

- `render_tech_stack_diagram()` 不接參數，回傳一整段自足的 HTML 字串（純 inline style + base64 內嵌 SVG 圖示），由 `st.html()` 直接渲染；不依賴任何外部 CSS／CDN，因此在 Cloud Run 上也能正常顯示。
- `_load_dag_svg(fname)` 以 `@st.cache_data(ttl=3600)` 包住 `gcs_reader.read_text("personal-vaults", fname)`，回傳 SVG 文字。讀取失敗時刻意拋 `FileNotFoundError` 而非回空字串——`st.cache_data` 不快取拋例外的呼叫，故失敗不會被鎖進快取，下次 rerun 會自動重試；頁面端接住例外後顯示 `Image Not Found`。
- 此頁不查 MongoDB，唯一的外部依賴是 GCS。

### 此頁面需查詢之 MongoDB collections

無（此頁不連 MongoDB）。

### 視覺化元件

| 元件 | 套件／API |
|------|-----------|
| Tech Stack 13 層卡片 | 自製 HTML／CSS 產生器 `utils/tech_stack_diagram.py` + `st.html` |
| DAG 流程圖 | mermaid 產出的 SVG 先存在 GCS，線上版由 GCS 讀取後以 `st.container(...).image()` 呈現 （mermaid 原始碼則存 `根目錄/dashboard_ui/images/mermaid_codes/`，此檔案不進 git 版控）|
| 版面 | Streamlit `st.tabs`、`st.container(width=, height=)` |

### 依賴的環境變數（.env）

```text
GOOGLE_APPLICATION_CREDENTIALS   # GCS 讀取 SVG（地端執行時需指定 service account JSON）
ERD_LINK                         # 選填；Entity-relationship diagram 外部連結，未設定時 tab 內連結為空
```

---

## Page 03 — `pages/onenote_review.py` OneNote 多版本審查系統

### 畫面區塊

| 區塊 | 功能 |
|------|------|
| 登入前 Hero + 引言 | 說明「為何 OneNote HTML 不適合直接進知識庫」與 medallion 三層的角色定位 |
| 登入前 三原則卡片 | 準確性 Accuracy／可靠性 Reliability／隱私與資安 Privacy 三張評估面向提示 |
| 登入表單 | 帳密比對 `.env` 的四組角色（ML/DL Engineer、Note Owner、Dept. Senior Specialist、Guest），成功後寫入 `session_state.authenticated` / `role` |
| 登入後 Hero | 四步驟操作指引 + 重新生成次數上限提醒；右上角顯示目前角色與登出鈕 |
| 三層下拉選單 | 筆記本 → 章節 → 頁面，逐層過濾，各層標題附待審數量 |
| 版本圓鈕 | 同一 `page_id` 的多個 `dt=` 版本依 `html_downloaded_at` 由新到舊排列，標示該版是否已生成過 enriched md |
| 左右對照區 | 左：bronze 原始 OneNote HTML；右：silver LLM 擴寫後 markdown。兩側都在白底 iframe 內渲染 |
| 審查操作按鈕 | 重試生成（Regenerate）／核可（Approve）／退件（Reject） |

補充說明：

- `_load_versions()` 以 `@st.cache_data(ttl=60)` 包住 `get_onenote_versioned_pages(db)`；後者對 `onenote_note_metadata` 跑 aggregation，依 `page_id` 分組並用 window function 算出 `lastArchivedAt`，濾掉已被歸檔版本蓋過（overwritten）與 rejected 的版本，只留「目前仍可審閱」的版本清單。
- Guest 角色在載入清單後立即被過濾，只看得到 `GUEST_ALLOWED_NOTEBOOK` / `GUEST_ALLOWED_SECTION` 指定的範圍；其 approve／reject 只呈現成功的表象（寫入 `session_state.guest_reviewed` 並跳 toast），完全不呼叫 Gold 端點、後端不做任何寫入。
- **on-demand 生成**：當選中版本的 `enriched_md_path` 為 null、且該版未歸檔、且本 session 尚未嘗試過，頁面會自動呼叫 `_trigger("on_demand")`。`_call_silver(trigger)` 先以 `google.oauth2.id_token.fetch_id_token()` 取 ID token，再 POST `{"page_id", "dt", "trigger"}` 到 `SILVER_ENDPOINT_URL`（timeout 180s），回傳 `(result_dict, error_msg)`；`_trigger()` 依結果分流處理逾時、連線失敗、`circuit_open`（LLM 服務級斷路器）、quota 超限等狀況，成功則 `_load_versions.clear()` + `st.rerun()` 重載。
- **Gold 歸檔**：`_call_gold(action)` 以同樣的 ID token 方式 POST `{"page_id", "dt", "role", "action"}` 到 `GOLD_ENDPOINT_URL`，`action` 為 `approved` / `rejected`，成功後清快取重載。
- **渲染細節**：`_replace_images_in_html()` / `_replace_images_in_md()` 以正則抓 `_images/xxx` 相對路徑，逐張換成 `gcs_reader.read_image_base64_by_uri()` 回傳的 data URI；`_flatten_onenote_html()` 另外取出 `<body>` 內層並移除 OneNote 的 `position:absolute`、固定 `left/top/width`，讓內容回到正常文件流、白底區塊高度才穩定。markdown 端以 `markdown` 套件轉 HTML（啟用 `fenced_code`、`tables`、`nl2br`）。
- 按鈕禁用條件：該版尚未產出 md、或該版已歸檔（唯讀）、或 Guest 已在本 session 操作過。

### 此頁面需查詢之 MongoDB collections

```text
onenote_note_metadata    # 唯讀；寫入由 Silver/Gold 端點負責
```

### 視覺化元件

| 元件 | 套件／API |
|------|-----------|
| 原始筆記／擴寫版對照 | `st.iframe`（自訂白底 `_WHITE_FRAME` HTML 模板） |
| Markdown → HTML | `markdown` 套件（`md_lib.markdown`） |
| 圖片內嵌 | base64 data URI（`utils/gcs_reader.read_image_base64_by_uri`） |
| 版本切換 / 選頁 | Streamlit `st.radio`、`st.selectbox` |
| 狀態回饋 | `st.spinner`、`st.toast`、`st.success` / `st.warning` / `st.error` |
| 卡片與 Hero | 原生 HTML + inline CSS |

此頁無圖表，未使用 plotly。

### 依賴的環境變數（.env）

```text
MONGO_ALTAS_URI
MONGO_DB_NAME
SILVER_ENDPOINT_URL                              # 地端裸跑預設 http://localhost:8002/enrich
GOLD_ENDPOINT_URL                                # 地端裸跑預設 http://localhost:8003/archive
GOOGLE_APPLICATION_CREDENTIALS                   # 讀 GCS 上的 html / md / 圖片
ROLE_OWNER_USERNAME / ROLE_OWNER_PASSWORD        # 必填（其餘角色選填）
ROLE_ML_USERNAME / ROLE_ML_PASSWORD
ROLE_SENIOR_USERNAME / ROLE_SENIOR_PASSWORD
ROLE_GUEST_USERNAME / ROLE_GUEST_PASSWORD
```

> 容器化執行時 `SILVER_ENDPOINT_URL` / `GOLD_ENDPOINT_URL` 需改成 `http://host.docker.internal:<port>/<route>`，雲端則填實際部署 URL。

---

## Page 04 — `pages/ingestion_data_quality.py` 攝取品質監控

### 畫面區塊

| 區塊 | 功能 |
|------|------|
| Hero 區 | 標題與最新快照日期 |
| KPI 四卡 | Total／Archived／Rejected／Embedded documents，各附「vs. last week」環比 delta 與 help 說明 |
| 圖表 1-左 生命週期漏斗 | Total → Archived → Embedded 三層漏斗，另以紅色箭頭 annotation 標出 rejected 數 |
| 圖表 1-右 附件完整度 | 依 `(status, embedded_status)` 分三類，堆疊呈現「失效 N 張附件」的筆記篇數 |
| 圖表 2 標籤分歧圖 | archived（綠，右）vs rejected（紅，左）的 tag 分佈，左右刻度對稱；slider 控制顯示前 N 名，並排兩張（分別依 archived / rejected 高頻排序）|
| 圖表 4 token 累計 | 雙軸折線：累計 total tokens（左軸）× cache hit rate %（右軸），上方另有三張 metric |
| 圖表 4 展開明細 | 每日 input／output token 堆疊柱 + latency p50 折線（雙軸） |
| 解讀提示 | 每張圖下方 `st.expander` 說明如何判讀異常 |

補充說明：

- 三支資料載入函式都以 `@st.cache_data(ttl=600)` 包住：`_load_notes_snapshots()`（`get_notes_summary_snapshots(db)`，取最新兩筆快照）、`_load_enrichment_logs()`（`get_enrichment_logs(db)` 回 DataFrame）、`_load_attachment_dismatch()`（`get_onenote_attachment_dismatch(db)`）。若沒有任何快照則 `st.warning` + `st.stop()`。
- `_delta(field)` 以最新快照減前一筆快照算環比；只有一筆快照時回 `None`，KPI 不顯示箭頭。
- 附件遺失圖以 `CAT_MAP` 把 `(status, embedded_status)` 映射成三個 x 軸類別（archived 未embed／archived 已embed／rejected），再用 `collections.Counter` 累計每個「失效張數」對應的筆記篇數；失效張數越多配色越偏警示（藍→紫→橘→紅）。
- `_build_tag_diverging_fig(display_tags)` 把 rejected 側的值取負數畫在左邊、archived 畫在右邊，並自行計算對稱的 `tickvals` / `ticktext`（顯示絕對值），高度隨 tag 數量動態調整。
- `_nice_ceiling(value, unit)` 搭配 `Y_TICKS=5`，讓雙軸圖左右兩軸的刻度線數量一致、視覺上等高對齊。

### 此頁面需查詢之 MongoDB collections

```text
notes_summary                      # KPI 四卡、生命週期漏斗、tag 分歧圖
onenote_note_metadata              # 附件遺失量堆疊圖
multimodal_llm_enrichment_logs     # token 累計、cache hit rate、latency
```

### 視覺化元件

| 元件 | 套件／API |
|------|-----------|
| 生命週期漏斗 | Plotly `go.Funnel` + `add_annotation` |
| 附件遺失量 | Plotly `go.Bar`（`barmode="stack"`） |
| 標籤分歧圖 | Plotly `go.Bar`（horizontal，`barmode="relative"`） |
| token 雙軸圖 | `plotly.subplots.make_subplots(specs=[[{"secondary_y": True}]])` + `go.Scatter` |
| 每日 token 明細 | 同上，`go.Bar`（stack）+ `go.Scatter` 混合雙軸 |
| KPI 卡片 | `st.metric`（`delta_description` / `delta_arrow` / `help`）+ 自訂 CSS |
| 互動控制 | `st.slider`、`st.expander` |

### 依賴的環境變數（.env）

```text
MONGO_ALTAS_URI
MONGO_DB_NAME
```

---

## Page 05 — `pages/retrieval_search_quality.py` 檢索品質監控

### 畫面區塊

| 區塊 | 功能 |
|------|------|
| Hero 區 | 標題與最近一筆 RAG 對話日期 |
| 圖表 6 散佈圖 | Cosine similarity × rerank score，依規則分成常態／Sim 高 Rerank 低（紅）／Sim 低 Rerank 高（橘）三類，附四象限虛線 |
| 散佈圖 KPI | 三張 metric 顯示各類 chunk 數量與其代表的診斷意義 |
| 圖表 9-左 檢索輪數 | 每個 session 的 user 訊息數分佈長條圖（≤3 藍、≤5 橘、>5 紅），下方顯示平均輪數；>3 輪跳警告 |
| 圖表 9-右 冷熱資料 | 文件被檢索次數 treemap，依次數分「🔥熱門／🌤中等／❄️冷門／🧊凍得邦邦硬」四層 |
| 冷資料清單 | expander 內以表格列出檢索次數 ≤2 的文件、距上次檢索天數 |
| 圖表 10 健康度 | 四項代理指標 metric（附 🟢🟡🔴 燈號）＋ 正規化後的四軸雷達圖，疊一條 0.7 健康基準虛線 |
| 判定標準／解讀提示 | expander 內以表格列出各指標的健康門檻與計算方式 |

補充說明：

- 四支載入函式皆以 `@st.cache_data(ttl=300)` 包住，全部讀 `chat_history`：`get_rag_retrieved_chunks()`（展開 `metadata.retrieved_chunks`，每個 chunk 一列）、`get_rag_session_rounds()`（每 session 的 `role=user` 訊息數）、`get_rag_file_retrieval_counts()`（各文件被檢索次數與 `days_since`）、`get_rag_satisfaction_proxy(db, truncate_limit=2000)`（rerank top-1 中位數、平均文件數、截斷率、最近日期）。
- `avg_rounds` 只計算一次，同時餵給輪數 histogram 與健康度雷達；算完後補回 `satisfaction["avg_rounds"]`，讓四項指標從同一個 dict 取值。
- `classify_outlier(row)` 以固定門檻（score>0.80 且 rerank<0.20／score<0.60 且 rerank>0.60）判離群類別，結果寫回 DataFrame 供 `px.scatter` 上色。
- `health_icon(val, good, bad, higher_is_better)` 回傳燈號 emoji，`higher_is_better=False` 時方向反轉；`normalize(val, min_v, max_v, invert)` 把各指標壓到 0–1 並統一成「越高越好」，再組成雷達圖的 r 值（首尾相接以閉合多邊形）。
- 頁面明言此四項為 RAGAS 導入前的過渡代理指標（以 `st.error` 標示）。

### 此頁面需查詢之 MongoDB collections

```text
chat_history      # 全頁唯一資料來源（僅取 agent_type=rag 的紀錄）
```

### 視覺化元件

| 元件 | 套件／API |
|------|-----------|
| similarity × rerank 散佈圖 | Plotly Express `px.scatter` + `add_vline` / `add_hline` |
| 檢索輪數分佈 | Plotly `go.Bar`（逐 bar 依門檻上色） |
| 冷熱資料 treemap | Plotly Express `px.treemap`（`color_continuous_scale="viridis"`，`np.average` 定 midpoint） |
| 健康度雷達 | Plotly `go.Scatterpolar`（目前狀態 + 健康基準兩條 trace） |
| 指標卡片 | `st.metric`（title 內嵌燈號 emoji）+ 自訂 CSS |
| 冷資料清單 | `st.dataframe` |
| 數值處理 | `numpy`、`pandas` |

### 依賴的環境變數（.env）

```text
MONGO_ALTAS_URI
MONGO_DB_NAME
```

---

## Page 06 — `pages/ai_knowledge_agent.py` AI 知識 Agent

### 畫面區塊

| 區塊 | 功能 |
|------|------|
| 登入 gate | 與 Page 03 共用 `session_state` 的 demo 帳密登入（四種角色） |
| Hero 區 | 標題「筆記語意查詢 · 摘要」；右上角顯示目前角色與登出鈕 |
| 側欄控制區 | 顯示本次對話的 LLM 呼叫次數 / 上限，提供「🔄 開新對話」重置 session |
| 對話區 | `st.chat_message` 重播歷史訊息 + `st.chat_input` 輸入新問題 |
| 來源筆記 | 每則回覆下方 expander 列出來源檔名、章節、向量分數、rerank 分數 |
| Rate limit 提示 | 呼叫數達上限時顯示警告並 `st.stop()`，引導使用者開新對話 |

補充說明：

- **Agent 工作鏈**：`route(query, session_id)` 先做意圖分流（R1 關鍵字快篩 → R2 LLM 分類），回傳 `agent_target`。命中 `rag_agent` 時呼叫 `rag_agent.rag_query(query, session_id, alias_tag_pairs, known_tags)`，內部依序跑 rewrite → `$vectorSearch` → Cohere rerank → 生成；命中 `planning_agent` 時，首次呼叫 `generate_learning_map()`、之後改走 `refine_learning_map()`（以 `session_state.planning_map_generated` 判斷）。router 回傳未預期值時 fallback 到 RAG。兩者皆回傳 `{"answer", "sources"}`。
- **快取策略**：`_load_alias_to_tags_map(_db, collection)` 與 `_load_known_tags(_db, collection)` 以 `@st.cache_data(ttl="12h")` 跨 session 共用（前者讀 `obsidian_note_metadata`、後者讀 `note_vectors_multimodal`）。這兩份資料不隨互動改變，放 `cache_data` 而非 `session_state`，避免多人同時使用時每個 session 各存一份相同資料；參數以 `_db` 底線前綴讓 `cache_data` 略過雜湊連線物件。
- **角色差異**：`_render_sources(sources)` 對 Guest 角色只列出來源檔名與章節（同名同章節去重），不揭露 vector／rerank 分數；其他角色完整顯示。
- **Rate limit**：`AI_AGENT_RATE_LIMIT`（預設 20）限制單一 session 的 LLM 呼叫次數，只有 agent 成功回應才遞增計數。
- **錯誤處理**：整條 agent 鏈包在 try/except 內，例外以 `logger.exception()` 完整 traceback 進 stderr（Cloud Run logs 可查），前端只顯示友善訊息。
- **對話落地**：各 agent 內部呼叫 `agent_tools/chat_history.save_chat_history()` 寫入 `chat_history`，每則訊息一筆，`metadata` 內嵌欄位隨 `agent_type` 而異（schema 詳見 [`dashboard_ui/README.md`](../dashboard_ui/README.md#schema--chat_history)）；這份紀錄正是 Page 05 的資料來源。
- **待辦**：Google OAuth（`st.login()`）已備妥 `.streamlit/secrets.toml` 的設定步驟註解，待 GCP Console 建立 OAuth 2.0 Client 後即可替換掉 demo 帳密 gate。

### 此頁面需查詢之 MongoDB collections

```text
obsidian_note_metadata      # alias → tag 對照表
note_vectors_multimodal     # 合法 tag 字典 + $vectorSearch 向量檢索（index: obsidian_vectors_index2）
chat_history                # 讀多輪脈絡；並寫入本頁產生的對話紀錄
```

### 視覺化元件

此頁為對話介面，未使用任何資料視覺化套件。UI 全部由 Streamlit 原生元件組成：`st.chat_message`、`st.chat_input`、`st.expander`、`st.sidebar`、`st.button`、`st.text_input`，Hero 與登入卡片為原生 HTML + inline CSS。

外部模型服務：Vertex AI `gemini-embedding-2`（query 向量化，1536 維、L2 normalize）、`gemini-2.5-flash-lite`（router／rewriter／RAG 生成）、`gemini-2.5-flash`（planning）、Cohere `rerank-v3.5`（重排序）。

### 依賴的環境變數（.env）

```text
MONGO_ALTAS_URI
MONGO_DB_NAME
GCP_PROJECT_ID                                   # Vertex AI 專案
AGENT_PLATFORM_USER_CREDENTIALS                  # 地端執行時的 Vertex AI service account JSON
COHERE_API_KEY                                   # reranker
AI_AGENT_RATE_LIMIT                              # 選填，預設 20
ROLE_OWNER_USERNAME / ROLE_OWNER_PASSWORD        # 必填（其餘角色選填）
ROLE_ML_USERNAME / ROLE_ML_PASSWORD
ROLE_SENIOR_USERNAME / ROLE_SENIOR_PASSWORD
ROLE_GUEST_USERNAME / ROLE_GUEST_PASSWORD
```

> 地端執行時，需解除 `agent_tools/connect_to_google_genai.py` 與 `agent_tools/query_with_vector_search.py` 中「地端測試跑下面區塊」的註解，client 才會從 `AGENT_PLATFORM_USER_CREDENTIALS` 取憑證；部署到 Cloud Run 時維持註解狀態，改用 ADC。

---

## 待整理事項

- 登入機制為 `.env` 帳密的 demo gate，Page 03 與 Page 06 各自複製一份 `CREDENTIALS` 清單與登入表單，OAuth 導入時可一併收斂成共用元件。
