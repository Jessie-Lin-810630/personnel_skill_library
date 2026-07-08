## Context

task06_v2（`task06_obsidian_embed_etl_v2`）對 Obsidian：gate 讀 `obsidian_note_metadata`（`status=archived AND embedded_status=false`）、依 `archived_md_path` 從 `personal-vaults/archived-notes/` 取 md、圖片走 wiki-link `![[x.png]]`＋`_attachment/`、以 `raw_md_path` 為 `obsidian_vectors_v2` 血緣鍵、`archived_md_md5_hash` 守衛 CAS 翻 `embedded_status`，並有 `status=deleted` 的軟刪除 purge。

task07 對 OneNote：C3 `onenote_note_metadata`（主鍵 `page_id`+`dt`）、bucket `onenote-vaults`、歸檔 md 在 `archived_md_path`、圖片在 `attached_images[].archived_image_path`（markdown `![](_images/<檔名>)` 語法、`_images/` 目錄）、archived md 指紋 `md_md5_hash`、無軟刪除。

兩來源最終要寫入**同一張** `obsidian_vectors_v2`（同一 Atlas Vector Search index），供同一 RAG 檢索。

約束：Python >= 3.14、pyenv + Poetry、pathlib、MongoDB upsert 冪等、unittest（非 pytest）、機密走 .env / Secret Manager、module docstring 樣板、`e_/t_/l_` 依資料本體流向歸類、跨 task copy 而非 import。

## Goals / Non-Goals

**Goals:**
- 獨立 task08，chunk/embed/normalize copy 自 task06_v2，替換 ingestion 與圖片解析。
- gate 讀 `onenote_note_metadata`（`status=archived AND embedded_status=false`）。
- 內容/圖片全走 archived 層（人工核可後），bucket `onenote-vaults`。
- 寫入共用 `obsidian_vectors_v2`，血緣欄 `md_path`=`archived_md_path` 值、`image_paths`=archived 圖片路徑。
- `md_md5_hash` 守衛 CAS 翻 `onenote_note_metadata.embedded_status`。

**Non-Goals:**
- 不動 task06_v2、`obsidian_note_metadata`、task07 三服務。
- 不實作 purge（OneNote 無 `deleted` 軟刪除）。
- 不自建 Atlas Vector Search index（沿用 `obsidian_vectors_v2` 既有 index）。
- 不在本分支改 task06_v2 的 `raw_md_path`→`md_path`（另分支處理）。
- chunk/embed 演算法不重新設計，copy 沿用。

## Decisions

### D1：獨立 task08，不參數化 task06_v2
新資料夾 `task08_onenote_embed_etl/`。chunk（header + recursive）、`gemini-embedding-2` 呼叫、L2 normalize、`title: {title} | text: {content}` prompt 由 task06_v2 copy。
- 替代方案：把 task06_v2 參數化成 source adapter（collection/bucket/圖片語法/血緣鍵/purge 全可切換）→ 否決。圖片語法（wiki-link vs markdown）、bucket、collection、有無 purge 四項全異，塞進單一 pipeline 會產生大量分支且破壞 v1/v2 隔離文化。

### D2：血緣鍵＝archived 路徑，欄位名 md_path，不設 source 判別欄
`obsidian_vectors_v2` 存入的來源路徑在 RAG（feature/dashboard-ui）作為「先指定資料源檔案」的檢索過濾鍵；業務上該來源必須是**人工核可/清理過**的 archived md 與 archived 圖片，不可用 raw/html/silver-未歸檔檔，否則檢索會誤以為拿未核可檔過濾。
- task08 向量 doc 血緣欄命名 `md_path`，值＝`archived_md_path`；`image_paths`＝`attached_images[].archived_image_path`。
- `archived_md_path` 為完整 gs:// URI，OneNote（`onenote-vaults`）與 Obsidian（`personal-vaults`）bucket 不同 → 全域唯一，故**不需** source 判別欄即可當 vectors 與兩張 metadata 的 join 鍵。
- **過渡期**：task06_v2 目前仍寫 `raw_md_path`（值為 raw 路徑）。task08 寫 `md_path`（值為 archived 路徑）。兩欄位名於 `obsidian_vectors_v2` 暫時並存；未來由**另一分支**把 task06_v2 的 `raw_md_path`→`md_path`、值改存 archived 路徑，收斂為單一欄位。本分支不碰 task06_v2。RAG 端需知悉此過渡。

### D3：圖片解析改 OneNote markdown 語法
task06_v2 的 `_resolve_chunk_images` 抓 `![[x.png]]` 並拼 `_attachment/`。task08 改抓標準 markdown `![alt](_images/<檔名>)`（task07 silver `convert_img_tag_to_md_str` 產出的語法），圖片在該 md 同層 `_images/` 目錄。
- 圖片來源優先用 gate 帶出的 `attached_images[].archived_image_path`（已知精確路徑、已存在），以 basename 對上 chunk 內連結；避免重推路徑。無對應 basename 者略過並記 warning。

### D4：gate 與 CAS 對齊 OneNote 主鍵與欄位
- gate 投影：`page_id`、`dt`、`archived_md_path`、`md_md5_hash`、`md_frontmatter`、`page_title`、`attached_images`。
- CAS：`onenote_note_metadata.update_one({archived_md_path: <本次 archived 路徑>, embedded_status: false, md_md5_hash: <本次版本>}, {$set: {embedded_status: true, embedded_at: now}})`。`archived_md_path` 全域唯一、可唯一定位一個 (page_id, dt) 版本，故用它當 CAS 過濾鍵，等同以 (page_id, dt) 定位，且 load 層天然持有此值不需另湊主鍵。未命中代表 embedding 期間又重歸檔（`md_md5_hash` 變），留待下輪。
- `md_md5_hash` 為 archived md 指紋；archived md 由 silver md server-side byte copy 而來，md5 相同，作為守衛穩定。

### D5：先刪後插以 md_path 為鍵
per-note `delete_many({md_path: <archived 路徑>})` → `insert_many`（重切後 chunk 數變動不留孤兒、重跑冪等）。與 task06_v2 的 `delete_many({raw_md_path})` 同語意、不同欄位名（過渡期並存，見 D2）。

### D6：向量 doc 結構對齊 task06_v2（欄位名差異最小）
每筆 chunk：`md_path`、`file_name`（＝`page_title`）、`chunk_index`、`chunk_total`、`tags`、`note_type`（＝`md_frontmatter.type`）、`date`、`section`、`content`、`image_paths`、`embedding`。與 task06_v2 差異僅血緣欄名（`md_path` vs `raw_md_path`）。Atlas Vector Search index 只索引 `embedding`（＋選填 filter 欄），欄名差異不影響 index 本身。

### D7：無 purge
OneNote 版本以 `review_closed`（rejected/overwritten）退役、非 `status=deleted`；archived 版本不會被軟刪除。故 task08 `main` 只做 embedding，不含 purge 端。若未來 OneNote 引入軟刪除語意再另議。

## Risks / Trade-offs

- **[依賴 task07 C3 對齊未落地]** 需 `task07-c3-schema-align` 先落地才有 `archived_md_path`/`attached_images[].archived_image_path`/`md_md5_hash`。**Mitigation**：本 change 可先完成程式與 unittest（mock GCS/Mongo/Vertex），實跑待 C3 對齊 live。
- **[過渡期兩血緣欄名並存]** `obsidian_vectors_v2` 同時有 `raw_md_path`（task06）與 `md_path`（task08）。**Mitigation**：D2 記為明確跨分支待辦；RAG 端過渡期查兩欄；task06 改名後收斂。
- **[chunk/embed 與 task06_v2 漂移]** copy 後各自演化。**Mitigation**：刻意的對照設計，差異記 work log；向量 doc 結構刻意對齊以確保同 index 可用。
- **[圖片 basename 撞名]** 不同 section 的 `_images/` 可能同名 png，但 task08 以「該 md 帶出的 `attached_images` archived 路徑」對 basename，範圍限該筆記，不跨筆記。
- **[多模態逐 chunk 呼叫成本]** 沿用 task06_v2 每 chunk 一次 `embed_content`。**Mitigation**：gate 限縮到 `embedded_status=false`，只對新/未做者燒 API。

## Migration Plan

1. `task07-c3-schema-align` 先 live，跑出 archived 資料與對齊後 C3。
2. 建 `task08_onenote_embed_etl/`，copy task06_v2 的 chunk/embed/normalize，替換 gate（onenote_note_metadata）、圖片解析（markdown `![]()`）、bucket（onenote-vaults）、血緣欄（md_path）。
3. 首跑 embedding：全部 archived+false → 全量 embed，之後穩態增量。
4. Rollback：task08 完全獨立（新資料夾、共用既有 vectors collection），停跑即可，不影響 task01/06/07。

## Open Questions

- `obsidian_vectors_v2` 過渡期是否要在 Atlas index 的 filter 欄同時涵蓋 `raw_md_path` 與 `md_path` → 依 RAG 檢索需求定，本 change 只保證寫入。
- task06_v2 的 `raw_md_path`→`md_path` 改名何時由哪個分支執行 → 跨分支協調，非本 change。
- OneNote 未來若需「來源已刪 → 清向量」語意，是否補 task08 purge → 待軟刪除需求出現再議。
