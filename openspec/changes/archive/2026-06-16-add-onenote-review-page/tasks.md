## 1. MongoDB 查詢工具

- [x] 1.1 在 `dashboard_ui/utils/interact_with_mongodb.py` 新增 `get_onenote_pages(db) -> list[dict]`，查詢 `onenote_page_metadata` 的必要欄位（`page_id`, `notebook`, `section`, `page_title`, `html_path`, `md_path`, `status`, `review_result`, `reviewed_at`）

## 2. GCS 讀取工具

- [x] 2.1 新增 `dashboard_ui/utils/gcs_reader.py`，以 `GOOGLE_APPLICATION_CREDENTIALS` 初始化 `storage.Client`
- [x] 2.2 實作 `read_text(bucket, blob_path) -> str`（讀取 HTML / MD）
- [x] 2.3 實作 `read_bytes_as_base64(bucket, blob_path) -> str`（讀取 PNG 並回傳 base64 data URI 字串）
- [x] 2.4 實作 `local_path_to_gcs_blob(local_path: str) -> str`：將 `html_path`（本地絕對路徑）轉為 GCS blob 路徑（strip `ONENOTE_OUTPUT_DIR/` prefix）

## 3. 審核頁面主體

- [x] 3.1 新增 `dashboard_ui/pages/onenote_review.py`，設定 `st.set_page_config`（layout="wide"）
- [x] 3.2 實作 demo 登入 gate（`REVIEW_PAGE_PASSWORD` 環境變數，`st.session_state.authenticated`）
- [x] 3.3 實作角色選擇 `st.radio`，結果存入 `st.session_state.role`
- [x] 3.4 實作三層下拉選擇器（筆記本 → 章節 → 頁面），資料來自 `get_onenote_pages()`
- [x] 3.5 實作狀態標籤：`pending_review` 顯示橘色標籤，`archived` 顯示綠色橫幅（含 `reviewed_at`），其他狀態顯示灰色標籤
- [x] 3.6 實作左欄 HTML 渲染：從 GCS 讀取 HTML，將 `_images/{id}` 圖片路徑替換為 base64 data URI，以 `st.components.v1.html()` 渲染
- [x] 3.7 實作右欄 MD 渲染：從 GCS 讀取 MD，將 `![](\_images/foo.png)` 替換為 base64 data URI，以 `st.markdown()` 渲染
- [x] 3.8 實作頁面底部 Approve / Reject 按鈕，`archived` 狀態時 `disabled=True`
- [x] 3.9 實作按鈕 `POST {ARCHIVE_ENDPOINT_URL}` 呼叫（`page_id`, `role`, `action`），以 try/except 捕捉連線錯誤並顯示訊息

## 4. 側邊欄整合

- [x] 4.1 在 `dashboard_ui/utils/ui_elements.py` 的 `_render_side_bar()` 新增 `st.sidebar.page_link("pages/onenote_review.py", label="OneNote Review", icon="🔍")`

## 5. 本地檢視驗證

- [x] 5.1 確認 `.env.example` 新增 `REVIEW_PAGE_PASSWORD` 與 `ARCHIVE_ENDPOINT_URL` 佔位符
- [x] 5.2 執行 `poetry run streamlit run dashboard_ui/app.py`，瀏覽器驗證以下路徑：demo 登入、角色選擇、三層選擇器、HTML/MD 並排顯示、按鈕停用（已歸檔頁面）
