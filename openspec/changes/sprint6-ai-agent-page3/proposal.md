## Why

Sprints 1–5 已完成 Tools 層（vector search、chat history）、RAG Agent、Intent Router、Planning Agent 的實作，但目前沒有 UI 串接點，使用者無法與這三個 agent 互動。Sprint 6 需要建立 Streamlit Page 3，把工作鏈接通，讓 AI Knowledge Agent 功能對外可用。

## What Changes

- 新建 `dashboard_ui/pages/ai_knowledge_agent.py`（Page 3）：單一對話框入口，使用 `st.chat_input` / `st.chat_message` 呈現對話
- 實作 Session 管理：uuid4 `session_id` + 側邊欄「開新對話」按鈕，點擊後清空對話顯示、重置計數器與 planning 狀態
- 實作 Rate Limiting：`st.session_state` 記錄 LLM API 呼叫次數，超過 20 次後拒絕繼續送出並顯示提示
- 串接 Agent 工作鏈：`intent_router_agent.route()` → `rag_agent.rag_query()` 或 `planning_agent.generate_learning_map()` / `refine_learning_map()`
- Planning Agent 路由邏輯：以 `st.session_state["planning_map_generated"]` flag 判斷，同一 session 首次規劃呼叫 `generate_learning_map()`，後續追問呼叫 `refine_learning_map()`
- 來源顯示：agent 回應下方以 expander 展示 sources 清單（file_name + section + score）
- `st.login()` Google OAuth 留 TODO placeholder（credentials 尚未建立）
- 更新 `dashboard_ui/utils/ui_elements.py` 的 `_render_side_bar()`，新增 Page 3 的側邊欄連結

## Capabilities

### New Capabilities

- `ai-knowledge-agent-page`：Page 3 完整實作，包含 chat UI、session 管理、rate limiting、agent 工作鏈串接與來源顯示

### Modified Capabilities

- `dashboard-navigation`：`_render_side_bar()` 新增 AI Knowledge Agent 頁面連結（繼 OneNote Review 之後）

## Impact

- **新建檔案**：`dashboard_ui/pages/ai_knowledge_agent.py`
- **修改檔案**：`dashboard_ui/utils/ui_elements.py`（`_render_side_bar()`）
- **依賴模組**（已實作，不修改）：`dashboard_ui/agents/intent_router_agent.py`、`dashboard_ui/agents/rag_agent.py`、`dashboard_ui/agents/planning_agent.py`、`dashboard_ui/agent_tools/chat_history.py`、`dashboard_ui/agent_tools/query_with_vector_search.py`
- **外部依賴**：`google-genai` SDK（Vertex AI）、MongoDB Atlas（已在環境中配置）
