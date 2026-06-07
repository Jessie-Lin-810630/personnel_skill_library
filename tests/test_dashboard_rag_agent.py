import importlib.util
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

# ── Stub heavy / external packages if not yet imported ───────────────────────
sys.modules.setdefault("loguru", MagicMock())

# dashboard_ui package stubs (same pattern as other test files)
sys.modules.setdefault(
    "dashboard_ui",
    MagicMock(__path__=[str(PROJECT_ROOT / "dashboard_ui")], __name__="dashboard_ui"),
)
sys.modules.setdefault(
    "dashboard_ui.utils",
    MagicMock(__path__=[str(PROJECT_ROOT / "dashboard_ui" / "utils")], __name__="dashboard_ui.utils"),
)
sys.modules.setdefault("dashboard_ui.utils.interact_with_mongodb", MagicMock())
sys.modules.setdefault(
    "dashboard_ui.agent_tools",
    MagicMock(
        __path__=[str(PROJECT_ROOT / "dashboard_ui" / "agent_tools")],
        __name__="dashboard_ui.agent_tools",
    ),
)
sys.modules.setdefault("dashboard_ui.agent_tools.query_with_vector_search", MagicMock())
sys.modules.setdefault("dashboard_ui.agent_tools.chat_history", MagicMock())
sys.modules.setdefault(
    "dashboard_ui.agents",
    MagicMock(
        __path__=[str(PROJECT_ROOT / "dashboard_ui" / "agents")],
        __name__="dashboard_ui.agents",
    ),
)

# ── Load rag_agent ────────────────────────────────────────────────────────────
_spec = importlib.util.spec_from_file_location(
    "dashboard_ui.agents.rag_agent",
    str(PROJECT_ROOT / "dashboard_ui" / "agents" / "rag_agent.py"),
)
rag_mod = importlib.util.module_from_spec(_spec)
rag_mod.__package__ = "dashboard_ui.agents"
sys.modules["dashboard_ui.agents.rag_agent"] = rag_mod
_spec.loader.exec_module(rag_mod)


# ── helpers ───────────────────────────────────────────────────────────────────

def _make_chunk(file_name="note.md", section="A > B", content="some text",
                score=0.9, file_path="notes/note.md"):
    return {"file_name": file_name, "section": section,
            "content": content, "score": score, "file_path": file_path}


# ── BuildContextTests ─────────────────────────────────────────────────────────

class BuildContextTests(unittest.TestCase):

    def test_empty_chunks_returns_empty_string(self):
        self.assertEqual(rag_mod._build_context([]), "")

    def test_single_chunk_header_contains_file_name_and_section(self):
        chunk = _make_chunk(file_name="SQL.md", section="SQL > DQL", content="SELECT 語法")
        result = rag_mod._build_context([chunk])
        self.assertIn("[來源 1] 檔案: SQL.md｜章節: SQL > DQL", result)

    def test_single_chunk_body_contains_content(self):
        chunk = _make_chunk(content="SELECT 語法")
        result = rag_mod._build_context([chunk])
        self.assertIn("SELECT 語法", result)

    def test_source_numbering_starts_at_1(self):
        chunks = [_make_chunk(), _make_chunk(file_name="b.md")]
        result = rag_mod._build_context(chunks)
        self.assertIn("[來源 1]", result)
        self.assertIn("[來源 2]", result)

    def test_multiple_chunks_joined_with_double_newline(self):
        chunks = [_make_chunk(content="第一段"), _make_chunk(content="第二段")]
        result = rag_mod._build_context(chunks)
        parts = result.split("\n\n")
        self.assertEqual(len(parts), 2)

    def test_header_and_content_separated_by_single_newline(self):
        chunk = _make_chunk(file_name="x.md", section="Sec", content="Body text")
        result = rag_mod._build_context([chunk])
        lines = result.split("\n")
        self.assertTrue(lines[0].startswith("[來源 1]"))
        self.assertEqual(lines[1], "Body text")

    def test_three_chunks_produce_three_source_labels(self):
        chunks = [_make_chunk(file_name=f"{i}.md") for i in range(3)]
        result = rag_mod._build_context(chunks)
        for i in (1, 2, 3):
            self.assertIn(f"[來源 {i}]", result)


# ── BuildSourceListTests ──────────────────────────────────────────────────────

class BuildSourceListTests(unittest.TestCase):

    def test_empty_input_returns_empty_list(self):
        self.assertEqual(rag_mod._build_source_list([]), [])

    def test_returns_all_three_required_fields(self):
        result = rag_mod._build_source_list([_make_chunk()])
        self.assertIn("file_name", result[0])
        self.assertIn("section", result[0])
        self.assertIn("score", result[0])

    def test_score_rounded_to_4_decimal_places(self):
        chunk = _make_chunk(score=0.912345678)
        result = rag_mod._build_source_list([chunk])
        self.assertEqual(result[0]["score"], round(0.912345678, 4))

    def test_correct_field_values_preserved(self):
        chunk = _make_chunk(file_name="note.md", section="Main > Sub", score=0.75)
        result = rag_mod._build_source_list([chunk])
        self.assertEqual(result[0]["file_name"], "note.md")
        self.assertEqual(result[0]["section"], "Main > Sub")

    def test_duplicate_file_name_and_section_deduplicated(self):
        chunks = [
            _make_chunk(file_name="a.md", section="S1", score=0.9),
            _make_chunk(file_name="a.md", section="S1", score=0.8),  # duplicate
        ]
        result = rag_mod._build_source_list(chunks)
        self.assertEqual(len(result), 1)

    def test_first_occurrence_kept_on_deduplication(self):
        chunks = [
            _make_chunk(file_name="a.md", section="S1", score=0.9),
            _make_chunk(file_name="a.md", section="S1", score=0.8),
        ]
        result = rag_mod._build_source_list(chunks)
        self.assertEqual(result[0]["score"], round(0.9, 4))

    def test_same_file_different_sections_not_deduplicated(self):
        chunks = [
            _make_chunk(file_name="a.md", section="S1"),
            _make_chunk(file_name="a.md", section="S2"),
        ]
        result = rag_mod._build_source_list(chunks)
        self.assertEqual(len(result), 2)

    def test_different_files_same_section_not_deduplicated(self):
        chunks = [
            _make_chunk(file_name="a.md", section="S1"),
            _make_chunk(file_name="b.md", section="S1"),
        ]
        result = rag_mod._build_source_list(chunks)
        self.assertEqual(len(result), 2)

    def test_source_list_does_not_include_content_field(self):
        """source_list 只給 UI 顯示來源，不應包含 content 全文。"""
        result = rag_mod._build_source_list([_make_chunk()])
        self.assertNotIn("content", result[0])


# ── RagQueryNoChunksTests ─────────────────────────────────────────────────────

class RagQueryNoChunksTests(unittest.TestCase):
    """rag_query when vector_search returns no results."""

    SESSION = "session-empty"

    def setUp(self):
        rag_mod.vector_search = MagicMock(return_value=[])
        rag_mod.load_chat_history = MagicMock()
        rag_mod.save_chat_history = MagicMock()

        self.mock_client = MagicMock()
        rag_mod._get_genai_client = MagicMock(return_value=self.mock_client)

    def test_saves_user_message_before_vector_search(self):
        rag_mod.rag_query("test query", self.SESSION)
        first_call_kwargs = rag_mod.save_chat_history.call_args_list[0].kwargs
        self.assertEqual(first_call_kwargs["role"], "user")
        self.assertEqual(first_call_kwargs["message_text"], "test query")
        self.assertEqual(first_call_kwargs["agent_type"], "rag")

    def test_returns_fallback_answer_when_no_chunks(self):
        result = rag_mod.rag_query("test query", self.SESSION)
        self.assertIn("answer", result)
        self.assertIn("沒有", result["answer"])

    def test_returns_empty_sources_list_when_no_chunks(self):
        result = rag_mod.rag_query("test query", self.SESSION)
        self.assertEqual(result["sources"], [])

    def test_saves_fallback_answer_to_chat_history(self):
        rag_mod.rag_query("test query", self.SESSION)
        roles = [c.kwargs["role"] for c in rag_mod.save_chat_history.call_args_list]
        self.assertIn("model", roles)

    def test_does_not_call_generate_content_when_no_chunks(self):
        rag_mod.rag_query("test query", self.SESSION)
        self.mock_client.models.generate_content.assert_not_called()

    def test_does_not_call_load_chat_history_when_no_chunks(self):
        rag_mod.rag_query("test query", self.SESSION)
        rag_mod.load_chat_history.assert_not_called()

    def test_total_save_count_is_two_when_no_chunks(self):
        rag_mod.rag_query("test query", self.SESSION)
        self.assertEqual(rag_mod.save_chat_history.call_count, 2)

    def test_vector_search_called_with_correct_query(self):
        rag_mod.rag_query("my question", self.SESSION)
        kwargs = rag_mod.vector_search.call_args.kwargs
        self.assertEqual(kwargs["query"], "my question")

    def test_vector_search_called_with_module_top_k_constant(self):
        rag_mod.rag_query("my question", self.SESSION)
        kwargs = rag_mod.vector_search.call_args.kwargs
        self.assertEqual(kwargs["top_k"], rag_mod.RAG_TOP_K)

    def test_vector_search_passes_filter_tags_when_provided(self):
        rag_mod.rag_query("query", self.SESSION, filter_tags="MySQL")
        kwargs = rag_mod.vector_search.call_args.kwargs
        self.assertEqual(kwargs["filter_tags"], "MySQL")

    def test_vector_search_passes_filter_note_type_when_provided(self):
        rag_mod.rag_query("query", self.SESSION, filter_note_type="knowledge_summary")
        kwargs = rag_mod.vector_search.call_args.kwargs
        self.assertEqual(kwargs["filter_note_type"], "knowledge_summary")

    def test_vector_search_passes_none_filters_by_default(self):
        rag_mod.rag_query("query", self.SESSION)
        kwargs = rag_mod.vector_search.call_args.kwargs
        self.assertIsNone(kwargs["filter_tags"])
        self.assertIsNone(kwargs["filter_note_type"])


# ── RagQueryWithChunksTests ───────────────────────────────────────────────────

class RagQueryWithChunksTests(unittest.TestCase):
    """rag_query when vector_search returns results."""

    SESSION = "session-with-chunks"
    QUERY = "MySQL 索引語法"
    FAKE_CHUNKS = [
        _make_chunk(file_name="sql.md", section="MySQL > Index",
                    content="CREATE INDEX …", score=0.95),
        _make_chunk(file_name="sql.md", section="MySQL > DDL",
                    content="CREATE TABLE …", score=0.88),
    ]
    FAKE_HISTORY = [
        {"role": "user",  "parts": [{"text": "previous question"}]},
        {"role": "model", "parts": [{"text": "previous answer"}]},
    ]

    def setUp(self):
        rag_mod.vector_search = MagicMock(return_value=self.FAKE_CHUNKS)
        rag_mod.load_chat_history = MagicMock(return_value=self.FAKE_HISTORY)
        rag_mod.save_chat_history = MagicMock()

        self.mock_response = MagicMock()
        self.mock_response.text = "這是模型的回答"
        self.mock_client = MagicMock()
        self.mock_client.models.generate_content.return_value = self.mock_response
        rag_mod._get_genai_client = MagicMock(return_value=self.mock_client)

    def _get_generate_call_kwargs(self):
        return self.mock_client.models.generate_content.call_args.kwargs

    # ── return value ──────────────────────────────────────────────────────────

    def test_returns_answer_from_model_response(self):
        result = rag_mod.rag_query(self.QUERY, self.SESSION)
        self.assertEqual(result["answer"], "這是模型的回答")

    def test_returns_non_empty_sources_list(self):
        result = rag_mod.rag_query(self.QUERY, self.SESSION)
        self.assertIsInstance(result["sources"], list)
        self.assertGreater(len(result["sources"]), 0)

    def test_sources_contain_required_fields(self):
        result = rag_mod.rag_query(self.QUERY, self.SESSION)
        for src in result["sources"]:
            with self.subTest(src=src):
                self.assertIn("file_name", src)
                self.assertIn("section", src)
                self.assertIn("score", src)

    # ── generate_content call ─────────────────────────────────────────────────

    def test_generate_content_called_exactly_once(self):
        rag_mod.rag_query(self.QUERY, self.SESSION)
        self.mock_client.models.generate_content.assert_called_once()

    def test_generate_content_uses_correct_model_constant(self):
        rag_mod.rag_query(self.QUERY, self.SESSION)
        self.assertEqual(
            self._get_generate_call_kwargs()["model"],
            rag_mod.RAG_AGENT1_MODEL,
        )

    def test_contents_includes_history_before_current_message(self):
        rag_mod.rag_query(self.QUERY, self.SESSION)
        contents = self._get_generate_call_kwargs()["contents"]
        self.assertEqual(contents[:2], self.FAKE_HISTORY)

    def test_last_content_entry_is_current_user_message(self):
        rag_mod.rag_query(self.QUERY, self.SESSION)
        contents = self._get_generate_call_kwargs()["contents"]
        self.assertEqual(contents[-1]["role"], "user")

    def test_current_user_message_contains_query_text(self):
        rag_mod.rag_query(self.QUERY, self.SESSION)
        contents = self._get_generate_call_kwargs()["contents"]
        text = contents[-1]["parts"][0]["text"]
        self.assertIn(self.QUERY, text)

    def test_current_user_message_contains_chunk_context(self):
        rag_mod.rag_query(self.QUERY, self.SESSION)
        contents = self._get_generate_call_kwargs()["contents"]
        text = contents[-1]["parts"][0]["text"]
        self.assertIn("sql.md", text)

    def test_total_contents_length_is_history_plus_one(self):
        rag_mod.rag_query(self.QUERY, self.SESSION)
        contents = self._get_generate_call_kwargs()["contents"]
        self.assertEqual(len(contents), len(self.FAKE_HISTORY) + 1)

    # ── load_chat_history call ────────────────────────────────────────────────

    def test_load_chat_history_called_with_correct_session_and_agent(self):
        rag_mod.rag_query(self.QUERY, self.SESSION)
        kwargs = rag_mod.load_chat_history.call_args.kwargs
        self.assertEqual(kwargs["session_id"], self.SESSION)
        self.assertEqual(kwargs["agent_type"], "rag")

    def test_load_chat_history_uses_module_n_constant(self):
        rag_mod.rag_query(self.QUERY, self.SESSION)
        kwargs = rag_mod.load_chat_history.call_args.kwargs
        self.assertEqual(kwargs["n"], rag_mod.CHAT_HISTORY_N)

    # ── save_chat_history calls ───────────────────────────────────────────────

    def test_total_save_count_is_two(self):
        """save_chat_history 應恰好被呼叫 2 次：user 一次、model 一次。"""
        rag_mod.rag_query(self.QUERY, self.SESSION)
        self.assertEqual(rag_mod.save_chat_history.call_count, 2)

    def test_first_save_is_user_message(self):
        rag_mod.rag_query(self.QUERY, self.SESSION)
        first_kwargs = rag_mod.save_chat_history.call_args_list[0].kwargs
        self.assertEqual(first_kwargs["role"], "user")
        self.assertEqual(first_kwargs["message_text"], self.QUERY)

    def test_second_save_is_model_response(self):
        rag_mod.rag_query(self.QUERY, self.SESSION)
        second_kwargs = rag_mod.save_chat_history.call_args_list[1].kwargs
        self.assertEqual(second_kwargs["role"], "model")
        self.assertEqual(second_kwargs["message_text"], "這是模型的回答")

    def test_model_save_metadata_contains_model_name(self):
        rag_mod.rag_query(self.QUERY, self.SESSION)
        second_kwargs = rag_mod.save_chat_history.call_args_list[1].kwargs
        self.assertEqual(second_kwargs["metadata"]["model"], rag_mod.RAG_AGENT1_MODEL)

    def test_model_save_metadata_contains_retrieved_chunks(self):
        rag_mod.rag_query(self.QUERY, self.SESSION)
        second_kwargs = rag_mod.save_chat_history.call_args_list[1].kwargs
        self.assertIn("retrieved_chunks", second_kwargs["metadata"])

    def test_model_save_metadata_contains_note_files(self):
        rag_mod.rag_query(self.QUERY, self.SESSION)
        second_kwargs = rag_mod.save_chat_history.call_args_list[1].kwargs
        self.assertIn("note_files", second_kwargs["metadata"])

    # ── empty history edge case ───────────────────────────────────────────────

    def test_works_correctly_with_empty_chat_history(self):
        """第一輪對話（無歷史）時，contents 只包含當前 user message。"""
        rag_mod.load_chat_history.return_value = []
        result = rag_mod.rag_query(self.QUERY, self.SESSION)
        contents = self._get_generate_call_kwargs()["contents"]
        self.assertEqual(len(contents), 1)
        self.assertEqual(result["answer"], "這是模型的回答")


if __name__ == "__main__":
    unittest.main()
