## Why

task01_v2（medallion 變體）產出了新的資料契約——`obsidian_note_metadata`（含 `status`、`embedded_status`、`archived_md_path`、`archived_md_md5_hash`、內嵌 `attached_images` 的 archived 路徑）與 `archived-notes/` 這層乾淨、隔離的清洗後 md——但目前沒有任何向量化消費端。現行 task06 仍吃 v1 的 `obsidian_notes` 與 GCS raw `.md`，無法對接 v2。本 change 建立 task06 的 v2 變體：從 archived 層做增量 embedding，並消費 task01_v2 的軟刪除訊號 purge 對應向量。此即 task01-v2 change 中 6.2 契約（`obsidian-note-soft-delete` spec 的「對 task06 曝露向量 purge 訊號」）的實作端。

## What Changes

- 新增 task06 的 v2 變體（新資料夾，暫名 `task06_obsidian_embed_etl_v2`），與現行 `task06_obsidian_embed_etl` 並存；現行 task06 不動。
- **Embedding gate 改讀 `obsidian_note_metadata`**：只挑 `status="archived"` 且 `embedded_status=false` 的筆記，取代現行 `get_notes_state()` 讀 `obsidian_notes` 的邏輯。
- **Embedding 來源改為 archived 層**：依 `archived_md_path` 從 `archived-notes/` 下載清洗後 md 做 chunking，多模態 embedding 時圖片改用 `attached_images[].archived_image_path`（archived 副本），沿用 Vertex AI `gemini-embedding-2`（1536 維、L2 normalize）。
- **寫入 v2 專用向量 collection `obsidian_vectors_v2`**（與 v1 `obsidian_vectors_multimodal` 完全隔離，需在 Atlas 手動建對應 Vector Search index）。以 note 的 `raw_md_path` 為向量血緣鍵，per note 先 `delete_many({raw_md_path})` 再 `insert_many`（重切冪等、不留孤兒）。
- **CAS 翻旗標**：以 `archived_md_md5_hash` 為守衛，只有該 note 仍 `embedded_status=false` 且 archived md5 未變才把 `embedded_status` 翻 `true`（避免 embed 過程中版本又更新造成誤標）。
- **新增 purge 消費端**：查 `status="deleted" AND embedded_status=true` 的筆記，`delete_many({raw_md_path})` 清 `obsidian_vectors_v2` 對應向量後，把該 note `embedded_status` 翻回 `false`，使其不再被重複挑出（消費 task01_v2 軟刪除訊號）。
- **BREAKING**：v2 使用的 collection（`obsidian_note_metadata`、`obsidian_vectors_v2`）與旗標欄位（`embedded_status`）皆與 v1（`obsidian_notes`、`obsidian_vectors_multimodal`、`embedding_done`）不同；dashboard 若要改讀 v2 向量需另議。

## Capabilities

### New Capabilities
- `obsidian-vector-embed-v2`：從 archived 層對 `obsidian_note_metadata` 做增量多模態 embedding——gate（`status=archived AND embedded_status=false`）、chunk archived md、embed archived 圖片、先刪後插寫入 `obsidian_vectors_v2`、以 `archived_md_md5_hash` 守衛的 CAS 翻 `embedded_status=true`。
- `obsidian-vector-purge`：消費 task01_v2 軟刪除訊號——挑 `status=deleted AND embedded_status=true`、`delete_many` 清 `obsidian_vectors_v2` 對應向量、翻 `embedded_status=false`，冪等且不重複挑出。

### Modified Capabilities
- （無：`openspec/specs/` 內無既有 task06 spec，皆為新增。）

## Impact

- **新增程式**：`task06_obsidian_embed_etl_v2/`（`e_*`、`t_*`、`l_*`、`main.py`）；chunking/embedding 邏輯可 copy/沿用現行 `task06_obsidian_embed_etl`。
- **MongoDB**：新增 `obsidian_vectors_v2` collection 與其 Atlas Vector Search index（1536 維、cosine）；讀寫 `obsidian_note_metadata.embedded_status`（task01_v2 已初始化為 false）。
- **GCS**：讀 `archived-notes/` 下的 md 與 `_attachment/` 圖片（task01_v2 已歸檔）。
- **上游依賴**：依賴 task01_v2 的 `obsidian_note_metadata` schema 與軟刪除契約；task01_v2 需先落地並產出 archived 資料。
- **不影響**：現行 `task06_obsidian_embed_etl`、`obsidian_notes`、`obsidian_vectors_multimodal`、dashboard。
