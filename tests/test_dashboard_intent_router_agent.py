"""意圖分類 router 測試。

測試策略:
  - R1 測試: 純邏輯關鍵字比對，不需 mock
  - R2 測試: mock load_chat_history 與 genai.Client，不打真實 API
  - route() 整合測試: mock _r2_llm_classify 與 save_chat_history
"""

import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

PROJECT_ROOT = Path(__file__).resolve().parents[1]
# Option A：把 dashboard_ui/ 加進 path，讓模組的裸 import 如 app 實際跑法般解析
sys.path.insert(0, str(PROJECT_ROOT / "dashboard_ui"))

from agent_tools.types_and_constants import RouterAgent
from agents import intent_router_agent as router_mod

_r1_keyword_match = router_mod._r1_keyword_match
_r2_llm_classify = router_mod._r2_llm_classify
route = router_mod.route

_MODULE = "agents.intent_router_agent"


# ════════════════════════════════════════════════════════════
# R1 測試（純邏輯，不需要任何 mock）
# ════════════════════════════════════════════════════════════


class TestR1KeywordMatch(unittest.TestCase):
    def test_planning_keyword_命中(self):
        target, score = _r1_keyword_match("幫我規劃初階資料工程師的學習")
        self.assertEqual(target, "planning_agent")
        self.assertGreater(score, 0)
        self.assertLessEqual(score, 1.0)

    def test_rag_keyword_命中(self):
        target, score = _r1_keyword_match("幫我查詢 Database 的索引建立語法")
        self.assertEqual(target, "rag_agent")
        self.assertGreater(score, 0)
        self.assertLessEqual(score, 1.0)

    def test_planning_優先於_rag(self):
        # 同時包含兩種關鍵字，應優先導向 planning（R1 先掃 planning keyword）
        target, _ = _r1_keyword_match("幫我查詢相關筆記，然後規劃學習路徑")
        self.assertEqual(target, "planning_agent")

    def test_無關輸入_回傳_None(self):
        target, score = _r1_keyword_match("好餓")
        self.assertIsNone(target)
        self.assertEqual(score, 0.0)

    def test_英文_planning_keyword(self):
        target, _ = _r1_keyword_match("give me a learning roadmap for data engineering")
        self.assertEqual(target, "planning_agent")

    def test_旅遊規劃_命中_planning_keyword(self):
        # 已知誤判：「規劃」太廣，旅遊規劃也會命中；記錄現有行為
        target, _ = _r1_keyword_match("幫我規劃神戶三日旅遊方案")
        self.assertEqual(target, "planning_agent")


# ════════════════════════════════════════════════════════════
# R2 測試（mock API，不打真實請求）
# ════════════════════════════════════════════════════════════


class TestR2LLMClassify(unittest.TestCase):
    def _make_mock_client(self, llm_output: str) -> MagicMock:
        mock_response = MagicMock()
        mock_response.text = llm_output

        mock_client = MagicMock()
        mock_client.models.generate_content.return_value = mock_response
        return mock_client

    @patch(f"{_MODULE}.load_chat_history", return_value=[])
    def test_輸出含_rag_回傳_rag_固定信心_0_95(self, mock_load):
        # 現行 _r2 僅以「是否含 planning」判斷，信心固定 0.95
        client = self._make_mock_client("rag_agent")
        target, score = _r2_llm_classify("好餓唷", "test_session", client)
        self.assertEqual(target, "rag_agent")
        self.assertEqual(score, 0.95)

    @patch(f"{_MODULE}.load_chat_history", return_value=[])
    def test_輸出含_planning_回傳_planning_固定信心_0_95(self, mock_load):
        client = self._make_mock_client("planning_agent")
        target, score = _r2_llm_classify("寶可夢大師成長路徑", "test_session", client)
        self.assertEqual(target, "planning_agent")
        self.assertEqual(score, 0.95)

    @patch(f"{_MODULE}.load_chat_history", return_value=[])
    def test_輸出無_planning_字樣_預設_rag(self, mock_load):
        # LLM 回整段解釋文字（不含 planning）→ 預設 rag_agent
        client = self._make_mock_client("目前的筆記裡沒有相關內容。")
        target, score = _r2_llm_classify("訂機票", "test_session", client)
        self.assertEqual(target, "rag_agent")
        self.assertEqual(score, 0.95)

    @patch(f"{_MODULE}.load_chat_history")
    def test_帶入_rag_history_組裝背景_contents(self, mock_load):
        # 第一次 (rag) 回 2 筆、第二次 (planning) 回空 → 背景摺成 1 user + 1 model ack + 1 current = 3
        mock_load.side_effect = [
            [
                {"role": "user", "parts": [{"text": "MongoDB 索引怎麼建？"}]},
                {"role": "model", "parts": [{"text": "MongoDB 索引可以透過 createIndex() 建立..."}]},
            ],
            [],
        ]
        client = self._make_mock_client("planning_agent")
        _r2_llm_classify("接下來我該學什麼", "test_session", client)

        call = client.models.generate_content.call_args
        contents = call.kwargs.get("contents") or call.args[1]
        self.assertEqual(len(contents), 3)  # 背景 user + model ack + 當前 user
        self.assertEqual(contents[-1]["role"], "user")
        self.assertIn("接下來我該學什麼", contents[-1]["parts"][0]["text"])

    @patch(f"{_MODULE}.load_chat_history", return_value=[])
    def test_無_history_時_contents_只有當前問題(self, mock_load):
        # 兩次 load 都回空 → 不加背景，只有 1 筆 current user
        client = self._make_mock_client("rag_agent")
        _r2_llm_classify("查詢筆記", "test_session", client)
        call = client.models.generate_content.call_args
        contents = call.kwargs.get("contents") or call.args[1]
        self.assertEqual(len(contents), 1)
        self.assertEqual(contents[0]["role"], "user")

    @patch(f"{_MODULE}.load_chat_history", return_value=[])
    def test_使用_router_agent_model(self, mock_load):
        client = self._make_mock_client("rag_agent")
        _r2_llm_classify("查詢筆記", "test_session", client)
        call = client.models.generate_content.call_args
        self.assertEqual(call.kwargs.get("model"), RouterAgent.MODEL)


# ════════════════════════════════════════════════════════════
# route() 整合測試（回傳 {"agent_target": ...} dict）
# ════════════════════════════════════════════════════════════


class TestRoute(unittest.TestCase):
    @patch(f"{_MODULE}.save_chat_history")
    def test_R1_命中_不呼叫_R2(self, mock_save):
        result = route("幫我規劃學習路徑", "test_session")
        self.assertEqual(result, {"agent_target": "planning_agent"})
        mock_save.assert_called_once()
        saved_metadata = mock_save.call_args.kwargs["metadata"]
        self.assertEqual(saved_metadata["method"], "r1_keyword")

    @patch(f"{_MODULE}.save_chat_history")
    @patch(f"{_MODULE}._r2_llm_classify", return_value=("rag_agent", 0.82))
    @patch(f"{_MODULE}.get_genai_client")
    def test_R1_未命中_呼叫_R2(self, mock_client, mock_r2, mock_save):
        result = route("好餓", "test_session")
        self.assertEqual(result, {"agent_target": "rag_agent"})
        mock_r2.assert_called_once()
        saved_metadata = mock_save.call_args.kwargs["metadata"]
        self.assertEqual(saved_metadata["method"], "r2_llm")
        self.assertEqual(saved_metadata["intent_score"], 0.82)
        self.assertEqual(saved_metadata["model"], RouterAgent.MODEL)

    @patch(f"{_MODULE}.save_chat_history")
    def test_route_回傳_dict_含_agent_target_key(self, mock_save):
        result = route("查詢 MongoDB 索引語法", "test_session")
        self.assertIn("agent_target", result)
        self.assertEqual(result["agent_target"], "rag_agent")

    @patch(f"{_MODULE}.save_chat_history")
    def test_save_metadata_含_intent_score(self, mock_save):
        route("查詢 MongoDB 索引語法", "test_session")
        saved_metadata = mock_save.call_args.kwargs["metadata"]
        self.assertIn("intent_score", saved_metadata)
        self.assertIsInstance(saved_metadata["intent_score"], float)


if __name__ == "__main__":
    unittest.main()
