"""tests/test_silver_service_endpoint.py

Unit tests for silver_service.app 的 /enrich 端點 — 驗證欄位檢查、身分驗證、HTTP 狀態碼分支與
對 t_enrich_html_to_markdown 的參數傳遞。全部 mock，不實打 LLM / GCS / MongoDB / Google 公鑰端點。
"""

import os
import unittest
from datetime import UTC, datetime, timedelta
from unittest.mock import patch

import jwt
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient

# ── Inject env vars BEFORE importing silver_service.app ───────────────────────
os.environ.setdefault("ONENOTE_GCS_BUCKET", "fake-bucket")
os.environ.setdefault("ENVIRONMENT", "local")
os.environ.setdefault("TOKEN_ISSUER_SA", "dashboard-sa@example.iam.gserviceaccount.com")
os.environ.setdefault("USER_ALLOWLIST", '{"owner@example.com": "Note Owner"}')

from task07_common import auth  # noqa: E402
from task07_silver_service import app as silver_app  # noqa: E402

ISSUER = "dashboard-sa@example.iam.gserviceaccount.com"
_PRIVATE_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)


def make_token(email="owner@example.com"):
    """簽一張合法的測試用 JWT。"""
    now = datetime.now(UTC)
    payload = {
        "iss": ISSUER,
        "aud": auth.USER_TOKEN_AUDIENCE,
        "email": email,
        "iat": now,
        "exp": now + timedelta(minutes=5),
    }
    return jwt.encode(payload, _PRIVATE_KEY, algorithm="RS256")


class _FakeSigningKey:
    def __init__(self, key):
        self.key = key


class _FakeJWKClient:
    """模擬 PyJWKClient，直接回傳測試公鑰，不對外連線。"""

    def __init__(self, public_key):
        self._public_key = public_key

    def get_signing_key_from_jwt(self, token):
        return _FakeSigningKey(self._public_key)


class TestEnrichEndpoint(unittest.TestCase):
    def setUp(self):
        auth._jwk_client = _FakeJWKClient(_PRIVATE_KEY.public_key())
        self.client = TestClient(silver_app.app, raise_server_exceptions=False)
        self.headers = {"X-User-Token": make_token()}

    def post(self, body, headers=None):
        return self.client.post("/enrich", json=body, headers=self.headers if headers is None else headers)

    # ── 400：缺欄位 / 非法 trigger ───────────────────────────────────────────
    def test_missing_page_id_returns_400(self):
        self.assertEqual(self.post({"dt": "2026-07-01"}).status_code, 400)

    def test_missing_dt_returns_400(self):
        self.assertEqual(self.post({"page_id": "p1"}).status_code, 400)

    def test_invalid_trigger_returns_400(self):
        resp = self.post({"page_id": "p1", "dt": "2026-07-01", "trigger": "bogus"})
        self.assertEqual(resp.status_code, 400)

    # ── 401 / 403：身分驗證 ──────────────────────────────────────────────────
    def test_missing_token_returns_401(self):
        resp = self.post({"page_id": "p1", "dt": "2026-07-01"}, headers={})
        self.assertEqual(resp.status_code, 401)

    def test_email_not_in_allowlist_returns_403(self):
        headers = {"X-User-Token": make_token(email="stranger@example.com")}
        resp = self.post({"page_id": "p1", "dt": "2026-07-01"}, headers=headers)
        self.assertEqual(resp.status_code, 403)

    def test_missing_token_does_not_call_service(self):
        with patch.object(silver_app, "t_enrich_html_to_markdown") as m:
            self.post({"page_id": "p1", "dt": "2026-07-01"}, headers={})
        m.assert_not_called()

    # ── 404：查無版本 ────────────────────────────────────────────────────────
    def test_not_found_returns_404(self):
        with patch.object(silver_app, "t_enrich_html_to_markdown", return_value={"status": "not_found", "error": "x"}):
            resp = self.post({"page_id": "p1", "dt": "2026-07-01"})
        self.assertEqual(resp.status_code, 404)
        self.assertEqual(resp.json()["status"], "not_found")

    # ── 200：成功並原樣回傳 dict ─────────────────────────────────────────────
    def test_success_returns_200_with_dict(self):
        result = {"status": "pending_review", "cache_hit": False, "md_path": "gs://b/x.md", "circuit_open": False}
        with patch.object(silver_app, "t_enrich_html_to_markdown", return_value=result) as m:
            resp = self.post({"page_id": "p1", "dt": "2026-07-01"})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json(), result)
        # 預設 trigger=on_demand 並正確帶入
        m.assert_called_once_with(page_id="p1", dt="2026-07-01", trigger="on_demand")

    def test_regenerate_trigger_forwarded(self):
        result = {"status": "pending_review", "cache_hit": False, "md_path": "gs://b/x.md"}
        with patch.object(silver_app, "t_enrich_html_to_markdown", return_value=result) as m:
            resp = self.post({"page_id": "p1", "dt": "2026-07-01", "trigger": "regenerate"})
        self.assertEqual(resp.status_code, 200)
        m.assert_called_once_with(page_id="p1", dt="2026-07-01", trigger="regenerate")

    # ── 200：業務錯誤（如 regenerate quota）帶原 dict ────────────────────────
    def test_business_error_returns_200(self):
        result = {"status": "pending_review", "error": "regenerate quota exceeded", "cache_hit": False}
        with patch.object(silver_app, "t_enrich_html_to_markdown", return_value=result):
            resp = self.post({"page_id": "p1", "dt": "2026-07-01", "trigger": "regenerate"})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["error"], "regenerate quota exceeded")

    # ── 200：斷路器冷卻中仍算業務結果 ────────────────────────────────────────
    def test_circuit_open_returns_200(self):
        result = {"status": "bronze_stored", "circuit_open": True, "cache_hit": False}
        with patch.object(silver_app, "t_enrich_html_to_markdown", return_value=result):
            resp = self.post({"page_id": "p1", "dt": "2026-07-01"})
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.json()["circuit_open"])

    # ── 500：服務本體未預期例外 ──────────────────────────────────────────────
    def test_unexpected_exception_returns_500(self):
        with patch.object(silver_app, "t_enrich_html_to_markdown", side_effect=RuntimeError("boom")):
            resp = self.post({"page_id": "p1", "dt": "2026-07-01"})
        self.assertEqual(resp.status_code, 500)


if __name__ == "__main__":
    unittest.main()
