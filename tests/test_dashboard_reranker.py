"""reranker 測試：Cohere cross-encoder 精排與 fallback。

_get_cohere_client 以 mock 覆蓋，不打真實 Cohere API。
"""

import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "dashboard_ui"))

from agent_tools import reranker as rr_mod
from agent_tools.types_and_constants import Reranker


def _chunk(idx, section="Sec", content="text", score=0.5):
    return {"chunk_index": idx, "section": section, "content": content, "score": score}


def _rerank_response(pairs):
    # pairs: list of (index, relevance_score)
    return SimpleNamespace(results=[SimpleNamespace(index=i, relevance_score=s) for i, s in pairs])


# ── _get_cohere_client ────────────────────────────────────────────────────────


class GetCohereClientTests(unittest.TestCase):
    def test_raises_when_no_api_key(self):
        with patch.object(rr_mod, "COHERE_API_KEY", None):
            with self.assertRaises(EnvironmentError):
                rr_mod._get_cohere_client()

    def test_returns_client_when_key_present(self):
        with patch.object(rr_mod, "COHERE_API_KEY", "key-123"), patch.object(rr_mod, "cohere") as mock_cohere:
            client = rr_mod._get_cohere_client()
        mock_cohere.ClientV2.assert_called_once_with(api_key="key-123")
        self.assertEqual(client, mock_cohere.ClientV2.return_value)


# ── rerank_chunks ─────────────────────────────────────────────────────────────


class RerankChunksTests(unittest.TestCase):
    def test_empty_chunks_returns_empty(self):
        self.assertEqual(rr_mod.rerank_chunks("q", []), [])

    def test_single_chunk_gets_rerank_score_1_without_api_call(self):
        mock_client = MagicMock()
        with patch.object(rr_mod, "_get_cohere_client", return_value=mock_client) as mock_get:
            result = rr_mod.rerank_chunks("q", [_chunk(0)])
        self.assertEqual(result[0]["rerank_score"], 1.0)
        mock_get.assert_not_called()

    def test_reorders_and_filters_low_scores(self):
        chunks = [_chunk(0), _chunk(1), _chunk(2)]
        # index 2 → 0.95、index 0 → 0.05（<0.1 被濾）、index 1 → 0.5
        mock_client = MagicMock()
        mock_client.rerank.return_value = _rerank_response([(2, 0.95), (0, 0.05), (1, 0.5)])
        with patch.object(rr_mod, "_get_cohere_client", return_value=mock_client):
            result = rr_mod.rerank_chunks("q", chunks)
        self.assertEqual([c["chunk_index"] for c in result], [2, 1])  # 0.05 被濾掉
        self.assertEqual(result[0]["rerank_score"], 0.95)

    def test_documents_prefix_section_when_present(self):
        chunks = [_chunk(0, section="SQL > DQL", content="body A"), _chunk(1, section="", content="body B")]
        mock_client = MagicMock()
        mock_client.rerank.return_value = _rerank_response([(0, 0.9), (1, 0.8)])
        with patch.object(rr_mod, "_get_cohere_client", return_value=mock_client):
            rr_mod.rerank_chunks("q", chunks)
        docs = mock_client.rerank.call_args.kwargs["documents"]
        self.assertEqual(docs[0], "[SQL > DQL]\nbody A")
        self.assertEqual(docs[1], "body B")  # 無 section 不加前綴

    def test_uses_reranker_model_and_caps_top_n(self):
        chunks = [_chunk(i) for i in range(3)]
        mock_client = MagicMock()
        mock_client.rerank.return_value = _rerank_response([(0, 0.9)])
        with patch.object(rr_mod, "_get_cohere_client", return_value=mock_client):
            rr_mod.rerank_chunks("q", chunks, top_n=10)
        kwargs = mock_client.rerank.call_args.kwargs
        self.assertEqual(kwargs["model"], Reranker.MODEL)
        self.assertEqual(kwargs["top_n"], 3)  # min(10, len(documents)=3)

    def test_fallback_keeps_original_order_on_exception(self):
        chunks = [_chunk(0, score=0.9), _chunk(1, score=0.8), _chunk(2, score=0.7)]
        with patch.object(rr_mod, "_get_cohere_client", side_effect=RuntimeError("cohere down")):
            result = rr_mod.rerank_chunks("q", chunks, top_n=2)
        self.assertEqual([c["chunk_index"] for c in result], [0, 1])  # 截斷 top_n=2
        self.assertEqual(result[0]["rerank_score"], 0.9)  # fallback：rerank_score=score


if __name__ == "__main__":
    unittest.main()
