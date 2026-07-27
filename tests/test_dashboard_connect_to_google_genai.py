"""connect_to_google_genai 測試：Vertex AI (us-central1) chat client 初始化。

Credentials 與 genai 皆 mock，不讀真實憑證、不建立真實連線。
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
        env = {"AGENT_PLATFORM_USER_CREDENTIALS": "/x.json", "GCP_PROJECT_ID": "proj-1"}
        with (
            patch.object(cc_mod, "Credentials"),
            patch.object(cc_mod, "genai") as mock_genai,
            patch.dict(cc_mod.os.environ, env, clear=True),
        ):
            client = cc_mod.get_genai_client()

        mock_genai.Client.assert_called_once()
        kwargs = mock_genai.Client.call_args.kwargs
        self.assertTrue(kwargs["vertexai"])
        self.assertEqual(kwargs["project"], "proj-1")
        self.assertEqual(kwargs["location"], "us-central1")
        self.assertEqual(client, mock_genai.Client.return_value)

    def test_raises_when_project_missing(self):
        env = {"AGENT_PLATFORM_USER_CREDENTIALS": "/x.json"}  # 無 GCP_PROJECT_ID
        with (
            patch.object(cc_mod, "Credentials"),
            patch.object(cc_mod, "genai"),
            patch.dict(cc_mod.os.environ, env, clear=True),
        ):
            with self.assertRaises(EnvironmentError):
                cc_mod.get_genai_client()


if __name__ == "__main__":
    unittest.main()
