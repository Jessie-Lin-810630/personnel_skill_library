"""tests/test_silver_service_endpoint.py

Unit tests for silver_service.app 的 /enrich 端點 — 驗證 body 解析、HTTP 狀態碼分支與
對 t_enrich_html_to_markdown 的參數傳遞。全部 mock，不實打 LLM / GCS / MongoDB。
"""

import os
import unittest
from unittest.mock import patch

# ── Inject env vars BEFORE importing silver_service.app ───────────────────────
os.environ.setdefault("ONENOTE_GCS_BUCKET", "fake-bucket")
os.environ.setdefault("ENVIRONMENT", "local")

from task07_silver_service import app as silver_app  # noqa: E402


class TestEnrichEndpoint(unittest.TestCase):
    def setUp(self):
        silver_app.app.config["TESTING"] = True
        self.client = silver_app.app.test_client()

    # ── 400：缺欄位 / 非法 trigger ───────────────────────────────────────────
    def test_missing_page_id_returns_400(self):
        resp = self.client.post("/enrich", json={"dt": "2026-07-01"})
        self.assertEqual(resp.status_code, 400)

    def test_missing_dt_returns_400(self):
        resp = self.client.post("/enrich", json={"page_id": "p1"})
        self.assertEqual(resp.status_code, 400)

    def test_invalid_trigger_returns_400(self):
        resp = self.client.post("/enrich", json={"page_id": "p1", "dt": "2026-07-01", "trigger": "bogus"})
        self.assertEqual(resp.status_code, 400)

    # ── 404：查無版本 ────────────────────────────────────────────────────────
    def test_not_found_returns_404(self):
        with patch.object(silver_app, "t_enrich_html_to_markdown", return_value={"status": "not_found", "error": "x"}):
            resp = self.client.post("/enrich", json={"page_id": "p1", "dt": "2026-07-01"})
        self.assertEqual(resp.status_code, 404)
        self.assertEqual(resp.get_json()["status"], "not_found")

    # ── 200：成功並原樣回傳 dict ─────────────────────────────────────────────
    def test_success_returns_200_with_dict(self):
        result = {"status": "pending_review", "cache_hit": False, "md_path": "gs://b/x.md", "circuit_open": False}
        with patch.object(silver_app, "t_enrich_html_to_markdown", return_value=result) as m:
            resp = self.client.post("/enrich", json={"page_id": "p1", "dt": "2026-07-01"})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.get_json(), result)
        # 預設 trigger=on_demand 並正確帶入
        m.assert_called_once_with(page_id="p1", dt="2026-07-01", trigger="on_demand")

    def test_regenerate_trigger_forwarded(self):
        result = {"status": "pending_review", "cache_hit": False, "md_path": "gs://b/x.md"}
        with patch.object(silver_app, "t_enrich_html_to_markdown", return_value=result) as m:
            resp = self.client.post("/enrich", json={"page_id": "p1", "dt": "2026-07-01", "trigger": "regenerate"})
        self.assertEqual(resp.status_code, 200)
        m.assert_called_once_with(page_id="p1", dt="2026-07-01", trigger="regenerate")

    # ── 200：業務錯誤（如 regenerate quota）帶原 dict ────────────────────────
    def test_business_error_returns_200(self):
        result = {"status": "pending_review", "error": "regenerate quota exceeded", "cache_hit": False}
        with patch.object(silver_app, "t_enrich_html_to_markdown", return_value=result):
            resp = self.client.post("/enrich", json={"page_id": "p1", "dt": "2026-07-01", "trigger": "regenerate"})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.get_json()["error"], "regenerate quota exceeded")

    # ── 500：服務本體未預期例外 ──────────────────────────────────────────────
    def test_unexpected_exception_returns_500(self):
        with patch.object(silver_app, "t_enrich_html_to_markdown", side_effect=RuntimeError("boom")):
            resp = self.client.post("/enrich", json={"page_id": "p1", "dt": "2026-07-01"})
        self.assertEqual(resp.status_code, 500)


if __name__ == "__main__":
    unittest.main()
