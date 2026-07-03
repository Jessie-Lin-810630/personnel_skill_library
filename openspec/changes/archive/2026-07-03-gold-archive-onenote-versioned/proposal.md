## Why

task07 lazy_loading 變體的 Silver 已可 on-demand 生成 md 到 GCS `processed-notes/`，審查頁的
`approve`/`reject` 目前仍是佔位按鈕。需要 Gold layer 把人工 `approved` 的 md 做最終歸檔，
讓審查流程閉環：md 與其引用 png 歸檔到 `archived-notes/`、C3 生命週期翻到 `archived`、
再讀回歸檔 md 萃取 frontmatter（tags/date/type/alias）寫入 C3 供後續檢索使用。

依調整後的 hand-over（第 167-192 行），本 Gold layer **不含向量化**——向量化解耦到另一條
pipeline（feature/etl-pipeline task06）後續獨立部署，避免初期模型頻繁調整造成管道黏著。

## What Changes

- 新增 **Gold Load 服務本體** `task07_onenote_to_markdown_lazy_loading/l_archive_note.py`：
  `archive_note(page_id, dt, role)` 執行歸檔（複製 md + png 到 `archived-notes/`）、upsert C3、
  讀回歸檔 md 萃取 frontmatter 再 upsert C3。含「同名一次只認可一份」把關。
- 新增 **Flask Gold/Archive 端點** `gold_service/app.py`（`POST /archive`，帶 `page_id`+`dt`+`role`+`action`），
  比照 `silver_service`/`archive_service` 模式，內部呼叫 `archive_note`（approve）或標記 `review_closed`（reject）。
- 擴充 `task07_onenote_to_markdown_lazy_loading/utils/gcs.py`：新增 `archived_note_prefix`、`download_bytes`、
  `copy_blob`（GCS 物件複製並取新 md5）。
- 擴充 `utils/audit_log.py`：新增查同頁是否已有 `archived` 版本的 helper（供把關與 UI 停用按鈕）。
- 更新審查頁 `dashboard_ui/pages/onenote_versioned_review.py`：`approve`/`reject` 佔位改為 POST Gold 端點；
  該 page_id 已有 `archived` 版本時，全部 dt 版本的操作按鈕失效並顯示「已歸檔」橫幅。
- **不含**：向量化（解耦至 task06 pipeline）；不改原版 `archive_service/`（原版 task07 專用）。

## Capabilities

### New Capabilities
- `gold-archive-endpoint`: Flask 端點接收 approve/reject，approve 時呼叫 Gold Load 把 md+png 歸檔到
  `archived-notes/`、upsert C3（`archived`、歸檔路徑、frontmatter metadata），reject 標記 `review_closed`；
  含「同名一次只認可一份」把關。不做向量化。

### Modified Capabilities
（無新的 spec delta——審查頁 `approve`/`reject` 由佔位改為呼叫 Gold 端點屬實作接線，其可觀察契約
併入 `gold-archive-endpoint` spec 的呼叫端行為場景；`onenote-versioned-review-page` 的既有 spec 於
silver 變更 archive 後才進 `openspec/specs/`，故此處不另立 delta。）

## Impact

- **新增檔案**：`task07_onenote_to_markdown_lazy_loading/l_archive_note.py`、`gold_service/app.py`、`gold_service/__init__.py`、`tests/test_gold_service_endpoint.py`。
- **修改檔案**：`task07_onenote_to_markdown_lazy_loading/utils/gcs.py`、`utils/audit_log.py`、`dashboard_ui/pages/onenote_versioned_review.py`、`dashboard_ui/utils/interact_with_mongodb.py`（`get_onenote_versioned_pages` 補 review_result/md_archive_path/archived_at 欄位）、CLAUDE.md。
- **GCS bucket**：`onenote-vaults`——`processed-notes/`（silver md）、`raw-notes/`（png）唯讀來源；`archived-notes/`（gold）寫入。
- **MongoDB collection**：`onenote_note_metadata`（C3，主鍵 `page_id`+`dt`）upsert：`status`、`review_result`、`reviewed_by_role`、`reviewed_at`、`archived_at`、`md_archive_path`、`img_archive_path`、`tags`、`date`、`type`、`alias`、`error_msg`。
- **依賴**：`flask`、`google-cloud-storage`、`pymongo`、`python-frontmatter`（皆已在 pyproject）。
- **環境變數（人工新增到 .env）**：`GOLD_ENDPOINT_URL`（如 `http://localhost:8003/archive`）。
- **路徑決策**：歸檔路徑採 hand-over 階層圖的 `gs://onenote-vaults/archived-notes/<user>/<notebook>/<section>/dt=<dt>/`（對齊既有單一 bucket 設計）。
