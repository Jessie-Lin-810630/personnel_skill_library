## ADDED Requirements

### Requirement: Username and password login form
登入頁面 SHALL 提供 username 與 password 兩個輸入欄位，以及「登入」按鈕。密碼欄位 SHALL 以遮罩方式顯示（`type="password"`）。

#### Scenario: Correct credentials unlock the page with correct role
- **WHEN** 使用者輸入符合某組角色帳密的 username 與 password 並送出
- **THEN** 頁面顯示完整審核介面，`st.session_state.role` 設為對應角色

#### Scenario: Wrong credentials block page
- **WHEN** 使用者輸入不符合任一組帳密的組合
- **THEN** 顯示「帳號或密碼錯誤」提示，頁面停止渲染

#### Scenario: Empty credentials block page
- **WHEN** 使用者未輸入 username 或 password 即送出
- **THEN** 顯示「請輸入帳號與密碼」提示，不嘗試比對

---

### Requirement: Read-only role display with logout button
登入後 SHALL 以唯讀方式顯示目前角色，並提供「登出」按鈕。按下登出 SHALL 清除 `st.session_state.authenticated` 與 `st.session_state.role` 並刷新頁面回到登入畫面。

#### Scenario: Role label shows current role
- **WHEN** 使用者以「Note Owner」帳密登入
- **THEN** 頁面顯示「目前角色：Note Owner」唯讀標籤

#### Scenario: Logout clears session and returns to login
- **WHEN** 使用者按下「登出」按鈕
- **THEN** session 清除，頁面回到 username/password 登入表單

## MODIFIED Requirements

### Requirement: Demo login gate
未通過驗證的使用者 SHALL 看到 username + password 輸入框（非單一密碼框）；比對三組角色帳密，符合任一組則 `st.session_state.authenticated = True` 並帶入對應 `role`。不符合則顯示通用錯誤訊息，頁面停止渲染。

#### Scenario: Correct password unlocks the page
- **WHEN** 使用者輸入正確的 username 與 password 組合
- **THEN** 頁面顯示完整審核介面，角色自動設定為對應組別

#### Scenario: Wrong password blocks page
- **WHEN** 使用者輸入錯誤的 username 或 password
- **THEN** 顯示「帳號或密碼錯誤」提示，頁面停止渲染
