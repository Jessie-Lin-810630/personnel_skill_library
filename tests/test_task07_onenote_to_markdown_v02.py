"""
tests/test_task07_onenote_to_markdown_v02.py

Unit tests for task07 v02 (純 Lazy Loading 改版) — type correctness &
exception-handling coverage. 不連 MongoDB / GCS / LLM，全部 mock。

Env vars injected BEFORE any task07_v02 import so the module-level guard in
e_onenote_download.py (sys.exit on missing ONENOTE_CLIENT_ID) is bypassed.
"""

import os
import unittest
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

# ── Inject env vars BEFORE importing task07_v02 ───────────────────────────────
os.environ.setdefault("ONENOTE_CLIENT_ID", "fake-client-id-for-test")
os.environ.setdefault("ONENOTE_GCS_BUCKET", "fake-bucket")
os.environ.setdefault("ENVIRONMENT", "local")

import requests  # noqa: E402

from task07_common import gcs  # noqa: E402
from task07_common.audit_log import (  # noqa: E402
    Environment,
    _now_utc,
    log_api_call,
    log_enrichment_call,
    upsert_version_meta,
)
from task07_common.hashing import html_source_hash  # noqa: E402
from task07_onenote_to_markdown_lazy_loading import e_onenote_download as e  # noqa: E402
from task07_onenote_to_markdown_lazy_loading.e_onenote_download import (  # noqa: E402
    RateLimiter,
    _extract_user_account,
    api_get,
    sanitize,
)
from task07_silver_service import t_enrich_html_to_markdown as t  # noqa: E402

# ═════════════════════════════════════════════════════════════════════════════
# utils/audit_log.py
# ═════════════════════════════════════════════════════════════════════════════


class NowUtcTests(unittest.TestCase):
    def test_returns_utc_datetime(self):
        self.assertIsInstance(_now_utc(), datetime)
        self.assertEqual(_now_utc().tzinfo, timezone.utc)


class EnvironmentEnumTests(unittest.TestCase):
    def test_enum_values(self):
        self.assertEqual(Environment.LOCAL, "local")
        self.assertEqual(Environment.PRODUCTION, "prod")

    def test_invalid_raises(self):
        with self.assertRaises(ValueError):
            Environment("staging")


class LogApiCallTests(unittest.TestCase):
    @patch("task07_common.audit_log._get_db")
    def test_writes_html_hash_and_downloaded(self, mock_get_db):
        mock_col = MagicMock()
        mock_get_db.return_value = {"onenote_graph_api_logs": mock_col}
        with patch.dict(os.environ, {"ENVIRONMENT": "local"}):
            log_api_call(
                page_id="p1",
                request_id="r1",
                method="GET",
                api_endpoint="https://graph/test",
                attempt_id=1,
                status="success",
                status_code=200,
                latency_ms=10,
                html_hash="abc123",
                downloaded=True,
                error_msg=None,
                html_path="u/from_onenote/raw_note/x/dt=2026-06-30/p.html",
            )
        doc = mock_col.insert_one.call_args[0][0]
        self.assertEqual(doc["html_hash"], "abc123")
        self.assertTrue(doc["downloaded"])
        self.assertEqual(doc["event_type"], "onenote_api_download")

    @patch("task07_common.audit_log._get_db")
    def test_mongo_failure_does_not_raise(self, mock_get_db):
        mock_col = MagicMock()
        mock_col.insert_one.side_effect = Exception("conn refused")
        mock_get_db.return_value = {"onenote_graph_api_logs": mock_col}
        with patch.dict(os.environ, {"ENVIRONMENT": "local"}):
            log_api_call(
                page_id=None,
                request_id="r",
                method="GET",
                api_endpoint="https://x",
                attempt_id=1,
                status="failure",
                status_code=500,
                latency_ms=5,
                html_hash=None,
                downloaded=False,
                error_msg="boom",
            )


class LogEnrichmentCallTests(unittest.TestCase):
    @patch("task07_common.audit_log._get_db")
    def test_cache_hit_zero_tokens(self, mock_get_db):
        mock_col = MagicMock()
        mock_get_db.return_value = {"multimodal_llm_enrichment_logs": mock_col}
        with patch.dict(os.environ, {"ENVIRONMENT": "local"}):
            log_enrichment_call(
                page_id="p1",
                html_hash="h1",
                model="gemini",
                cache_hit=True,
                trigger="on_demand",
                status="success",
                latency_ms=0,
                input_tokens=0,
                output_tokens=0,
                total_tokens=0,
                error_msg=None,
            )
        doc = mock_col.insert_one.call_args[0][0]
        self.assertTrue(doc["cache_hit"])
        self.assertEqual(doc["trigger"], "on_demand")
        self.assertEqual(doc["total_tokens"], 0)
        self.assertEqual(doc["event_type"], "llm_enrichment_call")


class UpsertVersionMetaTests(unittest.TestCase):
    @patch("task07_common.audit_log._get_db")
    def test_filter_key_is_page_id_and_dt(self, mock_get_db):
        mock_col = MagicMock()
        mock_get_db.return_value = {"onenote_note_metadata": mock_col}
        upsert_version_meta(page_id="p1", dt="2026-06-30", set_fields={"status": "bronze_stored"})
        filter_doc, update_doc = mock_col.update_one.call_args[0]
        self.assertEqual(filter_doc, {"page_id": "p1", "dt": "2026-06-30"})
        self.assertEqual(update_doc["$set"], {"status": "bronze_stored"})
        self.assertTrue(mock_col.update_one.call_args[1]["upsert"])

    @patch("task07_common.audit_log._get_db")
    def test_set_on_insert_optional(self, mock_get_db):
        mock_col = MagicMock()
        mock_get_db.return_value = {"onenote_note_metadata": mock_col}
        upsert_version_meta(page_id="p2", dt="2026-06-30", set_fields={"status": "x"})
        _, update_doc = mock_col.update_one.call_args[0]
        self.assertNotIn("$setOnInsert", update_doc)

    @patch("task07_common.audit_log._get_db")
    def test_mongo_failure_does_not_raise(self, mock_get_db):
        mock_col = MagicMock()
        mock_col.update_one.side_effect = Exception("write conflict")
        mock_get_db.return_value = {"onenote_note_metadata": mock_col}
        upsert_version_meta(page_id="p3", dt="2026-06-30", set_fields={"status": "x"})


# ═════════════════════════════════════════════════════════════════════════════
# utils/hashing.py & gcs.py
# ═════════════════════════════════════════════════════════════════════════════


class HashingTests(unittest.TestCase):
    def test_deterministic(self):
        self.assertEqual(html_source_hash("<p>a</p>"), html_source_hash("<p>a</p>"))

    def test_changes_with_content(self):
        self.assertNotEqual(html_source_hash("<p>a</p>"), html_source_hash("<p>b</p>"))


class GcsPrefixTests(unittest.TestCase):
    def test_raw_prefix(self):
        self.assertEqual(gcs.raw_note_prefix("u1", "NB", "SEC", "2026-06-30"), "raw-notes/u1/NB/SEC/dt=2026-06-30")

    def test_processed_prefix(self):
        self.assertEqual(
            gcs.processed_note_prefix("u1", "NB", "SEC", "2026-06-30"), "processed-notes/u1/NB/SEC/dt=2026-06-30"
        )

    def test_gs_uri_wraps_bucket(self):
        self.assertEqual(gcs.gs_uri("raw-notes/u1/p.html"), f"gs://{gcs.get_bucket_name()}/raw-notes/u1/p.html")

    def test_split_uri(self):
        self.assertEqual(
            gcs._split_uri("gs://onenote-vaults/raw-notes/u1/p.html"), ("onenote-vaults", "raw-notes/u1/p.html")
        )


# ═════════════════════════════════════════════════════════════════════════════
# e_onenote_download.py helpers
# ═════════════════════════════════════════════════════════════════════════════


class SanitizeTests(unittest.TestCase):
    def test_removes_forbidden_chars(self):
        result = sanitize('a<>:"/\\|?*b')
        for ch in '<>:"/\\|?*':
            self.assertNotIn(ch, result)

    def test_empty_becomes_untitled(self):
        self.assertEqual(sanitize("   "), "Untitled")


class ApiGetTests(unittest.TestCase):
    """驗證 try/except 分流：成功 / 4xx 直接拋 / 傳輸層錯誤會重試。"""

    def _ok_response(self):
        resp = MagicMock(status_code=200)
        resp.raise_for_status.return_value = None
        return resp

    def _http_error_response(self, status_code, reason="Err"):
        resp = MagicMock(status_code=status_code, reason=reason, headers={})
        resp.raise_for_status.side_effect = requests.exceptions.HTTPError(response=resp)
        return resp

    @patch("task07_onenote_to_markdown_lazy_loading.e_onenote_download.log_api_call")
    @patch("task07_onenote_to_markdown_lazy_loading.e_onenote_download.requests.get")
    def test_success_returns_response(self, mock_get, mock_log):
        ok = self._ok_response()
        mock_get.return_value = ok
        result = api_get("https://graph/x", {}, RateLimiter(), None, None)
        self.assertIs(result, ok)
        mock_log.assert_not_called()  # 成功不寫失敗 log

    @patch("task07_onenote_to_markdown_lazy_loading.e_onenote_download.log_api_call")
    @patch("task07_onenote_to_markdown_lazy_loading.e_onenote_download.requests.get")
    def test_4xx_raises_without_retry(self, mock_get, mock_log):
        mock_get.return_value = self._http_error_response(404, "Not Found")
        with self.assertRaises(requests.exceptions.HTTPError):
            api_get("https://graph/missing", {}, RateLimiter(), None, None)
        self.assertEqual(mock_get.call_count, 1)  # 不重試
        mock_log.assert_called_once()

    @patch("task07_onenote_to_markdown_lazy_loading.e_onenote_download.time.sleep", return_value=None)
    @patch("task07_onenote_to_markdown_lazy_loading.e_onenote_download.log_api_call")
    @patch("task07_onenote_to_markdown_lazy_loading.e_onenote_download.requests.get")
    def test_network_error_retries_then_succeeds(self, mock_get, mock_log, _sleep):
        ok = self._ok_response()
        mock_get.side_effect = [requests.exceptions.ConnectTimeout("timeout"), ok]
        result = api_get("https://graph/x", {}, RateLimiter(), None, None)
        self.assertIs(result, ok)
        self.assertEqual(mock_get.call_count, 2)
        mock_log.assert_called_once()  # 第一次網路錯誤有寫 log（status_code=0）
        self.assertEqual(mock_log.call_args.kwargs["status_code"], 0)

    def test_sets_timeout(self):
        self.assertEqual(e.REQUEST_TIMEOUT, (10, 60))

    @patch("task07_onenote_to_markdown_lazy_loading.e_onenote_download.time.sleep", return_value=None)
    @patch("task07_onenote_to_markdown_lazy_loading.e_onenote_download.log_api_call")
    @patch("task07_onenote_to_markdown_lazy_loading.e_onenote_download.requests.get")
    def test_retry_exhausted_logs_summary_then_raises(self, mock_get, mock_log, _sleep):
        mock_get.side_effect = requests.exceptions.ConnectTimeout("timeout")
        with self.assertRaises(RuntimeError):
            api_get("https://graph/x", {}, RateLimiter(), None, None)
        # 10 次逐次 attempt log + 1 筆 retry 耗盡收尾 log
        self.assertEqual(mock_log.call_count, 11)
        self.assertIn("10 retries", mock_log.call_args.kwargs["error_msg"])


class ExtractUserAccountTests(unittest.TestCase):
    def test_extracts_account_prefix(self):
        sections = [{"self": "https://graph/users/abcd123@gmail.com/onenote/sections/x"}]
        self.assertEqual(_extract_user_account(sections), "abcd123")

    def test_returns_none_when_no_match(self):
        self.assertIsNone(_extract_user_account([{"self": "https://graph/no-user"}]))


class DownloadNotebooksFailedBranchTests(unittest.TestCase):
    """content 下載失敗時，download_notebooks 傳給 upsert_version_meta 的參數契約。"""

    @patch("task07_onenote_to_markdown_lazy_loading.e_onenote_download.upsert_version_meta")
    @patch("task07_onenote_to_markdown_lazy_loading.e_onenote_download.log_api_call")
    @patch("task07_onenote_to_markdown_lazy_loading.e_onenote_download.get_all_from_an_api")
    @patch("task07_onenote_to_markdown_lazy_loading.e_onenote_download.api_get")
    def test_content_failure_upserts_fetched_failed(self, mock_api_get, mock_get_all, mock_log, mock_upsert):
        # api_get：第 1 次回 notebook 資料、第 2 次（content 下載）拋例外
        nb_resp = MagicMock()
        nb_resp.json.return_value = {"displayName": "NB"}
        mock_api_get.side_effect = [nb_resp, RuntimeError("Request failed after 10 retries: ...")]
        # get_all_from_an_api：第 1 次回 sections、第 2 次回 pages
        mock_get_all.side_effect = [
            [{"id": "s1", "displayName": "SEC", "self": "https://graph/users/jessie@gmail.com/onenote/sections/s1"}],
            [{"id": "p1", "title": "Note"}],
        ]

        e.download_notebooks(["nb1"], {}, RateLimiter(), None, None, "2026-06-30")

        mock_upsert.assert_called_once()
        args, kwargs = mock_upsert.call_args
        self.assertEqual(args, ("p1", "2026-06-30"))  # (page_id, dt) 走 filter key
        set_fields = kwargs["set_fields"]
        set_on_insert = kwargs["set_on_insert_fields"]
        self.assertEqual(set_fields["status"], "fetched_failed")
        self.assertIn("10 retries", set_fields["error_msg"])  # 保住錯誤訊息
        self.assertNotIn("page_id", set_fields)  # page_id 不放 set_fields
        self.assertEqual(set_fields["onenote_user_id"], "jessie")
        self.assertEqual(set_on_insert["embedded_status"], False)
        # error_msg 不得同時出現在 set_on_insert（避免 $set/$setOnInsert conflict）
        self.assertNotIn("error_msg", set_on_insert)
        # 兩 dict 無 key 重疊
        self.assertEqual(set(set_fields) & set(set_on_insert), set())


# ═════════════════════════════════════════════════════════════════════════════
# t_html_to_markdown.py — Silver on-demand service
# ═════════════════════════════════════════════════════════════════════════════


class CircuitGuardTests(unittest.TestCase):
    def test_opens_after_threshold(self):
        g = t._LLMServiceGuard(max_consecutive_failures=3, cooldown_seconds=60)
        self.assertFalse(g.is_open())
        for _ in range(3):
            g.record_failure()
        self.assertTrue(g.is_open())

    def test_success_resets_counter(self):
        g = t._LLMServiceGuard(max_consecutive_failures=3, cooldown_seconds=60)
        g.record_failure()
        g.record_failure()
        g.record_success()
        g.record_failure()
        self.assertFalse(g.is_open())  # 計數已歸零，再失敗一次不開斷路


class ClassifyNoteTypeTests(unittest.TestCase):
    def test_daily_log_detected(self):
        self.assertEqual(t._classify_note_type("2026-06-30 meeting"), "daily_log")

    def test_knowledge_summary_default(self):
        self.assertEqual(t._classify_note_type("RAG architecture"), "knowledge_summary")


class ConvertImgTagTests(unittest.TestCase):
    def test_img_becomes_markdown(self):
        soup = t.convert_img_tag_to_md_str('<p>x<img alt="pic" src="a.png"></p>')
        self.assertIn("![pic](a.png)", str(soup))


class CallLlmMultimodalTests(unittest.TestCase):
    def test_img_mime_inference(self):
        self.assertEqual(t._img_mime("gs://b/x.PNG"), "image/png")
        self.assertEqual(t._img_mime("gs://b/x.jpg"), "image/jpeg")
        self.assertEqual(t._img_mime("gs://b/x.unknown"), "image/png")

    def test_contents_include_image_parts(self):
        fake_resp = MagicMock()
        fake_resp.parsed = {"tags": [], "alias": "a", "new_content": "x"}
        fake_resp.usage_metadata.prompt_token_count = 10
        fake_resp.usage_metadata.candidates_token_count = 5
        fake_resp.usage_metadata.total_token_count = 15
        client = MagicMock()
        client.models.generate_content.return_value = fake_resp

        raw, usage = t._call_llm(
            client,
            "Note",
            "text ![p](_images/abc.png)",
            ["gs://onenote-vaults/raw-notes/u1/NB/SEC/dt=2026-06-30/_images/abc.png"],
        )

        contents = client.models.generate_content.call_args.kwargs["contents"]
        self.assertEqual(len(contents), 3)  # prompt + label + image
        self.assertEqual(contents[-1].file_data.mime_type, "image/png")
        self.assertEqual(usage["total_tokens"], 15)

    def test_no_images_sends_only_text(self):
        fake_resp = MagicMock()
        fake_resp.parsed = {"tags": [], "alias": "a", "new_content": "x"}
        fake_resp.usage_metadata.prompt_token_count = 1
        fake_resp.usage_metadata.candidates_token_count = 1
        fake_resp.usage_metadata.total_token_count = 2
        client = MagicMock()
        client.models.generate_content.return_value = fake_resp

        t._call_llm(client, "Note", "no image here", [])
        contents = client.models.generate_content.call_args.kwargs["contents"]
        self.assertEqual(len(contents), 1)


class EnrichPageTests(unittest.TestCase):
    """on-demand enrich 的分流：not_found / cache-hit / circuit-open / regenerate quota。"""

    BASE_META = {
        "html_hash": "h1",
        "onenote_user_id": "u1",
        "notebook": "NB",
        "section": "SEC",
        "page_title": "Note",
        "html_path": "gs://onenote-vaults/raw-notes/u1/NB/SEC/dt=2026-06-30/Note.html",
    }

    @patch("task07_silver_service.t_enrich_html_to_markdown.get_version_meta")
    def test_not_found(self, mock_meta):
        mock_meta.return_value = {}
        result = t.t_enrich_html_to_markdown("p1", "2026-06-30")
        self.assertEqual(result["status"], "not_found")

    @patch("task07_silver_service.t_enrich_html_to_markdown.upsert_version_meta")
    @patch("task07_silver_service.t_enrich_html_to_markdown.log_enrichment_call")
    @patch("task07_silver_service.t_enrich_html_to_markdown.find_cached_md_by_hash")
    @patch("task07_silver_service.t_enrich_html_to_markdown.get_version_meta")
    def test_cache_hit_skips_llm(self, mock_meta, mock_cache, mock_log, mock_upsert):
        mock_meta.return_value = dict(self.BASE_META)
        mock_cache.return_value = {"md_path": "u1/.../Note.md", "md_md5": "m5"}
        result = t.t_enrich_html_to_markdown("p1", "2026-06-30")
        self.assertTrue(result["cache_hit"])
        self.assertEqual(result["status"], "pending_review")
        # cache_hit log 寫了 tokens=0
        self.assertTrue(mock_log.call_args.kwargs["cache_hit"])
        self.assertEqual(mock_log.call_args.kwargs["total_tokens"], 0)

    @patch("task07_silver_service.t_enrich_html_to_markdown.upsert_version_meta")
    @patch("task07_silver_service.t_enrich_html_to_markdown.find_cached_md_by_hash")
    @patch("task07_silver_service.t_enrich_html_to_markdown.get_version_meta")
    def test_circuit_open_keeps_bronze(self, mock_meta, mock_cache, mock_upsert):
        mock_meta.return_value = dict(self.BASE_META, status="bronze_stored")
        mock_cache.return_value = {}
        # 強制斷路開啟
        t._guard._open_until = t.time.time() + 60
        try:
            result = t.t_enrich_html_to_markdown("p1", "2026-06-30")
        finally:
            t._guard.record_success()  # 還原
        self.assertTrue(result["circuit_open"])
        self.assertEqual(result["status"], "bronze_stored")

    @patch("task07_silver_service.t_enrich_html_to_markdown.count_regenerate")
    @patch("task07_silver_service.t_enrich_html_to_markdown.get_version_meta")
    def test_regenerate_quota_exceeded(self, mock_meta, mock_count):
        mock_meta.return_value = dict(self.BASE_META, status="pending_review", md_path="u1/.../Note.md")
        mock_count.return_value = t.REGENERATE_QUOTA
        result = t.t_enrich_html_to_markdown("p1", "2026-06-30", trigger="regenerate")
        self.assertEqual(result["error"], "regenerate quota exceeded")


if __name__ == "__main__":
    unittest.main()
