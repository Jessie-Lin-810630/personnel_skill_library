# Feature Branch: `feature/html-to-markdown` — Task07 v02（純 Lazy Loading 改版）開發執行成果摘要

> **開發目標**：在原 task07 的基礎上，把 OneNote → Markdown pipeline 改造為 **多版本可追溯 + 純 Lazy Loading** 架構。兩個核心目的：(1) **Bronze layer 保留同一份筆記的歷史版本**——以 GCS `dt=` 日期分區保存多版本 HTML，取代原本依賴 GCS bucket versioning（後者無法在 GCP Console 直接讀取比對）；(2) **省 multimodal LLM enrichment 的 token**——ETL 階段完全不呼叫 LLM，所有 enrichment 改為 UI **on-demand** 觸發，並以 `html_hash` 為冪等鍵建立 md 快取，使用者重複點擊同一版本不再產生額外 token。

> **開發起始日期**：2026-07-01（於 `feature/html-to-markdown` 分支內另建 v02 變體資料夾）

> **需求來源**：[`task07_onenote_versioned_etl_hand_over_v2.md`](./task07_onenote_versioned_etl_hand_over_v2.md)

> **執行環境**：macOS / VS Code / pyenv (Python 3.14) / Poetry / MongoDB Atlas / GCS 資料湖 / Azure App Registration（公用用戶端，委派式驗證）/ Vertex AI Gemini

> **與 v01 的關係**：v01（[`branch_html_to_md_summary.md`](./branch_html_to_md_summary.md)）輸出到本機磁碟、ETL 主動逐頁呼叫 LLM、C3 主鍵為 `page_id`（單版本）。v02 為**平行資料夾** `task07_onenote_to_markdown_lazy_loading/`，改為 GCS 資料湖多版本、ETL 只到 Bronze、Silver 純 on-demand，C3 主鍵改為 `(page_id, dt)`。兩者並存、不互相取代。

---

## 專案資料夾結構

```
feature/html-to-markdown/
├── .env                                              # 金鑰集中管理（不進 git）
├── poetry.lock
├── pyproject.toml
│
├── task07_onenote_to_markdown_lazy_loading/          # v02：純 Lazy Loading 變體
│   ├── __init__.py
│   ├── e_onenote_download.py                         # Bronze Extract：MSAL device-flow 取 token、
│   │                                                 # 下載 HTML、算 hash、有變動才以 dt= 分區寫 GCS
│   ├── t_enrich_html_to_markdown.py                  # Silver Transform：on-demand 函式，
│   │                                                 # html_hash 快取 → multimodal LLM → 組 frontmatter
│   ├── l_save_markdown.py                            # Silver Load：enriched md 寫 GCS + upsert C3
│   ├── main.py                                       # Bronze ETL 入口（只 Extract，不含 LLM）
│   └── utils/
│       ├── audit_log.py                              # 三個 MongoDB collections（C1/C2/C3）讀寫工具
│       ├── gcs.py                                    # GCS 資料湖讀寫、三層 blob 路徑組裝
│       └── hashing.py                                # html sha256（變動判定 / enrichment 冪等鍵）
│
└── tests/
    └── test_task07_onenote_to_markdown_v02.py        # Unit tests（unittest）
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
（Gold archived 由 feature/dashboard-ui 的 Archive 端點負責，不在此模組）
```

`dt=` 分區為版本鍵：同一份筆記每次偵測到 `html_hash` 變動，就以當日 `dt` 寫一份新版本，歷史版本不互相覆蓋、可在 Console 直接讀取比對。

---

### ETL 設計重點

#### Bronze — Extract（`e_onenote_download.py`）

ETL 主腳本**只做到 Bronze，全程不呼叫 LLM**。流程：

1. **驗證**：MSAL `PublicClientApplication` + Device Flow；Token 快取於 `~/.config/onenote-skill/token_cache.json`，過期自動靜默刷新（`acquire_token_silent`），401 時 `api_get()` 內就地換 token 重試一次
2. **設定速率控制**：`RateLimiter` 滑動視窗，每分鐘 115 次、每小時 380 次（低於 OneNote 官方 120/min、400/hour）
3. **請求並附設容錯（`api_get()`）**：`requests.get()` 設 `REQUEST_TIMEOUT=(10, 60)` 避免伺服器 hang 住無限等待；以 `raise_for_status()` 統一轉 `HTTPError` 後**分兩層 except**——`HTTPError`（401 換 token / 429 讀 `Retry-After` 退避 / 5xx 指數退避 / 其他 4xx 直接 raise 不重試）與 `RequestException`（傳輸層錯誤，`status_code=0` 退避重試）；最多 10 次，耗盡補一筆收尾列再 raise `RuntimeError`
4. **帳號萃取**：從 section 的 `self` URL（`/users/<email>/onenote/...`）萃取 `@` 前段作為 `user_id`（如 `lucky460721`）
5. **變動判定（核心）**：對**未 parse 的 HTML 原始碼**算 `html_source_hash`（sha256），與 C3 `get_latest_version_meta()` 取回的最新一筆 `html_hash` 比對——相同則只寫一筆 `downloaded=False` 的 C1 log 並跳過（不存新版本）；不同才進入下載流程
6. **圖片處理**：hash 有變動才 `BeautifulSoup` parse，偵測 `<img>` 的 Graph API 圖片資源 URL，下載後上傳 GCS `_images/`，並將 HTML 內 `src` 改寫為相對路徑 `_images/{resource_id}.ext`（`soup` tag copy-by-reference，改寫後連同 HTML 一併上傳）
  -  **request_id 注入式設計**：page content 呼叫由 `download_notebooks()`（page 層邏輯範圍）先生成 `request_id` 再**注入** `api_get()` 共用，使 api_get 內部的失敗 attempt log 與外層事後補記的結果 log 掛同一 ID 可 join；listing、圖片等各自獨立的請求則不注入、由 api_get 自生成
  - **稽核職責分離**：C1（request 層）全歸 `api_get()`——逐次 attempt 失敗 + retry 耗盡收尾列；C3（page 層生命週期）全歸 `download_notebooks()`——只記 `status`。避免同一次失敗重複寫 C1、避免 `status_code=0` 蓋掉真實碼
7. **回傳**：本次實際偵測到 hash 變動並寫入 GCS 的**新版本數**（`int`）

#### Silver — Transform（`t_enrich_html_to_markdown.py`）

**純 Lazy Loading**：本模組不在 ETL 主動執行，而是對外提供 `t_enrich_html_to_markdown(page_id, dt, trigger, client)` 函式，供 `feature/dashboard-ui` 的審查頁在使用者點擊某版本時 on-demand 呼叫。分支流程：

1. **查版本 metadata**：`get_version_meta(page_id, dt)`，查無回 `{"status": "not_found"}`
2. **regenerate 配額檢查**：`trigger="regenerate"` 且同一 `html_hash` 已成功 regenerate ≥ `REGENERATE_QUOTA (=2)` 次則拒絕（per-note 成本上限）
3. **html_hash 快取查找**：非 regenerate 時 `find_cached_md_by_hash()` 找相同 `html_hash` 且 `md_path != null` 的既有版本——**命中則零 token**（寫一筆 `cache_hit=True, tokens=0` 的 C2 log、upsert C3 進 `pending_review`、直接回傳既有 md_path）
4. **服務級斷路器**：cache miss 時先檢查 `_LLMServiceGuard`——LLM API **連續失敗達門檻（預設 5 次）即開斷路冷卻（預設 300s）**，期間筆記維持 `bronze_stored`、**不懲罰單一筆記**、不鎖使用者操作（取代 v01 綁「單筆記版本次數」的斷路器）
5. **多模態 LLM 呼叫**：從 GCS 下載 HTML、`convert_img_tag_to_md_str()` 把 `<img>` 轉 `![alt](src)` 後 `get_text()` 取純文字；連同 C3 `img_path` 內的 `gs://` 圖片 URI 一併送入 Vertex AI Gemini（`gemini-2.5-flash`），要求 model 實際判讀每張圖並生成「AI生成圖釋」；structured JSON 輸出 schema 強制 `tags`（5–10 中英混合關鍵字）、`alias`（1–2 個簡短別名）、`new_content`（重整後 Markdown）；`temperature=0.2`
6. **frontmatter 組合**：`_build_markdown()` 產出可被 Obsidian 開啟的 YAML frontmatter（`tags` / `date` / `type` / `alias`）；`type` 由 `_classify_note_type()` 依檔名是否含日期分類 `daily_log` / `knowledge_summary`
7. **稽核**：每次呼叫寫 C2 `multimodal_llm_enrichment_logs`（含 `cache_hit`、`trigger`、input/output/total tokens、latency）；失敗時 token 欄位寫 `None`（非 0）以區別 cache hit

#### Silver — Load（`l_save_markdown.py`）

- `save_enriched_md()`：把 enriched md 寫至 GCS `processed-notes/.../dt=<對齊 bronze 執行日>/<page>.md`，回傳 `(md_uri, md_md5)`
- 以 `(page_id, dt)` upsert C3，更新 `md_path`、`md_md5`、`md_exported_at`、`status="pending_review"`

#### 入口（`main.py`）

- `run_task07_bronze_etl()` 只呼叫 `e_onenote_download()` 下載並記錄新版本數
- **Silver enrichment 不在此執行**，由 UI on-demand 觸發

---

## MongoDB Collections
> 總計三份 collections, C1, C2 and C3
> 由 `utils/audit_log.py` 統一封裝。C1、C2 只追加；C3 以 `(page_id, dt)` 為主鍵 upsert，支援同頁多版本。

### Collection 1：`onenote_graph_api_logs`（只追加）

每筆 = 一次 Graph API 請求嘗試。新增 `html_hash`、`html_path`、`downloaded` 三欄，讓「hash 未變動而跳過」也能留下 `downloaded=False` 的紀錄。

```json
{
  "page_id": "onenote-page-id",
  "timestamp": "2026-07-01T10:00:00Z",
  "event_type": "onenote_api_download",
  "method": "GET",
  "api_endpoint": ".../pages/{id}/content",
  "request_id": "abc12345ef67",
  "attempt_id": 1,
  "status": "success",
  "status_code": 200,
  "latency_ms": 312,
  "html_hash": "sha256...",
  "html_path": "gs://onenote-vaults/raw-notes/lucky460721/NB/Sec/dt=2026-07-01/page.html",
  "downloaded": true,
  "environment": "local",
  "error_msg": null
}
```

### Collection 2：`multimodal_llm_enrichment_logs`（只追加）

每筆 = 一次 LLM enrichment 呼叫（含 cache hit）。用於 `count_regenerate()` 統計配額，也是 on-demand 省 token 的稽核依據——**沒人點的版本永遠不會出現在 C2**。

```json
{
  "page_id": "onenote-page-id",
  "html_hash": "sha256...",
  "timestamp": "2026-07-01T10:01:00Z",
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

每筆 = 一頁 OneNote 的**某一版本**完整生命週期，貫穿 Bronze → Silver → Gold 逐步 upsert。

```json
{
  "page_id": "onenote-page-id",
  "dt": "2026-07-01",
  "onenote_user_id": "lucky460721",
  "notebook": "工作筆記",
  "section": "資料工程",
  "page_title": "MongoDB 索引設計",
  "html_hash": "sha256...",
  "html_md5": "base64...",
  "html_path": "gs://onenote-vaults/raw-notes/.../dt=2026-07-01/MongoDB 索引設計.html",
  "html_downloaded_at": "2026-07-01T10:00:00Z",
  "img_md5": ["base64..."],
  "img_path": ["gs://onenote-vaults/raw-notes/.../_images/res-abc.png"],
  "md_path": null,
  "md_md5": null,
  "md_exported_at": null,
  "note_type": "knowledge_summary",
  "status": "bronze_stored",
  "embedded_status": false,
  "error_msg": null,
  "review_result": null,
  "reviewed_by_role": null,
  "reviewed_at": null,
  "md_archive_path": null,
  "img_archive_path": null,
  "archived_at": null
}
```

#### Collection 3 狀態流轉

| 情境 | `status` | `review_result` | `embedded_status` |
|------|----------|-----------------|-------------------|
| 新版下載完成、待 on-demand enrich | `bronze_stored` | null | false |
| html 下載但寫入失敗 | `fetched_failed` | null | false |
| LLM enrichment 進行中（on-demand 觸發） | `fetched` | null | false |
| LLM 生成失敗 | `enrich_failed` | null | false |
| 生成成功、等人審查 | `pending_review` | null | false |
| 按通過、歸檔成功 | `archived` | `approved` | true |
| 按通過、歸檔中途失敗 | `archive_failed` | `approved` | false |
| 被退回 | `review_closed` | `rejected` | false |

> 相較 v01：C3 主鍵由 `page_id` 改為 `(page_id, dt)`；新增 `html_hash`、`embedded_status`；不再使用 `superseded` 旗標——「同名筆記一次只認可一份」改由 Gold/UI 於 approve 時讀回 C3 判斷是否已有 `archived` 版本來控制。

---

## v01 → v02 關鍵差異對照

| 面向 | v01（`task07_onenote_to_markdown`） | v02（`task07_onenote_to_markdown_lazy_loading`） |
|------|-----------------------------------|-----------------------------------------------|
| 輸出目的地 | 本機磁碟 `.md` + HTML | GCS 資料湖（Bronze/Silver medallion 分層） |
| 歷史版本 | 依賴 GCS bucket versioning（Console 難讀） | `dt=` 日期分區顯式多版本 |
| LLM 觸發 | ETL 主動逐頁呼叫 | **純 Lazy Loading**，UI on-demand 觸發 |
| 省 token 機制 | 無 | `html_hash` md 快取 + regenerate 配額 |
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

## Unit Tests（`tests/test_task07_onenote_to_markdown_v02.py`）

以 `unittest` 撰寫，全部 mock（不連 MongoDB / GCS / LLM）；在 import 前先注入假 env 以繞過 `e_onenote_download.py` 模組層的 `ONENOTE_CLIENT_ID` 守門。

| 測試類別 | 測試對象 | 測試重點 |
|---------|---------|---------|
| `NowUtcTests` | `_now_utc()` | 回 UTC timezone-aware datetime |
| `EnvironmentEnumTests` | `Environment` StrEnum | 合法值、非法值 raise ValueError |
| `LogApiCallTests` | `log_api_call()` | 寫入 `html_hash`/`downloaded`/`event_type`、MongoDB 失敗不 raise |
| `LogEnrichmentCallTests` | `log_enrichment_call()` | cache hit 時 tokens=0、`trigger`/`event_type` 正確 |
| `UpsertVersionMetaTests` | `upsert_version_meta()` | filter key 為 `(page_id, dt)`、`$setOnInsert` 選用、db 失敗不 raise |
| `HashingTests` | `html_source_hash()` | 決定性、內容不同 hash 不同 |
| `GcsPrefixTests` | `gcs` 路徑組裝 | raw/processed prefix、`gs_uri`、`_split_uri` |
| `SanitizeTests` | `sanitize()` | 禁用字元替換、空字串回 Untitled |
| `ApiGetTests` | `api_get()` | 成功回傳、4xx 直接拋不重試、傳輸層錯誤重試（`status_code=0`）、重試耗盡收尾 log 後 raise、timeout 常數 |
| `ExtractUserAccountTests` | `_extract_user_account()` | 從 self URL 萃取帳號前段、無 match 回 None |
| `DownloadNotebooksFailedBranchTests` | `download_notebooks()` | content 失敗時傳給 `upsert_version_meta` 的參數契約（`fetched_failed`、`$set`/`$setOnInsert` 無 key 重疊） |
| `CircuitGuardTests` | `_LLMServiceGuard` | 達門檻開斷路、success 歸零計數 |
| `ClassifyNoteTypeTests` | `_classify_note_type()` | 有日期 → daily_log、無日期 → knowledge_summary |
| `ConvertImgTagTests` | `convert_img_tag_to_md_str()` | img 轉 Markdown 語法 |
| `CallLlmMultimodalTests` | `_img_mime()` / `_call_llm()` | mime 推斷、contents 含圖片 part、無圖只送文字、token usage |
| `EnrichPageTests` | on-demand 入口 | not_found / cache-hit 略過 LLM / circuit-open 維持 bronze / regenerate 配額超限 |

執行方式：
```bash
poetry run python -m unittest tests.test_task07_onenote_to_markdown_v02 -v
```

> **測試狀態**：37 個測試全數通過（`Ran 37 tests OK`）。測試檔的 import／`@patch` 目標與函式名皆已對齊 `task07_onenote_to_markdown_lazy_loading` package（Silver 模組 `t_enrich_html_to_markdown`、入口函式 `t_enrich_html_to_markdown`）。

---

## 此分支（v02）完成範圍

**已完成（Bronze + Silver 服務本體，本機地端階段）**
- [x] Bronze Extract：MSAL device-flow + Graph API 下載 HTML/圖片 + 速率控制 + `html_hash` 變動判定 + `dt=` 分區寫 GCS + C1/C3 稽核
- [x] Silver Transform：on-demand `t_enrich_html_to_markdown()` + `html_hash` 冪等快取 + LLM 服務級斷路器 + 多模態圖片判讀 + regenerate 配額 + C2 稽核
- [x] Silver Load：enriched md 寫 GCS + upsert C3（`pending_review`）
- [x] `main.py` 只跑 Bronze ETL（不含 LLM）
- [x] `utils/`：`audit_log.py`（C1/C2/C3）、`gcs.py`（資料湖三層路徑）、`hashing.py`（sha256 變動鍵）
- [x] Unit tests 覆蓋各模組型別正確性與例外處理（37 個測試全數通過）

**後續待開發（跨分支）**
- [ ] Silver→Gold on-demand 觸發點與多版本對照審查頁（`feature/dashboard-ui`）——圓鈕切換同名筆記 1~5 版、點未處理版本即時生成 md、人工核可後 Archive
- [ ] Gold layer：最終清洗、歸檔（`archived`）與向量化（`embedded_status`）
- [ ] 雲端部署（Bronze 每週 Cloud Run Job；Silver 服務隨 dashboard Cloud Run Service）

---

*本摘要涵蓋 `feature/html-to-markdown` 分支中 task07 v02（`task07_onenote_to_markdown_lazy_loading/`）的所有腳本與測試，於 2026-07-01 記錄。*
