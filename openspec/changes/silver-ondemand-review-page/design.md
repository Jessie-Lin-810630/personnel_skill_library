## Context

task07 lazy_loading 變體的 Bronze ETL 與 Silver 服務本體皆已合併進
`task07_onenote_to_markdown_lazy_loading/`。Silver 服務本體
`t_enrich_html_to_markdown(page_id, dt, trigger) -> dict` 已包含：regenerate quota 檢查、
`html_hash` 快取查找（`find_cached_md_by_hash`）、服務級斷路器 `_LLMServiceGuard`、
多模態 Gemini 呼叫、寫 md 到 GCS `processed-notes/`、upsert C3。回傳
`{status, cache_hit, md_path, circuit_open, error}`。

現況缺口：`feature/dashboard-ui` 分支上沒有任何觸發點讓此服務跑起來。既有
`dashboard_ui/pages/onenote_review.py` 是**原版 task07** 專用：讀舊 collection
`onenote_page_metadata`、單一版本、用 `local_path_to_gcs_blob` 假設本機路徑、md 須預先存在、
Approve/Reject 打 `archive_service` Flask 端點（`onenote-vaults` staging）。lazy_loading 變體的
schema 與資料流不同（`onenote_note_metadata` 主鍵 `page_id`+`dt`、`gs://` URI、多版本、
md 按需生成）。

約束：openspec config 規則「Dashboard pages read from MongoDB only — no direct ETL calls
from UI code」；CLAUDE.md「兩版 task07 並存、由 UI 遴選，未定奪前不得刪任一版」。

## Goals / Non-Goals

**Goals:**
- 把 Silver 服務端點化（Flask `POST /enrich`），Streamlit 維持唯讀、透過 HTTP 觸發。
- 新增 lazy_loading 專用多版本對照審查頁，作為 on-demand 觸發點。
- 通過標準：從審查頁點擊未處理版本 → GCS `processed-notes/` 出現 LLM 生成的 md。

**Non-Goals:**
- Gold layer（清洗、歸檔、向量化，hand-over 167-185）——下一階段。
- 雲端部署（Cloud Run、Artifact Registry，步驟 9-11）。
- 修改既有 `onenote_review.py`、`archive_service/`、原版 collection `onenote_page_metadata`。
- approve/reject 的後端行為（本階段僅佔位按鈕）。

## Decisions

### D1：Silver 端點化，比照 archive_service
新增 `silver_service/app.py`（Flask，`POST /enrich`），內部 `from
task07_onenote_to_markdown_lazy_loading.t_enrich_html_to_markdown import
t_enrich_html_to_markdown` 直接呼叫服務本體，把回傳 dict 原樣 JSON 化。錯誤分層比照
archive_service（400 缺欄位、404 查無版本、5xx 上游/DB/GCS）。
- **為何**：符合 config 規則（UI 不直呼 ETL）與 hand-over 4a「端點化，比照 Archive」；雲端
  步驟 10b 可直接把此端點包 image 沿用。
- **替代方案**：Streamlit 直接 import 呼叫——最簡但違反 config 規則、雲端需重寫，已由使用者否決。
- 本機以 `app.run(port=8002)` 起，審查頁讀 `SILVER_ENDPOINT_URL`（如
  `http://localhost:8002/enrich`）。與 archive_service 的 8001 錯開。

### D2：新增獨立審查頁，不改原版
新增 `dashboard_ui/pages/onenote_versioned_review.py`（檔名待定，語意為「多版本對照」）。
沿用既有登入 gate、`_render_side_bar()`、`_WHITE_FRAME` 白底渲染與圖片 base64 內嵌樣式，但
資料來源改為 `onenote_note_metadata` 且路徑改為 `gs://` URI 直讀。
- **為何**：CLAUDE.md 要求兩版並存供遴選；schema 與路徑假設不同，硬改原版會破壞原版行為。
- **替代方案**：參數化同一頁支援兩 schema——耦合高、違反「並存遴選」意圖，不採。

### D3：多版本查詢與 gs:// 讀取封裝
在 `dashboard_ui/utils/` 新增：
- `interact_with_mongodb` 增 `get_onenote_versioned_pages(db)`：查 `onenote_note_metadata`，
  回傳含 `page_id, notebook, section, page_title, dt, html_path, md_path, md_md5, html_hash,
  html_downloaded_at, status` 的清單，供頁面依 `page_id` 分組。
- `gcs_reader` 增以 `gs://` URI 為輸入的讀取函式（現有 `read_text/read_bytes_as_base64` 收
  bucket+blob，且 `local_path_to_gcs_blob` 假設本機路徑）。新增 `read_text_by_uri(uri)`、
  `read_image_base64_by_uri(uri)` 或等效 helper，解析 `gs://bucket/key`。
- **為何**：lazy_loading 的 metadata 存完整 `gs://` URI（見 `utils/gcs.gs_uri`），與原版本機路徑
  不同；圖片位於各 `dt=` 分區的 `_images/`，需由選定版本的 `html_path`/`md_path` 推得 prefix。

### D4：on-demand 觸發流程
審查頁選定版本後：
1. 若 `md_path != null` → 直接讀 GCS md 渲染（不呼叫端點）。
2. 若 `md_path == null` → `requests.post(SILVER_ENDPOINT_URL, json={page_id, dt,
   trigger:"on_demand"})`，成功後用回傳 `md_path` 讀 GCS 渲染；清 `@st.cache_data` 版本清單快取。
3. `regenerate` 按鈕 → 同上但 `trigger:"regenerate"`。
4. `approve`/`reject` → 僅 `st.info("Gold 歸檔後端於下一階段接上")`。
- 端點回傳 `circuit_open=true` 或非 2xx → 顯示提示、保留左側 html。

### D5：測試策略
- Silver 端點：以 unittest + mock（monkeypatch `t_enrich_html_to_markdown`）驗證 400/404/200
  分支與 body 傳遞，不實打 LLM。符合 memory「用 unittest 不用 pytest」。
- 端到端「md 出現在 processed-notes」由使用者手動驗證（需真實 Bronze 資料、Vertex AI 憑證、
  起 Streamlit + silver_service 兩 process），作為本階段通過標準。

## Risks / Trade-offs

- [本機需同時起 Streamlit 與 silver_service 兩 process] → README/tasks 註明啟動指令與
  `SILVER_ENDPOINT_URL` 設定；與 archive_service（8001）錯開埠（8002）。
- [Silver 端點 import task07 lazy_loading 套件，需 PYTHONPATH/poetry 能解析] → 以
  `python -m silver_service.app` 或於專案根起 Flask，比照 archive_service 的 import 慣例。
- [同名筆記「一次只認可一份」屬 Gold/UI 把關] → 本階段 approve 為佔位，暫不實作該把關，
  於 Gold 階段補。
- [LLM 首次生成延遲（數秒~數十秒）] → 審查頁顯示 spinner；端點 timeout 設足夠（比照 archive 的
  120s）。
- [圖片路徑推導] → 以選定版本 `html_path` 的父層 prefix + `_images/<檔名>` 組出圖片 blob，
  對齊 bronze 分區；md 內圖片同理。
