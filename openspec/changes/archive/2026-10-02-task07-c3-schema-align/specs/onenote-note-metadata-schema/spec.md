## ADDED Requirements

### Requirement: 複合唯一鍵與 hash 欄位命名一致

`onenote_note_metadata` SHALL 以 `page_id`+`dt` 為複合唯一鍵 (Upsert key)，支援同頁多版本。html 變動判定 hash 欄位 SHALL 命名為 `html_sha_hash`（sha256 hexdigest），GCS html 物件指紋欄位 SHALL 命名為 `html_md5_hash`，silver md 物件指紋欄位 SHALL 命名為 `md_md5_hash`。`onenote_graph_api_logs` 與 `multimodal_llm_enrichment_logs` 寫入的 html sha256 欄位 SHALL 同樣命名為 `html_sha_hash`，跨 collection 命名一致。系統 MUST NOT 再以 `html_hash`／`html_md5`／`md_md5` 作為寫入 MongoDB 的 document key。

#### Scenario: Bronze 寫入使用一致的 hash 欄位名

- **WHEN** Bronze 偵測到某頁 html 變動並 upsert `onenote_note_metadata`
- **THEN** 該版本 document 含 `html_sha_hash`、`html_md5_hash`，且不含 `html_hash`、`html_md5`

#### Scenario: 跨 collection hash 欄位名一致

- **WHEN** `onenote_graph_api_logs` 記一筆下載成功、`multimodal_llm_enrichment_logs` 記一筆 enrichment、`onenote_note_metadata` upsert 一版本
- **THEN** 三者表達 html sha256 的 document key 皆為 `html_sha_hash`

### Requirement: 圖片血緣以 attached_images Object 陣列表達

`onenote_note_metadata` SHALL 以單一 Array(Object) 欄位 `attached_images` 記錄每個版本引用的圖片血緣，MUST NOT 使用 `img_md5`／`img_path`／`img_archive_path` 平行陣列。每個 Object SHALL 含 `raw_image_path`、`raw_image_md5`（bronze 端），並於歸檔後補 `archived_image_path`、`archived_image_md5`（gold 端）。無引用圖片時 `attached_images` SHALL 為空陣列 `[]`。

#### Scenario: Bronze 寫入 raw 端圖片血緣

- **WHEN** Bronze 下載一頁含 2 張圖片並存入 raw-notes
- **THEN** 該版本 `attached_images` 為 2 個 Object，各含 `raw_image_path`、`raw_image_md5`，尚無 `archived_image_*`

#### Scenario: Gold 歸檔回填 archived 端圖片血緣

- **WHEN** 該版本被 approve 歸檔，圖片複製到 archived-notes
- **THEN** 每個 `attached_images` Object 被補上 `archived_image_path`、`archived_image_md5`

#### Scenario: 無圖片頁面

- **WHEN** 某頁不引用任何圖片
- **THEN** 該版本 `attached_images` 為 `[]`

### Requirement: topic 主題分類（Must）

`onenote_note_metadata` 每個版本 SHALL 有非空的 `topic`（字串）欄位，其值 SHALL 由 task01 相同的主題分類邏輯（`TOPIC_KEYWORDS` 關鍵字表按鍵順序優先匹配、全不中回 `other`）推導。Bronze 階段（尚無 LLM tags）SHALL 以 `page_title` 為比對來源寫入暫定 `topic`；Gold approve／reject 階段（已有 `md_frontmatter.tags`）MUST 以 tags＋title 重算並覆蓋 `topic`。

#### Scenario: Bronze 以標題初判 topic

- **WHEN** Bronze upsert 一個 `bronze_stored` 版本、尚無 tags
- **THEN** 該版本 `topic` 由 `page_title` 比對 `TOPIC_KEYWORDS` 得出（命中關鍵字則為對應 topic，否則 `other`），欄位非空

#### Scenario: Gold 以 tags 重算 topic

- **WHEN** 該版本經 enrichment 產出 `md_frontmatter.tags`，並被 approve 或 reject
- **THEN** `topic` 以 tags＋title 重算並 upsert 覆蓋，反映最佳分類

### Requirement: md_body 與失效圖片統計欄位

Gold 於 approve／reject 解析 md 正文時 MUST 一併寫入：內嵌 Object `md_body`（`valid_img_count` 整數、`word_count` 整數、`recomputed_at` 日期或 null），以及 `dismatched_img_count`（整數）、`md_has_dismatched_img`（布林）。命中（可正常渲染）的圖片數 SHALL 只記於 `md_body.valid_img_count`，`md_frontmatter` MUST NOT 含 `valid_img` 欄位。`dismatched_img_count` SHALL 為 md 正文 `![]()` 連結總數減去命中歸檔／raw 圖片 basename 的數；`md_has_dismatched_img` SHALL 為 `dismatched_img_count > 0`。

#### Scenario: 有失效圖片的 md

- **WHEN** 歸檔／退件 md 正文有 3 個 `![]()` 連結、其中 1 個 basename 未命中對應圖片
- **THEN** `md_body.valid_img_count=2`、`dismatched_img_count=1`、`md_has_dismatched_img=true`，`md_body.word_count` 為正文字數，`md_body.recomputed_at=null`，且 `md_frontmatter` 不含 `valid_img`

#### Scenario: 無失效圖片的 md

- **WHEN** md 正文所有 `![]()` 連結 basename 皆命中對應圖片
- **THEN** `dismatched_img_count=0`、`md_has_dismatched_img=false`

### Requirement: created_at / updated_at 稽核時間戳

`onenote_note_metadata` 每個版本 SHALL 有 `created_at`（首次 insert 時間）與 `updated_at`（最近一次任一欄位變更時間），兩者 SHALL 由共用的 upsert 工具集中維護：每次 upsert 的 `$set` MUST 蓋 `updated_at` 為當下 UTC，首次 insert 的 `$setOnInsert` MUST 補 `created_at` 為當下 UTC。呼叫端 MUST NOT 需要逐處手動帶這兩個時間戳。

#### Scenario: 首次 insert 同時記兩時間戳

- **WHEN** 某 `(page_id, dt)` 首次被 upsert
- **THEN** 該版本同時寫入 `created_at` 與 `updated_at`（值相近）

#### Scenario: 後續更新只動 updated_at

- **WHEN** 已存在的版本被再次 upsert（如 enrich 後翻 `pending_review`）
- **THEN** `updated_at` 被更新為當下、`created_at` 維持首次值不變
