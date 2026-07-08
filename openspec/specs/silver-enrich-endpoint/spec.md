# silver-enrich-endpoint Specification

## Purpose
TBD - created by archiving change silver-ondemand-review-page. Update Purpose after archive.
## Requirements
### Requirement: On-demand Silver enrich 端點

系統 SHALL 提供一個 Flask 端點 `POST /enrich`，接收單一版本的 `page_id`、`dt` 與 `trigger`，
呼叫 Silver 服務本體 `t_enrich_html_to_markdown` 對該版本做 on-demand enrichment，
並回傳 JSON 結果供呼叫端（審查頁）渲染。端點自身 MUST NOT 主動刪除任何 bronze 版本或既有 md。

`trigger` 的合法值為 `on_demand` 與 `regenerate`；未提供時預設 `on_demand`。

#### Scenario: cache miss 首次生成
- **WHEN** 呼叫端 `POST /enrich`，body 為 `{page_id, dt, trigger: "on_demand"}`，且該版本 `md_path=null`、無同 `html_hash` 快取
- **THEN** 端點呼叫 Silver 服務實際打 LLM，將 md 寫入 GCS `processed-notes/<user>/<notebook>/<section>/dt=<dt>/`，upsert `onenote_note_metadata`（`md_path`、`md_md5`、`status=pending_review`），回傳 `200` 與 `{status: "pending_review", cache_hit: false, md_path: "gs://..."}`

#### Scenario: cache hit 重用既有 md
- **WHEN** 呼叫端 `POST /enrich` 的 `html_hash` 已有一列 `md_path != null` 的紀錄（同版本重看或同 hash 另一版本已生成）
- **THEN** 端點不打 LLM，直接回傳既有 `md_path`，`{status: "pending_review", cache_hit: true, md_path: "gs://..."}`，且 `multimodal_llm_enrichment_logs` 記一列 `cache_hit=true`、tokens=0

#### Scenario: regenerate 受 quota 限制
- **WHEN** 呼叫端 `POST /enrich` 帶 `trigger: "regenerate"`，且該 `html_hash` 已 regenerate 達上限（2 次）
- **THEN** 端點回傳原狀態且不打 LLM，`{error: "regenerate quota exceeded", cache_hit: false}`

#### Scenario: 缺少必要欄位
- **WHEN** 呼叫端 `POST /enrich` 未帶 `page_id` 或 `dt`
- **THEN** 端點回傳 `400` 與錯誤訊息，不呼叫 Silver 服務

#### Scenario: 找不到版本
- **WHEN** `page_id`+`dt` 在 `onenote_note_metadata` 查無對應版本
- **THEN** 端點回傳 `404` 與 `{status: "not_found", error: ...}`

#### Scenario: 服務級斷路器開啟
- **WHEN** LLM API 連續失敗達門檻、斷路器開啟期間收到 cache miss 請求
- **THEN** 端點不打 LLM，回傳 `{circuit_open: true, status: "bronze_stored"}`，該版本狀態維持 `bronze_stored`
