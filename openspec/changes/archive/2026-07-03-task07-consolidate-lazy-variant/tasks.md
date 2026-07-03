## 1. 抽共用套件 task07_common

- [x] 1.1 `git mv` `utils/{gcs,audit_log,hashing}.py` → `task07_common/`；新增 `task07_common/__init__.py`
- [x] 1.2 Bronze ETL `e_onenote_download.py` import 改 `task07_common`

## 2. 服務隔離 + 改名

- [x] 2.1 `git mv silver_service task07_silver_service`；`git mv gold_service task07_gold_service`
- [x] 2.2 `git mv` `t_enrich_html_to_markdown.py`、`l_save_markdown.py` → `task07_silver_service/`；`l_archive_note.py` → `task07_gold_service/`
- [x] 2.3 service 內 import 改相對／`task07_common`；app 的 Usage docstring 與埠註解更新（archive_service 退役）
- [x] 2.4 測試 import 更新（silver/gold endpoint tests、`test_task07_..._v02` 指向新位置）

## 3. gold_service 取代 archive_service

- [x] 3.1 確認無程式 import `archive_service`（僅原審查頁 `ARCHIVE_ENDPOINT_URL`，於任務 4 移除）
- [x] 3.2 **（人工刪除）** 移除 `archive_service/` 整個資料夾

## 4. 合併審查頁

- [x] 4.1 以 versioned body 為基底、換上原版 hero 登入，`git mv -f` 覆蓋 `onenote_review.py`
- [x] 4.2 sidebar 移除「Versioned Review」連結
- [x] 4.3 移除孤兒 `get_onenote_pages`、`local_path_to_gcs_blob`（確認無其他呼叫者）

## 5. 退役原版 task07

- [x] 5.1 原版 `task07_onenote_to_markdown/` 在本分支（feature/dashboard-ui）不存在，無需刪除（僅存於 feature/html-to-markdown）

## 6. 文件與驗證

- [x] 6.1 CLAUDE.md：結構、常用指令、ETL 表、l_* 說明、去除「兩版並存」註記，改為「變體勝出、四執行環境」
- [x] 6.2 `poetry run python -m unittest`（silver/gold/v02）全綠、ruff 全過、合併頁與服務 py_compile 通過
- [x] 6.3 **（人工刪除）** 移除 `openspec/specs/archive-endpoint/`（原版能力退役）
- [x] 6.4 手動驗證（使用者執行）：起三服務 + Streamlit，合併後 `onenote_review.py` 登入 hero 正常、多版本審查 + silver/gold 端點皆可運作
