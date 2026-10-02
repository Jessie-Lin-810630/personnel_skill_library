# Tasks

## 1. 類型三：刪除已除役的測試檔

- [x] 1.1 刪除 `tests/test_task07_onenote_to_markdown.py`。驗證：`poetry run python -m unittest discover -s tests` 不再出現 `ModuleNotFoundError: No module named 'task07_onenote_to_markdown'`

## 2. 類型一：改為只驗證雲端憑證路徑

- [x] 2.1 `tests/test_dashboard_connect_to_google_genai.py` 移除對 `Credentials` 的 patch，改為只驗證雲端路徑。驗證：`poetry run python -m unittest tests.test_dashboard_connect_to_google_genai -v` 全綠
- [x] 2.2 在該測試檔的 module docstring 寫明地端憑證路徑不被涵蓋的原因（該段程式在註解內，執行期不存在）。驗證：檔案開頭讀得到這段說明

## 3. 類型二：時間欄位改為期待 datetime

- [x] 3.1 `tests/test_task02_github_restapi_etl.py` 的 `pushed_at`、`committed_at` 斷言改為期待 `datetime` 物件；`build_summary_document` 吃的是已轉換過的 repo document，所以輸入 fixture 的 `pushed_at` 也要是 `datetime`。另修 `snapshot_date`：原本以 `assertRegex` 比對 `YYYY-mm-dd` 字串，改為驗證它是時分秒歸零的 UTC `datetime`（這處在排序的 TypeError 之後，原本沒機會顯現）。驗證：`poetry run python -m unittest tests.test_task02_github_restapi_etl -v` 全綠
- [x] 3.2 `tests/test_task03_leetcode_ccClub_etl.py` 的 LeetCode 與 ccClub 兩支 summary 測試，`snapshot_date` 斷言同樣改為驗證時分秒歸零的 UTC `datetime`。驗證：`poetry run python -m unittest tests.test_task03_leetcode_ccClub_etl -v` 全綠
- [x] 3.3 確認修正後的斷言與 `task02_github_restapi_etl/README.md` 的 schema 定義一致（該欄位標為 `Date (ISO 8601)`）。驗證：逐一比對測試期待的型別與 README 表格的型別欄

## 4. 收尾

- [x] 4.1 全測試通過。驗證：`poetry run python -m unittest discover -s tests` 回報 0 failures、0 errors
- [x] 4.2 確認沒有動到任何非測試程式。驗證：`git diff --name-only` 的結果全部位於 `tests/` 底下
