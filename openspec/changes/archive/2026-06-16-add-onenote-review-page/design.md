## Context

task07 pipeline 已將 OneNote HTML → Gemini MD 的結果同步至 GCS bucket `onenote-vaults`（staging vault），並在 MongoDB Atlas `onenote_page_metadata`（Collection 3）記錄每頁的生命週期狀態。目前缺少前端工具讓使用者在批准前對比原始 HTML 與 LLM 輸出的 MD，並觸發後續 Archive 端點。

本設計在既有 `feature/dashboard-ui` 分支的 Streamlit dashboard 架構下，新增第三個頁面 `onenote_review.py`。

## Goals / Non-Goals

**Goals:**
- Streamlit 頁面從 GCS `onenote-vaults` 取得 HTML / MD / PNG（唯讀）
- 從 MongoDB `onenote_page_metadata` 讀取 pending_review 狀態的頁面清單
- 左欄渲染 HTML，右欄渲染 MD（含相對圖片路徑處理）
- Demo 登入（session password）擋陌生人
- 筆記本 → 章節 → 頁面 三層下拉選擇器
- Approve / Reject 按鈕呼叫 Archive 端點（POST /archive），已歸檔頁面停用按鈕並顯示橫幅
- 與既有 dashboard 側邊欄整合（新增 OneNote Review 連結）

**Non-Goals:**
- Archive 端點實作（獨立腳本，不在本 change）
- GCS 寫入權限
- 雲端部署 / Docker 修改
- 非 `onenote_page_metadata` 的其他 collection 操作

## Decisions

### 1. GCS 讀取：`google-cloud-storage` SDK（已在 pyproject.toml）

`gcs_reader.py` 以 `GOOGLE_APPLICATION_CREDENTIALS` 初始化 `storage.Client`，提供：
- `read_text(bucket, blob_path) -> str`：讀取 HTML / MD 文字
- `read_bytes(bucket, blob_path) -> bytes`：讀取 PNG 圖片
- `list_blobs(bucket, prefix) -> list[str]`：列出 staging vault 的 blob 路徑

本地路徑 → GCS blob 路徑的對應規則：`{帳號}/{筆記本}/{章節}/{頁名}.html`（strip `ONENOTE_OUTPUT_DIR/` prefix）。`onenote_page_metadata` 的 `html_path` 欄位儲存本地絕對路徑，轉換時以 `ONENOTE_OUTPUT_DIR` 為基準切割。

**替代方案考量**：直接用 `gsutil` CLI → 較難整合至 Streamlit session，排除。

### 2. Demo 登入：session_state password gate

在 `onenote_review.py` 開頭以 `st.session_state.get("authenticated")` 判斷，未通過則顯示密碼輸入框並 `st.stop()`。密碼從 `.env` 的 `REVIEW_PAGE_PASSWORD` 讀取，不 hardcode。

**替代方案考量**：Streamlit Community Cloud 的 `st.secrets` → 部署時再遷移，本地開發用 `.env` 即可。

### 3. HTML 渲染：`st.components.v1.html()`

HTML 包含 CSS 與圖片相對路徑。圖片部分需將 `_images/{id}.png` 替換為 base64 data URI（從 GCS 讀取 bytes 後 base64 encode），避免 Streamlit iframe 無法存取相對路徑的問題。

**替代方案考量**：serve static files → 需要額外 HTTP server，複雜度高，排除。

### 4. MD 渲染：`st.markdown()`

MD 內的圖片路徑（`![](\_images/foo.png)`）同樣需替換為 base64 data URI，確保渲染正確。

### 5. Archive 觸發：`requests.post` 呼叫外部端點

按鈕按下後以 `requests.post(ARCHIVE_ENDPOINT_URL, json={note_id, role})` 呼叫 Archive 端點（URL 從 `.env` 的 `ARCHIVE_ENDPOINT_URL` 讀取）。本地開發時可指向 `http://localhost:8001/archive`，端點尚未實作時按鈕顯示但操作會回傳連線錯誤訊息（不 crash）。

### 6. 角色選擇

登入後頁面上方顯示角色選擇 `st.radio`：ML/DL Engineer、Note Owner、Dept. Senior Specialist。選擇結果存入 `st.session_state.role` 並隨 POST 請求帶出。

### 7. MongoDB 查詢：新增函式至 `interact_with_mongodb.py`

`get_onenote_pages(db) -> list[dict]`：查詢 `onenote_page_metadata`，回傳所有頁面的必要欄位（`page_id`, `notebook`, `section`, `page_title`, `html_path`, `md_path`, `status`, `review_result`, `reviewed_at`）。不加狀態過濾，讓前端顯示所有頁面（已歸檔頁面顯示橫幅）。

## Risks / Trade-offs

- **GCS 圖片 base64**：圖片多時頁面初始載入慢 → 接受，demo 規模可接受；未來可加 lazy load
- **Archive 端點尚未實作**：按鈕 POST 會失敗 → 用 try/except 顯示錯誤訊息，不 crash Streamlit
- **ONENOTE_OUTPUT_DIR 路徑轉換**：若使用者未設定環境變數，GCS blob 路徑轉換會失敗 → 加 guard 提示
- **Demo 登入安全性低**：明文密碼在 session_state → 符合「demo 級」定位，不過度開發
