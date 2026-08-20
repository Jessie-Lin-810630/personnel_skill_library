## MODIFIED Requirements

### Requirement: Approve 觸發歸檔

系統 SHALL 提供 Flask 端點 `POST /archive`，接收 `page_id`、`dt`、`role`、`action`。當
`action=approved` 時，端點 MUST 呼叫 Gold Load 把該版本的 silver md 與其引用 png 從
`processed-notes/`（md）與 `raw-notes/`（png，路徑取自 C3 `attached_images[].raw_image_path`）複製到
`archived-notes/<user>/<notebook>/<section>/dt=<dt>/`，取得各自新 md5，並 upsert
`onenote_note_metadata`（複合唯一鍵 `page_id`+`dt`）：`status=archived`、`review_result=approved`、
`reviewed_by_role`、`reviewed_at`、`archived_at`、`archived_md_path`、`md_md5_hash`，以及把每個
`attached_images` Object 回填 `archived_image_path`、`archived_image_md5`。
本端點 MUST NOT 執行向量化（解耦至另一條 pipeline）。

#### Scenario: approve 已生成的版本
- **WHEN** 呼叫端 `POST /archive`，body 為 `{page_id, dt, role, action: "approved"}`，且該版本 `enriched_md_path != null`
- **THEN** 端點複製 md+png 到 `archived-notes/.../dt=<dt>/`、upsert C3 為 `archived`/`approved`、寫入 `archived_md_path` 與各 `attached_images[].archived_image_path/archived_image_md5` 與審核欄位，回傳 `200` 與 `{status: "archived", md_archive_path: "gs://..."}`（HTTP 回應 JSON 的 `md_archive_path` 鍵維持不變）

#### Scenario: approve 尚未生成 md 的版本
- **WHEN** 呼叫端 approve 一個 `enriched_md_path=null` 的版本
- **THEN** 端點不歸檔，回傳可辨識錯誤（該版本尚無 silver md 可歸檔），C3 不翻 `archived`

### Requirement: 歸檔連帶退役同頁其他候選版本

當 `action=approved` 歸檔成功後，Gold Load MUST 退役同頁（同 `page_id`）其他仍在審閱
（`status=pending_review`）的版本：以同一組複合唯一鍵 upsert C3 翻為 `status=review_closed`，並依
`html_sha_hash` 判定 `review_result`——與歸檔版 `html_sha_hash` 相同者標 `overwritten`（內容等同已被採納）、
不同者標 `rejected`。退役版本 MUST 記 `reviewed_at`，MUST NOT 寫 `reviewed_by_role`
（非逐一人工審閱，僅因同頁擇一歸檔而連帶結束審閱期）。`status != pending_review` 的版本
（如未進審閱的 `bronze_stored`）MUST NOT 被退役。

#### Scenario: 同 hash 的候選版本標 overwritten
- **WHEN** approve 某版本歸檔成功，同頁另有 `pending_review` 版本其 `html_sha_hash` 與歸檔版相同
- **THEN** 該版本被 upsert 為 `status=review_closed`、`review_result=overwritten`，記 `reviewed_at`、不記 `reviewed_by_role`

#### Scenario: 不同 hash 的候選版本標 rejected
- **WHEN** approve 某版本歸檔成功，同頁另有 `pending_review` 版本其 `html_sha_hash` 與歸檔版不同
- **THEN** 該版本被 upsert 為 `status=review_closed`、`review_result=rejected`，記 `reviewed_at`、不記 `reviewed_by_role`

#### Scenario: 未進審閱的版本不受退役影響
- **WHEN** approve 某版本歸檔成功，同頁另有 `status=bronze_stored`（`enriched_md_path=null`、從未進審閱）的版本
- **THEN** 該 `bronze_stored` 版本狀態不變，不被翻為 `review_closed`

### Requirement: 歸檔後萃取 frontmatter 與品質 metadata

Gold Load 在歸檔完成後 MUST 讀回 `archived-notes/` 那份剛歸檔的 md，組出內嵌 Object
`md_frontmatter`（僅 `tags`、`date`、`type`、`alias` 取自 frontmatter，MUST NOT 含 `valid_img`），並額外寫入
內嵌 Object `md_body`（`valid_img_count`、`word_count`、`recomputed_at`）、`dismatched_img_count`、
`md_has_dismatched_img`，以及以 `md_frontmatter.tags`＋頁面標題重算的 `topic`，最後以同一組複合唯一鍵
（`page_id`+`dt`）upsert `onenote_note_metadata`。當 frontmatter 未被正確寫入 metadata 區時，MUST 以
正文頂端 `key: value` 區塊做補救解析。`date` 寫入 C3 前 MUST 正規化為 BSON 可編碼的日期時間型別。

`md_body.valid_img_count` MUST 由歸檔 md 正文的 `![]()` 圖片連結取出檔名（basename），
與 `attached_images[].archived_image_path` 的 basename 比對，計算命中（可正常渲染）的圖片數。
`dismatched_img_count` MUST 為正文 `![]()` 連結總數減 `valid_img_count`；`md_has_dismatched_img` 為其 `> 0`。

#### Scenario: frontmatter 正常
- **WHEN** 歸檔 md 具合法 frontmatter（`tags: [..]`、`date: YYYY-MM-DD`、`type: ..`、`alias: [..]`）
- **THEN** C3 對應版本被 upsert 寫入 `md_frontmatter`（`tags`/`date`/`type`/`alias`，不含 `valid_img`）、`md_body`（`valid_img_count`/`word_count`/`recomputed_at=null`）、`dismatched_img_count`、`md_has_dismatched_img`，並以 tags 重算 `topic`

#### Scenario: frontmatter 錯位到正文
- **WHEN** md 的 metadata 未在 frontmatter 區、而落在正文頂端
- **THEN** Gold Load 掃描正文頂端 `key: value`（遇第一個真正 Markdown 標題行才停）補救萃取，寫入 `md_frontmatter` 並據其 tags 重算 `topic`

#### Scenario: 模型改壞圖片連結
- **WHEN** 歸檔 md 有 3 個 `![]()` 連結，其中 1 個檔名被模型改壞、不落在 `attached_images[].archived_image_path`
- **THEN** `md_body.valid_img_count=2`、`dismatched_img_count=1`、`md_has_dismatched_img=true`，且 `md_frontmatter` 不含 `valid_img`

### Requirement: Reject 標記關閉並保存壞 md 品質 metadata

當 `action=rejected` 時，端點 MUST upsert C3（`status=review_closed`、`review_result=rejected`、
`reviewed_by_role`、`reviewed_at`），MUST NOT 進行任何 GCS 歸檔寫入。退貨後 MUST 背景讀該版
silver md（`enriched_md_path`）萃取 `md_frontmatter`（不含 `valid_img`）、`md_body`（`valid_img_count` 對該版
`attached_images[].raw_image_path` basename 比對）、`dismatched_img_count`、`md_has_dismatched_img`，並以
tags 重算 `topic`，以同一組複合唯一鍵 upsert C3，供好 md／壞 md 分析；好壞由 `status` 區分。frontmatter 萃取失敗只記 `error_msg`，
MUST NOT 使退貨本身失敗。

#### Scenario: reject 一個版本
- **WHEN** 呼叫端 `POST /archive`，`action=rejected`，該版有 `enriched_md_path`
- **THEN** C3 對應版本翻為 `review_closed`/`rejected` 並記審核者與時間，不寫 `archived-notes/`，且寫入 `md_frontmatter`（不含 valid_img）、`md_body`（含 valid_img_count）、`dismatched_img_count`、`md_has_dismatched_img` 與重算的 `topic`，回傳 `200`

#### Scenario: reject 尚無 md 的版本
- **WHEN** 退貨一個 `enriched_md_path=null` 的版本
- **THEN** 僅翻 `review_closed`/`rejected`，不萃取 frontmatter、不報錯，回傳 `200`
