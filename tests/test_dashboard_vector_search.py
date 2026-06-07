import importlib.util
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

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
    "dashboard_ui.agent_tools.query_with_vector_search",
    str(PROJECT_ROOT / "dashboard_ui" / "agent_tools" / "query_with_vector_search.py"),
)
vs_mod = importlib.util.module_from_spec(_spec)
vs_mod.__package__ = "dashboard_ui.agent_tools"
sys.modules["dashboard_ui.agent_tools.query_with_vector_search"] = vs_mod
_spec.loader.exec_module(vs_mod)


# ── VectorSearchPipelineTests ─────────────────────────────────────────────────

class VectorSearchPipelineTests(unittest.TestCase):

    FAKE_VECTOR = [float(i) / 1536 for i in range(1536)]  # deterministic 1536-dim vector

    def setUp(self):
        self.mock_collection = MagicMock()
        self.mock_collection.aggregate.return_value = []
        vs_mod._get_db = lambda: {"obsidian_vectors": self.mock_collection}

        # Mock _get_openai_client so no real API key is needed
        self._client_patcher = patch.object(vs_mod, "_get_openai_client")
        mock_get_client = self._client_patcher.start()
        self.mock_openai_client = MagicMock()
        self.mock_openai_client.embeddings.create.return_value.data = [
            MagicMock(embedding=self.FAKE_VECTOR)
        ]
        mock_get_client.return_value = self.mock_openai_client

    def tearDown(self):
        self._client_patcher.stop()

    def _call_and_get_pipeline(self, **kwargs):
        """Run vector_search and return the pipeline passed to aggregate()."""
        vs_mod.vector_search("test query", **kwargs)
        return self.mock_collection.aggregate.call_args[0][0]

    # ── OpenAI embedding ──────────────────────────────────────────────────────

    def test_openai_embedding_called_with_query_text_and_correct_model(self):
        vs_mod.vector_search("找尋PLC知識")
        self.mock_openai_client.embeddings.create.assert_called_once_with(
            model="text-embedding-3-small",
            input=["找尋PLC知識"],
            encoding_format="float",
        )

    # ── Pipeline structure ────────────────────────────────────────────────────

    def test_pipeline_contains_exactly_two_stages(self):
        pipeline = self._call_and_get_pipeline()
        self.assertEqual(len(pipeline), 2)

    def test_first_stage_is_vectorsearch(self):
        pipeline = self._call_and_get_pipeline()
        self.assertIn("$vectorSearch", pipeline[0])

    def test_second_stage_is_project(self):
        pipeline = self._call_and_get_pipeline()
        self.assertIn("$project", pipeline[1])

    # ── $vectorSearch stage ───────────────────────────────────────────────────

    def test_vectorsearch_stage_uses_correct_index_name(self):
        pipeline = self._call_and_get_pipeline()
        self.assertEqual(pipeline[0]["$vectorSearch"]["index"], "obsidian_vectors_index")

    def test_vectorsearch_stage_path_targets_embedding_field(self):
        pipeline = self._call_and_get_pipeline()
        self.assertEqual(pipeline[0]["$vectorSearch"]["path"], "embedding")

    def test_vectorsearch_stage_query_vector_matches_openai_output(self):
        pipeline = self._call_and_get_pipeline()
        self.assertEqual(pipeline[0]["$vectorSearch"]["queryVector"], self.FAKE_VECTOR)

    def test_vectorsearch_stage_num_candidates_is_10x_top_k(self):
        pipeline = self._call_and_get_pipeline(top_k=5)
        self.assertEqual(pipeline[0]["$vectorSearch"]["numCandidates"], 50)

    def test_vectorsearch_stage_limit_equals_top_k(self):
        pipeline = self._call_and_get_pipeline(top_k=7)
        self.assertEqual(pipeline[0]["$vectorSearch"]["limit"], 7)

    # ── filter conditions ─────────────────────────────────────────────────────

    def test_no_filter_key_when_no_filter_args_provided(self):
        pipeline = self._call_and_get_pipeline()
        self.assertNotIn("filter", pipeline[0]["$vectorSearch"])

    def test_filter_tags_adds_tags_filter_to_vectorsearch_stage(self):
        pipeline = self._call_and_get_pipeline(filter_tags="MySQL")
        vs_filter = pipeline[0]["$vectorSearch"]["filter"]
        self.assertEqual(vs_filter["tags"], "MySQL")
        self.assertNotIn("note_type", vs_filter)

    def test_filter_note_type_adds_note_type_filter_to_vectorsearch_stage(self):
        pipeline = self._call_and_get_pipeline(filter_note_type="knowledge_summary")
        vs_filter = pipeline[0]["$vectorSearch"]["filter"]
        self.assertEqual(vs_filter["note_type"], "knowledge_summary")
        self.assertNotIn("tags", vs_filter)

    def test_both_filters_merged_into_single_filter_dict(self):
        """[提案] 同時提供兩個 filter 時，應合併為同一 filter dict，而非覆蓋。"""
        pipeline = self._call_and_get_pipeline(
            filter_tags="MySQL", filter_note_type="knowledge_summary"
        )
        vs_filter = pipeline[0]["$vectorSearch"]["filter"]
        self.assertEqual(vs_filter["tags"], "MySQL")
        self.assertEqual(vs_filter["note_type"], "knowledge_summary")

    # ── numCandidates cap ─────────────────────────────────────────────────────

    def test_num_candidates_capped_at_10000_for_large_top_k(self):
        """[提案] top_k=2000 時，numCandidates 不得超過 Atlas 上限 10000。"""
        pipeline = self._call_and_get_pipeline(top_k=2000)
        self.assertEqual(pipeline[0]["$vectorSearch"]["numCandidates"], 10_000)

    def test_num_candidates_not_capped_when_top_k_is_small(self):
        """[提案] top_k=10 時，numCandidates 為 100，不觸發上限。"""
        pipeline = self._call_and_get_pipeline(top_k=10)
        self.assertEqual(pipeline[0]["$vectorSearch"]["numCandidates"], 100)

    # ── $project stage ────────────────────────────────────────────────────────

    def test_project_stage_excludes_id(self):
        pipeline = self._call_and_get_pipeline()
        self.assertEqual(pipeline[1]["$project"]["_id"], 0)

    def test_project_stage_includes_required_content_fields(self):
        pipeline = self._call_and_get_pipeline()
        proj = pipeline[1]["$project"]
        for field in ("file_name", "file_path", "section", "content", "tags", "note_type"):
            with self.subTest(field=field):
                self.assertEqual(proj[field], 1)

    def test_project_stage_score_uses_vectorsearchscore_meta(self):
        pipeline = self._call_and_get_pipeline()
        self.assertEqual(
            pipeline[1]["$project"]["score"],
            {"$meta": "vectorSearchScore"},
        )

    def test_project_stage_does_not_include_embedding_field(self):
        """[提案] embedding 欄位不應出現在 $project 中（省傳輸量）。"""
        pipeline = self._call_and_get_pipeline()
        self.assertNotIn("embedding", pipeline[1]["$project"])

    # ── return value ──────────────────────────────────────────────────────────

    def test_returns_aggregate_results_as_list(self):
        fake_results = [
            {"file_name": "sql.md", "content": "SELECT …", "score": 0.95},
            {"file_name": "plc.md", "content": "PLC …", "score": 0.87},
        ]
        self.mock_collection.aggregate.return_value = fake_results
        result = vs_mod.vector_search("test")
        self.assertEqual(result, fake_results)

    def test_returns_empty_list_when_no_matching_chunks(self):
        """[提案] aggregate 無結果時回傳空 list，而非 None。"""
        self.mock_collection.aggregate.return_value = []
        result = vs_mod.vector_search("obscure non-existent topic")
        self.assertIsInstance(result, list)
        self.assertEqual(len(result), 0)


if __name__ == "__main__":
    unittest.main()
