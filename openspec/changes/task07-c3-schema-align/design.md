## Context

現行 task07 lazy_loading 已能跑通 Bronze（下載 html→算 hash→dt= 分區存 GCS→upsert C3 `bronze_stored`）、Silver（on-demand LLM enrich→存 processed-notes→`pending_review`）、Gold（approve 歸檔 archived-notes／reject 標記 `review_closed`，回寫 `md_frontmatter`）。但 C3 欄位命名與結構與交接文件定稿版不一致，且缺 `topic`（Must）等欄位。定稿 C3 見 `doc/task07_onenote_versioned_etl_hand_over_v2.md` 第 305–350 行。

約束：Python >= 3.14、pyenv + Poetry、pathlib、MongoDB upsert 冪等、unittest（非 pytest）、機密走 .env / Secret Manager、module docstring 樣板、`e_/t_/l_` 依資料本體流向歸類。跨 task copy 而非 import（維持獨立演化，沿用 task01_v2/task06_v2 慣例）。

## Goals / Non-Goals

**Goals:**
- C3 欄位命名與結構對齊定稿：hash 欄位改名、`attached_images` Object 陣列、新增 `topic`/`md_body`/dismatched/時間戳。
- `topic` 借用 task01 `TOPIC_KEYWORDS` + `_infer_topic()` 的分類邏輯。
- 修 `l_archive_note.py` 的 except 語法 bug（該檔目前 import 即 SyntaxError）。
- C1/C2 的 `html_hash` 同步改名 `html_sha_hash`，跨 collection 一致。

**Non-Goals:**
- 不改 Bronze/Silver/Gold 的行為邏輯（下載、hash 冪等、on-demand、斷路器、審查佇列篩選）。
- 不改 GCS 目錄結構與 blob 命名。
- 不做資料遷移腳本（既有 local 測試資料重建即可）。
- 不實作 task08 向量化（另案），本 change 只確保 C3 留下 task08 可用的血緣欄位。

## Decisions

### D1：hash 欄位改名，跨 C1/C2/C3 一致
`html_hash`→`html_sha_hash`、`html_md5`→`html_md5_hash`、`md_md5`→`md_md5_hash`。C1（`onenote_graph_api_logs`）、C2（`multimodal_llm_enrichment_logs`）內部函式參數名可保留 `html_hash`（僅程式區域變數），但**寫入 MongoDB 的 document key** 一律用 `html_sha_hash`，避免跨 collection join 時欄位名不一致。
- 註：交接文件 C3 Indexes 區塊（第 344 行）仍寫 `{ page_id: 1, html_hash: 1 }`，與欄位表的 `html_sha_hash` 不一致——以**欄位表為準**（`html_sha_hash`），index 名稱屬文件筆誤，於 tasks 標記待人工修文件。

### D2：`attached_images` Object 陣列取代三平行陣列
- Bronze `_store_images` 現回傳 `(img_md5, img_path)` 兩個等長 list；改在 `download_notebooks` 內 `zip` 成 `attached_images = [{"raw_image_path": p, "raw_image_md5": m}, ...]` 寫入 C3。`archived_image_path`/`archived_image_md5` 於 Bronze 階段不寫（歸檔後才有）。
- Gold `archive_note` 現產 `img_archive_paths` list；改為讀 `meta["attached_images"]`，逐一複製 `raw_image_path`→archived blob、取新 md5，回填同一 Object 的 `archived_image_path`/`archived_image_md5`，最後把整個 `attached_images` 陣列 upsert 回 C3。
- 取代 `img_md5`/`img_path`/`img_archive_path`。下游（task08 / valid_img 比對）改讀 `attached_images[].archived_image_path`。

### D3：`topic` 兩階段推導，借用 task01 分類器
- copy `task01_obsidian_etl_v2/silver_transform_markdown/t_build_metadata_docs.py` 的 `TOPIC_KEYWORDS` 常數與 `_infer_topic(tags, file_path)` 函式到 task07（Bronze 與 Gold 各自需要；置於能被兩處取用的位置，如 `task07_common` 或各自 copy，見 D6）。
- **Bronze**：此時尚無 LLM tags，以 `_infer_topic(tags=[], file_path=page_title)` 算暫定 topic 寫入（多半落 `other` 或由標題關鍵字命中）。
- **Gold/reject**：`md_frontmatter.tags` 已由 LLM 產出，以 `_infer_topic(tags, page_title)` 重算 topic 並 upsert 覆蓋，取得最佳分類（對齊 task01 topic 由 tags＋檔名推導的語意）。

### D4：`md_body`／dismatched 於 archive/reject 一併算出
解析 md 正文時（Gold `_extract_frontmatter` 附近）多算：
- `word_count = len(post.content.split())`
- `valid_img`：正文 `![]()` 連結 basename 命中歸檔／raw 圖片 basename 的數（沿用現有 `_count_valid_images`）。
- `total_img_links`：正文 `![]()` 連結總數。
- `dismatched_img_count = total_img_links - valid_img`；`md_has_dismatched_img = dismatched_img_count > 0`。
- `md_body = {"valid_img_count": valid_img, "word_count": word_count, "recomputed_at": None}`（`recomputed_at` 僅在未來因 ETL 變更重跑時才蓋值）。
- 命中圖片數**只記於** `md_body.valid_img_count`，`md_frontmatter` 不含 `valid_img`（去除定稿兩處冗餘，改以 `md_body` 單一來源，避免同值兩寫不一致）。`md_frontmatter` 僅 `tags`/`date`/`type`/`alias`。

### D5：`created_at`/`updated_at` 於 `upsert_version_meta` 集中處理
在 `task07_common/audit_log.py` 的 `upsert_version_meta` 內：一律把 `updated_at=_now_utc()` 併入 `$set`；把 `created_at=_now_utc()` 併入 `$setOnInsert`（即使呼叫端未給 `set_on_insert_fields` 也要建立 `$setOnInsert`）。呼叫端不需逐處手動帶時間戳。

### D6：topic 分類器放置位置
`TOPIC_KEYWORDS` + `_infer_topic` copy 到 `task07_common`（新增小模組，如 `topic.py`），供 Bronze 與 Gold 共用，避免同一份 copy 出現兩份漂移。此為 task07 三服務共用工具的定位（同 `gcs.py`/`hashing.py`），不違反「跨 task copy 而非 import」——是 task07 內部共用，而非 import task01。

### D7：`md_md5_hash` 語意
定稿定義 `md_md5_hash` 為「silver md 的 GCS md5」。Gold `copy_blob` 為 byte-identical server-side copy，archived md 的 md5 與 silver md 相同，故 Gold 覆寫 `md_md5_hash` 為歸檔 md5 屬同值、無害，保留現行行為（亦可視為複製正確性的驗證）。C3 不另設 archived md md5 欄位；下游 task08 CAS 可直接用 `md_md5_hash`。

## Risks / Trade-offs

- **[BREAKING data contract]** 既有 C3/C1/C2 文件欄位名改變，舊資料與新程式混用會查不到欄位。**Mitigation**：本階段為地端測試，重建測試資料即可；tasks 標記需清空或重灌 local collection。
- **[topic 於 Bronze 多為 other]** Bronze 無 tags，暫定 topic 準度低。**Mitigation**：Gold/reject 以 tags 重算為最終值；Bronze 值僅為滿足 Must 欄位的暫定佔位。
- **[偏離定稿的 valid_img 位置]** 定稿在 `md_frontmatter.valid_img` 與 `md_body.valid_img_count` 兩處列同義欄位；本實作只保留 `md_body.valid_img_count`、移除 `md_frontmatter.valid_img`，去除冗餘。**Mitigation**：下游（valid_img 分析）一律讀 `md_body.valid_img_count`；文件冗餘列為 follow-up 更正。
- **[跨 collection 改名遺漏]** C1/C2/C3 三處 `html_hash` 需一致改。**Mitigation**：以 grep 全掃 `html_hash`/`html_md5`/`md_md5` 寫入點，逐一改；unittest 斷言寫入 document 的 key 名。

## Migration Plan

1. 改 `task07_common`（audit_log 欄位名 + 時間戳 + 新增 `topic.py`）。
2. 改 Bronze（`attached_images`、topic、hash 欄位名）。
3. 改 Silver（md md5／hash 欄位名）。
4. 改 Gold（`attached_images` 回填、`md_body`/dismatched/topic 重算、修 except bug）。
5. 清空 local `onenote_note_metadata`/`onenote_graph_api_logs`/`multimodal_llm_enrichment_logs` 測試資料，端到端重跑 Bronze→Silver→Gold 驗證新欄位。
6. Rollback：欄位改名為純程式變更，`git revert` 即可；無 schema migration 需回滾。

## Open Questions

- 交接文件 Indexes 區塊 `html_hash` 筆誤是否要一併請文件維護者更正為 `html_sha_hash`（本 change 以程式為準，文件更正列為 follow-up）。
- `recomputed_at` 的觸發時機（哪些 ETL 變更算「需重跑」）未定義，先一律寫 `None`，待實際重跑需求出現再定。
