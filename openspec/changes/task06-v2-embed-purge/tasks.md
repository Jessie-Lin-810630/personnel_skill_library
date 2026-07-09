## 1. 前置：骨架

- [x] 1.1 建立 `task06_obsidian_embed_etl_v2/` 資料夾與 `__init__.py`、`e_*.py`、`t_*.py`、`l_*.py`、`main.py` 骨架，補符合規範的 module docstring
- [x] 1.2 從現行 `task06_obsidian_embed_etl` copy chunking / `gemini-embedding-2` 呼叫 / L2 normalize / `title: {title} | text: {content}` prompt 等 embedding 邏輯到 v2

## 2. Extract：gate 讀 obsidian_note_metadata

- [x] 2.1 `e_*`：查 `obsidian_note_metadata` 挑 `status="archived"` 且 `embedded_status=false` 的筆記，回傳含 `raw_md_path`/`archived_md_path`/`archived_md_md5_hash`/`attached_images`(archived 部分) 的待做清單
- [x] 2.2 `e_*`：依 `archived_md_path` 從 `archived-notes/` 下載清洗後 md 內文（`download_as_text`）
- [x] 2.3 unittest：gate 過濾（archived+false→挑、embedded_status=true 或 status≠archived→略過）

## 3. Transform：chunk 與多模態 embedding（archived 來源）

- [x] 3.1 `t_*`：對 archived md 內文做 chunking（沿用 v1 header + recursive 切法）
- [x] 3.2 `t_*`：多模態 embedding 以 `attached_images[].archived_image_path` 為圖片來源（`Part.from_uri`），產 1536 維向量並 L2 normalize
- [x] 3.3 `t_*`：組 chunk 向量 doc，帶 `raw_md_path` 血緣鍵、chunk 內文與 archived 圖片路徑
- [x] 3.4 unittest：chunk doc 帶 `raw_md_path`、圖片來源為 archived 路徑（mock embedding 呼叫）

## 4. Load：寫 note_vectors_multimodal + CAS 翻旗標

- [x] 4.1 `l_*`：對每份筆記先 `delete_many({raw_md_path})` 再 `insert_many` 寫入 `note_vectors_multimodal`（先刪後插、冪等）
- [x] 4.2 `l_*`：以 `archived_md_md5_hash` 守衛的 CAS 翻 `obsidian_note_metadata.embedded_status=true` 並蓋 `embedded_at`（條件 `{raw_md_path, embedded_status:false, archived_md_md5_hash:本次版本}`）
- [x] 4.3 unittest：先刪後插冪等（chunk 數變少無孤兒）、CAS 命中翻旗標、CAS 未命中（md5 已變）不翻

## 5. Purge：消費軟刪除訊號

- [x] 5.1 `l_*`：查 `status="deleted"` 且 `embedded_status=true` 的筆記，逐筆 `delete_many({raw_md_path})` 清 `note_vectors_multimodal`（不動 metadata 文件與 archived 副本）
- [x] 5.2 `l_*`：清完把該筆記 `embedded_status` 翻回 `false`（不再被重複挑出）
- [x] 5.3 unittest：被刪+已向量化→清向量並翻 false、已 purge（deleted+false）重跑冪等

## 6. 串接與收尾

- [x] 6.1 `main.py`：串 E→T→L（gate → chunk+embed → 先刪後插+CAS）＋ purge，補 loguru 日誌與 env 檢查
- [x] 6.2 於 Atlas Console 手動建 `note_vectors_multimodal` Vector Search index（1536 維、cosine）—手動步驟，需 task01_v2 先產出 archived 資料
- [x] 6.3 端到端本地實跑（embedding + 軟刪除後 purge）核對 `note_vectors_multimodal` 與 `embedded_status`—待 task01_v2 8.2 落地後
- [x] 6.4 執行 `poetry run python -m unittest discover -s tests` 全綠
