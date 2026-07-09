# Feature Branch: `feature/html-to-markdown` — Task07 v02（純 Lazy Loading 改版）開發執行成果摘要

> **開發目標**：在原 task07 (後稱為 v01) 的基礎上，把 OneNote → Markdown pipeline 改造為 **多版本可追溯 + 純 Lazy Loading** 架構。兩個核心目的：(1) **Bronze layer 保留同一份筆記的歷史版本**：以 GCS `dt=` 日期分區保存多版本 HTML，取代原本依賴 GCS bucket versioning（後者無法在 GCP Console 直接讀取比對）；(2) **省 multimodal LLM enrichment 的 token**：ETL 階段完全不呼叫 LLM，所有 enrichment 改為 UI **on-demand** 觸發，並以 `html_sha_hash` 為冪等鍵建立 md 快取，使用者重複點擊同一版本不再產生額外 token。

> **開發起始日期**：2026-07-01（於 `feature/html-to-markdown` 分支內另建 v02 變體資料夾）

> **需求來源**：[`task07_onenote_versioned_etl_hand_over_v2.md`](./task07_onenote_versioned_etl_hand_over_v2.md)

> **執行環境**：macOS / VS Code / pyenv (Python 3.14) / Poetry / MongoDB Atlas / GCS 資料湖 / Azure App Registration（公用用戶端，委派式驗證）/ Vertex AI Gemini

> **與 v01 的差異**：
> - v01（[`branch_html_to_md_summary.md`](./branch_html_to_md_summary.md)）輸出 onenote 筆記到本機磁碟、輸出筆記後到生成 markdown 的整段 ETL 採自動主動逐頁呼叫 LLM 中間無暫停、資料表 onenote metadata 主鍵為 `page_id`，一個筆記只存一個版本。
> - v02 改存 onenote 筆記到 GCS 資料湖，利用 dt 分區允許多版本筆記存放；ETL 只做到 Bronze layer；呼叫 LLM 生成 markdown 由前端 on-demand 觸發 (Silver layer)；人工核可後歸檔 (Gold layer)；資料表 onenote metadata 主鍵改為 `(page_id, dt)`，以區分不同日下載的筆記版本，不互相取代。

> **三服務拆分（未來各自部署容器）**：v02 已從單一資料夾拆成三個獨立執行環境 + 一個共用套件：`task07_onenote_to_markdown_lazy_loading/`（Bronze ETL）、`task07_silver_service/`（Silver enrich Flask 端點 8002）、`task07_gold_service/`（Gold 歸檔/退件 Flask 端點 8003）、`task07_common/`（三者共用的 gcs/audit_log/hashing/topic）。向量化再解耦到獨立的 `task08_onenote_embed_etl/`，與 Obsidian（task01_v2/task06_v2）共寫同一張向量表 `note_vectors_multimodal`。

---

## 專案資料夾結構

```
feature/html-to-markdown/
├── .env                                              # 金鑰集中管理（不進 git）
├── poetry.lock
├── pyproject.toml
│
├── task07_common/                                    # 三服務共用工具
│   ├── __init__.py
│   ├── audit_log.py                                  # 三個 MongoDB collections（C1/C2/C3）讀寫工具
│   │                                                 # upsert_version_meta 集中補 created_at/updated_at
│   ├── gcs.py                                        # GCS 資料湖讀寫、三層 blob 路徑組裝
│   ├── hashing.py                                    # html sha256（變動判定 / enrichment 冪等鍵）
│   └── topic.py                                      # topic 主題分類（copy 自 task01 TOPIC_KEYWORDS）
│
├── task07_onenote_to_markdown_lazy_loading/          # Bronze ETL（只 Extract，不含 LLM）
│   ├── __init__.py
│   ├── e_onenote_download.py                         # 下載 HTML、算 hash、有變動才以 dt= 分區寫 GCS
│   │                                                 # + upsert C3（bronze_stored、attached_images、topic）
│   └── main.py                                       # Bronze ETL 入口
│
├── task07_silver_service/                            # Silver enrich 端點（localhost:8002）
│   ├── __init__.py
│   ├── t_enrich_html_to_markdown.py                  # on-demand 函式：html_sha_hash 快取 → 多模態 LLM
│   ├── l_save_markdown.py                            # enriched md 寫 GCS + upsert C3（pending_review）
│   └── app.py                                        # Flask POST /enrich
│
├── task07_gold_service/                              # Gold 歸檔/退件端點（localhost:8003）
│   ├── __init__.py
│   ├── l_archive_note.py                             # approve 歸檔 archived-notes / reject 標記；
│   │                                                 # 回寫 md_frontmatter/md_body/dismatched/topic
│   └── app.py                                        # Flask POST /archive（approved / rejected）
│
├── task08_onenote_embed_etl/                         # 向量化（解耦，寫 note_vectors_multimodal）
│   ├── __init__.py
│   ├── e_scan_metadata.py                            # gate 讀 C3（archived + 未向量化）、取歸檔 md
│   ├── t_chunk_embed.py                              # chunk + 多模態 gemini-embedding-2（1536+L2）
│   ├── l_load_to_mongodb.py                          # 先刪後插 note_vectors_multimodal + md_md5_hash CAS
│   └── main.py                                       # E→T→L 入口（無 purge）
│
└── tests/
    ├── test_task07_onenote_to_markdown_v02.py        # Bronze + Silver 服務本體 unittest
    ├── test_silver_service_endpoint.py               # Silver /enrich 端點 unittest
    ├── test_gold_service_endpoint.py                 # Gold /archive 端點 + 歸檔/退件 unittest
    └── test_task08_onenote_embed.py                  # task08 向量化 unittest
```

---

## Task 07 v02 — OneNote 多版本 Lazy Loading ETL

### 資料來源

Microsoft OneNote（個人帳號），透過 Microsoft Graph API 存取（endpoint 與 v01 相同）。

| API 端點 | 用途 |
|----------|------|
| `GET /me/onenote/notebooks` | 列出所有筆記本 |
| `GET /me/onenote/notebooks/{id}/sections` | 列出章節 |
| `GET /me/onenote/sections/{id}/pages` | 列出頁面清單 |
| `GET /me/onenote/pages/{id}/content` | 取得頁面 HTML 內容 |
| `GET {resource_url}` | 下載嵌入圖片 |

### 輸出目的地：GCS 資料湖（medallion 分層）

單一固定 bucket（預設 `onenote-vaults`，可由 `ONENOTE_GCS_BUCKET` 覆寫），以「資料層 + user_id」組出三層 blob 路徑：

```
raw-notes/<user_id>/<notebook>/<section>/dt=<執行日>/<page>.html          Bronze HTML
raw-notes/<user_id>/<notebook>/<section>/dt=<執行日>/_images/<res_id>.ext Bronze 圖片
processed-notes/<user_id>/<notebook>/<section>/dt=<執行日>/<page>.md      Silver enriched md
archived-notes/<user_id>/<notebook>/<section>/dt=<執行日>/<page>.md       Gold 歸檔 md
archived-notes/<user_id>/<notebook>/<section>/dt=<執行日>/_images/<x>.ext Gold 歸檔圖片
```

`dt=` 分區為版本鍵：同一份筆記每次偵測到 `html_sha_hash` 變動，就以當日 `dt` 寫一份新版本，歷史版本不互相覆蓋、可在 Console 直接讀取比對。Gold 的 `dt` 對齊 Bronze 執行日。

### 資料表 Collections

存在 MongoDB Atlas Database `skill_dashboard`，總計 [3 份](#mongodb-collections):

1. `onenote_graph_api_logs` (簡稱 `C1`): [Schema 定義見後方](#collection-1onenote_graph_api_logs)
2. `multimodal_llm_enrichment_logs` (簡稱 `C2`): [Schema 定義見後方](#collection-2multimodal_llm_enrichment_logs)
3. `onenote_note_metadata` (簡稱 `C3`): [Schema 定義見後方](#collection-3onenote_note_metadata主鍵--page_id--dt)

---

### ETL 設計重點

#### Bronze — Extract（`e_onenote_download.py`）

ETL 主腳本**只做到 Bronze，全程不呼叫 LLM**。流程：

1. **驗證**：MSAL `PublicClientApplication` + Device Flow；Token 快取於 `~/.config/onenote-skill/token_cache.json`，過期自動靜默刷新（`acquire_token_silent`），401 時 `api_get()` 內就地換 token 重試一次
2. **設定速率控制**：`RateLimiter` 滑動視窗，每分鐘 115 次、每小時 380 次（低於 OneNote 官方 120/min、400/hour）
3. **請求並附設容錯（`api_get()`）**：`requests.get()` 設 `REQUEST_TIMEOUT=(10, 60)` 避免伺服器 hang 住無限等待；以 `raise_for_status()` 統一轉 `HTTPError` 後**分兩層 except**——`HTTPError`（401 換 token / 429 讀 `Retry-After` 退避 / 5xx 指數退避 / 其他 4xx 直接 raise 不重試）與 `RequestException`（傳輸層錯誤，`status_code=0` 退避重試）；最多 10 次，耗盡補一筆收尾列再 raise `RuntimeError`
4. **帳號萃取**：從 section 的 `self` URL（`/users/<email>/onenote/...`）萃取 `@` 前段作為 `user_id`（如 `lucky460721`）
5. **變動判定（核心）**：對**未 parse 的 HTML 原始碼**算 `html_source_hash`（sha256），與 C3 `get_latest_version_meta()` 取回的最新一筆 `html_sha_hash` 比對——相同則只寫一筆 `downloaded=False` 的 C1 log 並跳過（不存新版本）；不同才進入下載流程
6. **圖片處理**：hash 有變動才 `BeautifulSoup` parse，偵測 `<img>` 的 Graph API 圖片資源 URL，下載後上傳 GCS `_images/`，並將 HTML 內 `src` 改寫為相對路徑 `_images/{resource_id}.ext`（`soup` tag copy-by-reference，改寫後連同 HTML 一併上傳）；下載成功的圖片 `zip` 成 C3 的 `attached_images` Object 陣列（`raw_image_path`/`raw_image_md5`）
  -  **request_id 注入式設計**：page content 呼叫由 `download_notebooks()`（page 層邏輯範圍）先生成 `request_id` 再**注入** `api_get()` 共用，使 api_get 內部的失敗 attempt log 與外層事後補記的結果 log 掛同一 ID 可 join；listing、圖片等各自獨立的請求則不注入、由 api_get 自生成
  - **稽核職責分離**：C1（request 層）全歸 `api_get()`——逐次 attempt 失敗 + retry 耗盡收尾列；C3（page 層生命週期）全歸 `download_notebooks()`——只記 `status`。避免同一次失敗重複寫 C1、避免 `status_code=0` 蓋掉真實碼
7. **回傳**：本次實際偵測到 hash 變動並寫入 GCS 的**新版本數**（`int`）

#### Silver — Transform（`t_enrich_html_to_markdown.py`）

**純 Lazy Loading**：本模組不在 ETL 主動執行，而是對外提供 `t_enrich_html_to_markdown(page_id, dt, trigger, client)` 函式，供 `feature/dashboard-ui` 的審查頁在使用者點擊某版本時 on-demand 呼叫。分支流程：

1. **查版本 metadata**：`get_version_meta(page_id, dt)`，查無回 `{"status": "not_found"}`
2. **regenerate 配額檢查**：`trigger="regenerate"` 且同一 `html_sha_hash` 已成功 regenerate ≥ `REGENERATE_QUOTA (=2)` 次則拒絕（per-note 成本上限）
3. **html_sha_hash 快取查找**：非 regenerate 時 `find_cached_md_by_hash()` 找相同 `html_sha_hash` 且 `enriched_md_path != null` 的既有版本——**命中則零 token**（寫一筆 `cache_hit=True, tokens=0` 的 C2 log、upsert C3 進 `pending_review`、直接回傳既有 md_path）
4. **服務級斷路器**：cache miss 時先檢查 `_LLMServiceGuard`——LLM API **連續失敗達門檻（預設 5 次）即開斷路冷卻（預設 300s）**，期間筆記維持 `bronze_stored`、**不懲罰單一筆記**、不鎖使用者操作（取代 v01 綁「單筆記版本次數」的斷路器）
5. **多模態 LLM 呼叫**：從 GCS 下載 HTML、`convert_img_tag_to_md_str()` 把 `<img>` 轉 `![alt](src)` 後 `get_text()` 取純文字；連同 C3 `attached_images[].raw_image_path` 內的 `gs://` 圖片 URI 一併送入 Vertex AI Gemini（`gemini-2.5-flash`），要求 model 實際判讀每張圖並生成「AI生成圖釋」；structured JSON 輸出 schema 強制 `tags`（5–10 中英混合關鍵字）、`alias`（1–2 個簡短別名）、`new_content`（重整後 Markdown）；`temperature=0.2`
6. **frontmatter 組合**：`_build_markdown()` 產出可被 Obsidian 開啟的 YAML frontmatter（`tags` / `date` / `type` / `alias`）；`type` 由 `_classify_note_type()` 依檔名是否含日期分類 `daily_log` / `knowledge_summary`
7. **稽核**：每次呼叫寫 C2 `multimodal_llm_enrichment_logs`（含 `cache_hit`、`trigger`、input/output/total tokens、latency）；失敗時 token 欄位寫 `None`（非 0）以區別 cache hit

#### Silver — Load（`task07_silver_service/l_save_markdown.py`）

- `save_enriched_md()`：把 enriched md 寫至 GCS `processed-notes/.../dt=<對齊 bronze 執行日>/<page>.md`，回傳 `(md_uri, md_md5_hash)`
- 以 `(page_id, dt)` upsert C3，更新 `enriched_md_path`、`md_md5_hash`、`enriched_md_exported_at`、`status="pending_review"`

#### Silver 端點（`task07_silver_service/app.py`，localhost:8002）

- Flask `POST /enrich`，body `{page_id, dt, trigger}`；呼叫 `t_enrich_html_to_markdown` 做 on-demand enrichment
- 缺欄位 400、trigger 非法 400、查無版本 404、未預期例外 500，其餘（cache hit / pending_review / circuit_open / enrich_failed / quota）回 200，由呼叫端依 dict 欄位判讀
- 供審查頁維持對 GCS 唯讀、只能透過端點觸發 enrich

#### Gold — Load（`task07_gold_service/l_archive_note.py`，localhost:8003）

Flask `POST /archive`，body `{page_id, dt, role, action}`；`action` 為 `approved` / `rejected`：

- **approve（`archive_note`）**：把關是否早有更新版本已歸檔（本版 `dt` 早於最後歸檔日則 409 拒絕、idempotent 重複 approve 回既有結果）→ 從 `processed-notes/` 複製 md、從 `raw-notes/` 複製 png 到 `archived-notes/`，把每個 `attached_images` Object 回填 `archived_image_path`/`archived_image_md5` → upsert C3（`status=archived`、`review_result=approved`、`archived_md_path`、`md_md5_hash`、審核欄位）→ **退役同頁其他 `pending_review` 版本**（同 `html_sha_hash` 標 `overwritten`、否則 `rejected`）→ 讀回歸檔 md 萃取品質欄位
- **reject（`reject_note`）**：不寫 GCS，upsert C3（`status=review_closed`、`review_result=rejected`、審核欄位）→ 背景讀 silver md 萃取品質欄位
- **品質欄位（approve/reject 皆寫）**：`md_frontmatter`（`tags`/`date`/`type`/`alias`）、`md_body`（`valid_img_count`/`word_count`/`recomputed_at`）、`dismatched_img_count`、`md_has_dismatched_img`，並以 `md_frontmatter.tags`＋頁面標題重算 `topic`；`valid_img_count` 由 md 正文 `![]()` 連結 basename 命中歸檔/raw 圖片者計數

#### 入口（`task07_onenote_to_markdown_lazy_loading/main.py`）

- 函式 `run_task07_bronze_etl()` 只調用 `e_onenote_download()` 下載並記錄新版本數
- **Silver / Gold 不放在此執行**，由 UI on-demand（Silver）與 approve/reject（Gold）觸發

---

## MongoDB Collections
> 總計三份 collections, C1, C2 and C3
> 由 `task07_common/audit_log.py` 統一封裝。C1、C2 只追加 (insert)；C3 以 `(page_id, dt)` 為主鍵 upsert，支援同頁多版本。

### Collection 1：`onenote_graph_api_logs`

每筆 = 一次 Graph API 請求嘗試。新增 `html_sha_hash`、`html_path`、`downloaded` 三欄，讓「hash 未變動而跳過」也能留下 `downloaded=False` 的紀錄。

```json
{
  "_id" : ObjectId("6a44ce421996a609c157b692"),
  "page_id": "0-c69860f9dd8507...",
  "timestamp": ISODate("2026-07-01T10:00:00.012Z+0000"),
  "event_type": "onenote_api_download",
  "method": "GET",
  "api_endpoint": ".../pages/{id}/content",
  "request_id": "abc12345ef67",
  "attempt_id": 1,
  "status": "success",
  "status_code": 200,
  "latency_ms": 312,
  "html_sha_hash": "aa58a....",
  "html_path": "gs://onenote-vaults/raw-notes/lucky460721/NB/Sec/dt=2026-07-01/page.html",
  "downloaded": true,
  "environment": "local",
  "error_msg": null
}
```

### Collection 2：`multimodal_llm_enrichment_logs`

每筆 = 一次 LLM enrichment 呼叫（含 cache hit）。用於 `count_regenerate()` 統計配額，也是 on-demand 省 token 的稽核依據——**沒人點的版本永遠不會出現在 C2**。

```json
{
  "_id": ObjectId("6a4526abcf5f1da7406adebd"),
  "page_id": "0-c69860f9dd8507...",
  "html_sha_hash": "sha256...",
  "timestamp": ISODate("2026-07-01T10:00:00.012Z+0000"),
  "event_type": "llm_enrichment_call",
  "model": "gemini-2.5-flash",
  "cache_hit": false,
  "trigger": "on_demand",
  "status": "success",
  "latency_ms": 4200,
  "input_tokens": 1850,
  "output_tokens": 640,
  "total_tokens": 2490,
  "environment": "local",
  "error_msg": null
}
```

> `cache_hit=true` 時 tokens 皆為 0；`status="failure"` 時 tokens 為 `null`（區別「命中零成本」與「失敗沒算到」）。

### Collection 3：`onenote_note_metadata`（主鍵 = `page_id` + `dt`）

每筆 = 一頁 OneNote 的**某一版本**完整生命週期，貫穿 Bronze → Silver → Gold 逐步 upsert。欄位命名已對齊 hand-over v2 定稿（見文件第 303–347 行）。

```json
// bronze 階段的 enriched_*/archived_*/md_frontmatter/md_body 等為 null，Silver/Gold 逐步補。
{
  "_id": ObjectId("6a4526abcf5f1da7406adebd"),
  "page_id": "0-c69860f9dd8507...",
  "dt": "2026-07-01",
  "onenote_user_id": "lucky460721",
  "notebook": "工作筆記",
  "section": "資料工程",
  "page_title": "MongoDB 索引設計",

  // Bronze（html + 圖片血緣 + topic 初判）
  "html_sha_hash": "sha256...",             // 變動判定 / enrichment 冪等鍵
  "html_md5_hash": "base64...",             // GCS html 物件 md5
  "html_path": "gs://onenote-vaults/raw-notes/.../dt=2026-07-01/MongoDB 索引設計.html",
  "html_downloaded_at": ISODate("2026-07-01T08:22:26.093+0000"),
  "attached_images": [
    {
      "raw_image_path": "gs://onenote-vaults/raw-notes/.../_images/res-abc.png",
      "raw_image_md5": "base64...",
      "archived_image_path": null,          // Gold approve 後回填
      "archived_image_md5": null            // Gold approve 後回填
    }
  ],
  "topic": "database",                      // TOPIC_KEYWORDS 分類；bronze 以標題初判、gold 以 tags 重算

  // Silver（enriched md）
  "enriched_md_path": null,                 // silver md 路徑
  "md_md5_hash": null,                      // silver/gold md 的 GCS md5（有 gold 則以其為主）
  "enriched_md_exported_at": null,

  // 生命週期 / 審核
  "status": "bronze_stored",
  "embedded_status": false,                 // task08 向量化冪等依據
  "review_result": null,                    // null / approved / rejected / overwritten
  "reviewed_by_role": null,                 // ML engineer / note_owner / dept_senior_specialist
  "reviewed_at": null,
  "error_msg": null,

  // Gold（歸檔 + 品質欄位）
  "archived_md_path": null,                 // gold 歸檔 md 路徑
  "archived_at": null,
  "md_frontmatter": null,                   // {tags, date, type, alias}（無 valid_img）
  "md_body": null,                          // {valid_img_count, word_count, recomputed_at}
  "dismatched_img_count": null,             // 失效（basename 未命中）圖片數
  "md_has_dismatched_img": null,            // dismatched_img_count > 0

  // 稽核時間戳（upsert_version_meta 集中維護）
  "created_at": ISODate("2026-07-01T08:22:26.093+0000"),
  "updated_at": ISODate("2026-07-01T08:22:26.093+0000")
}
```

#### Collection 3 狀態流轉

| 執行層 | 情境 | `status` | `review_result` | `embedded_status` |
|-------|------|----------|-----------------|-------------------|
| Bronze | 新版下載完成、待 on-demand enrich | `bronze_stored` | null | false |
| Bronze | html 下載但寫入失敗 | `fetched_failed` | null | false |
| Silver | LLM enrichment 進行中（on-demand 觸發） | `fetched` | null | false |
| Silver | LLM 生成失敗 | `enrich_failed` | null | false |
| Silver | 生成成功、等人審查 | `pending_review` | null | false |
| Gold | 按通過、歸檔成功 | `archived` | `approved` | false（待 task08 翻 true） |
| Gold | 按通過、歸檔中途失敗 | `archive_failed` | `approved` | false |
| Gold | 針對性單一筆記退件 | `review_closed` | `rejected` | false |
| Gold | 同頁擇一歸檔而連帶退役、且 hash 與歸檔版相同 | `review_closed` | `overwritten` | false |
| task08 | 歸檔筆記完成向量化 | `archived` | `approved` | true |

> `overwritten` 與 `rejected` 之分：被退役版本的 `html_sha_hash` 與歸檔版相同者標 `overwritten`（內容等同已被採納），不同者標 `rejected`，避免好/壞 md 分析被誤導。`embedded_status` 由 task08 向量化成功後才翻 `true`。

> 相較 v01：
> - C3 主鍵由 `page_id` 改為 `(page_id, dt)`；
> - 新增 `html_sha_hash`、`embedded_status`、`attached_images`、`topic`、`md_body`、`dismatched_img_count`/`md_has_dismatched_img`、`created_at`/`updated_at`；
> - 欄位改名：silver md → `enriched_md_path`/`enriched_md_exported_at`、gold md → `archived_md_path`、圖片血緣由 `img_md5`/`img_path`/`img_archive_path` 三平行陣列重構為 `attached_images` Object 陣列。

---

## Task 08 — OneNote 向量化（`task08_onenote_embed_etl/`）

向量化從 task07 解耦成獨立 pipeline，目標是讓 **OneNote（task07 歸檔）** 與 **Obsidian（task01_v2 歸檔）** 兩種來源，向量化後寫入**同一張** `note_vectors_multimodal`（同一 Atlas Vector Search index），供同一條 RAG 檢索。chunk/embed/normalize 邏輯 copy 自 `task06_obsidian_embed_etl_v2`，僅替換 ingestion 與圖片解析；`task06_v2` 本分支完全不動。

| 面向 | 設計 |
|------|------|
| gate（`e_scan_metadata.py`） | 讀 C3 挑 `status="archived"` 且 `embedded_status=false`，投影 `archived_md_path`/`md_md5_hash`/`md_frontmatter`/`page_title`/`attached_images` |
| 內容來源 | 依 `archived_md_path` 從 `onenote-vaults/archived-notes/` 下載歸檔 md（人工核可後的乾淨層） |
| 圖片解析（`t_chunk_embed.py`） | 抓標準 markdown `![](_images/x.png)`（非 wiki-link），以 basename 對上 `attached_images[].archived_image_path` |
| embedding | Vertex AI `gemini-embedding-2`，1536 維、L2 normalize（逐 chunk 多模態） |
| 寫入（`l_load_to_mongodb.py`） | per-note 先 `delete_many({md_path})` 再 `insert_many` 進 `note_vectors_multimodal`；向量血緣欄 `md_path` 存 `archived_md_path` 值、`image_paths` 存 archived 圖片 |
| CAS 翻旗標 | 以 `md_md5_hash` 守衛（`archived_md_path` 定位版本），只有仍 `embedded_status=false` 且 md5 未變才翻 `embedded_status=true`＋以同一時戳蓋 `embedded_at` 與 `updated_at`（task08 直接以 pymongo 翻旗標、未走 `upsert_version_meta` 集中補時戳，故自行同步 `updated_at` 避免 `embedded_at` 晚於 `updated_at`） |
| purge | **無**（OneNote 版本以 `review_closed` 退役、無 `status=deleted` 軟刪除） |

---

## v01 → v02 關鍵差異對照

| 面向 | v01（`task07_onenote_to_markdown`） | v02（`task07_onenote_to_markdown_lazy_loading`） |
|------|-----------------------------------|-----------------------------------------------|
| 輸出目的地 | 本機磁碟 `.md` + HTML | GCS 資料湖（Bronze/Silver medallion 分層） |
| 歷史版本 | 依賴 GCS bucket versioning（Console 難讀） | `dt=` 日期分區顯式多版本 |
| LLM 觸發 | ETL 主動逐頁呼叫 | **純 Lazy Loading**，UI on-demand 觸發 |
| 省 token 機制 | 無 | `html_sha_hash` md 快取 + regenerate 配額 |
| 斷路器 | 綁單一筆記版本次數 | **LLM 服務級**（連續失敗開斷路冷卻） |
| C3 主鍵 | `page_id`（單版本） | `(page_id, dt)`（多版本） |
| C2 collection | `gemini_llm_logs` | `multimodal_llm_enrichment_logs`（加 `cache_hit`/`trigger`） |
| LLM 模型 | `gemini-2.5-flash-lite` | `gemini-2.5-flash`（多模態判讀圖片） |
| 變動判定鍵 | — | html 原始碼 sha256（非 Graph API `lastModifiedDateTime`） |

---

## 套件依賴

```
pymongo, msal, requests, beautifulsoup4, python-dotenv, loguru,
google-genai, google-auth, google-cloud-storage
```

## .env 金鑰

```
ONENOTE_CLIENT_ID=                # Azure App Registration Client ID（公用用戶端）
ONENOTE_GCS_BUCKET=               # 資料湖 bucket（預設 onenote-vaults）
ONENOTE_NOTEBOOK_IDS=             # （選填）JSON array，指定要下載的 notebook ID；省略則互動選擇
GOOGLE_APPLICATION_CREDENTIALS=   # GCS service account JSON
AGENT_PLATFORM_USER_CREDENTIALS=  # Vertex AI Gemini service account JSON
GCP_PROJECT_ID=                   # GCP 專案 ID（Vertex AI）
MONGO_ALTAS_URI=                  # MongoDB Atlas 連線字串
MONGO_DB_NAME=                    # MongoDB 資料庫名稱
ENVIRONMENT=                      # local | dev | prod
```

---

## Unit Tests

以 `unittest` 撰寫，全部 mock（不連 MongoDB / GCS / LLM）；在 import 前先注入假 env 以繞過模組層守門。四個測試檔涵蓋 Bronze/Silver 服務本體、Silver 端點、Gold 端點與 task08 向量化。

**`tests/test_task07_onenote_to_markdown_v02.py`（Bronze + Silver 本體 + task07_common）**

| 測試類別 | 測試對象 | 測試重點 |
|---------|---------|---------|
| `LogApiCallTests` | `log_api_call()` | 寫入 `html_sha_hash`/`downloaded`/`event_type`、MongoDB 失敗不 raise |
| `LogEnrichmentCallTests` | `log_enrichment_call()` | cache hit 時 tokens=0、`trigger`/`event_type` 正確 |
| `UpsertVersionMetaTests` | `upsert_version_meta()` | filter key `(page_id, dt)`、`$set` 帶 `updated_at`、insert 補 `created_at`、db 失敗不 raise |
| `HashingTests` / `GcsPrefixTests` / `SanitizeTests` | hashing / gcs / sanitize | 決定性 hash、raw/processed prefix、禁用字元替換 |
| `ApiGetTests` | `api_get()` | 4xx 不重試、傳輸層錯誤重試、重試耗盡收尾 log 後 raise、timeout 常數 |
| `DownloadNotebooksFailedBranchTests` | `download_notebooks()` | 失敗路徑 `fetched_failed`、`$set`/`$setOnInsert` 無 key 重疊 |
| `DownloadNotebooksSuccessBranchTests` | `download_notebooks()` | 成功路徑寫 `html_sha_hash`/`html_md5_hash`/`attached_images`(raw 端)/`topic`，不含舊欄位名 |
| `CircuitGuardTests` / `ClassifyNoteTypeTests` / `ConvertImgTagTests` / `CallLlmMultimodalTests` | Silver 本體 helper | 斷路器、note_type 分類、img 轉 md、多模態 contents/token usage |
| `EnrichPageTests` | on-demand 入口 | not_found / cache-hit 略過 LLM / circuit-open 維持 bronze / regenerate 配額超限 |

**`tests/test_silver_service_endpoint.py`（`POST /enrich`）**：缺欄位 400、trigger 非法 400、查無版本 404、業務結果 200、未預期例外 500。

**`tests/test_gold_service_endpoint.py`（`POST /archive` + 歸檔/退件本體）**：端點狀態碼（400/404/409/422/200）、`_build_md_quality_meta`（`md_frontmatter` 不含 valid_img、`md_body.valid_img_count`、`dismatched_img_count`/`md_has_dismatched_img`）、approve 退役同頁版本（`html_sha_hash` 判 overwritten/rejected）、reject 回寫品質欄位、型別正規化。

**`tests/test_task08_onenote_embed.py`（向量化）**：gate 過濾與投影、markdown `![]()` 圖片 basename 解析、向量 doc 結構（`md_path`=archived 路徑、L2 normalize）、切塊為空仍算已處理、失敗檔不列入 CAS、先刪後插、`md_md5_hash` 守衛 CAS 命中/未命中。

執行方式：
```bash
poetry run python -m unittest discover -s tests
```

> **測試狀態**：全套 **154 個測試全數通過**（`Ran 154 tests OK`）。測試 import／`@patch` 目標與函式名皆已對齊三服務 package（`task07_common`、`task07_silver_service`、`task07_gold_service`）與 `task08_onenote_embed_etl`。

---

## 此分支（v02）完成範圍

**已完成（Bronze + Silver + Gold + 向量化，本機地端階段）**
- [x] Bronze Extract：MSAL device-flow + Graph API 下載 HTML/圖片 + 速率控制 + `html_sha_hash` 變動判定 + `dt=` 分區寫 GCS + `attached_images`/`topic` + C1/C3 稽核
- [x] Silver Transform + 端點（8002）：on-demand `t_enrich_html_to_markdown()` + `html_sha_hash` 冪等快取 + LLM 服務級斷路器 + 多模態圖片判讀 + regenerate 配額 + C2 稽核
- [x] Silver Load：enriched md 寫 GCS + upsert C3（`enriched_md_path`、`pending_review`）
- [x] Gold 端點（8003）：approve 歸檔 archived-notes（回填 `attached_images` archived 端）/ reject 標記；退役同頁候選版本；回寫 `md_frontmatter`/`md_body`/`dismatched_*`/`topic`
- [x] task08 向量化：gate C3（archived+未向量化）→ chunk + `gemini-embedding-2` → 先刪後插 `note_vectors_multimodal` + `md_md5_hash` CAS 翻 `embedded_status`
- [x] `task07_common`：`audit_log.py`（C1/C2/C3 + 集中時間戳）、`gcs.py`、`hashing.py`、`topic.py`
- [x] C3 欄位對齊 hand-over v2 定稿（第 303–347 行）；`l_archive_note.py` 的 `except (ValueError, TypeError)` 語法 bug 修正
- [x] Unit tests 全套 **154 個測試全數通過**

**後續待開發**
- [x] 端到端本地實跑（清空 C1/C2/C3 後重跑 Bronze→Silver→Gold→task08，核對新欄位）——需真實 GCS/Mongo/LLM
- [x] 跨分支：`note_vectors_multimodal` 的 task06_v2 `raw_md_path`→`md_path`。
- [ ] 回到 `dashboard-ui` 分支上開發使用頁面。
- [ ] 雲端部署（Bronze 每週 Cloud Run Job；Silver/Gold/task08 各自 Cloud Run 容器，權限分離）

---

*本摘要涵蓋 `feature/html-to-markdown` 分支中 task07 v02（`task07_common` + Bronze ETL + `task07_silver_service` + `task07_gold_service`）與 task08 向量化（`task08_onenote_embed_etl/`）的所有腳本與測試，於 2026-07-01 起記錄，2026-07-09 更新至三服務拆分、C3 schema 對齊與 task08 落地。*
