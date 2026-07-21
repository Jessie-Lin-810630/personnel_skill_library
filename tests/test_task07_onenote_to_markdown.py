"""
tests/test_task07_onenote_to_markdown.py

Unit tests for task07 — type correctness & exception-handling coverage.

Env vars injected BEFORE any task07 import so that the module-level
guard in e_onenote_download.py (sys.exit on missing env vars) is bypassed.
"""

import os
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

# ── Inject env vars BEFORE importing task07 ───────────────────────────────────
os.environ.setdefault("ONENOTE_CLIENT_ID", "fake-client-id-for-test")
os.environ.setdefault("ONENOTE_OUTPUT_DIR", "/tmp/onenote_test")
os.environ.setdefault("ENVIRONMENT", "local")

from task07_onenote_to_markdown.e_onenote_download import (  # noqa: E402
    RateLimiter,
    _parse_onenote_dt,
    api_get,
    get_all,
    sanitize,
)
from task07_onenote_to_markdown.l_save_markdown import l_save_markdown  # noqa: E402
from task07_onenote_to_markdown.t_html_to_markdown import (  # noqa: E402
    _classify_note_type,
    convert_img_tag_to_md_str,
    t_html_to_markdown,
)
from task07_onenote_to_markdown.utils.audit_log import (  # noqa: E402
    Environment,
    _now_utc,
    get_page_meta,
    log_api_call,
    log_llm_call,
    upsert_page_metadata,
)

# ── Shared helper ─────────────────────────────────────────────────────────────


class FakeResponse:
    def __init__(self, status_code=200, payload=None, headers=None, text="", content=b"", reason="OK"):
        self.status_code = status_code
        self._payload = payload or {}
        self.headers = headers or {}
        self.text = text
        self.content = content
        self.reason = reason

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise Exception(f"HTTP {self.status_code}")


# ═════════════════════════════════════════════════════════════════════════════
# 1. utils/audit_log.py
# ═════════════════════════════════════════════════════════════════════════════


class NowUtcTests(unittest.TestCase):
    def test_returns_datetime_instance(self):
        self.assertIsInstance(_now_utc(), datetime)

    def test_timezone_is_utc(self):
        self.assertEqual(_now_utc().tzinfo, timezone.utc)


class EnvironmentEnumTests(unittest.TestCase):
    def test_enum_values(self):
        self.assertEqual(Environment.LOCAL, "local")
        self.assertEqual(Environment.DEVELOPMENT, "dev")
        self.assertEqual(Environment.PRODUCTION, "prod")

    def test_invalid_value_raises_value_error(self):
        with self.assertRaises(ValueError):
            Environment("staging")


class LogApiCallTests(unittest.TestCase):
    @patch("task07_onenote_to_markdown.utils.audit_log._get_db")
    def test_writes_correct_fields_to_mongo(self, mock_get_db):
        mock_col = MagicMock()
        mock_get_db.return_value = {"onenote_graph_api_logs": mock_col}
        with patch.dict(os.environ, {"ENVIRONMENT": "local"}):
            log_api_call(
                page_id="p1",
                request_id="req-1",
                method="GET",
                api_endpoint="https://graph.microsoft.com/test",
                attempt_id=1,
                status="success",
                status_code=200,
                latency_ms=42,
                error_msg=None,
            )

        mock_col.insert_one.assert_called_once()
        doc = mock_col.insert_one.call_args[0][0]
        self.assertEqual(doc["page_id"], "p1")
        self.assertEqual(doc["status"], "success")
        self.assertEqual(doc["status_code"], 200)
        self.assertEqual(doc["method"], "GET")

    @patch("task07_onenote_to_markdown.utils.audit_log._get_db")
    def test_unknown_environment_raises_runtime_error(self, mock_get_db):
        with patch.dict(os.environ, {"ENVIRONMENT": "unknown"}):
            with self.assertRaises(RuntimeError):
                log_api_call(
                    page_id=None,
                    request_id="r",
                    method="GET",
                    api_endpoint="https://example.com",
                    attempt_id=1,
                    status="success",
                    status_code=200,
                    latency_ms=10,
                    error_msg=None,
                )

    @patch("task07_onenote_to_markdown.utils.audit_log._get_db")
    def test_mongo_write_failure_does_not_raise(self, mock_get_db):
        mock_col = MagicMock()
        mock_col.insert_one.side_effect = Exception("connection refused")
        mock_get_db.return_value = {"onenote_graph_api_logs": mock_col}
        with patch.dict(os.environ, {"ENVIRONMENT": "local"}):
            log_api_call(
                page_id=None,
                request_id="r",
                method="GET",
                api_endpoint="https://example.com",
                attempt_id=1,
                status="success",
                status_code=200,
                latency_ms=10,
                error_msg=None,
            )


class LogLlmCallTests(unittest.TestCase):
    @patch("task07_onenote_to_markdown.utils.audit_log._get_db")
    def test_writes_correct_fields_to_mongo(self, mock_get_db):
        mock_col = MagicMock()
        mock_get_db.return_value = {"gemini_llm_logs": mock_col}
        with patch.dict(os.environ, {"ENVIRONMENT": "local"}):
            log_llm_call(
                page_id="p2",
                model="gemini-2.5-flash-lite",
                html_path="/path/page.html",
                attempt_id=1,
                status="success",
                latency_ms=300,
                input_tokens=100,
                output_tokens=200,
                thinking_tokens=50,
                total_tokens=350,
                error_msg=None,
            )

        doc = mock_col.insert_one.call_args[0][0]
        self.assertEqual(doc["model"], "gemini-2.5-flash-lite")
        self.assertEqual(doc["total_tokens"], 350)
        self.assertIsNone(doc["error_msg"])

    @patch("task07_onenote_to_markdown.utils.audit_log._get_db")
    def test_mongo_write_failure_does_not_raise(self, mock_get_db):
        mock_col = MagicMock()
        mock_col.insert_one.side_effect = Exception("timeout")
        mock_get_db.return_value = {"gemini_llm_logs": mock_col}
        with patch.dict(os.environ, {"ENVIRONMENT": "local"}):
            log_llm_call(
                page_id=None,
                model="gemini-2.5-flash-lite",
                html_path="/path.html",
                attempt_id=1,
                status="failure",
                latency_ms=100,
                input_tokens=None,
                output_tokens=None,
                thinking_tokens=None,
                total_tokens=None,
                error_msg="timeout",
            )

    @patch("task07_onenote_to_markdown.utils.audit_log._get_db")
    def test_unknown_environment_raises_runtime_error(self, mock_get_db):
        with patch.dict(os.environ, {"ENVIRONMENT": "chaos"}):
            with self.assertRaises(RuntimeError):
                log_llm_call(
                    page_id=None,
                    model="m",
                    html_path="/p.html",
                    attempt_id=1,
                    status="success",
                    latency_ms=1,
                    input_tokens=0,
                    output_tokens=0,
                    thinking_tokens=0,
                    total_tokens=0,
                    error_msg=None,
                )


class GetPageMetaTests(unittest.TestCase):
    @patch("task07_onenote_to_markdown.utils.audit_log._get_db")
    def test_returns_dict_when_record_found(self, mock_get_db):
        mock_col = MagicMock()
        mock_col.find_one.return_value = {"page_id": "abc", "html_path": "/p.html"}
        mock_get_db.return_value = {"onenote_page_metadata": mock_col}
        result = get_page_meta("/p.html")
        self.assertIsInstance(result, dict)
        self.assertEqual(result["page_id"], "abc")

    @patch("task07_onenote_to_markdown.utils.audit_log._get_db")
    def test_returns_empty_dict_when_not_found(self, mock_get_db):
        mock_col = MagicMock()
        mock_col.find_one.return_value = None
        mock_get_db.return_value = {"onenote_page_metadata": mock_col}
        self.assertEqual(get_page_meta("/missing.html"), {})

    @patch("task07_onenote_to_markdown.utils.audit_log._get_db")
    def test_returns_empty_dict_on_db_error(self, mock_get_db):
        mock_get_db.side_effect = Exception("db error")
        self.assertEqual(get_page_meta("/any.html"), {})


class UpsertPageMetadataTests(unittest.TestCase):
    @patch("task07_onenote_to_markdown.utils.audit_log._get_db")
    def test_calls_update_one_with_set_fields(self, mock_get_db):
        mock_col = MagicMock()
        mock_get_db.return_value = {"onenote_page_metadata": mock_col}
        upsert_page_metadata(page_id="p1", set_fields={"status": "fetched"})
        mock_col.update_one.assert_called_once()
        filter_doc, update_doc = mock_col.update_one.call_args[0]
        self.assertEqual(filter_doc, {"page_id": "p1"})
        self.assertIn("$set", update_doc)
        self.assertEqual(update_doc["$set"], {"status": "fetched"})
        self.assertTrue(mock_col.update_one.call_args[1]["upsert"])

    @patch("task07_onenote_to_markdown.utils.audit_log._get_db")
    def test_includes_set_on_insert_when_provided(self, mock_get_db):
        mock_col = MagicMock()
        mock_get_db.return_value = {"onenote_page_metadata": mock_col}
        upsert_page_metadata(page_id="p2", set_fields={"status": "fetched"}, set_on_insert_fields={"md_path": None})
        _, update_doc = mock_col.update_one.call_args[0]
        self.assertIn("$setOnInsert", update_doc)
        self.assertEqual(update_doc["$setOnInsert"], {"md_path": None})

    @patch("task07_onenote_to_markdown.utils.audit_log._get_db")
    def test_no_set_on_insert_key_when_arg_is_none(self, mock_get_db):
        mock_col = MagicMock()
        mock_get_db.return_value = {"onenote_page_metadata": mock_col}
        upsert_page_metadata(page_id="p3", set_fields={"status": "ok"})
        _, update_doc = mock_col.update_one.call_args[0]
        self.assertNotIn("$setOnInsert", update_doc)

    @patch("task07_onenote_to_markdown.utils.audit_log._get_db")
    def test_mongo_failure_does_not_raise(self, mock_get_db):
        mock_col = MagicMock()
        mock_col.update_one.side_effect = Exception("write conflict")
        mock_get_db.return_value = {"onenote_page_metadata": mock_col}
        upsert_page_metadata(page_id="p4", set_fields={"status": "fetched"})


# ═════════════════════════════════════════════════════════════════════════════
# 2. e_onenote_download.py
# ═════════════════════════════════════════════════════════════════════════════


class SanitizeTests(unittest.TestCase):
    def test_removes_forbidden_chars(self):
        result = sanitize('file<>:"/\\|?*name')
        self.assertNotIn("<", result)
        self.assertNotIn(">", result)
        self.assertNotIn(":", result)
        self.assertNotIn('"', result)
        self.assertNotIn("\\", result)
        self.assertNotIn("|", result)
        self.assertNotIn("?", result)
        self.assertNotIn("*", result)

    def test_strips_surrounding_whitespace(self):
        self.assertEqual(sanitize("  hello  "), "hello")

    def test_empty_input_returns_untitled(self):
        self.assertEqual(sanitize(""), "Untitled")

    def test_all_forbidden_chars_replaced_with_underscores(self):
        self.assertEqual(sanitize("<>"), "__")

    def test_clean_name_unchanged(self):
        self.assertEqual(sanitize("My Notebook"), "My Notebook")

    def test_control_chars_replaced(self):
        result = sanitize("file\x00name\x1fname")
        self.assertNotIn("\x00", result)
        self.assertNotIn("\x1f", result)

    def test_returns_str(self):
        self.assertIsInstance(sanitize("name"), str)


class ParseOnenoteDtTests(unittest.TestCase):
    def test_empty_string_returns_none(self):
        self.assertIsNone(_parse_onenote_dt(""))

    def test_z_suffix_parsed_as_utc_datetime(self):
        result = _parse_onenote_dt("2024-03-15T10:30:00Z")
        self.assertIsInstance(result, datetime)
        self.assertEqual(result.year, 2024)
        self.assertEqual(result.month, 3)
        self.assertEqual(result.day, 15)

    def test_offset_string_parsed_correctly(self):
        result = _parse_onenote_dt("2024-03-15T10:30:00+08:00")
        self.assertIsInstance(result, datetime)

    def test_invalid_string_returns_none(self):
        self.assertIsNone(_parse_onenote_dt("not-a-date"))

    def test_returns_datetime_type_on_valid_input(self):
        result = _parse_onenote_dt("2024-01-01T00:00:00Z")
        self.assertIsInstance(result, datetime)


class RateLimiterTests(unittest.TestCase):
    def test_acquire_records_timestamps(self):
        limiter = RateLimiter(per_minute=10, per_hour=50)
        limiter.acquire()
        limiter.acquire()
        self.assertEqual(len(limiter._min_q), 2)
        self.assertEqual(len(limiter._hour_q), 2)

    def test_default_limits_set(self):
        limiter = RateLimiter()
        self.assertEqual(limiter.per_minute, 115)
        self.assertEqual(limiter.per_hour, 380)

    def test_custom_limits_respected(self):
        limiter = RateLimiter(per_minute=50, per_hour=200)
        self.assertEqual(limiter.per_minute, 50)
        self.assertEqual(limiter.per_hour, 200)


class ApiGetTests(unittest.TestCase):
    def _limiter(self):
        m = MagicMock()
        m.acquire = MagicMock()
        return m

    @patch("task07_onenote_to_markdown.e_onenote_download.log_api_call")
    @patch("task07_onenote_to_markdown.e_onenote_download.requests.get")
    def test_200_returns_response(self, mock_get, mock_log):
        mock_get.return_value = FakeResponse(status_code=200)
        result = api_get(
            "https://example.com", {"Authorization": "Bearer tok"}, self._limiter(), MagicMock(), MagicMock()
        )
        self.assertEqual(result.status_code, 200)

    @patch("task07_onenote_to_markdown.e_onenote_download.log_api_call")
    @patch("task07_onenote_to_markdown.e_onenote_download.time.sleep")
    @patch("task07_onenote_to_markdown.e_onenote_download.requests.get")
    def test_429_retries_then_succeeds(self, mock_get, mock_sleep, mock_log):
        mock_get.side_effect = [
            FakeResponse(status_code=429, headers={"Retry-After": "1"}, reason="Too Many Requests"),
            FakeResponse(status_code=200),
        ]
        result = api_get(
            "https://example.com", {"Authorization": "Bearer tok"}, self._limiter(), MagicMock(), MagicMock()
        )
        self.assertEqual(result.status_code, 200)
        mock_sleep.assert_called()

    @patch("task07_onenote_to_markdown.e_onenote_download.log_api_call")
    @patch("task07_onenote_to_markdown.e_onenote_download.time.sleep")
    @patch("task07_onenote_to_markdown.e_onenote_download.requests.get")
    def test_5xx_retries_then_succeeds(self, mock_get, mock_sleep, mock_log):
        mock_get.side_effect = [
            FakeResponse(status_code=503, reason="Service Unavailable"),
            FakeResponse(status_code=200),
        ]
        result = api_get(
            "https://example.com", {"Authorization": "Bearer tok"}, self._limiter(), MagicMock(), MagicMock()
        )
        self.assertEqual(result.status_code, 200)
        mock_sleep.assert_called()

    @patch("task07_onenote_to_markdown.e_onenote_download.log_api_call")
    @patch("task07_onenote_to_markdown.e_onenote_download.CACHE_PATH")
    @patch("task07_onenote_to_markdown.e_onenote_download.requests.get")
    def test_401_refreshes_token_and_retries(self, mock_get, mock_cache, mock_log):
        headers = {"Authorization": "Bearer old-token"}
        mock_get.side_effect = [
            FakeResponse(status_code=401, reason="Unauthorized"),
            FakeResponse(status_code=200),
        ]
        app = MagicMock()
        app.get_accounts.return_value = [MagicMock()]
        app.acquire_token_silent.return_value = {"access_token": "new-token"}
        cache = MagicMock()
        cache.serialize.return_value = "{}"
        result = api_get("https://example.com", headers, self._limiter(), app, cache)
        self.assertEqual(result.status_code, 200)
        self.assertIn("new-token", headers["Authorization"])

    @patch("task07_onenote_to_markdown.e_onenote_download.log_api_call")
    @patch("task07_onenote_to_markdown.e_onenote_download.time.sleep")
    @patch("task07_onenote_to_markdown.e_onenote_download.requests.get")
    def test_exhausted_retries_raises_runtime_error(self, mock_get, mock_sleep, mock_log):
        mock_get.return_value = FakeResponse(status_code=429, headers={"Retry-After": "0"}, reason="Too Many Requests")
        with self.assertRaises(RuntimeError):
            api_get("https://example.com", {"Authorization": "Bearer tok"}, self._limiter(), MagicMock(), MagicMock())
        self.assertEqual(mock_get.call_count, 10)

    @patch("task07_onenote_to_markdown.e_onenote_download.log_api_call")
    @patch("task07_onenote_to_markdown.e_onenote_download.CACHE_PATH")
    @patch("task07_onenote_to_markdown.e_onenote_download.requests.get")
    def test_401_token_refresh_failure_raises_runtime_error(self, mock_get, mock_cache, mock_log):
        mock_get.return_value = FakeResponse(status_code=401, reason="Unauthorized")
        app = MagicMock()
        app.get_accounts.return_value = [MagicMock()]
        app.acquire_token_silent.return_value = {}  # no access_token
        cache = MagicMock()
        cache.serialize.return_value = "{}"
        with self.assertRaises(RuntimeError):
            api_get("https://example.com", {"Authorization": "Bearer tok"}, self._limiter(), app, cache)


class GetAllTests(unittest.TestCase):
    @patch("task07_onenote_to_markdown.e_onenote_download.api_get")
    def test_single_page_returns_all_items(self, mock_api_get):
        mock_api_get.return_value = FakeResponse(payload={"value": [{"id": "1"}, {"id": "2"}]})
        result = get_all("https://example.com", {}, MagicMock(), MagicMock(), MagicMock())
        self.assertEqual(result, [{"id": "1"}, {"id": "2"}])

    @patch("task07_onenote_to_markdown.e_onenote_download.api_get")
    def test_follows_next_link_for_pagination(self, mock_api_get):
        mock_api_get.side_effect = [
            FakeResponse(payload={"value": [{"id": "1"}], "@odata.nextLink": "https://next.com"}),
            FakeResponse(payload={"value": [{"id": "2"}]}),
        ]
        result = get_all("https://example.com", {}, MagicMock(), MagicMock(), MagicMock())
        self.assertEqual(result, [{"id": "1"}, {"id": "2"}])
        self.assertEqual(mock_api_get.call_count, 2)

    @patch("task07_onenote_to_markdown.e_onenote_download.api_get")
    def test_empty_value_returns_empty_list(self, mock_api_get):
        mock_api_get.return_value = FakeResponse(payload={"value": []})
        result = get_all("https://example.com", {}, MagicMock(), MagicMock(), MagicMock())
        self.assertIsInstance(result, list)
        self.assertEqual(len(result), 0)


# ═════════════════════════════════════════════════════════════════════════════
# 3. t_html_to_markdown.py
# ═════════════════════════════════════════════════════════════════════════════


class ClassifyNoteTypeTests(unittest.TestCase):
    def test_yyyy_mm_dd_classified_as_daily_log(self):
        self.assertEqual(_classify_note_type("2024-03-15 회의록"), "daily_log")

    def test_yyyymmdd_classified_as_daily_log(self):
        self.assertEqual(_classify_note_type("20240315_standup"), "daily_log")

    def test_chinese_date_classified_as_daily_log(self):
        self.assertEqual(_classify_note_type("2024年3月15日記錄"), "daily_log")

    def test_no_date_classified_as_knowledge_summary(self):
        self.assertEqual(_classify_note_type("Python Async Basics"), "knowledge_summary")

    def test_partial_digit_string_is_knowledge_summary(self):
        self.assertEqual(_classify_note_type("chapter1overview"), "knowledge_summary")

    def test_returns_str_type(self):
        self.assertIsInstance(_classify_note_type("any-name"), str)


class ConvertImgTagTests(unittest.TestCase):
    def test_converts_img_tag_to_markdown_syntax(self):
        html = '<html><body><img src="_images/abc.png" alt="diagram"/></body></html>'
        result_text = str(convert_img_tag_to_md_str(html))
        self.assertIn("![diagram](_images/abc.png)", result_text)
        self.assertNotIn("<img", result_text)

    def test_img_without_alt_uses_image_as_default(self):
        html = '<html><body><img src="img.png"/></body></html>'
        result_text = str(convert_img_tag_to_md_str(html))
        self.assertIn("![image](img.png)", result_text)

    def test_html_without_images_unchanged(self):
        html = "<html><body><p>Hello world</p></body></html>"
        soup = convert_img_tag_to_md_str(html)
        self.assertEqual(len(soup.find_all("img")), 0)
        self.assertIn("Hello world", soup.get_text())

    def test_returns_beautifulsoup_instance(self):
        from bs4 import BeautifulSoup

        result = convert_img_tag_to_md_str("<html><body></body></html>")
        self.assertIsInstance(result, BeautifulSoup)

    def test_multiple_images_all_converted(self):
        html = '<html><body><img src="a.png" alt="A"/><img src="b.png" alt="B"/></body></html>'
        result_text = str(convert_img_tag_to_md_str(html))
        self.assertIn("![A](a.png)", result_text)
        self.assertIn("![B](b.png)", result_text)


class THtmlToMarkdownTests(unittest.TestCase):
    # t_html_to_markdown() now returns None and calls save_one_page() per page.
    # All assertions inspect save_one_page.call_args instead of a return value.

    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.export_dir = Path(self._tmpdir.name)

    def tearDown(self):
        self._tmpdir.cleanup()

    def _write_html(self, nb: str, section: str, stem: str = "my-note", content: str = "<p>test content</p>") -> Path:
        sec_dir = self.export_dir / nb / section
        sec_dir.mkdir(parents=True, exist_ok=True)
        html_path = sec_dir / f"{stem}.html"
        html_path.write_text(content, encoding="utf-8")
        return html_path

    # decorator order: bottom → top maps to first → last positional arg after self
    @patch("task07_onenote_to_markdown.t_html_to_markdown.save_one_page")
    @patch("task07_onenote_to_markdown.t_html_to_markdown._get_genai_client")
    @patch("task07_onenote_to_markdown.t_html_to_markdown.extract_llm_fields")
    @patch("task07_onenote_to_markdown.t_html_to_markdown.get_page_meta")
    @patch("task07_onenote_to_markdown.t_html_to_markdown.time.sleep")
    def test_returns_none(self, mock_sleep, mock_meta, mock_llm, mock_client, mock_save):
        mock_meta.return_value = {}
        mock_llm.return_value = {"tags": ["python"], "alias": "Test", "new_content": "# Test"}
        self._write_html("NB", "Sec")
        result = t_html_to_markdown(["NB"], self.export_dir)
        self.assertIsNone(result)

    @patch("task07_onenote_to_markdown.t_html_to_markdown.save_one_page")
    @patch("task07_onenote_to_markdown.t_html_to_markdown._get_genai_client")
    @patch("task07_onenote_to_markdown.t_html_to_markdown.extract_llm_fields")
    @patch("task07_onenote_to_markdown.t_html_to_markdown.get_page_meta")
    @patch("task07_onenote_to_markdown.t_html_to_markdown.time.sleep")
    def test_save_one_page_called_once_on_success(self, mock_sleep, mock_meta, mock_llm, mock_client, mock_save):
        mock_meta.return_value = {}
        mock_llm.return_value = {"tags": ["python"], "alias": "Test", "new_content": "# Test"}
        self._write_html("NB", "Sec")
        t_html_to_markdown(["NB"], self.export_dir)
        mock_save.assert_called_once()

    @patch("task07_onenote_to_markdown.t_html_to_markdown.save_one_page")
    @patch("task07_onenote_to_markdown.t_html_to_markdown._get_genai_client")
    @patch("task07_onenote_to_markdown.t_html_to_markdown.extract_llm_fields")
    @patch("task07_onenote_to_markdown.t_html_to_markdown.get_page_meta")
    @patch("task07_onenote_to_markdown.t_html_to_markdown.time.sleep")
    def test_page_dict_has_all_required_keys(self, mock_sleep, mock_meta, mock_llm, mock_client, mock_save):
        mock_meta.return_value = {"page_id": "pid-1"}
        mock_llm.return_value = {"tags": ["k1"], "alias": "Alias", "new_content": "body"}
        self._write_html("NB", "Sec", "page1")
        t_html_to_markdown(["NB"], self.export_dir)
        page = mock_save.call_args[0][0]
        required = {
            "session_id",
            "page_id",
            "notebook",
            "section",
            "page_title",
            "html_path",
            "md_path",
            "content",
            "note_type",
            "img_count",
            "page_status",
            "page_error",
            "export_dt",
        }
        self.assertTrue(required.issubset(page.keys()))

    @patch("task07_onenote_to_markdown.t_html_to_markdown.save_one_page")
    @patch("task07_onenote_to_markdown.t_html_to_markdown._get_genai_client")
    @patch("task07_onenote_to_markdown.t_html_to_markdown.extract_llm_fields")
    @patch("task07_onenote_to_markdown.t_html_to_markdown.get_page_meta")
    @patch("task07_onenote_to_markdown.t_html_to_markdown.time.sleep")
    def test_content_starts_with_yaml_frontmatter(self, mock_sleep, mock_meta, mock_llm, mock_client, mock_save):
        mock_meta.return_value = {}
        mock_llm.return_value = {"tags": [], "alias": "T", "new_content": "# Hello"}
        self._write_html("NB", "S", "note")
        t_html_to_markdown(["NB"], self.export_dir)
        content = mock_save.call_args[0][0]["content"]
        self.assertIsInstance(content, str)
        self.assertTrue(content.startswith("---\n"))
        self.assertIn("---\n\n", content)

    @patch("task07_onenote_to_markdown.t_html_to_markdown.save_one_page")
    @patch("task07_onenote_to_markdown.t_html_to_markdown._get_genai_client")
    @patch("task07_onenote_to_markdown.t_html_to_markdown.extract_llm_fields")
    @patch("task07_onenote_to_markdown.t_html_to_markdown.get_page_meta")
    @patch("task07_onenote_to_markdown.t_html_to_markdown.time.sleep")
    def test_html_path_and_md_path_are_path_objects(self, mock_sleep, mock_meta, mock_llm, mock_client, mock_save):
        mock_meta.return_value = {}
        mock_llm.return_value = {"tags": [], "alias": "X", "new_content": "y"}
        self._write_html("NB", "S", "page")
        t_html_to_markdown(["NB"], self.export_dir)
        page = mock_save.call_args[0][0]
        self.assertIsInstance(page["html_path"], Path)
        self.assertIsInstance(page["md_path"], Path)

    @patch("task07_onenote_to_markdown.t_html_to_markdown.save_one_page")
    @patch("task07_onenote_to_markdown.t_html_to_markdown._get_genai_client")
    @patch("task07_onenote_to_markdown.t_html_to_markdown.extract_llm_fields")
    @patch("task07_onenote_to_markdown.t_html_to_markdown.get_page_meta")
    @patch("task07_onenote_to_markdown.t_html_to_markdown.time.sleep")
    def test_img_count_is_int_and_correct(self, mock_sleep, mock_meta, mock_llm, mock_client, mock_save):
        mock_meta.return_value = {}
        mock_llm.return_value = {"tags": [], "alias": "X", "new_content": "y"}
        self._write_html("NB", "S", "page", content='<img src="_images/a.png"/><img src="_images/b.png"/>')
        t_html_to_markdown(["NB"], self.export_dir)
        page = mock_save.call_args[0][0]
        self.assertIsInstance(page["img_count"], int)
        self.assertEqual(page["img_count"], 2)

    @patch("task07_onenote_to_markdown.t_html_to_markdown.save_one_page")
    @patch("task07_onenote_to_markdown.t_html_to_markdown._get_genai_client")
    @patch("task07_onenote_to_markdown.t_html_to_markdown.extract_llm_fields")
    @patch("task07_onenote_to_markdown.t_html_to_markdown.get_page_meta")
    @patch("task07_onenote_to_markdown.t_html_to_markdown.time.sleep")
    def test_llm_exception_skips_save(self, mock_sleep, mock_meta, mock_llm, mock_client, mock_save):
        mock_meta.return_value = {}
        mock_llm.side_effect = Exception("Gemini unavailable")
        self._write_html("NB", "S", "note", content="<p>fallback</p>")
        t_html_to_markdown(["NB"], self.export_dir)
        mock_save.assert_not_called()

    @patch("task07_onenote_to_markdown.t_html_to_markdown.save_one_page")
    @patch("task07_onenote_to_markdown.t_html_to_markdown._get_genai_client")
    @patch("task07_onenote_to_markdown.t_html_to_markdown.extract_llm_fields")
    @patch("task07_onenote_to_markdown.t_html_to_markdown.get_page_meta")
    @patch("task07_onenote_to_markdown.t_html_to_markdown.time.sleep")
    def test_llm_returns_none_skips_save(self, mock_sleep, mock_meta, mock_llm, mock_client, mock_save):
        mock_meta.return_value = {}
        mock_llm.return_value = None  # None.get() → AttributeError → caught as exception
        self._write_html("NB", "S", "note")
        t_html_to_markdown(["NB"], self.export_dir)
        mock_save.assert_not_called()

    @patch("task07_onenote_to_markdown.t_html_to_markdown.save_one_page")
    @patch("task07_onenote_to_markdown.t_html_to_markdown._get_genai_client")
    def test_missing_notebook_dir_does_not_call_save(self, mock_client, mock_save):
        t_html_to_markdown(["NonExistentNotebook"], self.export_dir)
        mock_save.assert_not_called()

    @patch("task07_onenote_to_markdown.t_html_to_markdown.save_one_page")
    @patch("task07_onenote_to_markdown.t_html_to_markdown._get_genai_client")
    @patch("task07_onenote_to_markdown.t_html_to_markdown.extract_llm_fields")
    @patch("task07_onenote_to_markdown.t_html_to_markdown.get_page_meta")
    @patch("task07_onenote_to_markdown.t_html_to_markdown.time.sleep")
    def test_export_dt_is_utc_datetime(self, mock_sleep, mock_meta, mock_llm, mock_client, mock_save):
        mock_meta.return_value = {}
        mock_llm.return_value = {"tags": [], "alias": "T", "new_content": "body"}
        self._write_html("NB", "S", "note")
        t_html_to_markdown(["NB"], self.export_dir)
        page = mock_save.call_args[0][0]
        self.assertIsInstance(page["export_dt"], datetime)
        self.assertEqual(page["export_dt"].tzinfo, timezone.utc)


# ═════════════════════════════════════════════════════════════════════════════
# 4. l_save_markdown.py
# ═════════════════════════════════════════════════════════════════════════════


class LSaveMarkdownTests(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.base = Path(self._tmpdir.name)

    def tearDown(self):
        self._tmpdir.cleanup()

    def _make_page(
        self, stem: str = "note", page_id: str | None = "pid-1", status: str = "successed", error: str | None = None
    ) -> dict:
        sec_dir = self.base / "NB" / "Sec"
        sec_dir.mkdir(parents=True, exist_ok=True)
        html_path = sec_dir / f"{stem}.html"
        html_path.write_text("<p>html</p>", encoding="utf-8")
        return {
            "html_path": html_path,
            "md_path": html_path.with_suffix(".md"),
            "content": "---\ntags: []\n---\n\n# Body\n",
            "page_id": page_id,
            "note_type": "knowledge_summary",
            "export_dt": datetime.now(timezone.utc),
            "img_count": 0,
            "page_status": status,
            "page_error": error,
        }

    @patch("task07_onenote_to_markdown.l_save_markdown.upsert_page_metadata")
    def test_writes_md_file_to_disk(self, mock_upsert):
        page = self._make_page()
        l_save_markdown([page])
        self.assertTrue(page["md_path"].exists())
        self.assertEqual(page["md_path"].read_text(encoding="utf-8"), page["content"])

    @patch("task07_onenote_to_markdown.l_save_markdown.upsert_page_metadata")
    def test_calls_upsert_with_correct_page_id(self, mock_upsert):
        page = self._make_page(page_id="pid-42")
        l_save_markdown([page])
        mock_upsert.assert_called_once()
        self.assertEqual(mock_upsert.call_args.kwargs["page_id"], "pid-42")

    @patch("task07_onenote_to_markdown.l_save_markdown.upsert_page_metadata")
    def test_skips_upsert_when_page_id_is_none(self, mock_upsert):
        page = self._make_page(page_id=None)
        l_save_markdown([page])
        mock_upsert.assert_not_called()

    @patch("task07_onenote_to_markdown.l_save_markdown.upsert_page_metadata")
    def test_status_successed_maps_to_pending_review(self, mock_upsert):
        page = self._make_page(status="successed")
        l_save_markdown([page])
        set_fields = mock_upsert.call_args.kwargs["set_fields"]
        self.assertEqual(set_fields["status"], "pending_review")

    @patch("task07_onenote_to_markdown.l_save_markdown.upsert_page_metadata")
    def test_status_upstream_task_failed_maps_correctly(self, mock_upsert):
        page = self._make_page(status="upstream_task_failed", error="LLM error")
        l_save_markdown([page])
        set_fields = mock_upsert.call_args.kwargs["set_fields"]
        self.assertEqual(set_fields["status"], "summarized failed")

    @patch("task07_onenote_to_markdown.l_save_markdown.upsert_page_metadata")
    def test_write_failure_sets_save_failed_status(self, mock_upsert):
        page = self._make_page()
        page["md_path"] = self.base / "no_dir" / "note.md"  # parent dir doesn't exist
        l_save_markdown([page])
        set_fields = mock_upsert.call_args.kwargs["set_fields"]
        self.assertEqual(set_fields["status"], "saved failed")

    @patch("task07_onenote_to_markdown.l_save_markdown.upsert_page_metadata")
    def test_write_failure_does_not_raise(self, mock_upsert):
        page = self._make_page()
        page["md_path"] = self.base / "no_dir" / "note.md"
        l_save_markdown([page])  # must not raise

    @patch("task07_onenote_to_markdown.l_save_markdown.upsert_page_metadata")
    def test_empty_pages_does_not_raise(self, mock_upsert):
        l_save_markdown([])
        mock_upsert.assert_not_called()

    @patch("task07_onenote_to_markdown.l_save_markdown.upsert_page_metadata")
    def test_multiple_pages_all_processed(self, mock_upsert):
        pages = [self._make_page(stem=f"note-{i}") for i in range(3)]
        l_save_markdown(pages)
        self.assertEqual(mock_upsert.call_count, 3)
        for page in pages:
            self.assertTrue(page["md_path"].exists())

    @patch("task07_onenote_to_markdown.l_save_markdown.upsert_page_metadata")
    def test_upsert_receives_note_type_and_export_dt(self, mock_upsert):
        page = self._make_page()
        l_save_markdown([page])
        set_fields = mock_upsert.call_args.kwargs["set_fields"]
        self.assertEqual(set_fields["note_type"], "knowledge_summary")
        self.assertIsInstance(set_fields["md_exported_at"], datetime)


if __name__ == "__main__":
    unittest.main()
