## Context

`onenote_review.py` 已實作完成，按下 Approve/Reject 時透過 `requests.post(ARCHIVE_ENDPOINT_URL, json={page_id, role, action})` 呼叫 Archive 端點。Archive 端點須為獨立服務（非 Streamlit 的一部分），持有 GCS `personal-vaults` 寫入權限 + `onenote-vaults` 唯讀權限。

本設計實作本地開發版本的 Archive 端點，以 Flask 提供 `POST /archive`，並在 `dashboard_ui/utils/gcs_archiver.py` 封裝所有 GCS 寫入邏輯。

## Goals / Non-Goals

**Goals:**
- Flask 端點接收 `{page_id, role, action}`
- `action == "approved"` 時執行 GCS 歸檔：
  - 把 staging PNG 複製到 `personal-vaults/{account}/from-onenote/{note_type}/{notebook}/{section}/_attachment/`
  - 讀 staging MD，將 `_images/foo.png` 改寫為相對路徑 `./_attachment/foo.png`，寫入 `personal-vaults/{account}/from-onenote/{note_type}/{notebook}/{section}/{page}.md`
- `action == "rejected"` 時只更新 MongoDB 狀態，不觸動 GCS
- 更新 MongoDB `onenote_page_metadata`（status, review_result, reviewed_by_role, reviewed_at, md_archive_path, img_archive_path, archived_at）
- staging vault 物件（html/md/png）歸檔後不刪除（步驟 8）
- `gcs_archiver.py` 放在 `dashboard_ui/utils/`（與 gcs_reader.py 同層）

**Non-Goals:**
- staging 物件刪除
- 雲端部署 / Cloud Run
- 批次歸檔
- 身份驗證（本地 demo，安全性由 Streamlit demo 登入承擔）

## Decisions

### 1. Archive 端點框架：Flask

本地 `POST /archive` 端點。Flask 夠輕量，不需要 FastAPI 的 async 特性。  
**啟動**：`poetry run flask --app archive_service.app run --port 8001`

### 2. GCS 歸檔工具：`gcs_archiver.py` 放 `dashboard_ui/utils/`

與 `gcs_reader.py` 同層，提供：
- `copy_images(page_record: dict) -> list[str]`：複製 staging PNG → personal-vaults，回傳已複製的 blob 路徑列表
- `archive_md(page_record: dict, img_archive_paths: list[str]) -> str`：讀 staging MD，改寫圖片路徑，寫入 personal-vaults，回傳新 blob 路徑
- 兩函式均不刪除 staging 物件（步驟 8 約束）

### 3. 圖片路徑改寫規則

staging MD 中圖片為 `_images/foo.png`（相對路徑）。  
archive 後 MD 位於 `personal-vaults/{account}/from-onenote/{note_type}/{notebook}/{section}/{page}.md`，圖片位於同層的 `_attachment/foo.png`。  
改寫時以 `./_attachment/foo.png` 取代 `_images/foo.png`（保持相對路徑，滿足 Obsidian 渲染）。

### 4. note_type 來源

從 MongoDB `onenote_page_metadata` 查 `note_type` 欄位。若查無值，預設為 `uncategorized`。

### 5. MongoDB 更新時序

`img_archive_path` 在 PNG 寫入完成後立即 upsert；`md_archive_path` 在 MD 寫入完成後立即 upsert。兩者都完成後，一次 upsert `status`, `review_result`, `reviewed_by_role`, `reviewed_at`, `archived_at`。

### 6. 錯誤回應

GCS/MongoDB 操作失敗時回傳 HTTP 500 + `{error: message}`，讓 Streamlit 頁面的 try/except 顯示錯誤訊息。

## Risks / Trade-offs

- **Flask 單執行緒**：本地 demo 可接受；Cloud Run 部署時改用 gunicorn
- **personal-vaults 權限**：需 service account 有寫入權限，由使用者手動設定
- **note_type 缺值**：預設 `uncategorized`，不擋流程
