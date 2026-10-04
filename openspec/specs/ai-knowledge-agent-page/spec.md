# ai-knowledge-agent-page Specification

## Purpose
TBD - created by archiving change sprint6-ai-agent-page3. Update Purpose after archive.
## Requirements

### Requirement: Chat interface renders conversation
Page 3 (`ai_knowledge_agent.py`) SHALL 提供 `st.chat_input` 輸入框與 `st.chat_message` 氣泡列表，讓使用者以對話形式與 AI Knowledge Agent 互動。

#### Scenario: User submits a query
- **WHEN** 使用者在 chat input 欄位輸入文字並按 Enter
- **THEN** 使用者訊息立即以 `user` 氣泡顯示在對話區，接著 agent 回應以 `assistant` 氣泡顯示

#### Scenario: Page loads with no messages
- **WHEN** 使用者首次開啟 Page 3（或重整頁面）
- **THEN** 對話區為空，僅顯示 chat input 欄位

---

### Requirement: Sources displayed under agent response
當 agent 回傳非空的 `sources` 清單時，Page 3 SHALL 在回應氣泡下方顯示可展開的「📎 來源筆記」欄位，內含每筆來源的 `file_name`、`section`、`score`。RAG agent 回傳的 `answer` 正文 SHALL NOT 包含由模型自行列出的來源清單，來源資訊只透過「📎 來源筆記」呈現，使同一則回應中的來源只出現一次。

#### Scenario: Agent returns sources
- **WHEN** `rag_query()` 或 `generate_learning_map()` / `refine_learning_map()` 回傳非空 `sources`
- **THEN** 回應氣泡下方顯示「📎 來源筆記」expander，展開後列出各 source 的 file_name、section、score

#### Scenario: Agent returns no sources
- **WHEN** agent 回傳空 `sources`（例如向量搜尋無結果）
- **THEN** 回應氣泡下方不顯示 expander

#### Scenario: RAG answer omits source list
- **WHEN** 使用者在新對話中提出筆記查詢，`rag_query()` 檢索到 chunk 並回傳模型生成的 `answer`
- **THEN** `answer` 正文不以「來源：」開頭的段落列出檔案名稱與章節，回應氣泡中的來源只出現在「📎 來源筆記」

---

### Requirement: Session is identified by uuid4 session_id
Page 3 SHALL 在 `st.session_state` 中維護一個 `session_id`（uuid4 字串），初始化時自動生成，並在每次呼叫 agent 時傳入，以對應 MongoDB `chat_history` collection 中的對話紀錄。

#### Scenario: Session initializes on page load
- **WHEN** 使用者首次載入 Page 3（session_state 尚無 session_id）
- **THEN** 自動生成 uuid4 作為 `session_id` 並存入 session_state

#### Scenario: Session persists across reruns within the same tab
- **WHEN** Streamlit rerun 被觸發（例如使用者送出訊息）
- **THEN** `session_id` 維持不變，對話在同一 session 中累積

---

### Requirement: New conversation button resets session
側邊欄 SHALL 提供「🔄 開新對話」按鈕，點擊後重置：`session_id`（重新生成 uuid4）、`messages`（清空）、`api_call_count`（歸零）、`planning_map_generated`（設為 False）。

#### Scenario: User clicks new conversation
- **WHEN** 使用者點擊側邊欄的「🔄 開新對話」按鈕
- **THEN** 對話區清空，session_id 更新為新的 uuid4，LLM 呼叫計數歸零

---

### Requirement: Rate limiting blocks excess LLM calls
Page 3 SHALL 在 `st.session_state["api_call_count"]` 達到上限（預設 20，可由環境變數 `AI_AGENT_RATE_LIMIT` 覆蓋）時，拒絕呼叫 agent 並在頁面上顯示提示訊息，引導使用者點「開新對話」。

#### Scenario: Call count within limit
- **WHEN** `api_call_count` < rate_limit
- **THEN** 使用者送出的訊息正常進入 agent 流程，`api_call_count` 遞增 1

#### Scenario: Call count reaches limit
- **WHEN** `api_call_count` >= rate_limit
- **THEN** agent 不被呼叫，chat input 停用，頁面顯示「已達本次對話 LLM 呼叫上限，請點『開新對話』繼續」

---

### Requirement: Intent router dispatches to correct agent
Page 3 SHALL 對每筆使用者輸入呼叫 `intent_router_agent.route(query, session_id)`，並根據回傳值 (`"rag_agent"` 或 `"planning_agent"`) 分派至對應 agent 函式。

#### Scenario: Router returns rag_agent
- **WHEN** `route()` 回傳 `"rag_agent"`
- **THEN** Page 3 呼叫 `rag_agent.rag_query(query, session_id)`

#### Scenario: Router returns planning_agent (first call)
- **WHEN** `route()` 回傳 `"planning_agent"` 且 `planning_map_generated` 為 False
- **THEN** Page 3 呼叫 `planning_agent.generate_learning_map(query, session_id)`，完成後設 `planning_map_generated = True`

#### Scenario: Router returns planning_agent (follow-up)
- **WHEN** `route()` 回傳 `"planning_agent"` 且 `planning_map_generated` 為 True
- **THEN** Page 3 呼叫 `planning_agent.refine_learning_map(query, session_id)`

---

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
