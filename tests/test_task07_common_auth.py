"""tests/test_task07_common_auth.py

Unit tests for task07_common.auth — 驗證 X-User-Token 的驗簽、到期、 USER_ALLOWLIST 比對，
以及請求驗證失敗改回 400 的 handler。以自造的 RSA 金鑰對簽 token，不連網、不打 Google。
"""

import os
import unittest
from datetime import UTC, datetime, timedelta
from unittest.mock import patch

import jwt
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
from pydantic import BaseModel

# 一律覆寫而非 setdefault：其他測試可能已先觸發 load_dotenv 把本機真實設定載進環境。
# 本檔的 setUp 另有 patch.dict 保險，這一行是為了 import 階段就有值。
os.environ["TOKEN_ISSUER_SA"] = "dashboard-sa@example.iam.gserviceaccount.com"

from task07_common import auth  # noqa: E402

ISSUER = "dashboard-sa@example.iam.gserviceaccount.com"
ALLOWLIST = '{"owner@example.com": "Note Owner", "ml@example.com": "ML/DL Engineer", "visitor@example.com": "Guest"}'

_PRIVATE_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
_OTHER_PRIVATE_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)


def make_token(
    email="owner@example.com",
    key=None,
    expires_in_seconds=300,
    audience=auth.USER_TOKEN_AUDIENCE,
    issuer=ISSUER,
):
    """簽一張測試用的 JWT，預設是一張各項條件都合法的 token。"""
    now = datetime.now(UTC)
    payload = {
        "iss": issuer,
        "aud": audience,
        "email": email,
        "iat": now,
        "exp": now + timedelta(seconds=expires_in_seconds),
    }
    return jwt.encode(payload, key or _PRIVATE_KEY, algorithm="RS256")


class _FakeSigningKey:
    """模擬 PyJWKClient 取回的金鑰物件，只需要 key 屬性。"""

    def __init__(self, key):
        self.key = key


class _FakeJWKClient:
    """模擬 PyJWKClient，直接回傳指定的公鑰，不對外連線。"""

    def __init__(self, public_key):
        self._public_key = public_key

    def get_signing_key_from_jwt(self, token):
        return _FakeSigningKey(self._public_key)


class _UnreachableJWKClient:
    """模擬抓不到 Google 公鑰端點的情形。"""

    def get_signing_key_from_jwt(self, token):
        raise jwt.PyJWKClientConnectionError("fail to fetch jwks")


def build_app():
    """建一個只有一個受保護端點的最小 app，用來驅動 dependency。"""
    app = FastAPI()
    auth.register_validation_error_handler(app)

    class Body(BaseModel):
        page_id: str

    @app.post("/probe")
    def probe(body: Body, user: auth.UserIdentity = Depends(auth.verify_user)):
        return {"email": user.email, "role": user.role, "page_id": body.page_id}

    return app


class TestVerifyUser(unittest.TestCase):
    def setUp(self):
        auth._jwk_client = _FakeJWKClient(_PRIVATE_KEY.public_key())
        self.client = TestClient(build_app(), raise_server_exceptions=False)
        self.env = patch.dict(
            os.environ,
            {"USER_ALLOWLIST": ALLOWLIST, "TOKEN_ISSUER_SA": ISSUER},
        )
        self.env.start()
        self.addCleanup(self.env.stop)

    def post(self, token=None):
        headers = {"X-User-Token": token} if token else {}
        return self.client.post("/probe", json={"page_id": "p1"}, headers=headers)

    def test_valid_token_in_allowlist_returns_200_with_role(self):
        resp = self.post(make_token())
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["email"], "owner@example.com")
        self.assertEqual(resp.json()["role"], "Note Owner")

    def test_bearer_prefix_is_accepted(self):
        resp = self.post(f"Bearer {make_token(email='ml@example.com')}")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["role"], "ML/DL Engineer")

    def test_missing_token_returns_401(self):
        self.assertEqual(self.post().status_code, 401)

    def test_wrong_signature_returns_401(self):
        self.assertEqual(self.post(make_token(key=_OTHER_PRIVATE_KEY)).status_code, 401)

    def test_expired_token_returns_401(self):
        self.assertEqual(self.post(make_token(expires_in_seconds=-10)).status_code, 401)

    def test_wrong_issuer_returns_401(self):
        self.assertEqual(self.post(make_token(issuer="someone-else@example.com")).status_code, 401)

    def test_wrong_audience_returns_401(self):
        self.assertEqual(self.post(make_token(audience="another-service")).status_code, 401)

    def test_email_not_in_allowlist_returns_403(self):
        self.assertEqual(self.post(make_token(email="stranger@example.com")).status_code, 403)

    def test_guest_role_returns_403(self):
        # Guest 明寫在 USER_ALLOWLIST 裡才能登入 dashboard，過得了「不在其中」那一關，需單獨擋
        self.assertEqual(self.post(make_token(email="visitor@example.com")).status_code, 403)

    def test_empty_allowlist_returns_403(self):
        with patch.dict(os.environ, {"USER_ALLOWLIST": ""}):
            self.assertEqual(self.post(make_token()).status_code, 403)

    def test_jwk_endpoint_unreachable_returns_503(self):
        # token 本身完全合法，失敗的是本服務連不到 Google 的公鑰端點，不該回 401
        auth._jwk_client = _UnreachableJWKClient()
        self.assertEqual(self.post(make_token()).status_code, 503)


class TestValidationErrorHandler(unittest.TestCase):
    def setUp(self):
        auth._jwk_client = _FakeJWKClient(_PRIVATE_KEY.public_key())
        self.client = TestClient(build_app(), raise_server_exceptions=False)
        self.env = patch.dict(
            os.environ,
            {"USER_ALLOWLIST": ALLOWLIST, "TOKEN_ISSUER_SA": ISSUER},
        )
        self.env.start()
        self.addCleanup(self.env.stop)

    def test_missing_field_returns_400_not_422(self):
        resp = self.client.post("/probe", json={}, headers={"X-User-Token": make_token()})
        self.assertEqual(resp.status_code, 400)


class TestLoadAllowlist(unittest.TestCase):
    def test_invalid_json_raises_runtime_error(self):
        with patch.dict(os.environ, {"USER_ALLOWLIST": "{not json"}):
            with self.assertRaises(RuntimeError):
                auth._load_allowlist()

    def test_non_object_json_raises_runtime_error(self):
        with patch.dict(os.environ, {"USER_ALLOWLIST": '["a", "b"]'}):
            with self.assertRaises(RuntimeError):
                auth._load_allowlist()


if __name__ == "__main__":
    unittest.main()
