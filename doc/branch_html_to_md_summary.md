# Feature Branch: `feature/html-to-markdown` — Task07 開發執行成果摘要

> **開發目標**：為慣用 Microsoft OneNote 筆記軟體但不習慣 Markdown 語法的使用者，建立一條 ETL pipeline，透過 Microsoft Graph API 抓取 OneNote HTML 頁面，以 Gemini LLM 重整結構並萃取關鍵字，最終輸出符合 Markdown 格式的 `.md` 檔案，作為 AI RAG 知識庫擴充的基礎。

> **開發起始日期**：2026-05-30

> **執行環境**：macOS / VS Code / pyenv (Python 3.14) / Poetry / MongoDB Atlas / Azure App Registration（公用用戶端，委派式驗證）

---

## 專案資料夾結構

```
feature/html-to-markdown/
├── .env                                          # 金鑰集中管理（不進 git）
├── poetry.lock
├── pyproject.toml
│
├── task07_onenote_to_markdown/
│   ├── __init__.py
│   ├── e_onenote_download.py                     # Extract：MSAL device-flow 取得 token，
│   │                                             # 呼叫 Graph API 下載 HTML 與圖片至本機
│   ├── t_html_to_markdown.py                     # Transform：解析 HTML、呼叫 Gemini LLM
│   │                                             # 重整結構並萃取 tags/alias，組合 frontmatter
│   ├── l_save_markdown.py                        # Load：將 .md 寫至本機，upsert Collection 3
│   ├── main.py                                   # 串接 E → T → L 的入口
│   └── utils/
│       └── audit_log.py                          # MongoDB 寫入工具（三個 collections）
│
└── tests/
    └── test_task07_onenote_to_markdown.py        # Unit tests（unittest）
```

---

## Task 07 — OneNote ETL

### 資料來源

Microsoft OneNote（個人帳號），透過 Microsoft Graph API 存取。

| API 端點 | 用途 |
|----------|------|
| `GET /me/onenote/notebooks` | 列出所有筆記本 |
| `GET /me/onenote/notebooks/{id}/sections` | 列出章節 |
| `GET /me/onenote/sections/{id}/pages` | 列出頁面清單 |
| `GET /me/onenote/pages/{id}/content` | 取得頁面 HTML 內容 |
| `GET {resource_url}` | 下載嵌入圖片 |

### ETL 設計重點

#### Extract（`e_onenote_download.py`）

- **驗證**：MSAL `PublicClientApplication` + Device Flow；Token 快取於 `~/.config/onenote-skill/token_cache.json`，過期自動靜默刷新（`acquire_token_silent`），401 時重試
- **速率控制**：`RateLimiter` 以滑動視窗追蹤每分鐘 115 次、每小時 380 次（低於 OneNote 官方上限 120/min、400/hour），429 時讀取 `Retry-After` header 加指數退避；5xx 亦指數退避；最多重試 10 次
- **帳號萃取**：從 section 的 `self` URL（`/users/<email>/onenote/...`）萃取 `@` 前段作為本機目錄名稱（如 `lucky460721`）
- **圖片處理**：偵測 `<img>` 的 Graph API 圖片資源 URL，下載後存至 `_images/` 目錄，並將 HTML 內 `src` 改寫為相對路徑 `_images/{resource_id}.ext`
- **稽核寫入**：每次 API 請求 append `onenote_graph_api_logs`（Collection 1）；每頁下載後 upsert `onenote_page_metadata`（Collection 3）初始狀態（`status="fetched"`）
- **回傳**：`ONENOTE_OUTPUT_DIR/{帳號}` 的絕對路徑字串，供 Transform step 使用
- **本機目錄結構**：
  ```
  {ONENOTE_OUTPUT_DIR}/{帳號}/{筆記本}/{章節}/{頁面名}.html
  {ONENOTE_OUTPUT_DIR}/{帳號}/{筆記本}/{章節}/_images/{resource_id}.ext
  ```

#### Transform（`t_html_to_markdown.py`）

- **圖片預處理**：`convert_img_tag_to_md_str()` 將 `<img>` 標籤轉為 Markdown 語法 `![alt](src)` 字串，再以 `soup.get_text()` 取出純文字送入 LLM
- **頁面元數據**：從 `audit_log.get_page_meta()` 查回 Collection 3 取得 `page_id` 與 `html_created_at`，用於 frontmatter 的 `date` 欄位
- **LLM 呼叫**：使用 Google Vertex AI Gemini（`gemini-2.5-flash-lite`），以 Service Account JSON 驗證（`AGENT_PLATFORM_USER_CREDENTIALS`）；要求模型以 structured JSON 輸出，schema 強制包含 `tags`（5–10 個中英混合技術關鍵字）、`alias`（2–6 字簡短別名）、`new_content`（重整後 Markdown 內容）；最多重試 3 次；溫度 0.2 穩定化輸出結構
- **note_type 分類**：`_classify_note_type()` 以正規表示式偵測檔名中是否含日期格式（`YYYY-MM-DD`、`YYYYMMDD`、`YYYY年M月D日`），有則歸類為 `daily_log`，否則為 `knowledge_summary`
- **frontmatter 組合**：
  ```yaml
  ---
  tags:
    - "tag1"
    - "tag2"
  date: "YYYY-MM-DD"
  type: knowledge_summary | daily_log
  alias: "簡短別名"
  ---
  ```
- **LLM 稽核**：每次呼叫 append `gemini_llm_logs`（Collection 2），記錄 input/output/thinking/total tokens 與延遲時間
- **回傳**：`list[dict]`（每筆為一頁的完整資訊），不直接寫檔

#### Load（`l_save_markdown.py`）

- 將 `.md` 寫至與 HTML 同目錄（`html_path.with_suffix(".md")`）
- 以 `page_id` 為條件 upsert Collection 3，更新 `md_path`、`md_exported_at`、`note_type`、`status`、`error_msg`
- 狀態對照：

  | 上游 `page_status` | Collection 3 `status` |
  |-------------------|-----------------------|
  | `successed` | `pending_review` |
  | `upstream_task_failed` | `summarized failed` |
  | `save_failed` | `saved failed` |

#### 入口（`main.py`）

- E step 回傳 `export_dir`（`ONENOTE_OUTPUT_DIR/{帳號}`）
- 若未設定 `ONENOTE_SELECTED_NOTEBOOKS`，從 `export_dir` 的子目錄列出候選筆記本，於終端機互動選擇（支援序號或名稱輸入）
- 依序執行 T → L，傳入選定筆記本名稱列表

---

## MongoDB Collections

### Collection 1：`onenote_graph_api_logs`（只追加）

每筆 = 一次 Graph API 請求嘗試

```json
{
  "_id": "ObjectId",
  "page_id": "onenote-page-id",
  "timestamp": "2026-06-01T10:00:00Z",
  "event_type": "onenote_api_download",
  "user_id": null,
  "method": "GET",
  "api_endpoint": "https://graph.microsoft.com/v1.0/me/onenote/pages/{id}/content",
  "request_id": "abc12345ef67",
  "attempt_id": 1,
  "status": "success",
  "status_code": 200,
  "latency_ms": 312,
  "error_msg": null,
  "environment": "local",
  "html_path": "/Users/.../OneNote-Export/lucky460721/NB/Sec/page.html"
}
```

### Collection 2：`gemini_llm_logs`（只追加）

每筆 = 一次 Gemini LLM 呼叫嘗試

```json
{
  "_id": "ObjectId",
  "page_id": "onenote-page-id",
  "timestamp": "2026-06-01T10:01:00Z",
  "event_type": "gemini_llm_call",
  "user_id": null,
  "model": "gemini-2.5-flash-lite",
  "html_path": "/Users/.../page.html",
  "attempt_id": 1,
  "status": "success",
  "latency_ms": 4200,
  "input_tokens": 1850,
  "output_tokens": 640,
  "thinking_tokens": 120,
  "total_tokens": 2610,
  "error_msg": null,
  "environment": "local"
}
```

### Collection 3：`onenote_page_metadata`（以 `page_id` 為唯一鍵 upsert）

每筆 = 一頁 OneNote 的完整生命週期元數據，貫穿 E → T → L 三步驟逐步更新

```json
{
  "page_id": "onenote-page-id",
  "notebook": "工作筆記",
  "section": "資料工程",
  "page_title": "MongoDB 索引設計",
  "html_path": "/Users/.../MongoDB 索引設計.html",
  "html_created_at": "2025-12-20T00:46:09.898Z",
  "html_modified_at": "2025-12-21T00:51:00.121Z",
  "img_count_in_html": 2,
  "img_path": ["/Users/.../_images/res-abc.png"],
  "md_path": "/Users/.../MongoDB 索引設計.md",
  "md_exported_at": "2026-06-01T10:02:00Z",
  "note_type": "knowledge_summary",
  "status": "pending_review",
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

| 情境 | `status` | `review_result` |
|------|----------|-----------------|
| 剛從 Graph API 抓取完畢 | `fetched` | null |
| Gemini LLM 生成失敗 | `summarized failed` | null |
| LLM 有回但寫 .md 失敗 | `saved failed` | null |
| .md 產生成功、等待人工審核 | `pending_review` | null |
| 人工審核通過且歸檔成功 | `archived` | `approved` |
| 人工審核通過但歸檔失敗 | `archive_failed` | `approved` |
| 人工審核退回 | `review_closed` | `rejected` |

---

## 套件依賴

```
pymongo, msal, requests, beautifulsoup4, python-dotenv, loguru,
google-genai, google-auth
```

## .env 金鑰

```
ONENOTE_CLIENT_ID=          # Azure App Registration Client ID（公用用戶端）
ONENOTE_OUTPUT_DIR=         # HTML / .md 輸出根目錄
ONENOTE_NOTEBOOK_IDS=       # （選填）JSON array，指定要下載的 notebook ID
ONENOTE_SELECTED_NOTEBOOKS= # （選填）逗號分隔的 notebook 名稱；省略則互動選擇
AGENT_PLATFORM_USER_CREDENTIALS=  # Vertex AI Service Account JSON 路徑
GCP_PROJECT_ID=             # GCP 專案 ID
MONGO_ALTAS_URI=            # MongoDB Atlas 連線字串
MONGO_DB_NAME=              # MongoDB 資料庫名稱
ENVIRONMENT=                # local | dev | prod
```

---

## Unit Tests（`tests/test_task07_onenote_to_markdown.py`）

以 `unittest` 撰寫，共涵蓋 4 個模組：

| 測試類別 | 測試對象 | 測試重點 |
|---------|---------|---------|
| `NowUtcTests` | `_now_utc()` | 型別正確、時區為 UTC |
| `EnvironmentEnumTests` | `Environment` StrEnum | 合法值、非法值 raise ValueError |
| `LogApiCallTests` | `log_api_call()` | 寫入正確欄位、非法 env raise RuntimeError、MongoDB 失敗不 raise |
| `LogLlmCallTests` | `log_llm_call()` | token 欄位、失敗不 raise、非法 env raise RuntimeError |
| `GetPageMetaTests` | `get_page_meta()` | 找到回 dict、找不到回 {}、db error 回 {} |
| `UpsertPageMetadataTests` | `upsert_page_metadata()` | `$set` 正確、`$setOnInsert` 有/無、upsert=True、db 失敗不 raise |
| `SanitizeTests` | `sanitize()` | 禁用字元替換、空字串回 Untitled、合法名稱不變 |
| `ParseOnenoteDtTests` | `_parse_onenote_dt()` | Z 結尾、offset 格式、空字串 None、非法字串 None |
| `RateLimiterTests` | `RateLimiter` | 時間戳記錄、預設/自訂上限 |
| `ApiGetTests` | `api_get()` | 200 正常回傳、429 退避重試、5xx 退避重試、401 刷新 token、重試耗盡 raise RuntimeError |
| `GetAllTests` | `get_all()` | 單頁、分頁 nextLink、空 value |
| `ClassifyNoteTypeTests` | `_classify_note_type()` | 三種日期格式 → daily_log、無日期 → knowledge_summary |
| `ConvertImgTagTests` | `convert_img_tag_to_md_str()` | img 轉 Markdown 語法、無 alt 用 "image"、無圖片不變、多圖 |
| `THtmlToMarkdownTests` | `t_html_to_markdown()` | 回傳型別、所有 key 齊全、frontmatter 格式、Path 型別、img_count、LLM 失敗狀態、None 回傳狀態、目錄不存在 skip |
| `LSaveMarkdownTests` | `l_save_markdown()` | 寫檔成功、upsert page_id 正確、page_id None 跳過 upsert、狀態對照正確、寫檔失敗狀態、失敗不 raise、空清單不 raise、多頁全數處理 |

執行方式：
```bash
poetry run python -m unittest tests.test_task07_onenote_to_markdown -v
```

---

## 此分支完成範圍

**已完成（本機地端階段）**
- [x] E step：MSAL device-flow 驗證 + Graph API 下載 HTML 與圖片 + 速率控制 + 稽核日誌
- [x] T step：HTML → Gemini LLM 重整結構 + tags/alias 萃取 + YAML frontmatter 組合
- [x] L step：寫 .md 至本機 + upsert Collection 3
- [x] `main.py` 串接 E → T → L，支援互動選擇筆記本或環境變數指定
- [x] `utils/audit_log.py`：三個 MongoDB collections 的讀寫工具
- [x] Unit tests 覆蓋四個模組的型別正確性與例外處理

**後續待開發（跨分支）**
- [x] 步驟 3：將本機 HTML / MD / 圖片同步上傳至 GCS `onenote-vaults`（staging vault）
- [x] 步驟 4–8：`feature/dashboard-ui` 新增對照審核頁面（HTML vs. MD 並排、檢核按鈕、Archive 端點）
- [ ] 步驟 9–11：雲端部署（Cloud Run Service / Job）

---

*本摘要涵蓋 `feature/html-to-markdown` 分支中 task07 的所有腳本與測試，於 2026-06-15 完成記錄。*
