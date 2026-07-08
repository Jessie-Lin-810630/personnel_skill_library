## Context

Silver 已可 on-demand 把 md 產到 GCS `processed-notes/`，C3（`onenote_note_metadata`，主鍵
`page_id`+`dt`）記錄各 `dt=` 版本血緣。審查頁 `onenote_versioned_review.py` 的 approve/reject 為佔位。
本階段接 Gold layer：把 `approved` 的 md 歸檔、翻 C3 生命週期、萃取 frontmatter。

依調整後 hand-over（167-192）：**Gold 不做向量化**（解耦到 task06 pipeline）；歸檔路徑取階層圖的
`gs://onenote-vaults/archived-notes/<user>/<notebook>/<section>/dt=<dt>/`（對齊 `utils/gcs.py` 單一
bucket 設計；第 185 行 per-user-bucket 舊路徑視為 v1 殘留，不採）。C3 schema（243-276）新增
frontmatter 四欄 `tags`/`date`/`type`/`alias`。

## Goals / Non-Goals

**Goals:**
- approve → 複製 md+png 到 `archived-notes/`、upsert C3 `archived` + 歸檔路徑 + 審核欄位。
- 歸檔後讀回 md 萃取 frontmatter（tags/date/type/alias）再 upsert C3。
- 「同名一次只認可一份」把關（端點 + UI 停用按鈕）。
- reject → C3 `review_closed`，不動 GCS。

**Non-Goals:**
- 向量化 / `note_vectors_multimodal`（另一條 pipeline）。
- 修改原版 `archive_service/`、`onenote_page_metadata`。
- bronze html 自動刪除（保留期人工評估）。

## Decisions

### D1：Gold Load 進 task07 套件，端點薄包
`archive_note(page_id, dt, role) -> dict` 放
`task07_onenote_to_markdown_lazy_loading/l_archive_note.py`（`l_*` = Load，對齊 ETL 命名）。
`gold_service/app.py` Flask `POST /archive` 薄包，比照 `silver_service`（埠 8003，與 silver 8002 /
archive_service 8001 錯開）。approve 呼叫 `archive_note`；reject 走輕量 C3 upsert。
- **替代**：把邏輯塞進端點——與 silver 端點薄包風格不一致，不採。

### D2：GCS 複製用 server-side copy
`utils/gcs.py` 新增 `copy_blob(src_uri, dst_blob) -> md5`（`bucket.copy_blob`，同 bucket 高效、
回新物件 md5）、`download_bytes`、`archived_note_prefix`。png 來源取 C3 `img_path`（raw-notes URI），
逐一 copy 到 `archived-notes/.../dt=/_images/<name>`。
- **替代**：download+upload——多一次進出流量，不採；但跨 bucket 時 `copy_blob` 仍可用。

### D3：frontmatter 萃取 + date 正規化
用 `python-frontmatter`：`post = frontmatter.loads(md_str)`；`fm = post.metadata or
_infer_misposition_metadata(post)`（補救解析，掃正文頂端 key:value，遇真正標題行才停，參考 hand-over
提供的函式）。`date`：`datetime.date` 或字串 → 正規化為 UTC `datetime`（BSON 不能編碼 `date`，只能
`datetime`）；解析失敗記 None。`tags`/`alias` 確保為 list（補救路徑可能回字串，需正規化）。

### D4：同名一次只認可一份
`utils/audit_log.py` 新增 `get_archived_version(page_id) -> dict`（查該 page_id `status=archived` 的列）。
- 端點：approve 前先查，若已有 archived 版本且非本 dt → 回 409/可辨識錯誤，不覆寫。
- 審查頁：`get_onenote_versioned_pages` 補回 `review_result`/`md_archive_path`/`archived_at`；渲染時若該
  page_id 任一版本 `status=archived` → 顯示橫幅 + 停用整組 approve/reject/regenerate。

### D5：審查頁接線
approve/reject 佔位改為 `requests.post(GOLD_ENDPOINT_URL, json={page_id, dt, role, action})`；成功清
`_load_versions` 快取並 rerun。沿用 silver 既有錯誤處理樣式（逾時 / 連線失敗 / 非 2xx）。

### D6：狀態流轉
approve 成功：`bronze_stored/pending_review → archived`。approve 失敗（GCS 中途錯）：C3 記 `error_msg`，
status 不翻 `archived`（比照狀態表 `archive_failed` 精神；本階段以 error_msg + 不翻 archived 表達，
不強制新增 archive_failed 值以免擴散）。reject：`→ review_closed`。

## Risks / Trade-offs

- [本機需同時起 3 個 process：streamlit / silver(8002) / gold(8003)] → CLAUDE.md 記三條啟動指令與
  `SILVER_ENDPOINT_URL`、`GOLD_ENDPOINT_URL`。
- [frontmatter date 型別] → 統一正規化為 UTC datetime；測試涵蓋 date 物件與字串兩路。
- [png 來源路徑] → 一律取 C3 `img_path`（raw-notes 權威來源），不從 md 內相對連結反推，避免路徑歧義。
- [同名把關的 race] → 單人 demo 情境足夠；端點查 + UI 停用雙層把關，先寫先贏，後到者回錯不覆寫。
- [歸檔路徑文件不一致] → 已擇 `onenote-vaults/archived-notes/`，於 proposal/design 標註；若使用者要舊
  per-user bucket 再調 `archived_note_prefix` 一處即可。
