# onenote-versioned-review-page Specification

## Purpose
TBD - created by archiving change silver-ondemand-review-page. Update Purpose after archive.
## Requirements
### Requirement: 多版本對照選擇

審查頁 SHALL 讀取 `onenote_note_metadata`（唯讀），依 `page_id` 分組同名筆記的多個 `dt=` 版本，
並以圓鈕（radio）讓審查者切換該頁的任一版本。版本清單 MUST 依 `html_downloaded_at` 排序，
供審查者辨認版本先後。頁面自身 MUST NOT 直接寫入 MongoDB 或 GCS。

#### Scenario: 切換同名筆記的不同版本
- **WHEN** 審查者選定某頁筆記、頁面偵測到該 `page_id` 有多個 `dt=` 版本
- **THEN** 頁面以圓鈕列出各版本（標示 `dt` 與下載時間），選中某版即載入該版對照內容

#### Scenario: 尚無資料
- **WHEN** `onenote_note_metadata` 查無任何版本
- **THEN** 頁面顯示提示（如「尚無 Bronze 資料，請先執行 task07 lazy_loading Bronze ETL」），不報錯

### Requirement: 左右對照渲染

審查頁 SHALL 左側渲染選定版本的 bronze html、右側渲染 silver md，兩者皆自 GCS `gs://` URI 讀取
（`html_path`、`md_path`）。頁面 MUST 以 `gs://` URI 直接讀取，不得沿用原版本機路徑轉換邏輯。

#### Scenario: 已生成 md 的版本
- **WHEN** 選定版本 `md_path != null`
- **THEN** 左側顯示 bronze html、右側顯示既有 silver md（讀 GCS，cache hit、不觸發 LLM）

#### Scenario: 內嵌圖片渲染
- **WHEN** html 或 md 內含 `_images/<檔名>` 圖片引用
- **THEN** 頁面自 GCS 對應 `dt=` 分區的 `_images/` 讀圖並內嵌顯示

### Requirement: on-demand 觸發 Silver enrichment

審查頁 SHALL 在審查者點到 `md_path=null`（未 enrich）的版本時，`POST` 呼叫 Silver enrich 端點
（`SILVER_ENDPOINT_URL`）帶 `page_id`+`dt`+`trigger=on_demand`，取得結果後渲染右側 md。
沒被點到的版本 MUST NOT 被 enrich。

#### Scenario: 首次點擊未處理版本
- **WHEN** 審查者切到一個 `md_path=null` 的版本
- **THEN** 頁面 POST Silver 端點觸發生成，收到 `md_path` 後渲染右側 md；生成期間顯示載入狀態

#### Scenario: 端點呼叫失敗或斷路
- **WHEN** Silver 端點回傳錯誤、逾時或 `circuit_open=true`
- **THEN** 頁面顯示對應提示（服務暫停 / 連線失敗），左側 html 仍可正常顯示，不使整頁崩潰

### Requirement: 審查操作按鈕

審查頁 SHALL 提供 `regenerate`、`approve`、`reject` 按鈕。`regenerate` MUST 走 `trigger=regenerate`
呼叫 Silver 端點（受 quota 限制）；`approve`/`reject` 於本階段為**佔位**：按鈕渲染但點擊後僅顯示
「Gold 後端待接」提示，MUST NOT 呼叫任何歸檔後端。

#### Scenario: 對品質不佳的版本 regenerate
- **WHEN** 審查者對已生成的版本按下 `regenerate`
- **THEN** 頁面 POST Silver 端點帶 `trigger=regenerate`，強制重生 md（未達 quota 上限時）並重渲染右側

#### Scenario: regenerate 已達上限
- **WHEN** 該版本 `html_hash` 的 regenerate 已達 2 次上限、審查者再按 `regenerate`
- **THEN** 頁面顯示「已達 regenerate 上限」提示，不再觸發 LLM

#### Scenario: approve/reject 佔位
- **WHEN** 審查者按下 `approve` 或 `reject`
- **THEN** 頁面顯示「Gold 歸檔後端於下一階段接上」提示，不呼叫任何後端、不改動資料
