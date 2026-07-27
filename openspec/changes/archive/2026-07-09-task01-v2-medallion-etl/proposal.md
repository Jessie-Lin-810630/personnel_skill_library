## Why

現行 task01 每次執行都對 GCS 上**全部** `.md` 做 `download_as_text()` 全量下載內文（CDC 只省 Mongo 寫入與 task06 embedding，未省下載），穩態下多數筆記靜態未變，白燒下載 I/O；且清洗後的筆記與原始筆記混在同一份 blob，未來若要在清洗前插入 document enrichment（LLM）沒有隔離區，半熟產物會直接污染 task06 的向量檢索來源。task01_v2 以 medallion 分層（Bronze/Silver/Gold）重整流程：CDC 先 gate 才下載、清洗後另存 archived 隔離區，並為未來 silver enrichment 預留掛載點。

## What Changes

- 新增 task01 的 medallion 變體（新資料夾，暫名 `task01_obsidian_etl_v2`），與現行 `task01_obsidian_etl` 並存，供對照兩種設計表現；現行 task01 不動。
- **Bronze**：由本機 `gcloud storage rsync` 覆蓋式同步到 `gs://personal-vaults/raw-notes/...`；不做 `dt=` 分區，改開啟 **GCS Object Versioning** 保留歷史版本（刻意與 task07 的 `dt=` 分區做設計對照）。
- **Silver**：以 GCS blob `md5_hash` 為 CDC 訊號，先查 `obsidian_note_metadata` 過濾出新增/變更的 `.md`，**只對變更的檔 `download_as_text()`**（取代現行全量下載）；沿用現行五個清洗函式（`_infer_note_type` / `_infer_topic` / `_infer_date` / `_infer_misposition_metadata` / `extract_attached_images`），清洗後 copy `.md` 與其引用圖片到 `gs://.../archived-notes/...`，並 upsert metadata。
- **Silver enrichment endpoint 僅預留掛載點**：本次不實作 LLM enrich、不新增 `processed-notes/` 關卡；清洗後直接進 `archived-notes/`。
- **軟刪除**：raw-notes 某 `.md` 從 live listing 消失（rsync 刪除）但 DB 尚存時，將該 note metadata 標 `status="deleted"`、保留 archived 副本供稽核，並提供 task06 一個 purge 對應向量的訊號。
- **資料模型改用單表內嵌**：attachment 血緣內嵌於 `obsidian_note_metadata.attached_images`（每個 entry 帶 raw + archived 兩組 path/md5），**不建** `obsidian_attachment_metadata` collection、**不用** `_id` 參考陣列。
- **Gold**：對 `obsidian_note_metadata` 做每日快照 `notes_summary`，追蹤清洗與向量化進度。
- **task06 合約調整**：task06 改讀 `obsidian_note_metadata` 的 CDC/軟刪除狀態做 gate 與向量清理（**BREAKING**：collection 名稱與 schema 與現行 `obsidian_notes` 不同；本次僅定義合約，task06 實作可另立 change）。

## Capabilities

### New Capabilities
- `obsidian-medallion-etl`：Bronze/Silver/Gold 分層的 Obsidian ETL。涵蓋 md5 CDC gate（只下載變更檔）、沿用既有清洗規則、清洗後歸檔到 archived-notes、單表內嵌 attachment 血緣的 upsert，以及 Gold 每日快照。
- `obsidian-note-soft-delete`：raw-notes 筆記被刪除時的軟刪除狀態機——標記 `status="deleted"`、保留 archived 稽核副本，並對下游（task06）曝露一致的「此版本需 purge 向量」訊號。

### Modified Capabilities
- （無：`openspec/specs/` 內無既有 task01 spec，皆為新增。）

## Impact

- **新增程式**：`task01_obsidian_etl_v2/`（`e_*`、`t_*`、`l_*`、`main.py`），可 copy/沿用現行 `task01_obsidian_etl` 的清洗與圖片解析函式。
- **GCS**：`personal-vaults` bucket 新增 `raw-notes/`、`archived-notes/` 前綴並開啟 Object Versioning；儲存量約翻倍（raw + archived 各一份，`.md`/`.png` 小檔成本可忽略）。
- **MongoDB**：新增 `obsidian_note_metadata`、`notes_summary` collections（與現行 `obsidian_notes`/`obsidian_summary` 並存，不覆蓋）。
- **下游依賴**：task06 需改對 `obsidian_note_metadata` 做 gate 與向量 purge（本 change 僅定義合約，實作另議）。
- **文件**：`doc/work_log.md`（20260707 段落）的 `obsidian_attachment_metadata` schema 需標記作廢、改為內嵌版；`CLAUDE.md` 與 `branch_etl_pipeline_summary.md` 待實作落地後補。
- **不影響**：現行 `task01_obsidian_etl`、dashboard、其餘 task。
