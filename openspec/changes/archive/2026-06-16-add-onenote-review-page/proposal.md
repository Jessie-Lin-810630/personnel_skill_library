## Why

task07 已完成 OneNote HTML → Gemini Markdown 轉換並同步至 GCS staging vault，但使用者目前沒有視覺化工具可以對比原始 HTML 與 LLM 輸出的 MD，也無法對審核結果進行確認，阻礙了後續 Archive 流程的觸發。

## What Changes

- 新增 `dashboard_ui/pages/onenote_review.py`：全新的 Streamlit 審核頁面
- 新增 `dashboard_ui/utils/gcs_reader.py`：從 GCS bucket `onenote-vaults` 讀取 HTML / MD / PNG 的工具函式
- 新增 MongoDB 查詢函式到 `dashboard_ui/utils/interact_with_mongodb.py`：讀取 `onenote_page_metadata` (Collection 3)

## Capabilities

### New Capabilities

- `onenote-review-page`：Streamlit 對照審核頁面，支援 demo 登入、筆記選擇器、HTML vs MD 並排渲染、狀態顯示、確認/退回按鈕

### Modified Capabilities

- `dashboard-navigation`：側邊欄新增「OneNote Review」連結

## Impact

- **新增檔案**：`dashboard_ui/pages/onenote_review.py`、`dashboard_ui/utils/gcs_reader.py`
- **修改檔案**：`dashboard_ui/utils/interact_with_mongodb.py`（新增 Collection 3 查詢）、`dashboard_ui/utils/ui_elements.py`（側邊欄連結）
- **依賴**：`google-cloud-storage`（已在 pyproject.toml 的 task06 path 或需確認）、`pymongo`（已有）
- **GCS bucket**：`onenote-vaults`（唯讀，讀取 HTML / MD / PNG）
- **MongoDB collection**：`onenote_page_metadata`（唯讀查詢；寫入由 Archive 端點負責，不在本 change 範圍）
- **不包含**：Archive 端點（步驟 5–6）、雲端部署（步驟 9–11）
