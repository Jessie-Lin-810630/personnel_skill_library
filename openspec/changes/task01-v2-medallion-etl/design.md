## Context

現行 `task01_obsidian_etl` 的 `scan_vault_gs()` 每次執行對全部目標 `.md` 做 `download_as_text()`（`e_scan_obsidian.py:249-263`），CDC（`sync_notes()`）只省 Mongo 寫入與 task06 embedding、未省 GCS 下載。清洗物與原始物共用同一份 blob，無隔離區，未來插入 LLM enrichment 會直接污染 task06 向量來源。

task01_v2 以 medallion 分層重整，並刻意與 task07 做設計對照：task07 用 `dt=` 分區保留多版本，task01_v2 改用 **GCS Object Versioning**，藉此比較兩種版本控制策略在 CDC 與運維上的表現差異。本次為單一 ETL job（非服務化），與現行 task01 並存不互相取代。

約束：Python >= 3.14、pyenv + Poetry、pathlib（不用 os.path）、MongoDB upsert 冪等、unittest（非 pytest）、機密走 .env / Secret Manager。

## Goals / Non-Goals

**Goals:**
- Silver 以 md5 CDC gate，**只下載變更的 `.md`**，取代現行全量下載
- 清洗後歸檔到 `archived-notes/` 隔離區，作為 task06 向量化的乾淨來源
- 單表內嵌 attachment 血緣（`obsidian_note_metadata.attached_images`），零跨表 join
- 軟刪除 + 對 task06 曝露一致的向量 purge 訊號
- 為未來 silver LLM enrichment 預留清洗順序掛載點

**Non-Goals:**
- 本次不實作 LLM enrichment、不建 `processed-notes/` 關卡、不做人工審查 UI
- 不改動現行 `task01_obsidian_etl`、task06、dashboard
- task06 對新 collection 的 gate/purge 實作屬另一 change，本次只定契約
- 不做 `dt=` 分區（刻意）

## Decisions

### D1：新資料夾並存，不改現行 task01
`task01_obsidian_etl_v2/`（`e_*`/`t_*`/`l_*`/`main.py`）與現行並存。清洗與圖片解析函式（`_infer_note_type`/`_infer_topic`/`_infer_date`/`_infer_misposition_metadata`/`resolve_image_blob_path`/`extract_attached_images`）**copy 而非 import**，沿用 task06 既有的「copy 決策」慣例，讓 v1/v2 可獨立演化以做對照。
- 替代方案：抽共用模組供 v1/v2 import → 否決，會耦合兩個要對照的設計，且違反「對照實驗獨立性」。

### D2：CDC gate 用單次 `$or` 查詢，不逐檔查
`list_blobs` 一次取全部 `raw-notes/` blob 的 `md5_hash`；對 Mongo 用單次查詢撈回既有 `{raw_md_path: raw_md_md5_hash}` 映射，在記憶體比對出「新增 / 變更」清單，只對清單內的檔 `download_as_text()`。
- 替代方案：逐檔查 DB → 否決，N 次 round trip。
- 內嵌 attachment 讓此處無 N+1（不需再查 attachment `_id`）。

### D3：attachment 單表內嵌，每 entry 帶 raw + archived 兩組 path/md5
沿用 v1 的 `attached_images` 內嵌結構，擴充為 `{raw_image_path, raw_image_md5, archived_image_path, archived_image_md5}`。因 `resolve_image_blob_path()` 規則把 `_attachment/` 放在**每份筆記自己的目錄底下**，圖片天然不跨筆記共用，正規化的去重/反查效益低，故不建獨立 collection。
- 替代方案：獨立 `obsidian_attachment_metadata` + `_id` 參考（work log 初版）→ 否決，帶來 join、N+1、跨表一致性成本，效益不成比例。

### D4：歸檔冪等靠 md5 + copy_blob 覆蓋
筆記 md5 一變，就 `copy_blob` 覆蓋歸檔 `.md` 與其引用圖片到 `archived-notes/.../_attachment/`；archived 端 md5 寫回該筆記的 `attached_images` entry。未變更筆記不觸發 copy。重跑同版本因 copy 為覆蓋語意，結果冪等。
- 圖片是否已歸檔的判斷內含在「筆記 md5 是否變」內：筆記沒變就不重 copy 圖；筆記變則連圖一起重 copy（成本只跟變更成正比）。

### D5：軟刪除 = live listing 差集
Silver 撈回 DB 全部 `raw_md_path` 集合，與本次 `raw-notes/` live listing 的路徑集合做差集；差集內（DB 有、GCS 無）者 `status="deleted"`，保留文件與 archived 副本。task06 以 `status="deleted" AND embedded_status=true` 挑待 purge，清完翻 `embedded_status=false`。
- 替代方案：硬刪（v1 `delete_many`）→ 否決，無稽核痕跡且與 Object Versioning 的「可回溯」精神不符。

### D6：upsert 鍵
`obsidian_note_metadata` 以 `raw_md_path` 為唯一鍵；`notes_summary` 以 `snapshot_date`（截到日）為唯一鍵。與現行 v1 的 `file_path`/`snapshot_date` 對齊語意，但 `raw_md_path` 含 `gs://bucket/` 前綴——CDC 比對時 blob.name 需統一拼上前綴，避免一邊有一邊無。

## Risks / Trade-offs

- **[比對鍵前綴不一致]** `raw_md_path` 含 `gs://personal-vaults/`、`blob.name` 不含 → 比對永遠 miss、每檔誤判為新增而全量下載。**Mitigation**：在 Extract 統一拼 `gs://{bucket}/{blob.name}` 後才比對與寫入，加 unittest 驗證映射一致。
- **[GCS 儲存翻倍]** raw + archived 各一份，加上 Object Versioning 的 noncurrent 版本。**Mitigation**：`.md`/`.png` 小檔成本可忽略；必要時對 `raw-notes/` 舊版設 lifecycle rule 限制保留版本數。
- **[跨階段部分失敗]** copy 圖成功但 metadata upsert 失敗，或反之，留下不一致中間態。**Mitigation**：以 `status`（null→archived）標記推進、全流程冪等重跑收斂；先 copy blob 再 upsert metadata，重跑時 md5 未變會跳過已完成部分。
- **[task06 契約未落地]** 本 change 只定 purge 訊號欄位，task06 尚未實作 → 被刪筆記的向量暫不會被清。**Mitigation**：契約欄位先就位（`status`/`embedded_status`），task06 change 補實作；過渡期孤兒向量不影響 v1 既有 `obsidian_vectors`。
- **[清洗規則與 v1 漂移]** copy 函式後 v1/v2 各自演化可能不同步。**Mitigation**：這是刻意的對照設計；差異記在 work log，不視為 bug。

## Migration Plan

1. GCS：`personal-vaults` 開啟 Object Versioning，建 `raw-notes/`、`archived-notes/` 前綴。
2. 首次 rsync 把本機 vault 灌到 `raw-notes/`。
3. 首跑 Silver：DB 空 → 全部視為新增、全量下載並歸檔（一次性成本），之後穩態只跑增量。
4. 與 v1 並行觀察，比較兩者 I/O 與查詢量後再決定是否退役 v1。
5. Rollback：v2 完全獨立（新資料夾、新 collection、新 GCS 前綴），停跑即可，不影響 v1 與現有資料。

## Open Questions

- `notes_summary` 快照除既有欄位外，是否要納入 task06/task07 的跨 task 指標（work log 待辦）→ 可先落最小集合，日後擴充。
- Object Versioning 的 noncurrent 版本保留策略（永久 vs lifecycle 限制）→ 先不設限，觀察儲存量再定。
- task06 翻 `embedded_status=false` 作為 purge 完成訊號是否與「重新 embed」語意衝突（兩者都設 false）→ 留待 task06 change 釐清，可能需獨立 `vectors_purged` 旗標。
