"""connect_to_google_genai 測試：Vertex AI (us-central1) chat client 初始化。

genai 全程 mock，不讀真實憑證、不建立真實連線。

只涵蓋雲端路徑，也就是憑證由 Cloud Run runtime service account 的 ADC 供給的那一條。
地端路徑（以 AGENT_PLATFORM_USER_CREDENTIALS 指向的金鑰檔建立 Credentials）寫在
get_genai_client 的註解區塊內，執行期不存在，連 import 都不會發生，因此無法以 patch 攔截、
也無法在此涵蓋。要讓兩條路徑都可測，得把註解開關改成環境變數判斷，那會動到程式本體，
不在本測試檔的範圍。
"""

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "dashboard_ui"))

from agent_tools import connect_to_google_genai as cc_mod


class GetGenaiClientTests(unittest.TestCase):
    def test_returns_client_pointing_at_us_central1(self):
        with (
            patch.object(cc_mod, "genai") as mock_genai,
            patch.dict(cc_mod.os.environ, {"GCP_PROJECT_ID": "proj-1"}, clear=True),
        ):
            client = cc_mod.get_genai_client()

        mock_genai.Client.assert_called_once()
        kwargs = mock_genai.Client.call_args.kwargs
        self.assertTrue(kwargs["vertexai"])
        self.assertEqual(kwargs["project"], "proj-1")
        self.assertEqual(kwargs["location"], "us-central1")
        self.assertEqual(client, mock_genai.Client.return_value)

    def test_raises_when_project_missing(self):
        with (
            patch.object(cc_mod, "genai"),
            patch.dict(cc_mod.os.environ, {}, clear=True),  # 無 GCP_PROJECT_ID
        ):
            with self.assertRaises(EnvironmentError):
                cc_mod.get_genai_client()


if __name__ == "__main__":
    unittest.main()
