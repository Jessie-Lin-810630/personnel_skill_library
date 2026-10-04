# silver-enrich-endpoint Specification

## Purpose
規範 Silver 端點 `POST /enrich` 對單一 OneNote 版本做 on-demand html 轉 md 的行為，涵蓋請求驗證、首次轉換與重新生成兩種觸發方式，以及並行請求下仍維持正確狀態的 LLM 服務斷路器，讓 LLM 只在審查者實際開啟某個版本時才被呼叫，並在 LLM 服務連續失敗時暫停呼叫。

## Requirements
### Requirement: On-demand Silver enrich 端點

- 系統 SHALL 提供一個 FastAPI 端點 `POST /enrich`，接收單一版本的 `page_id`、`dt` 與 `trigger`，呼叫 Silver 服務本體 `t_enrich_html_to_markdown` 對該版本做 on-demand enrichment，並回傳 JSON 結果供呼叫端（審查頁）渲染。
- 端點自身不可 (MUST NOT) 主動刪除任何 bronze 版本或既有 md。
- `trigger` 的合法值為 `on_demand` 與 `regenerate`；未提供時預設 `on_demand`。
- 請求欄位 SHALL 由 Pydantic model 驗證，驗證失敗回 `400`，與既有行為一致。
- 端點 SHALL 在處理請求之前先驗證 `X-User-Token`，驗證規則見 `user-identity-verification`。
- 未通過驗證者不可 (MUST NOT) 進入 enrichment 流程。
- Silver 讀 `onenote_note_metadata`／寫 `onenote_note_metadata` 時 SHALL 使用對齊定稿的欄位名：hash 判定與快取查找用 `html_sha_hash`，silver md 路徑 upsert 用 `enriched_md_path`、產出時間用 `enriched_md_exported_at`、物件指紋用 `md_md5_hash`。系統不可 (MUST NOT) 再以 `html_hash`／`md_path`／`md_md5` 作為寫入 `onenote_note_metadata` 的 document key。
- 快取查找 SHALL 以 `html_sha_hash` 相同且 `enriched_md_path != null` 命中既有 md。
- 圖片來源 SHALL 取自 `attached_images[].raw_image_path`。
- HTTP 回應 JSON 的 `md_path` 鍵維持不變，其值取自 `onenote_note_metadata` 的 `enriched_md_path`。

#### Scenario: cache miss 首次生成
- **WHEN** 呼叫端 `POST /enrich`，body 為 `{page_id, dt, trigger: "on_demand"}`，帶有通過驗證的 `X-User-Token`，且該版本 `enriched_md_path=null`、無同 `html_sha_hash` 快取
- **THEN** 端點呼叫 Silver 服務實際打 LLM，將 md 寫入 GCS `processed-notes/<user>/<notebook>/<section>/dt=<dt>/`，upsert `onenote_note_metadata`（`enriched_md_path`、`enriched_md_exported_at`、`md_md5_hash`、`status=pending_review`），回傳 `200` 與 `{status: "pending_review", cache_hit: false, md_path: "gs://..."}`

#### Scenario: cache hit 重用既有 md
- **WHEN** 呼叫端 `POST /enrich` 的 `html_sha_hash` 已有一列 `enriched_md_path != null` 的紀錄（同版本重看或同 hash 另一版本已生成）
- **THEN** 端點不打 LLM，直接回傳既有 md 位址，`{status: "pending_review", cache_hit: true, md_path: "gs://..."}`，且 `multimodal_llm_enrichment_logs` 記一列 `cache_hit=true`、tokens=0

#### Scenario: regenerate 受 quota 限制
- **WHEN** 呼叫端 `POST /enrich` 帶 `trigger: "regenerate"`，且該 `html_sha_hash` 已 regenerate 達上限（2 次）
- **THEN** 端點回傳原狀態且不打 LLM，`{error: "regenerate quota exceeded", cache_hit: false}`

#### Scenario: 缺少必要欄位
- **WHEN** 呼叫端 `POST /enrich` 未帶 `page_id` 或 `dt`
- **THEN** Pydantic 驗證失敗，端點回傳 `400` 與錯誤訊息，不呼叫 Silver 服務

#### Scenario: trigger 值非法
- **WHEN** 呼叫端 `POST /enrich` 帶的 `trigger` 不是 `on_demand` 或 `regenerate`
- **THEN** Pydantic 驗證失敗，端點回傳 `400`，不呼叫 Silver 服務

#### Scenario: 身分驗證未通過
- **WHEN** 請求未帶 `X-User-Token`、token 驗簽失敗，或 email 不在 `USER_ALLOWLIST` 內
- **THEN** 端點回 `401` 或 `403`（依 `user-identity-verification` 的規則），不呼叫 Silver 服務，不寫入 GCS 與 MongoDB

#### Scenario: 取不到驗簽金鑰
- **WHEN** `X-User-Token` 合法，但端點連不上 Google 的 JWK 端點
- **THEN** 端點回 `503`，不呼叫 Silver 服務，不寫入 GCS 與 MongoDB

#### Scenario: 找不到版本
- **WHEN** `page_id`+`dt` 在 `onenote_note_metadata` 查無對應版本
- **THEN** 端點回傳 `404` 與 `{status: "not_found", error: ...}`

#### Scenario: 服務級斷路器開啟
- **WHEN** LLM API 連續失敗達門檻、服務級斷路器 `_LLMServiceGuard` 開啟期間收到 cache miss 請求
- **THEN** 端點不打 LLM，回傳 `{circuit_open: true, status: "bronze_stored"}`，該版本狀態維持 `bronze_stored`

### Requirement: 斷路器狀態不因並行請求而失真

- 服務級斷路器 `_LLMServiceGuard` 的連續失敗次數與冷卻時間，在同一個 process 內有多個請求並行時 MUST 維持在合理範圍：次數不為負、不超過設定門檻，冷卻時間不為負。
- 實作上建議 (SHOULD) 以鎖保護 `record_failure` 與 `record_success` 的狀態變更，讓累加與跳脫判斷成為單一不可分割的動作。查詢是否冷卻中的讀取不必加鎖，因為它不改變任何狀態。

#### Scenario: 累計達門檻即跳脫
- **WHEN** 連續失敗次數累加到設定門檻
- **THEN** 斷路器進入冷卻，且計數歸零讓冷卻結束後重新累積

#### Scenario: 成功後重新計算
- **WHEN** 累積若干次失敗但尚未達門檻，接著記錄一次成功
- **THEN** 連續失敗次數歸零，後續失敗需重新累積到門檻才會跳脫

#### Scenario: 並行呼叫下狀態仍合理
- **WHEN** 多條執行緒同時對同一個斷路器記錄成功與失敗
- **THEN** 連續失敗次數不為負且不超過門檻，過程中不拋出例外
