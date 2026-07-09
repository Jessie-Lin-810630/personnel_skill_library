## Context

Sprints 1–5 已交付：
- `agent_tools/chat_history.py`：`load_chat_history()` / `save_chat_history()`（MongoDB `chat_history` collection）
- `agent_tools/query_with_vector_search.py`：`vector_search()`（MongoDB Atlas Vector Search）
- `agents/rag_agent.py`：`rag_query()`（筆記語意查詢 + 摘要）
- `agents/planning_agent.py`：`generate_learning_map()` / `refine_learning_map()`（學習路徑規劃，多輪）
- `agents/intent_router_agent.py`：`route()`（R1 keyword + R2 LLM 兩段路由）

目前這些模組均已可獨立呼叫（有 `__main__` 手動測試），但尚未有 Streamlit UI 串接。Page 3 是唯一缺口。

## Goals / Non-Goals

**Goals:**
- 在 `dashboard_ui/pages/ai_knowledge_agent.py` 建立 Page 3 的完整 Streamlit UI
- 串接 `route()` → `rag_query()` 或 `generate_learning_map()` / `refine_learning_map()`
- 實作 session_id 生命週期（瀏覽器 tab 層級）與「開新對話」手動重置
- 實作 Rate Limiting（每 session 上限 20 次 LLM 呼叫）
- 顯示 agent 回應來源（expander 形式）
- 新增 sidebar 連結（`_render_side_bar()`）

**Non-Goals:**
- `st.login()` Google OAuth（credentials 尚未建立，留 TODO placeholder）
- 新增或修改任何 agent / tool 模組邏輯
- 聊天訊息向量化或 GCS 寫入（Phase IV 任務）

## Decisions

### D1：Session state 與 MongoDB chat_history 分工

**決策**：Page 3 維護 `st.session_state["messages"]` 純粹用於畫面渲染，不從 MongoDB 重新讀取歷史訊息來恢復畫面。

**理由**：MongoDB chat_history 由 agent 模組負責讀寫，用途是讓 LLM 感知對話脈絡。Page 3 的畫面渲染只需在 Streamlit rerun 之間保持訊息列表，用 session_state 就足夠，不需要多一次 DB query。兩者職責不重疊。

**替代方案**：頁面初始化時從 MongoDB 讀取 history 還原畫面 → 增加 DB query 且對個人使用場景無必要（一個 tab 一個 session，不跨裝置）。

---

### D2：Planning Agent 兩支函式的分派邏輯

**決策**：以 `st.session_state["planning_map_generated"]` boolean flag 判斷：
- `False`（尚未生成）→ `generate_learning_map(query, session_id)`，完成後設為 `True`
- `True`（已有初版）→ `refine_learning_map(followup_query, session_id)`

**理由**：`generate_learning_map()` 與 `refine_learning_map()` 在 log、metadata stage、context 組裝方式上有語意差異，明確區分才能讓 chat_history metadata 正確記錄 `"initial_map"` vs `"refinement"`。用 flag 比查 DB 快，且符合個人單 tab 使用場景。

**替代方案**：每次都呼叫 `generate_learning_map()` → 初版生成 API 每輪重複查詢 top_k=10，成本較高且 metadata 語意不準確。

---

### D3：Rate Limiting 策略

**決策**：`st.session_state["api_call_count"]` 記錄每次使用者送出訊息後實際進入 agent 的次數（即成功觸發 LLM 的次數）。上限 20 次，超過後阻擋送出，顯示提示，引導使用者點「開新對話」繼續。

**理由**：Rate Limiting 在 Page 3 層做最直觀，agent 模組不需要感知計數邏輯。20 次對個人日常使用足夠（約 10–20 輪對話）。

---

### D4：「開新對話」按鈕重置範圍

**決策**：點擊「開新對話」清除：`session_id`（重新生成）、`messages`（清空）、`api_call_count`（歸零）、`planning_map_generated`（設 False）。

**理由**：完整重置讓下一輪對話從乾淨狀態開始，且 planning agent 的多輪脈絡也隨之斷開，符合「手動控制 session 生命週期」的設計決策。

---

### D5：Agent 回應的來源顯示

**決策**：`rag_query()` 與 `generate_learning_map()` / `refine_learning_map()` 均回傳 `{"answer": str, "sources": list}`。若 `sources` 非空，在 answer 氣泡下方以 `st.expander("📎 來源筆記")` 展示清單（file_name + section + score）。

**理由**：expander 預設收合，不干擾主要對話流；展開後提供溯源能力，方便驗證 agent 答案是否有依據。

---

### D6：`_render_side_bar()` 的修改方式

**決策**：直接在 `ui_elements.py` 的 `_render_side_bar()` 末尾追加 `st.sidebar.page_link`，指向 `pages/ai_knowledge_agent.py`，label 為「🤖 AI Knowledge Agent」。不新增函式，手術式修改。

**理由**：沿用 `dashboard-navigation` spec 確立的 sidebar 模式（已有 OneNote Review 的先例），維持一致性。

## Risks / Trade-offs

- **[Risk] Page 3 在頁面重整後 session 丟失** → 這是刻意設計（瀏覽器 tab 層級 session），使用者重整等同於開新對話，符合架構決策。無需 mitigation。
- **[Risk] Rate limit 20 次對某些使用場景不夠** → 可透過環境變數 `AI_AGENT_RATE_LIMIT`（預設 20）讓未來可調整，page 讀取時 fallback 到 20。
- **[Risk] 兩個 agent 的 `_get_genai_client()` 各自初始化，每次呼叫都重新 build credentials** → 對個人使用的 QPS 不構成問題；Sprint 7 部署時可視需要用 `st.cache_resource` 快取。目前不提前優化。
