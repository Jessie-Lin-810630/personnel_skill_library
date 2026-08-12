## Why

task07 lazy_loading 已把人工核可的 OneNote 筆記歸檔到 GCS `onenote-vaults/archived-notes/` 並在 `onenote_note_metadata`（C3）留下 `status=archived`、`embedded_status`、`archived_md_path`、`attached_images[].archived_image_path` 等血緣，但沒有向量化消費端。目標是讓「OneNote 經 task07 歸檔的筆記」與「Obsidian 經 task01_v2 歸檔的筆記」兩種來源，向量化後寫入**同一份** collection `note_vectors_multimodal`，供同一條 RAG 檢索使用。

task06_v2 是為 task01/Obsidian 量身打造的：讀 `obsidian_note_metadata`、bucket 寫死 `personal-vaults`、以 `raw_md_path` 為 join 鍵、圖片走 Obsidian wiki-link `![[x.png]]` + `_attachment/`、且含 Obsidian 專屬的軟刪除 purge。OneNote 側與之結構性不同：collection 為 `onenote_note_metadata`、bucket 為 `onenote-vaults`、無 raw md（join 鍵改用歸檔路徑）、圖片走標準 markdown `![](_images/x.png)` + `_images/`、且無軟刪除。把 task06_v2 參數化成雙來源會塞入大量分支、破壞 v1/v2 各自演化的隔離。因此改開獨立的 task08，chunk/embed/normalize 邏輯 copy 自 task06_v2，僅替換 ingestion 與圖片解析，寫入同一張向量表。task06_v2 本分支完全不動。

## What Changes

- 新增 `task08_onenote_embed_etl/`（`e_*`、`t_*`、`l_*`、`main.py`），與 task06_v2 並存；task06_v2 不動。
- **Embedding gate 讀 `onenote_note_metadata`**：挑 `status="archived"` 且 `embedded_status=false` 的版本，投影 `page_id`/`dt`/`archived_md_path`/`md_md5_hash`/`md_frontmatter`/`page_title`/`attached_images`。
- **內容與圖片走 archived 層（人工核可後）**：依 `archived_md_path` 從 `archived-notes/` 下載 md 內文 chunking；圖片解析改對應 OneNote 的 markdown `![](_images/<檔名>)` 語法與同層 `_images/` 目錄，來源用 `attached_images[].archived_image_path`（gs:// URI，bucket `onenote-vaults`）。沿用 Vertex AI `gemini-embedding-2`（1536 維、L2 normalize）。
- **寫入同一張 `note_vectors_multimodal`**：向量 doc 以 `md_path`（存 `archived_md_path` 的值）作為 data lineage 依據、圖片欄位 `image_paths`（存 archived image 路徑）。`archived_md_path`（完整 gs:// URI，跨 `onenote-vaults`/`personal-vaults` bucket 天然唯一）即 vectors 與兩張 metadata 的 join 鍵，**不另設 source 判別欄**。per-note 先 `delete_many({md_path})` 再 `insert_many`。
- **CAS 翻旗標**：以 `md_md5_hash`（archived md 指紋，與 silver md byte 相同）為守衛，只有該版本仍 `embedded_status=false` 且 `md_md5_hash` 未變才把 `onenote_note_metadata.embedded_status` 翻 `true`＋蓋 `embedded_at`。
- **不含 purge**：OneNote 無軟刪除（版本以 `review_closed` 退役、非 `deleted`），task08 不實作 purge 端。

## Capabilities

### New Capabilities
- `onenote-vector-embed`：從 `onenote-vaults/archived-notes/` 對 `onenote_note_metadata` 做增量多模態 embedding——gate（`status=archived AND embedded_status=false`）、chunk archived md、以 markdown `![]()`+`_images/` 解析 archived 圖片、寫入共用 `note_vectors_multimodal`（以 `md_path`=`archived_md_path` 作為 data lineage 依據）、以 `md_md5_hash` 守衛的 CAS 翻 `embedded_status`。

## Impact

- **新增程式**：`task08_onenote_embed_etl/`（`e_*`/`t_*`/`l_*`/`main.py`）；chunking/embedding/normalize 由 task06_v2 copy。
- **MongoDB**：讀寫 `onenote_note_metadata.embedded_status`；寫入既有 `note_vectors_multimodal`（與 task01/task06 共用，同一 Atlas Vector Search index）。
- **GCS**：讀 `onenote-vaults/archived-notes/` 的 md 與 `_images/` 圖片。
- **上游依賴**：依賴 task07 C3 schema 對齊（change `task07-c3-schema-align`）先落地，才有 `archived_md_path`/`attached_images[].archived_image_path`/`md_md5_hash`。
- **不影響**：task06_v2、`obsidian_note_metadata`、task07 三服務。
- **跨分支待辦（不在本 change）**：`note_vectors_multimodal` 目前 task06_v2 寫 `raw_md_path`、task08 寫 `md_path`，欄位名暫時並存；task06_v2 的 `raw_md_path`→`md_path` 改名與「改存 archived 路徑值」由**另一分支**處理，本分支不碰 task06_v2。RAG 檢索端（feature/dashboard-ui）需知悉過渡期兩欄位並存。
