## 1. 前置：骨架與 copy

- [x] 1.1 建立 `task08_onenote_embed_etl/` 與 `__init__.py`、`e_*.py`、`t_*.py`、`l_*.py`、`main.py` 骨架，補符合規範的 module docstring
- [x] 1.2 從 `task06_obsidian_embed_etl_v2` copy chunking（`_chunk_markdown`）、`gemini-embedding-2` 呼叫、`_normalize`、`title: {title} | text: {content}` prompt、`_get_genai_client` 等 embedding 邏輯

## 2. Extract：gate 讀 onenote_note_metadata

- [x] 2.1 `e_scan_metadata`：查 `onenote_note_metadata` 挑 `status="archived"` 且 `embedded_status=false`，投影 `page_id`/`dt`/`archived_md_path`/`md_md5_hash`/`md_frontmatter`/`page_title`/`attached_images`
- [x] 2.2 `e_scan_metadata`：依 `archived_md_path` 從 `onenote-vaults/archived-notes/` 下載歸檔 md 內文（去 frontmatter 取 body）
- [x] 2.3 unittest：gate 過濾條件與投影欄位正確

## 3. Transform：chunk 與多模態 embedding（OneNote markdown 圖片）

- [x] 3.1 `t_chunk_embed`：對 archived md 內文做 chunking（copy task06_v2 header + recursive 切法）
- [x] 3.2 `t_chunk_embed`：圖片解析改抓標準 markdown `![](_images/<檔名>)`，以 basename 對上 `attached_images[].archived_image_path`；對不上記 warning 略過
- [x] 3.3 `t_chunk_embed`：每 chunk 多模態 embedding（`Part.from_uri` 送 archived 圖片 gs:// URI），產 1536 維並 L2 normalize
- [x] 3.4 `t_chunk_embed`：組向量 doc，血緣欄 `md_path`=`archived_md_path`、`image_paths`=archived 圖片、`file_name`=`page_title`、`tags`/`note_type`/`date` 取自 `md_frontmatter`
- [x] 3.5 unittest：chunk doc 帶 `md_path`（archived 路徑）、圖片來源為 archived 路徑、markdown `![]()` 語法解析正確（mock embedding 呼叫）

## 4. Load：寫 note_vectors_multimodal + CAS 翻旗標

- [x] 4.1 `l_load_to_mongodb`：對每份筆記先 `delete_many({md_path})` 再 `insert_many` 寫入 `note_vectors_multimodal`（先刪後插、冪等）
- [x] 4.2 `l_load_to_mongodb`：以 `md_md5_hash` 守衛的 CAS 翻 `onenote_note_metadata.embedded_status=true` 並蓋 `embedded_at`（條件 `{archived_md_path, embedded_status:false, md_md5_hash:本次版本}`，`archived_md_path` 唯一定位版本）
- [x] 4.3 unittest：先刪後插冪等、CAS 命中翻旗標、CAS 未命中（md5 已變／切塊為空只刪不插）不翻

## 5. 串接與收尾

- [x] 5.1 `main.py`：串 E→T→L（gate → chunk+embed → 先刪後插+CAS），補 loguru 日誌與 env 檢查；不含 purge
- [ ] 5.2 端到端本地實跑核對 `note_vectors_multimodal` 新增 `md_path` 血緣的 chunk 與 `embedded_status`（需真實 GCS/Mongo/Vertex，待 `task07-c3-schema-align` live）
- [x] 5.3 `poetry run python -m unittest discover -s tests` 全綠
- [x] 5.4 CLAUDE.md 的 ETL 表新增 task08 一列（來源 `onenote-vaults/archived-notes/`、目的地 `note_vectors_multimodal`）
- [ ] 5.5 （跨分支待辦，非本 change）由另一分支把 task06_v2 的 `raw_md_path`→`md_path`、值改存 archived 路徑，收斂 `note_vectors_multimodal` 血緣欄；同步通知 RAG（feature/dashboard-ui）過渡期兩欄並存
