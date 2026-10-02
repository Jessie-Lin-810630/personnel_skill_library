# Design

## Context

成因分類見 `proposal.md`。這裡只記修法的取捨。

三類失敗的共同點是「測試寫死了某個當時成立、現在不成立的前提」：類型一寫死了模組會 import `Credentials`，類型二寫死了欄位是字串，類型三寫死了某個資料夾存在。修測試的方向因此不是逐一調參數，而是讓斷言貼著「程式與其 README 共同定義的現行契約」。

## Goals / Non-Goals

**Goals:**

- `poetry run python -m unittest discover -s tests` 全數通過，讓後續 change 能用「全綠」當驗收條件。
- 每個修正都能說出依據，不以「讓測試通過」為唯一目的而放寬斷言。

**Non-Goals:**

- 不動任何非測試程式。
- 不提高測試涵蓋率，不重構測試結構，不改測試框架。
- 不處理以註解切換地端與雲端路徑的做法。

## Decisions

### 1. 類型二以 README 的 schema 定義為準，不是以程式現況為準

- 表面上看，測試期待字串、程式回傳 `datetime`，兩者不一致；只看程式就改測試，等於預設「程式一定對」。

- 實際依據是 `task02_github_restapi_etl/README.md` 的 Collection schema：`created_at`、`pushed_at`、`committed_at` 三個欄位都標為 `Date (ISO 8601)`，範例文件寫的是 `ISODate("2026-02-04T06:06:12.000+0000")`，也就是 MongoDB 的原生日期型別。pymongo 要存成 BSON Date 必須收到 `datetime` 物件，收到字串只會存成字串。

- 所以程式的 `_parse_iso_datetime()` 是對的，測試的字串期待是舊的。修測試而非修程式。

### 2. 類型一只驗證雲端路徑，不設法讓地端路徑可測

- `connect_to_google_genai.py` 以註解區塊切換地端與雲端兩條路徑，被註解的那條在執行期不存在，任何 patch 都攔不到。

- 要讓兩條路徑都可測，得把註解開關改成環境變數判斷。那會動到兩支程式，超出本次「只修測試」的範圍。

- 因此測試只涵蓋實際會執行的雲端路徑：未設 `GCP_PROJECT_ID` 時拋 `EnvironmentError`、已設定時回傳綁定 us-central1 的 client。地端路徑維持不被涵蓋，這是已知的缺口，在測試檔的 docstring 寫明原因，避免日後有人以為是漏寫。

### 3. 類型三刪除檔案，不改寫成 skip

- 另一個作法是保留檔案並標上 `@unittest.skip`。不採用，因為它對應的 `task07_onenote_to_markdown/` 已經整個刪除，不會再回來，留著只會讓人誤以為 v1 還有東西要維護。

- v2 的 `tests/test_task07_onenote_to_markdown_v02.py` 已涵蓋現行實作，刪除不會造成涵蓋缺口。

## Risks / Trade-offs

- **地端憑證路徑仍無測試涵蓋。** 這是決策 2 的代價。該路徑只在有人手動解除註解時才執行，改壞了要到地端實際跑才會發現。
- **類型二的修正依賴 README 的 schema 定義正確。** 若 README 本身寫錯，修完的測試會一起錯。已比對程式行為與 README 兩者一致，但兩者若同時偏離實際 MongoDB 內容，本次不會察覺。
- **修完之後失敗數歸零，日後任何新失敗都會立刻顯眼。** 這是目的，但也表示往後不能再用「這是既有失敗」搪塞。
