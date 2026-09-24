# Spec Delta

## Purpose

規範審查者的身分從登入、轉傳到後端驗證的完整行為，讓 Silver 與 Gold 端點判斷審核者身分時依據一個經過驗簽的短效 JWT，而不是呼叫端在 request body 自行填寫的字串。

## ADDED Requirements

### Requirement: Dashboard 以 Google 帳號登入

- Dashboard SHALL 使用 Streamlit 內建的 OIDC 登入（`st.login()` / `st.user`），以 Google 為 OIDC provider，discovery 網址為 `https://accounts.google.com/.well-known/openid-configuration`，取代以環境變數帳密比對的登入方式。
- 未登入的使用者不可 (MUST NOT) 進入 OneNote 審查頁或 AI agent 頁。
- 登入成功後，系統 SHALL 從 `st.user` 取得經 Google 驗證的 email。
- `st.user` 只提供解碼後的 claims，不提供原始 ID token，因此系統不可 (MUST NOT) 依賴轉傳原始 ID token 來傳遞身分。

#### Scenario: 未登入的使用者被擋下
- **WHEN** 使用者直接開啟 OneNote 審查頁或 AI agent 頁且尚未登入
- **THEN** 頁面顯示登入入口並停止渲染其餘內容，不讀取 MongoDB，也不呼叫任何端點

#### Scenario: 登入成功取得身分
- **WHEN** 使用者完成 Google 帳號登入
- **THEN** 系統取得 `st.user.email`，頁面繼續渲染

### Requirement: 允許清單決定角色

- 系統 SHALL 以登入者的 email 對照允許清單決定角色。
- 清單內的 email 取得該筆設定的審查角色，清單外的 email 一律取得 `Guest` 角色。
- OAuth 同意畫面 SHALL 維持 External 與 Testing 狀態，並以測試使用者名單擋下不允許登入的帳號，讓應用程式端的清單比對成為第二道檢查而非唯一檢查。

#### Scenario: 清單內的 email 取得審查角色
- **WHEN** 登入者的 email 存在於允許清單
- **THEN** `st.session_state.role` 設為清單中對應的角色，頁面提供完整審查功能

#### Scenario: 清單外的 email 落到 Guest
- **WHEN** 登入者的 email 不在允許清單
- **THEN** `st.session_state.role` 設為 `Guest`，頁面可瀏覽但 approve 與 reject 不呼叫任何端點，MongoDB 與 GCS 皆無寫入

### Requirement: 審查者身分以獨立 header 轉傳

- Dashboard 呼叫 Silver 與 Gold 端點時 SHALL 在 `X-User-Token` header 帶入一個短效 JWT。
- 該 JWT SHALL 由 dashboard 以自己的 Cloud Run runtime service account 私鑰簽發，內容至少包含登入者 email 與到期時間。
- 簽發 SHALL 透過 GCP IAM Credentials 的 `signJwt`，私鑰不可 (MUST NOT) 以檔案或環境變數形式存在於 dashboard 容器內。
- `Authorization` header 務必 (MUST) 維持給 dashboard runtime service account 的 ID token 使用。
- 該 header 由 Cloud Run 的 IAM 檢查，不會傳到應用程式，因此不可 (MUST NOT) 用來傳遞使用者身分。

#### Scenario: 呼叫端點時兩個 header 並存
- **WHEN** 已登入且非 Guest 的使用者按下 approve、reject 或 regenerate。
- **THEN** 送出的請求同時帶 `Authorization`（service account ID token，供 Cloud Run IAM 檢查）與 `X-User-Token`（dashboard 簽發的短效 JWT）。

#### Scenario: Guest 不送出請求
- **WHEN** Guest 角色的使用者按下 approve 或 reject。
- **THEN** 頁面只更新畫面狀態，不送出任何請求，因此不產生 `X-User-Token`。

### Requirement: 端點驗證 token 並推導角色

- Silver 與 Gold 服務端點 SHALL 以 dashboard runtime service account 的公開金鑰驗證 `X-User-Token` 的簽章、簽發者、接收者與有效期限，取出 email 後對照允許清單推導角色。
- 簽發者的 service account email SHALL 由環境變數 `TOKEN_ISSUER_SA` 提供，公開金鑰向 Google 為該 service account 公開的 JWK 端點取得，不可 (MUST NOT) 寫死在程式碼裡。
- 角色對照表 SHALL 由環境變數 `USER_ALLOWLIST` 提供，內容為 email 對應角色名稱的 JSON object。
- 端點不能 (MUST NOT) 從 request body 讀取角色。
- 取不到 JWK 端點時 SHALL 回 `503`，不可 (MUST NOT) 回 `401`，因為那是服務對外連線的問題而非 token 有問題，回 `401` 會讓呼叫端誤以為要重新登入。
- 驗證邏輯 SHALL 集中在 `task07_common/auth.py`，Silver 與 Gold 兩個服務以 FastAPI dependency 掛載，但仍維持各自獨立部署。

#### Scenario: token 有效且在允許清單內
- **WHEN** 請求帶的 `X-User-Token` 通過驗簽，且 email 在允許清單內。
- **THEN** 端點以清單對應的角色繼續處理請求，該角色寫入 audit log 的 `reviewed_by_role`。並回傳 `200`。

#### Scenario: 缺少 token
- **WHEN** 請求未帶 `X-User-Token`。
- **THEN** 端點回 `401`，不呼叫 Silver 服務本體或 Gold Load，MongoDB 與 GCS 皆無寫入。

#### Scenario: token 驗簽失敗或過期
- **WHEN** `X-User-Token` 簽章不符、簽發者不符或已過期。
- **THEN** 端點回 `401`，不呼叫 Silver 服務本體或 Gold Load。

#### Scenario: token 有效但不在允許清單內
- **WHEN** `X-User-Token` 通過驗簽，但 email 不在允許清單內（推導為 `Guest`）。
- **THEN** 端點回 `403`，不呼叫 Silver 服務本體或 Gold Load。

#### Scenario: 取不到驗簽金鑰
- **WHEN** `X-User-Token` 本身合法，但端點連不上 Google 的 JWK 端點，無法取得公開金鑰。
- **THEN** 端點回 `503` 並在日誌記下取金鑰失敗，不呼叫 Silver 服務本體或 Gold Load，呼叫端可稍後重試同一張 token。
