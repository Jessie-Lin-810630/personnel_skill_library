"""vector_search 測試：query 向量化 + $vectorSearch pipeline 組裝（v2）。

以 Vertex AI gemini-embedding-2 為 embedding model、note_vectors_multimodal 為集合、
血緣欄 md_path。_get_embed_client / _get_db 皆 mock，不打真實 API / DB。
"""

import math
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

PROJECT_ROOT = Path(__file__).resolve().parents[1]
# Option A：把 dashboard_ui/ 加進 path，讓模組的裸 import 如 app 實際跑法般解析
sys.path.insert(0, str(PROJECT_ROOT / "dashboard_ui"))

from agent_tools import query_with_vector_search as vs_mod
from agent_tools.types_and_constants import EmbeddingModel, NoteCollections

# ── NormalizeTests ────────────────────────────────────────────────────────────


class NormalizeTests(unittest.TestCase):
    def test_zero_vector_returned_as_is(self):
        self.assertEqual(vs_mod._normalize([0.0, 0.0]), [0.0, 0.0])

    def test_empty_vector_returned_as_is(self):
        self.assertEqual(vs_mod._normalize([]), [])

    def test_result_is_unit_length(self):
        v = vs_mod._normalize([3.0, 4.0])
        self.assertEqual(v, [0.6, 0.8])
        self.assertAlmostEqual(math.sqrt(sum(x * x for x in v)), 1.0)


# ── VectorSearchPipelineTests ─────────────────────────────────────────────────


class VectorSearchPipelineTests(unittest.TestCase):
    FAKE_RAW = [3.0, 4.0]  # → _normalize → [0.6, 0.8]

    def setUp(self):
        self.mock_collection = MagicMock()
        self.mock_collection.aggregate.return_value = []
        vs_mod._get_db = lambda: {vs_mod.VECTOR_COLLECTION: self.mock_collection}

        self.mock_embed_client = MagicMock()
        self.mock_embed_client.models.embed_content.return_value = SimpleNamespace(
            embeddings=[SimpleNamespace(values=list(self.FAKE_RAW))]
        )
        self._patcher = patch.object(vs_mod, "_get_embed_client", return_value=self.mock_embed_client)
        self._patcher.start()

    def tearDown(self):
        self._patcher.stop()

    def _pipeline(self, **kwargs):
        vs_mod.vector_search("test query", **kwargs)
        return self.mock_collection.aggregate.call_args[0][0]

    @property
    def _expected_vector(self):
        return vs_mod._normalize(list(self.FAKE_RAW))

    # ── embedding ─────────────────────────────────────────────────────────────

    def test_embed_uses_gemini_model_and_dim(self):
        vs_mod.vector_search("找尋PLC知識")
        kwargs = self.mock_embed_client.models.embed_content.call_args.kwargs
        self.assertEqual(kwargs["model"], EmbeddingModel.MODEL)
        self.assertEqual(kwargs["config"].output_dimensionality, EmbeddingModel.DIM)

    def test_query_vector_is_l2_normalized_embedding(self):
        pipeline = self._pipeline()
        self.assertEqual(pipeline[0]["$vectorSearch"]["queryVector"], self._expected_vector)

    def test_uses_note_vectors_multimodal_collection(self):
        captured = {}

        class _DB:
            def __getitem__(self, name):
                captured["name"] = name
                return MagicMock(aggregate=MagicMock(return_value=[]))

        vs_mod._get_db = lambda: _DB()
        vs_mod.vector_search("q")
        self.assertEqual(captured["name"], NoteCollections.VECTOR)

    # ── pipeline structure ────────────────────────────────────────────────────

    def test_pipeline_has_two_stages(self):
        pipeline = self._pipeline()
        self.assertEqual(len(pipeline), 2)
        self.assertIn("$vectorSearch", pipeline[0])
        self.assertIn("$project", pipeline[1])

    # ── $vectorSearch stage ───────────────────────────────────────────────────

    def test_vectorsearch_uses_index2(self):
        pipeline = self._pipeline()
        self.assertEqual(pipeline[0]["$vectorSearch"]["index"], EmbeddingModel.VECTOR_INDEX)

    def test_vectorsearch_path_is_embedding(self):
        self.assertEqual(self._pipeline()[0]["$vectorSearch"]["path"], "embedding")

    def test_limit_equals_top_k(self):
        self.assertEqual(self._pipeline(top_k=7)[0]["$vectorSearch"]["limit"], 7)

    def test_num_candidates_is_10x_top_k(self):
        self.assertEqual(self._pipeline(top_k=5)[0]["$vectorSearch"]["numCandidates"], 50)

    def test_num_candidates_capped_at_10000(self):
        self.assertEqual(self._pipeline(top_k=2000)[0]["$vectorSearch"]["numCandidates"], 10_000)

    # ── filter conditions ─────────────────────────────────────────────────────

    def test_no_filter_key_when_no_args(self):
        self.assertNotIn("filter", self._pipeline()[0]["$vectorSearch"])

    def test_filter_tags_wrapped_in_in(self):
        vs_filter = self._pipeline(filter_tags=["MySQL"])[0]["$vectorSearch"]["filter"]
        self.assertEqual(vs_filter["tags"], {"$in": ["MySQL"]})
        self.assertNotIn("note_type", vs_filter)
        self.assertNotIn("md_path", vs_filter)

    def test_filter_note_type_is_plain_value(self):
        vs_filter = self._pipeline(filter_note_type="knowledge_summary")[0]["$vectorSearch"]["filter"]
        self.assertEqual(vs_filter["note_type"], "knowledge_summary")
        self.assertNotIn("tags", vs_filter)

    def test_filter_file_path_targets_md_path_lineage(self):
        vs_filter = self._pipeline(filter_file_path=["gs://v/a.md"])[0]["$vectorSearch"]["filter"]
        self.assertEqual(vs_filter["md_path"], {"$in": ["gs://v/a.md"]})

    def test_file_path_takes_precedence_over_tags(self):
        # 程式碼為 if filter_file_path ... elif filter_tags：兩者並存時 tags 被略過
        vs_filter = self._pipeline(filter_file_path=["x"], filter_tags=["MySQL"])[0]["$vectorSearch"]["filter"]
        self.assertIn("md_path", vs_filter)
        self.assertNotIn("tags", vs_filter)

    def test_tags_and_note_type_merged(self):
        vs_filter = self._pipeline(filter_tags=["MySQL"], filter_note_type="knowledge_summary")[0]["$vectorSearch"][
            "filter"
        ]
        self.assertEqual(vs_filter["tags"], {"$in": ["MySQL"]})
        self.assertEqual(vs_filter["note_type"], "knowledge_summary")

    # ── $project stage ────────────────────────────────────────────────────────

    def test_project_excludes_id_and_embedding(self):
        proj = self._pipeline()[1]["$project"]
        self.assertEqual(proj["_id"], 0)
        self.assertNotIn("embedding", proj)

    def test_project_uses_md_path_not_file_path(self):
        proj = self._pipeline()[1]["$project"]
        self.assertEqual(proj["md_path"], 1)
        self.assertNotIn("file_path", proj)

    def test_project_includes_required_content_fields(self):
        proj = self._pipeline()[1]["$project"]
        for field in ("file_name", "md_path", "chunk_index", "section", "content", "tags", "note_type"):
            with self.subTest(field=field):
                self.assertEqual(proj[field], 1)

    def test_project_score_uses_vectorsearchscore_meta(self):
        proj = self._pipeline()[1]["$project"]
        self.assertEqual(proj["score"], {"$meta": "vectorSearchScore"})

    # ── return value ──────────────────────────────────────────────────────────

    def test_returns_aggregate_results_as_list(self):
        fake = [{"file_name": "sql.md", "md_path": "gs://v/sql.md", "score": 0.95}]
        self.mock_collection.aggregate.return_value = fake
        self.assertEqual(vs_mod.vector_search("test"), fake)

    def test_returns_empty_list_when_no_matches(self):
        self.mock_collection.aggregate.return_value = []
        result = vs_mod.vector_search("obscure topic")
        self.assertIsInstance(result, list)
        self.assertEqual(result, [])


if __name__ == "__main__":
    unittest.main()
