# 循環改進處、遇到過的問題彙整
## ♻️ 改進中
- README 與專案結構文件仍需隨任務演進持續修訂，包含各 ETL 任務產出的 MongoDB collection schema 與 Phase IV 部署里程碑。
- Task03 LeetCode GraphQL API 缺少正式文件，且依賴 `LEECODE_SESSION` 與 CSRF token；cookie 過期會導致 403，雲端部署前需評估自動更新或替代認證流程。
- Task06 MongoDB Atlas Vector Search 目前資料量仍小，M0 Free Tier 足夠；但後續筆記數、chunk 數、embedding 維度或 metadata 增加時，需重新估算儲存量與成本。
- Phase III RAG agent v2 檢索受資料量不均影響：通識型主題（如 docker / k8s）在向量庫中的筆記量少於特定主題（如 dev container），rerank 後雖能命中、但回答易偏狹隘（見 20260625 測試 case 3）。後續需補充通識型筆記或評估針對主題覆蓋度的檢索策略。（20260625）
- Phase III RAG agent v2 reranker 信心門檻未設：rerank 相對分數偏低（最高僅約 0.7）時模型仍會給出探索性回答，需評估是否設定 rerank 分數門檻或在回答中標示信心程度。（20260625）
- Task07 長 context 筆記（如大型筆記本頁面）會造成 LLM 回應高延遲，需追蹤並建立監控機制以識別潛在卡頓點。（20260616）

## ✅ 已解決
- Task02 GitHub REST API 需要處理 rate limit，以及 409、429、403 等例外狀態的邏輯；後續維護時仍須留意 API 規格與錯誤處理策略。
- Task02 曾發生 GitHub commit 統計在多分支中重複計算的邏輯錯誤，已修正，但後續新增統計指標時需避免相同資料被重複聚合。
- Task03 ccClub 資料抓取依賴 CSRF token、帳號與密碼，需持續注意登入流程、token 取得方式與憑證管理。
- Task05 Google Sheets ETL 曾遇到 `SettingWithCopyWarning` 與 upsert 設計錯誤，已透過 `dataframe.copy()` 與 upsert 邏輯修正。
- Task07 Intent Router：R2 LLM 受前輪 RAG agent 對話污染，誤將 RAG 回覆視為自身判斷依據；已在 `_r2_llm_classify()` 組裝 historical messages 時插入隔離提示修正。（20260610）
- Task07 OneNote download：實作滑動視窗 rate limiter 遵守 Graph API 每分鐘 115 次、每小時 380 次上限，並對 429 加指數退避（最多 retry 10 次）。（20260612）
- Task07 OneNote download：壓力測試發現大型筆記本下載時 hourly rate limit 觸發長達 46 分鐘等待導致 access token 過期；已在 `api_get()` 遇 401 時自動呼叫 `refresh_token()` 並以 `token_refreshed` flag 防止無限重試。（20260612）
- Task07 HTML→MD 轉換：`soup.get_text()` 會靜默丟棄所有 HTML tag（含 `<img>`），LLM 無法感知圖片存在；已改為先用 `replace_with()` 將 `<img>` 轉為 Markdown 圖片語法再呼叫 `get_text()`。（20260613）
- Task07 LLM 選型：比較 Gemini 2.5 flash lite 與 Haiku 4.5 的價格、rate limit、context window 後，確定採用 Gemini 2.5 flash lite（價格更低、context window 更大）。（20260615）
- Task07 Pipeline 穩定性：`t_html_to_markdown()` 改為每頁 LLM 轉換完成後立即寫入磁碟，避免後續頁面失敗導致已完成頁面資料丟失。（20260616）
- Task07 效能：`_get_genai_client()` 移出 retry loop，改為每次 pipeline run 初始化一次，避免短時間內重複讀取憑證觸發 Vertex AI throttling。（20260616）
- Task07 LLM 品質：發現傳入 `http_options=types.HttpOptions(timeout=N)` 至 `genai.Client()` 會中斷模型 thinking phase 導致輸出品質劣化；已放棄此方法，改以 retry-on-exception 處理 LLM hang。（20260616）
- Task07 GCS 路徑設計：將 Obsidian 與 OneNote 筆記分至 `from-obsidian/` 與 `from-onenote/` 子資料夾，解決 `gcloud storage rsync -d` 可能誤刪跨來源同名檔案的問題。（20260617）
- Task07 Archive endpoint：`archive()` 存在 TOCTOU race condition（`find_one` 後資料被刪，upsert 建出殘缺資料）；已改為 `upsert=False` 並檢查 `matched_count`，為 0 時返回 404。（20260617）
- Task07 Archive endpoint：初版將 DB 連線、`copy_images()`、`archive_md()` 包在同一 try-except，不易除錯；已拆分為獨立 try-except，分別對應 504/503/502/500 各狀態碼。（20260617）
- Task07 audit log 缺失：OneNote 下載、LLM 萃取、GCS 上傳三個流程的 audit log 均已補齊，並載入 MongoDB Atlas 三個 collection（`onenote_graph_api_logs`、`gemini_llm_logs`、`onenote_page_metadata`）。（20260615）
- Task07 LLM 生成表格審核：`Note Reviewer` Streamlit 頁面（`dashboard_ui/pages/onenote_review.py`）已實作，提供人工逐頁審核介面，使 ML scientist 與生技領域人員可在頁面上直接審閱 LLM 自動生成內容並決定是否封存。（20260617）
- Phase III 的 Router Agent 檢索品質：`_extract_filter_tags()` 直接拿短詞 tag（如 AI、MySQL）對整句 query 做 `fuzz.partial_ratio` 比對，易因部分字符巧合命中錯誤 tag（如「找 dev container」誤中 AI tag）污染下游 rag agent；已移除該層，改以「alias 模糊比對反查筆記 tags（`_extract_tags_via_alias()`）→ HyDE 重寫（`_r_hyde_rewrite()`）→ 全庫退階」的鏈路，藉筆記 alias 的語意結構導航，檢索準確度明顯提升。（20260621）
- Phase III 的 Router Agent 跨輪上下文污染：追問（如「partition_clause 能否再講多一點」）被 router 重新抽出錯誤 `filter_tags`（如 kafka）傳給 rag agent，導致撈回無關 chunks；已新增 `_looks_like_followup()` 與 `_get_last_filter_tags()`，追問時直接繼承上一輪 `filter_tags`、跳過重新抽取，緩解主要污染（殘留問題見改進中）。（20260621）
- Task06 embedding 選型：已從純文字模型 `text-embedding-3-small` 改為多模態 `Gemini-embedding-2`，並重構 task06 pipeline 以符合其 prompt 格式（多模態與未來圖片需求的疑慮已解除）。（20260624）
- Task06 vector upsert 殘留 chunk：筆記重新切塊後 chunk 數變少時，舊 chunk 不會被 upsert 覆蓋而成為殘缺孤兒資料；已改為先依 `file_path` `deleteMany` 同筆記所有 chunk 再 insert 新 chunk，避免多輪 embedding 後殘留破碎 chunk。（20260624）
- Task06 API 用量：導入 CDC（data capture change）機制，僅當 GCS 檔案變更且 `obsidian_notes` 中 `embedding_done=false` 時才呼叫 Vertex AI 進行 embedding，否則略過，節省 API 請求。（20260624）
- Phase III Router/RAG Agent prefilter 雙面刃與跨輪上下文污染：舊版以 tag／file_path 對 vector search 做 boolean prefilter，初始命中錯誤或漏掉時反而把正確答案硬排除，且 `_looks_like_followup()` 追問繼承上輪 filter 易擴大污染、啟發式追問判定又會誤判同主題新查詢。已重構為 RAG agent v2——Router 職責單一化只做 intent 分類，retrieval 全封裝進 `rag_query()`：帶 chat history 的 Query Rewrite（改寫為獨立問句並推薦 tags 做 query expansion，不做 prefilter）→ 無 prefilter 的 vector search（top_k 10~15）→ Cohere cross-encoder rerank（用原始 query 取 top 5）→ LLM 生成。標籤缺失不再排除正確答案，追問由 rewrite 看 history 自動補全指代，多輪測試 case 1/2/3 大多通過（殘留資料量不均問題見改進中）。（20260625）

# Daily Work Log
## 20260423 Work log
1. Initiated the project description in README.md, describing the goal of project and planned developmet items.
2. Initiated git branch feature/etl-pipeline
3. Initiated virtual environment by using pyenv + poetry. Used python 3.14.
4. Installed the python tools by
    ```bash
        poetry add pymongo python-frontmatter python-dotenv loguru

        # pymongo: for connection to MongoDB
        # python-frontmatter: for parsing the frontmatter in each .md file in vault.
        # logura: for saving/showing logs humanfriendly
    ```
5. Built the early folder structure and summarized it in [doc/project_structure_feature-etl-pipeline.md](project_structure_feature-etl-pipeline.md).

6. Create .env files. The contents in .env followed the requirements in the .env.example file.
7. Create four scripts that manages the ETL pipeline in task01-Obsidian.
8. Pre-run the pipeline and load the results to MongoDB on premises.
    ```bash
        poetry run python task01_obsidian_etl/main.py.
        # or:
        poetry run python -m task01_obsidian_etl.main
    ```
9. Establish the unit tests for task01.

## 20260428 Work log
1. Read the [official docs](https://docs.github.com/en/rest) about GitHub Rest API as references in task02.
    In conclusion, there were three major documents guiding how to interact with endpoints of GitHun Rest API:
    - endpoint of listing repo: https://docs.github.com/en/rest/repos/repos?apiVersion=2026-03-10#list-repositories-for-the-authenticated-user
    - endpoint of listing commits:  https://docs.github.com/en/rest/commits/commits?apiVersion=2026-03-10#list-commits
    - endpoint of listing readme: https://docs.github.com/en/rest/repos/contents?apiVersion=2026-03-10#get-a-repository-readme
2. Create `Personal Access Token (classic)` and appended it to the .env file.
3. Created four scripts that manages the ETL pipeline in task02-github_restapi_etl.
4. Drafted the schema design of collections generated in this task in [doc/project_structure_feature-etl-pipeline.md](project_structure_feature-etl-pipeline.md). `This can be revised in the future if needed`.
5. Installed python module, `requests`, by executing :
    ```bash
        poetry add requests
    ```
6. Create four scripts to that manages the ETL pipeline in task02-github_restapi.
7. Pre-run the pipeline and load the results to MongoDB on premises.
    ```bash
        poetry run python task02_github_restapi_etl/main.py.
    ```

## 20260429 Work log
1. According to official documents(https://docs.github.com/en/rest/using-the-rest-api/rate-limits-for-the-rest-api?apiVersion=2026-03-10&versionId=free-pro-team%40latest&restPage=about-the-rest-api), added function _check_and_wait_rate_limit() for the prevention of exceeding rate-limit.
2. Consolidate the try-except in the [srcipt](../task02_github_restapi_etl/e_request_github_api.py) to make sure the 409, 429, 403 error can be captured and properly handled case by case.
3. Establish the unit tests for task02 and all the testing results are pass.

## 20260503 Work log
1. Searched available API endpoints from leetcode.com. The searching results showed that leetcode has been applying graphQL API to request documents and users' features for backend.
2. However, no official documents about querying practices for the graphQL API of leetcode were provided. Instead, used the [suggestions on Postman](https://documenter.getpostman.com/view/14486486/2s93sZ6tec#intro).
3. Through the pre-tests on Postman, concluded that two querying statements, `view solved problem for user` and `Question Number` were what we could used in this project. The particular techniques should be in attentions was two COOKIES, `LEECODE_SESSIOM` and `CRSF TOKEN` when HTTP request.
4. The execution results demonstrated that if the COOKIES were expired then HTTP request might failed (error 403). So, the [ETL task 03](../task03_leetcode_ccClub_etl/) requesting leetcode graphQL API needed manual log-in on browser beforehand in order to keep the COOKIES not expired. `The current ETL task03 was suitable for running on-premise. How to automatically refresh the COOKIES in period should be discussed when deployment.`
5. Append the environments variables required for calling `leetcode graphQL API` to the .env file.
6. Created four scripts performing ETL tasks for personal submission records on leetcode. The scripts were stored in [task03_leetcode_ccClub_etl](../task03_leetcode_ccClub_etl/).
7. Drafted the schema design of collections generated in this task in [doc/project_structure_feature-etl-pipeline.md](project_structure_feature-etl-pipeline.md). `This can be revised in the future if needed`.

## 20260505 Work log
1. Investigate if API endpoints available from ccClub judgement system that was another website for coding practices once registered. The investigating result showed that several endpoints featuring REST API was accessible.
2. The particular techniques should be in attentions was CRSF TOKEN in cookies when HTTP request. The token was given by server upon visit. To successfully extracting the personal coding practices records (like what users generally did on leetcode.com) in ETL pipeline, `CRSF TOKEN`, `username` and `password` were key points.
3. After pre-testing, already created four scripts performing ETL tasks for personal submission records on ccClub. The scripts were stored in [task03_leetcode_ccClub_etl](../task03_leetcode_ccClub_etl/).
4. Drafted the schema design of collections generated in this task in [doc/project_structure_feature-etl-pipeline.md](project_structure_feature-etl-pipeline.md). `This can be revised in the future if needed`.

## 20260508 Work log
1. Created a spreadsheet for scoring personal skills on the online google sheet.
2. Created a Service Account on GCP console, then generated and downloaded the JSON key of account.
3. Granted the Service Account "Editor" access to the google sheet.
4. Appended [doc/project_structure_feature-etl-pipeline.md](project_structure_feature-etl-pipeline.md), to addressed the schema design of collections generated by task05. `This can be revised in the future if needed`.
5. Inititated four scripts performing ETL tasks for personal skill scoring and statistical calculation. The scripts were stored in [task05_googlesheet_skill_etl](../task05_googlesheet_skill_etl/).
6. Appended the file path of JSON key to the .env file.
7. Polished the scripts at step 5 via Claude. After that, python-logger was added to improve readability. Also, dataframe.copy() method was implemented to a little lines to prevent from `SettingWithCopyWarning`.
8. Establish the unit tests for task05 and all the testing results are pass.

## 20260511 Work log
1. To branch `feature/etl-pipeline`, fixed the logistic transformation error about task02 that would repeatedly count the same commits in all branches so that the commit counts were overestimated.
2. To branch `feature/etl-pipeline`, fixed the design error on the upserting in the function `upsert_skill_scores` about task05.
3. To branch `feature/etl-pipeline`, correct the typo of label name on radar axis.

## 20260512 Work log
1. Created app.py as `HOME page` via streamlit. The precomputing functions before render was defined in [dashboard_ui/utils](../dashboard_ui/utils/).
2. Asked Codex to polish the draft of app.py. Major improvements:
```
    1. 面臨問題：`app.py` 有 hard-coding 靜態資料。
    我提供的解決方向：改成調用 `dashboard_ui/utils/interact_with_mongodb.py` 內讀取 MongoDB 的函式，並生成 `app2.py`。
    Codex最後修改的方向：建立 `app2.py`，用 MongoDB utils 取得雷達圖、KPI、GitHub、刷題題型等資料，並加上必要格式轉換。
    最終是否解決：Yes，app2.py 合併入 app.py

    2. 面臨問題：`make_radar()` 的 hover tooltip 因內容太長被切邊。
    我提供的解決方向：修正 hover 顯示。
    Codex最後修改的方向：新增 hover 文字換行 helper，將任務內容自動插入 `<br>`，並調整雷達圖 margin/domain。
    最終是否解決：Yes

    3. 面臨問題：修正 hover 後發生 `update_layout()` 重複傳入 `margin` 的 TypeError。
    我提供的解決方向：回報錯誤訊息。
    Codex最後修改的方向：建立 `radar_layout = {**plotly_layout_base, "margin": ...}`，避免 `margin` 被重複作為 keyword 傳入。
    最終是否解決：Yes，app2.py 合併入 app.py

    4. 面臨問題：MongoDB utils 回傳值新增 `snapshot_date` / `fetched_date`，頁面需要顯示最近更新日期。
    我提供的解決方向：在兩個雷達圖與 KPI 四張卡片，共 6 處加上「最近更新日期」。
    Codex最後修改的方向：雷達圖使用 `st.caption()` 顯示日期；KPI 初版也先用 caption 顯示。
    最終是否解決：Yes，app2.py 合併入 app.py

    5. 面臨問題：`get_obsidian_kpi()` 與 `get_github_kpi()` 已改成 tuple 最後一個元素固定為更新日期，先前相容 dict/tuple 的 helper 變得多餘。
    我提供的解決方向：再次修改 `app2.py`，刪掉多餘函式，並把 KPI 更新日期改成 `_format_delta()` 的 `suffix` 傳入。
    Codex最後修改的方向：移除 `_date_from_result()`，直接 unpack tuple，將四張 KPI 的更新日期併入 `st.metric()` delta 字串。
    最終是否解決：Yes，app2.py 合併入 app.py

    6. 面臨問題：`biotech_labels` 中 `"製程技術 (細胞分注、反應器操作) 操作能力"` 太長，radar 軸標籤被切到。
    我提供的解決方向：調整斷行。
    Codex最後修改的方向：新增 radar label formatting，將該標籤顯示成三行，並用 label normalization 保持 hover 任務查找正常。
    最終是否解決：Yes，app2.py 合併入 app.py
```

## 20260513 Work log
1. Reviewed `README.md` to consolidated the project milestone again. Defining tasks of the feature developments and deployment on cloud services clearly, and exported in the paragraph of [2. `Knowledge Factory`](../README.md).
2. Based on the revised paragraph mentioned at 1., created the [2nd streamlit page](../dashboard_ui/pages/knowledge_factory.py). Because there were miscellaneous elements on UI of `HOME` and `Knowledge Factory` pages, the UI components were concluded in the new scripts, [ui_elements.py](../dashboard_ui/utils/ui_elements.py) in order to make the codes more readable.
3. Create contexts to cowork with Claue code in the next stage.
    ```markdown
    ---
    # Phase II 部署工作啟動前提
    ## 專案背景
    **專案名稱**：個人技能儀表板與知識庫訓練（Streamlit + MongoDB local/MongoDB atlas + GCP）
    **開發者**：Jessie Lin（生技製藥工程師、研究員，轉資料工程師）
    **目前狀態**：Phase I 已完成，進入 Phase II 雲端部署階段

    ## 已完成的 Phase I 成果
    **Branch `feature/etl-pipeline`**：
    - ETL task01 (Obsidian.md 存 metadata 與 content)
    - ETL task02 (GitHub REST API 獲取 repository 資料)
    - ETL task03（LeetCode GraphQL API 獲取取刷題進度 + ccClub 取得刷題進度）
    - ETL task05 (Google Sheets Skill 盤點表，獲取技能經驗值並清洗後量化)
    **Branch `feature/dashboard-ui`**：
    - Streamlit 兩頁式 dashboard
        - **`dashboard_ui/app.py`**（第一頁主頁Home，描述 KPI / 雷達圖 / GitHub cards / 刷題統計）
        - **`dashboard_ui/pages/knowledge_factory.py`**（第二頁，此專案架構繪製頁）
    - functions as utils：
        - **`dashboard_ui/utils/interact_with_mongodb.py`**
        - **`dashboard_ui/utils/precomputing.py`**
        - **`dashboard_ui/utils/ui_elements.py`**
    **資料庫**：地端 MongoDB localhost
    **credentials**: 使用 `.env` file
    --
    ```
4. Created the [hand-over](branch_developd_gcp_deploy_hand_over.md) of GCP deployment procedures in phase II.

> Until 20260514, the containers for ETL `task01`、`task02`、`task03`、`task05` were stably ran by Cloud run jobs while `dashboard-ui` app service was stably ran by Cloud run services, demonstrating that the docker images generated by branch `develop` worked well so far. However, some questions about workflow might be solved or optimized:
    - 經由 Git Actions push到Artifact registry 進版 image 後，如何確保 cloud run jobs 下次啟動容器時是使用最新版的 image?目前是手動進入 GCP console 更改 job configuration，指定最新版 (latest) 的容器。

## 20260525 Work log (Task 06 Start)
### Evaluate which Embedding models were suitable
1. the types of data to be vectorized. The .md files for a Obsidian vault containing vast `string` and `images(.PNG)`. Sometimes `pdf` was attached to the files and it almost hardly happened.
2. the characters of each file ranged in 500 - 7,000 in Engilish & Chinese which means that the `tokens from one .md file might be 1,000 - 14,000`.
3. Considering the service (a chatbot providing note summary, query) will run on cloud. `The embedding models should allow to be called through API` rather than restricting to installation on premise.

    > Thus, `text-embedding-3-small` provided by OpenAI and `Gemini Embedding 2` by Google are two candidates.

4. Cost of calling Embedding API
    > Cost Calling to `Gemini Embedding 2` was 10x higher than that to `text-embedding-3-small`. Both are affordable so far.

|情境篇數| Tokens | text-embedding-3-small |費用 |
|------|---------|------------------------|----|
|初次全量建立 1,000 篇| ~800K tokens | $0.016（約 0.5 台幣）|
|初次全量建立 5,000 篇| ~4M tokens |$0.08（約 2.5 台幣）|
|每週增量（50 篇新筆記| 50 篇~40K tokens|$0.0008（幾乎免費）|

### Evaluate the loading on Vector database, MongoDB atlas.
1. It is better to do data chunking because the content of each .md file are long-text which might occassionally exceeded the limit of context window of the furture LLM model or the limit of tokens of embedding model.
2. The dimensions of vectors for the model `text-embedding-3-small` are `1536`, while for `Gemini embedding 2` are `3072`.

|Model |維度 |每個向量大小（float32）|
|------|----|---------------------|
|text-embedding-3-small |1536 | 1536 × 4 bytes = 6 KB|
|Gemini Embedding 2 |3072 | 3072 × 4 bytes = 12 KB|

3. Cost calculation
    ```plaintext
    假設你有 300 篇筆記：
    → 每篇 6 個 chunk = 1,800 個向量
    → 1,800 × 6 KB（text-embedding-3-small）= 10.8 MB 向量資料
    → 加上 metadata（source、chunk_index、content text）≈ 再乘 3 倍
    → 總計約 32.4 MB

    假設你有 1,000 篇筆記，則 108 MB
    ```
> `MongoDB atlas M0 Free Tier up to 512 MB, far from 108 MB`


## 20260526 Work log
1. MVP and RAG practices are the recent major goals in this project, so `text-embedding-3-small` was selected as the primary embedding model. If embedding muiltple files are firmly required in the next step, then the multimodal model `Gemini embedding 2` could be selected.
- 使用模型：text-embedding-3-small
    - 引用方式：openai Python SDK，model 參數傳入 "text-embedding-3-small"
    - API 文件：https://platform.openai.com/docs/guides/embeddings
    - 維度：1536（EMBEDDING_DIM），建立 MongoDB Atlas Vector Index 時填這個數字
    - 費用：$0.02 / 1M tokens（2025 年定價）
2. Went to https://platform.openai.com/api-keys to create an API secret key (and set billing detail which needed credit card). Keep it in .env and secret managers.
3. Created the scripts `task06/t_chunk_embed.py` and `task06_obsidian_embed_etl/l_upsert_vectors.py`. Successfully practiced chuncking and embedding the long text in three markdown files.
4. Created the script `task06_obsidian_embed_etl/main.py`, to successfully insert the docs with embedded chunks to new collection `Obsidian_vectors` on atlas.
5. Created the index for vector search by following the [hand-over](./task06_vctr_srch_idx_hand_over.md). The resulted collection `Obsidian_vectors` that contained the embedded chunks from the long texts in 63 .md files, took about 410 KB in MongoDB atlas.
6.

> Until 20260527, some questions might be solved or optimized:
> 1. 若未來一份筆記被重新切塊後 chunk 數量減少 (例如從 6 個縮為 4 個)，
    舊的 chunk_index 4、5 不會自動被刪除。
    目前資料量小，影響不大；若未來需要清理孤立 chunk，
    可在 upsert 前先 delete_many({"file_path": file_path})，再重新 insert。
> 2. 根據這篇新聞(https://www.ithome.com.tw/news/173423)，發現 atlas 為 MongoDB 提供 Voyage embedding model，可以在使用 MongoDB 雲端資料庫時使用自動 embedding 功能，後續再考慮補上選型評估。

## 20260528 Work log
1. Evaluated which AI agents are suitable for this project. Then exported to [report](./ai-agent-evaluation-report.md).

## 20260610 Work log
1. The intent router agent and rag agent were created and tested in the first round via unit test. There were some logistic defect when judging the intention in the samples of user's queries.
The testing results were listed as follows. Particulary in the Sample 10 and 11, the context with historical chat messesges with RAG agents confused the LLM of router agent in R2 plan. The LLM representing R2 considered the responses by RAG its own response.
```
    # ============= Sample 1 ================
    # Model Response: 🆗
    # 使用 R1 方案，R1 命中 rag keyword: ['查詢'], score=0.0222
    print(route("幫我查詢Database的索引建立語法，我只要MySQL的", "router_test_run11"))

    # ============= Sample 2 ================
    # Model Response: 🆗
    # 使用 R1 方案，R1 命中 planning keyword: ['規劃'], score=0.0227
    print(route("幫我規劃初階資料工程師的學習", "router_test_run12"))

    # ============= Sample 3 ================
    # Model Response: 🆗
    # R2 輸出格式異常: '這個要求與查詢或摘要筆記內容，或是生成個人化學習路徑都無關。使用者只是想訂機票，這是一個獨立的任務，需要使用專門的訂票服務或網站。因此，我無法將'，預設導向 rag_agent, score=0.5
    print(route("訂機票", "router_test_run13"))

    # ============= Sample 4 ================
    # Model Response: 🆗
    # 使用 R1 方案，R1 命中 rag keyword: ['在哪'], score=0.0222
    print(route("小波在哪裡", "router_test_run14"))

    # ============= Sample 5 ================
    # Model Response: 🆗
    # R2 輸出格式異常: '我無法判斷你的意圖。你的輸入「好餓」與查詢筆記內容或生成學習路徑沒有關聯。請提供更明確的指示。'，預設導向 rag_agent, score=0.5
    print(route("好餓", "router_test_run15"))

    # ============= Sample 6 ================
    # Model Response: 🆗
    # R1 命中 planning keyword ['規劃']，但同時命中排除詞 ['旅遊']，降級至 R2
    # R2 方案判斷結果: planning_agent, score=0.95
    print(route("幫我規劃神戶三日旅遊方案", "router_test_run16"))

    # ============= Sample 7 ================
    # Model Response: 🆗
    # R2 輸出格式異常: '我無法判斷您的意圖。您是想查詢現有的神戶旅遊筆記內容，還是想生成一個個人化的神戶旅遊學習路徑或行程規劃呢？'，預設導向 rag_agent, score=0.5
    print(route("我想了解神戶旅遊方案", "router_test_run0610-7"))

    # ============= Sample 8 ================
    # Model Response: ⚠️ Should not route to 'planning agent' ! ⚠️
    # R2 方案判斷結果: planning, score=0.95
    print(route("寶可夢大師成長路徑","router_test_run0610-8"))

    # ============= Sample 9 ================
    # Model Response: 🆗
    # R2 輸出格式異常: '我無法判斷您的意圖。您的輸入「好餓唷」並未包含任何關於查詢筆記內容或生成學習路徑的資訊。請提供更明確的指示，例如您想查詢筆記中的特定內容，或是'，預設導向 rag_agent, score=0.5
    print(route("好餓唷", "router_test_run0610-9"))

    # ============= Sample 10 ================
    # Model Response: 🆗
    # "目前的筆記裡沒有相關內容。"
    print(rag_query("好餓唷!", "test_run0610-10"))

    # Model Response: ⚠️ 回應受到前輪對話污染，R2 LLM 把 RAG agent 的回覆當成自己的答案拋出 ⚠️
    # R2 輸出格式異常: '目前的筆記裡沒有相關內容。'，預設導向 rag_agent, score=0.5
    print(route("好餓唷~", "test_run0610-10"))

    print(rag_query("好餓唷!", "test_run0610-10"))  # RAG agent回應 "目前的筆記裡沒有相關內容。"

    # Model Response: ⚠️ 仍然污染 ⚠️
    # R2 輸出格式異常: '目前的筆記裡沒有相關內容。'，預設導向 rag_agent, score=0.5
    print(route("好餓唷~", "test_run0610-10"))

    # Model Response: ⚠️ 污染範圍是 R2的LLM，R1方案採用關鍵字比對所以回覆沒有問題 ⚠️
    # 使用 R1 方案，R1 命中 rag keyword: ['查詢'], score=0.0222
    print(route("查詢MySQL索引語法", "test_run0610-10"))


    # ============= Sample 11 ================
    # Model Response: 🆗
    # R2 輸出格式異常: '我無法判斷您的意圖。您的輸入「好餓唷~」與查詢或摘要筆記內容（rag_agent）或生成個人化學習路徑（planning_agent）的意圖都不相關。'，預設導向 rag_agent, score=0.5
    print(route("好餓唷~", "test_run0610-11"))

    # Model Response: 🆗
    # "目前的筆記裡沒有相關內容。"
    print(rag_query("好餓唷!", "test_run0610-11"))

    # Model Response, ⚠️ 回應受到前輪對話污染，R2 LLM 把 RAG agent 的回覆當成自己的答案拋出 ⚠️:
    # '目前的筆記裡沒有相關內容。'，預設導向 rag_agent, score=0.5
    print(route("好餓唷~", "test_run0610-11"))

    # Model Response: 🆗
    # 這次有找到'根據提供的筆記片段，MySQL 索引的創建語法可以在以下幾種情況下進行：\n\n1.  **...'
    print(rag_query("MySQL索引在哪", "test_run0610-11"))

    # Model Response: ⚠️ 仍然污染 ⚠️
    # R2 輸出格式異常: '目前的筆記裡沒有相關內容。'，預設導向 rag_agent, score=0.5
    print(route("好餓唷~", "test_run0610-11"))
```
3. By inserting the prompt to the paragraph when assembling the historical messages in the function `_r2_llm_classify()` that had been defined in `dashboard_ui/agents/intent_router_agent.py`. The router agent could response more appropriately. The test result is recorded as follows (Sample 12).

```
    # ============= Sample 12 ================

    # Model Response: 🆗
    # 'R2 輸出格式異常: '我無法判斷您的意圖。您的輸入「好餓唷~」與查詢或摘要筆記內容（rag_agent）或生成個人化學習路徑（planning_agent）的意圖都不相關。'，預設導向 rag_agent, score=0.5'
    print(route("好餓唷~", "test_run0610-12"))

    # Model Response: 🆗
    # "目前的筆記裡沒有相關內容。"
    print(rag_query("好餓唷!", "test_run0610-12"))

    # Model Response: ✅ 回覆已經矯正
    # R2 方案判斷結果: rag_agent, score=1.0
    print(route("好餓唷~", "test_run0610-12"))
    # 💡 補充: 同時發現若 rag history 裡已有相同輸入的紀錄，
    #    R2 會給高 intent_score（例如 1.0），即使該輸入意圖不明。
    #    原因：LLM 把「上一輪 rag 處理過」解讀為「這一輪應該繼續給 rag」。
    #    真實使用情境下 router 只跑一次，此問題不會在 production 出現。

    # Model Response: 🆗
    # 使用 R1 方案，R1 命中 rag keyword: ['查詢'], score=0.0222
    print(route("查詢MySQL索引語法", "test_run0610-12"))

    print(rag_query("MySQL索引在哪", "test_run0610-12"))

    # Model Response: 🆗
    # R2 輸出格式異常: '你的輸入「好餓唷~」與查詢筆記內容或規劃學習路徑的意圖都不符。我無法判斷你的意圖。'，預設導向 rag_agent, score=0.5
    print(route("好餓唷~", "test_run0610-12"))
```

## 20260612 Work log
1. Created new branch `html-to-md` for new feature of conversion `.html` output from OneNote graph API to .`.md` files.
2. Installed Claude Code AI assistant.
3. Installed `OpecSpec` for practice of Spec-Driven Development along with this project.
4. Inititated the testing scripts for pipeline `task07_onenote_to_markdown` where primarily intended to request the personal notes on Microsoft OneNote through the `Azure graph API`, download the raw notes as individual .html file and summarize the `metadata` of html files in .csv file.

- The storage hierarchy of a metadata, .html files and .md files are temporarily operated as follows. Then the granularity of metadata is defined at page-level of a notebook.

5. Until 20260612, the downloaded few files are firstly saved disk on premises. Some observations were observed and fixed:

    - **Rate Limit**：使用滑動視窗 rate limiter，同時遵守 Graph API 的兩個限制：每分鐘 120 次（上限設 115）與每小時 400 次（上限設 380）。遇到 429 時在 `Retry-Af
    ter` 基礎上加指數退避，retry 最多 10 次。
    - **Token 過期（壓力測試發現）**：下載大型筆記本（17 sections、數百頁）時，每小時 rate limit 會觸發長達 46 分鐘的等待，導致 access token 在等待期間過期，下一次
    API 呼叫收到 401 而崩潰。修復方式：`api_get()` 遇到 401 時會自動呼叫 `refresh_token()` 刷新 token 並重試一次（`token_refreshed` flag 防止無限重試）。

> However, audit log was missing, so new function recording the **audit log should be established**.

6. Used python package `markdowndify` to roughly transform the file format from `.html` file to `.md` in order to remove the markup so that the user prompt wrapped with the md content asking LLM for key extraction could be shorter, and the file size could be smaller. When converting to .md, inserted `frontmatter` so that users could be able to manage the .md file on Obsidian better in the future.

7. After utilizing mardowndify package, LLM were introduced to polish the overall content structure. *Two LLM candidates were proposed, Anthropic Haiki 4.5 or Google Gemini flash 2.5 lite.* So far, The performance by the model 'Haiki 4.5' has been tested first on 20260612. Some observation was concluded as follows.

    |  notebook  |  section  |  page  |  observation  | possible impact |
    |------------|-----------|--------|---------------|---------------|
    |  Data Engineering  |  Summarize_Airflow_Kafka  |  (經典到爆) LocalExecutor 失敗 | Repeatedly showed the page title at the first line of content body | 🟢 Might not interfere reading experiences of humans and AI |
    |  Data Engineering  |  Summarize_Airflow_Kafka  |  (經典到爆) LocalExecutor 失敗 |  unexpected heading level conversion, some should not be promoted from \<li> to \<h2> (## in markdown)  | 🔴 Wrong hierarchy of header/subheader/caption/... would impact the reading experiences of humans and might misleading AI. |
    |  Data Engineering |  YT_彭彭  |  MySQL  |  Some paragraph in original text of html did not end with at least 2 whitespace, causing that after transformation the following newline could not lose indentation and unaligned position of head. | 🟡 Might interfere reading experiences of humans |
    |  Data Engineering |  YT_彭彭  |  MySQL  |  Some Engilish letters in original text of html were typed in `full-width` (e.g. `ＴＡＢＬＥ`) but did not transformed to `half-width` (e.g., `TABLE`).   | 🟢 Might not interfere reading experiences of humans and AI |
    |  Data Engineering |  YT_彭彭  |  MySQL  | Several sentenses started with `bullets` lacked of line break. Instead, they sticked the last letter/symbol of the previous line where they should not belong. (e.g:  `(1234.PNG)- 補充：`, should be `(1234.PNG)   \- 補充：`)  |  🟢 Might not interfere reading experiences of humans and AI |
    |  Data Engineering |  YT_彭彭  |  SQL基本資訊  |  The tags \<ul> and the inner tags \<li> were all transformed to `-`. However, it is better to promote the outermost \<ul> to `#` or `##` in .md file rather than `-`. |  🔴 Ambiguous hierarchy might lead to the loss of semantics after chunking. |

> HTML 的 \<ul>\<li> 階層本身對 AI 來說，仍能理解父子關係；但如果這些 \<li> 實際上是在扮演「章節標題」的角色，那仍然不如 \<h1>~\<h6> 或對應的 Markdown # ## ### 結構來得清晰。 尤其是從 OneNote 匯出的 HTML，通常建議先轉換成語意化的 Markdown 再餵給 RAG 或訓練流程。

> 就語意強度 h1 > h2 > h3 > ul/li > 單純段落，大部分 RAG 系統都會給標題更高權重。如果一份 html 筆記都用清單來標記，再轉成 markdown 語法時可能只剩 `-` 這樣的階層，這未來可能會讓語意強度減弱。

> **Experience rule of data Transformation to markdown for better data chunking, RAG, AI understanding.**
    想讓 Markdown 同時對 人類、Markdown 解析器、RAG 系統、LLM 都穩定可讀，建議：  \
    1. 標題用 # / ## / ###  \
    2. 清單用 -  \
    3. 圖片、標題、清單之間留空行  \
    4. 不要把新元素黏在上一行尾巴

8. Due to the observation mentioned above, the other transformation approaches were evaluated again.

| 方案編號 | 方案                                                                   | 成本 | 準確度 | 前測過? |
| ------- | --------------------------------------------------------------------- | --- | ----- | ----- |
| S1 | HTML → Reshape structure by LLM → Markdowndify tool                   | 低  | 最高  | YES (samples owned by user) |
| S2 | HTML → Markdowndify tool → Reshape structure by LLM                   | 低  | 高 (tool 可能破壞原始階層)  | YES (samples owned by user), as summarized in 6~7. |
| S3 | HTML → PDF → OCR by Goole Document AI API  → Markdowndify tool        | 中高 | 中   | YES (official tutorial) |
| S4 | HTML → PDF → OCR by Goole Document AI API → Reshape structure by LLM  | 最高 | 中   | No |

> According to the pre-test result, **the approach in this task07 was alterd from `S2` to `S1` to aviod data loss.**

## 20260613 Work log
1. Starting to draft the new transformation srcipt using the approach `S1`. This time, the LLM tested was `Gemini flash lite 2.5 lite`.
> Price comparison between [Gemini 2.5 flash lite Model](https://cloud.google.com/gemini-enterprise-agent-platform/generative-ai/pricing?_gl=1*fk0iq6*_ga*MTEwMzU3Nzc5NS4xNzc2MzA1MzUw*_ga_WH2QY8WWF5*czE3ODEzMDkxMjMkbzExMiRnMSR0MTc4MTMxMDE3NCRqMjgkbDAkaDA.#gemini-models-2.5) and [Anthropic Haiku 4.5 Model](https://platform.claude.com/docs/en/about-claude/pricing).
> Rate limit comparison between [Gemini 2.5 flash lite Model](https://ai.google.dev/gemini-api/docs/rate-limits) and [Anthropic Haiku 4.5 Model](https://platform.claude.com/docs/en/api/rate-limits)
> Token calculation comparison between [Gemini 2.5 flash lite Model](https://docs.cloud.google.com/gemini-enterprise-agent-platform/models/capabilities/get-token-count?hl=zh-tw#gemini-get-token-count-samples-python_genai_sdk) and [Anthropic Haiku 4.5 Model](https://platform.claude.com/usage/limits?focus=claude_haiku_4:rpm).
> Context Window comparison between [Gemini 2.5 flash lite Model](https://ai.google.dev/gemini-api/docs/models/gemini-2.5-flash-lite) and [Anthropic Haiku 4.5 Model](https://platform.claude.com/docs/en/about-claude/models/overview).


2. While testing the [`S1` pipeline](/task07_onenote_to_markdown/t_html_to_markdown.py) on the sampe OneNote page `供應商稽核.html`, **a data loss issue was identified: all `<img>` tags were silently dropped before the content was fed into LLM.** The root cause was `soup.get_text(' ', strip=True)`, which strips every HTML tag (including `<img>`) when converting BeautifulSoup tree to plain text. As a result, the LLM received no image-related information and was unable to place image references in the reshaped content.

    | file | affected step | observation | possible impact |
    |------|--------------|-------------|----------------|
    | `供應商稽核.html` | `plain_text = soup.get_text(...)` | `<img>` tags with `alt` and `src` attributes were discarded entirely before LLM call | 🔴 Image data permanently lost in `new_content`; LLM has no knowledge that images exist in the note |

    - **Fix applied**: Instead of calling `get_text()` directly after parsing, each `<img>` tag is now replaced in-place with its Markdown image syntax `![alt](src)` using BeautifulSoup's `replace_with()` method before `get_text()` is invoked. This way, image markers survive the tag-stripping step as plain text strings and are visible to the LLM.

    ```python
    # before fix
    for img in soup.find_all("img"):
        if img.get("alt"):
            img["alt"] = " ".join(img["alt"].split())
    plain_text = soup.get_text(' ', strip=True)  # <img> silently discarded here

    # after fix
    for img in soup.find_all("img"):
        alt = " ".join(img.get("alt", "").split()) or "image"
        src = img.get("src", "")
        img.replace_with(f"\n![{alt}]({src})\n")   # convert tag → markdown string in-place
    plain_text = soup.get_text(' ', strip=True)     # image markers now survive as plain text
    ```

    - To complement the fix above, an additional instruction `(vi)` was added to the LLM user prompt, explicitly telling the model that any `![]()` pattern in the input is a pre-cleaned, Markdown-compatible image link. The model is instructed to keep the image within its original section (not move it out), allow indentation adjustment, and optionally generate a short 3–5 line AI-generated image description labelled as `「AI生成圖釋」`.

    > **Lesson learned**: `BeautifulSoup.get_text()` is destructive — it silently removes all tags including semantic ones like `<img>`, `<table>`, `<a>`. When the downstream consumer is an LLM that needs to reconstruct structure, always pre-convert semantically important tags to their text-equivalent representations (e.g., Markdown syntax) before calling `get_text()`, rather than assuming the LLM can infer their existence from surrounding context.

3. The output by LLM was sometimes not perfect. As tested result about the image with embedded table in the notebook `生技製劑筆記本/General technical knowledge/Mycoplasma`. LLM tried to analyze the semantic of the table in a statistic image and created new table via markdown syntax. Although the truth of such table, the original image, did not loss and it was referred by a link in the markdown context, the newly created table by AI need to be fairly and professionally `inspected to judge the reliability of using AI model`. This should be handed over to ML scientist and senior techinicans within biotech domain.

## 20260615 Work log
1. Determined to use Gemini 2.5 flash lite LLM due to cheaper price.

    Feature  |  Gemini 2.5 flash lite   |   Haiki 4.5  |
    ---------|--------------------------|--------------|
    Input token  |  1 M   |   200 K  |
    Output token  |  65 K   |   64 K  |
    Price  |  baseline   |   2x-higher than 2.5 flash lite  |

2. Drafted whole development plan of `task07` in the branch`feature/html-to-md` and it future intention in the other branches. See the doc [`hand-over`](./task07_html_to_md_hand_over.md).

    > All the development since then will follows this hand-over to create the other spec. docs(if needed) and scripts.

3. Created [python scripts](../task07_onenote_to_markdown/) for entire task07 pipeline.
    > The srcipt establishment also solved the issue on lack of audit logs in the processes of fetching OneNote, extracting by LLM and uploading to GCS. They are loaded to MongoDB atlas. Meanwhile, the metadata of linkage between original notes from OneNote and transformed notes by LLM are also created. Finally, three collections were established on MongoDB atlas as planned in the [hand-over doc](./task07_html_to_md_hand_over.md).

## 20260616 Work log
1. Refactored `t_html_to_markdown()` to **save each page immediately** after LLM conversion (instead of accumulating all results in memory and flushing at the end), so that successfully converted notes are written to disk even if the pipeline stalls on a later page.

2. Moved `_get_genai_client()` out of the per-attempt retry loop: the `genai.Client` is now initialised **once** per pipeline run and passed into `extract_llm_fields()`, avoiding repeated credential reads and connection setup within a short window — which was the likely cause of Vertex AI throttling.

3. It was observed that passing `http_options=types.HttpOptions(timeout=N)` to `genai.Client()` degraded the quality of LLM output (markdown with no heading hierarchy or line breaks), because the HTTP-layer timeout interrupted the model's thinking phase before generation was complete. This approach was abandoned; LLM hangs are instead handled by the existing retry-on-exception logic.

    > Should keep track of any note with `long context` that causes high latency between prompt submission and model response, as this is the most likely trigger for apparent hangs.

4. Extracted `save_one_page()` as a standalone helper in `l_save_markdown.py`; `l_save_markdown()` is kept as a thin wrapper for backward compatibility. Added `continue` in the `except` block (with `finally` for counters) so that LLM failures skip disk write entirely rather than saving low-quality plain-text fallback.

## 20260617 Work log
1. Revised the file path (exactly blob path) planned for archive.
- before change:
    - Note-related files in '.md' directly generated by Obsidian laptop app via gcloud rsync, were stored at `gs://personal-vaults/01_daily_logs/`、, `gs://personal-vaults/04_projects/`、,...etc.
    - Note-related files in '.md', '.html', '.png' generated by OneNote graph API and Gemini LLM were uploaded from on-premise laptop via gcloud rsync, were stored at `gs://onenote-vaults/<my-accountid>/<notebook-name>/<sectoin-name>/<page-name>/`.
    - Note-related files in '.md' and '.png' after reviewed were originally expected to be archived at `gs://personal-vaults/01_daily_logs/`、, `gs://personal-vaults/04_projects/` as well.

- after change:
    - Note-related files in '.md' directly generated by `Obsidian laptop app` via gcloud rsync, were stored at `gs://personal-vaults/<my-accountid>/from-obsidian/01_daily_logs/`、, `gs://personal-vaults/<my-accountid>/from-obsidian/04_projects/`、,...etc.
    - Note-related files in '.md', '.html', '.png' generated by `OneNote graph API` and Gemini LLM were uploaded from on-premise laptop via gcloud rsync, were stored at `gs://onenote-vaults/<my-id>/<notebook-name>/<sectoin-name>/<page-name>/`.
    - Note-related files in '.md' and '.png' after reviewed were decided to be archived at `gs://personal-vaults/<my-accountid>/from-onenote/01_daily_logs/`、, `gs://personal-vaults/<my-accountid>/from-onenote/04_projects/`.
- Reason for changes:
    - Make the management rule of different subfolders flexible. The notes originated from OneNote and Obsidian can be control in its own TTL and object versioning policy. For example, notes in the subfolder `gs://personal-vaults/<my-accountid>/from-onenote/...` is set for 3 year month while the subfolder `gs://personal-vaults/<my-accountid>/from-obsidian/...` is set for 2 months because the updating frequency may be higher.
    - Make sure the execution of `gcloud storage rsync -d` did not delete or replace the file with the same name already exists but originated from different note software/endpoint. For example, if the content of '20260625 testing_LLM_sonnet.md' was firstly created via OneNote software, processed by LLM, approved by human and finally archived in `gs://personal-vaults/01_daily_logs/`. The next day, users intend to synchronized the notes from Obsidian app on premise to the same bucket and he/she want to used `gcloud storage rsync -d` to complete. At that moment, this was expected to delete the newly archived files in the bucket yesterday since they did not existed in the Obsidian folder on premises. On the other hand, using `gcloud storage rsync`(without `-d`) would let the obsoleted files accumulated. If a certain note was just renamed without any content change before synchronizing, then there were be two files containing duplicated contents staying on GCS bucket. So, `gcloud storage rsync -d` is required. Then the notes from two sources was managed in two subfolders in the same bucket.


2. Tried OpenSpec Skill and triggered through Claude Coding Assistant. (Model Sonnet 4.6) This is the first time in this project.

3. By combining the [hand-over created by myself](task07_html_to_md_hand_over.md) and spec-driven development (SDD) tool OpenSpec, established the [`Note Reviewer` streamlit page](./../dashboard_ui/pages/onenote_review.py) and created the [archive endpoint](./../archive_service/) via python Flask.

4. Summarized what has learned from the result of 1 & 2.
    - gcs_archiver.py: Most of python function design followed the logistic of my hand-over, especially, how to get the markdown path, html path, image path correctly from the single-truth, MongoDB atlas `onenote_page_metadata`.
    - gcs_archiver.py: Commons downloading methods of blobs from GCS by python SDK:

        | 方法                     | 回傳型別        | 適用場景            |     行為         |
        | ---------------------- | ----------- | --------------- | --------------- |
        | download_as_text()     | str         | md/json/csv/txt | 對GCS API request get -> 下載 bytes -> decode 成純文字並回傳<br>例如：<br>raw_md = blob.download_as_text(encoding="utf-8") <br> 類似於： <br>raw_bytes = blob.download_as_bytes() <br>raw_md = raw_bytes.decode("utf-8")  |
        | download_as_bytes()    | bytes       | pdf/image/zip   |  對GCS API request get -> 下載 並回傳 bytes <br>例如：得到 b'Hello World' |
        | download_to_filename() | 寫入檔案        | 大檔案             | 直接存成本地檔案，打開檔案內容要另外寫 <br>例如：blob.download_to_filename("report.pdf") <br>with open("report.pdf", "rb") as f: <br>&nbsp;&nbsp;&nbsp;&nbsp;data = f.read()|
        | download_to_file()     | stream      | API/Memory stream/Flask 回傳檔案   | from io import BytesIO<br>blob = bucket.blob("docs/readme.md")  ## 建立 blob 物件<br>buffer = BytesIO()  ## 建立二進位制檔案存在記憶體<br>blob.download_to_file(buffer)   ## 將 blob 寫入這個二進位制檔案<br>buffer.seek(0)  ## 寫完將檔案游標移到字首<br>content = buffer.read().decode("utf-8")  ## 再次從頭讀檔，並以utf-8解析回字串<br>print(content)|

    - gcs_archiver.py: Common uploading methods to GCS by python SDK.

        | 方法 | 輸入型別 | 適用場景 | 行為 |
        | ----- | ----- | ----- | ----- |
        | `upload_from_string(data, content_type=...)` | `str` / `bytes` | 動態生成內容（markdown / JSON / API output） | 將記憶體中的字串或 bytes → 直接轉成 object 上傳到 GCS<br><br>例如：<br>`blob.upload_from_string(rewritten_md, content_type="text/markdown")`<br><br>等價概念：<br>`bytes_data = rewritten_md.encode("utf-8")`<br>`blob.upload_from_file(io.BytesIO(bytes_data))` |
        | `upload_from_filename(filename, content_type=...)` | `str (file path)` | 本機已有檔案 | 直接讀取本機檔案 → 上傳到 GCS<br><br>例如：<br>`blob.upload_from_filename("README.md")`<br><br>內部流程：<br>open file → read bytes → upload |
        | `upload_from_file(file_obj, content_type=...)` | file-like object (`open()`) | 已開啟檔案 / streaming / pipeline | 從 Python file object 讀取資料 → 上傳到 GCS<br><br>例如：<br>`with open("data.json", "rb") as f:`<br>&nbsp;&nbsp;&nbsp;&nbsp;`blob.upload_from_file(f)`<br><br>適合：串流或避免先存成路徑 |
        | `upload_from_fileobj(file_obj)` | file-like object（舊版 API） | legacy / 相容舊 code | 與 `upload_from_file()` 類似，但較舊版本 API<br><br>建議：新專案用 `upload_from_file` |
        | `upload_from_string(..., content_type="application/octet-stream")` | `bytes / str` | binary / unknown format | 將資料當成「純二進位」上傳，不做格式解釋<br><br>例如：<br>`blob.upload_from_string(image_bytes, content_type="application/octet-stream")` |

    - app.py： 修改 archive() 矛盾設計，因為函式中已經有 find_one() 確認 page_id 事先存在，如果 page_id 不存在，那後面 updte_one(upsert=True) 基本上不會發生 upsert；如果 padge_id 確實存在，但立刻有人在瞬間毫秒間隙刪了這筆資料，那後面 updte_one(upsert=True) 的 upsert 反而會產出殘缺不全的資料，也就是**race condition / TOCTOU (Time-of-check to time-of-use)**的issue。解決方式：
        - `把 upsert 改為 False`。
        - Pymongo `update_one()` 回傳的 UpdateResult 物件，取出 `matched_count` 屬性判別如果是 0，代表前面 find_one() 有找到資料但是在 update_one() 時資料不見了，此時中止函式不往後執行，且借用 404 code 讓 Flask 泡給前端。

    - app.py： 調整 try-exception 顆粒度，初版的 archive() 將 DB 連線、copy_images()、archive_md() 都包在一區 try-except 中，不易除錯。將他們用獨立的 try-exception 包覆後，捕捉400、500、503、504 常見 status code。

    | 例外   | 上游  | 狀態碼 |
    | ----- | ----- | ----- |
    | ServerSelectionTimeoutError, NetworkTimeout, DeadlineExceeded   | DB / GCS | 504 |
    | ConnectionFailure, GCS ServiceUnavailable   | DB / GCS | 503 |
    | GCS GoogleAPICallError（其餘 HTTP 錯誤）  | GCS | 502 |
    | 其他 Exception  | 我方邏輯 | 500 |


5. Running the streamlit page and flask app.py
    ```bash
        # streamlit
        poetry run streamlit run dashboard_ui/app.py
    ```
    ```bash
        # flask (alter one to run)
        poetry run python -m "archive_service.app"

        # or
        poetry run flask --app archive_service.app run --port 8001
    ```

## 20260621 Work log
1. Established the [feature of planning agent](../dashboard_ui/agents/planning_agent.py) and the [chat box in streamlit page](../dashboard_ui/pages/ai_knowledge_agent.py) as planned in the [evaluation-report](ai-agent-evaluation-report.md).

2. Performed the querying tests. Some unexpected answers from the agents are observed and listed as follows.
- Testing case 1 for note querying and summarizing:

    | Run number in one session | User Query | Route to which Agent | Agent's response |  Why unexpected |
    | ------------------------- | ---------- | ---------------- | ---------------- | --------------- |
    | 1 | 幫我找NoSQL的CAP | rag | 目前的筆記裡沒有相關內容。 | Shall reply `20260421 CAP 理論.md` which is exactly existing. Also this note did not presented in the source list, showning that no correct response in the chunks.  |
    | 2 | 找尋CAP  | rag | 目前的筆記裡沒有相關內容。| Same explanation as above  |
    | 3 | CAP理論 | rag | AP理論探討分散式架構下的三項權衡議題， |  3 of 4 notes in the source list hitted the targeted note, `20260421 CAP 理論.md` |
    | After `revised the system prompt` from <br>"如果完全沒有足夠資訊，請明確告知使用者「目前的筆記裡沒有相關內容」，不要自行推測或捏造答案。"<br> to <br>"若筆記片段中找不到足夠資訊，請提供使用者你找到的片段資訊，跟對方確認你找到的關鍵字中是否有切中使用者真正想詢問的。如果完全沒有足夠資訊，請明確告知使用者「目前的筆記裡沒有相關內容」，不要自行推測或捏造答案。". <br> Then continue the session: |
    | 4 | 找尋 cap | rag | "根據您提供的筆記片段，找到與「CAP理論」相關的內容如下：<br>來源 4 檔案: 20260120 Kafka - 基本介紹.md｜章節: 來源筆記<br>提到「20260421 CAP 理論」以及「分散式架構」。<br>筆記片段中僅提及「CAP理論」與「分散式架構」的關聯，並未詳細解釋 CAP 理論的內容。<br>您想詢問的「CAP」是否與這個「CAP理論」有關呢？" | `20260421 CAP 理論.md` missed in the source list again. |
    | 5 | 是的 | rag | "您提供的筆記片段中，只有來源 1 提到了 $eleMatch 這個運算子，並說明它在針對「多份文檔組合而成的陣列」做查詢時非常常見。<br>...(中略)..您想詢問的「是的」是指您想進一步了解 $eleMatch 的用法，還是您想詢問其他與 CAP 理論相關的內容呢？"  | `20260421 CAP 理論.md` missed in the source list again and inaccurate semantic explanation by agent. |

- Testing case 2 for note planning:

    | Run number in one session | User Query | Route to which Agent | Agent's response |  Why unexpected |
    | ------------------------- | ---------- | ---------------- | ---------------- | --------------- |
    | 1 | 我目前熟悉 Linux 基本指令和 Python，完全沒用過 Kubernetes，想學會在資料工程的場景下用 Kubernetes，例如把資料處理腳本容器化部署。 | planning | "好的，根據您提供的筆記片段，我對您目前的程度理解如下：您對 Linux 指令與 Python 程式設計有基礎，並對 Docker 容器化技術有深入理解，包括 Dockerfile 編寫、多容器啟動（如 Kafka）、以及儲存機制（Bind Mount 與 Volume Mount）...<br>基於您的目標（在資料工程場景下用 Kubernetes 部署資料處理腳本），以下是為您規劃的學習路徑：---<br>### 學習路徑建議<br>#### 第一階段：Kubernetes 核心概念與基礎操作<br>#### 第二階段：資料處理腳本容器化與部署<br>#### 第三階段：資料工程儲存與狀態管理<br>*"    | Met the rule in system prompt |
    | 2 | 可以把 Kubernetes 核心概念與本地環境建置 那個階段展開講細一點嗎？ | planning agent | "好的，我已了解您希望針對「第一階段：Kubernetes 核心概念與基礎操作」進行更詳細的展開。<br>根據您提供的筆記片段，我對您目前的程度理解如下：<br>您對 Linux 指令與 Python 程式設計有基礎，並對 Docker 容器化技術有深入理解，包括 Dockerfile 編寫、多容器啟動（如 Kafka）、以及儲存機制（Bind Mount 與 Volume Mount）。對於資料工程的自動化流程、排程任務（如 Cron Job/Airflow）與大量數據處理也有經驗。此外，您對 Dev Containers 有豐富的使用經驗，並能利用 `docker-compose` 整合多服務開發環境。<br>### 學習路徑建議 (針對第一階段詳細展開)<br>#### 第一階段：Kubernetes 核心概念與基礎操作與本地環境建置<br>*   **目標：** 建立對 Kubernetes 運作原理與基本元件的全面理解，能夠操作 `kubectl` 部署簡單應用，並在本地環境成功搭建與互動。<br>*   **具體技能/主題：**<br>.  **Kubernetes 簡介與核心概念：從單機到分散式容器編排**<br>"| Some preface already showned in the last run of same session answered by agent again. |
    | 3 | (由於上輪對話agent有把回應是依據哪個筆記片段標示為註解，所以這輪使用者特地針對筆記註解來細部詢問)有點不懂，你的筆記片段7、8、9是什麼意思呢 | rag agent | "目前的筆記裡沒有相關內容。" | routing result did not went wrong but not meet user's real intention |
    | 4 | 我要規劃學習路徑，但是我是先針對剛剛的對話做詢問，上一輪對話中你提到的筆記片段7、8、9是指我哪一份筆記 | planning agent | "您好！非常抱歉，上一輪對話中我引用的筆記片段編號可能造成了混淆。這表示我在處理多輪對話時，對筆記片段的編號參考出現了錯誤。我會立即修正這個問題。<br>根據您這次提供的筆記片段列表，我來為您釐清上一輪對話中提到的編號所對應的筆記內容：<br>*   **筆記片段 7：** 在上一輪對話中，我提到「尤其當您使用 GKE 這類託管服務時 ([筆記片段 7])，了解其底層架構能幫助您更好地利用服務並進行故障排除。」    *   **實際對應的筆記：** `20260503 Python 爬蟲 POST() 相關參數.md`。<br>*   **澄清：** 這裡的引用是錯誤的。我對您「GKE 服務有初步認識」的判斷，應該是來自您在第一輪對話中提及的「對 Google Kubernetes Engine (GKE) 服務有初步認識」，而非這個特定的筆記片段。這個筆記片段本身是關於 Python 爬蟲的。<br>*   **筆記片段 8：** 在上一輪對話中，我並沒有明確引用筆記片段 8。<br>*   **實際對應的筆記：** `20260427 透過 leetcode 刷題學習 MySQL 語法.md`。<br>*   **筆記片段 9：** 在上一輪對話中，我提到「您已熟悉 Docker 容器化與 `docker-compose` 進行多容器服務整合 ([筆記片段 5], [筆記片段 9])。」<br>    *   **實際對應的筆記：** `MySQL Window Function.md`。<br>    *   **澄清：** 這裡的引用也是錯誤的。我對您「能利用 `docker-compose` 整合多服務開發環境」的判斷，應該是來自您在第一輪對話中提及的「多容器啟動（如 Kafka）」以及對 Docker 容器化的深入理解，而非這個特定的筆記片段。這個筆記片段本身是關於 MySQL Window Function 的。<br>**總結來說：**<br>*   我對您「GKE 服務有初步認識」的判斷，是基於您在初始需求中直接提及的資訊。<br>*   我對您「能利用 `docker-compose` 整合多服務開發環境」的判斷，是基於您對 Docker 容器化、多容器啟動（如 Kafka，對應 `[筆記片段 5]`）的熟悉程度。<br>*   筆記片段 3 (資料模型設計 - SQL.md) 在上一輪被錯誤地引用為「Cloud Run 的單一容器限制」。<br>我會確保在接下來的對話中，對筆記片段的引用更加精確，避免再次出現類似的錯誤。感謝您的指正！<br>請問您是否需要我根據這些澄清，重新評估或調整學習路徑建議？或者我們繼續針對「第一階段：Kubernetes 核心概念與基礎操作與本地環境建置」的展開內容進行討論？" | Bad user experiences |
    | 5 | 重新評估 | planning agent | "請提供您想重新評估的筆記片段編號或內容。" | Bad user experiences |
    | 6 | 重新評估kubernetes的學習路徑，確保回覆中有對應正確的學習筆記 | planning agent | "好的，我已了解您的需求，將重新評估 Kubernetes 的學習路徑，並確保所有「你已有基礎」的標註都能精確對應到您提供的筆記片段。<br>---### 學習路徑建議 (重新評估與筆記對應)<br>#### 第一階段：Kubernetes 核心概念與基礎操作<br>*   **目標：** 建立對 Kubernetes 運作原理與基本元件的全面理解，能夠操作 `kubectl` 部署簡單應用。<br>*   **具體技能/主題：**<br>*   **Kubernetes 簡介與核心概念：從單機到分散式容器編排**<br>| Correct note reference but the previous runs were the waste. |

3. After implementing additional three layers inside the [routing agent](../dashboard_ui/agents/intent_router_agent.py):  \
    (1) _extract_filter_tags() inside the function `route()`.  \
    (2) _extract_tags_via_alias() inside the function `route()`. \
    (3) _r_hyde_rewrite() inside the function `route()`: rewrite in the function `route()` for query transformation.

    > The performance was somewhat improved. Described as follows:

- Flowchart in route() of router agent:
    ```plaintext
    query
    │
    ├─ Step 3A: extract_filter_tags(原始 query, known_tags)  ← 全庫 tag 字典字串比對
    │           │
    │           ├─ 命中 → filter_tags 確定 → 跳到 rag_query()
    │           │
    │           └─ 沒命中 → Step 3B
    │
    ├─ Step 3B: alias 模糊比對
    │           1. distinct alias list (從 obsidian_notes)
    │           2. 模糊比對原始 query，定位到相關筆記（可能多篇）
    │           3. 萃取這些筆記的 tags，做「頻率收緊」而非全部聯集
    │           │
    │           ├─ 有抓到 tags → filter_tags 確定 → 跳到 rag_query()
    │           │
    │           └─ 沒抓到 → Step 3C
    │
    ├─ Step 3C: HyDE rewrite (原始 query + 全庫 known_tags) → 推薦一個 tag + 假設性問句
    │           │
    │           ├─ 推薦 tag 存在於 known_tags → filter_tags 確定
    │           │
    │           └─ 不存在 / NONE → Step 3D
    │
    └─ Step 3D: filter_tags = None，退化成無 filter 全庫搜尋
    ```

- key codes
    ```python
        # 如果導向 rag agent，則對使用者的查詢語句萃取出與現存筆記有關聯的標籤 (tag)
        filter_tags = None
        search_query = query
        search_optimize_method = None

        if agent_target == "rag_agent":
            db = get_db_atlas()
            known_tags = _load_known_tags(db, "obsidian_vectors")

            # Step 3A: 全庫 tag 字典字串比對
            tag_hit = _extract_filter_tags(query, known_tags)
            if tag_hit:
                filter_tags = [tag_hit]
                search_optimize_method = "extract_filter_tags"

            # Step 3B: alias 模糊比對，用來反查 tags，專治 tags 沒有正確標示、但是筆記名稱本身有符合查詢語意的時候
            if not filter_tags:
                logger.info(f"先模糊比對筆記本身alias...")
                alias_tag_pairs = _load_alias_to_tags_map(db, "obsidian_notes")
                tags_from_alias = _extract_tags_via_alias(query, alias_tag_pairs, known_tags)
                if tags_from_alias:
                    filter_tags = tags_from_alias
                    search_optimize_method = "extract_tags_via_alias"

            # Step 3C: HyDE rewrite，根據筆記庫真實存在的 tags 來重寫使用者的查詢，讓下一關的 rag agent 更能理解使用者意圖
            if not filter_tags:
                logger.info(f"模糊比對筆記本身 alias 查無結果，使用 HyDE 重寫查詢")
                client = _get_genai_client()
                hyde_result = _r_hyde_rewrite(query, known_tags, client)
                if hyde_result["tag"]:
                    filter_tags = [hyde_result["tag"]]
                search_query = hyde_result["hypothetical"]
                search_optimize_method = "HyDE_rewrite"

            # Step 3D: 都沒找到 → filter_tags 保持 None，退階成全庫搜索
            if not filter_tags:
                logger.info(f"使用 HyDE 重寫查詢也無效，退回全庫搜索")

        return {"agent_target": agent_target,
                "filter_tags": filter_tags,
                "search_query": search_query,
                "search_optimize_method": search_optimize_method}
    ```

- Testing case 1 for note querying and summarizing:

    | Run number in one session | User Query | Route to which Agent | Agent's response |  Why unexpected |
    | ------------------------- | ---------- | ---------------- | ---------------- | --------------- |
    | 1 | 幫我找NoSQL的CAP | rag | 目前的筆記裡沒有相關內容。筆記中提到 NoSQL 的時機，其中一點是「著重在快速讀取資料與可用性，而非ACID」。<br>您想詢問的關鍵字「CAP」是否與「ACID」有關聯？ | ❌ router agent 執行 `_extract_filter_tags()` 找到 NoSQL 筆記 tag，沒有去找CAP，誤導 rag agent 的 `vector search` |
    | 1 | 找尋CAP  | rag | CAP理論探討分散式架構下的三項權衡議題，包含：Consistency (一致性)、Availability (可用性)、Partitioning Tolerance (分區容忍)。這三者不可能兼顧，最多只能滿足其中兩種。... | ✅ router agent 執行 `_extract_tags_via_alias()` 找到'CAP-theorem' 與 'distribution-architecture' 筆記 tag，成功引導 rag agent 的 `vector search` 用這兩個 tag 檢索筆記 |
    | 1 | CAP理論 | rag | AP理論探討分散式架構下的三項權衡議題， | ❓ 來源筆記都準確指向實體筆記名稱。值得紀錄的是，這裡使用者的查詢是"理論"而非"theorem"，導致 router agent 得執行 `_extract_tags_via_alias()` 找到'CAP-theorem'與'distribution-architecture'、而不是乾脆的`_extract_filter_tags()`，或許可以思考的是`_extract_filter_tags()`的匹配精準度過於嚴苛? |
    | 1 | 摘要cap理論 | rag | CAP 理論探討分散式架構下的三項權衡議題... | 評語同上 |
    | 1 | 將cap理論摘要成3句 | rag | CAP 理論指出，在分散式架構中，一致性 (Consistency)、可用性 (Availability) 和分區容忍 (Partition Tolerance) 這三者無法同時兼顧，只能選擇其中兩項。... | 評語同上 |
    | 1 | 找尋cap理論筆記然後摘要理論的主張。 | rag | CAP 理論主張，在分散式架構中，一致性 (Consistency)、可用性 (Availability) 和分區容忍 (Partition Tolerance) 這三者無法同時兼顧，只能滿足其中兩項。  | router agent 執行 `_r_hyde_rewrite()` 重寫查詢語句，且一併回傳'CAP-theorem' tag |
    | 1 | find the note about 'cap-theorem' | rag | CAP 理論探討分散式架構下的三項權衡議題，包含：Consistency (一致性)、Availability (可用性)、Partitioning tolerance (分區容忍)。這三者不可能兼顧，之間只能滿足其中二種。 | ✅ router agent 執行 `_extract_filter_tags()` 直接命中 tag |

- Testing case 2 for note querying and summarizing:

    | Run number in one session | User Query | Route to which Agent | Agent's response |  Why unexpected |
    | ------------------------- | ---------- | ---------------- | ---------------- | --------------- |
    | 1 | 查詢MySQL的Window function | rag | 根據您提供的筆記片段，以下是關於 MySQL Window Function 的資訊：<br>架構：<br>Window function 的架構主要包含： | ✅ router agent 執行 `_extract_filter_tags()` 找到 MySQL 筆記 tag，引導 rag agent 的 `vector search()` |
    | 2 | partition_clause 能否再講多一點  | rag | 您好，根據您提供的筆記片段，partition_clause 在 MySQL Window Function 中是用來定義資料的分區方式。<br>這意味著，當您使用 PARTITION BY 子句時，MySQL 會將整個資料集分成不同的區塊（partitions），然後 Window Function 會獨立地在每個區塊內進行計算。....筆記片段中雖然沒有直接解釋 MySQL Window Function 的 `partition_clause`，但您提供的 Kafka 相關筆記中多次提到 "Partition"，其概念與 Window Function 的 `partition_clause` 有異曲同工之妙，都是將資料進行「分區」或「分組」的概念。<br>請問這樣的解釋對您有幫助嗎？您想進一步了解 `partition_clause` 在 MySQL 中的具體應用，或是其他方面的資訊呢?| ❌ router agent 執行 `_extract_tags_via_alias()` 找到"partition" 筆記 tag，混入雜訊引導 rag agent 的 `vector search()`用這tag 檢索到 kakfa |
    | 3 | 我不想知道 kafka，而是想知道 window function 用於「計算每個部門的平均薪資，您可以使用 PARTITION BY department，這樣平均薪資的計算就會在每個部門內部獨立進行，而不是對整個公司的薪資進行平均。」這個案例。 | rag | 您好，非常抱歉，我之前的回答誤解了您的意思，並提供了與 Kafka 相關的筆記內容。<br>根據您提供的筆記片段，這些內容都與 Kafka 的 Partition、Replication、Segment 和 Cleanup 相關，而沒有任何關於 MySQL Window Function 的資訊。 | ❌ router agent 執行 `_extract_tags_via_alias()` 找到"partition" 筆記 tag，混入雜訊引導 rag agent，此外，Window Function 是第一輪找到的筆記，但在這輪發生`上下文丟失`。 |

- Testing case 3 for note querying and summarizing:

    | Run number in one session | User Query | Route to which Agent | Agent's response |  Why unexpected |
    | ------------------------- | ---------- | ---------------- | ---------------- | --------------- |
    | 1 | 我想要找容器化技術 | rag | 根據您提供的筆記片段，以下是關於容器化技術的資訊：<br>Dev Container 是一種由微軟提供的 VS Code 插件，它使用 Docker 容器化技術來定義一個標準化的開發環境。這讓開發團隊成員能夠使： | ✅ router agent 執行 `_r_hyde_rewrite()` 重寫查詢語句，且一併回傳'docker' tag |
    | 2 | 找dev container  | rag | 目前的筆記裡沒有關於「dev container」的內容。 | ❌ router agent 執行 `_extract_filter_tags()` 找到"AI" 筆記 tag，混入雜訊引導 rag agent 的 `vector search()`用這tag 檢索到 AI |
    | 1 | 找dev-container  | rag | 根據您提供的筆記片段，以下是關於 Dev Container 的資訊：<br>什麼是 Dev Container？ Dev Container 是由微軟提供的 VS Code 插件，它使用 Docker 容器化技術來定義一個標準化的開發環境，讓 VS Code IDE 可以直接在該環境中工作。 | ✅ router agent 執行 `_extract_filter_tags()` 找到"dev-container" 筆記 tag，引導 rag agent 的 `vector search()` 用這 tag 檢索到 dev container |

4. After removed the first layer, `_extract_filter_tags()` from the function `route()`:
> The performance was even better and many issues on the 3. could be solved. New flow chart is described as follows:

- Flowchart in route() of router agent:
    ```plaintext
        query
        │
        ├─ Step 3A: alias 模糊比對（rapidfuzz）
        │    ├─ 命中一篇或多篇 alias → 反查這些筆記的 tags list
        │    │    └─ 用 known_tags 做校驗（過濾掉不存在的 tag）→ 傳給 rag_query()
        │    │
        │    └─ 沒命中 → Step 3B
        │
        ├─ Step 3B: HyDE rewrite（query + known_tags → LLM）
        │    ├─ LLM 推薦的 tag 存在於 known_tags → 傳給 rag_query()
        │    └─ 不存在 / NONE → Step 3C
        │
        └─ Step 3C: filter_tags=None，退化成無 filter 全庫搜索
    ```
- Now the searching chains before hand over to the rag agent in the function `route()` of router agent was changed to:
    ```python
    def route():
        # 中間省略.....
        # 如果導向 rag agent，則對使用者的查詢語句萃取出與現存筆記有關聯的標籤 (tag)
        filter_tags = None
        search_query = query
        search_optimize_method = None

        if agent_target == "rag_agent":
            db = get_db_atlas()
            known_tags = _load_known_tags(db, "obsidian_vectors")

            # Step 3A: alias 模糊比對，用來反查 tags，專治 tags 沒有正確標示、但是筆記名稱本身有符合查詢語意的時候
            if not filter_tags:
                logger.info(f"先模糊比對筆記本身alias...")
                alias_tag_pairs = _load_alias_to_tags_map(db, "obsidian_notes")
                tags_from_alias = _extract_tags_via_alias(query, alias_tag_pairs, known_tags)
                if tags_from_alias:
                    filter_tags = tags_from_alias
                    search_optimize_method = "extract_tags_via_alias"

            # Step 3B: HyDE rewrite，根據筆記庫真實存在的 tags 來重寫使用者的查詢，讓下一關的 rag agent 更能理解使用者意圖
            if not filter_tags:
                logger.info(f"模糊比對筆記本身 alias 查無結果，使用 HyDE 重寫查詢")
                client = _get_genai_client()
                hyde_result = _r_hyde_rewrite(query, known_tags, client)
                if hyde_result["tag"]:
                    filter_tags = [hyde_result["tag"]]
                search_query = hyde_result["hypothetical"]
                search_optimize_method = "HyDE_rewrite"

            # Step 3C: 都沒找到 → filter_tags 保持 None，退階成全庫搜索
            if not filter_tags:
                logger.info(f"使用 HyDE 重寫查詢也無效，退回全庫搜索")

        return {"agent_target": agent_target,
                "filter_tags": filter_tags,
                "search_query": search_query,
                "search_optimize_method": search_optimize_method}
    ```

- Testing case 1 for note querying and summarizing:

    | Run number in one session | User Query | Route to which Agent | Agent's response |  Why unexpected |
    | ------------------------- | ---------- | ---------------- | ---------------- | --------------- |
    | 1 | 幫我找NoSQL的CAP | rag | 根據筆記內容，CAP理論探討的是分散式架構下的三個權衡議題：Consistency (一致性)、Availability (可用性)、Partitioning Tolerance .... | ✅ router agent 執行 `_r_hyde_rewrite()` 重寫查詢語句，且一併回傳'CAP-theorem' tag |
    | 1 | 找尋CAP  | rag | 前的筆記裡有關於 CAP 理論的內容，主要探討分散式架構下的三項權衡議題：Consistency (一致性)、Availability (可用性)、Partitioning Tolerance (分區容忍)。... | ✅ router agent 執行 `_extract_tags_via_alias()` 找到'CAP-theorem' 與 'distribution-architecture' 筆記 tag，成功引導 rag agent 的 `vector search` 用這兩個 tag 檢索筆記 |
    | 1 | CAP理論 | rag | AP理論探討分散式架構下的三項權衡議題， | ✅ router agent 執行 `_extract_tags_via_alias()` 找到'CAP-theorem' 與 'distribution-architecture' 筆記 tag，成功引導 rag agent 的 `vector search` 用這兩個 tag 檢索筆記 |
    | 1 | 摘要cap理論 | rag | CAP理論探討分散式架構下的三項權衡議題：... | 評語同上 |
    | 1 | 將cap理論摘要成3句 | rag | CAP理論探討分散式架構下的三個權衡議題：一致性... | 評語同上 |
    | 1 | 找尋cap理論筆記然後摘要理論的主張。 | rag | CAP 理論主張，在分散式架構中，一致性 (Consistency)、可用性 (Availability) 和分區容忍 (Partition Tolerance) 這三者無法同時兼顧，只能滿足其中兩項。  | ✅ router agent 執行 `_r_hyde_rewrite()` 重寫查詢語句，且一併回傳'CAP-theorem' tag |
    | 1 | find the note about 'cap-theorem' | rag | CAP 理論探討分散式架構下的三項權衡議題，包含：Consistency (一致性)、Availability (可用性)、Partitioning tolerance (分區容忍)。這三者不可能兼顧，之間只能滿足其中二種。 | ✅ router agent 執行 `_r_hyde_rewrite()` 重寫查詢語句，且一併回傳'CAP-theorem' tag |

- Testing case 2 for note querying and summarizing:

    | Run number in one session | User Query | Route to which Agent | Agent's response |  Why unexpected |
    | ------------------------- | ---------- | ---------------- | ---------------- | --------------- |
    | 1 | 查詢MySQL的Window function | rag | 根據您提供的筆記片段，以下是關於 MySQL Window Function 的資訊：<br>架構：<br>Window function 的架構主要包含： | ✅ router agent 執行 `_extract_filter_tags()` 找到 MySQL 筆記 tag，引導 rag agent 的 `vector search()` |
    | 2 | partition_clause 能否再講多一點  | rag | 您好，您提供的筆記片段主要圍繞著 Kafka 的 Partition 概念，而非 MySQL 的 Window Function 中的 partition_clause。<br>根據您提供的筆記片段，我找到以下關於 Kafka Partition 的資訊.... | ❌ router agent 執行 `_r_hyde_rewrite()` 重寫查詢語句，且一併回傳'partition' tag，導致最後 Window function parition clause 沒有出現在 LLM 的回覆參考 |
    | 3 | 我不想知道 kafka，而是想知道 window function 用於「計算每個部門的平均薪資，您可以使用 PARTITION BY department，這樣平均薪資的計算就會在每個部門內部獨立進行，而不是對整個公司的薪資進行平均。」這個案例。 | rag | 供的筆記片段中，關於 MySQL Window Function 的 partition_clause，其作用是「資料表中的分區方式，分區完成後，MySQL 會針對分區後的每區塊，分別套用 window_function_name() 做運算。 | ✅ router agent 執行 `_extract_tags_via_alias()` 找到['MySQL', 'SQL', 'window-function'] 筆記 tag，正確回覆給使用者，只有第 2 層一度被污染 |

- Testing case 3 for note querying and summarizing:

    | Run number in one session | User Query | Route to which Agent | Agent's response |  Why unexpected |
    | ------------------------- | ---------- | ---------------- | ---------------- | --------------- |
    | 1 | 我想要找容器化技術 | rag | 根據您提供的筆記片段，以下是關於容器化技術的資訊：<br>Dev Container 是一種由微軟提供的 VS Code 插件，它使用 Docker 容器化技術來定義一個標準化的開發環境。這讓開發團隊成員能夠使： | ✅ router agent 執行 `_r_hyde_rewrite()` 重寫查詢語句，且一併回傳'docker' tag |
    | 2 | 找dev container  | rag | 根據您提供的筆記片段，以下是關於 Dev Container 的資訊...<br>定義與目的：... | ✅ router agent 執行 `_extract_filter_tags()` 找到 'docker', 'dev-container', 'development-environment', 'virtual-environment', 'collaboration' tag，引導 rag agent 的 `vector search()` |
    | 1 | 找dev-container  | rag | 根據您提供的筆記片段，以下是關於 Dev Container 的資訊：<br>什麼是 Dev Container： | ✅ router agent 執行 `_extract_filter_tags()` 找到 'docker', 'dev-container', 'development-environment', 'virtual-environment', 'collaboration' tag，引導 rag agent 的 `vector search()` |

    > 整體推論：
    _extract_filter_tags() 的核心問題不只是「只回傳一個 tag」，而是它的比對邏輯本身有漏洞，它拿 tag 字串去跟 query 做比對，但 tag 通常是短詞（MySQL、NoSQL、AI），query 是完整句子，fuzz.partial_ratio("AI", "找dev container") 很容易因為部分字符巧合命中而拿到高分，這解釋了 "找dev container" 命中 AI tag 這個令人費解的失誤。
    _extract_tags_via_alias() 效果較好的是，它走的是另一個方向，先找「哪篇筆記跟 query 有關」，再從那篇筆記「繼承整個 tags list」。這個間接定位的方式，等於用人類寫筆記時賦予的語意結構 (alias 是摘要性標題，比 tag 短詞資訊量帶來的語意更為豐滿) 來導航。

5. By following the previous testing result mentioned at 4., there was still a pending issue about the context contamination. As illustrated, the root cause after analysis pointed out the wrong filter tagas was generated by the router agent within the inner function `_extract_tags_via_alias()` of the function `route()`, and passed to the downstream rag agent. This led to the context contamination, the rag agent model with improper background information answered irrelevant output.

    ```
    使用者: "partition_clause 能否再講多一點"
            │
            ▼
        [Router Agent]  ← 問題出在這裡
        看到 "partition" → 抽出 kafka tag → 傳錯 filter_tags 給 rag_query()
            │
            ▼
        vector_search(filter_tags=["kafka"])  ← 撈回來的 chunks 就已經錯了
            │
            ▼
        [RAG Agent LLM]
        拿到一堆 kafka chunks + chat history ← 即使 prompt 再強，巧婦難為無米之炊
    ```

- This was fixed by implementing the new functions to judge if the current query was followup query. The flow chart was
    ```plaintext
    使用者: "partition_clause 能否再講多一點"
                │
                ▼
        [Router Agent] (比對 query 是否出現追問詞或是岔題排他性的詞)
                │
                ├─────────────────────────[ 是追問 ]─────────────────────────┐
                │                                                           │
                ▼                                                           ▼
    (從 chat history 查詢上一輪 filter_tags)                             [ 不是追問 ]
                │                                                           │
        ┌─────┴────────────────────────┐                                    │
        ▼                              ▼                                    │
    [ 查詢結果為 None ]            [ 查詢到 filter_tags ]                      │
        │                              │                                    │
        ▼                              ▼                                    ▼
    (代表上一層判斷有誤、           (繼承並跳過抽取 filter_tags 工作)     (根據 query 抽取新的 filter_tags)
    不是追問，回去重新執行                 │                                    │
    filter_tags 抽取)                   │                                    │
        │                              │                                    │
        ▼                              ▼                                    ▼
    vector_search(                 vector_search(                      vector_search(
    filter_tags=["kafka"]          filter_tags=(<上一輪的tags>)        filter_tags=["kafka"]
    )                              )                                   )
        │                               │                                    │
        └───────────────────────────────┼────────────────────────────────────┘
                                        │
                                        ▼
                                [RAG Agent LLM]
                            新 chunks + chat history
    ```
- Now the searching chains before hand over to the rag agent in the function `route()` of router agent was changed to:
    ```python
    def _looks_like_followup(query: str) -> bool:
    """
    判斷 query 是否屬於繼續追問，而非一個新的、岔題的獨立查詢。
    當字數少（<= 100 字）、包含追問訊號詞、不包含排他詞均滿足時，回傳 True 代表追問。
    透過判定是否為追問，來控制是否要在當前查詢中搜尋向量資料庫。

    這是輕量啟發式規則，不走 LLM，避免增加延遲。
    """

    FOLLOWUP_SIGNALS = ["再", "更多", "繼續", "詳細", "追問",
                        "能否", "可以", "那", "然後",
                        "剛才", "上面", "前面", "這個", "那個",
                        "它", "他", "她",
                        "more", "further", "continue",
                        "elaborate", "expand", "go on", "discuss"
                        ]
    EXCLUDE_SIGNALS = ["新", "改", "改成", "岔題", "另外",
                       "new", "another", "change", "other"]
    query_stripped = query.strip()
    is_short = len(query_stripped) <= 100
    has_signal = any(s in query_stripped for s in FOLLOWUP_SIGNALS)
    no_exc_signal = any(es not in query_stripped for es in EXCLUDE_SIGNALS)
    return is_short and has_signal and no_exc_signal


    def _get_last_filter_tags(db: Database, session_id: str) -> list[str] | None:
        """
        從 chat_history 讀取這個 session 最近一筆 router 紀錄的 filter_tags。
        回傳 list[str] (可能是空 list) 或 None (沒有歷史紀錄 / 上輪是 no_filter_fallback)。
        """
        doc = db["chat_history"].find_one({"session_id": session_id,
                                        "agent_type": "router",
                                        "role": "model",
                                        "content": {"$nin": ["rag_agent", "planning_agent"]},
                                        },
                                        sort=[("timestamp", -1)],  # 取最新一筆
                                        projection={"content": 1,
                                                    "_id": 0
                                                    },
                                        )
        if not doc:
            return None
        try:
            # 注意 find_one 回傳的是 dict，但是 doc 的值是 json-like string，值的部分需轉回 python object
            parsed = json.loads(doc["content"])
            return parsed if isinstance(parsed, list) else None
        except (json.JSONDecodeError, TypeError):
            logger.warning("_get_last_filter_tags: content 反序列化失敗")
            return None

    def route():
        # ── Step 3: 如果導向 rag agent，則對使用者的查詢語句萃取出與現存筆記有關聯的標籤 (tag) ─────────────────
        filter_tags = None
        search_query = query
        search_optimize_method = None

        if agent_target == "rag_agent":
            db = get_db_atlas()
            known_tags = _load_known_tags(db, "obsidian_vectors")
            alias_tag_pairs = _load_alias_to_tags_map(db, "obsidian_notes")

            # Step 3A: 先確認是否屬於使用者追問：短句且上輪有 filter_tags，直接沿用，不再重新找 tags ──────
            if _looks_like_followup(query):  #
                inherited = _get_last_filter_tags(db, session_id)
                logger.info(f"此波追問，無繼承 filter_tags，需重新抽取 tag")
                if inherited:
                    filter_tags = inherited
                    search_optimize_method = "inherited_tags_from_last_turn"
                    logger.info(f"追問繼承 filter_tags: {filter_tags}，跳過重新抽取")

            # Step 3B: 執行 _extract_tags_via_alias(query, alias_tag_pairs, known_tags)
            # Step 3C: 執行 HyDE rewrite
            # Step 3D: 判斷 是否要退階為請 rag agent 做全庫搜索
            # Step 3E: 執行 存入 chat_history

        return {"agent_target": agent_target,
            "filter_tags": filter_tags,
            "search_query": search_query,
            "search_optimize_method": search_optimize_method}
    ```
- The testing result was briefly summarized:


- Testing case 1 for note querying and summarizing:

    | Run number in one session | User Query | Route to which Agent | Agent's response |  Why unexpected |
    | ------------------------- | ---------- | ---------------- | ---------------- | --------------- |
    | 1 | 幫我找NoSQL的CAP | rag | 根據筆記內容，CAP理論探討的是分散式架構下的三個權衡議題：Consistency (一致性)、Availability (可用性)、Partitioning Tolerance .... | ✅ router agent 執行 `_r_hyde_rewrite()` 重寫查詢語句，且一併回傳'CAP-theorem' tag |
    | 1 | 找尋CAP  | rag | 前的筆記裡有關於 CAP 理論的內容，主要探討分散式架構下的三項權衡議題：Consistency (一致性)、Availability (可用性)、Partitioning Tolerance (分區容忍)。... | ✅ router agent 執行 `_extract_tags_via_alias()` 找到'CAP-theorem' 與 'distribution-architecture' 筆記 tag，成功引導 rag agent 的 `vector search` 用這兩個 tag 檢索筆記 |
    | 1 | CAP理論 | rag | AP理論探討分散式架構下的三項權衡議題， | ✅ router agent 執行 `_extract_tags_via_alias()` 找到'CAP-theorem' 與 'distribution-architecture' 筆記 tag，成功引導 rag agent 的 `vector search` 用這兩個 tag 檢索筆記 |
    | 1 | 摘要cap理論 | rag | CAP理論探討分散式架構下的三項權衡議題：... | 評語同上 |
    | 1 | 將cap理論摘要成3句 | rag | CAP理論探討分散式架構下的三個權衡議題：一致性... | 評語同上 |
    | 1 | 找尋cap理論筆記然後摘要理論的主張。 | rag | CAP 理論主張，在分散式架構中，一致性 (Consistency)、可用性 (Availability) 和分區容忍 (Partition Tolerance) 這三者無法同時兼顧，只能滿足其中兩項。  | ✅ router agent `認為有追問行為`，但因為數首輪對話，所以重新執行`_extract_tags_via_alias()`後無果，再進入 `_r_hyde_rewrite()` 重寫查詢語句，且一併回傳'CAP-theorem' tag |
    | 1 | find the note about 'cap-theorem' | rag | CAP 理論探討分散式架構下的三項權衡議題，包含：Consistency (一致性)、Availability (可用性)、Partitioning tolerance (分區容忍)。這三者不可能兼顧，之間只能滿足其中二種。 | ✅ router agent 執行 `_r_hyde_rewrite()` 重寫查詢語句，且一併回傳'CAP-theorem' tag |

- Testing case 2 for note querying and summarizing:

    | Run number in one session | User Query | Route to which Agent | Agent's response |  Why unexpected |
    | ------------------------- | ---------- | ---------------- | ---------------- | --------------- |
    | 1 | 查詢MySQL的Window function | rag | 根據您提供的筆記片段，以下是關於 MySQL Window Function 的資訊：<br>架構：<br>Window function 的架構主要包含： | ✅ router agent 執行 `_extract_filter_tags()` 找到 MySQL 筆記 tag，包含： {'alias': 'MySQL資料型態', 'tags': ['MongoDB', 'MySQL', 'data-type', 'BSON'], 'score': 62.5} 與 {'alias': 'MySQL Window Function', 'tags': ['MySQL', 'SQL', 'window-function'], 'score': 95.23809523809523} 這兩份筆記，引導 rag agent 的 `vector search()` |
    | 2 | partition_clause 能否再講多一點  | rag | 根據您提供的筆記片段，關於 partition_clause 的說明如下：<br>partition_clause 是資料表中的分區方式。在套用 Window Function 時，MySQL 會針對 partition_clause 分區後的每一個區塊，分別......您提供的其他筆記片段（來源 1、3、5）主要在討論資料庫的分片 (Sharding) 和分割 (Partitioning) 機制，以及 SQL 與 NoSQL 的比較，這些內容與 MySQL Window Function 中的 partition_clause 的具體用法關聯性較小。 | ⚠️ router agent `_looks_like_followup()` 判斷屬於追問，繼承前次 filter tags ('MongoDB', 'MySQL', 'data-type', 'BSON', 'SQL')，最後 Window function parition clause 留在 LLM 的回覆參考中，但因為 vector search 是由 rag agent 繼承 tags 與追問 query 後重新計算相似度，造成此時混入新的筆記來源與追問語意較相似但是跟上一輪語意較遠，最後造成 rag agent 仍有部分上下文污染。在這輪測試中發現來源筆記變成了 MongoDB 筆記 |
    | 3 | 追問 partition_clause 就好，不想知道分片機制。 | ⚠️ 回覆結果幾乎同上一輪，只是把分片機制刪掉而已。 |
    | 4 | 我只想知道 window function 用於「計算每個部門的平均薪資，您可以使用 PARTITION BY department，這樣平均薪資的計算就會在每個部門內部獨立進行，而不是對整個公司的薪資進行平均。」這個案例。 | rag | 供的筆記片段中，關於 MySQL Window Function 的 partition_clause，其作用是「資料表中的分區方式，分區完成後，MySQL 會針對分區後的每區塊，分別套用 window_function_name() 做運算。 | ⚠️ router agent 不知道這屬於追問，但靠著 user query 中不刻意提及非主題相關性的詞彙，router 會執行 `_extract_tags_via_alias()` 找到['MySQL', 'SQL', 'window-function'] 筆記 tag，正確回覆給使用者 |

- Testing case 3 for note querying and summarizing:

    | Run number in one session | User Query | Route to which Agent | Agent's response |  Why unexpected |
    | ------------------------- | ---------- | ---------------- | ---------------- | --------------- |
    | 1 | 我想要找容器化技術 | rag | 根據您提供的筆記片段，以下是關於容器化技術的資訊：<br>Dev Container 是一種由微軟提供的 VS Code 插件，它使用 Docker 容器化技術來定義一個標準化的開發環境。這讓開發團隊成員能夠使： | ✅ router agent 執行 `_r_hyde_rewrite()` 重寫查詢語句，且一併回傳'docker' tag |
    | 2 | 找dev container  | rag | 根據您提供的筆記片段，以下是關於 Dev Container 的資訊...<br>定義與目的：... | ⚠️ router agent 不知道這屬於追問，直接執行 `_extract_filter_tags()` 找到 'docker', 'dev-container', 'development-environment', 'virtual-environment', 'collaboration' tag，引導 rag agent 的 `vector search()` |
    | 1 | 找dev-container  | rag | 根據您提供的筆記片段，以下是關於 Dev Container 的資訊：<br>什麼是 Dev Container： | ✅ router agent 執行 `_extract_filter_tags()` 找到 'docker', 'dev-container', 'development-environment', 'virtual-environment', 'collaboration' tag，引導 rag agent 的 `vector search()` |

6. Others learned during coding:
    - Two iteration approaches to search the text in the LLM's response.

        ```python
            text = response.text.strip()
            # approach 1 ( next() + generator expression )
            note_line = next((l for l in text.splitlines() if l.startswith("ALIAS:")), "ALIAS: NONE")
            tag_line = next((l for l in text.splitlines() if l.startswith("TAG:")), "TAG: NONE")
            hyde_line = next((l for l in text.splitlines() if l.startswith("HYPOTHETICAL:")), "")

            raw_note = note_line.replace("ALIAS:", "").strip()
            raw_tag = tag_line.replace("TAG:", "").strip()
            hypothetical = hyde_line.replace("HYPOTHETICAL:", "").strip() or query

            # approach 2 ( for-loop )
            raw_note = "NONE"
            raw_tag = "NONE"
            hypothetical = query
            for line in text.splitlines():
                if line.startswith("ALIAS:"):
                    raw_note = line.replace("ALIAS:", "").strip()
                if line.startswith("TAG:"):
                    raw_tag = line.replace("TAG:", "").strip()
                if line.startswith("HYPOTHETICAL:"):
                    hypothetical = line.replace("HYPOTHETICAL:", "").strip() or query
        ```

    | approach |   explanation   |effectiveness  | edge condition  |
    | -------- |  -------------  | -------------- | -------------- |
    |    1     |  呼叫了三次 `text.splitlines()` 並`個別`走訪。<br> | `next()` + generator 可控制每次走訪 `text.splitlines()` 期間是否要即時StopIteration， 如 `text.splitlines()` 內存有目標行，generator 就會傳遞找到的結果給 `next()`， `next()` 這行就算執行完畢、generator 不會工作、不會繼續往後走訪。若目標行坐落於文本前半段，代表不需要看完整個文本，較有效率。<br>但如果都沒有目標行，最壞結果就是三次走訪都獨立完整地執行了三次。  |  `next(...)` 只要遇到第一個符合條件的行就會回傳並結束。  |
    |    2     |  只切分一次 `text.splitlines()`，並用一個迴圈走訪所有行。<br> |  不論文長多長，都只會走訪一次。但即使在第一行就找到了所有要的資訊，依然會硬生生把整個文本全部跑完，無法提早結束。  |  由於迴圈不會一找到就停下，所以每跑完每一行，後面的 `if line.startswith(...)` 可能會直接覆蓋掉前面已經存進 raw_note 、raw_tag 或是 hypothetical 的值。 |
    > **Conclusion:**  \
    > **Approach 1 比較 pythonic，但是 Approach 2 比較彈性可擴展其他運算需求。**  \
    > **適用場景: 如果很確定文本輸出必定會有一筆 ALIAS: / TAG: / HYPOTHETICAL:，且只想拿一筆， Approach 1 是比較簡潔的寫法。**

## 20260624 Work log
1. To well judge the model's answering quality in the production-like environment, changed the embedding models from text-only embedding model `text-embedding-3-small` to `Gemini-embedding-2` which was multimodal model.

2. The prospose change plan was appended to the chapter [增量-embeddingcdc成果task-01--task-06 in the branch summary](./branch_etl_pipeline_summary.md#增量-embeddingcdc成果task-01--task-06).

3. Refactored the pipeline of task06 to fit the required prompt format of `Gemini-embedding-2`.

4. Meanwhile, fixed the pending defection of `upsert` behavior to MongoDB atlas collection which might leave silo, broken, and obsoleted data chunks if the length of chunks had been shorten after re-embedding a revised text. As the [resulted script](../task06_obsidian_embed_etl/l_load_to_mongodb.py), `deleteMany and insert` behavior replaced `upsert`.The doc of `all` the embedded chunks pointed to the same note file path would be deleted from the collection `obsidian_vectors_multimodal` first. Then new chunks were inserted. This should prevent the broken chunks left in the vector database after multiple rounds of embedding tasks to a note text.

5. To save the requests to vertex AI API, [data capture change (CDC) approach](../task06_obsidian_embed_etl/l_load_to_mongodb.py) was implemented in refactoring. Only when the file on GCS was changed and the its embedding status in the collection `obsidian_notes` was not done (`embedding_done`=false) yet, the requests to Vertex AI API for embedding the text of the file would be performed. Otherwise, the requests would be skipped.

6. To accomplished the 3. & 4., the schema of collections `obsidian_summary` were revised. See the [revision in the branch_etl_pipeline_summary.md](branch_etl_pipeline_summary.md#mongodb-collections).

7. Installed the linter and formattor via `pre-commit` and `ruff`.

8. Updated the [hand-over of index creation](./task06_vctr_srch_idx_hand_over.md) to align the model type.

## 20260625 Work log
1. After changed the embedding model to multimodal models and migrate the collection of vector database from `obsidian_vectors` to `obsidian_vectors_multimodal`, the router and rag agents were tested again. This time key word search method was changed from `tags of note` to `file path of note` to avoid the context contamination in the follow-up questions in a session that was resulted by the less relevant tags of function `_extract_filter_tags()` inherited from the last question in the same session ([See Test case 2](#20260621-work-log)). In this change, inherited items was `file path of note from the last question`, I hope this could pinning the retreival scope in multi-run conversations with router,/rag agent. The testing materials included the `case 2 and case 3 ever used in 20260621 Work log` and one new case. The testing results were explained as follows.

| Run number in one session | User Query | Route to which Agent | Agent's response |  Why unexpected |
| ------------------------- | ---------- | ---------------- | ---------------- | --------------- |
| 1 | 查詢MySQL的Window function | rag | 根據您提供的筆記片段，以下是關於 MySQL Window Function 的資訊：<br>架構：<br>Window function 的架構主要包含： | ✅ router agent 執行 `extract_file_paths_via_alias` 找到兩份筆記：["MongoDB 與 MySQL 資料型態彙整兼比較.md", "MySQL Window Function.md"]，引導 rag agent 的 `vector search()`，這一輪回答同前面測試結果、能夠聚焦在 Window function 的解釋 |
| 2 | partition_clause 能否再講多一點  | rag | 根據您提供的筆記片段，以下是關於 `partition_clause` 的詳細說明.....`partition_clause` 的作用是定義資料表中的分區方式。當您指定了 `partition_clause` 後，MySQL 會將資料表分割成不同的區塊（或稱為「分區」）。接著，Window Function 會針對每一個獨立的分區， | ✅ router agent `_looks_like_followup()` 判斷屬於追問，繼承前次的兩份筆記，最後 Window function parition clause 留在 LLM 的回覆參考中，這一次 rag agent 的 `vector_search()` 計算後，取得的 top 5 chunk 都來自的 Window function 筆記，回答並無失焦、且無上下文污染。 |
| 3 | 有用到partition的範例 | rag | 您提供的筆記片段主要是在說明 Kafka 的 Partition 概念，而不是 MySQL 的  | ⚠️ router agent 不認為是追問，所以執行了`extract_file_paths_via_alias()`，重新搜索跟 query 相似的筆記，結果歪樓找到 Kafka 的 partition 主題筆記，導致 rag agent 的檢索範圍再度被新筆記 "Kafka - Partition、Replication、Segment、Cleanup.md" 污染|
| 4 | 你找看看 window function 的 cte 範例中是否有提過 partition | rag | 關於 MySQL Window Function 的 partition_clause，其作用是「資料表中的分區方式，分區完成後，MySQL 會針對分區後的每區塊，分別套用 window_function_name() 做運算。 | ❌ router agent 不知道這屬於追問，但靠著 user query 重新正面表述是 Window function 的 partition ，router 會執行 `02_knowledge_bases/MySQL Window Function.md` 找到精準筆記給 rag，但這樣正面表述法並不是每次都很符合人類的對話習慣。 |

- Testing case 3 for note querying and summarizing:

    | Run number in one session | User Query | Route to which Agent | Agent's response |  Why unexpected |
    | ------------------------- | ---------- | ---------------- | ---------------- | --------------- |
    | 1 | 我想要找容器化技術 | rag | 容器化技術的核心在於隔離應用程式及其依賴，.... | ✅ router agent 執行 `_r_hyde_rewrite()` 重寫查詢語句，且一併回傳'docker' tag 給 rag agent，接著 rag agent 基於 tag 但不侷限 note file path (因為是 router agent 程式邏輯導致)，找到了筆記["Docker - 專有名詞與概念.md"]，從而開始聚焦在 docker |
    | 2 | 找dev container  | rag | 根據您提供的筆記片段，以下是關於 Dev Container 的資訊...<br>定義與目的：... | ⚠️ router agent 不知道這屬於追問，直接執行 `extract_file_paths_via_alias` 找到兩份筆記["20260105 在 VS code 啟動Dev Container.md", "建置開發環境 - 使用 Dev container 與 Poetry 的差異.md"]，引導 rag agent 的 `vector search()` |
    | 3 | 進一步詢問怎麼開啟 Dev Container 使用 Claude Code | rag | 根根據您提供的筆記片段，目前沒有直接說明如何「開啟 Dev Container 使用 Claude Code」的具體步驟... | ❌ router agent 執行 `_extract_filter_path_via_alias()`找到兩份筆記["Claude Code 基本組成.md", "Claude Code Prompt 相關核心思維.md"]，提供給 rag agent 的 `vector search()`，`但問題是這兩份筆記不是正確來源`，所以 rag agent 拿到錯誤命中的資料且又被限縮只能在這兩份筆記中做搜尋。 rag agent 應該要檢索到 ["20260607 規格驅動開發 (SDD) - 用 Agent Skills 讓 AI 照著規格精準建置系統.md"] 這份筆記，然而這份筆記不論是file path 還是 tag 都沒有 dev container/container 的語意。 |

> Conclusion:
> 不論是 0621 還是 0625 用 file path 或 note tags 來作為 vector search 執行前的 prefilter，prefilter 本身就是雙面刃，雖然它在精準命中時能大幅提升回答品質、多輪對話中不會失焦，但在初始命中錯誤或漏掉時反而會把正確答案排除在外。

2. Changed previous the RAG flow:
    ```
    # 舊版:
    query
    │
    ├─ Router: intent 分類 (R1/R2)
    │    └─ 如果 rag_agent → 啟動 tag 抽取流程:
    │         ├─ Step A: _extract_filter_tags() ← 全庫 tag 字串比對
    │         ├─ Step 2A: _extract_tags_via_alias() ← alias 模糊比對
    │         ├─ Step 2B: _r_hyde_rewrite() ← HyDE + tag 推薦
    │         ├─ _looks_like_followup() + 繼承上輪 filter_tags/file_paths
    │         └─ Step 2C: 退化全庫搜索
    │
    ├─ vector_search(filter_tags=..., top_k=5) ← prefilter 硬排除
    │
    └─ LLM 生成回答

    # 5 層 tag 抽取邏輯互相干擾，debug 困難
    # prefilter 是 boolean 邏輯，tag/file_path 沒命中就把正確答案排除
    # 追問繼承機制傳遞錯誤 → 後續每輪都歪
    # 程式碼複雜度高（~350 行 router 邏輯）
    ```

    ```
    # 新版
    query + chat_history
        │
        ├─ Router: intent 分類 (R1/R2)  ← 職責單一化
        │
        └─ rag_query() 內部:
            │
            ├─ Step 3: Query Rewrite (帶 history)
            │    ├─ rewritten_query  → 獨立問句（給 reranker）
            │    ├─ expanded_query   → rewritten + tags（給 vector_search）
            │    └─ recommended_tags → 純記錄用
            │
            ├─ Step 4: vector_search(expanded_query, 無 prefilter, top_k=10)
            │
            ├─ Step 5: Cohere rerank(rewritten_query, top_n=5)
            │
            └─ Step 6: LLM 生成回答
    # 預期優勢：
    # Router 只做 intent，rag_agent 封裝所有 retrieval 邏輯
    # 不做 prefilter → 標籤缺失不會排除正確答案
    # Query expansion → 軟性增強語意信號（而非硬排除）
    # Reranker (cross-encoder) → 精準度遠高於 bi-encoder 向量距離
    # 追問自動處理 → rewrite 看 history 就能補全指代
    ```
3. RAG agent 新版整體流程
    ```
    query + chat_history (最近3輪)
            │
            ▼
    ┌──────────────────┐
    │  Query Rewrite   │  ← 一次 LLM call，看著 history 改寫成獨立問句
    │  (帶 history)     │     + 推薦 3-5 個 tags 做 query expansion（不做 prefilter）
    └──────────────────┘
            │
            ▼ expanded_query（改寫句 + tag 關鍵字）
    ┌──────────────────┐
    │  Vector Search   │  ← 不加 filter，top_k=10~15
    │  (無 prefilter)   │     讓向量語意自由匹配
    └──────────────────┘
            │
            ▼ 10~15 candidate chunks
    ┌──────────────────┐
    │  Cohere Rerank   │  ← cross-encoder 精排
    │                  │     用原始 query（不是 expanded），取 top 5
    └──────────────────┘
            │
            ▼ top 5 reranked chunks
    ┌──────────────────┐
    │  RAG Agent LLM   │  ← 生成最終回答
    │  (+ chat_history) │
    └──────────────────┘
    ```
4. Testing result:

- Testing case 1 for note querying and summarizing:

    | Run number in one session | User Query | Route to which Agent | Agent's response |  Why unexpected |
    | ------------------------- | ---------- | ---------------- | ---------------- | --------------- |
    | 1 | 幫我找NoSQL的CAP | rag | NoSQL 的 CAP 理論探討分散式架構下的三項權衡議題：Consistency... | ✅ router agent 執行 `_r1_keyword_match()` 導向 rag agent， rag rewrite 後 `幫我找CAP理論在分散式架構下的應用。` 推薦三個 tags，三個 tags 都是真實存在的 tags。 `vector search()` 後 `rerank` 語意相關度差距拉大，鑑別出最具查詢意圖的答案。 |
    | 1 | 找尋CAP  | rag | CAP理論探討分散式架構下的三項權衡議題，包含：Consistency (一致性)、Availability (可用性)、Partitioning Tolerance (分區容忍)。這三者不可能兼顧，最多只能滿足其中兩種。... | ✅ router agent 執行 `_r1_keyword_match()` 導向 rag agent， rag rewrite 後 `找CAP理論的相關筆記` 推薦兩個 tags，兩個 tags 都是真實存在的 tags。 `vector search()` 後 `rerank` 語意相關度差距拉大，鑑別出最具查詢意圖的答案。 |
    | 1 | CAP理論 | rag | 同上 | ✅ router agent 執行 `__r2_llm_classify()` 導向 rag agent， rag rewrite 後 `找CAP理論的相關筆記` 推薦兩個 tags，兩個 tags 都是真實存在的 tags。 `vector search()` 後 `rerank` 語意相關度差距拉大，鑑別出最具查詢意圖的答案。 |
    | 1 | 找尋cap理論筆記然後摘要理論的主張。 | rag | CAP理論主張，在分散式架構下，一致性（Consistency）、可用性（Availability）和分區容忍（Partitioning Tolerance）這三者不可能同時兼顧，最多只能同時滿足其中兩種。  | ✅ router agent 執行  `_r1_keyword_match()` 導向 rag agent， rag rewrite 後 `找CAP理論的相關筆記` 推薦兩個 tags，兩個 tags 都是真實存在的 tags。 `vector search()` 後 `rerank` 語意相關度差距拉大，鑑別出最具查詢意圖的答案。  |
    | 1 | find the note about 'cap-theorem' | rag | CAP 理論探討分散式架構下的三項權衡議題，包含：Consistency (一致性)、Availability (可用性)、Partitioning tolerance (分區容忍)。這三者不可能兼顧，之間只能滿足其中二種。 | ✅ router agent 執行 `__r2_llm_classify()` 導向 rag agent， rag rewrite 後 `find the note about 'cap-theorem'` 推薦兩個 tags，兩個 tags 都是真實存在的 tags。 `vector search()` 後 `rerank` 語意相關度差距拉大，鑑別出最具查詢意圖的答案。 |

- Testing case 2 for note querying and summarizing:

    | Run number in one session | User Query | Route to which Agent | Agent's response |  Why unexpected |
    | ------------------------- | ---------- | ---------------- | ---------------- | --------------- |
    | 1 | 查詢MySQL的Window function | rag | MySQL 的 Window function 架構主要包含 window_function_name(expression) OVER ([partition_clause], [order_clause], [frame_clause]) [new_column_name]。 | ✅ router agent 執行  `_r1_keyword_match()` 導向 rag agent， rag rewrite 後 `查詢MySQL的Window function...` 推薦4個 tags，4個 tags 都是真實存在的 tags。 `vector search()` 後 `rerank` 語意相關度差距拉大，鑑別出最具查詢意圖的答案。 |
    | 2 | partition_clause 能否再講多一點  | rag | partition_clause 用於資料表的分區方式，分區完成後，MySQL 會針對每個分區分別套用 window function 進行運算。 | ✅ router agent 執行  `_r1_keyword_match()` 導向 rag agent， rag rewrite 後 `查詢MySQL的Window function...` 推薦9個 tags，9個 tags 都是真實存在的 tags。 `vector search()` 後 `rerank` 語意相關度差距拉大，鑑別出最具查詢意圖的答案。 |
    | 3 | 我想要知道他的範例程式碼 | rag | 以下是關於 MySQL Window Function 的範例程式碼：範例 1：使用 DENSE_RANK() 進行排名，並透過 CTE 過濾出每個部門薪水前三名的員工 | ✅ router agent 執行 `__r2_llm_classify()` 導向 rag agent， rag rewrite 後 `MySQL Window function 的 partition_clause 的範例程式碼` 推薦9個 tags，9個 tags 都是真實存在的 tags。 `vector search()` 後 `rerank` 語意相關度差距拉大，鑑別出最具查詢意圖的答案。 |

- Testing case 3 for note querying and summarizing:

    | Run number in one session | User Query | Route to which Agent | Agent's response |  Why unexpected |
    | ------------------------- | ---------- | ---------------- | ---------------- | --------------- |
    | 1 | 我想要找容器化技術 | rag | Dev Container 是由微軟提供的 VS code 插件，它使用 Docker 容器化技術來定義一個標準化的開發環境，並讓 VS code IDE 直接在該環境中工作。 (來源 1)... | ⚠️ router agent 執行  `_r1_keyword_match()` 導向 rag agent， rag rewrite 後 `容器化技術` 推薦4個 tags，4個 tags 都是真實存在的 tags。 `vector search()` 後 `rerank` 語意相關度差距拉大，鑑別出最具查詢意圖的答案，但是回得有點狹隘，原因是資料庫對於 docker/k8s 這類通識型的的筆記量少於 dev container。 |
    | 2 | 進一步詢問怎麼開啟 Dev Container 使用 Claude Code | rag | 根據目前的筆記內容，無法提供詳細的步驟說明如何在 Dev Container 中開啟並使用 Claude Code。... | ✅ router agent 執行 `__r2_llm_classify()` 導向 rag agent， rag rewrite 後 `進一步詢問怎麼開啟 Dev Container 使用 Claude Code` 推薦16個 tags，16個 tags 都是真實存在的 tags。 `vector search()` 後 `rerank` 語意相關度差距拉大，鑑別出最具查詢意圖的答案。 |
    | 3 | 那繼續找 ，改找 20260607 規格驅動開發 (SDD) - 用 Agent Skills 讓 AI 照著規格精準建置系統.md這份筆記中是否有claude code 投用於 dev container的章節 | rag | 在「20260607 規格驅動開發 (SDD) - 用 Agent Skills 讓 AI 照著規格精準建置系統.md」這份筆記中，有提到如何讓 AI 參考 OpenSpec 來實作專案功能，其中包含「啟動 Claude Code」的步驟，但沒有直接說明將 Claude Code 投用於 Dev Container 的章節...不過，在另一份筆記「20260105 在 VS code 啟動Dev Container.md」中，有提到「在 Dev Container 中任意使用 Claude Code」，並參照「使用 Dev container 建置 Node 環境然後使用 Claude Code」。 (來源 5) 這兩份筆記片段可能暗示了將 Claude Code 與 Dev Container 結合使用的可能性，但具體的實作步驟或專門的章節在您提供的片段中並未出現。 | ✅ router agent 執行 `_r1_keyword_match()` 導向 rag agent， rag rewrite 後 `查詢 20260607 規格驅動開發 (SDD) - 用 Agent Skills 讓 AI 照著規格精準建置系統.md 這份筆記中是否有關於 Claude Code 應用於 Dev Container 的章節` 推薦16個 tags，16個 tags 都是真實存在的 tags。 `vector search()` 後 `rerank` 語意相關度差距拉大，但最高只有 0.7，不過模型仍給出一些可能的探索空間，所以可再追問一次。 |
    | 4 | 原來如此，那如果找「使用 Dev container 建置 Node 環境然後使用 Claude Code 」這個章節呢? 這章節裡面提到什麼全部列給我看 | rag | 根據您提供的筆記片段，關於「使用 Dev container 建置 Node 環境然後使用 Claude Code」這個主題，可以整理出以下資訊：<br>核心概念: 這部分內容是關於如何在 Dev Container 中建立 Node.js 開發環境，並能夠自由使用 Claude Code。 (來源 1, 來源 2)<br>參考資料: 提供了一個 GitHub 連結作為參考教材：https://github.com/deancourse/claude-code-docker-container-demo#。 (來源 3)<br>相關筆記: 提到了「20260105 在 VS code 啟動Dev Container」這份筆記。 (來源 1, 來源 2)...<br>目前提供的筆記片段中，沒有更詳細的步驟或內容說明具體如何在 Dev Container 中建置 Node.js 環境並使用 Claude Code，僅提及了這個主題、一個參考連結以及相關的筆記名稱。 | ✅ rag agent 這次回答得十分貼近筆記內文真實的面貌，測試通過。 |

## 20260701 Work log
1. Initiate the task07 with lazy loading in the branch `feature/html-to-markdown` based on the requirement changes description in [task07_onenote_versioned_etl_hand_over_v2](./task07_onenote_versioned_etl_hand_over_v2.md). New goal in the task07 was "implementation of the incremental loads for the raw notes of OneNote app and keeping the historical versions available", and "open the LLM call for document enrichment being triggered on demand to reduce the waste of token".
> In previous task07, the historical versions of note from OneNote cannot be accessible unless using GCS versioning control; However, the latter one could not be easily read and check directly on GCP console. So, the [variants](../task07_onenote_to_markdown_lazy_loading/) of original task07 was created in this branch.

2. To meet the new goals, the schema of collections in this task07 was also revised to carefully make sure the data lineage and datalogs. New schema definition also referred to [task07_onenote_versioned_etl_hand_over_v2](./task07_onenote_versioned_etl_hand_over_v2.md).

3. Start to implement the codes against the hand-over, the learning notes from this part was written as follows.

- MSAL module
    ```python
    """Procedure:
    1. 連線應用程式中心後，優先嘗試自動更新 (用 Refresh Token 換新的 Access Token)
    2. 失敗時才提示登入（Device Flow）取得新 Token。
    3. 最後存檔將 Token 持久化，以利下次能自動更新。
    """
    import msal
    from pathlib import Path

    def _build_msal_app() -> tuple[msal.PublicClientApplication,
                                    msal.SerializableTokenCache]:
        """建立可快取物件 cache 與 Microsoft 應用程式物件 app。不回傳 token。

        此函式會自動檢查全域變數 CACHE_PATH (Path 物件) 是否存在，
        若存在則會讀取並載入先前的快取紀錄。

        **Notes**:
            此函式本身不會將更新後的快取寫回硬碟，呼叫端需自行負責後續儲存。

        Returns:
            tuple[msal.PublicClientApplication, msal.SerializableTokenCache]:
                傳回設定好的 MSAL 應用程式實例與 Token 快取物件。
        """
        # 建立可被序列化（也就是能轉成文字存成檔案）的快取物件 cache
        cache = msal.SerializableTokenCache()
        # 檢查指定的路徑（CACHE_PATH, Path 物件）下有沒有先前存好的快取檔案
        # 本機測試可以考慮把 CACHE_PATH 建在 ~/.config/ 下
        if CACHE_PATH.exists():
            # 用 .deserialize() 把裡面的文字資料讀進記憶體的快取物件
            cache.deserialize(CACHE_PATH.read_text())

        # 建立 PublicClientApplication 物件
        # CLIENT_ID 為應用程式註冊識別碼，AUTHORITY 為微軟的身分驗證中心網址
        app = msal.PublicClientApplication(CLIENT_ID, authority=AUTHORITY, token_cache=cache)
        return app, cache

    def get_token() -> tuple[str,
                            msal.PublicClientApplication,
                            msal.SerializableTokenCache]:
        """Acquire access token; triggers device-flow login when no cached token exists."""

        # 1. 建立應用程式物件、快取物件
        app, cache = _build_msal_app()

        # 2. 從應用程式的快取中尋找是否有記錄著使用者帳號
        accounts = app.get_accounts()

        # 3. 嘗試在背景自動取得 Token。若有快取帳號且 Access Token 已過期，會自動用 Refresh Token 刷新。
        result = app.acquire_token_silent(SCOPES, account=accounts[0]) if accounts else None

        # 4. 如果無法在背景靜態取得 Token（無帳號或快取提前失效），則觸發互動式登入
        if not result:

            # 啟動裝置驗證流程 (Device Flow)
            # initiate_device_flow() 跟 acquire_token_by_device_flow() 配合使用
            flow = app.initiate_device_flow(scopes=SCOPES)
            if "user_code" not in flow:
                logger.error(f"Device flow initiation failed: {flow}")
                sys.exit(1)
            print("\n" + flow["message"])
            print("等待瀏覽器授權完成...")
            result = app.acquire_token_by_device_flow(flow)

        # 5. 將最新的快取狀態序列化，寫回硬碟檔案中（確保下次能靜態自動更新）
        CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        CACHE_PATH.write_text(cache.serialize())

        # 6. 若最後仍未成功取得 access_token，終止程式並記錄錯誤訊息
        if "access_token" not in result:
            logger.error(f"Auth failed: {result.get('error_description', result)}")
            sys.exit(1)

        return result["access_token"], app, cache
    ```
    > 可思考的是，這2支函式每次執行都只能在地端 CLI 手動觸發跑，如果需要設計成 Web 服務讓使用者到彈出式瀏覽器打開做第一次登入授權，然後第二次開始都自動化啟動函式且更新 token，則這 2 個函式的授權策略與金鑰存放地點需要改動。
    > 但是 OneNote Graph API 自 2025 年起已經不支持採用 Client Credentials flow 驗證機制的 app-only authentication。需由人做 delegated authentication。
- Slide Window 演算法做 API Ratelimiter
    ```python
    """核心設計：
    1. 閱讀官方說明確認 rate-limit rule
    2. 設計 rate buffer 空間
    3. 用 deque() 管理一段時間窗口內實際發生的請求時間點，失效的時間點不納入佇列
    4. Sliding-window 計算要等多久來達到重置時間點。
    5. 用 time.sleep() 暫停請求，直到跨過重置時間點。
    """
    class RateLimiter:
    """Sliding-window (滑動窗口演算法) limiter enforcing OneNote API caps (120/min, 400/hour)."""

    def __init__(self, per_minute: int = 115, per_hour: int = 380):
        self.per_minute = per_minute
        self.per_hour = per_hour
        self._min_q = deque()  # 紀錄一分鐘內的請求時間
        self._hour_q = deque()  # 紀錄一小時內的請求時間

    def acquire(self):
        while True:
            now = time.time()
            while self._min_q and now - self._min_q[0] > 60:
                self._min_q.popleft()
            while self._hour_q and now - self._hour_q[0] > 3600:
                self._hour_q.popleft()
            wait = 0
            if len(self._min_q) >= self.per_minute:
                # 預測下一次重置請求量的時間點，且扣除現在時間點，即可得到還要等多久才能觸達重置時間點。
                wait = max(wait, self._min_q[0] + 60 - now)
            if len(self._hour_q) >= self.per_hour:
                wait = max(wait, self._hour_q[0] + 3600 - now)
            if wait <= 0:
                break
            logger.info(f"[rate limiter] waiting {wait:.1f}s "
                        f"(min={len(self._min_q)}/115, hour={len(self._hour_q)}/380)")
            # time.sleep() 實際表現出來的睡眠時間長度會有浮點數誤差，+0.05 以確保迴圈下一輪一定可以走到 break
            time.sleep(wait + 0.05)
        now = time.time()
        self._min_q.append(now)
        self._hour_q.append(now)
    ```
- `api_get()` 的錯誤處理：從「先成功、再看 status_code」改為 try/except 分層 + timeout，並釐清 onenote_graph_api_logs 的 log 寫入責任
    ```python
    """學到的重點：
    1. requests.get() 若沒設 timeout，遇到伺服器 hang 住不回應時會「無限等待」，
       連 requests.exceptions.Timeout 都不會被拋出——所以 timeout 是讓後續捕捉能生效的前提。
    2. 「有回應但狀態碼不好 (401/429/5xx)」和「連請求都送不出去 (連線逾時、DNS 失敗、
       連線被 reset、endpoint 壞掉)」是兩種不同層次的錯誤，要分開接。
    3. 4xx 裡除了 401/429 之外 (如 400/403/404) 屬於非暫時性錯誤，重試 10 次也不會變好，
       應寫一筆 log 後直接往上拋，不浪費配額。
    4. log 寫在哪一層要想清楚：同一次失敗如果內層 (api_get) 與外層 (download_notebooks)
       都各寫一次 onenote_graph_api_logs，會產生重複列，且外層用 status_code=0 反而蓋掉內層真實的狀態碼。
    """
    ```
    - **修改前**：先 `r = requests.get(...)` 拿到回應物件，再用一連串 `if r.status_code == 401 / 429 / >=500` 判斷。
        ```python
        r = requests.get(url, headers=headers, stream=binary)   # ← 沒有 timeout
        latency_ms = int((time.perf_counter() - t0) * 1000)
        if r.status_code == 401 and not token_refreshed: ...
        if r.status_code == 429: ...
        if r.status_code >= 500: ...
        r.raise_for_status()
        return r
        ```
        > 盲點：只要 `requests.get()` 這一行本身在傳輸層就噴例外 (Timeout / ConnectionError / DNS 解析失敗 / endpoint 壞掉)，程式根本走不到後面的 `r.status_code`，例外會直接穿透整個 `for attempt in range(1, 11)` 重試迴圈往上拋，**既不重試、也不留 log**。再加上沒設 timeout，伺服器 hang 住時會卡死。
    - **修改後**：把 `requests.get()` 包進 `try`，並加 `timeout=REQUEST_TIMEOUT`；用 `r.raise_for_status()` 把非 2xx 統一轉成 `HTTPError`，再分兩層 `except` 接。
        ```python
        REQUEST_TIMEOUT = (10, 60)  # (connect, read) 秒

        for attempt in range(1, 11):
            try:
                r = requests.get(url, headers=headers, stream=binary, timeout=REQUEST_TIMEOUT)
                latency_ms = int((time.perf_counter() - t0) * 1000)
                r.raise_for_status()          # 非 2xx → 拋 HTTPError
                return r
            except requests.exceptions.HTTPError as e:
                r = e.response                # 從例外物件取回 response
                status_code = r.status_code
                if status_code == 401 and not token_refreshed: ...   # 換 token 重試
                elif status_code == 429: ...                          # 退避重試
                elif status_code >= 500: ...                          # 退避重試
                else:                                                 # 其他 4xx
                    log_api_call(..., status_code=status_code, ...)
                    raise                     # 不重試，直接拋
            except requests.exceptions.RequestException as e:
                # Timeout / ConnectionError / DNS 失敗等傳輸層錯誤
                log_api_call(..., status_code=0, error_msg=str(e))    # status_code=0 代表沒拿到回應
                time.sleep(2 ** attempt * 5)  # 指數退避後重試
                continue

        # retry 耗盡：補一筆「收尾列」再拋 RuntimeError，讓 api_get 成為 onenote_graph_api_logs 的完整單一來源
        log_api_call(..., status_code=0, error_msg=f"Request failed after 10 retries: {url}")
        raise RuntimeError(f"Request failed after 10 retries: {url}")
        ```
        > 差異總結：(1) `HTTPError` 是 `RequestException` 的子類別，所以 `except HTTPError` 一定要放在 `except RequestException` 前面，否則傳輸層以外的 HTTP 錯誤會被前者攔截後就進不到分流；(2) 傳輸層錯誤時可能連 `r` 都沒有，log 用 `status_code=0` 標記「沒有回應」，並把 `latency_ms` 重算到出錯當下；(3) 只有 401/429/5xx 與傳輸層錯誤會 `continue` 重試，其餘 4xx 直接 `raise`。
    - **踩到的坑：重複的 log**。`download_notebooks()` 呼叫 page content 那一支 `api_get()` 時用 `try/except Exception` 包住。原本 except 裡「又」寫了一筆 `log_api_call(..., status_code=0)`，於是一次 4xx 失敗會在 onenote_graph_api_logs 產生 **2 筆**：內層 api_get 已寫過正確 `status_code` (如 404)，外層再寫一筆 `status_code=0`，反而把真實狀態碼蓋掉、也誤導判讀。
        ```python
        # download_notebooks() 內：只保留 onenote_graph_api_logs (page 層狀態)，不再寫 onenote_graph_api_logs
        try:
            raw_html = api_get(..., page_id=page_id).text
        except Exception as e:
            # C1 request 層 log 已由 api_get() 內部 (逐次 attempt + 收尾列) 完整寫過，
            # 這裡只記 onenote_graph_api_logs 的 page 層狀態，避免重複寫 C1、也避免 status_code=0 蓋掉真實碼
            upsert_version_meta(page_id, dt,
                                set_fields={..., "status": "fetched_failed", "error_msg": str(e)})
            continue
        ```
        > 職責分離結論：**C1 (request 層稽核) 全歸 `api_get()`**——逐次 attempt 失敗 + 4xx/retry 耗盡的收尾列都在這寫；**C3 (page 層生命週期) 全歸 `download_notebooks()`**——只記 `status=fetched_failed`。這樣同一次失敗在 C1 不再重複，「這頁最終失敗」在 C1 (收尾列) 與 C3 (fetched_failed) 各有對應、可交叉追溯。
- `request_id` 該由誰生成：注入 (往下傳) 而非回傳 (往上拿)
    ```python
    """學到的重點：
    1. request_id 的語意是「同一個邏輯請求 (含其 retry) 共用一個 ID」，
       用來把 C1 裡分散的多筆列 join 回同一次請求。
    2. api_get() 內部的「失敗 attempt log」是在『執行中、還沒 return 之前』就寫進 C1 的，
       所以 request_id 必須在『進入 api_get 的當下』就已確定——這是選型的決定性條件。
    3. api_get() 會 raise (4xx / retry 耗盡 / token 刷新失敗)，raise 時沒有回傳值。
    """
    ```
    - **情境**：`download_notebooks()` 在 `api_get()` 成功拿到 `raw_html` 後，還會在外面補寫「hash 未變動跳過」或「新版本已存」的結果列。這些結果列與 api_get 內部的失敗 attempt 列，本質上都是「同一次請求」的衍生，理應共用同一個 request_id 才能 join。
    - **為何不用「回傳式」`return response, request_id` 讓外部 unpack**：
        - (a) **raise 死穴**：api_get 一旦 raise 就沒有回傳值，呼叫端在**失敗時拿不到** request_id；但要關聯 log 最需要 ID 的時機恰恰是失敗時。要補救得自訂例外把 id 塞進 exception 帶出，machinery 變多、職責更糊。
        - (b) **時序兜不起來**：失敗 attempt 列是 mid-call 當下就寫的，若等 api_get 結束才回傳 id，那些列早已用某個 id 寫進去、呼叫端事後才知道，順序上對不上 (何況失敗根本 return 不到)。
        - (c) **破壞 fluent 串接**：現在各處是 `api_get(...).text` / `.json()` / `.content` 直接鏈；改回傳 tuple 後連 listing、圖片這些不在乎 id 的呼叫都被迫 `resp, rid = api_get(...)`。
    - **採用「注入式」**：request_id 由呼叫端 (= 一個 page 的邏輯操作範圍) 先生成，再傳進 api_get 共用；api_get 只是**繼承**這個 context，不是它的擁有者。它預設仍自己生成 (`request_id = request_id or uuid.uuid4().hex[:12]`)，只有「結果要在 api_get 外面被補記 log」的 page content 呼叫才注入。
        ```python
        # api_get(): 省略則自生成；呼叫端有傳就共用
        def api_get(..., request_id: str | None = None):
            request_id = request_id or uuid.uuid4().hex[:12]

        # download_notebooks(): page 層先生成，注入 content 呼叫，結果列共用同一 id
        request_id = uuid.uuid4().hex[:12]
        raw_html = api_get(..., page_id=page_id, request_id=request_id).text
        ...
        log_api_call(..., request_id=request_id, status="success", downloaded=False)  # 掛同一 id
        ```
        > 這就是 dependency injection 的味道：把「上下文」往下傳、而不是往上回傳。反面案例 (listing、`_store_images` 的圖片呼叫) 各自是獨立邏輯請求，本來就該有自己的 id，所以**不注入**、讓 api_get 自生成——「不同 url endpoint 不同 request_id」正是預期行為。

- `PurePosixPath()` vs. `Path()` 解析 URI 字串
    - Path() 下面有兩個子類別 PosixPath() 與 WindowsPath()，建立 Path() 物件時，會自動根據機器的文件系統來建立出 PosixPath 類別或 WindowsPath，像是 Mac 系統就會建成 PosixPath 類別:
    ```python
        from pathlib import Path
        print(type(Path.home()))
        # 在 Mac 上執行的話就會出現 <class 'pathlib.PosixPath'>
    ```
    - PurePosixPath() 則是一律用 Posix 規則來解析傳入的路徑字串，不會因為作業系統差異而解析不同。底層運作也不涉及任何文件檔案系統 (不會調用 resolve 等)，純粹是解析字串。當要解析的字串本身是帶有冒號之類的路徑字串時，例如: URI 字串，PurePosixPath() 不隨作業系統而有解析差異。
    ```python
        from pathlib import Path
        Path("s3://bucket/key.jpg").suffix # 輸出 '.jpg'  在 Linux/Mac 上没问题，但在 Windows 可能會把 s3: 理解為盤符。
        PurePosixPath("s3://bucket/key.jpg")  # 就沒有差異了，不論什麼系統都用 Posix 解析，而 URI 本身也是遵循 Posix 規則。
    ```
4. Established the ETL scripts of task07 with lazy loading, named as [`task07_onenote_to_markdown_lazy_loading`](../task07_onenote_to_markdown_lazy_loading/) to distinguish from the previous task07. Since T and L task would be triggered on demand in frontend UI, their python scripts will be delivered to the `branch feature/dashboard-ui` for integration.

## 20260702 Work log
1. Switched to the branch feature/dashboard-ui and established the new page [`onenote_versioned_review`](../dashboard_ui/pages/onenote_versioned_review.py) using python streamlit module. The web page utilized [`silver_service`](../silver_service/app.py) endpoint using python flask module to realize the document enrichment by LLM call on-demand.

2. Questions when practing 1. were noted down as follows. Some of them were not actually faced problems but predicted by myself.

- What will happen if user logged in the web page and selected one of notes to started human review process but in the meanwhile the bronze layer task (downloading the latest html note from OneNote graph API) ran as scheduled? What is the impact on the collection `onenote_note_metadata` in MongoDB Atlas database when reading (to render frontend) and writting (to save metadata of new downloaded note)?

- Timeout in regeneraton step may happen if the image size is larger.
```bash
2026-07-02 14:50:50.520 | WARNING  | task07_onenote_to_markdown_lazy_loading.t_enrich_html_to_markdown:t_enrich_html_to_markdown:387 - [enrich failed] Untitled: No JSON in response: None

2026-07-02 14:50:50.523 | INFO     | __main__:enrich:61 - [silver] enrich: page_id=0-b43f9de7dc534591aefa34e1f6fb45b7!1-A5F7F5395D4FB9F!209, dt=2026-07-02, trigger=regenerate → enrich_failed
```

- Guard of LLM call quota work normally.
```bash
127.0.0.1 - - [02/Jul/2026 14:58:07] "POST /enrich HTTP/1.1" 200 -
2026-07-02 15:00:23.330 | WARNING  | task07_onenote_to_markdown_lazy_loading.t_enrich_html_to_markdown:t_enrich_html_to_markdown:305 - [regenerate] html_hash=e32f98dc 已達上限 2 次

2026-07-02 15:00:23.330 | INFO     | __main__:enrich:61 - [silver] enrich: page_id=0-0849dd0b84ac43de85e1707f7dcdaaf6!1-A5F7F5395D4FB9F!209, dt=2026-07-01, trigger=regenerate → pending_review
```

- 針對"生技製劑筆記本/General Technical Knowledge/Saline"筆記測試:
1. 下拉式清單點選該筆記後，頁面成功顯示這份筆記屬於哪個分區 (=哪一天透過 bronze 上傳到GCS的)，且顯示尚未LLM 生成筆記 ("🟠 未生成")。
2. 接著網頁確實自動 calling LLM，成功生成後，四處地點的顯示結果如下：
    - terminal logger
    ```bash
    2026-07-02 15:06:45.710 | INFO     | task07_onenote_to_markdown_lazy_loading.l_save_markdown:save_enriched_md:24 - 💾 Silver md 已存 → gs://onenote-vaults/processed-notes/lucky460721/生技製劑筆記本/General technical knowledge/dt=2026-07-01/Saline.md

    2026-07-02 15:06:45.728 | SUCCESS  | task07_onenote_to_markdown_lazy_loading.t_enrich_html_to_markdown:t_enrich_html_to_markdown:408 - enriched Saline（5726 tokens）

    2026-07-02 15:06:45.729 | INFO     | __main__:enrich:61 - [silver] enrich: page_id=0-83a74cd3c68a48f284ac9ea148398247!1-A5F7F5395D4FB9F!209, dt=2026-07-01, trigger=on_demand → pending_review
    ```

    - Streamlit 網頁跳出 LLM 生成的 Markdown ，狀態改為
    ```plaintext
    版本（同名筆記的各 dt= 分區）
    dt=2026-07-01　(2026-07-01 08:11:49)　✅ 已生成
    ```

    - MongoDB Atlas Collection 'multimodal_llm_enrichment_logs':
    ```json
        {
        "_id" : ObjectId("6a460e05a007164164223750"),
        "page_id" : "0-83a74cd3c68a48f284ac9ea148398247!1-A5F7F5395D4FB9F!209",
        "html_hash" : "5d33e85769205d10ef099ac4a5b65a989248aa06ea572b5a3f716e0974ee8479",
        "timestamp" : ISODate("2026-07-02T07:06:45.605+0000"), // 確實是生成日的 UTC 時間
        "event_type" : "llm_enrichment_call",
        "model" : "gemini-2.5-flash",
        "cache_hit" : false,
        "trigger" : "on_demand",
        "status" : "success",
        "latency_ms" : NumberInt(21107),
        "input_tokens" : NumberInt(2636),
        "output_tokens" : NumberInt(948),
        "total_tokens" : NumberInt(5726),
        "environment" : "local",
        "error_msg" : null
    }
    ```
    - MongoDB Atlas Collection 'onenote_note_metadata':
    ```json
        {
        "_id" : ObjectId("6a44cbc5bf6e2cc35fab29a5"),
        "dt" : "2026-07-01",
        "page_id" : "0-83a74cd3c68a48f284ac9ea148398247!1-A5F7F5395D4FB9F!209",
        "archived_at" : null,
        "embedded_status" : false,
        "error_msg" : null,
        "html_downloaded_at" : ISODate("2026-07-01T08:11:49.956+0000"), // 時間與前端網頁顯示時間相同
        "html_hash" : "5d33e85769205d10ef099ac4a5b65a989248aa06ea572b5a3f716e0974ee8479",
        "html_md5" : "YP6j+D7gFLTq300UF+q31g==",
        "html_path" : "gs://onenote-vaults/raw-notes/lucky460721/生技製劑筆記本/General technical knowledge/dt=2026-07-01/Saline.html",
        "img_archive_path" : null,
        "img_md5" : [
            "eAgL7P1I8PpfbM4Dtpqc0g=="
        ],
        "img_path" : [
            "gs://onenote-vaults/raw-notes/lucky460721/生技製劑筆記本/General technical knowledge/dt=2026-07-01/_images/0-d90534f90272456eb72715e96c0d6d80!1-A5F7F5395D4FB9F!209.png"
        ],
        "md_archive_path" : null,
        "md_exported_at" : ISODate("2026-07-02T07:06:45.711+0000"), // 確實排在 LLM 回應給 silver_serivce 後。
        "md_md5" : "Whtn34q7R+K2s+mU+lhHVg==",  // 如實寫入
        "md_path" : "gs://onenote-vaults/processed-notes/lucky460721/生技製劑筆記本/General technical knowledge/dt=2026-07-01/Saline.md",  // 路徑正確
        "notebook" : "生技製劑筆記本",
        "onenote_user_id" : "lucky460721",
        "page_title" : "Saline",
        "review_result" : null,
        "reviewed_at" : null,
        "reviewed_by_role" : null,
        "section" : "General technical knowledge",
        "status" : "pending_review"  // 生成後進入 review 關卡
        }
    ```
3. 故意點選 `regenerate` 觸發再生成後，上面提及的四個地點變成:

    - terminal logger
    ```bash
        2026-07-02 15:33:33.463 | INFO     | task07_onenote_to_markdown_lazy_loading.l_save_markdown:save_enriched_md:24 - 💾 Silver md 已存 → gs://onenote-vaults/processed-notes/lucky460721/生技製劑筆記本/General technical knowledge/dt=2026-07-01/Saline.md

        2026-07-02 15:33:33.482 | SUCCESS  | task07_onenote_to_markdown_lazy_loading.t_enrich_html_to_markdown:t_enrich_html_to_markdown:408 - enriched Saline（6459 tokens）

        2026-07-02 15:33:33.484 | INFO     | __main__:enrich:61 - [silver] enrich: page_id=0-83a74cd3c68a48f284ac9ea148398247!1-A5F7F5395D4FB9F!209, dt=2026-07-01, trigger=regenerate → pending_review
    ```

    - Streamlit 網頁自動刷新為 LLM 再版的 Markdown，狀態改為
    ```plaintext
    版本（同名筆記的各 dt= 分區）
    dt=2026-07-01　(2026-07-01 08:11:49)　✅ 已生成
    ```

    - MongoDB Atlas Collection 'multimodal_llm_enrichment_logs':
    ```json
        // {"_id" : ObjectId("6a460e05a007164164223750"),....} 第一筆尚在
        // 新增第二筆如下：
        {
        "_id" : ObjectId("6a46144da007164164223751"),
        "page_id" : "0-83a74cd3c68a48f284ac9ea148398247!1-A5F7F5395D4FB9F!209",
        "html_hash" : "5d33e85769205d10ef099ac4a5b65a989248aa06ea572b5a3f716e0974ee8479",
        "timestamp" : ISODate("2026-07-02T07:33:33.353+0000"),
        "event_type" : "llm_enrichment_call",
        "model" : "gemini-2.5-flash",
        "cache_hit" : false,
        "trigger" : "regenerate",
        "status" : "success",
        "latency_ms" : NumberInt(22884),
        "input_tokens" : NumberInt(2636),
        "output_tokens" : NumberInt(843),
        "total_tokens" : NumberInt(6459),
        "environment" : "local",
        "error_msg" : null
        }
    ```

    - MongoDB Atlas Collection 'onenote_note_metadata':
    ```json
        {
        "_id" : ObjectId("6a44cbc5bf6e2cc35fab29a5"),
        "dt" : "2026-07-01",
        "page_id" : "0-83a74cd3c68a48f284ac9ea148398247!1-A5F7F5395D4FB9F!209",
        "archived_at" : null,
        "embedded_status" : false,
        "error_msg" : null,
        "html_downloaded_at" : ISODate("2026-07-01T08:11:49.956+0000"), // 時間與前端網頁顯示時間相同
        "html_hash" : "5d33e85769205d10ef099ac4a5b65a989248aa06ea572b5a3f716e0974ee8479",
        "html_md5" : "YP6j+D7gFLTq300UF+q31g==",
        "html_path" : "gs://onenote-vaults/raw-notes/lucky460721/生技製劑筆記本/General technical knowledge/dt=2026-07-01/Saline.html",
        "img_archive_path" : null,
        "img_md5" : [
            "eAgL7P1I8PpfbM4Dtpqc0g=="
        ],
        "img_path" : [
            "gs://onenote-vaults/raw-notes/lucky460721/生技製劑筆記本/General technical knowledge/dt=2026-07-01/_images/0-d90534f90272456eb72715e96c0d6d80!1-A5F7F5395D4FB9F!209.png"
        ],
        "md_archive_path" : null,
        "md_exported_at" : ISODate("2026-07-02T07:33:33.463+0000"), // 刷新了，上一版的被覆蓋
        "md_md5" : "I04xzLBR9j0ryj9COqVdCQ==", // 刷新了，上一版的被覆蓋
        "md_path" : "gs://onenote-vaults/processed-notes/lucky460721/生技製劑筆記本/General technical knowledge/dt=2026-07-01/Saline.md",  // 路徑正確，但也導致上一版的被覆蓋
        "notebook" : "生技製劑筆記本",
        "onenote_user_id" : "lucky460721",
        "page_title" : "Saline",
        "review_result" : null,
        "reviewed_at" : null,
        "reviewed_by_role" : null,
        "section" : "General technical knowledge",
        "status" : "pending_review"  // 生成後進入 review 關卡
        }
    ```

4. 第二次故意點選 `regenerate` 觸發再生成後，上面提及的四個地點:

    - terminal logger
    ```bash
    2026-07-02 15:47:16.594 | INFO     | task07_onenote_to_markdown_lazy_loading.l_save_markdown:save_enriched_md:24 - 💾 Silver md 已存 → gs://onenote-vaults/processed-notes/lucky460721/生技製劑筆記本/General technical knowledge/dt=2026-07-01/Saline.md

    2026-07-02 15:47:16.610 | SUCCESS  | task07_onenote_to_markdown_lazy_loading.t_enrich_html_to_markdown:t_enrich_html_to_markdown:408 - enriched Saline（6161 tokens）

    2026-07-02 15:47:16.612 | INFO     | __main__:enrich:61 - [silver] enrich: page_id=0-83a74cd3c68a48f284ac9ea148398247!1-A5F7F5395D4FB9F!209, dt=2026-07-01, trigger=regenerate → pending_review
    ```

    - Streamlit 網頁自動刷新為 LLM 再版的 Markdown，狀態改為
    ```plaintext
    版本（同名筆記的各 dt= 分區）
    dt=2026-07-01　(2026-07-01 08:11:49)　✅ 已生成
    ```

    - MongoDB Atlas Collection 'multimodal_llm_enrichment_logs':
    ```json
        // {"_id" : ObjectId("6a460e05a007164164223750"),....} 第一筆尚在
        // {"_id" : ObjectId("6a460e05a007164164223750"),....} 第二筆尚在
        // 新增第三筆如下：
        {
        "_id" : ObjectId("6a461784a007164164223752"),
        "page_id" : "0-83a74cd3c68a48f284ac9ea148398247!1-A5F7F5395D4FB9F!209",
        "html_hash" : "5d33e85769205d10ef099ac4a5b65a989248aa06ea572b5a3f716e0974ee8479",
        "timestamp" : ISODate("2026-07-02T07:47:16.488+0000"),
        "event_type" : "llm_enrichment_call",
        "model" : "gemini-2.5-flash",
        "cache_hit" : false,
        "trigger" : "regenerate",
        "status" : "success",
        "latency_ms" : NumberInt(20751),
        "input_tokens" : NumberInt(2636),
        "output_tokens" : NumberInt(982),
        "total_tokens" : NumberInt(6161),
        "environment" : "local",
        "error_msg" : null
        }
    ```

    - MongoDB Atlas Collection 'onenote_note_metadata':
    ```json
        {
        "_id" : ObjectId("6a44cbc5bf6e2cc35fab29a5"),
        "dt" : "2026-07-01",
        "page_id" : "0-83a74cd3c68a48f284ac9ea148398247!1-A5F7F5395D4FB9F!209",
        "archived_at" : null,
        "embedded_status" : false,
        "error_msg" : null,
        "html_downloaded_at" : ISODate("2026-07-01T08:11:49.956+0000"), // 時間與前端網頁顯示時間相同
        "html_hash" : "5d33e85769205d10ef099ac4a5b65a989248aa06ea572b5a3f716e0974ee8479",
        "html_md5" : "YP6j+D7gFLTq300UF+q31g==",
        "html_path" : "gs://onenote-vaults/raw-notes/lucky460721/生技製劑筆記本/General technical knowledge/dt=2026-07-01/Saline.html",
        "img_archive_path" : null,
        "img_md5" : [
            "eAgL7P1I8PpfbM4Dtpqc0g=="
        ],
        "img_path" : [
            "gs://onenote-vaults/raw-notes/lucky460721/生技製劑筆記本/General technical knowledge/dt=2026-07-01/_images/0-d90534f90272456eb72715e96c0d6d80!1-A5F7F5395D4FB9F!209.png"
        ],
        "md_archive_path" : null,
        "md_exported_at" : ISODate("2026-07-02T07:47:16.595+0000"), // 刷新了，再次被覆蓋
        "md_md5" : "teDegRXTRtwy/E55hLVrSA==", // 刷新了，上一版的被覆蓋
        "md_path" : "gs://onenote-vaults/processed-notes/lucky460721/生技製劑筆記本/General technical knowledge/dt=2026-07-01/Saline.md",  // 路徑正確，但也導致上一版的被覆蓋
        "notebook" : "生技製劑筆記本",
        "onenote_user_id" : "lucky460721",
        "page_title" : "Saline",
        "review_result" : null,
        "reviewed_at" : null,
        "reviewed_by_role" : null,
        "section" : "General technical knowledge",
        "status" : "pending_review"  // 生成後進入 review 關卡
        }
    ```

5. 第三次故意點選 `regenerate` ，跳出 `regenerate quota exceeded`，正確擋下 regenerate 需求。
    - 故意切到其他筆記後再點選一次 `regenerate`，仍然正確地擋下 regenerate 需求。
    - 重新整理頁面，再登入一次後，點選 `regenerate`，仍然正確地擋下 regenerate 需求。
    - Terminal logger 輸出如下:

    ```bash
        2026-07-02 16:00:45.443 | WARNING  | task07_onenote_to_markdown_lazy_loading.t_enrich_html_to_markdown:t_enrich_html_to_markdown:305 - [regenerate] html_hash=5d33e857 已達上限 2 次

        2026-07-02 16:00:45.443 | INFO     | __main__:enrich:61 - [silver] enrich: page_id=0-83a74cd3c68a48f284ac9ea148398247!1-A5F7F5395D4FB9F!209, dt=2026-07-01, trigger=regenerate → pending_review
    ```

6. 針對初步測試總結似乎可以優化的地方：
    - 大檔案的 `regenerate` 會 timeout 失敗
    - LLM 生成時所套的 tags 是基於他的訓練資料來生成，長遠來看，客製化的向量資料庫是不是應該要餵給他 tags references set，以確保他可以為 enriched content 挑 tags 時，有一定的比例是符合企業文化的關鍵字、另外比例則是仰賴生成技術為企業潛在的資訊/知識冰山做紀錄。
    > 跟 CLAUDE Opus 4.8 CHAT 討論後:
    > 第一: rewriter model 的工作流目前是每一輪都要「看著整份 tag 清單」來挑推薦與重寫查詢語句。清單就是它的 per-query 輸入，如果 tags 基數爆炸，trade-off 就是每輪 token 變貴、嚴重者 attention 被稀釋，要從幾千個 tag (其中可能有一堆只出現一次的噪音) 裡挑出對的幾個，讓查詢品質掉。
    > 第二: 語意漂移會稀釋 tag 本來要給的「集中效應」。 tag 之所以能拉高 recall,靠的是同一概念被一致地、重複地標記,把語意質量集中到一個點,讓改寫後的查詢向量能被拉進那一區。一旦 k8s / kubernetes / 容器編排 散成三個,這個「重複」就沒了,推薦哪個都像擲骰子,拉力變弱。注意這裡的傷害形態是recall miss(相關 chunk 沒被撈出來),而不是精度下降。

    - streamlit app 執行時的 warning:
        ```bash
        `st.components.v1.html` will be removed after 2026-06-01.
        2026-07-02 16:00:45.280 Please replace `st.components.v1.html` with `st.iframe`.
        ```
        - st.components.v1.html 在 Streamlit 1.56.0 已 deprecated
        - 這個方法原本是用於在 iframe 中嵌入 html string，根據[官方文件](https://docs.streamlit.io/develop/api-reference/custom-components/st.components.v1.html)，v1.html 已經 deprecated，如果不想使用 iframe，則使用 st.html 方法，但如想繼續使用 iframe，應使用 [st.iframe](https://docs.streamlit.io/develop/api-reference/custom-components/st.components.v1.iframe)。
        - 通常官方對純 HTML 字串的通用建議是 st.html，但這個方法是行內渲染、無 iframe 沙箱、且不支援 height/scrolling。
        - 我們的[頁面設計所渲染](../dashboard_ui/pages/onenote_review.py)的是完整 `<html><head><style>... 文件（_WHITE_FRAME）加 base64 圖片`，需要沙箱隔離避免筆記 CSS 滲入整個 dashboard，也需要固定高度捲動框。
        > 已改成 st.iframe，接受 HTML 字串、沙箱 iframe、支援 height，並已經解決此 warning。
    - 前端頁面設計修改為：
        - 圓點切換設計改成下拉式選單放在頁面旁邊，選單標題命名為`版號(dt)`，後面跟著提示可審閱版本數量，可審閱的版本數量意思是 `上次 archived"後到現在有多少份筆記是沒有被 rejected，現在可以開放審閱`。
        - 歸檔後 tag 分佈、note_type 分佈 ()
        - Gemini 輸出 markdown <筆記 title> <版本 dt=>

    - 一份筆記某版本在 `rejected` 後，當下應該是`那一版本`的所有按鈕都失效，不能影響其他版本操作，而且再重新整理後不需要出現在前端了，此外，如果下次要在審閱同名筆記的其他版本 (=其他 dt)，則也應該要先過濾掉已經被判為 `rejected` 的筆記，避免使用者疑惑。
    > 已經修正，現在效果為：
    > reject 一個版本 → md 消失在頁面、其他版本的按鈕照常可被點。

    -  以 page_id 與 dt 作為主鍵查詢一份筆記的所有版本，並在前端做審閱，approved 觸發歸檔後，`regenerate`、`approved`、`rejected` 確實都已經失效，但這裡可能會有一個不便點在於，如果該 page_id 後續還有加入新內容造成 html_hash 變了然後會被下載到 `/raw-notes/` bronze layer，但是前端由於是以 `page_id` 與 `dt` 來管理按鈕是否生效，所以這時候會遇到新版筆記要歸檔的話將會不可行、沒有按鈕可操作，也沒辦法生成 enriched document。建議改成 page_id 在歸檔後，如果後面的日子有內容變動，新出現的 dt 版的筆記可重回 Silver 層生成文件且進入 gold layer，所以前端在跟使用者互動之前應有篩選機制，如下：
    ```MongoDB
        db.onenote_note_metadata.aggregate([{$match: {page_id: "abc123",
                                                    review_result: {$ne:"rejected"}
                                                    }
                                            },
                                    {$addFields: {dt_n: {$convert: {input: "$dt",
                                                                    to: "date",
                                                                    onError: null,
                                                                    onNull: null }}
                                                  }
                                    },
                                     {$setWindowFields: {
                                          sortBy: { archived_at: 1 },
                                          output: {
                                            lastArchivedAt: {
                                                      $max: {$dateTrunc: {date: "$archived_at", unit: "day"}},
                                                      window: { documents: ["unbounded", "unbounded"] }
                                                      }
                                                  }
                                            }
                                      },
                                      { $match: { $expr: { $gte: ["$dt_n", "$lastArchivedAt"] } } },
                                      { $project: {dt_n:0, lastArchivedAt:0}}
                                   ]);
    ```
    > 已經修正，現在效果為：
    > approve 某版歸檔後，對同 page_id 在 OneNote 加新內容 → 跑 bronze ETL 產生新 dt → 審查頁應出現該新版、可重走 Silver → Gold。

    - t_enrich_html_to_markdown.py 的 convert_img_tag_to_md_str() 在改寫 alt 圖釋時如果 alt 本來就有 `]` 符號，會在 convert to markdown string 時無法正常顯示圖片，因為 markdown 的圖片連結語法是`![替代文字](圖片相對路徑)`，如果替代文字中有`]`，解析器會看到`![替代]文字](圖片相對路徑)`，多出來的`]`會造成圖片顯示失敗，因此，需要修改此函式，把 `]` 同 alt 取代掉。此外，經實測，`!`、`[`、`%`等特殊符號夾在替代文字中不會影響，所以不需要特別處理。
    - 但即使如此，convert_img_tag_to_md_str() 執行後的 markdown string 會傳入 LLM call，這裡會有一個風險是，LLM 回傳的 enriched document `![](圖片相對路徑)` 有可能跟送進去之前的 markdown string 不太一致，例如："(0-02abd90`c`7e5c43c7bd33c4405ec5e53f!1-A5F7F5395D4FB9F!209.png)" 會變成 "(0-02abd90`b`7e5c43c7bd33c4405ec5e53f!1-A5F7F5395D4FB9F!209.png)"，而 `regenerate` 又換成另一張圖，例如："(0-4c3f19486a09451db`58f5`a5e93cb62ef!1-A5F7F5395D4FB9F!209.png)"
    變成了 "(0-4c3f19486a09451db`8f5`a5e93cb62ef!1-A5F7F5395D4FB9F!209")"，此為模型隨機性，透過提示工程修改 system prompt 可以較為緩解。
    > 除了修改 system prompt，也已在 `onenote_note_metadata` 新增了 `md_frontmatter` 欄位，查核追蹤有效圖片數量，作為評估資料品質的依據，未來可以搭配視覺化工具來擴展前端圖表。
    > `md_frontmatter` 在 archive 與 reject 觸發後都會寫入，以評估好 md 與壞 md 的特性。(例如：哪類別的筆記容易被退件、歸檔的筆記是不是存在人工審查疏漏沒發現破圖)。

## 20260705 Work log

- MongoDB Atlas 連線結構優化：從「每次查詢都 new 一個 MongoClient」收斂成 module-level 單例
    ```python
    """學到的重點：
    1. MongoClient 本身就設計成「長生命週期的單例」——它內建連線池 (connection pool) 且 thread-safe，
       正確用法是整個程式共用一個，而不是每次查詢都 new 一個。
    2. Streamlit 的 @st.cache_resource 是「跨 page、跨 session 全域共用」的快取，適合放連線這種資源；
       但它「定義在哪個 module 就綁在哪」，A 頁定義的 cache_resource 函式，B 頁不能靠 import A 來重用
       (import 會把 A 整頁 script 從頭重跑一遍)。
    3. @st.cache_data 快取的是「回傳值 (資料)」，不是連線物件。把 get_db_atlas() 藏在 cache_data 函式裡，
       TTL 到期或 .clear() 之後就會再 new 一個 client，舊的沒關、連線池殘留，長期累積逼近 Atlas 連線上限。
    """
    ```
    - **情境**：dashboard 有四頁 (HOME / knowledge_factory / ai_knowledge_agent / onenote_review) 加上 agent_tools，全都要連同一個 Atlas cluster。原本 `get_db_atlas()` 每被呼叫一次就 `MongoClient(uri)` 建一個新 client。HOME 頁用 `@st.cache_resource` 包了一層還好，但 onenote_review 把它藏在 `@st.cache_data(ttl=60)` 的 `_load_versions()` 裡，每 60 秒 TTL 到、或每次 enrich 成功呼叫 `_load_versions.clear()`，就會再開一個新連線池。
    - **優化前**：`get_db_atlas()` 無狀態，每次呼叫都建立新連線。
        ```python
        def get_db_atlas() -> Database:
            mongo_uri = os.getenv("MONGO_ALTAS_URI")
            db_name = os.getenv("MONGO_DB_NAME")
            ...
            client = MongoClient(mongo_uri)   # ← 每呼叫一次 new 一個，各自帶一整個連線池
            return client[db_name]
        ```
        > 盲點：MongoClient 預設連線池最多 100 條連線，多頁 × 多次 cache miss 各開一個 client，舊 client 不會馬上被 GC 關閉、連線池殘留佔用，長時間跑會逼近 Atlas 低階 tier 的連線數上限 (如 M0 = 500) 而報 connection limit exceeded。app.py 那層 `@st.cache_resource` 只擋得住自己這頁的重複，那份快取是「app.py module 私有」的，其他頁 import 不到，等於各頁各自為政。
    - **優化後**：把「取 client」收斂成 module-level lazy 單例，首次建立、之後所有 caller 重用同一份。
        ```python
        _atlas_db: Database | None = None

        def get_db_atlas() -> Database:
            global _atlas_db
            if _atlas_db is not None:      # 已建立過 → 直接重用，不再 new client
                return _atlas_db
            mongo_uri = os.getenv("MONGO_ALTAS_URI")
            db_name = os.getenv("MONGO_DB_NAME")
            ...
            _atlas_db = MongoClient(mongo_uri)[db_name]
            return _atlas_db
        ```
        > 差異：現在四頁 + agent_tools 全部共用同一個 MongoClient 與同一個連線池，不管誰在哪頁、cache 命不命中，連線只建立一次。app.py 那層多餘的 `@st.cache_resource get_mongo_db()` 包裝也可以直接拿掉，改成 `db = mongo_utils.get_db_atlas()`。
    - **為什麼要優化**：
        - (a) **連線數**：避免「每次查詢就 new 一個 client」把 Atlas 連線池撐爆——在低階 tier 會直接報 connection limit exceeded。
        - (b) **效能**：建立 MongoClient 要做 TLS handshake + cluster topology discovery，不便宜；重用單例省掉每次查詢的建連成本。
        - (c) **語意正確**：MongoClient 官方就建議當單例用，「每次查詢開一個」是反模式 (anti-pattern)。
        - (d) **為什麼用 module-level 單例而非 @st.cache_resource**：get_db_atlas() 也被 agent_tools (非純 page context) 呼叫，module 級單例不綁 Streamlit runtime、任何 caller 都能共用；`@st.cache_resource` 需要 script run context，通用性較差。

## 20260707 Work log
1. New schema of task01
    ```json
        // Collection name: obsidian_note_metadata
        {
        "_id": "60c72b2f9b1d8b2bad7f0001", // MongoDB 自動生成
        "note_user_id": "lucky460721", // 筆記使用者，從 GCS blob path 的 "personal-vaults/raw-notes/lucky460721/data-engineering/01-daily-logs/20250909 Mac安裝Python.md" 解析得到
        "notebook": "data-engineering", // notebook 名稱，從 GCS blob path 的 "personal-vaults/raw-notes/lucky460721/data-engineering/01-daily-logs/20250909 Mac安裝Python.md" 解析得到
        "section": "01-daily-logs",  // section 名稱，從 GCS blob path 的 "personal-vaults/raw-notes/lucky460721/data-engineering/01-daily-logs/20250909 Mac安裝Python.md" 解析得到
        "file_name": "20250909 Mac安裝Python.md", // 筆記檔名稱，從 GCS blob path 的 "personal-vaults/raw-notes/lucky460721/data-engineering/01-daily-logs/20250909 Mac安裝Python.md" 解析得到
        "raw_md_md5_hash": "7CeqwdfwX3ZJmgek9o0wg==", // 筆記 md5 hash 作為變動比對值，從 blob.md5_hash 取得
        "raw_md_path": "gs://personal-vaults/raw-notes/.../01-daily-logs/20250909 Mac安裝Python.md", // 即 GCS 路徑，含 (gs://)
        "raw_md_updated_at": "2026-07-06T12:00:00Z", // blob 更新時間，從 blob.updated 取得
        "archived_at": "2026-07-06T12:22:00Z",  // 清洗完 raw_md 後存到從 GCS blob path 的 "personal-vaults/archived-notes/lucky460721/data-engineering/01-daily-logs/20250909 Mac安裝Python.md" 的時間(utc+0)，從 archived-notes 後方開始路徑全部跟 raw-notes 相同
        "archived_md_md5_hash": "e59cd35b5bab9b311210bc875b1e00aa",  // 存入 archived-notes/ 下的筆記之 md5，從 blob.md5_hash 取得
        "archived_md_path": "gs://personal-vaults/archived-notes/lucky460721/data-engineering/01-daily-logs/20250909 Mac安裝Python.md",
        "status": "archived", // 隨 archived_md_path & archived_img_path 寫入時一併翻成 archived，在此之前都是 null
        "embedded_status": true, // archived_md 被向量化過的狀態標示，初始化為 false，只有在 task06 完成時回來這裡翻成 true，
        "error_msg": "",  // GCS 讀寫異常時 msg
        "archived_md_frontmatter": {
            "archived_md_frontmatter.tags": ["javascript", "async", "guide"],
            "archived_md_frontmatter.date": "2026-07-06T00:00:00Z",
            "archived_md_frontmatter.type": "tutorial",
            "archived_md_frontmatter.alias": ["JS Async", "Asynchronous JS"]  // raw md 的 frontmatter 既有的架構與內容，直接取出來清洗，並在將 md 存到 archive-notes 後一併存入
        },
        "attached_images": [ {"raw_image_path": "gs://personal-vaults/raw-notes/.../_attachment/image04.png",
                              "raw_image_md5": "7Vrwjio3123mgek9o0wg==",
                              "archived_image_path": "gs://personal-vaults/archived-notes/.../_attachment/image04.png",
                              "archived_image_md5": "7CYeIJqAqX3ZJmgek9o0wg=="
                              },
                              {},
                              {}
                            ],
        "topic": "Programming",  // 從 archived md 的 tag 挑選出來的 topic
        "word_count": 1250 //  從 archived md 的數出來的文章字數(不含frontmatter)
        }
    ```

    - (Bronze) E & L: 從本機走 `glcoud storage rsync` 到 `gs://personal-vaults/raw-notes/lucky460721/.../....`。
    - (Silver) Transform: 設計兩支主函式，分別處理 md 與 attachment
        - 處理 attachment 流程：
            - 從 `gs://personal-vaults/raw-notes/_attachment/` 掃描所有 ext 為 `.png`、`jpeg`等圖像的 blobs，從 blob.md5_hash 洗出 md5_hash 雜湊值，並在 collection `obsidian_attachment_metadata`，以跟上面相同的邏輯查找哪些屬於新增與變更的檔案，也放入待清理列表 list。
            - 對回傳的 list，逐一取得 blob.md5_hash，針對 `raw_file_path` 做 upsert，寫入 `file_name`, `raw_file_md5_hash`, `raw_file_updated_at`, `status`(初始化為 null)。

        - 處理 md 流程：
            - 從 `gs://personal-vaults/raw-notes/...` 掃描所有 ext 為 `.md` 的 blobs，以 blob.name，在 collection `obsidian_note_metadata` 找 `raw_md_path` 找匹配的，如果表上沒有匹配的，則 insert 放入待清理列表，如果有匹配則進一步找該列的 `md_md5_hash` 是否跟 GCS 上的 md5_hash 相同，若不同則也放入待清理列表 list。(可以不一定要二階段查詢，可用 $or 條件運算子)。
            - 對回傳的 list，逐一 `download_as_text()` 做資料轉換，轉換工作包含現行版本的 task01 的：
                - `_infer_misposition_metadata()`
                - `_infer_note_type()`
                - `_infer_topic()`
                - `_infer_date()`
                - `extract_attached_images()`
        > 未來如果這裡希望新增 document enrichment by LLM，則可從這裡加入，然後斟酌淘汰上述五個清理步驟或是挪動修改順序，例如：把 `_infer_misposition_metadata()` 挪到 LLM 生成後面再做，就跟 task07 雷同。此外，清理後建議改先存入 `processed-notes/...` 下方，並經由人工審查或抽撿來檢視是否放行該 folder 到 `archive-notes`，除非是對模型生成品質已有信心，則可直接存入 `archive-notes/...`。由於 `archive-notes` 後續將讓給 task06 定期掃描存入向量化資料庫，所以如果 enriched document 品質不穩定，直接存放在 `archive-notes` 會可能污染到檢索品質。

        清理後直接存入呼叫 `archive-notes/...md` 下，並組裝準備 Upsert `obsidian_note_metadata` 的欄位之 dict，key 包含：`note_user_id`, `notebook`, `section`, `file_name`, `raw_md_md5_hash`,`raw_md_path`, `raw_md_updated_at`, `raw_md_attachment_id`, `status`(為 `archived`), `archived_at`, `archived_md_md5_hash`, `archived_md_path`, `archived_md_attachment_id`, `embedded_status`(初始化為 false), `archived_md_frontmatter`, `topic`, `world_count`。

        其中 `raw_md_attachment_id` 的值，會從 `extract_attached_images()` 解析出來的 GCS URI (=raw_file_path) 到 `obsidian_attachment_metadata` 查找後取出 `_id` 欄位值後，以陣列寫入`raw_md_attachment_id`中，這支函式最後要回傳真正有找到對應 `_id` 的 `raw_file_path` 列表。
    - (Silver) Load：收尾 attachment。
        - 走訪 Transform 層回傳的`有用的 raw_file_path` 列表，以 copy_blob() 到 `archive-notes/.../_images/` 下並取得 md5 hash 雜湊值以後，寫入 `obsidian_attachment_metadata`，更新欄位 `status`(翻成 archived), `archived_file_md5_hash`, `archived_file_path`, `archived_at`(datetime.now(tz=timezone.utc))。
    - (Gold) 對 `obsidian_note_metadata` 做快照，追蹤清理後與向量化進度，分析：
        ```json
            // Collection Name: notes_summary
            {
            "_id": "60c72b2f9b1d8b2bad7f0001", // MongoDB 自動生成
            "snapshot_date": ISODate("2026-06-26T00:00:00.000+0000"), // 快照日當天只照一次，故不計時\分\秒
            "by_type": { "daily-log": 40, "knowledge-base": 32, "project": 15 },  //
            "by_topic": { "python": 18, "sql": 12, "ml": 8, "cloud": 6, "biotech": 14, "other": 29 },
            "total_notes": 21,
            "total_types": 21,
            "total_tags": 21,
            "total_singleton_tags": 5,
            "embedded_notes": 2  // 計數 "obsidian_note_metadata" 中 embed_status=true 有幾筆
            }
        ```
        > 待辦事項：這裡的快照項目需要視希望看task01、task07與task06還有沒有什麼指標想放進來，所以欄位還可能要再多想。

2. Based on the planning above, established the scripts of [task01-v2](../task01_obsidian_etl_v2/).

## 20260708 Work log
1. In the branch `feature/html-to-markdown`, revised the [task07](../task07_onenote_to_markdown_lazy_loading/) to reduce the difference of schema designs between task01 that ingested the notes from Obsidian App and this task07 that ingested the notes from OneNote App. Most of columns in [task07](../doc/task07_onenote_versioned_etl_hand_over_v2.md) were all almost similar except for the hash calculation for raw-notes and existence of columns to address the metadata of processed-notes in Silver layer. The gold layer, storing the archived-notes prior to embedding to RAG, are described in the same business meaning in their individual tables.
    > Next Step: *`dashboard_ui/pages/onenote_review.py` 第 328,342 行應使用enriched_md_path，否則版本清單會誤判尚未生成。*
2. Estabslished [task08](../task08_onenote_embed_etl/) for embedding the OneNote archived-note markdown files to vector database. The design of the task08 almost the same as the embedding task06 that handles the archived-notes from Obsidian.
    > Next Step: Minor correct the column name of vector database collection `note_vectors_multimodal` from `raw_md_path` to `md_path` in order to correct the business meaning:
    > - Source of any embed should be archived notes in markdown file and no longer raw notes or processed notes. The latter two only valued in bronze and silver layer. Source of embed should come from gold layer (i.e., archived notes).
    > - To accommodate the archived .md from both task07 (handling OneNote) and task01 (handling Obsidian), the column name of `md_path` does not specifiy the note APP name. (Neither `onenote_md_path` nor `obsidian_md_path` were used. Just `md_path`).
    > - Same requirements for the column `image_paths`. This column point to the paths of archived images of a note without limiting to any specific note APP.

## 20260713 Work log
1. Switched to the branch `develop`, merged task01, task01_v2, task06_v2, byproject.toml, openspec/changes, .env.example, and CLAUDE.md, from the branch 'feature/etl-pipeline' to the branch 'Develop'. The openspec/changes, .env.example, and CLAUDE.md in were 'feature/etl-pipeline' especially synchronzied to the latest version as that in the branch 'feature/dashboard-ui' before hand, so merging from 'feature/etl-pipeline' would not led to the commit version of CLAUDE.md behind the 'feature/dashboard-ui'.

2. In the branch `develop`, exported and overwrote the `requirements.txt`.
    - Key observation: In the [Dockerfile.task05](../docker/Dockerfile.task05), the behavior of `python -m pip install --no-cache-dir -r requirements.txt` could not install the pre-release versions of packages even though version number had been designated in the requirements.txt. For example, the wrapper `pygsheet==0.1.19b25` is beta ver. of PEP 440. The command `pip install` could ignore it so that the dependent package `pygsheets` cannot be normally imported in a docker container.
    > Solution: Specified the version number of `pygsheets (not pygsheet)` in the requirements.txt to make sure the pip install successfully install the packages that is truely required in [task05 scripts](../task05_googlesheet_skill_etl/e_fetch_google_sheet.py).

3. Successfully deployed the task01_v2 to cloud run job and meanwhile the other task02, task03, and task05 were re-deployed as well due to the github workflow automatically push their images to GCP artifact registry.

4. Established the [Dockerfile.task06](../docker/Dockerfile.task06) and github workflow to automatically build docker image and push to GCP artifact registry.
    > 待辦事項：change the github workflow to accomplish the automatically deployment the container via cloud run jobs.

5. Manually deployed the task06 on cloud run job. All the steps worked smoothly. Additionally, minor revised the passed argument to the function `_get_genai_client()` in [the connection with agent platform](../task06_obsidian_embed_etl_v2/t_chunk_embed.py). Cloud run job container use service account to generate `genai.client()` in the google agent platform so the credentials with json key was commented out. The codes to create credentials was left for execution on-premise or 3rd-part cloud services only.

6. Same jobs were done for [task08](../task08_onenote_embed_etl/t_chunk_embed.py). Deployment onto GCP cloud run job went well.
