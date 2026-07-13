## 1. 修改 _render_side_bar()

- [x] 1.1 在 `dashboard_ui/utils/ui_elements.py` 的 `_render_side_bar()` 末尾，於 OneNote Review 連結之後新增 `st.sidebar.page_link("pages/ai_knowledge_agent.py", label="🤖 AI Knowledge Agent")`

## 2. 建立 Page 3 骨架

- [x] 2.1 新建 `dashboard_ui/pages/ai_knowledge_agent.py`，設定 `st.set_page_config`（title="AI Knowledge Agent", icon="🤖", layout="wide"）並呼叫 `_render_side_bar()`
- [x] 2.2 在檔案頂部加入 `# TODO: st.login()` placeholder 注解區塊，說明 Google OAuth 尚待設定
- [x] 2.3 匯入所需模組：`uuid`, `os`, `streamlit`, `agents.intent_router_agent`, `agents.rag_agent`, `agents.planning_agent`

## 3. 實作 Session State 初始化

- [x] 3.1 在頁面腳本頂部（`st.set_page_config` 之後）實作 session_state 初始化邏輯：若 `session_id` 不存在則生成 uuid4；初始化 `messages: list = []`、`api_call_count: int = 0`、`planning_map_generated: bool = False`

## 4. 實作側邊欄控制區

- [x] 4.1 在 sidebar 顯示目前 session 的 LLM 呼叫計數（`api_call_count / rate_limit`）
- [x] 4.2 新增「🔄 開新對話」按鈕：點擊後重置 `session_id`（新 uuid4）、清空 `messages`、`api_call_count=0`、`planning_map_generated=False`，並呼叫 `st.rerun()`

## 5. 實作 Rate Limiting

- [x] 5.1 在頁面腳本中讀取環境變數 `AI_AGENT_RATE_LIMIT`（int, fallback=20）作為上限值
- [x] 5.2 在 `chat_input` submit 處理前判斷 `api_call_count >= rate_limit`：若超限則以 `st.warning()` 顯示提示並 `st.stop()`，不進入 agent 流程

## 6. 實作 Agent 工作鏈串接

- [x] 6.1 實作 `handle_user_input(query: str)` 函式（或同等內聯邏輯）：呼叫 `intent_router_agent.route(query, session_id)` 取得 `agent_target`
- [x] 6.2 根據 `agent_target == "rag_agent"` 呼叫 `rag_agent.rag_query(query, session_id)` 並取得 `result`
- [x] 6.3 根據 `agent_target == "planning_agent"` 且 `planning_map_generated == False`，呼叫 `planning_agent.generate_learning_map(query, session_id)`，完成後設 `planning_map_generated = True`
- [x] 6.4 根據 `agent_target == "planning_agent"` 且 `planning_map_generated == True`，呼叫 `planning_agent.refine_learning_map(query, session_id)`
- [x] 6.5 不論哪個 agent，成功回傳後 `api_call_count += 1`

## 7. 實作對話顯示

- [x] 7.1 實作「重播歷史訊息」邏輯：頁面渲染時遍歷 `st.session_state["messages"]`，以 `st.chat_message(role)` 顯示 content 與 sources
- [x] 7.2 使用者送出訊息後，立即將 `{role: "user", content: query}` append 至 `messages` 並渲染為 `st.chat_message("user")`
- [x] 7.3 agent 回傳後，將 `{role: "assistant", content: result["answer"], sources: result["sources"], agent_type: agent_target}` append 至 `messages` 並渲染為 `st.chat_message("assistant")`
- [x] 7.4 若 `sources` 非空，在 assistant 氣泡下方以 `st.expander("📎 來源筆記")` 顯示清單（`file_name | section | score`）

## 8. 錯誤處理

- [x] 8.1 在 agent 呼叫外層加 `try/except Exception`，捕捉後以 `st.error()` 顯示錯誤訊息，不將失敗訊息存入 `messages`，且不遞增 `api_call_count`
