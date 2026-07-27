"""RAG agent (v2) 測試：rewrite → vector_search → rerank → generate。

外部相依（rewrite_query / vector_search / rerank_chunks / load/save_chat_history /
get_genai_client）皆以 MagicMock 覆蓋，不打真實 API；
build_context / build_source_list 為純函式，讓其真實執行做整合驗證。
"""

import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock

PROJECT_ROOT = Path(__file__).resolve().parents[1]
# Option A：把 dashboard_ui/ 加進 path，讓模組的裸 import 如 app 實際跑法般解析
sys.path.insert(0, str(PROJECT_ROOT / "dashboard_ui"))

from agent_tools.types_and_constants import RagAgent, Reranker
from agents import rag_agent as rag_mod


def _make_chunk(
    file_name="sql.md",
    section="MySQL > Index",
    content="CREATE INDEX …",
    score=0.9,
    md_path="gs://onenote-vaults/archived-notes/u/sql.md",
    chunk_index=0,
    rerank_score=0.8,
):
    return {
        "file_name": file_name,
        "section": section,
        "content": content,
        "score": score,
        "md_path": md_path,
        "chunk_index": chunk_index,
        "rerank_score": rerank_score,
    }


ALIAS_TAG_PAIRS = [{"alias": "sql", "tags": ["MySQL"]}]
KNOWN_TAGS = {"mysql"}
REWRITE_RESULT = {
    "rewritten_query": "RW",
    "expanded_query": "EXP",
    "recommended_tags": ["MySQL"],
}


# ── RagQueryNoChunksTests ─────────────────────────────────────────────────────


class RagQueryNoChunksTests(unittest.TestCase):
    """vector_search 回空時的分支。"""

    SESSION = "session-empty"
    QUERY = "MySQL 索引語法"

    def setUp(self):
        self.mock_client = MagicMock()
        rag_mod.get_genai_client = MagicMock(return_value=self.mock_client)
        rag_mod.save_chat_history = MagicMock()
        rag_mod.load_chat_history = MagicMock(return_value=[])
        rag_mod.rewrite_query = MagicMock(return_value=REWRITE_RESULT)
        rag_mod.vector_search = MagicMock(return_value=[])
        rag_mod.rerank_chunks = MagicMock()

    def _run(self):
        return rag_mod.rag_query(self.QUERY, self.SESSION, ALIAS_TAG_PAIRS, KNOWN_TAGS)

    def test_saves_user_message_first(self):
        self._run()
        first = rag_mod.save_chat_history.call_args_list[0].kwargs
        self.assertEqual(first["role"], "user")
        self.assertEqual(first["message_text"], self.QUERY)
        self.assertEqual(first["agent_type"], "rag")

    def test_rewrite_query_called_with_history_and_pairs(self):
        self._run()
        kwargs = rag_mod.rewrite_query.call_args.kwargs
        self.assertEqual(kwargs["query"], self.QUERY)
        self.assertEqual(kwargs["alias_tag_pairs"], ALIAS_TAG_PAIRS)
        self.assertEqual(kwargs["known_tags"], KNOWN_TAGS)
        self.assertEqual(kwargs["client"], self.mock_client)

    def test_vector_search_uses_expanded_query_and_no_prefilter(self):
        self._run()
        kwargs = rag_mod.vector_search.call_args.kwargs
        self.assertEqual(kwargs["query"], "EXP")
        self.assertEqual(kwargs["top_k"], RagAgent.TOP_K)
        self.assertIsNone(kwargs["filter_tags"])
        self.assertIsNone(kwargs["filter_file_path"])

    def test_returns_fallback_answer(self):
        result = self._run()
        self.assertIn("沒有", result["answer"])

    def test_returns_empty_sources_and_debug(self):
        result = self._run()
        self.assertEqual(result["sources"], [])
        self.assertEqual(result["debug"], {})

    def test_does_not_call_rerank_or_generate(self):
        self._run()
        rag_mod.rerank_chunks.assert_not_called()
        self.mock_client.models.generate_content.assert_not_called()

    def test_save_count_is_two(self):
        self._run()
        self.assertEqual(rag_mod.save_chat_history.call_count, 2)

    def test_load_chat_history_uses_rag_agent_n(self):
        self._run()
        kwargs = rag_mod.load_chat_history.call_args.kwargs
        self.assertEqual(kwargs["agent_type"], "rag")
        self.assertEqual(kwargs["n"], RagAgent.CHAT_HISTORY_N)


# ── RagQueryWithChunksTests ───────────────────────────────────────────────────


class RagQueryWithChunksTests(unittest.TestCase):
    """vector_search 有結果時的完整 pipeline。"""

    SESSION = "session-with-chunks"
    QUERY = "MySQL 索引語法"
    HISTORY = [
        {"role": "user", "parts": [{"text": "previous question"}]},
        {"role": "model", "parts": [{"text": "previous answer"}]},
    ]
    CHUNKS = [
        _make_chunk(file_name="sql.md", section="MySQL > Index", content="CREATE INDEX …", score=0.95),
        _make_chunk(file_name="sql.md", section="MySQL > DDL", content="CREATE TABLE …", score=0.88),
    ]
    RERANKED = [
        _make_chunk(file_name="sql.md", section="MySQL > Index", score=0.95, rerank_score=0.99),
    ]

    def setUp(self):
        self.mock_response = MagicMock()
        self.mock_response.text = "這是模型的回答"
        self.mock_client = MagicMock()
        self.mock_client.models.generate_content.return_value = self.mock_response

        rag_mod.get_genai_client = MagicMock(return_value=self.mock_client)
        rag_mod.save_chat_history = MagicMock()
        rag_mod.load_chat_history = MagicMock(return_value=list(self.HISTORY))
        rag_mod.rewrite_query = MagicMock(return_value=REWRITE_RESULT)
        rag_mod.vector_search = MagicMock(return_value=list(self.CHUNKS))
        rag_mod.rerank_chunks = MagicMock(return_value=list(self.RERANKED))

    def _run(self):
        return rag_mod.rag_query(self.QUERY, self.SESSION, ALIAS_TAG_PAIRS, KNOWN_TAGS)

    def _generate_kwargs(self):
        return self.mock_client.models.generate_content.call_args.kwargs

    # ── rerank ────────────────────────────────────────────────────────────────

    def test_rerank_uses_rewritten_query_and_reranker_top_n(self):
        self._run()
        kwargs = rag_mod.rerank_chunks.call_args.kwargs
        self.assertEqual(kwargs["query"], "RW")
        self.assertEqual(kwargs["chunks"], self.CHUNKS)
        self.assertEqual(kwargs["top_n"], Reranker.TOP_N)

    # ── generate_content ──────────────────────────────────────────────────────

    def test_generate_content_called_once_with_rag_model(self):
        self._run()
        self.mock_client.models.generate_content.assert_called_once()
        self.assertEqual(self._generate_kwargs()["model"], RagAgent.MODEL)

    def test_contents_history_before_current_message(self):
        self._run()
        contents = self._generate_kwargs()["contents"]
        self.assertEqual(contents[:2], self.HISTORY)
        self.assertEqual(contents[-1]["role"], "user")

    def test_current_message_contains_query_and_chunk_context(self):
        self._run()
        text = self._generate_kwargs()["contents"][-1]["parts"][0]["text"]
        self.assertIn(self.QUERY, text)
        self.assertIn("sql.md", text)  # build_context 真實組裝的來源檔名

    def test_empty_history_makes_contents_length_one(self):
        rag_mod.load_chat_history.return_value = []
        self._run()
        self.assertEqual(len(self._generate_kwargs()["contents"]), 1)

    # ── return value ──────────────────────────────────────────────────────────

    def test_returns_answer_from_response(self):
        result = self._run()
        self.assertEqual(result["answer"], "這是模型的回答")

    def test_sources_built_from_reranked_chunks(self):
        result = self._run()
        self.assertGreater(len(result["sources"]), 0)
        for src in result["sources"]:
            self.assertIn("file_name", src)
            self.assertIn("section", src)
            self.assertIn("vector_score", src)
            self.assertIn("rerank_score", src)

    def test_debug_contains_pipeline_fields(self):
        debug = self._run()["debug"]
        self.assertEqual(debug["rewritten_query"], "RW")
        self.assertEqual(debug["expanded_query"], "EXP")
        self.assertEqual(debug["vector_search_count"], len(self.CHUNKS))
        self.assertEqual(debug["reranked_count"], len(self.RERANKED))

    # ── save model message metadata ───────────────────────────────────────────

    def test_model_save_metadata_fields(self):
        self._run()
        meta = rag_mod.save_chat_history.call_args_list[1].kwargs["metadata"]
        self.assertEqual(meta["model"], RagAgent.MODEL)
        self.assertEqual(meta["search_optimize_method"], "rewrite_expand_rerank")
        self.assertEqual(meta["rewritten_query"], "RW")
        self.assertEqual(meta["recommended_tags"], ["MySQL"])
        self.assertIn("note_files", meta)

    def test_retrieved_chunks_file_path_uses_md_path_value(self):
        self._run()
        meta = rag_mod.save_chat_history.call_args_list[1].kwargs["metadata"]
        retrieved = meta["retrieved_chunks"]
        self.assertEqual(retrieved[0]["file_path"], self.RERANKED[0]["md_path"])

    def test_save_count_is_two(self):
        self._run()
        self.assertEqual(rag_mod.save_chat_history.call_count, 2)

    def test_second_save_is_model_response(self):
        self._run()
        second = rag_mod.save_chat_history.call_args_list[1].kwargs
        self.assertEqual(second["role"], "model")
        self.assertEqual(second["message_text"], "這是模型的回答")


if __name__ == "__main__":
    unittest.main()
