"""query_rewriter 測試：tag 字典載入、alias-tag 對照表、history 格式化、query 改寫。

MongoDB collection 與 genai client 皆以 fake / mock 覆蓋。
"""

import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "dashboard_ui"))

from agent_tools import query_rewriter as qr_mod
from agent_tools.types_and_constants import NoteCollections, RewriterAgent


class _FakeColl:
    def __init__(self, docs=None, distinct_vals=None):
        self._docs = docs or []
        self._distinct = distinct_vals or []
        self.find_filter = None
        self.find_projection = None

    def distinct(self, field):
        return self._distinct

    def find(self, filter_doc, projection=None):
        self.find_filter = filter_doc
        self.find_projection = projection
        return iter(self._docs)


# ── _load_known_tags ──────────────────────────────────────────────────────────


class LoadKnownTagsTests(unittest.TestCase):
    def test_returns_distinct_tags_as_set(self):
        coll = _FakeColl(distinct_vals=["MySQL", "SQL", "MySQL"])
        result = qr_mod._load_known_tags({NoteCollections.VECTOR: coll})
        self.assertEqual(result, {"MySQL", "SQL"})


# ── _load_alias_to_tags_map ───────────────────────────────────────────────────


class LoadAliasMapTests(unittest.TestCase):
    def test_obsidian_filter_projection_and_flatten(self):
        docs = [
            {"file_name": "note.md", "tags": ["t1"], "alias": ["A1", "A2"], "file_path": "gs://v/note.md"},
        ]
        coll = _FakeColl(docs=docs)
        result = qr_mod._load_alias_to_tags_map({NoteCollections.OBSIDIAN: coll})

        # 只撈 archived + embedded
        self.assertEqual(coll.find_filter, {"status": "archived", "embedded_status": True})
        # obsidian 分支 projection：alias/tags 取自 archived_md_frontmatter、file_path=archived_md_path
        self.assertEqual(coll.find_projection["alias"], "$archived_md_frontmatter.alias")
        self.assertEqual(coll.find_projection["file_path"], "$archived_md_path")
        # 攤平：file_name（去 .md）為首，其後為各 alias
        aliases = [p["alias"] for p in result]
        self.assertEqual(aliases, ["note", "A1", "A2"])
        self.assertTrue(all(p["tags"] == ["t1"] for p in result))

    def test_onenote_projection_uses_page_title_and_md_frontmatter(self):
        coll = _FakeColl(docs=[])
        qr_mod._load_alias_to_tags_map({NoteCollections.ONENOTE: coll}, collection=NoteCollections.ONENOTE)
        self.assertEqual(coll.find_projection["file_name"], "$page_title")
        self.assertEqual(coll.find_projection["alias"], "$md_frontmatter.alias")

    def test_empty_docs_returns_empty_list(self):
        coll = _FakeColl(docs=[])
        self.assertEqual(qr_mod._load_alias_to_tags_map({NoteCollections.OBSIDIAN: coll}), [])


# ── _format_history_for_prompt ────────────────────────────────────────────────


class FormatHistoryTests(unittest.TestCase):
    def test_empty_history_returns_placeholder(self):
        self.assertEqual(qr_mod._format_history_for_prompt([]), "(無對話歷史)")

    def test_formats_user_and_model_prefixes(self):
        msgs = [
            {"role": "user", "parts": [{"text": "問題"}]},
            {"role": "model", "parts": [{"text": "回答"}]},
        ]
        result = qr_mod._format_history_for_prompt(msgs)
        self.assertIn("使用者: 問題", result)
        self.assertIn("助手: 回答", result)

    def test_long_model_reply_truncated_to_300(self):
        msgs = [{"role": "model", "parts": [{"text": "x" * 500}]}]
        result = qr_mod._format_history_for_prompt(msgs)
        self.assertIn("....(省略)", result)
        self.assertLess(len(result), 400)


# ── rewrite_query ─────────────────────────────────────────────────────────────


class RewriteQueryTests(unittest.TestCase):
    KNOWN = {"mysql", "index"}
    PAIRS = [{"alias": "sql", "tags": ["MySQL"]}]

    def _client(self, llm_text):
        mock_client = MagicMock()
        mock_client.models.generate_content.return_value = SimpleNamespace(text=llm_text)
        return mock_client

    def test_uses_rewriter_model(self):
        client = self._client("REWRITTEN: 改寫後\nTAGS: MySQL")
        qr_mod.rewrite_query("原始", self.PAIRS, [], self.KNOWN, client=client)
        self.assertEqual(client.models.generate_content.call_args.kwargs["model"], RewriterAgent.MODEL)

    def test_parses_rewritten_and_validates_tags(self):
        client = self._client("REWRITTEN: MySQL 索引怎麼建\nTAGS: MySQL, Index, Nope")
        result = qr_mod.rewrite_query("怎麼建", self.PAIRS, [], self.KNOWN, client=client)
        self.assertEqual(result["rewritten_query"], "MySQL 索引怎麼建")
        # 只保留存在於 known_tags 的（不計大小寫）；"Nope" 被剔除
        self.assertEqual(result["recommended_tags"], ["MySQL", "Index"])
        self.assertEqual(result["expanded_query"], "MySQL 索引怎麼建 MySQL Index")

    def test_missing_rewritten_falls_back_to_original_query(self):
        client = self._client("TAGS: None")
        result = qr_mod.rewrite_query("原始問題", self.PAIRS, [], self.KNOWN, client=client)
        self.assertEqual(result["rewritten_query"], "原始問題")
        self.assertEqual(result["recommended_tags"], [])
        self.assertEqual(result["expanded_query"], "原始問題")

    def test_exception_returns_fallback(self):
        client = MagicMock()
        client.models.generate_content.side_effect = RuntimeError("llm down")
        result = qr_mod.rewrite_query("原始", self.PAIRS, [], self.KNOWN, client=client)
        self.assertEqual(result, {"rewritten_query": "原始", "expanded_query": "原始", "recommended_tags": []})


if __name__ == "__main__":
    unittest.main()
