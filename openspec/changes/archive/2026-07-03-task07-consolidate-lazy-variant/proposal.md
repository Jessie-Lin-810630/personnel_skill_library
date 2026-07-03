## Why

task07 的 lazy_loading 變體（GCS 資料湖多版本 × 純 on-demand Silver × Gold 歸檔/退件）經審查 UI 遴選、
手動驗證後定案勝出。原版 `task07_onenote_to_markdown/`（本機磁碟、ETL 主動逐頁呼叫 LLM）與其
`archive_service/`、原版審查頁應退役。同時，Silver 與 Gold 未來要各自部署成雲端容器、各開 endpoint，
需把它們依賴的模組/工具切割成自帶，且不得混入 Streamlit（`dashboard_ui`）職責區。

## What Changes

- **服務隔離為獨立容器單元**（未來各自部署）：
  - 抽共用套件 `task07_common/`（`gcs.py`、`audit_log.py`、`hashing.py`），供三者依賴。
  - `silver_service/` → `task07_silver_service/`，並納入 `t_enrich_html_to_markdown.py`、`l_save_markdown.py`。
  - `gold_service/` → `task07_gold_service/`，並納入 `l_archive_note.py`。
  - `task07_onenote_to_markdown_lazy_loading/` 收斂為純 Bronze ETL（`e_onenote_download.py`、`main.py`）。
  - 三者改 import `task07_common`；services 內改相對 import。Streamlit 不 import 任何 `task07_*`。
- **`task07_gold_service` 取代 `archive_service`**：刪除原版 `archive_service/`（Flask + `utils/gcs_archiver.py`、`utils/mongodb.py`），淘汰 `ARCHIVE_ENDPOINT_URL`。
- **合併審查頁**：`onenote_versioned_review.py` 的多版本審查功能併入 `onenote_review.py`；登入沿用原 `onenote_review` 的 hero 版面（帳密→角色），登入後採 versioned 的多版本 body。移除 sidebar 的「Versioned Review」連結、刪除孤兒 `get_onenote_pages` 與 `local_path_to_gcs_blob`。
- **退役原版 task07**：`task07_onenote_to_markdown/`（本機磁碟版、`onenote_page_metadata`）整個資料夾退役（可由 `feature/html-to-markdown` 分支還原）。
- 更新 CLAUDE.md（結構、常用指令、ETL 表、l_* 說明、去除「兩版並存」註記）。

## Capabilities

### New Capabilities
（無新增能力——本次為重構、合併與退役。）

### Modified Capabilities
- `onenote-review-page`: 資料源由 `onenote_page_metadata`／本機路徑改為 `onenote_note_metadata`（aggregation 過濾 rejected／舊版）＋ `gs://` URI；新增 `dt=` 多版本圓鈕、on-demand Silver 觸發、Gold approve/reject 與 regenerate；登入保留 hero 版面（帳密→角色）。

### Removed Capabilities
- `onenote-versioned-review-page`: 併入 `onenote-review-page`（同一頁提供，不再獨立）。
- `archive-endpoint`: 原版 task07 的 Flask 歸檔端點退役，由 `gold-archive-endpoint`（`task07_gold_service`）取代。

## Impact

- **改名/搬移（git mv）**：`silver_service`→`task07_silver_service`、`gold_service`→`task07_gold_service`；`t_enrich_html_to_markdown.py`、`l_save_markdown.py`→`task07_silver_service/`；`l_archive_note.py`→`task07_gold_service/`；`utils/{gcs,audit_log,hashing}.py`→`task07_common/`。
- **新增**：`task07_common/__init__.py`。
- **修改**：所有 service/ETL/測試的 import；`dashboard_ui/pages/onenote_review.py`（合併）；`dashboard_ui/utils/{gcs_reader,interact_with_mongodb,ui_elements}.py`（移除孤兒、sidebar）；CLAUDE.md；service app 埠註解與 Usage。
- **需人工刪除（rm 受 hook 擋）**：`archive_service/`、`task07_onenote_to_markdown/`、`openspec/specs/archive-endpoint/`。
- **不變**：MongoDB collections（`onenote_note_metadata` 等）、GCS bucket 結構、endpoint 行為契約（僅程式位置改變）。
- **部署**：四個獨立執行環境（Bronze ETL Job、`task07_silver_service` 8002、`task07_gold_service` 8003、Streamlit）。
