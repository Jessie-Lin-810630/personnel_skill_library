# 循環改進處、遇到過的問題彙整
## ♻️ 改進中
- README 與專案結構文件仍需隨任務演進持續修訂，包含各 ETL 任務產出的 MongoDB collection schema 與 Phase IV 部署里程碑。
- Task03 LeetCode GraphQL API 缺少正式文件，且依賴 `LEECODE_SESSION` 與 CSRF token；cookie 過期會導致 403，雲端部署前需評估自動更新或替代認證流程。
- Task06 RAG/embedding 方案已先選用 `text-embedding-3-small`，但若未來需要處理圖片或多模態資料，仍需重新評估 Gemini Embedding 或 MongoDB Atlas/Voyage 自動 embedding。
- Task06 vector upsert 目前若筆記重新切塊後 chunk 數量減少，舊 chunk 不會自動刪除；未來資料量增加時可在 upsert 前先依 `file_path` 清除舊 chunks 再重新寫入。
- Task06 MongoDB Atlas Vector Search 目前資料量仍小，M0 Free Tier 足夠；但後續筆記數、chunk 數、embedding 維度或 metadata 增加時，需重新估算儲存量與成本。

## ✅ 已解決
- Task02 GitHub REST API 需要處理 rate limit，以及 409、429、403 等例外狀態的邏輯；後續維護時仍須留意 API 規格與錯誤處理策略。
- Task02 曾發生 GitHub commit 統計在多分支中重複計算的邏輯錯誤，已修正，但後續新增統計指標時需避免相同資料被重複聚合。
- Task03 ccClub 資料抓取依賴 CSRF token、帳號與密碼，需持續注意登入流程、token 取得方式與憑證管理。
- Task05 Google Sheets ETL 曾遇到 `SettingWithCopyWarning` 與 upsert 設計錯誤，已透過 `dataframe.copy()` 與 upsert 邏輯修正。

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
1. The intent agent and rag agent were created and tested in the first round via unit test. There were some logistic defect when judging the intention in the samples of user's queries.
The testing results were listed as follows. Particulary in the Sample 10 and 11, the context with historical chat messesges with RAG agents confused the LLM of Router agent in R2 plan. The LLM representing R2 considered the responses by RAG its own response.
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
1. Created new branch for new feature of conversion `.html` output from OneNote graph API to .`.md` files.
2. Installed Claude Code AI assistant.
3. Installed `OpecSpec` for practice of Spec-Driven Development along with this project.
4. Inititated the `task07_onenote_to_markdown` where intended to request the personal notes on Microsoft OneNote through the `Azure graph API`, download the raw notes as individual .html file and summarize the `metadata` of html files in .csv file.

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
> Rate limit comparison between [Gemini 2.5 flash lite Model](https://ai.google.dev/gemini-api/docs/rate-limits) and []
> Token calculation comparison between [Gemini 2.5 flash lite Model](https://docs.cloud.google.com/gemini-enterprise-agent-platform/models/capabilities/get-token-count?hl=zh-tw#gemini-get-token-count-samples-python_genai_sdk) and [Anthropic Haiku 4.5 Model](https://platform.claude.com/usage/limits?focus=claude_haiku_4:rpm).

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

4. 