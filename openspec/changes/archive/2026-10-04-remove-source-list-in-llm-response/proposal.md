## Why

Page 3 的 RAG 回答會出現兩份來源清單：一份是 Gemini 依 `SYSTEM_PROMPT`「要標註引用的來源 (檔案名稱與章節)」自行寫在回答正文結尾的「來源：」清單，另一份是頁面在回答氣泡下方渲染的「📎 來源筆記」。前者由模型逐一照抄 context 中每個 chunk 的檔名與章節，同一章節切成多個 chunk 時就會重複列出，且與後者資訊重疊。來源呈現應只保留頁面渲染的「📎 來源筆記」一處，由程式控制去重與訪客／非訪客的分數顯示差異。

## What Changes

- 修改 `dashboard_ui/agents/rag_agent.py` 的 `SYSTEM_PROMPT`：移除「要標註引用的來源 (檔案名稱與章節)」的要求，改為明確指示模型不在回答中列出來源清單、不標註檔名與章節，並告知系統會在回答下方另外顯示來源筆記。
- 不改動 `ai_knowledge_agent.py` 的渲染邏輯，「📎 來源筆記」維持由 `_render_sources()` 輸出。
- 不對模型回答做後處理；回答是否仍夾帶來源清單取決於模型對指令的遵循度。

## Capabilities

### New Capabilities

（無）

### Modified Capabilities

- `ai-knowledge-agent-page`：「Sources displayed under agent response」新增約束，RAG agent 的回答正文不包含來源清單，來源只透過回答氣泡下方的「📎 來源筆記」呈現。

## Impact

- **修改程式**：`dashboard_ui/agents/rag_agent.py`（僅 `SYSTEM_PROMPT` 字串）。
- **不影響**：`planning_agent` 的 prompt 與輸出、`build_context()` 的 context 格式、`sources` 的組裝與 `_render_sources()` 的去重／角色分數顯示、chat_history 的寫入格式。
- **已知限制**：MongoDB chat_history 中既有 session 的舊回答仍含「來源：」清單，會隨最近 3 輪歷史回送模型，可能讓舊 session 接下來數輪仍模仿舊格式；開新對話後不受影響。
