# # Task07 Hand-over：OneNote 多版本保留 × LLM 省呼叫 ETL 開發計畫

> **開發目標**： 延續 Task07 的 OneNote → Markdown → 向量庫 ETL，本分支針對「企業部門公務筆記」場景強化兩個目標：  \
> 1. **Bronze layer: 允許保留同一份筆記的舊版本 HTML**，讓資料源歷史可追溯、不互相覆蓋，核心手段是「在 GCS 以 `dt=` 日期分區保存多版本 OneNote 的同名筆記，檔型為 html」。  \
> 2. **Silver & Gold layer: 避免浪費 multimodal LLM 的 enrichment 任務呼叫**，核心手段是「以 `html_hash` 為冪等鍵為 LLM enriched markdown document 建立快取，存在 GCS」、「ETL 階段完全不主動呼叫 LLM，所有 enrichment 改為**純 Lazy Loading（on-demand）**：等到使用者登入審查 UI、點擊某個尚未處理的版本時，才當場觸發 Silver 流程（查快取 → 呼叫 LLM → 存 MD）」、「以 `html_hash` 快取兜底，即使使用者重複點擊同一版本也不會產生額外 token」。  \
> 相較個人Task01 Obsidian 筆記（流程1，改動少、可全量 eager 處理），Task 07 的 OneNote 公務筆記改動頻繁、且 human-in-loop 審查易塞車。**本企劃刻意不引入背景預熱與跨版本狀態機**：因為改動頻繁時，預先 enrich 出來的中間版多半沒人會選，主動生成只是燒 token；改用 Lazy Loading 後，ETL 與人類審查兩端透過 GCS 既有檔案解耦，架構單向、清晰，且省 token 的效益靠 `html_hash` 快取自然達成，毋須複雜的 superseded 標記與預熱閘門。

## 前置條件確認
**執行環境**：macOS with Web browser / VS Code IDE / pyenv (Python 3.14) / Poetry
**AI tool**：Claude code + OpenSpec skill
**資料授權**：本人 Delegated Authorization，員工於瀏覽器登入授權後，呼叫端取得 OneNote Graph API token
**開發分支**：
  - `feature/html-to-markdown`：負責開發 Bronze layer（OneNote Graph API 下載 html 至 GCS、以 `dt=` 分區保留多版本、hash 值判定變動）與 Silver layer 的 enrichment **服務本體**（`html.parser` → multimodal LLM → enriched markdown、`html_hash` 冪等快取、LLM 服務級守門）。此 Silver 服務不在 ETL 主動執行，而是**作為可被 UI on-demand 呼叫的模組**對外提供。
  - existing branch, `feature/dashboard-ui`：負責開發 Gold layer 與 **on-demand 觸發點**——多版本對照審查頁 (圓鈕切換同名筆記 1~5 版)，使用者點擊未處理版本時呼叫 Silver 服務即時生成 md，人工核可後自動化歸檔 (archive endpoint)，同名筆記一次只能認可一份。
**目的整併至分支**：`develop`

---

## 專案資料夾結構

```
feature/onenote-versioned-etl/
├── .env
├── poetry.lock
├── pyproject.toml
│
├── .claude/
│   ├── commands/
│   ├── hooks/
│   └── skills/
│
├── task07_onenote_versioned_etl/
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

---

## Task 07 — OneNote 多版本 ETL

### 資料來源
Microsoft OneNote Graph API（Delegated Authorization）

### Tools, Framework
- msal（取得 delegated token）
- requests（下載 html 與引用圖片）
- BeautifulSoup / html.parser
- google gen ai sdk（multimodal LLM enrichment）

### database, data storage
- MongoDB Atlas（api logs、LLM logs、note metadata (含 enrichment 快取索引)、向量庫）
- GCS（data lake，以 `dt=` 分區保存 html、md、png 多版本）

---

### Bronze layer — 多版本 raw notes 保存

> **版本保留的設計核心**：路徑帶 `dt=<bronze執行日>` 分區。同一頁筆記每次 hash 有變動就寫進新的日期資料夾，舊版本留在舊分區、不被覆蓋。歷史可完整回溯。

- Hierarchy of blobs
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

- Extract 步驟
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
---

### Bronze → Silver 過渡期 — ETL 只到 Bronze，Silver 純 on-demand

> **省 LLM calls 的設計核心**：ETL（每週腳本）**只做到 Bronze**——下載 + hash + 存版本 + 更新 C3，全程不呼叫 LLM。Silver 的 enrichment **完全交給 UI 端觸發**：使用者登入審查頁、點擊某個尚未處理的版本時，才當場走 Silver 流程。沒有背景預熱、沒有佇列空/非空的分流閘門、沒有跨版本 `superseded` 標記。

- 設計取捨（為何改為純 Lazy Loading）
  - 公務筆記改動頻繁、人工審查易塞車。若每週主動預熱最新版，塞車時預熱出來的中間版多半沒人會選，等於白燒 token。
  - 改為 on-demand 後，**省 token 的效益完全由 `html_hash` 快取自然達成**：使用者沒點的版本永遠不 enrich；點過的版本第二次點命中快取、零成本。毋須用狀態機去「決定這週該不該動手」。
  - ETL 與人類審查兩端透過 GCS 既有檔案 + C3 metadata 解耦，資料流**單向**（Bronze 存檔 → 使用者點擊 → Silver 生成），不會有 `pending_review → bronze_stored → superseded` 的中間態 race condition。

- 服務級守門（取代原本綁「單筆記版本次數」的斷路器）
  - 斷路器**不再綁定單一筆記的歷史版本次數**，而是設在 **LLM 服務級別**：若 LLM API **連續失敗/超時達門檻（如 5 次）**，則暫停 on-demand enrich 一段時間，避免服務異常時持續打壞掉的 API。期間筆記狀態維持 `bronze_stored`，**不懲罰任何單一筆記**、不鎖死使用者操作。
  - 單筆記的成本上限則由 Silver→Gold 既有的 `regenerate` quota 控制（同一 `html_hash` 最多 regenerate 2 次）。
  - 此守門為輕量邏輯，收進 `t_html_to_markdown.py` 的 LLM 呼叫包裝，不另開模組。

---

### Silver layer — on-demand 觸發 × 冪等快取

> **省 LLM  的設計核心之二**：enriched document markdown 結果以 `html_hash` 為快取鍵，同一份 html 永遠只打一次 LLM。

- Hierarchy of blobs（md 存 silver，分區對齊 bronze）
```plaintext
gs://onenote-vaults/processed-notes/<onenote_user_id>/
├── <notebook_name>/
│       └── <section_name>/
│               └── dt=<bronze執行日>/             # 注意是 bronze 的執行日
│                       └── <page_name>_001.md    ⬅️ 放 LLM enriched documents + 流水號
```

- 觸發時機**只有一種**：**on-demand**——使用者在審查 UI 點擊某個 `bronze_stored`（尚未生成 md）的版本時即時觸發。針對被點到的那一版 html 筆記（不限定最新版；舊版被點同樣即時生成），ETL 階段不主動觸發。

- Transformation 步驟
  1. 取該版 `html_hash`，先**查快取**：拿 html_hash 去 collection `onenote_note_metadata` 找「有沒有一列 相同 `html_hash` 且 `md_path != null` 的資料」。
    - 若有 (即 enriched document markdown 存在): 判定且寫入 colleciotn `multimodal_llm_enrichment_logs` 的欄位 `cache_hit=true`，直接讀 `gs://onenote-vaults/processed-notes/<onenote_user_id>/` 下的既有 md，**不打 LLM，跳過 step 2**。
    - 若無：判定且寫入 colleciotn `multimodal_llm_enrichment_logs` 的欄位 `cache_hit=false`，並執行 step 2 生成文件。
  2. `html.parser` 解析 html，交給 multimodal LLM 做 document enrichment 轉成 markdown，存 md 檔到 `gs://onenote-vaults/processed-notes/<onenote_user_id>/` 下的分區。
    > **多模態 enrichment**：除了送入 html 純文字，亦把該頁內嵌圖片（C3 `img_path` 記錄的 `gs://` URI）以 `types.Part.from_uri()` 一併送進 `generate_content()`，讓 model 實際判讀圖片內容、在對應 `![]()` 連結下方生成更精準的「AI生成圖釋」。圖片以「文字標籤 `_images/<檔名>` + 圖片 Part」成對附上，供 model 與內文連結對齊。
  > **冪等快取得到的本體其實是透過 `onenote_note_metadata` 的 `html_hash` 資料去 GCS 找到已經持久化的 md 檔**，所以「同一 hash」取資料的請求（員工切換/重看版本）的工作時，都是重複利用步驟 1。
  3. 更新資料庫:
  - Insert collection `multimodal_llm_enrichment_logs` (含 cache_hit、trigger、tokens)
  - Upsert collection `onenote_note_metadata` (md_path、md_md5、md_exported_at、status=pending_review)

*補充: 快取本體不放 Streamlit cache 理由是，on-demand enrich 雖由 UI 觸發，但生成結果（md）需跨 session、跨 process 持久可查（其他使用者或下次登入都要看得到），Streamlit 記憶體不能當事實來源。持久、跨 process 的事實來源 = `onenote_note_metadata`的 html_hash + GCS（md）媒合出的筆記內容；`st.cache_data` 只當選配的 session 內加速層。將來 `onenote_note_metadata` 查詢量過大才考慮在前面加 Redis。*

---

### Silver → Gold 過渡期 — 多版本對照人工審查

- Streamlit 對照頁：左渲染 bronze html、右渲染 silver layer 產出的 enriched document markdown (md)，但仍保留上方圓鈕可切換同名筆記 1~5 任一版本（對應1~5種不同 `dt=` 分區）。
- **on-demand 首次載入**：圓鈕點到一個 `md_path=null`（從未 enrich）的版本時，當場呼叫 Silver 服務生成 md（cache miss、實際打 LLM）；點到已生成過的版本則直接讀 GCS 既有 md（cache hit、零成本）。沒被點到的版本永不 enrich。
- 在 streamlit 人工確認 LLM 產出品質、不偏離 bronze 本意。
- **同名一次只認可一份**：按下某版 `approved` → 觸發 gold layer；其餘同名版本的歸檔按鈕失效、按下 `reject` 則不進 gold layer。
- **防貪心重複呼叫**：同一版本重看走快取零成本；唯一會主動產生新 LLM call 的是認為品質不好、按下 `regenerate` 按鈕，對此 `regenerate` 設小 quota（同一 `html_hash` 最多 regenerate 2 次）即可。

---

### Gold layer — 最終清洗、歸檔與向量化

> 將 silver 產出且經人工 `approved` 的 md 做最終格式清洗與向量化。

- Hierarchy of blobs
```plaintext
gs://<onenote_user_id>/from_onenote/archived_note
├── <notebook_name>/
│       └── <section_name>/
│               ├── <page_name>.md          ⬅️ cleaned，從 processed_note 清洗複製
│               └── _images/
│                     └── image01.png        ⬅️ cleaned，從 processed_note 複製
```

- Load 步驟:
  1. cleaned md 與 png 存 `gs://<onenote_user_id>/from_onenote/archived_note/...`，各自有 md5。
  2. 向量化資料存 MongoDB Atlas Vector Database collection `note_vectors_multimodal`。
  3. **向量化亦以 hash 做冪等**：避免同內容重複 embed。
  > bronze 的 html 留存於各 `dt=` 分區、不自動刪除，保留期人工評估。

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
| 被退回 | review_closed | rejected | false |

> approved ≠ archived，審核通過後仍視檔案系統運作分 archive_failed / archived，以 status 為最終判斷依據。
>
> 同名筆記「一次只認可一份」由 Gold/UI 控制：approve 某版後，UI 讀回 C3 發現該 page_id 已有 `archived` 版本，其餘版本歸檔按鈕即失效。不需要 `superseded` 旗標。

### Example - 同名筆記在 week 1 ~ week 4 的變化歷程（純 Lazy Loading）
> 下面用同一份筆記 `page_id=p1`、人類連續幾週沒登入、第 4 週才回來審查走一遍。`vx` 代表筆記版本、`Hx`代表筆記版本的 `html_hash`：v1=H1、v2=H2、v3=H3、v4=H4。C1、C2、C3 代表前述提到的 collection 1、2、3。
> **重點：ETL 每週只跑 Bronze、完全不呼叫 LLM；C2 只有在第 4 週人類點擊版本時才出現列。沒人點到的 v2、v3 永遠不 enrich，這就是省 token 的地方。**

#### Week 1~3（dt=06-01 / 06-08 / 06-15）：v1、v2、v3 陸續進版 → 只存 Bronze

每週 ETL 下載新版、算 hash、存 GCS 分區、upsert C3，**都不呼叫 LLM**。

**C1 `onenote_graph_api_logs`（每週各新增 1 列，共 3 列）**

| page_id | html_hash | downloaded | status_code | status |
|---|---|---|---|---|
| p1 | H1 | true | 200 | success |
| p1 | H2 | true | 200 | success |
| p1 | H3 | true | 200 | success |

**C2 `multimodal_llm_enrichment_logs` → 三週皆無新增列**（ETL 不呼叫 LLM）

**C3 `onenote_note_metadata`（三列，全為 bronze_stored）**

| dt | html_hash | md_path | status | embedded_status | review_result |
|---|---|---|---|---|---|
| 06-01 | H1 | null | bronze_stored | false | null |
| 06-08 | H2 | null | bronze_stored | false | null |
| 06-15 | H3 | null | bronze_stored | false | null |

> 三個版本都靜靜躺在 Bronze，`md_path` 全 null。沒有 `pending_review` 把任何閘門關著，也沒有任何 superseded 標記。

#### Week 4（dt=2026-06-22）：v4 進版（Bronze）→ 人類登入 → on-demand enrich → 核可歸檔

本週 ETL 一樣只下載 v4 存 Bronze；之後人類登入審查頁，**只點了最新版 v4**，比對滿意後核可。

**C1（再新增 1 列）**

| page_id | html_hash | downloaded | status_code | status |
|---|---|---|---|---|
| p1 | H4 | true | 200 | success |

**C2（人類點 v4 觸發；第一次 miss、切走再切回 hit，共 2 列）**

| page_id | html_hash | trigger | cache_hit | total_tokens | status |
|---|---|---|---|---|---|
| p1 | H4 | on_demand | false | 1750 | success |
| p1 | H4 | on_demand | **true** | 0 | success |

> 第一列：首次點 v4，cache miss、實際 enrich。第二列：員工切去看別版又切回 v4，命中快取、**不打 LLM**（tokens=0）。v1/v2/v3 因為沒人點，C2 從頭到尾沒有它們的列。

**C3（最終四列狀態）**

| dt | html_hash | md_path | status | embedded_status | review_result |
|---|---|---|---|---|---|
| 06-01 | H1 | null | bronze_stored | false | null |
| 06-08 | H2 | null | bronze_stored | false | null |
| 06-15 | H3 | null | bronze_stored | false | null |
| 06-22 | H4 | …/dt=06-22/Note.md | archived | **true** | approved |

> v1~v3 維持 `bronze_stored`（仍可被未來某次點擊即時 enrich），v4 被核可、歸檔、向量化。整段流程單向、無中間態翻轉，也不需要 superseded 旗標——「同名一次只認可一份」由 UI 讀回 C3 是否已有 `archived` 版本來把關。

---

## Development strategy

### **地端測試階段**
**此分支**

1. **Extract**: 同[前述](#bronze-layer--多版本-raw-notes-保存)

2. **Bronze 收尾 (ETL 只到 Bronze、不呼叫 LLM)**: 同[前述](#bronze--silver-過渡期--etl-只到-bronzesilver-純-on-demand)。每週腳本下載 + hash + 存版本 + upsert C3（status=bronze_stored）即結束。

3. **Silver (on-demand enrichment + hash 冪等快取 + 服務級守門)**: 同[前述](#silver-layer--on-demand-觸發-冪等快取)。由 UI 點擊觸發，含 LLM API 連續失敗的服務級守門。

**切到 `feature/dashboard-ui` 分支**

4a. **on-demand Silver 觸發（端點化，比照 Archive）**: Streamlit 本身維持唯讀；點到 `md_path=null` 的版本時，只帶 page_id + dt 呼叫 **Silver enrich service**（即 `feature/html-to-markdown` 分支的 enrichment 服務本體）。由該服務查快取 → 必要時打 LLM → 寫 md 到 GCS `processed_note/` → upsert C3（status=pending_review）。Streamlit 收到結果後渲染。

4. **Gold layer**: 參考[前述1](#silver--gold-過渡期--多版本對照人工審查)與[前述2](#gold-layer--最終清洗歸檔與向量化)。approved 觸發步驟 5，reject 記 `review_closed`，頁面加 demo 級登入窗。

5. **Archive 端點（獨立腳本）**: Streamlit 不自寫 vault，只帶 page_id + dt + 登入者角色呼叫 Archive service。Archive 讀 silver、寫 `gs://<onenote_user_id>/from_onenote/archived_note/`：複製 png、改寫 md 圖片連結為相對路徑後寫 `cleaned.md`，並向量化寫入 `note_vectors_multimodal`（向量化亦以 hash 冪等）。

6. **Archive upsert `onenote_note_metadata`**：status、review_result、reviewed_by_role、reviewed_at、md_archive_path、img_archive_path、archived_at、embedded_status=true。

7. **防重複檢核**：Streamlit 渲染時讀回 `onenote_note_metadata`，已歸檔頁顯示「已歸檔」橫幅並停用按鈕；同名其餘版本按鈕失效。

8. **舊版 html 保留**：各 `dt=` 分區 html 不自動刪，保留期人工於 GCP console 評估，不過度開發。

### **雲端部署階段（同部門跨帳號，GCP 為平台）**

9. Merge `feature/dashboard-ui` → `develop`，包 image 推 Artifact Registry、跑 Cloud Run。Streamlit 服務帳戶僅持 staging（raw_note / processed_note）**唯讀**；頁面加 demo 級登入窗。

10. Archive 端點包 image，Cloud Run 持 `archived_note` **寫入** + staging **唯讀**。

10b. Silver enrich 端點包 image，Cloud Run 持 `processed_note` **寫入** + `raw_note` **唯讀**；由 Streamlit on-demand 呼叫。

11. log 仍寫入同一個 MongoDB Atlas（地端階段已整併），雲端只是換 Cloud Run 容器讀寫同一 Atlas。

> 核心原則：Streamlit 直連 Atlas / GCS 皆**唯讀**僅作狀態顯示；所有寫入（on-demand enrich 的 md / 狀態翻轉、檢核者、歸檔）分別由 **Silver enrich 端點**與 **Archive 端點**執行。LLM 與 embedding 兩段都以 `html_hash` / 內容 hash 做冪等、hash 值判定變動，整條鏈不重複燒 token。
