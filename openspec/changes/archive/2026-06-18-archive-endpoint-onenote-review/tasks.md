## 1. 依賴套件

- [x] 1.1 在 `pyproject.toml` 加入 `flask` 依賴，執行 `poetry add flask`

## 2. GCS 歸檔工具（`dashboard_ui/utils/gcs_archiver.py`）

- [x] 2.1 建立 `dashboard_ui/utils/gcs_archiver.py`，讀取 `ARCHIVE_PERSONAL_BUCKET`（預設 `personal-vaults`）環境變數
- [x] 2.2 實作 `copy_images(page_record: dict) -> list[str]`：
  - 從 `page_record` 取得 `html_path`，推導 staging section blob prefix（strip `ONENOTE_OUTPUT_DIR/`）
  - 列出 staging `onenote-vaults/{prefix}/_images/` 下的所有 PNG blob
  - 從 `page_record` 取得 `note_type`（預設 `uncategorized`）、`notebook`、`section`
  - 逐一複製 PNG 到 `personal-vaults/{account}/from-onenote/{note_type}/{notebook}/{section}/_attachment/{filename}`
  - 回傳複製完成的 personal-vaults blob 路徑列表
  - **不刪除** staging PNG
- [x] 2.3 實作 `archive_md(page_record: dict, img_archive_paths: list[str]) -> str`：
  - 從 `page_record` 取得 `md_path`，推導 staging MD blob（strip `ONENOTE_OUTPUT_DIR/`）
  - 從 GCS 讀取 MD 文字
  - 將 `_images/{filename}` 替換為 `./_attachment/{filename}`
  - 將 MD 寫入 `personal-vaults/{account}/from-onenote/{note_type}/{notebook}/{section}/{page}.md`
  - 回傳新的 personal-vaults blob 路徑
  - **不刪除** staging MD
- [x] 2.4 兩函式若失敗均 raise exception（由 Flask endpoint catch）

## 3. Archive 端點（`archive_service/app.py`）

- [x] 3.1 建立 `archive_service/__init__.py`（空檔）
- [x] 3.2 建立 `archive_service/app.py`，設定 Flask app，從 `.env` 讀取 `MONGO_ALTAS_URI`、`MONGO_DB_NAME`、`GOOGLE_APPLICATION_CREDENTIALS`
- [x] 3.3 實作 `POST /archive`，接收 JSON body `{page_id, role, action}`，驗證欄位存在
- [x] 3.4 從 MongoDB `onenote_page_metadata` 以 `page_id` 查詢頁面記錄，若查無則回 404
- [x] 3.5 `action == "approved"` 時：
  - 呼叫 `copy_images(page_record)`，完成後 upsert `img_archive_path`
  - 呼叫 `archive_md(page_record, img_archive_paths)`，完成後 upsert `md_archive_path`
  - 兩者都完成後，upsert `status="archived"`, `review_result="approved"`, `reviewed_by_role=role`, `reviewed_at=utcnow`, `archived_at=utcnow`
- [x] 3.6 `action == "rejected"` 時：
  - 只 upsert `status="rejected"`, `review_result="rejected"`, `reviewed_by_role=role`, `reviewed_at=utcnow`
  - 不觸動 GCS
- [x] 3.7 成功回傳 HTTP 200 + `{status: "ok"}`；失敗回傳 HTTP 500 + `{error: message}`

## 4. 本地驗證

- [x] 4.1 確認 `.env.example` 新增 `DESTINATION_BUCKET=personal-vaults` 佔位符（環境變數名稱為 `DESTINATION_BUCKET`）
- [x] 4.2 執行 `poetry run flask --app archive_service.app run --port 8001` 確認啟動無錯誤
- [x] 4.3 在另一個 terminal 啟動 Streamlit，選一個 `pending_review` 頁面，按下 Approve，確認 MongoDB `onenote_page_metadata` 的 `status` 即時更新為 `archived`（前端即時渲染，無後端寫入與前端顯示延遲差）
- [x] 4.4 確認 staging `onenote-vaults` 的 html/md/png 物件未被刪除
