## ADDED Requirements

### Requirement: Embedding gate 讀 onenote_note_metadata 挑待向量化版本

系統 SHALL 從 MongoDB collection `onenote_note_metadata` 挑出 `status="archived"` 且 `embedded_status=false` 的版本作為待 embedding 清單；`status` 非 archived 或 `embedded_status=true` 者 MUST NOT 被納入。gate SHALL 只依 DB 狀態判斷，不重掃 GCS，並投影 `page_id`、`dt`、`archived_md_path`、`md_md5_hash`、`md_frontmatter`、`page_title`、`attached_images`。

#### Scenario: 只挑已歸檔且未向量化者

- **WHEN** 一版本 `status="archived"` 且 `embedded_status=false`
- **THEN** 該版本被納入待 embedding 清單

#### Scenario: 已向量化或未歸檔者略過

- **WHEN** 一版本 `embedded_status=true`，或 `status` 為 `review_closed`/`bronze_stored`/`pending_review`
- **THEN** 該版本不被納入待 embedding 清單

### Requirement: 從 archived 層取內容與圖片做多模態 embedding

系統 SHALL 依 `archived_md_path` 從 `onenote-vaults/archived-notes/` 下載歸檔 md 內文做 chunking，並在多模態 embedding 時以 `attached_images[].archived_image_path`（archived 副本、bucket `onenote-vaults`）作為圖片來源，MUST NOT 使用 raw-notes 或 processed-notes 的檔。chunk 內圖片以標準 markdown `![](_images/<檔名>)` 語法辨識、以 basename 對上 `archived_image_path`；對不上者 SHALL 記 warning 後略過。embedding SHALL 沿用 Vertex AI `gemini-embedding-2`（`output_dimensionality=1536`、輸出後 L2 normalize）。

#### Scenario: 以 archived md 與 archived 圖片產生向量

- **WHEN** 一版本進入 embedding，其 chunk 內含 `![](_images/a.png)` 且 `a.png` 落在 `attached_images[].archived_image_path`
- **THEN** chunk 來源為 `archived_md_path` 的內文，圖片來源為對應 `archived_image_path`，產出 1536 維、已 L2 normalize 的向量

#### Scenario: 連結對不上歸檔圖片則略過

- **WHEN** chunk 內 `![](_images/typo.png)` 的 basename 不落在任何 `archived_image_path`
- **THEN** 該圖不送入模型、記 warning，chunk 文字仍照常 embedding

### Requirement: 向量寫入共用 note_vectors_multimodal，以 archived 路徑作為 data lineage 依據

系統 SHALL 將 chunk 向量寫入既有 collection `note_vectors_multimodal`（與 task01/task06 共用），每筆 = 一個 chunk。向量 doc 中作為 data lineage 依據的欄位 SHALL 命名 `md_path`，其值 SHALL 為該版本的 `archived_md_path`（archived md 的完整 gs:// URI）；圖片欄 `image_paths` SHALL 為該 chunk 對應的 `archived_image_path` 清單。系統 MUST NOT 以 raw-notes/processed-notes/html 路徑作為該欄的值，且 MUST NOT 另設 source 判別欄（`archived_md_path` 跨 bucket 全域唯一）。對本次處理的每份筆記，系統 SHALL **先 `delete_many({md_path})` 再 `insert_many`**。

#### Scenario: md_path 存 archived md 路徑

- **WHEN** 一版本 `archived_md_path="gs://onenote-vaults/archived-notes/.../n.md"` 完成 embedding
- **THEN** 其每個 chunk doc 的 `md_path` 為該 archived md 路徑，`image_paths` 為 archived 圖片路徑

#### Scenario: 先刪後插避免孤兒 chunk

- **WHEN** 一份先前已向量化、內容重歸檔後 chunk 數變少的筆記再次 embedding
- **THEN** 該 `md_path` 的舊 chunk 全被刪除、僅存本次新插入的 chunk，無殘留

### Requirement: 以 md_md5_hash 守衛的 CAS 翻 embedded_status

系統 SHALL 在該版本 chunk 寫入成功後，以 Compare-And-Swap 翻 `onenote_note_metadata.embedded_status=true`：以 `archived_md_path` 唯一定位該版本（等同 `page_id`+`dt`），**只有** DB 該版本仍 `embedded_status=false` 且 `md_md5_hash` 等於本次 embedding 的版本才翻，並蓋上 `embedded_at`（UTC）。CAS 未命中時 MUST NOT 翻旗標（代表 embedding 期間又重歸檔）。

#### Scenario: 版本一致才翻旗標

- **WHEN** 寫入 chunk 後，DB 該版本 `embedded_status=false` 且 `md_md5_hash` 與本次相同
- **THEN** `embedded_status` 翻 `true` 並蓋 `embedded_at`

#### Scenario: 版本已變則不翻

- **WHEN** embedding 期間該筆記又重歸檔（`md_md5_hash` 不同）
- **THEN** CAS 未命中、`embedded_status` 維持 `false`，待下輪重 embedding

### Requirement: 不含軟刪除 purge

task08 `main` SHALL 只執行 embedding（gate → chunk+embed → 先刪後插 + CAS），MUST NOT 包含 purge 端。OneNote 版本以 `review_closed` 退役、無 `status=deleted` 軟刪除語意，故不對應 task06_v2 的 purge。

#### Scenario: 執行只做 embedding

- **WHEN** task08 `main` 執行
- **THEN** 只跑 embedding 流程，不查 `status=deleted`、不刪任何既有向量作為 purge
