# Spec Delta

## ADDED Requirements

### Requirement: Google OIDC login gate

- 未登入的使用者 SHALL 看到 hero 版面與登入入口。
- 登入使用 Streamlit 內建的 OIDC 登入（`st.login()`），以 Google 為 OIDC provider。
- 登入成功後，系統 SHALL 以 `st.user.email` 對照允許清單決定角色並寫入 `st.session_state.role`。
- 清單外的 email 一律取得 `Guest` 角色，仍可進入頁面瀏覽。
- 角色由允許清單決定，不另設角色下拉。

#### Scenario: 允許清單內的帳號取得審查角色
- **WHEN** 使用者以允許清單內的 Google 帳號完成登入
- **THEN** 頁面顯示完整多版本審查介面，`st.session_state.role` 設為清單中對應的角色

#### Scenario: 允許清單外的帳號落到 Guest
- **WHEN** 使用者以允許清單外的 Google 帳號完成登入
- **THEN** 頁面顯示審查介面，`st.session_state.role` 設為 `Guest`，approve 與 reject 只更新畫面而不呼叫端點

#### Scenario: 未登入不得進入
- **WHEN** 使用者尚未登入
- **THEN** 只顯示 hero 版面與登入入口，頁面停止渲染其餘內容

## MODIFIED Requirements

### Requirement: Approve and Reject buttons

- 頁面底部 SHALL 提供「Approve」「Reject」「Regenerate」按鈕。
- Approve/Reject 以 `POST {GOLD_ENDPOINT_URL}` 帶 `{page_id, dt, action}`（approve 歸檔、reject 標記 review_closed 並回寫 md_frontmatter）。
- Regenerate 以 `POST {SILVER_ENDPOINT_URL}` 帶 `trigger=regenerate`（受 quota）。
- 三個呼叫成功後 SHALL 清版本清單快取並重載。
- 三個呼叫 SHALL 在 `X-Reviewer-Token` header 帶入 dashboard 為登入者簽發的短效 JWT。
- `Authorization` header 維持帶 dashboard runtime service account 的 ID token。
- `role` 不再放進 request body，改由端點自 token 推導。

#### Scenario: Approve triggers gold endpoint
- **WHEN** 使用者對已生成 md 的版本按下 Approve
- **THEN** 送出 `POST /archive` 帶 `action="approved"` 與 `X-Reviewer-Token`，成功後該版翻為已歸檔

#### Scenario: Reject triggers gold endpoint
- **WHEN** 使用者按下 Reject
- **THEN** 送出 `POST /archive` 帶 `action="rejected"` 與 `X-Reviewer-Token`，該版標記 review_closed 並從版本清單消失

#### Scenario: Regenerate triggers silver endpoint
- **WHEN** 使用者對品質不佳的版本按下 Regenerate
- **THEN** 送出 `POST /enrich` 帶 `trigger="regenerate"` 與 `X-Reviewer-Token`，未達 quota 上限時重生 md 並重渲染

#### Scenario: Guest 按下按鈕不呼叫端點
- **WHEN** `Guest` 角色的使用者按下 Approve 或 Reject
- **THEN** 頁面只呈現操作成功的畫面並停用該版本的按鈕，不送出請求，MongoDB 與 GCS 皆無寫入

## REMOVED Requirements

### Requirement: Demo login gate

**Reason**: 登入方式改為以 Google 為 provider 的 OIDC 登入，以環境變數帳密比對決定角色的做法連同其
`ROLE_ML_*` / `ROLE_OWNER_*` / `ROLE_SENIOR_*` 六個變數一併退場。

**Migration**: 由本 delta 的 `Requirement: Google OIDC login gate` 取代。原本以帳密區分的三個角色
改為寫進 email 允許清單，實作時移除 `CREDENTIALS` 比對與相關環境變數。
