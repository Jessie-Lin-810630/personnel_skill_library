# Spec Delta

## Purpose

規範審查者的身分從登入、轉傳到後端驗證的完整行為，讓 Silver 與 Gold 端點判斷審核者身分時依據一個經過驗簽的短效 JWT，而不是呼叫端在 request body 自行填寫的字串。

## ADDED Requirements

### Requirement: Dashboard 以 Google 帳號登入

- Dashboard SHALL 使用 Streamlit 內建的 OIDC 登入（`st.login()` / `st.user`），以 Google 為 OIDC provider，discovery 網址為 `https://accounts.google.com/.well-known/openid-configuration`，取代以環境變數帳密比對的登入方式。
- 未登入的使用者不可 (MUST NOT) 進入 OneNote 審查頁或 AI agent 頁。
- 完成登入僅代表該 Google 帳號真實存在，不代表取得存取權；是否放行 SHALL 由 `USER_ALLOWLIST` 裁決。
- 登入成功後，系統 SHALL 從 `st.user` 取得經 Google 驗證的 email。
- `st.user` 只提供解碼後的 claims，不提供原始 ID token，因此系統不可 (MUST NOT) 依賴轉傳原始 ID token 來傳遞身分。

#### Scenario: 未登入的使用者被擋下
- **WHEN** 使用者直接開啟 OneNote 審查頁或 AI agent 頁且尚未登入
- **THEN** 頁面顯示登入入口並停止渲染其餘內容，不讀取 MongoDB，也不呼叫任何端點

#### Scenario: 登入成功取得身分
- **WHEN** 使用者完成 Google 帳號登入
- **THEN** 系統取得 `st.user.email`，頁面繼續渲染

### Requirement: `USER_ALLOWLIST` 決定能否進入與角色

- 系統 SHALL 以登入者的 email 對照 `USER_ALLOWLIST` 決定角色，`USER_ALLOWLIST` 是唯一的授權依據。
- 列在 `USER_ALLOWLIST` 內的 email 取得該筆設定的角色；不在其中的 email 不可 (MUST NOT) 進入 OneNote 審查頁或 AI agent 頁。
- `Guest` 務必 (MUST) 明列於 `USER_ALLOWLIST` 中才成立，不可 (MUST NOT) 作為查無結果時的預設角色。
- `USER_ALLOWLIST` 未設定或無法解析時，系統 SHALL 拒絕所有帳號進入，不可 (MUST NOT) 退回 `Guest`。
- OAuth 同意畫面的發布狀態與測試使用者名單不可 (MUST NOT) 被當成擋人的機制（理由見 `design.md` 決策 8）。

#### Scenario: `USER_ALLOWLIST` 內的 email 取得對應角色
- **WHEN** 登入者的 email 存在於 `USER_ALLOWLIST`
- **THEN** `st.session_state.role` 設為 `USER_ALLOWLIST` 中對應的角色，頁面依該角色渲染

#### Scenario: `USER_ALLOWLIST` 外的 email 被拒絕進入
- **WHEN** 登入者的 email 不在 `USER_ALLOWLIST`
- **THEN** 頁面顯示未授權畫面與登出按鈕並停止渲染其餘內容，不讀取 MongoDB，不呼叫任何端點，也不觸發任何 LLM 呼叫

#### Scenario: `USER_ALLOWLIST` 無法解析時一律拒絕
- **WHEN** 環境變數 `USER_ALLOWLIST` 未設定、不是合法 JSON，或解析結果不是 JSON object
- **THEN** 系統記一筆警告並拒絕所有帳號進入，包含原本列在 `USER_ALLOWLIST` 內的帳號

#### Scenario: `USER_ALLOWLIST` 內的 Guest 可瀏覽但不可寫入
- **WHEN** 登入者的 email 在 `USER_ALLOWLIST` 中對應的角色為 `Guest`
- **THEN** 頁面可瀏覽、AI agent 可正常對話，但 approve 與 reject 不呼叫任何端點，MongoDB 與 GCS 皆無寫入

### Requirement: 審查者身分以獨立 header 轉傳

- Dashboard 呼叫 Silver 與 Gold 端點時 SHALL 在 `X-User-Token` header 帶入一個短效 JWT。
- 該 JWT SHALL 由 dashboard 以自己的 Cloud Run runtime service account 私鑰簽發，內容包含簽發者、接收者、登入者 email 與到期時間。
- 該 JWT 不可 (MUST NOT) 夾帶角色。角色一律由端點自行對照 `USER_ALLOWLIST` 推導，簽進 token 會變成沒人讀的欄位，也會讓人誤以為端點採用呼叫端指定的角色。
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

- Silver 與 Gold 服務端點 SHALL 以 dashboard runtime service account 的公開金鑰驗證 `X-User-Token` 的簽章、簽發者、接收者與有效期限，取出 email 後對照 `USER_ALLOWLIST` 推導角色。
- 簽發者的 service account email SHALL 由環境變數 `TOKEN_ISSUER_SA` 提供，公開金鑰向 Google 為該 service account 公開的 JWK 端點取得，不可 (MUST NOT) 寫死在程式碼裡。
- 角色對照表 SHALL 由環境變數 `USER_ALLOWLIST` 提供，內容為 email 對應角色名稱的 JSON object。
- 端點不能 (MUST NOT) 從 request body 讀取角色。
- 推導出的角色為 `Guest` 時，端點 SHALL 拒絕該請求。
- 取不到 JWK 端點時 SHALL 回 `503`，不可 (MUST NOT) 回 `401`，因為那是服務對外連線的問題而非 token 有問題，回 `401` 會讓呼叫端誤以為要重新登入。
- 驗證邏輯 SHALL 集中在 `task07_common/auth.py`，Silver 與 Gold 兩個服務以 FastAPI dependency 掛載，但仍維持各自獨立部署。

#### Scenario: token 有效且在 `USER_ALLOWLIST` 內
- **WHEN** 請求帶的 `X-User-Token` 通過驗簽，且 email 在 `USER_ALLOWLIST` 內。
- **THEN** 端點以 `USER_ALLOWLIST` 對應的角色繼續處理請求，該角色寫入 audit log 的 `reviewed_by_role`。並回傳 `200`。

#### Scenario: 缺少 token
- **WHEN** 請求未帶 `X-User-Token`。
- **THEN** 端點回 `401`，不呼叫 Silver 服務本體或 Gold Load，MongoDB 與 GCS 皆無寫入。

#### Scenario: token 驗簽失敗或過期
- **WHEN** `X-User-Token` 簽章不符、簽發者不符或已過期。
- **THEN** 端點回 `401`，不呼叫 Silver 服務本體或 Gold Load。

#### Scenario: token 有效但不在 `USER_ALLOWLIST` 內
- **WHEN** `X-User-Token` 通過驗簽，但 email 不在 `USER_ALLOWLIST` 內。
- **THEN** 端點回 `403`，不呼叫 Silver 服務本體或 Gold Load。

#### Scenario: token 有效但角色為 Guest
- **WHEN** `X-User-Token` 通過驗簽，email 在 `USER_ALLOWLIST` 內且對應角色為 `Guest`。
- **THEN** 端點回 `403`，不呼叫 Silver 服務本體或 Gold Load。

#### Scenario: 取不到驗簽金鑰
- **WHEN** `X-User-Token` 本身合法，但端點連不上 Google 的 JWK 端點，無法取得公開金鑰。
- **THEN** 端點回 `503` 並在日誌記下取金鑰失敗，不呼叫 Silver 服務本體或 Gold Load，呼叫端可稍後重試同一張 token。
