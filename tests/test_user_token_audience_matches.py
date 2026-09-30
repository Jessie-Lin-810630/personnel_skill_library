"""tests/test_user_token_audience_matches.py

確認簽發端與驗證端的 X-User-Token audience 常數一致。

dashboard 不 import task07_* 套件（見專案 CLAUDE.md），因此 USER_TOKEN_AUDIENCE 必須兩邊各寫一份。
兩份不一致時，登入與呼叫流程都不會出錯，只會在端點驗簽時回 401 且訊息為 audience 不符，
從畫面上看起來像是登入有問題，不容易追。測試檔不受 import 限制，故在此把兩者釘在一起。
"""

import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
# Option A：把 dashboard_ui/ 加進 path，讓模組的裸 import（utils）如 app 實際跑法般解析
sys.path.insert(0, str(PROJECT_ROOT / "dashboard_ui"))

from utils.user_token_for_silver_and_gold import USER_TOKEN_AUDIENCE as SIGNER_AUDIENCE  # noqa: E402

from task07_common.auth import USER_TOKEN_AUDIENCE as VERIFIER_AUDIENCE  # noqa: E402


class TestAudienceConstantsMatch(unittest.TestCase):
    def test_signer_and_verifier_use_the_same_audience(self):
        self.assertEqual(
            SIGNER_AUDIENCE,
            VERIFIER_AUDIENCE,
            "簽發端與驗證端的 USER_TOKEN_AUDIENCE 必須一致，"
            "否則端點會以 audience 不符回 401。"
            "兩處為 dashboard_ui/utils/user_token_for_silver_and_gold.py 與 task07_common/auth.py",
        )


if __name__ == "__main__":
    unittest.main()
