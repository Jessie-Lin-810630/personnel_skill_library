# # Task07 Hand-over：OneNote 多版本保留 × LLM 省呼叫 ETL 開發計畫

> **開發目標**： 延續 Task07 的 OneNote → Markdown → 向量庫 ETL，本分支針對「企業部門公務筆記」場景強化兩個目標：  \
> 1. **Bronze layer - 允許保留同一份筆記的舊版本 HTML**，讓資料源歷史可追溯、不互相覆蓋:\
核心手段是「在 GCS 以 `dt=` 日期分區保存多版本 OneNote 的同名筆記，檔型為 html」。  \
> 2. **Silver - 避免浪費 multimodal LLM 的 enrichment 任務呼叫**:\
核心手段是「ETL 階段完全不主動呼叫 LLM，所有 enrichment 改為**純 Lazy Loading（on-demand）**，也就是等到使用者登入審查 UI、點擊某個尚未處理的版本時，才當場觸發 Silver 流程（查快取 → 呼叫 LLM → 存 MD）」。  \
查快取的意思是「以筆記的 `html_hash` 為冪等鍵，在 metadata 中尋找這個 `html_hash` 與是否先前已經建立過 LLM enriched markdown document 且已存在 GCS 上的何者路徑，`html_hash`為 key，`md_path`為 value，從 GCS 上尋 `md_path` 來作為資料快取，因此就不需重複 enrich 相同內容筆記。  \
除非使用者要求 `regenerate` enriched document」。`regenerate` 按鈕實作於後文詳述。
> 3. **Gold - 加入 `regenerate` 點擊額度限制，避免系統上線初期被惡意狂打 LLM calls**: \
核心手段是在 LLM_call_logs 增加 `trigger` 欄位紀錄呼叫模型的原因，若 `regenerate` 超過額度則封鎖按鈕，只能 archive 或 reject。

## 前置條件確認
- **執行環境**：macOS with Web browser / VS Code IDE / pyenv (Python 3.14) / Poetry  \
- **AI tool**：Claude code + OpenSpec skill  \
- **資料授權**：本人 Delegated Authorization，員工於瀏覽器登入授權後，呼叫端取得 OneNote Graph API token  \
- **開發分支**：
  - New branch `feature/html-to-markdown`：負責開發 Bronze layer，從 OneNote Graph API 判斷是否下載 html 至 GCS 並執行下載。
  - existing branch, `feature/dashboard-ui`：
    - 負責開發多版本對照審查頁。
    - 負責開發 Silver layer 的 enrichment 服務本體，生成 enriched document markdown。
    - 負責開發 Gold layer 的歸檔 (`archive`) 與退件 (`rejected`) 按鈕，且在觸發後登記筆記特性數據到 metadata，作為 LLM 生成之資料品質的驗證指標。
- **目的整併至分支**：`feature/html-to-markdown` 整併至 `feature/dashboard-ui`，`feature/dashboard-ui` 再隨雲端部署時整併到 `develop`

---

## 專案資料夾結構

```
分支 feature/html-to-markdown
<project root workdir>/
├── .env
├── poetry.lock
├── pyproject.toml
│
├── task07_onenote_to_markdown_lazy_loading/
│   ├── e_onenote_download.py     # Bronze layer - Extract：人工確認 endpoints、下載 html，
│   │                             # 算 html_hash、與 metadata 最新 hash 值判定變動
│   ├── t_html_to_markdown.py     # Silver layer - Transform：html.parser → multimodal LLM 做出
│   │                             # enriched document mardown，enrichment 以 html_hash 冪等快取；
│   │                             # 內含輕量服務級守門（LLM API 連續失敗則暫停 on-demand）
│   ├── l_save_markdown.py        # Silver layer - Load：enriched document md 存 GCS，更新 metadata
│   ├── main.py                   # Bronze ETL 入口（Extract + Load，不含 LLM）；Silver 由 UI on-demand 觸發
│   └── utils/
│         ├── hashing.py          # html 原始碼 hash、GCS 物件 md5
│         └── audit_log.py        # Append log to MongoDB
│
└── tests/
```

```
分支 feature/dashboard-ui
<project root workdir>/
├── .env
├── poetry.lock
├── pyproject.toml
│
├── dashboard_ui/
│   └── app.py                               # 網頁入口，主頁面
│       ├── pages/
│       │    └── onenote_review.py           # 頁面3 - silver & gold 層服務入口
│       └── utils/
│            ├── gcs_reader.py               # 讀取 GCS 物件，無法寫入。
│            ├── interact_with_mongodb.py    # 與 MongoDB 連線，透過各 collection 查詢函式取得文檔資料
│            └── ui_elements.py              # 共用 UI 元件：sidebar、雷達圖、任務明細表、色票設定，
│                                            # 供 app.py 與 pages/ 使用
│
│
├── task07_onenote_to_markdown_lazy_loading/
│   ├── e_onenote_download.py     # Bronze layer - Extract：人工確認 endpoints、下載 html，
│   │                             # 算 html_hash、與 metadata 最新 hash 值判定變動
│   ├── main.py                   # Bronze ETL 入口
│
├── task07_silver_service/
│   ├── t_enrich_html_to_markdown.py  # Silver layer - Transform：html.parser → multimodal LLM 做出
│   │                                 # enriched document mardown，enrichment 以 html_hash 冪等快取；
│   ├── l_save_markdown.py            # Silver layer - Load：enriched document md 存 GCS
│   └── app.py                        # Silver 服務主體，串聯 t & l
│
├── task07_gold_service/
│   ├── l_archive_note.py             # Gold layer - 處理歸檔或退件，並寫入資料品質指標。
│   └── app.py                        # Gold 服務主體
│
├── task07_common/                    # task07 三層共用函式庫
│   ├── gcs.py                        # 下載或是上傳物件到 gcs
│   ├── hashing.py                    # html 原始碼 hash、GCS 物件 md5
│   └── audit_log.py                  # Append log to MongoDB
└── tests/
```

---

## Task 07 — OneNote 多版本下載、彙整、審查 ETL 流程描述

### 資料來源
Microsoft OneNote Graph API（Delegated Authorization）

### Tools, Framework
- msal（取得 delegated token）
- requests（下載 html 與引用圖片）
- BeautifulSoup / html.parser
- google gen ai sdk（multimodal LLM enrichment）

### database, data storage
- MongoDB Atlas
  - api logs: collection 名稱為 `onenote_graph_api_logs`
  - LLM logs: collection 名稱為 `multimodal_llm_enrichment_logs`
  - note metadata: collection 名稱為 `onenote_note_metadata`
- GCS（data lake，以 `dt=` 分區保存 html、md、png 多版本）

---

### Bronze layer — 多版本 raw notes 保存

- ETL 步驟
  1. Delegated token → 請求 OneNote Graph API，取得員工公務筆記的所有 page endpoints 清單。
  2. **人工確認 (python `input()`)** 核查要從哪些 endpoints 下載，避免自動化腳本無聲載到敏感資訊造成個資外流。
  3. 對核可的 endpoints 用 `requests.get()` 下載 html 原始碼（含引用圖片），計算 **html 原始碼 hash**（`utils/hashing.py`）。
     > 選用 hash 而不是 API 的 `lastModified_datetime` 判斷筆記是否變動的緣由：實測 page endpoint 的 lastModified 與 notebook/section endpoint 不同步、語意不清，故改以下載後的 html hash 為變動依據。

  4. 變動判定後儲存
    - 讀取 MongoDB Atlas collection `onenote_note_metadata`，取出該頁筆記**最新一筆**已記錄的 `html_hash`。
      > 以該頁**最新一筆 hash** 為準，**而不是綁定「上次執行日」**，因為有可能上次執行時，部分筆記因未變動而沒寫新 hash 紀錄時，導致資料庫撈資料後比對失敗。
    - 若新算的 `html_hash` 與最新一筆 hash **相同**，則**不下載**。
      > 因為內容沒變，避免不同 `dt=` 分區存重複檔、浪費空間。
    - 若新算的 `html_hash` 與最新一筆 hash **不同**，則視為新版本，**下載 html 與它引用的 images**，寫入 `gs://onenote-vaults/raw-notes/<onenote_user_id>/<notebook>/<section>/dt=<bronze執行日>/<page>.html`、`gs://onenote-vaults/raw-notes/<onenote_user_id>/<notebook>/<section>/dt=<bronze執行日>/_images/<image>.png`，此時 html 與 png 取得各自的 GCS 物件 md5。
      > 取捨說明：此處只跟「最新一版 hash」比對，所以 內容長相變化歷程如果是 A → B → 改回 A，回退成 A 的這階段，筆記本身是被當新版再存一份。不做 hash 去重，因為若要連回退都去重，需改成比對該頁**所有歷史 hash**；對公務筆記通常跟最新版比即足夠。
  5. 更新資料庫
    - Insert to collection `onenote_graph_api_logs`。
    - Upsert to collection `onenote_note_metadata`（page_id、notebook、section、page_title、dt、html_hash、html_md5、html_path、html_downloaded_at、img_*、status=bronze_stored、embedded_status=false）。
      > 新版本一律落在 `bronze_stored`（待 on-demand enrich），ETL 不在此呼叫 LLM、不做任何跨版本標記。
  6. 執行頻率
    - 第一次由人工授權應用程式取得 token，第二次開始自動化每週一次。
      > 需設計 refresh token 機制與記載第一次觸發時核可過哪些筆記本，否則第二次仍然需要人機互動來做筆記本挑選，若使用者仍期望人機互動，應再設計服務介面且部署在有人監管的伺服器；若可完全自動化，則可部署 bronze 至 serverless 服務上。

  7. Hierarchy of blobs on GCS
    ```plaintext
    gs://onenote-vaults/raw-notes/<onenote_user_id>
    ├── <notebook_name>/
    │       ├── <section_name>/
    │       │       ├── dt=2026-06-10/                ⬅️ 第一次偵測到變動的版本
    │       │       │       ├── <page_name>.html
    │       │       │       └── _images/
    │       │       │             └── image01.png
    │       │       ├── dt=2026-06-18/                ⬅️ hash 又變了，存新版本
    │       │       │       ├── <page_name>.html
    │       │       │       └── _images/
    │       │       │             └── image01.png
    │       │       └── dt=<bronze執行日>/             ⬅️ 最新版本
    │       │               ├── <page_name>.html
    │       │               └── _images/
    │       └── <section_name_2>/
    │               └── dt=.../
    └── <notebook_name_2>/
            └── ...
    ```

    > GCS 保存路徑前綴帶 `dt=<bronze執行日>`。同一頁筆記每次 hash 有跟`上一版本的 hash 值不同`就寫進新的日期資料夾，舊版本留在舊 dt 分區、不被覆蓋，以保留歷史可完整回溯。

---

### Silver layer — on-demand 觸發 × 冪等快取

> 設計取捨（為何純 Lazy Loading (on-deman)）
>  - 公務筆記改動頻繁、人工審查易塞車。若每週主動預熱最新版，塞車時預熱出來的中間版多半沒人會選，等於白燒 token。
>  - on-demand 後，**省 token 的效益完全由 `html_hash` 快取自然達成**：使用者沒點的版本永遠不 enrich；點過的版本第二次點命中快取、零成本。毋須用狀態機去「決定這週該不該動手」。

- 觸發時機**只有一種**：**on-demand**——使用者在審查 UI 點擊某個 `bronze_stored`（尚未生成 md）的版本時即時觸發。針對被點到的那一版 html 筆記（不限定最新版；舊版被點同樣即時生成），ETL 階段不主動觸發。

- ETL 步驟
  1. 使用者在透過 streamlit 寫出的審查介面，選擇某一篇筆記後，即時觸發`最新版`的筆記 enrichment 任務 (step 2&3)，而最新版筆記的 html 檔放在 GCS 哪個路徑下，由 collection `onenote_note_metadata` 的欄位 `dt=<最新>` & `page_id` 作為主鍵來查詢得到該資料列的 `html_hash`。

  2. 拿該列 `html_hash` 繼續在 collection `onenote_note_metadata` 找「有沒有`任何列` 具有相同 `html_hash` 且 `md_path != null` 的資料」，若有，代表 enriched document markdown 之前已經透過 LLM 生成且存入 GCS:
    - 判定 colleciotn `multimodal_llm_enrichment_logs` 的欄位 `cache_hit=true`。
    - Insert collection `multimodal_llm_enrichment_logs` (含 cache_hit、trigger、tokens)。
    - 拿著搜尋到的 `md_path` (路徑架構應為: `gs://onenote-vaults/processed-notes/<onenote_user_id>/`) 去下載 enriched document 後渲染在審查 UI 上，**不打 LLM**。
    - 跳過 step 3.
    > **此步驟定義為 「冪等快取」，得到的本體其實是透過 `onenote_note_metadata` 的 `html_hash` 資料去 GCS 找到已經持久化的 md 檔**，所以在 UI 上對「同一 hash」的資料讀取情境時，都是重複利用此步驟。

  3. 若 md_path 均為 null，代表該筆記完全沒有經過 LLM 做 enrichment 且存入 GCS:
    - 判定 colleciotn `multimodal_llm_enrichment_logs` 的欄位 `cache_hit=false`。
    - 以 BeautifulSoup `html.parser` 解析 html，去掉 markup 標記取出文本主幹，文本中應該要清理 (clean&transform) 加上 `![<文字標籤>](_images/<檔名>)`，告訴模型這裡有張圖片。
    - 把圖片 URI (collection `onenote_note_metadata` 欄位 `img_path` 可查到) 與文本交給 multimodal LLM 做 document enrichment 轉成 markdown。讓模型將需判讀圖片內容、在對應 `![]()` 連結下方生成擴寫出「AI生成圖釋」。
    - 存 md 檔到 `gs://onenote-vaults/processed-notes/<onenote_user_id>/` 下的分區。
    - Insert collection `multimodal_llm_enrichment_logs` (含 cache_hit、trigger、tokens)
    - Upsert collection `onenote_note_metadata` (md_path、md_md5、md_exported_at、status=pending_review)。

  4. 若使用者移步到較早版本的筆記，則也是進行 step 1-3 步驟來建立 enriched document markdown。

  5. Hierarchy of blobs on GCS (dt=值，對齊 bronze 的 dt 值)
    ```plaintext
    gs://onenote-vaults/processed-notes/<onenote_user_id>/
    ├── <notebook_name>/
    │       └── <section_name>/
    │               └── dt=<bronze執行日>/          # 注意是 bronze 的執行日
    │                       └── <page_name>.md     # 放 LLM enriched documents
    ```

  6. on-demand 觸發後，若對於 LLM 生成結果不滿意，允許使用者在 UI 上操作 `regenerate` 按鈕重新生成，生成機制有兩層管制:
    - 服務級別設計 circuit breaker：若 LLM API **連續失敗/超時達門檻（如 5 次）**，則暫停 on-demand enrich 一段時間，避免服務異常時持續打壞掉的 API。期間筆記狀態 (= collection `onenote_note_metadata` 欄位 `status`) 維持 `bronze_stored`，不鎖死使用者操作。
    - 單篇筆記的 `regenerate` 成本上限由預設 quota 做控制 (同一 `html_hash` 在 `multimodal_llm_enrichment_logs` 欄位 `trigger` 值最多出現兩筆 `regenerate`)。

> 將來 `onenote_note_metadata` 查詢量過大，或許考慮在前面加 Redis，專門存放會被 step 2 捕捉到的 markdown。

---

### Silver → Gold 過渡期 — UI 互動模式

- **對照頁設計**：Streamlit 左渲染 bronze html、右渲染 silver layer 產出的 enriched document markdown，但仍保留上方圓鈕可切換同名筆記 1~5 任一版本（對應1~5種不同 `dt=` 分區）。
- **on-demand 首次載入**：圓鈕點到一個 `md_path=null`（=從未 enrich）的版本時，當場呼叫 Silver 服務生成 md，若點到已生成過的版本則直接讀 GCS 既有 md（cache hit、零成本）。沒被點過的版本永不 enrich。
- **防貪心重複呼叫**：切換到生成過的版本必須走[冪等快取](#silver-layer--on-demand-觸發--冪等快取)，不重複打 LLM，唯一會主動產生新 LLM call 的是認為品質不好，按下 `regenerate` 按鈕，請 silver layer 執行 `regenerate` 任務。
- **進入 Gold layer 方式**：按下某版 `approve` 或 `reject`。

---

### Gold layer — 核可後歸檔

> 將 silver layer 產出的 enriched document 且經人工 `approved`/`rejected` 的 md 做最終格式歸檔，並驗證資料品質記載入 metadata。

- Hierarchy of blobs
```plaintext
gs://onenote-vaults/archived-notes/<onenote_user_id>/
├── <notebook_name>/
│       └── <section_name>/
│               └── dt=<bronze執行日>/             # 注意是 bronze 的執行日，從 C3 可讀 dt 取得
│                       ├── <page_name>.md.       # 從 processed_note 讀取後清理存入
│                       └── _images/
│                             └── image01.png     # 從 raw-notes 複製過來，每份筆記的 img 來自
                                                  # 哪個 raw-notes/ 下的路徑，可以從 C3
                                                  # 讀 img_path 得知。
```

- Load 步驟:
  - 允許使用者觸發 `approved` 或 `rejected` 任一行為，由 flask routing 到不同處理程序，如下說明：
  - 若為`rejected`:
    1. 這一篇的筆記 `approved`、`reject`、`regenerate` 按鈕立即失效，前端顯示 `已退件`
    2. 以 page_id & dt 為主鍵，upsert `onenote_note_metadata`，更新欄位 review_result、reviewed_at、reviewed_by_role、error_msg (若有例外)。
    3. 回讀 `gs://onenote-vaults/processed-notes/<onenote_user_id>/` 被退件的 md 檔，萃取 frontmatter 區的 metadata (tags、date、type、alias)。
    4. 以 page_id & dt 為主鍵，Upsert `onenote_note_metadata`，更新欄位 tags、date、type、alias、valid_img_cont，[schema 見後方](#collection-3-簡稱-c3-onenote_note_metadata)。

  - 若為`approved`:
    1. 將 md 從 `gs://onenote-vaults/processed-notes/<onenote_user_id>/...` 複製到 `gs://onenote-vaults/archived-notes/<onenote_user_id>/`，得到新 md5；將 md 引用的 png 從 `gs://onenote-vaults/raw-notes/<onenote_user_id>/...` 複製到 `gs://onenote-vaults/archived-notes/<onenote_user_id>/`，得到新 md5。
    2. 前端顯示 `archive 完成` 後，歸檔的那份筆記以及比它舊的筆記 (dt 較早) 的所有 `approved`、`reject`、`regenerate` 按鈕立即失效。
    3. 以 page_id & dt 為主鍵，upsert `onenote_note_metadata`，更新欄位 archived_at、img_archive_path、md_archive_path、review_result、reviewed_at、reviewed_by_role、error_msg (若有例外)。
    4. 歸檔後回讀 `gs://onenote-vaults/archived-notes/<onenote_user_id>/` 那份剛剛歸檔的 md 檔，萃取 frontmatter 區的 metadata (tags、date、type、alias)。
    5. 以 page_id & dt 為主鍵，Upsert `onenote_note_metadata`，更新欄位 tags、date、type、alias、valid_img_cont，[schema 見後方](#collection-3-簡稱-c3-onenote_note_metadata)。

### Followup policies out of bronze/silver/gold layer

  > bronze 的 html 留存於各 `dt=` 分區、不自動刪除，保留期人工評估。
  > 存在 archived-notes/ 下的資料 (md、png) 的向量化工作由另一條解耦的 pipeline (分支 feature/etl-pipeline task06) 開發後額外部署，避免初期模型調整頻繁但過度管道依賴性太黏而不易維護。
  > 向量化以 hash 做冪等：避免同內容重複 embed。embed 存 MongoDB Atlas Vector Database collection `note_vectors_multimodal`。

---

## Schema Definition

> 遵守人、事、時、地、結果 + primary key

### Collection 1 (簡稱 `C1`): `onenote_graph_api_logs`
- Purpose：下載 OneNote html 時記錄。**Written：keep appending。Reading：trouble shooting 才查。**

| 欄位名稱      | MongoDB 型別 | Must | 說明 |
| ------------ | ---------- | ---- | ---- |
| _id          | ObjectId   | Y    | 自動主鍵 |
| page_id      | String     | Y    | OneNote 頁面 ID，關聯其他 collection |
| timestamp    | ISODate    | Y    | 寫入時間 (UTC+0) |
| event_type   | String     | Y    | 固定值：onenote_api_download |
| method       | String     | Y    | GET |
| api_endpoint | String     | Y    | API Endpoint URL |
| request_id   | String     | Y    | UUID ，同輪請求有相同 Request ID，不論 retry |
| attempt_id   | Int32      | Y    | 呼叫次數，retry 第一次為 2 |
| status       | String     | Y    | success、failure |
| status_code  | Int32      | Y    | HTTP Status Code |
| latency_ms   | Int32      | Y    | API 回應耗時 (ms) |
| html_hash    | String     | Y    | 下載後 html 原始碼 hash（變動判定依據） |
| html_path    | String     | N    | 下載的 html 之完整 GCS 路徑 (gs://..../note.html)，downloaded=false時為 null |
| downloaded   | Bool       | Y    | 本次是否實際下載，html_hash 相同則 false |
| environment  | String     | Y    | local、dev、prod |
| error_msg    | String     | N    | 失敗訊息 |

### Collection 2 (簡稱 `C2`): `multimodal_llm_enrichment_logs`
- Purpose：呼叫 LLM 做 enrichment 時記錄。**Written：keep appending。Reading：trouble shooting 或追 token 帳單時查。**

| 欄位名稱         | MongoDB 型別 | Must | 說明 |
| --------------- | ---------- | ---- | ---- |
| _id             | ObjectId   | Y    | 自動主鍵 |
| page_id         | String     | Y    | 關聯其他 collection |
| html_hash       | String     | Y    | 輸入 html 的 hash（冪等鍵） |
| timestamp       | Date       | Y    | 寫入時間 (UTC+0) |
| event_type      | String     | Y    | 固定值：llm_enrichment_call |
| model           | String     | Y    | LLM 名稱 |
| cache_hit       | Bool       | Y    | true 表示讀快取、未實際打 LLM |
| trigger         | String     | Y    | on_demand、regenerate |
| status          | String     | Y    | success、failure |
| latency_ms      | Int32      | Y    | 回應耗時 (ms) |
| input_tokens    | Int32      | N    | cache_hit 時為 0 |
| output_tokens   | Int32      | N    | cache_hit 時為 0 |
| total_tokens    | Int32      | N    | cache_hit 時為 0 |
| environment     | String     | Y    | local、dev、prod |
| error_msg       | String     | N    | 失敗訊息 |

### Collection 3 (簡稱 `C3`): `onenote_note_metadata`
- Purpose：記錄每一個 `dt=` 版本在 html → md → archived 之間的血緣與生命週期。**Written：upsert。Reading：頻繁查 (hash 值判定變動、快取查找、UI 渲染)。**

| 欄位名稱            | MongoDB 型別   | Must | 說明 |
| ------------------ | ------------- | ---- | ---- |
| _id                | ObjectId      | Y    | 自動主鍵 |
| onenote_user_id    | String        | Y    | OneNote 使用者 ID或員工編號 |
| page_id            | String        | Y    | OneNote 頁面 ID |
| notebook           | String        | Y    | Notebook 名稱 |
| section            | String        | Y    | Section 名稱 |
| page_title         | String        | Y    | 頁面標題 |
| dt                 | String        | Y    | bronze 執行日分區（一篇筆記最多一dt一個版本，故不同dt可凸顯一份筆記在跨日的多版本，dt也可作筆記的版本鍵） |
| html_hash          | String        | Y    | html 原始碼 hash（變動判定 / enrichment 冪等鍵） |
| html_md5           | String        | Y    | GCS html 物件 md5 |
| html_path          | String        | Y    | 含 dt= 分區的 GCS 路徑 |
| html_downloaded_at | Date          | Y    | 下載時間（UI 多版本對照排序依據） |
| img_md5            | Array<String> | N    | 引用 png 的 GCS md5，無圖為 [] |
| img_path           | Array<String> | N    | 引用 png 的 GCS 路徑，無圖為 [] |
| md_path            | String        | N    | silver md 路徑，未生成為 null |
| md_md5             | String        | N    | silver md 的 GCS md5 |
| md_exported_at     | Date          | N    | enrichment 產出時間 |
| embedded_status    | Bool          | Y    | 是否已成功向量化（gold 向量化冪等依據） |
| status             | String        | Y    | 生命週期狀態，見下表 |
| review_result      | String        | N    | null、approved、rejected |
| reviewed_by_role   | String        | N    | null、ML engineer、note_owner、dept_senior_specialist |
| reviewed_at        | Date          | N    | 審核時間 |
| md_archive_path    | String        | N    | gold 歸檔 md 路徑 |
| img_archive_path   | Array<String> | N    | gold 歸檔 png 路徑集合 |
| archived_at        | Date          | N    | 歸檔完成時間 |
| error_msg          | String        | N    | C1/C2 未接住的其他關卡錯誤 |
| md_frontmatter     | Object        | N    | archive & reject 後觸發寫入 md 的 frontmatter，作為筆記識別與追蹤資料品質用 |
| md_frontmatter.tags | Array<String> | N    | 在 md frontmatter 欄位裡面，筆記的關鍵字清單 |
| md_frontmatter.date | Date          | N    | md frontmatter 欄位裡面，原始筆記上傳到 html 時間 |
| md_frontmatter.type | String        | N    | md frontmatter 欄位裡面，筆記的大類別 |
| md_frontmatter.alias | Array<String> | N   | md frontmatter 欄位裡面，單篇筆記的別名 |
| md_frontmatter.valid_img | int      | N    | md frontmatter 欄位裡面，筆記中能正常解析與渲染的圖片數量 |

- Indexes
```javascript
  { page_id: 1, dt: -1 }                          // 取某頁最新版 / 多版本對照
  { page_id: 1, html_hash: 1 }                    // hash 值判定變動、enrichment 快取查找
  { notebook: 1, section: 1, page_title: 1, html_downloaded_at: -1 }  // UI 多版本對照 groupby + 排序
  { embedded_status: 1 }
  { status: 1 }
  { archived_at: -1 }
```

### Status, Review_result, Embedded_status 取值定義
| Scenario | status | review_result | embedded_status |
| -------- | ------ | ------------- | --------------- |
| html 下載但寫入失敗 | fetched_failed（從 C1 回推 error） | null | false |
| hash 相同、未下載 | skipped_unchanged | null | — |
| 新版下載完成、待 on-demand enrich | bronze_stored | null | false |
| LLM enrichment 進行中（on-demand 觸發） | fetched | null | false |
| LLM 生成失敗 | enrich_failed（從 C2 回推 error） | null | false |
| 生成成功、等人審查 | pending_review | null | false |
| 按通過、歸檔成功 | archived | approved | true |
| 按通過、歸檔中途失敗 | archive_failed | approved | false |
| 針對性單一筆記退件 | review_closed | rejected | false |
| 核可日當天的候選筆記已有其他份歸檔<br>，間接造成此份筆記過期結束審閱期 | review_closed | overwritten 或 rejected | false |

> `overwritten` 僅發生在，歸檔的筆記之 html_hash 跟被退件其他筆記 html_hash 相同。若歸檔的筆記之 html_hash 跟其他同時間競選的筆記之 html_hash 不同，則既為 `rejected`。需要這樣設計是因為，如果不區分 `overwritten` 這個情境，統一把被退件的筆記判定為 `rejected`，則未來在分析好壞筆記的時候，被核可的筆記內容將會同時出現 `rejected` 與 `approved` 兩種狀態，那就區分不出來他是好或壞了，誤導分析。

> 語意釐清：approved ≠ archived，審核通過後仍視檔案系統運作分 archive_failed / archived，以 status 為最終判斷依據。

### Example - 同名筆記在 week 1 ~ week 4 的變化歷程（純 Lazy Loading）

#### Week 1~3

每週 ETL 下載新版、算 hash、存 GCS 分區，**都不進入審查頁呼叫 LLM**。

**C1 `onenote_graph_api_logs` (每週各新增 1 列，共 3 列)**

| page_id |     dt     | html_hash | downloaded | status_code | status |
|---------|------------|-----------|------------|-------------|--------|
|   p1    | 2026-06-01 |     H1    |    true    |    200     | success |
|   p1    | 2026-06-08 |     H2    |    true    |    200     | success |
|   p1    | 2026-06-15 |     H3    |    true    |    200     | success |

**C2 `multimodal_llm_enrichment_logs`**

三週皆無新增列。

**C3 `onenote_note_metadata`（三列，全為 bronze_stored）**

| page_id |     dt     | html_hash | md_path | status | embedded_status | review_result |
|---------|------------|-----------|---------|--------|-----------------|---------------|
|   p1    | 2026-06-01 |     H1    |  null | bronze_stored |   false   |   null   |
|   p1    | 2026-06-08 |     H2    |  null | bronze_stored |   false   |   null   |
|   p1    | 2026-06-15 |     H3    |  null | bronze_stored |   false   |   null   |

> 三個版本都靜靜躺在 `bronze_stored` 的 `raw-notes/` 下，`md_path` 全 null，也沒有 `pending_review` 的 markdown 文件。

#### Week 4 - 筆記透過 OneNote 軟體被改回 H2 一樣的內容，然後重新下載。當周人類登入審查頁，查看 06-22 版本 -> 06-15 版本 -> 06-08 版本，比對後核可 06-22 版本。

**C1**

| page_id |     dt     | html_hash | downloaded | status_code | status |
|---------|------------|-----------|------------|-------------|--------|
|   p1    | 2026-06-01 |     H1    |    true    |    200     | success |
|   p1    | 2026-06-08 |     H2    |    true    |    200     | success |
|   p1    | 2026-06-15 |     H3    |    true    |    200     | success |
|   p1    | 2026-06-22 |     H2    |    true    |    200     | success |

**C2 - 當周人類登入審查頁，查看 06-22 版本 -> 06-15 版本 -> 06-08 版本。**

| page_id | timestamp  | html_hash | trigger | cache_hit | total_tokens | status |
|---------|------------|-----------|---------|-----------|--------------|--------|
|   p1    |     t1     |     H2    |on_demand|  false    |      1750    | success|
|   p1    |     t2     |     H3    |on_demand|  false    |      1247    | success|
|   p1    |     t3     |     H2    |on_demand|  true     |       0      | success|

> 第三列，t3 查看的 06-08 版本之 html_hash 跟 06-22 版本相同，所以直接取 06-22 生成的 md 即可，第三列的`cache_hit=true` 表沒有打過 LLM。

**C3 比對後核可 06-22 版本**

- 核可前一刻:

| page_id |   dt  | html_hash | md_path | status | embedded_status | review_result |
|---------|-------|-----------|---------|--------|-----------------|---------------|
|   p1    | 06-01 |     H1    |   null  | bronze_stored | false | null |
|   p1    | 06-08 |     H2    | `在process-notes/dt=06-22` | `pending_review` | false | null |
|   p1    | 06-15 |     H3    | `在process-notes/dt=06-15` | `pending_review` | false | null |
|   p1    | 06-22 |     H2    | `在process-notes/dt=06-22` | `pending_review` | false | approved |

- 核可後:

| page_id |   dt  | html_hash | md_path | status | embedded_status | review_result | md_archive_path |
|---------|-------|-----------|---------|--------|-----------------|---------------|---------------|
|   p1    | 06-01 |     H1    |   null  | `bronze_stored` | false | null | null |
|   p1    | 06-08 |     H2    | `在process-notes/dt=06-22` | `review_closed` | false | `overwritten` | null |
|   p1    | 06-15 |     H3    | `在process-notes/dt=06-15` | `review_closed` | false | `rejected` | null |
|   p1    | 06-22 |     H2    | `在process-notes/dt=06-22` | `archived` | false | `approved` | `在archived-notes/dt=06-22` |

---

## Development strategy

### **地端測試階段**
**`feature/html-to-markdown` 分支**

1. **Extract**: 同[前述](#bronze-layer--多版本-raw-notes-保存)

2. **Bronze layer**: 同[前述](#bronze--silver-過渡期--etl-只到-bronzesilver-純-on-demand)。每週腳本下載 + hash + 存版本 + upsert C3（status=bronze_stored）即結束。

3. **Silver layer**: 同[前述](#silver-layer--on-demand-觸發-冪等快取)。由 UI 點擊觸發，含 LLM API 連續失敗的服務級守門。

**切到 `feature/dashboard-ui` 分支**

4a. **on-demand Silver 觸發**: 參考既有 Archive_service 的框架，繼承 `feature/html-to-markdown` 分支的 silver 後包成獨立端點。

4. **Gold layer**: 參考[前述1](#gold-layer--核可後歸檔)與[前述2](#silver--gold-過渡期--ui-互動模式)。參考既有 Archive_service 的框架包成獨立端點，頁面加 demo 級登入窗。

5. **舊版 html 保留**：各 `dt=` 分區 html 不自動刪，保留期人工於 GCP console 評估，不過度開發。

### **雲端部署階段（同部門跨帳號，GCP 為平台）**

6. Merge `feature/dashboard-ui` → `develop`，包 image 推 Artifact Registry、跑 Cloud Run。Streamlit 服務帳戶僅持 staging（raw_note / processed_note）**唯讀**；頁面加 demo 級登入窗。

7. gold archive 端點包成獨立 image，Cloud Run 持 `archived_note` **寫入** 權限。

7b. Silver enrich 端點包 image，Cloud Run 持 `processed_note` **寫入** 權限。

8. log 仍寫入同一個 MongoDB Atlas（地端階段已整併），雲端只是換 Cloud Run 容器讀寫同一 Atlas。

> 核心原則：Streamlit 直連 Atlas / GCS 皆**唯讀**僅作狀態顯示；所有寫入 GCS 分別由 **Silver enrich 端點**與 **Gold archive 端點**執行。LLM 與 embedding 兩段都以 `html_hash` / 內容 hash 做冪等、hash 值判定變動，整條鏈不重複燒 token。
