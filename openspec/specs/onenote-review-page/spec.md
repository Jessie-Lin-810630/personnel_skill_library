# onenote-review-page Specification

## Purpose
TBD - normalized from legacy archived delta format.
## Requirements
### Requirement: Google OIDC login gate

- 未登入的使用者 SHALL 看到 hero 版面與登入入口。
- 登入使用 Streamlit 內建的 OIDC 登入（`st.login()`），以 Google 為 OIDC provider。
- 登入成功後，系統 SHALL 以 `st.user.email` 對照 `USER_ALLOWLIST` 決定角色並寫入 `st.session_state.role`。
- 不在 `USER_ALLOWLIST` 內的 email 不可 (MUST NOT) 進入本頁，`Guest` 務必 (MUST) 明列於 `USER_ALLOWLIST` 中才成立。
- 角色由 `USER_ALLOWLIST` 決定，不另設角色下拉。

#### Scenario: `USER_ALLOWLIST` 內的帳號取得審查角色
- **WHEN** 使用者以 `USER_ALLOWLIST` 內的 Google 帳號完成登入
- **THEN** 頁面顯示完整多版本審查介面，`st.session_state.role` 設為 `USER_ALLOWLIST` 中對應的角色

#### Scenario: `USER_ALLOWLIST` 內的 Guest 帳號可瀏覽但不寫入
- **WHEN** 使用者以 `USER_ALLOWLIST` 中角色為 `Guest` 的 Google 帳號完成登入
- **THEN** 頁面顯示審查介面，`st.session_state.role` 設為 `Guest`，approve 與 reject 只更新畫面而不呼叫端點

#### Scenario: `USER_ALLOWLIST` 外的帳號不得進入
- **WHEN** 使用者以 `USER_ALLOWLIST` 外的 Google 帳號完成登入
- **THEN** 頁面顯示未授權畫面與登出按鈕並停止渲染，不讀取 `onenote_note_metadata`，不呼叫任何端點

#### Scenario: 未登入不得進入
- **WHEN** 使用者尚未登入
- **THEN** 只顯示 hero 版面與登入入口，頁面停止渲染其餘內容

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

- 頁面底部 SHALL 提供「Approve」「Reject」「Regenerate」按鈕。
- Approve/Reject 以 `POST {GOLD_ENDPOINT_URL}` 帶 `{page_id, dt, action}`（approve 歸檔、reject 標記 review_closed 並回寫 md_frontmatter）。
- Regenerate 以 `POST {SILVER_ENDPOINT_URL}` 帶 `trigger=regenerate`（受 quota）。
- 三個呼叫成功後 SHALL 清版本清單快取並重載。
- 三個呼叫 SHALL 在 `X-User-Token` header 帶入 dashboard 為登入者簽發的短效 JWT。
- `Authorization` header 維持帶 dashboard runtime service account 的 ID token。
- `role` 不再放進 request body，改由端點自 token 推導。

#### Scenario: Approve triggers gold endpoint
- **WHEN** 使用者對已生成 md 的版本按下 Approve
- **THEN** 送出 `POST /archive` 帶 `action="approved"` 與 `X-User-Token`，成功後該版翻為已歸檔

#### Scenario: Reject triggers gold endpoint
- **WHEN** 使用者按下 Reject
- **THEN** 送出 `POST /archive` 帶 `action="rejected"` 與 `X-User-Token`，該版標記 review_closed 並從版本清單消失

#### Scenario: Regenerate triggers silver endpoint
- **WHEN** 使用者對品質不佳的版本按下 Regenerate
- **THEN** 送出 `POST /enrich` 帶 `trigger="regenerate"` 與 `X-User-Token`，未達 quota 上限時重生 md 並重渲染

#### Scenario: Guest 按下按鈕不呼叫端點
- **WHEN** `Guest` 角色的使用者按下 Approve 或 Reject
- **THEN** 頁面只呈現操作成功的畫面並停用該版本的按鈕，不送出請求，MongoDB 與 GCS 皆無寫入

#### Scenario: Guest 不觸發語意擴充生成
- **WHEN** `Guest` 角色的使用者選到一個尚未生成 md 的版本
- **THEN** 頁面顯示尚未生成的提示，不呼叫 Silver 端點，不消耗模型配額

#### Scenario: Guest 的重試生成按鈕停用
- **WHEN** `Guest` 角色的使用者檢視任一版本
- **THEN** 審查按鈕列的重試生成按鈕為停用狀態並附說明，按不下去也不會送出請求

#### Scenario: Guest 的生成失敗重試按鈕停用
- **WHEN** `Guest` 角色的使用者檢視一個曾經生成失敗的版本，右欄出現失敗訊息與重試按鈕
- **THEN** 該重試按鈕亦為停用狀態並附說明，不會清掉失敗記號也不會重新觸發生成
