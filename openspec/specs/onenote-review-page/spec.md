# onenote-review-page Specification

## Purpose
TBD - normalized from legacy archived delta format.
## Requirements
### Requirement: Demo login gate
未通過驗證的使用者 SHALL 看到 hero 版面與帳號／密碼登入表單；帳密與 `ROLE_ML_*` / `ROLE_OWNER_*` /
`ROLE_SENIOR_*` 環境變數比對，命中則以對應角色登入（`st.session_state.authenticated=True`、
`st.session_state.role=<角色>`），不符則顯示錯誤且頁面停止渲染。角色由登入帳密決定，不再另設角色下拉。

#### Scenario: Correct credential unlocks the page
- **WHEN** 使用者輸入與某角色相符的帳號密碼並送出
- **THEN** 頁面顯示完整多版本審查介面，`st.session_state.role` 設為對應角色

#### Scenario: Wrong credential blocks page
- **WHEN** 使用者輸入不存在的帳號或錯誤密碼
- **THEN** 顯示「帳號或密碼錯誤」提示，頁面停止渲染

### Requirement: Three-level note selector
頁面上方 SHALL 提供筆記本 → 章節 → 頁面三層下拉選擇器，資料來源改為 `onenote_note_metadata`
collection（透過 aggregation 過濾 `status=review_closed`（含 rejected 與 overwritten）並僅保留 `dt≥最後歸檔日` 的可審閱版本）。
選定頁面後 SHALL 以 `dt=` 圓鈕列出同名筆記的多個版本供切換（依 `html_downloaded_at` 排序）。

#### Scenario: Notebook/section/page filters cascade
- **WHEN** 使用者依序選擇筆記本與章節
- **THEN** 章節、頁面下拉逐層篩選；選定頁面後顯示該頁可審閱的 `dt=` 版本圓鈕

#### Scenario: Rejected and superseded versions hidden
- **WHEN** 某版本 `status=review_closed`（`review_result=rejected` 或 `overwritten`），或其 `dt` 早於該頁最後歸檔日
- **THEN** 該版本不出現在版本清單

### Requirement: Status badge at top
選定版本後，頁面 SHALL 依「該選定版本自己」的狀態呈現；當選定版本 `status=archived` 時顯示唯讀提示並
停用其操作按鈕，不因同名另一版已歸檔而影響本版。

#### Scenario: Archived version is read-only
- **WHEN** 選定版本 `status=archived`
- **THEN** 顯示「此版本已歸檔」提示，該版 approve/reject/regenerate 停用；同名其他可審閱版本按鈕維持可用

### Requirement: Side-by-side HTML and MD view
選定版本後，頁面 SHALL 左欄渲染 bronze html、右欄渲染 silver md，兩者皆自 `gs://` URI（`html_path`、
`md_path`）讀取，內嵌圖片以 base64 data URI 替換 `_images/` 路徑。當選定版本 `md_path=null` 時，頁面
SHALL `POST` 呼叫 Silver enrich 端點（`SILVER_ENDPOINT_URL`）即時生成 md 後渲染；已生成則直接讀 GCS。

#### Scenario: On-demand generate when md missing
- **WHEN** 使用者切到一個 `md_path=null` 的版本
- **THEN** 頁面呼叫 Silver 端點生成 md，成功後渲染右欄；端點失敗/斷路時顯示提示且左欄 html 仍正常

#### Scenario: Cache hit on generated version
- **WHEN** 選定版本 `md_path != null`
- **THEN** 直接讀 GCS 既有 md 渲染，不呼叫端點

### Requirement: Approve and Reject buttons
頁面底部 SHALL 提供「Approve」「Reject」「Regenerate」按鈕。Approve/Reject 以 `POST {GOLD_ENDPOINT_URL}`
帶 `{page_id, dt, role, action}`（approve 歸檔、reject 標記 review_closed 並回寫 md_frontmatter）；
Regenerate 以 `POST {SILVER_ENDPOINT_URL}` 帶 `trigger=regenerate`（受 quota）。成功後清版本清單快取並重載。

#### Scenario: Approve triggers gold endpoint
- **WHEN** 使用者對已生成 md 的版本按下 Approve
- **THEN** 送出 `POST /archive` 帶 `action="approved"`，成功後該版翻為已歸檔

#### Scenario: Reject triggers gold endpoint
- **WHEN** 使用者按下 Reject
- **THEN** 送出 `POST /archive` 帶 `action="rejected"`，該版標記 review_closed 並從版本清單消失

#### Scenario: Regenerate triggers silver endpoint
- **WHEN** 使用者對品質不佳的版本按下 Regenerate
- **THEN** 送出 `POST /enrich` 帶 `trigger="regenerate"`，未達 quota 上限時重生 md 並重渲染
