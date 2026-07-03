## 1. GCS 與 audit 工具擴充

- [x] 1.1 `task07_onenote_to_markdown_lazy_loading/utils/gcs.py` 新增 `archived_note_prefix(user_id, notebook, section, dt)` → `archived-notes/<user>/<nb>/<sec>/dt=<dt>`
- [x] 1.2 `utils/gcs.py` 新增 `download_bytes(uri)` 與 `copy_blob(src_uri, dst_blob) -> str|None`（server-side copy，回目的物件 md5）
- [x] 1.3 `utils/audit_log.py` 新增 `get_archived_version(page_id) -> dict`（查該 page_id `status=archived` 的列，供把關/UI）

## 2. Gold Load 服務本體

- [x] 2.1 新增 `task07_onenote_to_markdown_lazy_loading/l_archive_note.py`，含 `_infer_misposition_metadata(post)`（參考 hand-over 提供的補救解析）
- [x] 2.2 `archive_note(page_id, dt, role) -> dict`：取 C3 版本 → 無版本回 `not_found`、`md_path=null` 回可辨識錯誤
- [x] 2.3 同名把關：`get_archived_version(page_id)` 已有且非本 dt → 回錯誤不覆寫
- [x] 2.4 複製 md（`md_path`→`archived-notes/.../dt=/<page_title>.md`）與各 png（C3 `img_path`→`archived-notes/.../dt=/_images/<name>`），收集 md5 與歸檔路徑
- [x] 2.5 upsert C3：`status=archived`、`review_result=approved`、`reviewed_by_role`、`reviewed_at`、`archived_at`、`md_archive_path`、`img_archive_path`、`error_msg=None`
- [x] 2.6 讀回歸檔 md → `frontmatter.loads` → `post.metadata or _infer_misposition_metadata` → 正規化（date→UTC datetime、tags/alias→list）→ upsert C3 `tags`/`date`/`type`/`alias`
- [x] 2.7 GCS/DB 例外 → 記 C3 `error_msg`、status 不翻 `archived`，回錯誤 dict

## 3. Gold/Archive 端點

- [x] 3.1 新增 `gold_service/__init__.py`、`gold_service/app.py`（Flask，`POST /archive`，埠 8003），比照 `silver_service`/`archive_service`
- [x] 3.2 解析 `page_id`/`dt`/`role`/`action`；缺欄位或非法 action 回 400
- [x] 3.3 `action=approved` → 呼叫 `archive_note`，依回傳 dict 對應 200/404/409/500
- [x] 3.4 `action=rejected` → upsert C3 `status=review_closed`/`review_result=rejected`/`reviewed_by_role`/`reviewed_at`，回 200；不寫 GCS

## 4. 審查頁接線

- [x] 4.1 `dashboard_ui/utils/interact_with_mongodb.py` `get_onenote_versioned_pages` 補回 `review_result`、`md_archive_path`、`archived_at`、`reviewed_by_role`
- [x] 4.2 `onenote_versioned_review.py`：`approve`/`reject` 佔位改為 `requests.post(GOLD_ENDPOINT_URL, ...)`，成功清 `_load_versions` 快取並 rerun；沿用既有錯誤處理
- [x] 4.3 該 page_id 任一版本 `status=archived` → 顯示「已歸檔」橫幅、停用整組 approve/reject/regenerate 按鈕

## 5. 設定與測試

- [x] 5.1 `GOLD_ENDPOINT_URL`（如 `http://localhost:8003/archive`）記入 CLAUDE.md 環境變數段；補 `gold_service` 啟動指令；更新 ETL 表 task07 變體輸出加 `archived-notes/`
- [x] 5.2 `tests/test_gold_service_endpoint.py`（unittest + Flask test_client，patch `archive_note`）：驗證 400/404/200（approve、reject）分支與 body 傳遞
- [x] 5.3 `tests/` 補 `archive_note` frontmatter 萃取與 date 正規化的單元測試（mock gcs/audit），涵蓋正常 frontmatter 與錯位補救兩路
- [x] 5.4 `poetry run python -m unittest tests.test_gold_service_endpoint` 等新測試綠燈
- [x] 5.5 手動端到端（使用者執行）：起 gold_service（8003），審查頁按 approve → 確認 `archived-notes/` 出現 md+png、C3 翻 `archived` 且含 frontmatter 欄位 ← **通過標準**

## 6. 試用回饋調整：rejected 過濾 × 歸檔後可續審新內容

- [x] 6.1 `get_onenote_versioned_pages` 改用 aggregation：`$match review_result!=rejected` + 每 page_id `$setWindowFields` 算 `lastArchivedAt`（partitionBy page_id）+ 只留 `dt≥lastArchivedAt`（尚無歸檔全留）
- [x] 6.2 `utils/audit_log.py`：`get_archived_version` 換成 `get_latest_archived_version(page_id)`（依 archived_at 取最新歸檔版）
- [x] 6.3 `archive_note` 放寬把關：本版已 archived → idempotent；本版 dt 日 < 最後歸檔日 → 409 不覆寫；dt 日 ≥ 最後歸檔日 → 放行（新內容可再歸檔）
- [x] 6.4 `onenote_versioned_review.py`：移除「整組 page_archived 失效＋橫幅」，改逐版本——僅選中版自己 `archived` 才唯讀/停用；auto-enrich 與按鈕 disable 皆改看 `is_version_archived`
- [x] 6.5 補測試：`archive_note` idempotent / conflict(舊版) / not_found / no-md 早退分支；全套新測試綠燈
- [x] 6.6 手動驗證（使用者執行）：reject 一版 → 消失且不影響他版；approve 後對同 page_id 加新內容（新 dt）→ 新版可重走 Silver→Gold ← **本次調整通過標準**

## 7. 試用回饋調整：C3 frontmatter 改內嵌 Object + valid_img

- [x] 7.1 `l_archive_note.py` 新增 `_count_valid_images(content, img_archive_paths)`：正則抓正文 `![]()` 連結、取 basename、與 `img_archive_path` basename 比對計命中數
- [x] 7.2 `_extract_frontmatter(md_str, img_archive_paths)` 改回傳 5 欄 dict（tags/date/type/alias/valid_img）
- [x] 7.3 `archive_note` 步驟 4 upsert 改為單一內嵌 Object `{"archived_md_frontmatter": fm}`（取代先前 4 個扁平欄位）
- [x] 7.4 補測試：valid_img basename 命中/未命中、無歸檔路徑回 0；新測試綠燈
- [x] 7.5 手動驗證（使用者執行）：approve 後 C3 出現 `md_frontmatter` 內嵌 Object 且 `valid_img` 反映正確圖片數 ← **本次調整通過標準**

## 8. 試用回饋調整：欄位改名 md_frontmatter × reject 也保存 frontmatter

- [x] 8.1 C3 欄位 `archived_md_frontmatter` 改名 `md_frontmatter`（approve/reject 共用，好壞 md 靠 status 區分）；`_extract_frontmatter` 參數 `img_archive_paths`→`img_paths`（approve 傳 img_archive_path、reject 傳 raw-notes img_path）
- [x] 8.2 `l_archive_note.py` 新增 `reject_note(page_id, dt, role)`：翻 C3 review_closed → 背景讀 silver md 萃取 frontmatter 以 `md_frontmatter` upsert；失敗只記 error_msg
- [x] 8.3 `gold_service/app.py` reject 分支改薄包 `reject_note`（移除端點內 inline upsert 與相關 import）
- [x] 8.4 測試：reject_note 寫 review_closed + md_frontmatter(valid_img)、無 md 跳過；端點 reject 薄包；全套綠燈
- [x] 8.5 手動驗證（使用者執行）：reject 一版後 C3 出現 `md_frontmatter`（status=review_closed），approve 版則 status=archived，兩者皆可比對 valid_img ← **本次調整通過標準**
