"""
測試策略:
  - R1 測試: 完全不需要 mock，純邏輯函式
  - R2 測試: mock load_chat_history 與 genai.Client，不打真實 API
  - route() 整合測試: mock _r2_llm_classify 與 save_chat_history
"""

import importlib.util
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

# ── Stub heavy / external packages ───────────────────────────────────────────
sys.modules.setdefault("loguru", MagicMock())
sys.modules.setdefault("google.oauth2", MagicMock())
sys.modules.setdefault("google.oauth2.service_account", MagicMock())
sys.modules.setdefault("google.genai", MagicMock())
sys.modules.setdefault("google.genai.types", MagicMock())

# dashboard_ui package stubs
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
sys.modules.setdefault("dashboard_ui.agent_tools.chat_history", MagicMock())
sys.modules.setdefault(
    "dashboard_ui.agents",
    MagicMock(
        __path__=[str(PROJECT_ROOT / "dashboard_ui" / "agents")],
        __name__="dashboard_ui.agents",
    ),
)

# ── Load intent_router_agent ──────────────────────────────────────────────────
_spec = importlib.util.spec_from_file_location(
    "dashboard_ui.agents.intent_router_agent",
    str(PROJECT_ROOT / "dashboard_ui" / "agents" / "intent_router_agent.py"),
)
router_mod = importlib.util.module_from_spec(_spec)
router_mod.__package__ = "dashboard_ui.agents"
sys.modules["dashboard_ui.agents.intent_router_agent"] = router_mod
_spec.loader.exec_module(router_mod)

_r1_keyword_match = router_mod._r1_keyword_match
_r2_llm_classify = router_mod._r2_llm_classify
route = router_mod.route

_MODULE = "dashboard_ui.agents.intent_router_agent"


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
        # 同時包含兩種關鍵字，應優先導向 planning
        target, score = _r1_keyword_match("幫我查詢相關筆記，然後規劃學習路徑")
        self.assertEqual(target, "planning_agent")

    def test_無關輸入_回傳_None(self):
        target, score = _r1_keyword_match("好餓")
        self.assertIsNone(target)
        self.assertEqual(score, 0.0)

    def test_英文_planning_keyword(self):
        target, score = _r1_keyword_match("give me a learning roadmap for data engineering")
        self.assertEqual(target, "planning_agent")

    def test_旅遊規劃_命中_planning_keyword(self):
        # 已知誤判：「規劃」這個詞太廣，旅遊規劃也會命中
        # 這個 test 記錄現有行為，提醒未來可收窄關鍵字
        target, score = _r1_keyword_match("幫我規劃神戶三日旅遊方案")
        self.assertEqual(target, "planning_agent")  # 目前行為，不代表正確


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
    def test_正常輸出_rag(self, mock_load):
        client = self._make_mock_client("rag_agent:0.88")
        target, score = _r2_llm_classify("好餓唷", "test_session", client)
        self.assertEqual(target, "rag_agent")
        self.assertEqual(score, 0.88)

    @patch(f"{_MODULE}.load_chat_history", return_value=[])
    def test_正常輸出_planning(self, mock_load):
        client = self._make_mock_client("planning_agent:0.95")
        target, score = _r2_llm_classify("寶可夢大師成長路徑", "test_session", client)
        self.assertEqual(target, "planning_agent")
        self.assertEqual(score, 0.95)

    @patch(f"{_MODULE}.load_chat_history", return_value=[])
    def test_格式異常_預設_rag(self, mock_load):
        # 模擬 LLM 輸出非預期格式（例如輸出整段解釋文字）
        client = self._make_mock_client("目前的筆記裡沒有相關內容。")
        target, score = _r2_llm_classify("訂機票", "test_session", client)
        self.assertEqual(target, "rag_agent")
        self.assertEqual(score, 0.5)

    @patch(f"{_MODULE}.load_chat_history")
    def test_帶入_history_驗證_contents_組裝(self, mock_load):
        """確認 history 有正確被帶入 contents，不是空的"""
        # _r2_llm_classify 呼叫 load_chat_history 兩次 (rag, planning)
        # 第一次 (rag) 回傳 2 筆，第二次 (planning) 回傳空，合計 2 + 1 current = 3 筆
        mock_load.side_effect = [
            [
                {"role": "user",  "parts": [{"text": "MongoDB 索引怎麼建？"}]},
                {"role": "model", "parts": [{"text": "MongoDB 索引可以透過 createIndex() 建立..."}]},
            ],
            [],
        ]
        client = self._make_mock_client("planning_agent:0.91")
        target, score = _r2_llm_classify("接下來我該學什麼", "test_session", client)

        call_kwargs = client.models.generate_content.call_args
        contents = call_kwargs.kwargs.get("contents") or call_kwargs.args[1]
        self.assertEqual(len(contents), 3)   # 2 筆 rag history + 1 筆當前問題
        self.assertEqual(contents[-1]["role"], "user")
        self.assertIn("接下來我該學什麼", contents[-1]["parts"][0]["text"])


# ════════════════════════════════════════════════════════════
# route() 整合測試
# ════════════════════════════════════════════════════════════

class TestRoute(unittest.TestCase):

    @patch(f"{_MODULE}.save_chat_history")
    def test_R1_命中_不呼叫_R2(self, mock_save):
        result = route("幫我規劃學習路徑", "test_session")
        self.assertEqual(result, "planning_agent")
        mock_save.assert_called_once()
        saved_metadata = mock_save.call_args.kwargs["metadata"]
        self.assertEqual(saved_metadata["method"], "r1_keyword")

    @patch(f"{_MODULE}.save_chat_history")
    @patch(f"{_MODULE}._r2_llm_classify", return_value=("rag_agent", 0.82))
    @patch(f"{_MODULE}._get_genai_client")
    def test_R1_未命中_呼叫_R2(self, mock_client, mock_r2, mock_save):
        result = route("好餓", "test_session")
        self.assertEqual(result, "rag_agent")
        mock_r2.assert_called_once()
        saved_metadata = mock_save.call_args.kwargs["metadata"]
        self.assertEqual(saved_metadata["method"], "r2_llm")
        self.assertEqual(saved_metadata["intent_score"], 0.82)

    @patch(f"{_MODULE}.save_chat_history")
    def test_save_metadata_含_intent_score(self, mock_save):
        route("查詢 MongoDB 索引語法", "test_session")
        saved_metadata = mock_save.call_args.kwargs["metadata"]
        self.assertIn("intent_score", saved_metadata)
        self.assertIsInstance(saved_metadata["intent_score"], float)


if __name__ == "__main__":
    unittest.main()
