# gold-archive-endpoint Specification

## Purpose
規範 Gold 端點 `POST /archive` 接收審查結果後的行為，涵蓋 approve 時把 silver md 與引用圖片歸檔並萃取 frontmatter、同頁其他候選版本的退役、reject 時的關閉標記，以及身分與請求欄位的驗證，讓每個 OneNote 頁面在 `onenote_note_metadata` 中只有經過人工審核的版本進入 `archived-notes/`，並成為下游向量化的唯一來源。

## Requirements
### Requirement: Approve 觸發歸檔

- 系統 SHALL 提供 FastAPI 端點 `POST /archive`，接收 `page_id`、`dt`、`action`。
- 審核者角色不再由 body 提供，改由 `X-User-Token` 驗證後推導，規則見 `user-identity-verification`。
- 當 `action=approved` 時，端點 MUST 呼叫 Gold Load 把該版本的 silver md 與其引用 png 從 `processed-notes/`（md）與 `raw-notes/`（png，路徑取自 `onenote_note_metadata` 的 `attached_images[].raw_image_path`）複製到 `archived-notes/<user>/<notebook>/<section>/dt=<dt>/`，取得各自新 md5。
- 複製完成後 MUST upsert `onenote_note_metadata`（複合唯一鍵 `page_id`+`dt`）：`status=archived`、`review_result=approved`、`reviewed_by_role`、`reviewed_at`、`archived_at`、`archived_md_path`、`md_md5_hash`，並把每個 `attached_images` Object 回填 `archived_image_path`、`archived_image_md5`。
- 系統不可 (MUST NOT) 再以 `md_archive_path`／`img_archive_path`／`md_md5` 作為寫入 `onenote_note_metadata` 的 document key；HTTP 回應 JSON 的 `md_archive_path` 與 `img_archive_path` 鍵維持不變。
- 其中 `reviewed_by_role` MUST 寫入驗證後推導的角色。
- 本端點不可 (MUST NOT) 執行向量化（解耦至另一條 pipeline）。

#### Scenario: approve 已生成的版本
- **WHEN** 呼叫端 `POST /archive`，body 為 `{page_id, dt, action: "approved"}`，帶有通過驗證的 `X-User-Token`，且該版本 `enriched_md_path != null`
- **THEN** 端點複製 md+png 到 `archived-notes/.../dt=<dt>/`、upsert `onenote_note_metadata` 為 `archived`/`approved`，寫入 `archived_md_path`、`md_md5_hash`、各 `attached_images[].archived_image_path`／`archived_image_md5` 與審核欄位（`reviewed_by_role` 取自驗證結果），回傳 `200` 與 `{status: "archived", md_archive_path: "gs://..."}`

#### Scenario: approve 尚未生成 md 的版本
- **WHEN** 呼叫端 approve 一個 `enriched_md_path=null` 的版本
- **THEN** 端點不歸檔，回傳可辨識錯誤（該版本尚無 silver md 可歸檔），`onenote_note_metadata` 不翻 `archived`

### Requirement: 歸檔連帶退役同頁其他候選版本

當 `action=approved` 歸檔成功後，Gold Load MUST 退役同頁（同 `page_id`）其他仍在審閱
（`status=pending_review`）的版本：以同一組複合唯一鍵 upsert `onenote_note_metadata` 翻為
`status=review_closed`，並依 `html_sha_hash` 判定 `review_result`——與歸檔版 `html_sha_hash` 相同者標
`overwritten`（內容等同已被採納）、不同者標 `rejected`。退役版本 MUST 記 `reviewed_at`，
MUST NOT 寫 `reviewed_by_role`（非逐一人工審閱，僅因同頁擇一歸檔而連帶結束審閱期）。
`status != pending_review` 的版本（如未進審閱的 `bronze_stored`）MUST NOT 被退役。

#### Scenario: 同 hash 的候選版本標 overwritten
- **WHEN** approve 某版本歸檔成功，同頁另有 `pending_review` 版本其 `html_sha_hash` 與歸檔版相同
- **THEN** 該版本被 upsert 為 `status=review_closed`、`review_result=overwritten`，記 `reviewed_at`、不記 `reviewed_by_role`

#### Scenario: 不同 hash 的候選版本標 rejected
- **WHEN** approve 某版本歸檔成功，同頁另有 `pending_review` 版本其 `html_sha_hash` 與歸檔版不同
- **THEN** 該版本被 upsert 為 `status=review_closed`、`review_result=rejected`，記 `reviewed_at`、不記 `reviewed_by_role`

#### Scenario: 未進審閱的版本不受退役影響
- **WHEN** approve 某版本歸檔成功，同頁另有 `status=bronze_stored`（`enriched_md_path=null`、從未進審閱）的版本
- **THEN** 該 `bronze_stored` 版本狀態不變，不被翻為 `review_closed`

### Requirement: 歸檔後萃取 frontmatter metadata

Gold Load 在歸檔完成後 MUST 讀回 `archived-notes/` 那份剛歸檔的 md，組出內嵌 Object
`md_frontmatter`，並以同一組複合唯一鍵（`page_id`+`dt`）upsert `onenote_note_metadata`。該 Object
MUST 含 4 個欄位：`tags`、`date`、`type`、`alias`（取自 frontmatter），且 MUST NOT 含 `valid_img`
——命中的圖片數改記於 `md_body.valid_img_count`。當 frontmatter 未被正確寫入 metadata 區時，
MUST 以正文頂端 `key: value` 區塊做補救解析。`date` 寫入 `onenote_note_metadata` 前 MUST 正規化為
BSON 可編碼的日期時間型別。

同一次 upsert MUST 一併寫入內嵌 Object `md_body`（`valid_img_count` 整數、`word_count` 整數、
`recomputed_at` 日期或 null）、`dismatched_img_count`（整數）、`md_has_dismatched_img`（布林），
以及以 `md_frontmatter.tags`＋頁面標題重算的 `topic`。

`md_body.valid_img_count` MUST 由歸檔 md 正文的 `![]()` 圖片連結取出檔名（basename），與
`attached_images[].archived_image_path` 的 basename 比對，計算命中（可正常渲染）的圖片數，供追蹤
模型輸出的圖片連結正確率。`dismatched_img_count` MUST 為正文 `![]()` 連結總數減去
`valid_img_count`；`md_has_dismatched_img` MUST 為 `dismatched_img_count > 0`。

#### Scenario: frontmatter 正常
- **WHEN** 歸檔 md 具合法 frontmatter（`tags: [..]`、`date: YYYY-MM-DD`、`type: ..`、`alias: [..]`）
- **THEN** 對應版本被 upsert 寫入 `md_frontmatter`，內含 `tags`（陣列）、`date`（日期時間）、`type`（字串）、`alias`（陣列）且不含 `valid_img`，並一併寫入 `md_body`（`valid_img_count`／`word_count`／`recomputed_at=null`）、`dismatched_img_count`、`md_has_dismatched_img` 與以 tags 重算的 `topic`

#### Scenario: frontmatter 錯位到正文
- **WHEN** md 的 metadata 未在 frontmatter 區、而落在正文頂端
- **THEN** Gold Load 掃描正文頂端 `key: value`（遇第一個真正 Markdown 標題行才停）補救萃取，寫入 `md_frontmatter` 並據其 tags 重算 `topic`

#### Scenario: 模型改壞圖片連結
- **WHEN** 歸檔 md 有 3 個 `![]()` 連結，其中 1 個檔名被模型改壞、不落在 `attached_images[].archived_image_path`
- **THEN** `md_body.valid_img_count` 計為 2（僅命中歸檔圖片者計入）、`dismatched_img_count=1`、`md_has_dismatched_img=true`

### Requirement: 可審閱版本篩選

審查頁（呼叫端）SHALL 只呈現「可審閱」的版本：查 C3 時 MUST 濾掉 `status=review_closed`
的版本（含 `review_result=rejected` 與 `overwritten`，不論 `dt`）；並依每個 `page_id` 算出
`lastArchivedAt = max(dateTrunc(archived_at, day))`，只保留 `dt >= lastArchivedAt` 的版本
（尚無歸檔時全留）。此使歸檔後的新內容（更新的 `dt`）能重新進入審閱與歸檔，而已退役與比最後
歸檔日更舊的版本自動退出審查佇列。

#### Scenario: 已退役版本不再出現
- **WHEN** 某版本 `status=review_closed`（`review_result=rejected` 或 `overwritten`）
- **THEN** 該版本不出現在審查頁的版本清單（不論其 `dt`）；同名其他非 review_closed 版本不受影響

#### Scenario: 歸檔後新內容可重走 Silver→Gold
- **WHEN** 某 `page_id` 已有一版歸檔，之後 bronze 下載到更新內容（更新的 `dt`）
- **THEN** 該新 `dt` 版本出現在審查頁、可 on-demand enrich 並再次 approve 歸檔；比最後歸檔日更舊的版本不再顯示

### Requirement: 歸檔把關與逐版本唯讀

端點 MUST 防禦性把關：本 `(page_id, dt)` 已 `archived` 時 approve 為 idempotent（不重做）；
當存在「更新內容的歸檔版本」（本版 `dt` 日 < 最後歸檔日）時 MUST 拒絕歸檔、不覆寫舊版；
本版 `dt` 日 ≥ 最後歸檔日（含尚無歸檔）則放行。審查頁 MUST 僅對「選中版本自己已 `archived`」時
停用該版 `approve`/`reject`/`regenerate` 並標示唯讀，MUST NOT 因同名另一版已歸檔而停用本版。

#### Scenario: approve 較舊版本被拒
- **WHEN** 某 `page_id` 已有較新內容歸檔，呼叫端 approve 一個 `dt` 日早於最後歸檔日的舊版
- **THEN** 端點回 `409` 與可辨識錯誤，不覆寫既有歸檔

#### Scenario: 重複 approve 已歸檔版本
- **WHEN** 呼叫端對一個 `status=archived` 的版本再次 approve
- **THEN** 端點回 `200` 並回既有歸檔路徑（idempotent），不重複複製或改動

#### Scenario: 審查頁逐版本停用
- **WHEN** 審查頁選中的版本 `status=archived`
- **THEN** 僅該版顯示唯讀、其 approve/reject/regenerate 停用；同名其他可審閱版本的按鈕維持可用

### Requirement: Reject 標記關閉並保存壞 md frontmatter

當 `action=rejected` 時，端點 MUST upsert `onenote_note_metadata`（`status=review_closed`、
`review_result=rejected`、`reviewed_by_role`、`reviewed_at`），MUST NOT 進行任何 GCS 歸檔寫入。
退貨後 MUST 背景讀該版 silver md（`enriched_md_path`）萃取 `md_frontmatter`（不含 `valid_img`）、
`md_body`（`valid_img_count` 以該版 `attached_images[].raw_image_path` 的 basename 比對）、
`dismatched_img_count`、`md_has_dismatched_img`，並以 tags 重算 `topic`，以同一組複合唯一鍵
upsert `onenote_note_metadata`，供好 md／壞 md 分析；好壞由 `status` 區分。萃取失敗只記
`error_msg`，MUST NOT 使退貨本身失敗。

#### Scenario: reject 一個版本
- **WHEN** 呼叫端 `POST /archive`，`action=rejected`，該版有 `enriched_md_path`
- **THEN** 對應版本翻為 `review_closed`/`rejected` 並記審核者與時間，不寫 `archived-notes/`，且寫入 `md_frontmatter`（不含 `valid_img`）、`md_body`（含 `valid_img_count`）、`dismatched_img_count`、`md_has_dismatched_img` 與重算的 `topic`，回傳 `200`

#### Scenario: reject 尚無 md 的版本
- **WHEN** 退貨一個 `enriched_md_path=null` 的版本
- **THEN** 僅翻 `review_closed`/`rejected`，不萃取 frontmatter、不報錯，回傳 `200`

### Requirement: 請求驗證

- 端點 MUST 先驗證 `X-User-Token`，未通過者回 `401` 或 `403`，取不到驗簽金鑰回 `503`（規則見 `user-identity-verification`），三者皆不可 (MUST NOT) 呼叫 Gold Load。
- 通過身分驗證後，端點 MUST 以 Pydantic model 驗證必要欄位與合法 `action`：缺 `page_id`/`dt`/`action` 回 `400`；`action` 非 `approved`/`rejected` 回 `400`；`page_id`+`dt` 查無版本回 `404`。
- `role` 不再是請求欄位，body 若帶了 `role` MUST 予以忽略。
- 驗證失敗的狀態碼 MUST 為 `400`，不可 (MUST NOT) 使用 `422`，因為 `422` 已用於「該版本尚未生成 md 或複製失敗」這類業務錯誤，兩者必須可分辨。

#### Scenario: 缺欄位
- **WHEN** body 缺少 `page_id`、`dt` 或 `action` 任一
- **THEN** 端點回 `400`，不呼叫 Gold Load

#### Scenario: 非法 action
- **WHEN** `action` 非 `approved`/`rejected`
- **THEN** 端點回 `400`

#### Scenario: body 夾帶 role 欄位
- **WHEN** 呼叫端在 body 帶了 `role`
- **THEN** 端點忽略該欄位，仍以 `X-User-Token` 推導的角色寫入 `reviewed_by_role`

#### Scenario: 身分驗證未通過
- **WHEN** 請求未帶 `X-User-Token`、token 驗簽失敗，或 email 不在 `USER_ALLOWLIST` 內
- **THEN** 端點回 `401` 或 `403`，不呼叫 Gold Load，GCS 與 MongoDB 皆無寫入

#### Scenario: 取不到驗簽金鑰
- **WHEN** `X-User-Token` 合法，但端點連不上 Google 的 JWK 端點
- **THEN** 端點回 `503`，不呼叫 Gold Load，GCS 與 MongoDB 皆無寫入

#### Scenario: 驗證失敗與業務錯誤可分辨
- **WHEN** 一個請求因欄位不合法被擋下，另一個請求因該版本尚未生成 md 被擋下
- **THEN** 前者回 `400`，後者回 `422`
