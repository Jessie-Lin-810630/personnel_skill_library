# Proposal

## Why

`poetry run python -m unittest discover -s tests` 目前有 7 個測試不通過（1 個 failure、6 個 error）。這些失敗在 `f349efe` 之前就存在，與近期的 FastAPI 與登入改動無關，但它們讓「全測試通過」失去意義：每次跑測試都要先分辨哪些失敗是舊的、哪些是剛弄壞的，新的迴歸很容易被淹沒在既有雜訊裡。前一個 change 就因此把驗收條件從「全綠」改寫成「失敗數不增加」。

逐一查證後，7 個失敗分成三類，**成因全部是測試沒有跟上程式與資料夾結構的變更，沒有任何一個代表程式有錯**。

## What Changes

### 類型一：patch 目標已不存在（2 個）

- `tests/test_dashboard_connect_to_google_genai.py` 的兩個測試以 `patch.object(cc_mod, "Credentials")` 攔截憑證建立，但 `dashboard_ui/agent_tools/connect_to_google_genai.py` 的 `from google.oauth2.service_account import Credentials` 位於「地端測試跑下面區塊」的註解內，雲端路徑不會 import 它，patch 目標因而不存在。
- 改為只驗證雲端路徑的行為：`GCP_PROJECT_ID` 未設定時拋出 `EnvironmentError`，已設定時回傳綁定 us-central1 的 client。拿掉對 `Credentials` 的 patch。

### 類型二：期待的型別已過時（4 個）

- `task02_github_restapi_etl/t_transform_github.py` 的 `_parse_iso_datetime()` 會把 GitHub API 回傳的 ISO 8601 字串轉成 `datetime` 物件，`task03_leetcode_ccClub_etl` 亦有相同處理。測試仍以字串比對，於是在排序時拋 `TypeError: '<' not supported between 'datetime.datetime' and 'str'`，或在斷言時因型別不同而失敗。
- 改為期待 `datetime` 物件。方向依據是 `task02_github_restapi_etl/README.md` 的 schema 定義寫明這些欄位是 `Date (ISO 8601)`、範例為 `ISODate(...)`，也就是 MongoDB 原生日期型別，程式的現行行為才是正確的。

### 類型三：測試檔對應的程式已除役（1 個）

- `tests/test_task07_onenote_to_markdown.py` 對應的 `task07_onenote_to_markdown/` 資料夾已隨 v1 除役刪除，測試模組 import 失敗。
- 刪除該測試檔。v2 的 `tests/test_task07_onenote_to_markdown_v02.py` 已涵蓋現行實作。

### 不在本次範圍

- **不動任何程式碼**，只改 `tests/` 底下的檔案。三類失敗都源於測試過時，程式行為與其 README 的 schema 定義一致。
- 不處理 `connect_to_google_genai.py` 與 `query_with_vector_search.py` 以註解切換地端與雲端路徑的做法。那個做法讓地端分支無法被測試涵蓋，屬於實作層面的取捨，若要改成以環境變數判斷，應另案評估。
- 不新增測試涵蓋率，不重構既有測試的結構。

## Capabilities

本 change 只修正測試程式，不改變任何對外行為，故無 spec 變更。`.openspec.yaml` 設 `skip_specs: true`。

## Impact

- **修改檔案**：`tests/test_dashboard_connect_to_google_genai.py`、`tests/test_task02_github_restapi_etl.py`、`tests/test_task03_leetcode_ccClub_etl.py`。
- **刪除檔案**：`tests/test_task07_onenote_to_markdown.py`。
- **不影響**：所有非測試程式、MongoDB 欄位與型別、GCS 目錄結構、部署設定。
- **完成後**：`poetry run python -m unittest discover -s tests` 全數通過，後續 change 的驗收條件可以恢復成「全綠」這個明確標準。
