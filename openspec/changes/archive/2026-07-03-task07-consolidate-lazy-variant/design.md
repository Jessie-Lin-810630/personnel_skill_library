## Context

Silver（`task07_silver_service`）、Gold（`task07_gold_service`）、Bronze ETL、Streamlit 四者未來各自
部署為雲端容器。原版 task07（本機磁碟、`onenote_page_metadata`、`archive_service`）已由變體取代。
掃描確認：`archive_service` 無程式 import（僅 `onenote_review.py` 透過 `ARCHIVE_ENDPOINT_URL` 打它）；
`get_onenote_pages`/`local_path_to_gcs_blob` 只服務原版審查頁；`dashboard_ui` 未 import 任何 task07 套件。

## Goals / Non-Goals

**Goals:**
- 三個執行單元自帶相依（透過共用套件 `task07_common`），互不耦合、可各自打容器。
- `task07_gold_service` 取代 `archive_service`；退役原版 task07。
- 單一審查頁 `onenote_review.py`：原 hero 登入 + 變體多版本 body。

**Non-Goals:**
- 改變任何 endpoint 的行為契約（僅搬程式位置與 import）。
- 改動 MongoDB collections / GCS bucket 結構。
- 撰寫各容器的 Dockerfile / 雲端部署（後續另做）。

## Decisions

### D1：共用套件 `task07_common`（不逐一複製）
`gcs.py`、`audit_log.py`、`hashing.py` 收進 `task07_common/`，ETL / silver / gold 皆 import。相較「複製三份」
少漂移；相較「服務內各留一份」少維護點。三個容器各自打包時把 `task07_common` 一併納入。

### D2：資料夾命名 `task07_*` 前綴
`task07_silver_service`、`task07_gold_service`、`task07_common`、`task07_onenote_to_markdown_lazy_loading`
共用前綴，從專案結構一眼看出同源、僅拆成不同容器服務。ETL 資料夾名維持不變（避免多一輪 import churn）。

### D3：以 `git mv` 搬移、人工刪除退役物
所有改名/搬移用 `git mv`（此環境可用），保留 git 歷史、免人工刪。真正的「刪除」（`archive_service/`、
`task07_onenote_to_markdown/`、`openspec/specs/archive-endpoint/`）因 `rm` 受 hook 擋，列清單由使用者執行。

### D4：審查頁合併，登入以原版為主、body 以變體為主
以 `onenote_versioned_review.py` 為 body 基底，將其精簡登入換成 `onenote_review.py` 的 hero 登入區塊，
再 `git mv -f` 覆蓋 `onenote_review.py`。兩頁本就共用 `st.session_state["authenticated"/"role"]`，登入表單
key 收斂為原版的 `login_user`/`login_pwd`。移除 sidebar 的 versioned 連結與孤兒函式。

## Risks / Trade-offs

- [跨套件 import `task07_common`] → 三容器打包時都需納入 `task07_common`；本地 `python -m task07_*` 於 repo root 可解析。
- [退役原版不可逆] → 已確認 `feature/html-to-markdown` 可還原；本分支退役不怕過頭。
- [openspec `archive-endpoint` spec 非 Requirement 格式] → 不寫 REMOVE delta，改由刪除該 spec 資料夾退役（列入人工刪除清單）。
- [合併頁 widget key 衝突] → 收斂為單一套 key；session_state 共用不影響。
