## Why

task07 lazy_loading 三套服務（Bronze ETL、`task07_silver_service`、`task07_gold_service`，共用 `task07_common`）目前寫入 `onenote_note_metadata`（C3）的欄位，與交接文件 `doc/task07_onenote_versioned_etl_hand_over_v2.md` 第 305–350 行定稿的 C3 schema 有系統性落差：欄位命名不一致（`html_hash`/`html_md5`/`md_md5` vs 定稿的 `html_sha_hash`/`html_md5_hash`/`md_md5_hash`）、圖片血緣以三個平行陣列（`img_md5`/`img_path`/`img_archive_path`）表達而非定稿的 `attached_images` Object 陣列、且完全缺少 `topic`（Must）、`md_body`、`dismatched_img_count`/`md_has_dismatched_img`、`created_at`/`updated_at` 等欄位。此外 `task07_gold_service/l_archive_note.py:51` 有一處 Python 2 式 `except ValueError, TypeError:` 語法錯誤，導致該模組無法 import。

對齊 C3 是下游向量化（task08 onenote embed，將與 task01/task06 共寫 `note_vectors_multimodal`）能以 `md_archive_path`/`archived_image_path` 為血緣鍵、以 `status=archived AND embedded_status=false` 為 gate 的前提。本 change 只對齊 task07 的資料契約與修 bug，不改 lazy loading / on-demand / 斷路器等既有行為。

## What Changes

- **欄位改名**（跨 Bronze/Silver/Gold 與 `task07_common`）：`html_hash`→`html_sha_hash`、`html_md5`→`html_md5_hash`、`md_md5`→`md_md5_hash`；silver md 欄位 `md_path`→`enriched_md_path`、`md_exported_at`→`enriched_md_exported_at`；gold 歸檔 md 欄位 `md_archive_path`→`archived_md_path`。C1（`onenote_graph_api_logs`）與 C2（`multimodal_llm_enrichment_logs`）的 `html_hash` 欄位同步改為 `html_sha_hash`，跨 collection 命名一致。（HTTP 端點回應 JSON 的 `md_path`／`md_archive_path` 鍵維持不變，僅 C3 document key 改名；審查頁 `dashboard_ui/pages/onenote_review.py` 讀 C3 的 `md_path` 同步改讀 `enriched_md_path`。）
- **圖片血緣重構為 `attached_images` Object 陣列**：Bronze 寫入 `[{raw_image_path, raw_image_md5}, ...]`；Gold 歸檔時把每個 Object 補上 `archived_image_path`、`archived_image_md5`。移除 `img_md5`/`img_path`/`img_archive_path` 三個平行陣列。
- **新增 `topic`（Must）**：借用 `task01_obsidian_etl_v2/silver_transform_markdown/t_build_metadata_docs.py` 的 `TOPIC_KEYWORDS` 與 `_infer_topic()`（copy 而非 import，維持 task 間獨立演化）。Bronze 以 `page_title` 為初判來源寫入暫定 `topic`；Gold/reject 取得 `md_frontmatter.tags` 後以 tags＋title 重算並更新。
- **新增 `md_body` Object**：`{valid_img_count, word_count, recomputed_at}`，於 archive/reject 解析 md 正文時一併算出。
- **新增 `dismatched_img_count` / `md_has_dismatched_img`**：archive/reject 時預先算好 md 內失效（連結 basename 未命中歸檔／raw 圖片）的圖片數，避免日後跨欄位比對全表掃描。
- **新增 `created_at` / `updated_at`**：於共用 `upsert_version_meta` 集中處理——每次 `$set` 蓋 `updated_at`，首次 insert 補 `created_at`。
- **修 bug**：`l_archive_note.py` 的 `except ValueError, TypeError:` 改為 `except (ValueError, TypeError):`。

## Capabilities

### New Capabilities
- `onenote-note-metadata-schema`：定稿 C3（`onenote_note_metadata`）的欄位契約——主鍵 `page_id`+`dt`、命名一致的 hash 欄位、`attached_images` Object 陣列的跨層填寫規則、`topic` 推導、`md_body`/`dismatched_img_count`/`md_has_dismatched_img` 品質欄位，以及 `created_at`/`updated_at` 稽核時間戳。

### Modified Capabilities
- `silver-enrich-endpoint`：Silver 端點 upsert C3 的 md md5 欄位由 `md_md5` 改名為 `md_md5_hash`；快取查找／hash 判定所用欄位由 `html_hash` 改名為 `html_sha_hash`。
- `gold-archive-endpoint`：歸檔複製的 png 來源與退役判定改讀 `attached_images`（取代 `img_path`）；歸檔結果寫回 `attached_images[].archived_image_path/archived_image_md5`（取代 `img_archive_path`）；`md_frontmatter` 之外新增寫入 `md_body`、`dismatched_img_count`、`md_has_dismatched_img`，並重算 `topic`。

## Impact

- **修改程式**：`task07_common/audit_log.py`（欄位改名、`upsert_version_meta` 集中補時間戳）、`task07_onenote_to_markdown_lazy_loading/e_onenote_download.py`（`attached_images` 重構、topic、欄位改名）、`task07_silver_service/t_enrich_html_to_markdown.py` 與 `l_save_markdown.py`（md md5／hash 欄位改名）、`task07_gold_service/l_archive_note.py`（`attached_images` 歸檔回填、`md_body`/dismatched/topic、修 except bug）。
- **MongoDB**：`onenote_note_metadata` 欄位契約變更（改名 + 新增）；C1/C2 的 `html_hash`→`html_sha_hash`。屬 BREAKING data-contract 變更，既有測試資料需重建或遷移。
- **不影響**：Bronze/Silver/Gold 的下載、hash 冪等、on-demand enrichment、斷路器、審查頁互動等行為邏輯；GCS 目錄結構不變。
- **下游前置**：本 change 落地後，task08 onenote embed 才能以定稿 C3 對接（另案）。
