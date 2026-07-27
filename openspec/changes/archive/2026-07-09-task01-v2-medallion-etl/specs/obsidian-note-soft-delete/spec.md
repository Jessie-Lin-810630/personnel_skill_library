## ADDED Requirements

### Requirement: raw 筆記消失時對 metadata 做軟刪除

系統 SHALL 在 Silver 執行時偵測「`obsidian_note_metadata` 存在某 `raw_md_path`、但該 `.md` 已不在 `raw-notes/` 的 live listing」的情形（rsync 刪除所致），並將該筆記 metadata 的 `status` 標為 `deleted`。系統 MUST NOT 硬刪該 metadata 文件（保留供稽核），且 MUST NOT 刪除 `archived-notes/` 下的 archived 副本。偵測 SHALL 冪等：已為 `deleted` 者重跑不改變其他欄位。

#### Scenario: 偵測被刪筆記並軟刪除

- **WHEN** 某 `raw_md_path` 在 DB 存在，但本次 `raw-notes/` live listing 不含該路徑
- **THEN** 該 metadata 文件 `status` 被設為 `deleted`，文件與 archived 副本均保留

#### Scenario: 未被刪筆記不受影響

- **WHEN** 某 `raw_md_path` 仍存在於 live listing
- **THEN** 其 `status` 不被改為 `deleted`

#### Scenario: 軟刪除重跑冪等

- **WHEN** 對已 `status="deleted"` 的筆記再次執行 Silver
- **THEN** 該文件維持 `deleted`，不重複異動時間戳或其他欄位

### Requirement: 對 task06 曝露向量 purge 訊號

系統 SHALL 讓下游 task06 能以一致查詢辨識「已軟刪除且其向量仍存在」的筆記——即 `status="deleted"` 且 `embedded_status=true` 的文件——作為需 purge 對應向量的訊號。task06 完成向量清除後 SHALL 能將該文件標記為已清（例如翻回 `embedded_status=false`），使其不再被重複挑出。本 change 僅定義此資料契約，task06 實作另立 change。

#### Scenario: 已向量化的被刪筆記被挑為待 purge

- **WHEN** 一筆記 `status="deleted"` 且 `embedded_status=true`
- **THEN** task06 以該條件查詢時 SHALL 能挑出此文件作為待 purge 向量對象

#### Scenario: purge 完成後不再被挑出

- **WHEN** task06 清除對應向量並將該文件標記為已清（`embedded_status=false`）
- **THEN** 後續以「`status="deleted"` 且 `embedded_status=true`」查詢時不再包含此文件
