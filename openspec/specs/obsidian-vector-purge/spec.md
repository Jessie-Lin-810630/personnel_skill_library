# obsidian-vector-purge Specification

## Purpose
TBD - created by archiving change task06-v2-embed-purge. Update Purpose after archive.
## Requirements

### Requirement: 消費軟刪除訊號清除對應向量

系統 SHALL 挑出 `obsidian_note_metadata` 中 `status="deleted"` 且 `embedded_status=true` 的筆記（task01_v2 軟刪除且其向量仍存在者），對每筆以 `delete_many({raw_md_path})` 清除 `note_vectors_multimodal` 中對應向量。purge 只動 `note_vectors_multimodal`，MUST NOT 刪除 `obsidian_note_metadata` 文件或其 archived 副本。

#### Scenario: 已向量化的被刪筆記其向量被清

- **WHEN** 一筆記 `status="deleted"` 且 `embedded_status=true`
- **THEN** `note_vectors_multimodal` 中該 `raw_md_path` 的所有 chunk 被刪除，該 metadata 文件與 archived 副本保留

### Requirement: purge 後翻旗標且不重複挑出

系統 SHALL 在清除某筆記向量後，把該 `obsidian_note_metadata` 文件的 `embedded_status` 翻回 `false`，使其於後續「`status=deleted AND embedded_status=true`」查詢時不再被挑出。purge SHALL 冪等：已清過（`embedded_status=false`）的被刪筆記重跑不再處理。

#### Scenario: 清完翻旗標

- **WHEN** 某被刪筆記向量清除完成
- **THEN** 其 `embedded_status` 翻為 `false`

#### Scenario: 重跑冪等

- **WHEN** 對已 purge（`status="deleted"` 且 `embedded_status=false`）的筆記再次執行 purge
- **THEN** 該筆記不被挑出、不重複 delete_many、旗標不再變動
