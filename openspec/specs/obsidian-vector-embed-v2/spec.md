# obsidian-vector-embed-v2 Specification

## Purpose
TBD - created by archiving change task06-v2-embed-purge. Update Purpose after archive.
## Requirements

### Requirement: Embedding gate 讀 obsidian_note_metadata 挑待向量化筆記

系統 SHALL 從 MongoDB collection `obsidian_note_metadata` 挑出 `status="archived"` 且 `embedded_status=false` 的筆記作為待 embedding 清單；`status` 非 archived（含 deleted / error / null）或 `embedded_status=true` 者 MUST NOT 被納入。gate SHALL 只依 DB 狀態判斷，不重掃 GCS。

#### Scenario: 只挑已歸檔且未向量化者

- **WHEN** 一筆記 `status="archived"` 且 `embedded_status=false`
- **THEN** 該筆記被納入待 embedding 清單

#### Scenario: 已向量化或未歸檔者略過

- **WHEN** 一筆記 `embedded_status=true`，或 `status` 為 `deleted`/`error`/`null`
- **THEN** 該筆記不被納入待 embedding 清單

### Requirement: 從 archived 層取內容與圖片做多模態 embedding

系統 SHALL 依 `archived_md_path` 從 `archived-notes/` 下載清洗後 md 內文做 chunking，並在多模態 embedding 時以 `attached_images[].archived_image_path`（archived 副本）作為圖片來源，MUST NOT 使用 raw-notes 的原始檔。embedding SHALL 沿用 Vertex AI `gemini-embedding-2`（`output_dimensionality=1536`、輸出後 L2 normalize）。

#### Scenario: 以 archived md 與 archived 圖片產生向量

- **WHEN** 一筆記進入 embedding
- **THEN** chunk 來源為 `archived_md_path` 的內文，圖片來源為其 `archived_image_path`，產出 1536 維、已 L2 normalize 的向量

### Requirement: 向量寫入 v2 專用 collection 並 per-note 先刪後插

系統 SHALL 將 chunk 向量寫入 MongoDB collection `note_vectors_multimodal`（與 v1 `obsidian_vectors_multimodal` 隔離），每筆 = 一個 chunk，且帶 `raw_md_path` 作為 note 的 join 鍵。對本次處理的每份筆記，系統 SHALL **先 `delete_many({raw_md_path})` 再 `insert_many`**，確保重切後 chunk 數變動不留孤兒、且重跑冪等。

#### Scenario: 先刪後插避免孤兒 chunk

- **WHEN** 一份先前已向量化、內容重切後 chunk 數變少的筆記再次 embedding
- **THEN** 該 `raw_md_path` 的舊 chunk 全被刪除、僅存本次新插入的 chunk，無殘留

#### Scenario: v2 向量與 v1 隔離

- **WHEN** v2 embedding 寫入完成
- **THEN** 向量落在 `note_vectors_multimodal`，`obsidian_vectors_multimodal`（v1）不受影響

### Requirement: 以 archived_md_md5_hash 守衛的 CAS 翻 embedded_status

系統 SHALL 在該筆記 chunk 寫入成功後，以 Compare-And-Swap 翻 `obsidian_note_metadata.embedded_status=true`：**只有** DB 該筆記仍 `embedded_status=false` 且 `archived_md_md5_hash` 等於本次 embedding 的版本才翻，並蓋上 `embedded_at`（UTC）。CAS 未命中時 MUST NOT 翻旗標（代表 embedding 期間版本又更新）。

#### Scenario: 版本一致才翻旗標

- **WHEN** 寫入 chunk 後，DB 該筆記 `embedded_status=false` 且 `archived_md_md5_hash` 與本次相同
- **THEN** `embedded_status` 翻 `true` 並蓋 `embedded_at`

#### Scenario: 版本已變則不翻

- **WHEN** embedding 期間該筆記已被重歸檔（`archived_md_md5_hash` 不同）
- **THEN** CAS 未命中、`embedded_status` 維持 `false`，待下輪重 embedding
