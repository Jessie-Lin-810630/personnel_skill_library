import importlib.util
import sys
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock

from pymongo import DESCENDING

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

# Satisfy `from ..utils.interact_with_mongodb import get_db_altas` before loading module
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

_spec = importlib.util.spec_from_file_location(
    "dashboard_ui.agent_tools.chat_history",
    str(PROJECT_ROOT / "dashboard_ui" / "agent_tools" / "chat_history.py"),
)
ch_mod = importlib.util.module_from_spec(_spec)
ch_mod.__package__ = "dashboard_ui.agent_tools"
sys.modules["dashboard_ui.agent_tools.chat_history"] = ch_mod
_spec.loader.exec_module(ch_mod)


# ── helpers ──────────────────────────────────────────────────────────────────

class _FakeCursor:
    """Chainable fake cursor that records sort / limit args for assertion.
    Used only by load_chat_history (find().sort().limit())."""

    def __init__(self, docs):
        self._docs = list(docs)
        self.sort_field = None
        self.sort_direction = None
        self.limit_n = None

    def sort(self, field, direction):
        self.sort_field = field
        self.sort_direction = direction
        return self

    def limit(self, n):
        self.limit_n = n
        return self

    def __iter__(self):
        return iter(self._docs)


class _FakeChatCollection:
    """Minimal fake for the chat_history MongoDB collection."""

    def __init__(self, docs=None, session_count=0):
        self._docs = list(docs or [])
        self._session_count = session_count
        # find() / load_chat_history path
        self.find_filter = None
        self.find_projection = None
        self.last_cursor = None
        # find_one() / save_chat_history delete path
        self.find_one_filter = None
        self.find_one_sort = None
        # write operations
        self.deleted_filter = None
        self.inserted_doc = None

    def find(self, filter_doc, projection=None):
        self.find_filter = filter_doc
        self.find_projection = projection
        self.last_cursor = _FakeCursor(self._docs)
        return self.last_cursor

    def find_one(self, filter_doc, sort=None):
        self.find_one_filter = filter_doc
        self.find_one_sort = sort
        return self._docs[0] if self._docs else None

    def count_documents(self, filter_doc):
        return self._session_count

    def delete_one(self, filter_doc):
        self.deleted_filter = filter_doc

    def insert_one(self, doc):
        self.inserted_doc = doc


def _make_db(collection):
    return {"chat_history": collection}


# ── LoadChatHistoryTests ──────────────────────────────────────────────────────

class LoadChatHistoryTests(unittest.TestCase):

    SESSION = "session-abc"
    AGENT = "rag"

    def _run(self, docs, n=3):
        coll = _FakeChatCollection(docs=docs)
        ch_mod._get_db = lambda: _make_db(coll)
        result = ch_mod.load_chat_history(self.SESSION, self.AGENT, n=n)
        return result, coll

    def test_returns_empty_list_when_no_history(self):
        result, _ = self._run(docs=[])
        self.assertEqual(result, [])

    def test_query_filter_includes_session_id_and_agent_type(self):
        _, coll = self._run(docs=[])
        self.assertEqual(
            coll.find_filter,
            {"session_id": self.SESSION, "agent_type": self.AGENT},
        )

    def test_projection_excludes_id_and_includes_role_and_content(self):
        _, coll = self._run(docs=[])
        self.assertEqual(
            coll.find_projection,
            {"_id": 0, "role": 1, "content": 1},
        )

    def test_sort_is_descending_on_timestamp(self):
        _, coll = self._run(docs=[])
        self.assertEqual(coll.last_cursor.sort_field, "timestamp")
        self.assertEqual(coll.last_cursor.sort_direction, DESCENDING)

    def test_limit_is_n_times_2(self):
        _, coll = self._run(docs=[], n=3)
        self.assertEqual(coll.last_cursor.limit_n, 6)

    def test_return_format_matches_google_genai_contents_schema(self):
        # DB returns newest-first (DESCENDING); model reply is newer than user question
        docs = [
            {"role": "model", "content": "PLC stands for…"},  # newest → index 0
            {"role": "user", "content": "what is PLC?"},       # oldest → index 1
        ]
        result, _ = self._run(docs=docs)
        # Function reverses → oldest first: user question, then model answer
        self.assertEqual(len(result), 2)
        self.assertIn("role", result[0])
        self.assertIn("parts", result[0])
        self.assertEqual(result[0]["role"], "user")
        self.assertEqual(result[0]["parts"], [{"text": "what is PLC?"}])
        self.assertEqual(result[1]["parts"], [{"text": "PLC stands for…"}])

    def test_returns_docs_in_chronological_ascending_order(self):
        # find() returns newest-first; load_chat_history must reverse to oldest-first
        docs = [
            {"role": "model", "content": "answer"},   # newest → index 0 from DB
            {"role": "user", "content": "question"},  # oldest → index 1 from DB
        ]
        result, _ = self._run(docs=docs)
        # After reversal: question (user) should come first
        self.assertEqual(result[0]["role"], "user")
        self.assertEqual(result[1]["role"], "model")

    # ── [提案] 補充驗證項目 ────────────────────────────────────────────────

    def test_custom_n_sets_limit_to_n_times_2(self):
        """[提案] n 參數正確地將 limit 設為 n*2，不僅限預設值。"""
        _, coll = self._run(docs=[], n=5)
        self.assertEqual(coll.last_cursor.limit_n, 10)

    def test_each_content_mapped_to_parts_text_field(self):
        """[提案] content 欄位正確對應到 parts[0]["text"]，而非其他欄位名稱。"""
        docs = [{"role": "user", "content": "hello world"}]
        result, _ = self._run(docs=docs)
        part = result[0]["parts"][0]
        self.assertIn("text", part)
        self.assertEqual(part["text"], "hello world")


# ── SaveChatHistoryTests ──────────────────────────────────────────────────────

class SaveChatHistoryTests(unittest.TestCase):

    SESSION = "session-xyz"
    AGENT = "router"

    def _run(self, message_text, session_count=0, metadata=None):
        coll = _FakeChatCollection(
            docs=[{"_id": "oldest-id", "timestamp": "t0"}],
            session_count=session_count,
        )
        ch_mod._get_db = lambda: _make_db(coll)
        ch_mod.save_chat_history(
            self.SESSION, self.AGENT, "user", message_text, metadata=metadata
        )
        return coll

    def test_message_over_2000_chars_is_truncated_to_2000(self):
        long_msg = "x" * 2500
        coll = self._run(long_msg)
        self.assertEqual(len(coll.inserted_doc["content"]), 2000)

    def test_message_exactly_2000_chars_is_not_truncated(self):
        """[提案] 邊界值 2000 字元剛好不應被截斷。"""
        exact_msg = "y" * 2000
        coll = self._run(exact_msg)
        self.assertEqual(len(coll.inserted_doc["content"]), 2000)

    def test_message_under_2000_chars_is_not_truncated(self):
        short_msg = "hello"
        coll = self._run(short_msg)
        self.assertEqual(coll.inserted_doc["content"], "hello")

    def test_session_below_100_limit_does_not_call_delete(self):
        coll = self._run("msg", session_count=99)
        self.assertIsNone(coll.deleted_filter)

    def test_session_exactly_at_100_limit_deletes_oldest_before_insert(self):
        coll = self._run("msg", session_count=100)
        self.assertIsNotNone(coll.deleted_filter)
        self.assertIsNotNone(coll.inserted_doc)

    def test_session_over_100_limit_also_deletes_oldest(self):
        """[提案] count > 100（例如資料不一致時），同樣觸發刪除。"""
        coll = self._run("msg", session_count=101)
        self.assertIsNotNone(coll.deleted_filter)

    def test_find_one_uses_ascending_sort_to_locate_oldest_doc(self):
        """[提案] 刪除前呼叫 find_one 時 sort 參數為升序 [("timestamp", 1)]，確保取到最舊一筆。"""
        coll = self._run("msg", session_count=100)
        self.assertEqual(coll.find_one_filter, {"session_id": self.SESSION})
        self.assertEqual(coll.find_one_sort, [("timestamp", 1)])

    def test_delete_one_uses_id_returned_by_find_one(self):
        """[提案] delete_one 的 filter 使用 find_one 回傳 doc 的 _id，確保刪對那一筆。"""
        coll = self._run("msg", session_count=100)
        self.assertEqual(coll.deleted_filter, {"_id": "oldest-id"})

    def test_inserted_doc_contains_all_required_fields(self):
        coll = self._run("test content")
        doc = coll.inserted_doc
        self.assertEqual(doc["session_id"], self.SESSION)
        self.assertEqual(doc["agent_type"], self.AGENT)
        self.assertEqual(doc["role"], "user")
        self.assertEqual(doc["content"], "test content")
        self.assertIsInstance(doc["timestamp"], datetime)
        self.assertIn("metadata", doc)

    def test_metadata_defaults_to_empty_dict_when_none(self):
        coll = self._run("msg", metadata=None)
        self.assertEqual(coll.inserted_doc["metadata"], {})

    def test_metadata_is_stored_as_provided_when_given(self):
        """[提案] 傳入非 None 的 metadata 應原樣儲存。"""
        meta = {"model": "gemini-2.5-flash-lite", "intent_score": 0.92}
        coll = self._run("msg", metadata=meta)
        self.assertEqual(coll.inserted_doc["metadata"], meta)

    def test_truncated_content_preserved_first_2000_chars(self):
        """[提案] 截斷時保留的是前 2000 字元，而非末段。"""
        msg = "A" * 2000 + "B" * 500
        coll = self._run(msg)
        self.assertTrue(coll.inserted_doc["content"].startswith("A"))
        self.assertFalse("B" in coll.inserted_doc["content"])


if __name__ == "__main__":
    unittest.main()
