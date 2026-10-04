# Tasks

## 1. 修改 SYSTEM_PROMPT

- [x] 1.1 依 `design.md` 決策 2，修改 `dashboard_ui/agents/rag_agent.py` 的 `SYSTEM_PROMPT`：刪除第一條指令中「且要**標註引用的來源 (檔案名稱與章節)**。」這一句，並在其後新增一條指令，要求模型不在回答中列出「來源」清單、不標註檔案名稱或章節，同時說明系統會在回答下方另外顯示來源筆記。其餘指令的文字維持不變。驗證：`SYSTEM_PROMPT` 中已找不到「標註引用的來源」，並讀得到新增的那條指令
- [x] 1.2 確認改動通過專案的格式與 lint 檢查。驗證：`poetry run ruff check dashboard_ui/agents/rag_agent.py` 與 `poetry run ruff format --check dashboard_ui/agents/rag_agent.py` 皆無錯誤

## 2. 測試

- [x] 2.1 既有的 RAG agent 單元測試不受影響。這些測試以 mock 取代模型呼叫，不斷言 prompt 內容，因此預期不需修改。驗證：`poetry run python -m unittest tests.test_dashboard_rag_agent -v` 全綠
- [x] 2.2 全測試通過。驗證：`poetry run python -m unittest discover -s tests` 回報 0 failures、0 errors

## 3. 手動驗收

- [x] 3.1 依 `design.md` 的 Verification 段落，以非訪客身分啟動 `poetry run streamlit run dashboard_ui/app.py`，進入 AI 知識 Agent 頁並開新對話，提出會命中同一章節多個 chunk 的查詢（例如 MySQL Window Function）。驗證：回答正文沒有以「來源：」開頭列出檔名與章節的段落，「📎 來源筆記」照常顯示且帶有 vector 與 rerank 分數
- [x] 3.2 以訪客身分重複 3.1 的查詢。驗證：回答正文同樣沒有來源清單，「📎 來源筆記」只列出去重後的檔名與章節，看不到分數

## 4. 收尾

- [ ] 4.1 確認實作只動到 `SYSTEM_PROMPT`。驗證：以 commit 為單位查核本 change 的實作 commit，`git show --name-only --format="" <commit>` 的結果只有 `dashboard_ui/agents/rag_agent.py` 與本 change 自己的 `tasks.md`，且 `git show <commit>` 的 diff 只落在 `SYSTEM_PROMPT` 字串內
