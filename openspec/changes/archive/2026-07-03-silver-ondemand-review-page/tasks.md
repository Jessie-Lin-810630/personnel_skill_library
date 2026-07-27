## 1. Silver enrich 端點（silver_service）

- [x] 1.1 建立 `silver_service/__init__.py`、`silver_service/app.py`（Flask app，`POST /enrich`），比照 `archive_service/app.py` 結構
- [x] 1.2 `/enrich` 解析 body（`page_id`、`dt`、`trigger` 預設 `on_demand`）；缺 `page_id`/`dt` 回 400；`trigger` 非 `on_demand`/`regenerate` 回 400
- [x] 1.3 `/enrich` 內部 import 並呼叫 `task07_onenote_to_markdown_lazy_loading.t_enrich_html_to_markdown.t_enrich_html_to_markdown`，把回傳 dict JSON 化
- [x] 1.4 依回傳 dict 對應 HTTP 狀態碼：`not_found` → 404；含 `error`（如 regenerate quota）→ 帶原 dict 回 200（業務結果，由呼叫端依欄位判讀）；正常 → 200；未預期例外 → 500
- [x] 1.5 包上游/例外處理（比照 archive 的 DB/GCS 例外分層），失敗記 log 並回 5xx
- [x] 1.6 `app.run(port=8002, debug=True)`（與 archive_service 8001 錯開）；module docstring 依專案規範

## 2. Dashboard 讀取封裝（utils）

- [x] 2.1 `dashboard_ui/utils/interact_with_mongodb.py` 新增 `get_onenote_versioned_pages(db)`：查 `onenote_note_metadata`，回傳含 `page_id, notebook, section, page_title, dt, html_path, md_path, md_md5, html_hash, html_downloaded_at, status` 的清單
- [x] 2.2 `dashboard_ui/utils/gcs_reader.py` 新增以 `gs://` URI 為輸入的讀取 helper：`read_text_by_uri(uri)` 與 `read_image_base64_by_uri(uri)`（解析 `gs://bucket/key`），不影響既有 `read_text`/`read_bytes_as_base64`/`local_path_to_gcs_blob`

## 3. 多版本對照審查頁

- [x] 3.1 新增 `dashboard_ui/pages/onenote_versioned_review.py`，沿用既有登入 gate、`_render_side_bar()`、`_WHITE_FRAME` 白底渲染樣式
- [x] 3.2 讀 `get_onenote_versioned_pages`，三層下拉（筆記本/章節/頁面）選定 `page_id` 後，以 `dt=` 圓鈕列出該頁多版本（依 `html_downloaded_at` 排序，標示 dt 與時間）；查無資料顯示提示
- [x] 3.3 選定版本：左側以 `gs://` URI 讀 bronze html 白底渲染、圖片自對應 `dt=` 分區 `_images/` base64 內嵌
- [x] 3.4 右側渲染 silver md：`md_path != null` 直接讀 GCS 渲染（cache hit、不呼叫端點）
- [x] 3.5 `md_path == null` 時 `requests.post(SILVER_ENDPOINT_URL, json={page_id, dt, trigger:"on_demand"})`，顯示 spinner，成功後用回傳 `md_path` 讀 GCS 渲染並清版本清單 `@st.cache_data`
- [x] 3.6 端點回 `circuit_open=true`/逾時/非 2xx → 顯示對應提示，左側 html 仍正常顯示
- [x] 3.7 `regenerate` 按鈕：`trigger:"regenerate"` 呼叫端點；回 `regenerate quota exceeded` 時顯示「已達上限」提示
- [x] 3.8 `approve`/`reject` 佔位按鈕：點擊僅 `st.info("Gold 歸檔後端於下一階段接上")`，不呼叫後端

## 4. 設定與測試

- [x] 4.1 `SILVER_ENDPOINT_URL`（如 `http://localhost:8002/enrich`）記入 CLAUDE.md 環境變數段（`.env.example` 受 protect-env hook 保護、由使用者自行填 `.env`）
- [x] 4.2 `tests/test_silver_service_endpoint.py`（unittest + Flask test_client，patch `t_enrich_html_to_markdown`），驗證 400/404/200/500 分支與 body 傳遞，不實打 LLM
- [x] 4.3 `poetry run python -m unittest tests.test_silver_service_endpoint` 綠燈（8/8）；全套另有 5 個既有失敗（4 dashboard `utils` import path + 1 task07 v02 mime mock），與本次無關
- [x] 4.4 手動端到端驗證（使用者執行）：起 `silver_service`（8002）+ Streamlit，於審查頁點未處理版本，確認 GCS `processed-notes/` 出現 LLM 生成 md ← **本階段通過標準**

## 5. 文件

- [x] 5.1 CLAUDE.md「常用指令」補 silver_service 啟動指令（`poetry run python -m silver_service.app`）
