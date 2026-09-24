# Spec Delta

## MODIFIED Requirements

### Requirement: On-demand Silver enrich 端點

- 系統 SHALL 提供一個 FastAPI 端點 `POST /enrich`，接收單一版本的 `page_id`、`dt` 與 `trigger`，呼叫 Silver 服務本體 `t_enrich_html_to_markdown` 對該版本做 on-demand enrichment，並回傳 JSON 結果供呼叫端（審查頁）渲染。
- 端點自身不可 (MUST NOT) 主動刪除任何 bronze 版本或既有 md。
- `trigger` 的合法值為 `on_demand` 與 `regenerate`；未提供時預設 `on_demand`。
- 請求欄位 SHALL 由 Pydantic model 驗證，驗證失敗回 `400`，與既有行為一致。
- 端點 SHALL 在處理請求之前先驗證 `X-Reviewer-Token`，驗證規則見 `reviewer-identity-verification`。
- 未通過驗證者不可 (MUST NOT) 進入 enrichment 流程。

#### Scenario: cache miss 首次生成
- **WHEN** 呼叫端 `POST /enrich`，body 為 `{page_id, dt, trigger: "on_demand"}`，帶有通過驗證的 `X-Reviewer-Token`，且該版本 `md_path=null`、無同 `html_hash` 快取
- **THEN** 端點呼叫 Silver 服務實際打 LLM，將 md 寫入 GCS `processed-notes/<user>/<notebook>/<section>/dt=<dt>/`，upsert `onenote_note_metadata`（`md_path`、`md_md5`、`status=pending_review`），回傳 `200` 與 `{status: "pending_review", cache_hit: false, md_path: "gs://..."}`

#### Scenario: cache hit 重用既有 md
- **WHEN** 呼叫端 `POST /enrich` 的 `html_hash` 已有一列 `md_path != null` 的紀錄（同版本重看或同 hash 另一版本已生成）
- **THEN** 端點不打 LLM，直接回傳既有 `md_path`，`{status: "pending_review", cache_hit: true, md_path: "gs://..."}`，且 `multimodal_llm_enrichment_logs` 記一列 `cache_hit=true`、tokens=0

#### Scenario: regenerate 受 quota 限制
- **WHEN** 呼叫端 `POST /enrich` 帶 `trigger: "regenerate"`，且該 `html_hash` 已 regenerate 達上限（2 次）
- **THEN** 端點回傳原狀態且不打 LLM，`{error: "regenerate quota exceeded", cache_hit: false}`

#### Scenario: 缺少必要欄位
- **WHEN** 呼叫端 `POST /enrich` 未帶 `page_id` 或 `dt`
- **THEN** Pydantic 驗證失敗，端點回傳 `400` 與錯誤訊息，不呼叫 Silver 服務

#### Scenario: trigger 值非法
- **WHEN** 呼叫端 `POST /enrich` 帶的 `trigger` 不是 `on_demand` 或 `regenerate`
- **THEN** Pydantic 驗證失敗，端點回傳 `400`，不呼叫 Silver 服務

#### Scenario: 身分驗證未通過
- **WHEN** 請求未帶 `X-Reviewer-Token`、token 驗簽失敗，或 email 不在允許清單內
- **THEN** 端點回 `401` 或 `403`（依 `reviewer-identity-verification` 的規則），不呼叫 Silver 服務，不寫入 GCS 與 MongoDB

#### Scenario: 找不到版本
- **WHEN** `page_id`+`dt` 在 `onenote_note_metadata` 查無對應版本
- **THEN** 端點回傳 `404` 與 `{status: "not_found", error: ...}`

#### Scenario: 服務級斷路器開啟
- **WHEN** LLM API 連續失敗達門檻、服務級斷路器 `_LLMServiceGuard` 開啟期間收到 cache miss 請求
- **THEN** 端點不打 LLM，回傳 `{circuit_open: true, status: "bronze_stored"}`，該版本狀態維持 `bronze_stored`

## ADDED Requirements

### Requirement: 斷路器計數在多執行緒下不漏算

- 服務級斷路器 `_LLMServiceGuard` 的連續失敗次數，在同一個 process 內有多個請求並行時 MUST 正確累加，不因同時寫入而少算。
- 實作上建議 (SHOULD) 以鎖保護 `record_failure` 與 `record_success` 的狀態變更，讓累加與跳脫判斷成為單一不可分割的動作。

#### Scenario: 兩個請求同時失敗
- **WHEN** 兩個 enrich 請求在同一個 process 內同時失敗並記錄失敗
- **THEN** 連續失敗次數累加兩次，不因同時寫入而少算

#### Scenario: 累計達門檻即跳脫
- **WHEN** 連續失敗次數累加到設定門檻
- **THEN** 斷路器進入冷卻，且冷卻時間只被設定一次
