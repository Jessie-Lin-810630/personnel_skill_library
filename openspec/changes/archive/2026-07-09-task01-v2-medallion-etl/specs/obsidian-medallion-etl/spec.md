## ADDED Requirements

### Requirement: Bronze 層以 rsync 覆蓋同步並保留版本

系統 SHALL 由本機透過 `gcloud storage rsync` 將 Obsidian vault 覆蓋式同步到 `gs://personal-vaults/raw-notes/<note_user_id>/<notebook>/<section>/` 作為 Bronze 原始層；bucket SHALL 啟用 GCS Object Versioning 以保留被覆蓋/刪除的歷史版本，且 MUST NOT 使用 `dt=` 分區。Bronze 階段 MUST NOT 呼叫任何 LLM 或執行清洗。

#### Scenario: 覆蓋同步既有筆記

- **WHEN** 本機一份既有 `.md` 內容變更後執行 rsync
- **THEN** `raw-notes/` 對應 blob 被新內容覆蓋，且舊版本以 noncurrent version 保留在同一路徑

#### Scenario: Bronze 不做清洗與 LLM

- **WHEN** Bronze 同步完成
- **THEN** `raw-notes/` 下的 `.md` 與圖片為原始未清洗內容，過程中未產生任何 LLM 呼叫紀錄

### Requirement: Silver 層以 md5 做 CDC gate，只下載變更檔

系統 SHALL 以 `list_blobs` 取得 `raw-notes/` 下每份 `.md` 的 `md5_hash`（不下載內容），並與 `obsidian_note_metadata` 現況比對：DB 無對應 `raw_md_path`（新增）或 `raw_md_md5_hash` 不同（變更）者才納入待清洗清單。系統 SHALL 僅對待清洗清單內的 `.md` 執行 `download_as_text()`；未變更的 `.md` MUST NOT 被下載內文。

#### Scenario: 未變更筆記略過下載

- **WHEN** 某 `.md` 的 GCS `md5_hash` 與 `obsidian_note_metadata` 既有 `raw_md_md5_hash` 相同
- **THEN** 該檔不被下載內文、不進入清洗流程，其 metadata 不被異動

#### Scenario: 新增或變更筆記納入清洗

- **WHEN** 某 `.md` 在 DB 無對應 `raw_md_path`，或其 `md5_hash` 與既有值不同
- **THEN** 該檔被 `download_as_text()` 下載並進入清洗流程

### Requirement: Silver 層清洗沿用既有規則並解析圖片血緣

系統 SHALL 對每份待清洗 `.md` 沿用現行 task01 的清洗規則推導 `note_type`、`topic`、`date`、`word_count`，缺 frontmatter 時以正文頂端 key:value 補救；並解析 `![[ ]]` 圖片嵌入，依「該筆記所在目錄下的 `_attachment/`」規則推算每張圖的 raw GCS 路徑與 md5，組成 attachment 血緣。清洗與 LLM enrichment 之間 SHALL 預留掛載順序（本次不實作 LLM、不新增 `processed-notes/` 關卡）。

#### Scenario: 推導筆記 metadata

- **WHEN** 一份含 frontmatter `type`/`tags`/`date` 的筆記進入清洗
- **THEN** 產出 `note_type`（frontmatter 優先、fallback 資料夾前綴）、`topic`（tags/檔名比對關鍵字）、`date`、`word_count`（不含 frontmatter）

#### Scenario: 解析圖片血緣

- **WHEN** 筆記正文含 `![[diagram.png]]` 且該圖存在於同目錄 `_attachment/`
- **THEN** attachment 血緣含該圖的 raw GCS 路徑與其 `md5_hash`；GCS 上不存在的圖片略過並記 warning

### Requirement: Silver 層歸檔到 archived-notes 並複製引用圖片

系統 SHALL 將清洗後的 `.md` 以 `copy_blob` 寫入 `gs://personal-vaults/archived-notes/<與 raw-notes 相同的後段路徑>`，並將該筆記引用且存在的圖片複製到對應 `archived-notes/.../_attachment/`。歸檔 SHALL 冪等：重跑同一版本不產生重複或殘留。

#### Scenario: 歸檔筆記與其圖片

- **WHEN** 一份變更筆記完成清洗
- **THEN** 清洗後 `.md` 出現在 `archived-notes/` 對應路徑，其引用圖片一併出現在對應 `_attachment/`，並記錄 archived 端的 path 與 md5

#### Scenario: 重跑歸檔冪等

- **WHEN** 對同一版本筆記重複執行 Silver
- **THEN** `archived-notes/` 結果與單次執行一致，無重複寫入殘留

### Requirement: 筆記 metadata 以單表內嵌 upsert 到 obsidian_note_metadata

系統 SHALL 將每份筆記寫入 MongoDB collection `obsidian_note_metadata`，**以 `raw_md_path` 為唯一鍵做 upsert**（冪等）。attachment 血緣 SHALL 以 `attached_images` 陣列內嵌於同一 note 文件，每個 entry 含 raw 與 archived 兩組 path/md5；系統 MUST NOT 另建 `obsidian_attachment_metadata` collection，MUST NOT 使用 `_id` 參考陣列。文件 SHALL 含 `status`（歸檔完成為 `archived`）與 `embedded_status`（初始 `false`，由 task06 翻轉）。

#### Scenario: 新增筆記 upsert

- **WHEN** 一份 DB 無對應 `raw_md_path` 的筆記完成歸檔
- **THEN** `obsidian_note_metadata` 新增一筆，含 raw/archived 的 path 與 md5、內嵌 `attached_images`、`status="archived"`、`embedded_status=false`

#### Scenario: 變更筆記重跑冪等

- **WHEN** 同一 `raw_md_path` 的筆記再次歸檔
- **THEN** 既有文件被 upsert 覆蓋更新，不產生重複文件

### Requirement: Gold 層每日快照追蹤清洗與向量化進度

系統 SHALL 對 `obsidian_note_metadata` 現況彙總，寫入 MongoDB collection `notes_summary`，**以 `snapshot_date`（當日只記一次、不含時分秒）為唯一鍵做 upsert**。快照 SHALL 至少含依 `note_type`/`topic` 的計數、總筆數，以及已向量化筆數（`embedded_status=true` 計數）。

#### Scenario: 產生當日快照

- **WHEN** Gold 階段執行
- **THEN** `notes_summary` 對當日 `snapshot_date` upsert 一筆，含 by_type/by_topic 計數、total_notes、embedded_notes

#### Scenario: 同日重跑覆蓋

- **WHEN** 同一日再次執行 Gold
- **THEN** 當日快照被覆蓋為最新值，不新增第二筆
