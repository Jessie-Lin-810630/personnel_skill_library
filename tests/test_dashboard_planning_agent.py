"""Planning agent 測試：學習地圖初版生成與多輪追問調整。

vector_search / save_chat_history / get_genai_client 皆 mock；
build_context / build_source_list / build_history_context_message 為純函式，讓其真實執行
（build_history_context_message 內的 load_chat_history 於 agent_helpers 層 mock）。
"""

import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "dashboard_ui"))

from agent_tools import agent_helpers as helpers_mod
from agent_tools.types_and_constants import PlanningAgent
from agents import planning_agent as pl_mod


def _make_chunk(
    file_name="ml.md",
    section="ML > Basics",
    content="gradient descent …",
    score=0.9,
    md_path="gs://v/ml.md",
    chunk_index=0,
):
    return {
        "file_name": file_name,
        "section": section,
        "content": content,
        "score": score,
        "md_path": md_path,
        "chunk_index": chunk_index,
    }


class PlanningAgentTests(unittest.TestCase):
    SESSION = "session-plan"
    QUERY = "我想從生技轉資料工程"
    CHUNKS = [_make_chunk(file_name="ml.md"), _make_chunk(file_name="de.md", section="DE > ETL")]

    def setUp(self):
        self.mock_response = MagicMock()
        self.mock_response.text = "學習路徑內容"
        self.mock_client = MagicMock()
        self.mock_client.models.generate_content.return_value = self.mock_response

        pl_mod.get_genai_client = MagicMock(return_value=self.mock_client)
        pl_mod.save_chat_history = MagicMock()
        pl_mod.vector_search = MagicMock(return_value=list(self.CHUNKS))
        # build_history_context_message 真跑，但其內部 load_chat_history 於 agent_helpers 層 mock
        helpers_mod.load_chat_history = MagicMock(return_value=[])

    def _generate_kwargs(self):
        return self.mock_client.models.generate_content.call_args.kwargs

    # ── generate_learning_map ─────────────────────────────────────────────────

    def test_generate_saves_user_first_and_uses_planning_top_k(self):
        pl_mod.generate_learning_map(self.QUERY, self.SESSION)
        first = pl_mod.save_chat_history.call_args_list[0].kwargs
        self.assertEqual(first["role"], "user")
        self.assertEqual(pl_mod.vector_search.call_args.kwargs["top_k"], PlanningAgent.TOP_K)

    def test_generate_no_chunks_returns_fallback(self):
        pl_mod.vector_search.return_value = []
        result = pl_mod.generate_learning_map(self.QUERY, self.SESSION)
        self.assertEqual(result["sources"], [])
        self.assertIn("沒有", result["answer"])
        self.mock_client.models.generate_content.assert_not_called()

    def test_generate_uses_planning_model_and_stage_initial_map(self):
        pl_mod.generate_learning_map(self.QUERY, self.SESSION)
        self.assertEqual(self._generate_kwargs()["model"], PlanningAgent.MODEL)
        meta = pl_mod.save_chat_history.call_args_list[1].kwargs["metadata"]
        self.assertEqual(meta["stage"], "initial_map")

    def test_generate_retrieved_chunks_file_path_uses_md_path(self):
        pl_mod.generate_learning_map(self.QUERY, self.SESSION)
        meta = pl_mod.save_chat_history.call_args_list[1].kwargs["metadata"]
        self.assertEqual(meta["retrieved_chunks"][0]["file_path"], self.CHUNKS[0]["md_path"])

    def test_generate_answer_and_sources_returned(self):
        result = pl_mod.generate_learning_map(self.QUERY, self.SESSION)
        self.assertEqual(result["answer"], "學習路徑內容")
        self.assertGreater(len(result["sources"]), 0)

    def test_generate_with_history_prepends_context_pair(self):
        # build_history_context_message 回非空 → contents = 2(背景 user/model) + 1 current = 3
        helpers_mod.load_chat_history.return_value = [
            {"role": "user", "parts": [{"text": "上一輪問題"}]},
            {"role": "model", "parts": [{"text": "上一輪回答"}]},
        ]
        pl_mod.generate_learning_map(self.QUERY, self.SESSION)
        self.assertEqual(len(self._generate_kwargs()["contents"]), 3)

    # ── refine_learning_map ───────────────────────────────────────────────────

    def test_refine_uses_stage_refinement(self):
        pl_mod.refine_learning_map("把 MLOps 展開", self.SESSION)
        meta = pl_mod.save_chat_history.call_args_list[1].kwargs["metadata"]
        self.assertEqual(meta["stage"], "refinement")

    def test_refine_no_chunks_still_calls_generate(self):
        # refine 無 chunks 時不 early-return，改用 context fallback 字串續跑
        pl_mod.vector_search.return_value = []
        result = pl_mod.refine_learning_map("追問", self.SESSION)
        self.mock_client.models.generate_content.assert_called_once()
        self.assertEqual(result["answer"], "學習路徑內容")


if __name__ == "__main__":
    unittest.main()
