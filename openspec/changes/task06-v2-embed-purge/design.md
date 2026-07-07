## Context

現行 `task06_obsidian_embed_etl` 吃 v1 的 `obsidian_notes`（`get_notes_state()` 讀 `{file_path: {file_md5_hash, embedding_done}}`），從 GCS raw `.md` 重新下載、chunk、多模態 embed（`gemini-embedding-2`、1536 維、L2 normalize），寫 `obsidian_vectors_multimodal`，再以帶 `file_md5_hash` 守衛的 CAS 翻 `embedding_done=true`＋蓋 `embedded_at`（見 `task06_obsidian_embed_etl/l_load_to_mongodb.py`）。

task01_v2 改用 medallion：`obsidian_note_metadata`（鍵 `raw_md_path`，含 `status`/`embedded_status`/`archived_md_path`/`archived_md_md5_hash`/內嵌 `attached_images` 的 archived 路徑）＋ `archived-notes/` 乾淨層＋軟刪除訊號（`status="deleted"`）。本 change 建 task06 v2 對接這套契約，並實作 task01-v2 6.2 的 purge 消費端。

約束：Python >= 3.14、pyenv + Poetry、pathlib、MongoDB upsert 冪等、unittest（非 pytest）、機密走 .env / Secret Manager、module docstring 樣板、`e_/t_/l_` 依資料本體流向歸類。

## Goals / Non-Goals

**Goals:**
- Embedding gate 改讀 `obsidian_note_metadata`（`status=archived AND embedded_status=false`）
- 從 archived 層（`archived_md_path` + `archived_image_path`）做多模態 embedding，來源乾淨且與 raw 隔離
- 寫 v2 專用 `obsidian_vectors_v2`，per-note 先刪後插、`archived_md_md5_hash` 守衛 CAS 翻 `embedded_status`
- purge 消費軟刪除訊號：清 `obsidian_vectors_v2` 對應向量後翻 `embedded_status=false`

**Non-Goals:**
- 不改現行 `task06_obsidian_embed_etl`、`obsidian_notes`、`obsidian_vectors_multimodal`、`embedding_done`
- 不改 dashboard 檢索端（若要改讀 v2 向量另議）
- 不自建 Atlas Vector Search index（手動於 Console 建，同 v1 慣例）
- chunking/embedding 演算法不重新設計，沿用 v1

## Decisions

### D1：新資料夾並存、chunk/embed copy 沿用
`task06_obsidian_embed_etl_v2/`（`e_/t_/l_/main.py`）與 v1 並存。chunking、`gemini-embedding-2` 呼叫、L2 normalize、`title: {title} | text: {content}` prompt 等 copy 自 v1（copy 而非 import，讓 v1/v2 獨立演化做對照，沿用 task01_v2/task06 既有慣例）。
- 替代方案：抽共用 embedding 模組 → 否決，耦合兩個要對照的設計。

### D2：向量血緣鍵用 raw_md_path
`obsidian_vectors_v2` 每筆 chunk 帶 `raw_md_path`（note 的唯一鍵，對齊 `obsidian_note_metadata` 主鍵），purge 與先刪後插都以 `delete_many({raw_md_path})`。v1 用 `file_path`，v2 用 `raw_md_path` 保持與 metadata 主鍵一致、好推理。

### D3：embedding 完全走 archived 層
內文取 `archived_md_path`、圖片取 `attached_images[].archived_image_path`。archived 是人工/品質把關後的隔離層，確保 embedding 來源穩定、且未來插入 silver LLM enrichment 時不會拿到半熟 raw。
- 圖片以 `Part.from_uri(gs://...archived...)` 送入，沿用 v1 私有 bucket 由 Vertex AI 直讀。

### D4：CAS 守衛欄位對齊 v2
v1 用 `file_md5_hash` 守衛，v2 改用 `archived_md_md5_hash`（本次 embed 的 archived 版本）。CAS 條件：`{raw_md_path, embedded_status: false, archived_md_md5_hash: <本次版本>}` → `{$set: {embedded_status: true, embedded_at: now}}`。未命中代表 embed 期間又重歸檔，留待下輪。

### D5：purge 與 embedding 同一次執行、先 embed 後 purge
`main` 內先跑 embedding gate、再跑 purge（或反序皆可，兩者作用集合不相交：embedding 挑 archived+false、purge 挑 deleted+true）。purge 以 `delete_many({raw_md_path})` 清向量後，CAS/直接 `update_one` 翻 `embedded_status=false`。
- purge 翻 false 是「已清、不再挑出」語意；與 embedding 端「false=待做」語意一致（deleted 的筆記 status 仍是 deleted，不會被 embedding gate 誤挑）。

### D6：embedded_status 雙語意由 status 區隔
task01-v2 design 曾留 open question：`embedded_status=false` 同時代表「待 embedding」與「purge 已完成」。以 `status` 區隔即可，不需額外 `vectors_purged` 旗標：
- embedding gate 條件含 `status="archived"` → deleted 的筆記即使 `embedded_status=false` 也不會被 embedding 誤挑。
- purge 條件含 `status="deleted"` → archived 的筆記不會被 purge 誤挑。
兩端條件的 `status` 互斥，`embedded_status` 布林足以承載，無需新欄位。

## Risks / Trade-offs

- **[依賴 task01_v2 尚未 live 落地]** 沒有 archived 資料與 metadata 就無從 embedding。**Mitigation**：本 change 可先完成程式與單元測試（mock GCS/Mongo/Vertex），實跑待 task01_v2 8.2 端到端後接。
- **[Atlas Vector Search index 未建]** `obsidian_vectors_v2` 需手動建 index 才能檢索。**Mitigation**：tasks 列為手動步驟；embedding 寫入本身不依賴 index。
- **[chunk/embed 規則與 v1 漂移]** copy 後 v1/v2 各自演化。**Mitigation**：刻意的對照設計，差異記 work log。
- **[purge 與 embedding 競態]** 同一筆記若在一次執行中既 archived 又被標 deleted（理論上不會，status 單一）。**Mitigation**：status 為單一值、兩 gate 互斥，不會同時命中。
- **[多模態逐 chunk 呼叫成本]** 沿用 v1 每 chunk 一次 `embed_content`。**Mitigation**：gate 已限縮到 `embedded_status=false`，只對新/未做者燒 API。

## Migration Plan

1. task01_v2 先 live 跑出 archived 資料與 `obsidian_note_metadata`（embedded_status 初始 false）。
2. Atlas Console 手動建 `obsidian_vectors_v2` 的 Vector Search index（1536 維、cosine，filter 欄位視需要）。
3. 首跑 task06 v2 embedding：全部 archived+false → 全量 embed（一次性），之後穩態只做增量。
4. 軟刪除發生後，purge 端清理對應向量。
5. Rollback：v2 完全獨立（新資料夾、新 collection），停跑即可，不影響 v1。

## Open Questions

- `obsidian_vectors_v2` 的 Vector Search index 要 filter 哪些欄位（tags / note_type / topic）→ 依 dashboard v2 檢索需求再定，先建最小 vector-only index。
- dashboard 何時切到讀 v2 向量 → 另議，非本 change 範圍。
- 是否要記錄 purge 事件的稽核（何時清了哪些 raw_md_path）→ 可先靠 loguru，日後需要再落 collection。
