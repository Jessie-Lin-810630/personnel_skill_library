# Spec Delta

## ADDED Requirements

### Requirement: Login gate on AI agent page

- AI agent 頁 SHALL 在頁面頂部加入登入 gate，使用 Streamlit 內建的 OIDC 登入（`st.login()`），以 Google 為 OIDC provider。
- 未登入的使用者不可 (MUST NOT) 看到對話介面，也不可 (MUST NOT) 觸發任何 LLM 呼叫或 MongoDB 查詢。
- 本頁不呼叫 Silver 或 Gold 端點，因此不可 (MUST NOT) 轉傳 `X-User-Token`。
- 角色改由 `USER_ALLOWLIST` 對照登入者 email 推導，取代原本以環境變數帳密比對的方式。既有的角色差異維持不變：`Guest` 角色在來源清單中看不到 vector 與 rerank 分數。
- 不在 `USER_ALLOWLIST` 內的 email 不可 (MUST NOT) 進入本頁，也不可 (MUST NOT) 觸發任何 LLM 呼叫。
- `USER_ALLOWLIST` 內的 `Guest` SHALL 擁有與其他角色相同的對話權限，包含 intent router、RAG 與學習路徑規劃。

#### Scenario: 未登入不得進入
- **WHEN** 使用者開啟 AI agent 頁且尚未登入
- **THEN** 頁面只顯示登入入口，不渲染對話介面，`session_id` 不初始化，不呼叫 agent

#### Scenario: 登入後可正常對話
- **WHEN** `USER_ALLOWLIST` 內的使用者完成登入
- **THEN** 頁面渲染對話介面，既有的 session、rate limit 與 intent router 行為不變

#### Scenario: `USER_ALLOWLIST` 外的帳號不得進入
- **WHEN** 使用者以 `USER_ALLOWLIST` 外的 Google 帳號完成登入
- **THEN** 頁面顯示未授權畫面與登出按鈕並停止渲染，`session_id` 不初始化，不呼叫 agent，不查 MongoDB

#### Scenario: 登出後回到登入入口
- **WHEN** 已登入的使用者登出
- **THEN** 頁面回到登入入口，對話紀錄與 `session_id` 清空

## REMOVED Requirements

### Requirement: Auth placeholder for future st.login()

**Reason**: 本次已實際接上以 Google 為 provider 的 OIDC 登入，預留位置的注解區塊不再需要。

**Migration**: 由本 delta 的 `Requirement: Login gate on AI agent page` 取代。實作時移除檔案頂部的
`# TODO: st.login()` 注解區塊，以及該頁與審查頁重複的一整套帳密登入（`CREDENTIALS` 比對、hero 版面、
`st.session_state.authenticated` 判斷），改呼叫共用的 `dashboard_ui/utils/auth_gate.py`。
