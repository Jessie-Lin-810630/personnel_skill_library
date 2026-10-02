# Spec Delta

## MODIFIED Requirements

### Requirement: Approve 觸發歸檔

- 系統 SHALL 提供 FastAPI 端點 `POST /archive`，接收 `page_id`、`dt`、`action`。
- 審核者角色不再由 body 提供，改由 `X-User-Token` 驗證後推導，規則見 `user-identity-verification`。
- 當 `action=approved` 時，端點 MUST 呼叫 Gold Load 把該版本的 silver md 與其引用 png 從 `processed-notes/`（md）與 `raw-notes/`（png，路徑取自 `onenote_note_metadata` 的 `img_path`）複製到 `archived-notes/<user>/<notebook>/<section>/dt=<dt>/`，取得各自新 md5。
- 複製完成後 MUST upsert `onenote_note_metadata`（複合唯一鍵 `page_id`+`dt`）：`status=archived`、`review_result=approved`、`reviewed_by_role`、`reviewed_at`、`archived_at`、`md_archive_path`、`img_archive_path`。
- 其中 `reviewed_by_role` MUST 寫入驗證後推導的角色。
- 本端點不可 (MUST NOT) 執行向量化（解耦至另一條 pipeline）。

#### Scenario: approve 已生成的版本
- **WHEN** 呼叫端 `POST /archive`，body 為 `{page_id, dt, action: "approved"}`，帶有通過驗證的 `X-User-Token`，且該版本 `md_path != null`
- **THEN** 端點複製 md+png 到 `archived-notes/.../dt=<dt>/`、upsert `onenote_note_metadata` 為 `archived`/`approved` 並寫入歸檔路徑與審核欄位（`reviewed_by_role` 取自驗證結果），回傳 `200` 與 `{status: "archived", md_archive_path: "gs://..."}`

#### Scenario: approve 尚未生成 md 的版本
- **WHEN** 呼叫端 approve 一個 `md_path=null` 的版本
- **THEN** 端點不歸檔，回傳可辨識錯誤（該版本尚無 silver md 可歸檔），`onenote_note_metadata` 不翻 `archived`

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
