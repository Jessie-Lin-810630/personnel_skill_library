## 1. 前置：GCS 與骨架

- [x] 1.1 對 `personal-vaults` bucket 開啟 Object Versioning，確認 `raw-notes/`、`archived-notes/` 前綴可寫
- [x] 1.2 建立 `task01_obsidian_etl_v2/` 資料夾與 `__init__.py`、`e_*.py`、`t_*.py`、`l_*.py`、`main.py` 空骨架
- [x] 1.3 從現行 task01 copy 清洗與圖片解析函式（`_infer_note_type`/`_infer_topic`/`_infer_date`/`_infer_misposition_metadata`/`resolve_image_blob_path`/`extract_attached_images`）到 v2，並補齊符合規範的 module docstring

## 2. Bronze：rsync 同步（文件化）

- [x] 2.1 於 README 或 main docstring 記錄 Bronze rsync 指令（本機 → `gs://personal-vaults/raw-notes/<user>/<notebook>/<section>/`），標明 Bronze 不清洗、不呼叫 LLM
- [x] 2.2 確認 rsync 覆蓋後 noncurrent 版本有被 Object Versioning 保留（手動驗一次）

## 3. Silver Extract：CDC gate（只下載變更檔）

- [x] 3.1 `e_*`：`list_blobs("personal-vaults")` 掃 `raw-notes/` 下 `.md` 與 `_attachment/` 圖片，取 `md5_hash`；`.md` 的 key 統一拼成含 `gs://` 前綴的 `raw_md_path`
- [x] 3.2 `e_*`：單次查詢 `obsidian_note_metadata` 撈回 `{raw_md_path: raw_md_md5_hash}` 映射（`get_existing_md5_map`；屬 ingestion 輔助讀取、不寫入，故歸 `e_` 而非 `l_`）
- [x] 3.3 `e_*`／`main`：記憶體比對出「新增（DB 無）／變更（md5 異）」待清洗清單，未變更檔不下載
- [x] 3.4 僅對待清洗清單 `download_as_text()` 取內文
- [x] 3.5 unittest：驗證 `raw_md_path` 前綴拼接與 CDC 比對（未變更→略過、md5 異→納入、DB 無→納入）

## 4. Silver Transform：清洗與圖片血緣

- [x] 4.1 `t_*`：對每份待清洗 `.md` 推導 `note_type`/`topic`/`date`/`word_count`（frontmatter 優先、缺則正文頂端補救）
- [x] 4.2 `t_*`：解析 `![[ ]]` 圖片，依「筆記所在目錄 `_attachment/`」規則算 raw GCS 路徑與 md5，組 `attached_images` 內嵌條目（raw 部分先填、archived 部分留待歸檔補）
- [x] 4.3 在清洗流程中以註解標出未來 LLM enrichment 的掛載順序點（本次不實作）
- [x] 4.4 unittest：清洗推導與圖片血緣解析（含 GCS 不存在圖片略過並 warning）

## 5. Silver Load：歸檔與 metadata upsert

- [x] 5.1 `l_*`：`copy_blob` 把清洗後 `.md` 覆蓋寫入 `archived-notes/<同後段路徑>`，取回 archived md5
- [x] 5.2 `l_*`：copy 該筆記引用且存在的圖片到對應 `archived-notes/.../_attachment/`，把 archived path/md5 回填各 `attached_images` 條目
- [x] 5.3 `l_*`：以 `raw_md_path` 為唯一鍵 upsert `obsidian_note_metadata`，寫入 raw/archived path+md5、內嵌 `attached_images`、`status="archived"`、`embedded_status=false`、時間戳
- [x] 5.4 unittest：歸檔冪等（重跑同版本無重複／殘留）與 upsert 冪等（同 `raw_md_path` 不生重複文件）

## 6. 軟刪除

- [x] 6.1 `l_*`：撈 DB 全部 `raw_md_path` 與本次 live listing 做差集，差集內文件 `status="deleted"`，保留文件與 archived 副本（不硬刪）
- [x] 6.2 確認 task06 可用 `status="deleted" AND embedded_status=true` 查出待 purge；於 spec/design 記錄此契約（task06 實作另 change）
- [x] 6.3 unittest：軟刪除偵測（被刪→deleted、仍存→不動、已 deleted 重跑冪等）

## 7. Gold：每日快照

- [x] 7.1 `l_*`：彙總 `obsidian_note_metadata`，以 `snapshot_date`（截到日）為唯一鍵 upsert `notes_summary`，含 by_type/by_topic/total_notes/embedded_notes
- [x] 7.2 unittest：同日重跑覆蓋為單筆

## 8. 串接與收尾

- [x] 8.1 `main.py`：串 E→T→L（CDC gate → 清洗 → 歸檔 upsert → 軟刪除 → Gold 快照），補 loguru 日誌與 env 檢查
- [x] 8.2 端到端本地實跑一次（新增／變更／刪除三情境）並核對 GCS 與 MongoDB 結果
- [x] 8.3 更新 `doc/work_log.md` 20260707 段落：標記 `obsidian_attachment_metadata` schema 作廢、改為單表內嵌版
- [x] 8.4 執行 `poetry run python -m unittest discover -s tests` 全綠

## 9. 錯誤處理與模組歸位（實作期追加）

- [x] 9.1 `l_*` `archive_note`：任一 `_copy_blob` 例外時寫 `note_doc["error_msg"]` 後 re-raise；成功時 `error_msg=""`
- [x] 9.2 `l_*` 新增 `mark_note_error`：失敗時以 `raw_md_path` 為鍵 upsert `status="error"`+`error_msg`（不動 archived_*，可冪等重跑）；`main` 的 except 呼叫它落地
- [x] 9.3 `l_*` `build_and_upsert_summary`：快照計數過濾改為只計 `status=="archived"`（排除 deleted / error，避免污染 total/by_type）
- [x] 9.4 模組歸位：`_infer_*`/`extract_attached_images`/`resolve_image_blob_path`/`TOPIC_KEYWORDS` 移到 `t_`；`get_existing_md5_map` 移到 `e_`；`FOLDER_TYPE_MAP` 留 `e_` 供 `t_` import
- [x] 9.5 更新 `CLAUDE.md` ETL 命名規則：前綴依「資料本體流向」歸類（附 `get_existing_md5_map` 範例）
- [x] 9.6 unittest：`archive_note` 例外寫 error_msg 並拋、`mark_note_error` upsert 行為、快照排除 error
