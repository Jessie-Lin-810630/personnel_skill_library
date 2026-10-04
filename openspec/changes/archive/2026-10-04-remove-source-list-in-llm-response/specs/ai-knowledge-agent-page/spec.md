## MODIFIED Requirements

### Requirement: Sources displayed under agent response
當 agent 回傳非空的 `sources` 清單時，Page 3 SHALL 在回應氣泡下方顯示可展開的「📎 來源筆記」欄位，內含每筆來源的 `file_name`、`section`、`score`。RAG agent 回傳的 `answer` 正文 SHALL NOT 包含由模型自行列出的來源清單，來源資訊只透過「📎 來源筆記」呈現，使同一則回應中的來源只出現一次。

#### Scenario: Agent returns sources
- **WHEN** `rag_query()` 或 `generate_learning_map()` / `refine_learning_map()` 回傳非空 `sources`
- **THEN** 回應氣泡下方顯示「📎 來源筆記」expander，展開後列出各 source 的 file_name、section、score

#### Scenario: Agent returns no sources
- **WHEN** agent 回傳空 `sources`（例如向量搜尋無結果）
- **THEN** 回應氣泡下方不顯示 expander

#### Scenario: RAG answer omits source list
- **WHEN** 使用者在新對話中提出筆記查詢，`rag_query()` 檢索到 chunk 並回傳模型生成的 `answer`
- **THEN** `answer` 正文不以「來源：」開頭的段落列出檔案名稱與章節，回應氣泡中的來源只出現在「📎 來源筆記」
