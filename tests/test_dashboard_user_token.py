"""tests/test_dashboard_user_token.py

Unit tests for dashboard_ui/utils/user_token_for_silver_and_gold.py 的 mint_user_token —
驗證 payload 內容、狀態碼判斷與憑證來源選擇。全部 mock，不實打 IAM Credentials。
"""

import json
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parents[1]
# Option A：把 dashboard_ui/ 加進 path，讓模組的裸 import（utils）如 app 實際跑法般解析
sys.path.insert(0, str(PROJECT_ROOT / "dashboard_ui"))

from utils import user_token_for_silver_and_gold as ut  # noqa: E402

ISSUER = "dashboard-sa@example.iam.gserviceaccount.com"


class _FakeResponse:
    """模擬 requests 的回應，只提供本模組會用到的介面。"""

    def __init__(self, status_code, body=None):
        self.status_code = status_code
        self._body = body if body is not None else {}
        self.text = json.dumps(self._body)

    def json(self):
        return self._body


class _FakeSession:
    """模擬 AuthorizedSession，記下送出的 payload 並回傳指定的假回應。"""

    def __init__(self, response):
        self._response = response
        self.sent_payload = None
        self.sent_url = None

    def post(self, url, json=None, timeout=None):
        self.sent_url = url
        self.sent_payload = json
        return self._response


class _MintTestCase(unittest.TestCase):
    """共用的環境設定：指定 issuer，並且不走地端金鑰檔那條路。"""

    def setUp(self):
        self.env = patch.dict(
            os.environ,
            {"TOKEN_ISSUER_SA": ISSUER, "DASHBOARD_SIGNER_CREDENTIALS": ""},
        )
        self.env.start()
        self.addCleanup(self.env.stop)

    def mint_with(self, response, email="owner@example.com"):
        """以指定的假回應執行一次 mint_user_token，回傳 (結果或例外, 假 session)。"""
        session = _FakeSession(response)
        with (
            patch.object(ut, "_get_signer_credentials", return_value=object()),
            patch.object(ut.google.auth.transport.requests, "AuthorizedSession", return_value=session),
        ):
            return ut.mint_user_token(email), session


class TestPayload(_MintTestCase):
    def test_payload_contains_expected_claims(self):
        _, session = self.mint_with(_FakeResponse(200, {"signedJwt": "fake.jwt.value"}))
        payload = json.loads(session.sent_payload["payload"])
        self.assertEqual(payload["iss"], ISSUER)
        self.assertEqual(payload["aud"], ut.USER_TOKEN_AUDIENCE)
        self.assertEqual(payload["email"], "owner@example.com")
        self.assertEqual(payload["exp"] - payload["iat"], ut.TOKEN_TTL_SECONDS)

    def test_payload_does_not_carry_role(self):
        # 角色由端點自己查 USER_ALLOWLIST 推導，簽進 token 會變成沒人讀的欄位
        _, session = self.mint_with(_FakeResponse(200, {"signedJwt": "fake.jwt.value"}))
        payload = json.loads(session.sent_payload["payload"])
        self.assertNotIn("role", payload)

    def test_payload_is_sent_as_json_string(self):
        # signJwt 要求 payload 欄位是已序列化的 JSON 字串，不是巢狀物件
        _, session = self.mint_with(_FakeResponse(200, {"signedJwt": "fake.jwt.value"}))
        self.assertIsInstance(session.sent_payload["payload"], str)

    def test_url_targets_the_issuer_service_account(self):
        _, session = self.mint_with(_FakeResponse(200, {"signedJwt": "fake.jwt.value"}))
        self.assertIn(ISSUER, session.sent_url)
        self.assertTrue(session.sent_url.endswith(":signJwt"))

    def test_returns_signed_jwt(self):
        token, _ = self.mint_with(_FakeResponse(200, {"signedJwt": "fake.jwt.value"}))
        self.assertEqual(token, "fake.jwt.value")


class TestStatusCodeHandling(_MintTestCase):
    def test_non_200_success_status_is_rejected(self):
        # 201/204 雖然 resp.ok 為 True，但 signJwt 成功一律回 200，其他值代表非預期行為
        for code in (201, 204):
            with self.subTest(code=code):
                with self.assertRaises(RuntimeError):
                    self.mint_with(_FakeResponse(code, {"signedJwt": "should-not-be-used"}))

    def test_redirect_status_is_rejected(self):
        # 3xx 的 resp.ok 為 True，若用 resp.ok 判斷會放行，但回應沒有 signedJwt
        for code in (301, 302, 399):
            with self.subTest(code=code):
                with self.assertRaises(RuntimeError):
                    self.mint_with(_FakeResponse(code, {}))

    def test_error_status_is_rejected(self):
        for code in (400, 403, 500):
            with self.subTest(code=code):
                with self.assertRaises(RuntimeError):
                    self.mint_with(_FakeResponse(code, {"error": {"message": "nope"}}))

    def test_200_without_signed_jwt_is_rejected(self):
        with self.assertRaises(RuntimeError):
            self.mint_with(_FakeResponse(200, {}))

    def test_200_with_empty_signed_jwt_is_rejected(self):
        # 空字串不可當成合法 token 送出去
        with self.assertRaises(RuntimeError):
            self.mint_with(_FakeResponse(200, {"signedJwt": ""}))


class TestIssuerRequired(unittest.TestCase):
    def test_missing_issuer_raises(self):
        with patch.dict(os.environ, {"TOKEN_ISSUER_SA": ""}):
            with self.assertRaises(RuntimeError):
                ut.mint_user_token("owner@example.com")


class TestSignerCredentialSource(unittest.TestCase):
    def test_uses_key_file_when_env_set(self):
        # 地端：明確指定 dashboard SA 的金鑰檔，不讓 google.auth.default 抓到別支 SA
        with patch.dict(os.environ, {"DASHBOARD_SIGNER_CREDENTIALS": "/tmp/fake-key.json"}):
            with patch("google.oauth2.service_account.Credentials.from_service_account_file") as from_file:
                from_file.return_value = "key-file-credentials"
                self.assertEqual(ut._get_signer_credentials(), "key-file-credentials")
                from_file.assert_called_once()

    def test_falls_back_to_adc_when_env_unset(self):
        # 雲端：不設變數，走 ADC 取 Cloud Run 的 runtime service account
        with patch.dict(os.environ, {"DASHBOARD_SIGNER_CREDENTIALS": ""}):
            with patch.object(ut.google.auth, "default", return_value=("adc-credentials", "proj")) as default:
                self.assertEqual(ut._get_signer_credentials(), "adc-credentials")
                default.assert_called_once()


if __name__ == "__main__":
    unittest.main()
