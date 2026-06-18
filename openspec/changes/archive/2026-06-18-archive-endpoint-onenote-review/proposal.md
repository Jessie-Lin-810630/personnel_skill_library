## Why

`onenote_review.py` 已完成 HTML vs MD 審核頁面，使用者可按下 Approve/Reject，但 Archive 端點尚未實作，導致按下後只能看到連線失敗錯誤。需要實作獨立的 Archive 端點服務，讓審核流程閉環。

## What Changes

- 新增 `archive_service/app.py`：獨立的 Flask Archive 端點（`POST /archive`），接收 `page_id`、`role`、`action`，執行 GCS staging → personal vault 歸檔與 MongoDB 狀態更新
- 新增 `dashboard_ui/utils/gcs_archiver.py`：封裝 Archive 服務所需的 GCS 寫入操作（複製 PNG、讀取並改寫 MD 圖片路徑、寫入 personal-vaults），staging vault 物件在歸檔後不做任何刪除

## Capabilities

### New Capabilities

- `archive-endpoint`：Flask Archive 端點，接收審核動作，執行 GCS 物件複製/寫入與 MongoDB `onenote_page_metadata` 狀態更新

## Impact

- **新增檔案**：`archive_service/app.py`、`dashboard_ui/utils/gcs_archiver.py`
- **依賴**：`flask`（需加入 pyproject.toml）、`google-cloud-storage`（已有）、`pymongo`（已有）
- **GCS bucket 寫入**：`personal-vaults`（需 service account 持有 `roles/storage.objectCreator` on `personal-vaults`）
- **GCS bucket 唯讀**：`onenote-vaults`（staging；歸檔後不刪除）
- **MongoDB collection**：`onenote_page_metadata`（upsert `status`, `review_result`, `reviewed_by_role`, `reviewed_at`, `md_archive_path`, `img_archive_path`, `archived_at`）
- **環境變數（人工新增）**：`ARCHIVE_PERSONAL_BUCKET`（預設 `personal-vaults`）
- **不包含**：雲端部署（步驟 9–11）、staging vault 自動刪除
