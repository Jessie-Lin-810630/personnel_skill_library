## Why

task07 的 lazy_loading 變體目前只跑到 Bronze：每週 ETL 下載 OneNote html、以 `dt=` 分區存 GCS、upsert `onenote_note_metadata`（status=`bronze_stored`），完全不呼叫 LLM。Silver enrichment 服務本體 `t_enrich_html_to_markdown(page_id, dt, trigger)` 已合併進 `task07_onenote_to_markdown_lazy_loading/`，但**尚無任何觸發點**——沒有人能讓它跑起來、把 markdown 產到 GCS `processed-notes/`。

依 hand-over 設計，Silver 的 enrichment 一律 on-demand：使用者在審查頁點擊某個尚未處理的版本時才即時觸發。因此需要（1）把 Silver 服務端點化，（2）新增多版本對照審查頁作為 on-demand 觸發點，讓審查者切換同名筆記的各 `dt=` 版本、左右對照 bronze html 與 silver md、按需生成。

## What Changes

- 新增 **Flask Silver enrich 端點**（`silver_service/app.py`，`POST /enrich`）：接收 `page_id`、`dt`、`trigger`，內部呼叫既有 `t_enrich_html_to_markdown`，回傳 `status`、`cache_hit`、`md_path`、`circuit_open`。比照既有 `archive_service/app.py` 模式，讓 Streamlit 維持唯讀、不直接呼叫 ETL。
- 新增 **lazy_loading 專用多版本對照審查頁**（`dashboard_ui/pages/` 新頁）：讀 `onenote_note_metadata` 依 page 分組，以 `dt=` 圓鈕切換同名筆記的多個版本；左渲染 bronze html、右渲染 silver md（皆自 GCS `gs://` URI 讀取）。
  - 點到 `md_path=null`（未 enrich）的版本時，`POST` 呼叫 Silver enrich 端點 on-demand 生成 md 後渲染；已生成的版本直接讀 GCS 既有 md（cache hit、零成本）。
  - 含 `regenerate` 按鈕（走 `trigger=regenerate`、受 quota 限制）與 `approve`/`reject` **佔位**按鈕（先渲染，Gold 後端於下一階段接上）。
- 新增讀取封裝：查 `onenote_note_metadata` 多版本清單、直接以 `gs://` URI 讀 GCS 物件（不沿用原版 `local_path_to_gcs_blob` 的本機路徑假設）。
- **不改動**既有 `dashboard_ui/pages/onenote_review.py`（原版 task07 專用）——依 CLAUDE.md，兩版 task07 並存，各自接審查 UI 供使用者遴選。

## Capabilities

### New Capabilities
- `silver-enrich-endpoint`: Flask 端點接收 `page_id`+`dt`+`trigger`，呼叫 Silver 服務本體做 on-demand enrichment，寫 md 到 GCS `processed-notes/` 並回報結果；不主動刪除任何 bronze 版本。
- `onenote-versioned-review-page`: 多版本對照審查頁，讀 `onenote_note_metadata` 依 page 分組、`dt=` 圓鈕切換版本、左右對照 html/md、on-demand 觸發 Silver 端點生成 md，含 regenerate 與 approve/reject 佔位按鈕。

### Modified Capabilities
（無——本次不修改既有 spec 的 requirements；既有 `onenote-review-page`、`archive-endpoint` spec 屬原版 task07，保持不動。）

## Impact

- **新增檔案**：`silver_service/app.py`、`silver_service/__init__.py`、`silver_service/utils/`（視需要的 mongodb/gcs 封裝或直接複用 task07 lazy_loading utils）、`dashboard_ui/pages/<lazy_review_page>.py`、`dashboard_ui/utils/` 內新增 lazy_loading 版多版本查詢與 gs:// 讀取 helper。
- **呼叫的既有模組**：`task07_onenote_to_markdown_lazy_loading.t_enrich_html_to_markdown`（Silver 服務本體，不修改）。
- **MongoDB collection**：`onenote_note_metadata`（C3，主鍵 `page_id`+`dt`）唯讀查詢（審查頁）；狀態 upsert 由 Silver 服務本體在 enrich 時執行（`status=pending_review`、`md_path`、`md_md5`、`md_exported_at`）。
- **GCS bucket**：`onenote-vaults`——`raw-notes/`（bronze html/png）唯讀、`processed-notes/`（silver md）由 Silver 端點寫入。
- **依賴**：`flask`（archive_service 已引入）、`google-cloud-storage`、`pymongo`、`google-genai`（皆已有）。
- **環境變數（人工新增）**：`SILVER_ENDPOINT_URL`（審查頁呼叫端點的 URL，如 `http://localhost:8002/enrich`）。
- **不包含**：Gold layer（最終清洗、歸檔、向量化，hand-over 第 167-185 行）留待下一階段；雲端部署（步驟 9-11）。
