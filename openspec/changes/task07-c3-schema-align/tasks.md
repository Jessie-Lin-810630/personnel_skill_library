## 1. task07_common：欄位名、時間戳、topic 分類器

- [x] 1.1 `audit_log.py`：C3/C1/C2 寫入 document 的 key 改名——`html_hash`→`html_sha_hash`（C1 `log_api_call`、C2 `log_enrichment_call`、C3 相關查詢）、`html_md5`→`html_md5_hash`、`md_md5`→`md_md5_hash`；`find_cached_md_by_hash`／`count_regenerate` 等查詢條件同步改名
- [x] 1.2 `audit_log.py` `upsert_version_meta`：一律把 `updated_at=_now_utc()` 併入 `$set`、`created_at=_now_utc()` 併入 `$setOnInsert`（即使呼叫端未給 set_on_insert 也建立）
- [x] 1.3 新增 `task07_common/topic.py`：copy task01 `t_clean_obsidian` 的 `TOPIC_KEYWORDS` 與 `infer_topic(tags, file_name)`，補符合規範的 module docstring
- [x] 1.4 unittest：`upsert_version_meta` 首次 insert 補 `created_at`+`updated_at`、後續 `$set` 帶 `updated_at`；`infer_topic` 命中／全不中回 `other`（在 gold 測試涵蓋）

## 2. Bronze ETL：attached_images、topic、hash 欄位名

- [x] 2.1 `e_onenote_download.py` `download_notebooks`：成功路徑把 `img_md5`/`img_path` `zip` 成 `attached_images=[{raw_image_path, raw_image_md5}, ...]` 寫入；移除 `img_md5`/`img_path`/`img_archive_path` 平行陣列
- [x] 2.2 `download_notebooks`：`html_hash`→`html_sha_hash`、`html_md5`→`html_md5_hash` 寫入鍵改名；失敗路徑 set_on_insert 的 `attached_images=[]`、md md5 欄位改 `md_md5_hash`、補 md_body/dismatched 占位
- [x] 2.3 `download_notebooks`：以 `infer_topic([], page_title)` 算 `topic` 寫入（bronze 無 tags）
- [x] 2.4 unittest：Bronze 成功／失敗路徑 upsert 的 document 含 `html_sha_hash`/`html_md5_hash`/`attached_images`(raw 端)/`topic`，不含舊欄位名

## 3. Silver：md md5／hash 欄位名

- [x] 3.1 `t_enrich_html_to_markdown.py`：讀 `meta["html_sha_hash"]`、cache 查找對齊；upsert `md_md5`→`md_md5_hash`；圖片來源改讀 `attached_images[].raw_image_path`
- [x] 3.2 `l_save_markdown.py` `save_enriched_md`：upsert 的 `md_md5`→`md_md5_hash`
- [x] 3.3 unittest：cache hit／miss 兩路徑 upsert 的 document 使用 `md_md5_hash`

## 4. Gold：attached_images 回填、md_body/dismatched、topic 重算、修 bug

- [x] 4.1 `l_archive_note.py`：修 `except ValueError, TypeError:`→`except (ValueError, TypeError):`
- [x] 4.2 `archive_note`：png 複製來源改讀 `meta["attached_images"][].raw_image_path`；把每個 Object 回填 `archived_image_path`/`archived_image_md5`，整個 `attached_images` upsert 回 C3；移除 `img_archive_path`（C3 端）；md md5 欄位 `md_md5`→`md_md5_hash`
- [x] 4.3 新增 `_count_img_links` 總連結數 helper，`_build_md_quality_meta` 算 `word_count`、`valid_img`、`dismatched_img_count`、`md_has_dismatched_img`，組 `md_body`
- [x] 4.4 `archive_note`：以 `infer_topic(md_frontmatter["tags"], page_title)` 重算 `topic`，與 `md_frontmatter`/`md_body`/dismatched 一併 upsert
- [x] 4.5 `reject_note`：同 4.2–4.4，圖片 basename 比對來源改 `attached_images[].raw_image_path`，寫入 `md_body`/dismatched/重算 `topic`
- [x] 4.6 `退役同頁` 與快取判定的 `html_hash`→`html_sha_hash`
- [x] 4.7 unittest：approve 後 `attached_images` 含 archived 端、`md_body`/`dismatched_img_count`/`md_has_dismatched_img`/`topic` 正確；reject 同；模型改壞圖片時 valid/dismatched 計數正確

## 5. 收尾

- [x] 5.1 全域 grep 確認無殘留 `html_hash`/`html_md5`/`md_md5`/`img_path`/`img_md5`/`img_archive_path` 作為 C3 document key 的寫入點（HTTP response dict 的 `img_archive_path` 屬端點回應契約、非 C3，保留）
- [ ] 5.2 清空 local `onenote_note_metadata`/`onenote_graph_api_logs`/`multimodal_llm_enrichment_logs`，端到端重跑 Bronze→Silver→Gold（approve 與 reject 各一），核對新欄位（需真實 GCS/Mongo/LLM，待人工實跑）
- [x] 5.3 `poetry run python -m unittest discover -s tests` 全綠（141 tests）
- [ ] 5.4 （文件 follow-up，非本 change 程式範圍）提醒維護者更正交接文件 Indexes 區塊 `html_hash`→`html_sha_hash`
