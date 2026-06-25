# 循環改進處、遇到過的問題彙整
## ♻️ 改進中
- README 與專案結構文件仍需隨任務演進持續修訂，包含各 ETL 任務產出的 MongoDB collection schema 與 Phase IV 部署里程碑。
- Task03 LeetCode GraphQL API 缺少正式文件，且依賴 `LEECODE_SESSION` 與 CSRF token；cookie 過期會導致 403，雲端部署前需評估自動更新或替代認證流程。
- Task06 MongoDB Atlas Vector Search 目前資料量仍小，M0 Free Tier 足夠；但後續筆記數、chunk 數、embedding 維度或 metadata 增加時，需重新估算儲存量與成本。
- Phase III 的 Router Agent 追問繼承仍有殘留上下文污染：`_looks_like_followup()` 判定為追問並繼承上輪 `filter_tags` 後，rag agent 仍會以「追問 query」重算向量相似度，導致混入與追問語意相近、但與上一輪主題較遠的筆記來源（如 partition_clause 追問仍混入 Sharding/NoSQL 來源）。後續需評估追問時是否應沿用上一輪 `search_query` 或限制相似度重算範圍。（20260621）
- Phase III 的 Router Agent 追問判定為啟發式規則（`_looks_like_followup()` 比對追問詞／排他詞），會誤判：同主題的新查詢（如「找 dev container」）未被視為追問而重抽 tag，雖結果正確但邏輯非預期；需評估更穩健的追問判定機制。（20260621）
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
    **專案名稱**：個人技能儀表板與知識庫訓練（Streamlit + MongoDB local/MongoDB Altas + GCP）
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

### Evaluate the loading on Vector database, MongoDB Altas.
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
> `MongoDB Altas M0 Free Tier up to 512 MB, far from 108 MB`


## 20260526 Work log
1. MVP and RAG practices are the recent major goals in this project, so `text-embedding-3-small` was selected as the primary embedding model. If embedding muiltple files are firmly required in the next step, then the multimodal model `Gemini embedding 2` could be selected.
- 使用模型：text-embedding-3-small
    - 引用方式：openai Python SDK，model 參數傳入 "text-embedding-3-small"
    - API 文件：https://platform.openai.com/docs/guides/embeddings
    - 維度：1536（EMBEDDING_DIM），建立 MongoDB Atlas Vector Index 時填這個數字
    - 費用：$0.02 / 1M tokens（2025 年定價）
2. Went to https://platform.openai.com/api-keys to create an API secret key (and set billing detail which needed credit card). Keep it in .env and secret managers.
3. Created the scripts `task06/t_chunk_embed.py` and `task06_obsidian_embed_etl/l_upsert_vectors.py`. Successfully practiced chuncking and embedding the long text in three markdown files.
4. Created the script `task06_obsidian_embed_etl/main.py`, to successfully insert the docs with embedded chunks to new collection `Obsidian_vectors` on Altas.
5. Created the index for vector search by following the [hand-over](./task06_vctr_srch_idx_hand_over.md). The resulted collection `Obsidian_vectors` that contained the embedded chunks from the long texts in 63 .md files, took about 410 KB in MongoDB Altas.
6.

> Until 20260527, some questions might be solved or optimized:
> 1. 若未來一份筆記被重新切塊後 chunk 數量減少 (例如從 6 個縮為 4 個)，
    舊的 chunk_index 4、5 不會自動被刪除。
    目前資料量小，影響不大；若未來需要清理孤立 chunk，
    可在 upsert 前先 delete_many({"file_path": file_path})，再重新 insert。
> 2. 根據這篇新聞(https://www.ithome.com.tw/news/173423)，發現 Altas 為 MongoDB 提供 Voyage embedding model，可以在使用 MongoDB 雲端資料庫時使用自動 embedding 功能，後續再考慮補上選型評估。

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
    > The srcipt establishment also solved the issue on lack of audit logs in the processes of fetching OneNote, extracting by LLM and uploading to GCS. They are loaded to MongoDB Altas. Meanwhile, the metadata of linkage between original notes from OneNote and transformed notes by LLM are also created. Finally, three collections were established on MongoDB Altas as planned in the [hand-over doc](./task07_html_to_md_hand_over.md).

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
    - gcs_archiver.py: Most of python function design followed the logistic of my hand-over, especially, how to get the markdown path, html path, image path correctly from the single-truth, MongoDB Altas `onenote_page_metadata`.
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
            db = get_db_altas()
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
            db = get_db_altas()
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
            db = get_db_altas()
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
    | 2 | partition_clause 能否再講多一點  | rag | 根據您提供的筆記片段，關於 partition_clause 的說明如下：<br>partition_clause 是資料表中的分區方式。在套用 Window Function 時，MySQL 會針對 partition_clause 分區後的每一個區塊，分別......您提供的其他筆記片段（來源 1、3、5）主要在討論資料庫的分片 (Sharding) 和分割 (Partitioning) 機制，以及 SQL 與 NoSQL 的比較，這些內容與 MySQL Window Function 中的 partition_clause 的具體用法關聯性較小。 | ⚠️ router agent `_looks_like_followup()` 判斷屬於追問，繼承前次 filter tags ('MongoDB', 'MySQL', 'data-type', 'BSON', 'SQL')，最後 Window function parition clause 留在 LLM 的回覆參考中，但因為 vector search 是由 rag agent 繼承 tags 與追問 query 後重新計算相似度，造成此時混入新的筆記來源與追問語意較相似但是跟上一輪語意較遠，最後造成 rag agent 仍有部分上下文污染。在這輪測試中發現來源筆記變成了 |
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

4. Meanwhile, fixed the pending defection of `upsert` behavior to MongoDB Altas collection which might leave silo, broken, and obsoleted data chunks if the length of chunks had been shorten after re-embedding a revised text. As the [resulted script](../task06_obsidian_embed_etl/l_load_to_mongodb.py), `deleteMany and insert` behavior replaced `upsert`.The doc of `all` the embedded chunks pointed to the same note file path would be deleted from the collection `obsidian_vectors_multimodal` first. Then new chunks were inserted. This should prevent the broken chunks left in the vector database after multiple rounds of embedding tasks to a note text.

5. To save the requests to vertex AI API, [data capture change (CDC) approach](../task06_obsidian_embed_etl/l_load_to_mongodb.py) was implemented in refactoring. Only when the file on GCS was changed and the its embedding status in the collection `obsidian_notes` was not done (`embedding_done`=false) yet, the requests to Vertex AI API for embedding the text of the file would be performed. Otherwise, the requests would be skipped.

6. To accomplished the 3. & 4., the schema of collections `obsidian_summary` were revised. See the [revision in the branch_etl_pipeline_summary.md](branch_etl_pipeline_summary.md#mongodb-collections).

7. Installed the linter and formattor via `pre-commit` and `ruff`.

8. Updated the [hand-over of index creation](./task06_vctr_srch_idx_hand_over.md) to align the model type.
