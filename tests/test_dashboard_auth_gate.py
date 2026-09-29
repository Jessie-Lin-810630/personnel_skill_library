"""tests/test_dashboard_auth_gate.py

Unit tests for dashboard_ui/utils/auth_gate.py 的 resolve_role — 驗證允許清單比對、
清單外落 Guest，以及清單設定有問題時的保守行為。不啟動 Streamlit、不連任何服務。
"""

import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parents[1]
# Option A：把 dashboard_ui/ 加進 path，讓模組的裸 import（utils）如 app 實際跑法般解析
sys.path.insert(0, str(PROJECT_ROOT / "dashboard_ui"))

from utils.auth_gate import GUEST_ROLE, resolve_role  # noqa: E402

ALLOWLIST = '{"owner@example.com": "Note Owner", "ml@example.com": "ML/DL Engineer"}'


class TestResolveRole(unittest.TestCase):
    def test_email_in_allowlist_gets_its_role(self):
        with patch.dict(os.environ, {"USER_ALLOWLIST": ALLOWLIST}):
            self.assertEqual(resolve_role("owner@example.com"), "Note Owner")
            self.assertEqual(resolve_role("ml@example.com"), "ML/DL Engineer")

    def test_email_not_in_allowlist_falls_back_to_guest(self):
        with patch.dict(os.environ, {"USER_ALLOWLIST": ALLOWLIST}):
            self.assertEqual(resolve_role("stranger@example.com"), GUEST_ROLE)

    def test_unset_allowlist_falls_back_to_guest(self):
        with patch.dict(os.environ, {"USER_ALLOWLIST": ""}):
            self.assertEqual(resolve_role("owner@example.com"), GUEST_ROLE)

    def test_invalid_json_falls_back_to_guest(self):
        # 常見誤設：把 shell 用的單引號連同內容一起存進 Secret Manager
        with patch.dict(os.environ, {"USER_ALLOWLIST": f"'{ALLOWLIST}'"}):
            self.assertEqual(resolve_role("owner@example.com"), GUEST_ROLE)

    def test_non_object_json_falls_back_to_guest(self):
        with patch.dict(os.environ, {"USER_ALLOWLIST": '["owner@example.com"]'}):
            self.assertEqual(resolve_role("owner@example.com"), GUEST_ROLE)

    def test_empty_email_falls_back_to_guest(self):
        with patch.dict(os.environ, {"USER_ALLOWLIST": ALLOWLIST}):
            self.assertEqual(resolve_role(""), GUEST_ROLE)


if __name__ == "__main__":
    unittest.main()
