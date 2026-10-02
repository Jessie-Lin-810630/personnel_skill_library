"""tests/test_dashboard_auth_gate.py

Unit tests for dashboard_ui/utils/auth_gate.py 的 _resolve_role — 驗證 USER_ALLOWLIST 比對、
USER_ALLOWLIST 外一律無角色（無角色者由 require_login 擋在頁面外），
以及 USER_ALLOWLIST 設定有問題時一律拒絕的保守行為。
不啟動 Streamlit、不連任何服務。
"""

import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parents[1]
# Option A：把 dashboard_ui/ 加進 path，讓模組的裸 import（utils）如 app 實際跑法般解析
sys.path.insert(0, str(PROJECT_ROOT / "dashboard_ui"))

from utils.auth_gate import GUEST_ROLE, _resolve_role  # noqa: E402

ALLOWLIST = '{"owner@example.com": "Note Owner", "ml@example.com": "ML/DL Engineer", "visitor@example.com": "Guest"}'


class TestResolveRole(unittest.TestCase):
    def test_email_in_allowlist_gets_its_role(self):
        with patch.dict(os.environ, {"USER_ALLOWLIST": ALLOWLIST}):
            self.assertEqual(_resolve_role("owner@example.com"), "Note Owner")
            self.assertEqual(_resolve_role("ml@example.com"), "ML/DL Engineer")

    def test_guest_must_be_listed_explicitly(self):
        # Guest 不再是查無結果時的預設值，要當訪客就得明寫在 USER_ALLOWLIST 裡
        with patch.dict(os.environ, {"USER_ALLOWLIST": ALLOWLIST}):
            self.assertEqual(_resolve_role("visitor@example.com"), GUEST_ROLE)

    def test_email_not_in_allowlist_has_no_role(self):
        with patch.dict(os.environ, {"USER_ALLOWLIST": ALLOWLIST}):
            self.assertIsNone(_resolve_role("stranger@example.com"))

    def test_unset_allowlist_denies_everyone(self):
        with patch.dict(os.environ, {"USER_ALLOWLIST": ""}):
            self.assertIsNone(_resolve_role("owner@example.com"))

    def test_invalid_json_denies_everyone(self):
        # 常見誤設：把 shell 用的單引號連同內容一起存進 Secret Manager
        with patch.dict(os.environ, {"USER_ALLOWLIST": f"'{ALLOWLIST}'"}):
            self.assertIsNone(_resolve_role("owner@example.com"))

    def test_non_object_json_denies_everyone(self):
        with patch.dict(os.environ, {"USER_ALLOWLIST": '["owner@example.com"]'}):
            self.assertIsNone(_resolve_role("owner@example.com"))

    def test_empty_email_has_no_role(self):
        with patch.dict(os.environ, {"USER_ALLOWLIST": ALLOWLIST}):
            self.assertIsNone(_resolve_role(""))


if __name__ == "__main__":
    unittest.main()
