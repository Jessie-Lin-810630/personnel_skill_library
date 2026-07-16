# 單元測試報告 — dashboard_ui/agent_tools & agents

**日期**：2026-06-06  
**Branch**：`feature/dashboard-ui`  
**測試執行結果**：**102 tests, 0 failures, 0 errors — OK**

---

## 一、受測腳本與函式一覽

| 受測腳本 | 函式 | 測試檔案 |
|---|---|---|
| `dashboard_ui/agent_tools/chat_history.py` | `load_chat_history()` | `tests/test_dashboard_chat_history.py` |
| `dashboard_ui/agent_tools/chat_history.py` | `save_chat_history()` | `tests/test_dashboard_chat_history.py` |
| `dashboard_ui/agent_tools/query_with_vector_search.py` | `vector_search()` | `tests/test_dashboard_vector_search.py` |
| `dashboard_ui/agents/rag_agent.py` | `_build_context()` | `tests/test_dashboard_rag_agent.py` |
| `dashboard_ui/agents/rag_agent.py` | `_build_source_list()` | `tests/test_dashboard_rag_agent.py` |
| `dashboard_ui/agents/rag_agent.py` | `rag_query()` | `tests/test_dashboard_rag_agent.py` |
| `dashboard_ui/agents/intent_router_agent.py` | `_r1_keyword_match()` | `tests/test_dashboard_intent_router_agent.py` |
| `dashboard_ui/agents/intent_router_agent.py` | `_r2_llm_classify()` | `tests/test_dashboard_intent_router_agent.py` |
| `dashboard_ui/agents/intent_router_agent.py` | `route()` | `tests/test_dashboard_intent_router_agent.py` |

---

## 二、測試項目明細

### 2-1 `load_chat_history()` — 9 個測試

函式職責：讀取指定 session + agent_type 最近 N 輪對話，回傳格式對齊 Google GenAI SDK `contents` 參數。

| # | 測試名稱 | 驗證重點 | 標記 |
|---|---|---|---|
| 1 | `test_returns_empty_list_when_no_history` | MongoDB 無紀錄時回傳 `[]` 而非 `None` | 必要 |
| 2 | `test_query_filter_includes_session_id_and_agent_type` | `find()` filter 必須同時包含 `session_id` 與 `agent_type` 兩個條件，避免跨 agent 資料污染 | 必要 |
| 3 | `test_projection_excludes_id_and_includes_role_and_content` | projection `{"_id": 0, "role": 1, "content": 1}` 正確，不回傳多餘欄位 | 必要 |
| 4 | `test_sort_is_descending_on_timestamp` | 以 `timestamp` 降冪（DESCENDING = -1）取最新的 N 筆 | 必要 |
| 5 | `test_limit_is_n_times_2` | 預設 `n=3` 時 `limit = 6`（1 輪 = 1 user + 1 model） | 必要 |
| 6 | `test_return_format_matches_google_genai_contents_schema` | 每筆格式為 `{"role": ..., "parts": [{"text": ...}]}`，可直接送進 Vertex AI API | 必要 |
| 7 | `test_returns_docs_in_chronological_ascending_order` | DB 取出後呼叫 `.reverse()`，確保最終順序是舊→新 | 必要 |
| 8 | `test_custom_n_sets_limit_to_n_times_2` | n 為非預設值（如 5）時，limit 仍正確為 n×2 | **[提案]** |
| 9 | `test_each_content_mapped_to_parts_text_field` | content 欄位對應的 key 名稱確實是 `"text"` 而非其他 | **[提案]** |

---

### 2-2 `save_chat_history()` — 12 個測試

函式職責：寫入一筆對話紀錄，含兩層安全防護（單筆 2000 字元截斷、session 100 筆上限）。
刪除最舊一筆使用 `find_one(sort=[("timestamp", 1)])` 取回 dict，再以其 `_id` 呼叫 `delete_one`。

| # | 測試名稱 | 驗證重點 | 標記 |
|---|---|---|---|
| 1 | `test_message_over_2000_chars_is_truncated_to_2000` | 超過 2000 字元的 message 自動截斷至 2000 | 必要 |
| 2 | `test_message_exactly_2000_chars_is_not_truncated` | 邊界值：剛好 2000 字元**不應**截斷 | **[提案]** |
| 3 | `test_message_under_2000_chars_is_not_truncated` | 短訊息原樣儲存，不截斷 | 必要 |
| 4 | `test_session_below_100_limit_does_not_call_delete` | count=99 時不呼叫 `delete_one` | 必要 |
| 5 | `test_session_exactly_at_100_limit_deletes_oldest_before_insert` | count=100（觸發邊界）呼叫 `delete_one` 刪最舊一筆，再 `insert_one` | 必要 |
| 6 | `test_session_over_100_limit_also_deletes_oldest` | count=101（資料不一致情境）同樣觸發刪除 | **[提案]** |
| 7 | `test_find_one_uses_ascending_sort_to_locate_oldest_doc` | `find_one` 的 filter 為 `{"session_id": ...}`、sort 為 `[("timestamp", 1)]`（升序取最舊） | **[提案]** |
| 8 | `test_delete_one_uses_id_returned_by_find_one` | `delete_one` 的 filter 使用 `find_one` 回傳 doc 的 `_id`，確保刪對那一筆 | **[提案]** |
| 9 | `test_inserted_doc_contains_all_required_fields` | 寫入 doc 包含 `session_id, agent_type, role, content, timestamp, metadata` 六欄 | 必要 |
| 10 | `test_metadata_defaults_to_empty_dict_when_none` | `metadata=None` 時儲存為 `{}` 而非 `None` | 必要 |
| 11 | `test_metadata_is_stored_as_provided_when_given` | 傳入非 None 的 metadata dict 時原樣寫入 | **[提案]** |
| 12 | `test_truncated_content_preserved_first_2000_chars` | 截斷保留的是**前** 2000 字元，而非末段 | **[提案]** |

---

### 2-3 `vector_search()` — 21 個測試

函式職責：接收自然語言 query → OpenAI embedding → 組裝 MongoDB Atlas `$vectorSearch` pipeline → 執行並回傳 top-K chunk。

#### OpenAI Embedding

| # | 測試名稱 | 驗證重點 | 標記 |
|---|---|---|---|
| 1 | `test_openai_embedding_called_with_query_text_and_correct_model` | mock OpenAI client，確認呼叫 `embeddings.create(model="text-embedding-3-small", input=[query], encoding_format="float")` | 必要 |

#### Pipeline 結構

| # | 測試名稱 | 驗證重點 | 標記 |
|---|---|---|---|
| 2 | `test_pipeline_contains_exactly_two_stages` | `aggregate()` 收到的 pipeline 恰好兩個 stage | 必要 |
| 3 | `test_first_stage_is_vectorsearch` | stage[0] 為 `$vectorSearch` | 必要 |
| 4 | `test_second_stage_is_project` | stage[1] 為 `$project` | 必要 |

#### $vectorSearch Stage

| # | 測試名稱 | 驗證重點 | 標記 |
|---|---|---|---|
| 5 | `test_vectorsearch_stage_uses_correct_index_name` | `index = "obsidian_vectors_index"` | 必要 |
| 6 | `test_vectorsearch_stage_path_targets_embedding_field` | `path = "embedding"` | 必要 |
| 7 | `test_vectorsearch_stage_query_vector_matches_openai_output` | `queryVector` 等於 OpenAI mock 回傳的 vector，確保 embedding 結果有正確流入 pipeline | 必要 |
| 8 | `test_vectorsearch_stage_num_candidates_is_10x_top_k` | `numCandidates = top_k × 10`（Atlas 官方建議） | 必要 |
| 9 | `test_vectorsearch_stage_limit_equals_top_k` | `limit = top_k` | 必要 |

#### Filter 條件

| # | 測試名稱 | 驗證重點 | 標記 |
|---|---|---|---|
| 10 | `test_no_filter_key_when_no_filter_args_provided` | 不傳 filter 時，`$vectorSearch` stage **不含** `"filter"` key | 必要 |
| 11 | `test_filter_tags_adds_tags_filter_to_vectorsearch_stage` | `filter_tags="MySQL"` → `filter.tags = "MySQL"`，且不含 `note_type` | 必要 |
| 12 | `test_filter_note_type_adds_note_type_filter_to_vectorsearch_stage` | `filter_note_type="knowledge_summary"` → `filter.note_type = "knowledge_summary"`，且不含 `tags` | 必要 |
| 13 | `test_both_filters_merged_into_single_filter_dict` | 同時傳兩個 filter 時，合併為同一 dict 而非後者覆蓋前者 | **[提案]** |

#### numCandidates 上限

| # | 測試名稱 | 驗證重點 | 標記 |
|---|---|---|---|
| 14 | `test_num_candidates_capped_at_10000_for_large_top_k` | `top_k=2000` → `numCandidates` 不超過 Atlas 上限 10,000 | **[提案]** |
| 15 | `test_num_candidates_not_capped_when_top_k_is_small` | `top_k=10` → `numCandidates = 100`，不觸發上限 | **[提案]** |

#### $project Stage

| # | 測試名稱 | 驗證重點 | 標記 |
|---|---|---|---|
| 16 | `test_project_stage_excludes_id` | `_id: 0` | 必要 |
| 17 | `test_project_stage_includes_required_content_fields` | `file_name, file_path, section, content, tags, note_type` 六欄均為 `1` | 必要 |
| 18 | `test_project_stage_score_uses_vectorsearchscore_meta` | `score: {"$meta": "vectorSearchScore"}` | 必要 |
| 19 | `test_project_stage_does_not_include_embedding_field` | `embedding` 欄位**不在** $project 中（省傳輸量） | **[提案]** |

#### 回傳值

| # | 測試名稱 | 驗證重點 | 標記 |
|---|---|---|---|
| 20 | `test_returns_aggregate_results_as_list` | aggregate 結果正確包裝為 list 回傳 | 必要 |
| 21 | `test_returns_empty_list_when_no_matching_chunks` | 無相關 chunk 時回傳 `[]` 而非 `None` | **[提案]** |

---

---

### 2-4 `rag_agent.py` — 47 個測試

#### `_build_context()` — 7 個測試

函式職責：將 `vector_search()` 回傳的 top-K chunk list 組裝為純文字 context block，每段標注來源編號、檔名與章節。

| # | 測試名稱 | 驗證重點 | 標記 |
|---|---|---|---|
| 1 | `test_empty_chunks_returns_empty_string` | 空 list 輸入回傳 `""` 而非 `None` 或拋出例外 | 必要 |
| 2 | `test_single_chunk_header_contains_file_name_and_section` | header 格式：`[來源 1] 檔案: {file_name}｜章節: {section}` | 必要 |
| 3 | `test_single_chunk_body_contains_content` | chunk 的 `content` 欄位完整出現在輸出中 | 必要 |
| 4 | `test_source_numbering_starts_at_1` | 多個 chunk 時，編號從 1 開始依序遞增 | 必要 |
| 5 | `test_multiple_chunks_joined_with_double_newline` | 各 chunk block 以 `\n\n` 分隔，分成 2 個 part | 必要 |
| 6 | `test_header_and_content_separated_by_single_newline` | 同一 chunk 內，header 與 content 以單個 `\n` 分隔 | 必要 |
| 7 | `test_three_chunks_produce_three_source_labels` | 3 個 chunk → 出現 `[來源 1]`、`[來源 2]`、`[來源 3]` | 必要 |

#### `_build_source_list()` — 9 個測試

函式職責：組裝回傳給 Streamlit UI 的來源清單，去除相同 `file_name + section` 組合，score 四捨五入至 4 位小數。

| # | 測試名稱 | 驗證重點 | 標記 |
|---|---|---|---|
| 1 | `test_empty_input_returns_empty_list` | 空 list 輸入回傳 `[]` | 必要 |
| 2 | `test_returns_all_three_required_fields` | 每筆來源含 `file_name`、`section`、`score` 三欄 | 必要 |
| 3 | `test_score_rounded_to_4_decimal_places` | score 以 `round(..., 4)` 處理，不回傳原始精度 | 必要 |
| 4 | `test_correct_field_values_preserved` | `file_name`、`section` 值原樣保留 | 必要 |
| 5 | `test_duplicate_file_name_and_section_deduplicated` | 相同 `(file_name, section)` 只保留一筆 | 必要 |
| 6 | `test_first_occurrence_kept_on_deduplication` | 去重時保留**第一筆**的 score，而非後者覆蓋 | 必要 |
| 7 | `test_same_file_different_sections_not_deduplicated` | 同檔案、不同章節視為不同來源，不去重 | 必要 |
| 8 | `test_different_files_same_section_not_deduplicated` | 不同檔案、相同章節名稱視為不同來源，不去重 | 必要 |
| 9 | `test_source_list_does_not_include_content_field` | 來源清單僅供 UI 顯示，不應含 `content` 全文 | 必要 |

#### `rag_query()` — 無 chunks 分支 — 11 個測試

情境：`vector_search()` 回傳空 list，進入 fallback 流程。

| # | 測試名稱 | 驗證重點 | 標記 |
|---|---|---|---|
| 1 | `test_saves_user_message_before_vector_search` | 第一次 `save_chat_history` 的 `role="user"`，且 `message_text` 等於原始 query | 必要 |
| 2 | `test_returns_fallback_answer_when_no_chunks` | 回傳 answer 含「沒有」字串（告知使用者查無結果） | 必要 |
| 3 | `test_returns_empty_sources_list_when_no_chunks` | 回傳 `sources = []` | 必要 |
| 4 | `test_saves_fallback_answer_to_chat_history` | `role="model"` 的 save 呼叫確實發生 | 必要 |
| 5 | `test_does_not_call_generate_content_when_no_chunks` | 無 chunk 時**不呼叫** Vertex AI | 必要 |
| 6 | `test_does_not_call_load_chat_history_when_no_chunks` | 無 chunk 時**不讀取**歷史（省 DB round-trip） | 必要 |
| 7 | `test_total_save_count_is_two_when_no_chunks` | `save_chat_history` 共呼叫 2 次（user + fallback model） | 必要 |
| 8 | `test_vector_search_called_with_correct_query` | `vector_search` 的 `query` 參數等於傳入的 query 字串 | 必要 |
| 9 | `test_vector_search_called_with_module_top_k_constant` | `top_k` 參數使用模組常數 `RAG_TOP_K`（= 5） | 必要 |
| 10 | `test_vector_search_passes_filter_tags_when_provided` | 傳入 `filter_tags` 時，值原樣透傳給 `vector_search` | 必要 |
| 11 | `test_vector_search_passes_filter_note_type_when_provided` | 傳入 `filter_note_type` 時，值原樣透傳給 `vector_search` | 必要 |

#### `rag_query()` — 有 chunks 分支 — 20 個測試

情境：`vector_search()` 回傳 2 筆 chunk，進入完整 RAG 流程。

| # | 測試名稱 | 驗證重點 | 標記 |
|---|---|---|---|
| 1 | `test_returns_answer_from_model_response` | 回傳的 `answer` 等於模型 `response.text` | 必要 |
| 2 | `test_returns_non_empty_sources_list` | `sources` 為非空 list | 必要 |
| 3 | `test_sources_contain_required_fields` | 每筆 source 含 `file_name`、`section`、`score` | 必要 |
| 4 | `test_generate_content_called_exactly_once` | LLM 呼叫恰好一次 | 必要 |
| 5 | `test_generate_content_uses_correct_model_constant` | `model` 參數使用模組常數 `RAG_AGENT1_MODEL` | 必要 |
| 6 | `test_contents_includes_history_before_current_message` | `contents` 陣列前段為 `load_chat_history` 回傳的歷史 | 必要 |
| 7 | `test_last_content_entry_is_current_user_message` | `contents` 最後一筆的 `role = "user"` | 必要 |
| 8 | `test_current_user_message_contains_query_text` | 當輪 user message 的 text 含原始 query | 必要 |
| 9 | `test_current_user_message_contains_chunk_context` | 當輪 user message 的 text 含 chunk 的 file_name（context 已注入） | 必要 |
| 10 | `test_total_contents_length_is_history_plus_one` | `len(contents) = len(history) + 1`（history + 當輪訊息） | 必要 |
| 11 | `test_load_chat_history_called_with_correct_session_and_agent` | `session_id` 與 `agent_type="rag"` 正確傳入 | 必要 |
| 12 | `test_load_chat_history_uses_module_n_constant` | `n` 參數使用模組常數 `CHAT_HISTORY_N`（= 3） | 必要 |
| 13 | `test_total_save_count_is_two` | `save_chat_history` 共呼叫 2 次（user + model） | 必要 |
| 14 | `test_first_save_is_user_message` | 第一次 save 的 `role="user"` 且 `message_text` = query | 必要 |
| 15 | `test_second_save_is_model_response` | 第二次 save 的 `role="model"` 且 `message_text` = 模型回答 | 必要 |
| 16 | `test_model_save_metadata_contains_model_name` | 模型 save 的 `metadata["model"]` = `RAG_AGENT1_MODEL` | 必要 |
| 17 | `test_model_save_metadata_contains_retrieved_chunks` | metadata 含 `retrieved_chunks` 欄位（file_path list） | 必要 |
| 18 | `test_model_save_metadata_contains_note_files` | metadata 含 `note_files` 欄位（去重後的 file_name set） | 必要 |
| 19 | `test_vector_search_passes_none_filters_by_default` | 不傳 filter 時，`filter_tags` 與 `filter_note_type` 均為 `None` | 必要 |
| 20 | `test_works_correctly_with_empty_chat_history` | 第一輪對話（歷史為空）時，`contents` 長度 = 1，仍正確回傳 answer | 必要 |

---

### 2-5 `intent_router_agent.py` — 13 個測試

#### `_r1_keyword_match()` — 6 個測試

函式職責：對使用者輸入做 keyword 快篩，優先比對 `R1_PLANNING_KEYWORDS`，再比對 `R1_RAG_KEYWORDS`，回傳 `(target, score)` 或 `(None, 0.0)`。
score 以「命中關鍵字數 / 關鍵字總數」計算。

| # | 測試名稱 | 驗證重點 | 標記 |
|---|---|---|---|
| 1 | `test_planning_keyword_命中` | 含「規劃」等詞 → `planning_agent`，且 `0 < score ≤ 1.0` | 必要 |
| 2 | `test_rag_keyword_命中` | 含「查詢」等詞 → `rag_agent`，且 `0 < score ≤ 1.0` | 必要 |
| 3 | `test_planning_優先於_rag` | 同時含 planning 與 rag 關鍵字，應優先回傳 `planning_agent` | 必要 |
| 4 | `test_無關輸入_回傳_None` | 無任何關鍵字命中 → `(None, 0.0)` | 必要 |
| 5 | `test_英文_planning_keyword` | 英文詞（`roadmap`）同樣能命中 planning 分類 | 必要 |
| 6 | `test_旅遊規劃_命中_planning_keyword` | **已知誤判記錄**：「規劃」過廣，旅遊規劃也會命中 planning；測試固定現有行為，提醒未來可收窄關鍵字 | **[提案]** |

---

#### `_r2_llm_classify()` — 4 個測試

函式職責：R1 無法判斷時呼叫 LLM 分類。讀取最近 N 輪歷史（rag + planning 各讀一次後合併），組裝 `contents` 陣列送入 Vertex AI，解析 `"agent:score"` 格式，格式異常時 fallback 為 `("rag_agent", 0.5)`。

| # | 測試名稱 | 驗證重點 | 標記 |
|---|---|---|---|
| 1 | `test_正常輸出_rag` | LLM 輸出 `"rag_agent:0.88"` → 正確解析 `target="rag_agent", score=0.88` | 必要 |
| 2 | `test_正常輸出_planning` | LLM 輸出 `"planning_agent:0.95"` → 正確解析 `target="planning_agent", score=0.95` | 必要 |
| 3 | `test_格式異常_預設_rag` | LLM 輸出無法 split/parse 時，fallback `("rag_agent", 0.5)` | 必要 |
| 4 | `test_帶入_history_驗證_contents_組裝` | rag history 回傳 2 筆、planning 回傳 0 筆 → `contents` 共 3 筆（2 history + 1 current），最後一筆 `role="user"` 且含原始 query | 必要 |

---

#### `route()` — 3 個測試

函式職責：統合 R1 → R2 routing 流程，呼叫 `save_chat_history` 記錄 router 判斷結果與 metadata。

| # | 測試名稱 | 驗證重點 | 標記 |
|---|---|---|---|
| 1 | `test_R1_命中_不呼叫_R2` | R1 命中時直接回傳，`save_chat_history` 呼叫恰好一次且 `metadata["method"] == "r1_keyword"` | 必要 |
| 2 | `test_R1_未命中_呼叫_R2` | R1 未命中時進入 R2，`_r2_llm_classify` 確實被呼叫，`metadata["method"] == "r2_llm"` 且 `metadata["intent_score"] == 0.82` | 必要 |
| 3 | `test_save_metadata_含_intent_score` | R1 命中時，`save_chat_history` 的 `metadata` 必含 `intent_score`（float 型別） | 必要 |

---

## 三、測試統計

| 分類 | 測試數 |
|---|---|
| `load_chat_history` 必要項目 | 7 |
| `load_chat_history` 提案補充 | 2 |
| `save_chat_history` 必要項目 | 6 |
| `save_chat_history` 提案補充 | 6 |
| `vector_search` 必要項目 | 15 |
| `vector_search` 提案補充 | 6 |
| `_build_context` | 7 |
| `_build_source_list` | 9 |
| `rag_query` (無 chunks 分支) | 11 |
| `rag_query` (有 chunks 分支) | 20 |
| `_r1_keyword_match` | 6 |
| `_r2_llm_classify` | 4 |
| `route` | 3 |
| **合計** | **102** |

**執行時間**：< 0.02 秒（純 mock，不依賴真實 DB / OpenAI API / Vertex AI）

---

## 四、覆蓋率量測

### 4-1 安裝 coverage.py

須先安裝 `coverage`，需先加入（dev dependency 即可）：

```bash
poetry add --group dev coverage
```

> 或直接 pip 安裝至現有環境：
> ```bash
> pip install coverage
> ```

### 4-2 執行指令

於**專案根目錄**下執行：

```bash
poetry run coverage run -m unittest \
    tests/test_dashboard_chat_history.py \
    tests/test_dashboard_vector_search.py \
    tests/test_dashboard_rag_agent.py \
    tests/test_dashboard_intent_router_agent.py
```

若要同時跑所有測試（含既有的 task01–task05）：

```bash
poetry run coverage run --source=dashboard_ui -m unittest discover -s tests
```

`--source=dashboard_ui` 限定只統計 `dashboard_ui/` 套件的覆蓋率，排除第三方套件與 task ETL 腳本的干擾。

### 4-3 查看覆蓋率報告

**終端機文字報告（快速）**

```bash
poetry run coverage report -m
```

輸出範例：

```
Name                                                        Stmts   Miss  Cover   Missing
-----------------------------------------------------------------------------------------
dashboard_ui/agent_tools/chat_history.py              42      4    90%   166-170
dashboard_ui/agent_tools/query_with_vector_search.py               38      3    92%   124-134
dashboard_ui/agents/rag_agent.py                               55      5    91%   38-51,187
-----------------------------------------------------------------------------------------
TOTAL                                                          135     12    91%
```

- **Stmts**：可執行語句總數
- **Miss**：未被任何測試執行到的語句數
- **Cover**：覆蓋率百分比
- **Missing**：未覆蓋的行號（通常為 `if __name__ == "__main__":` 區塊）

**HTML 互動式報告（詳細，可逐行查看）**

```bash
poetry run coverage html -d htmlcov
open htmlcov/index.html
```

瀏覽器開啟後可點選各個 .py 檔，綠色為已覆蓋行、紅色為未覆蓋行。

**XML 報告（CI 整合用）**

```bash
poetry run coverage xml -o coverage.xml
```

適用於 GitHub Actions / SonarQube 等 CI 平台讀取。

### 4-4 未覆蓋範圍說明

以下範圍預期不在覆蓋率內，屬正常：

| 未覆蓋區塊 | 原因 |
|---|---|
| `if __name__ == "__main__":` 區塊（三支源碼末尾） | 僅用於手動執行除錯，測試環境不執行 |
| `_get_openai_client()` 的 `EnvironmentError` 分支 | 需要真實環境變數缺失的情境，屬整合測試範疇 |
| `_get_genai_client()` 全函式（rag_agent.py L38–51） | 整合測試範疇；單元測試以 mock 替換，不執行真實 Vertex AI 初始化 |

---

## 五、注意事項

### Mock 策略

- **`_get_db`**：兩支源碼的 `_get_db` 僅在 `__main__` 才賦值，測試在每個 case 的 `_run()` 中直接注入 `ch_mod._get_db = lambda: mock_db`。
- **OpenAI Client**：以 `unittest.mock.patch.object` mock `_get_openai_client()`，讓 embedding 回傳固定的 1536-dim float list，不發出真實 API 請求。
- **`_FakeCursor`**：模擬 pymongo cursor chaining（`.sort().limit()`），僅供 `load_chat_history` 的 `find()` 路徑使用，記錄 sort field / direction / limit 供 assertion 驗證。
- **`_FakeChatCollection.find_one()`**：`save_chat_history` 改以 `find_one(sort=[("timestamp", 1)])` 取得最舊一筆 dict，fake 直接回傳 `_docs[0]`，讓 `delete_one` 能收到正確的 `_id`。

### rag_agent 的 Mock 策略

- **外部套件 stub**：`loguru` 及 `dashboard_ui.*` 子模組於載入前以 `sys.modules.setdefault()` 注入 `MagicMock`，確保 `importlib` 載入 `rag_agent.py` 時頂層 import 不報錯。`google.*` 套件由 poetry 環境提供，import 正常通過。
- **`_get_genai_client()`**：在每個 test class 的 `setUp` 以直接賦值 `rag_mod._get_genai_client = MagicMock(return_value=self.mock_client)` 取代，避免讀取環境變數或發出真實 Vertex AI 請求。
- **`vector_search` / `load_chat_history` / `save_chat_history`**：三個函式於模組載入後以 `from ... import` 綁定在 `rag_mod` 命名空間，`setUp` 中直接替換模組屬性（`rag_mod.vector_search = MagicMock(...)`），`rag_query` 呼叫時取用的即為替換後的 mock。
- **`save_chat_history` 呼叫驗證**：使用 `MagicMock()` 並透過 `.call_args_list[n].kwargs` 依序取得第 1 次（user）和第 2 次（model）呼叫的關鍵字參數，確保傳入值與預期一致。

### intent_router_agent 的 Mock 策略

- **外部套件 stub**：`google.oauth2`、`google.oauth2.service_account`、`google.genai`、`google.genai.types` 在環境中不可直接 import，於模組載入前以 `sys.modules.setdefault()` 注入 `MagicMock`，使 `importlib` 載入時頂層 import 不報錯。
- **`_r1_keyword_match()` 測試**：不需要任何 mock，純邏輯驗證；確認關鍵字清單的命中行為與優先順序（planning > rag）。
- **`_r2_llm_classify()` 測試**：以 `@patch(f"{_MODULE}.load_chat_history")` mock DB 讀取；以 `_make_mock_client()` helper 建立假 `genai.Client`，讓 `response.text` 回傳固定字串，不發出真實 Vertex AI 請求。`test_帶入_history_驗證_contents_組裝` 使用 `side_effect=[list, []]` 分別控制 rag / planning 兩次 `load_chat_history` 呼叫的回傳值。
- **`route()` 測試**：以 `@patch` 同時 mock `_get_genai_client`、`_r2_llm_classify`、`save_chat_history`，隔離所有 I/O；透過 `mock_save.call_args.kwargs["metadata"]` 驗證 routing 後寫入的 metadata 內容與 method 標記。
