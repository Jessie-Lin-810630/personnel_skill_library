"""tests/test_gold_service_endpoint.py

Unit tests for gold_service.app 的 /archive 端點與 l_archive_note 的 frontmatter 萃取 /
型別正規化。全部 mock，不連 GCS / MongoDB / Google 公鑰端點。
"""

import os
import unittest
from datetime import UTC, datetime, timedelta
from unittest.mock import patch

import jwt
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient

# ── Inject env vars BEFORE importing gold_service.app ─────────────────────────
os.environ.setdefault("ONENOTE_GCS_BUCKET", "fake-bucket")
os.environ.setdefault("ENVIRONMENT", "local")
# 這兩個一律覆寫而非 setdefault：其他測試可能已先觸發 load_dotenv 把本機真實設定載進環境，
# 用 setdefault 會變成空操作，測試就會改用真實允許清單，比對不到下面的假 email 而拿到 403。
os.environ["TOKEN_ISSUER_SA"] = "dashboard-sa@example.iam.gserviceaccount.com"
os.environ["USER_ALLOWLIST"] = '{"owner@example.com": "Note Owner"}'

from task07_common import auth  # noqa: E402
from task07_gold_service import app as gold_app  # noqa: E402
from task07_gold_service import l_archive_note as la  # noqa: E402

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


class TestArchiveEndpoint(unittest.TestCase):
    def setUp(self):
        auth._jwk_client = _FakeJWKClient(_PRIVATE_KEY.public_key())
        self.client = TestClient(gold_app.app, raise_server_exceptions=False)
        self.headers = {"X-User-Token": make_token()}

    def post(self, body, headers=None):
        return self.client.post("/archive", json=body, headers=self.headers if headers is None else headers)

    # ── 400 ──────────────────────────────────────────────────────────────────
    def test_missing_fields_returns_400(self):
        self.assertEqual(self.post({"page_id": "p1", "dt": "2026-07-01"}).status_code, 400)

    def test_invalid_action_returns_400(self):
        resp = self.post({"page_id": "p1", "dt": "2026-07-01", "action": "bogus"})
        self.assertEqual(resp.status_code, 400)

    # ── 401 / 403：身分驗證 ──────────────────────────────────────────────────
    def test_missing_token_returns_401(self):
        resp = self.post({"page_id": "p1", "dt": "2026-07-01", "action": "approved"}, headers={})
        self.assertEqual(resp.status_code, 401)

    def test_email_not_in_allowlist_returns_403(self):
        headers = {"X-User-Token": make_token(email="stranger@example.com")}
        resp = self.post({"page_id": "p1", "dt": "2026-07-01", "action": "approved"}, headers=headers)
        self.assertEqual(resp.status_code, 403)

    def test_missing_token_does_not_call_gold_load(self):
        with patch.object(gold_app, "archive_note") as m:
            self.post({"page_id": "p1", "dt": "2026-07-01", "action": "approved"}, headers={})
        m.assert_not_called()

    # ── approved 分支 ─────────────────────────────────────────────────────────
    def test_approved_success_returns_200(self):
        result = {"status": "archived", "md_archive_path": "gs://b/archived-notes/x.md", "img_archive_path": []}
        with patch.object(gold_app, "archive_note", return_value=result) as m:
            resp = self.post({"page_id": "p1", "dt": "2026-07-01", "action": "approved"})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["status"], "archived")
        # 角色取自 token 對照允許清單的結果，不是呼叫端指定的
        m.assert_called_once_with(page_id="p1", dt="2026-07-01", role="Note Owner")

    def test_role_in_body_is_ignored(self):
        result = {"status": "archived", "md_archive_path": "gs://b/x.md", "img_archive_path": []}
        with patch.object(gold_app, "archive_note", return_value=result) as m:
            resp = self.post({"page_id": "p1", "dt": "2026-07-01", "action": "approved", "role": "Fake Admin"})
        self.assertEqual(resp.status_code, 200)
        # body 帶的假角色被忽略，仍以 token 推導的角色寫入
        m.assert_called_once_with(page_id="p1", dt="2026-07-01", role="Note Owner")

    def test_approved_not_found_returns_404(self):
        with patch.object(gold_app, "archive_note", return_value={"status": "not_found", "error": "x"}):
            resp = self.post({"page_id": "p1", "dt": "2026-07-01", "action": "approved"})
        self.assertEqual(resp.status_code, 404)

    def test_approved_conflict_returns_409(self):
        with patch.object(gold_app, "archive_note", return_value={"status": "archived_conflict", "error": "dup"}):
            resp = self.post({"page_id": "p1", "dt": "2026-07-01", "action": "approved"})
        self.assertEqual(resp.status_code, 409)

    def test_approved_no_md_returns_422(self):
        with patch.object(gold_app, "archive_note", return_value={"status": "pending_review", "error": "no md"}):
            resp = self.post({"page_id": "p1", "dt": "2026-07-01", "action": "approved"})
        self.assertEqual(resp.status_code, 422)

    def test_validation_400_and_business_422_are_distinguishable(self):
        bad_field = self.post({"page_id": "p1", "dt": "2026-07-01", "action": "bogus"})
        with patch.object(gold_app, "archive_note", return_value={"status": "pending_review", "error": "no md"}):
            no_md = self.post({"page_id": "p1", "dt": "2026-07-01", "action": "approved"})
        self.assertEqual(bad_field.status_code, 400)
        self.assertEqual(no_md.status_code, 422)

    # ── rejected 分支（端點薄包 reject_note）────────────────────────────────
    def test_rejected_success_returns_200(self):
        result = {"status": "review_closed", "review_result": "rejected"}
        with patch.object(gold_app, "reject_note", return_value=result) as m:
            resp = self.post({"page_id": "p1", "dt": "2026-07-01", "action": "rejected"})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["review_result"], "rejected")
        m.assert_called_once_with(page_id="p1", dt="2026-07-01", role="Note Owner")

    def test_rejected_not_found_returns_404(self):
        with patch.object(gold_app, "reject_note", return_value={"status": "not_found", "error": "x"}):
            resp = self.post({"page_id": "p1", "dt": "2026-07-01", "action": "rejected"})
        self.assertEqual(resp.status_code, 404)


class TestFrontmatterExtraction(unittest.TestCase):
    def test_wellformed_frontmatter(self):
        md = (
            "---\n"
            "tags: [tubing-pump,蠕動幫浦,泵浦原理]\n"
            "date: 2026-07-01\n"
            "type: knowledge_summary\n"
            "alias: [蠕動幫浦原理與特性,tubing-pump-介紹]\n"
            "---\n\n# 內文\n本文。"
        )
        quality = la._build_md_quality_meta(md, None, "泵浦原理")
        fm = quality["md_frontmatter"]
        self.assertEqual(fm["tags"], ["tubing-pump", "蠕動幫浦", "泵浦原理"])
        self.assertIsInstance(fm["date"], datetime)
        self.assertEqual(fm["date"].year, 2026)
        self.assertEqual(fm["type"], "knowledge_summary")
        self.assertEqual(fm["alias"], ["蠕動幫浦原理與特性", "tubing-pump-介紹"])
        self.assertNotIn("valid_img", fm)  # valid_img 已移出 md_frontmatter，只存在 md_body
        # md_body / dismatched：無圖片連結 → 全 0
        self.assertEqual(quality["md_body"]["valid_img_count"], 0)
        self.assertGreater(quality["md_body"]["word_count"], 0)
        self.assertIsNone(quality["md_body"]["recomputed_at"])
        self.assertEqual(quality["dismatched_img_count"], 0)
        self.assertFalse(quality["md_has_dismatched_img"])

    def test_mispositioned_metadata(self):
        # frontmatter 漏寫進 metadata 區、落在正文頂端
        md = (
            "tags: [a,b,c]\ndate: 2026-06-15\ntype: daily_log\nalias: [x, y]\n\n# 真正標題\n內文 #inline-tag 不算標題。"
        )
        fm = la._build_md_quality_meta(md, None, "note")["md_frontmatter"]
        self.assertEqual(fm["tags"], ["a", "b", "c"])
        self.assertEqual(fm["type"], "daily_log")
        self.assertEqual(fm["alias"], ["x", "y"])
        self.assertIsInstance(fm["date"], datetime)


class TestValidImgCount(unittest.TestCase):
    def test_valid_img_counts_matches_by_basename(self):
        md = (
            "---\ntags: [a]\ndate: 2026-07-01\ntype: knowledge_summary\nalias: [x]\n---\n\n"
            "# 標題\n\n![圖一](_images/img_good1.png)\n\n"
            "![壞掉的替代文字](_images/img_typo.png)\n\n"
            "![圖三](_images/img_good2.png)\n"
        )
        img_archive_paths = [
            "gs://onenote-vaults/archived-notes/u/nb/sec/dt=2026-07-01/_images/img_good1.png",
            "gs://onenote-vaults/archived-notes/u/nb/sec/dt=2026-07-01/_images/img_good2.png",
        ]
        quality = la._build_md_quality_meta(md, img_archive_paths, "標題")
        # img_good1、img_good2 命中；img_typo 未落入 → valid_img_count=2、dismatched=1
        self.assertNotIn("valid_img", quality["md_frontmatter"])
        self.assertEqual(quality["md_body"]["valid_img_count"], 2)
        self.assertEqual(quality["dismatched_img_count"], 1)
        self.assertTrue(quality["md_has_dismatched_img"])

    def test_valid_img_zero_when_no_archive_paths(self):
        md = "# t\n\n![a](_images/x.png)\n"
        self.assertEqual(la._count_valid_images(md, []), 0)

    def test_count_valid_images_direct(self):
        content = "![a](_images/one.png)\n![b](_images/two.png)\n![c](_images/missing.png)"
        paths = ["gs://b/dt=x/_images/one.png", "gs://b/dt=x/_images/two.png"]
        self.assertEqual(la._count_valid_images(content, paths), 2)


class TestArchiveNoteGuard(unittest.TestCase):
    """archive_note 放寬把關後的早退分支（不觸及 GCS）。"""

    def test_not_found(self):
        with patch.object(la, "get_version_meta", return_value={}):
            r = la.archive_note("p1", "2026-06-01", "ML")
        self.assertEqual(r["status"], "not_found")

    def test_already_archived_idempotent(self):
        meta = {"status": "archived", "archived_md_path": "gs://b/x.md", "attached_images": []}
        with patch.object(la, "get_version_meta", return_value=meta):
            r = la.archive_note("p1", "2026-06-22", "ML")
        self.assertEqual(r["status"], "archived")
        self.assertEqual(r.get("note"), "already archived")

    def test_no_md_cannot_archive(self):
        with patch.object(la, "get_version_meta", return_value={"status": "bronze_stored", "enriched_md_path": None}):
            r = la.archive_note("p1", "2026-06-01", "ML")
        self.assertIn("無生成 md", r["error"])

    def test_conflict_older_than_latest_archived(self):
        # 本版 dt=06-01 早於已歸檔版本的歸檔日 06-22 → 不覆寫
        meta = {"status": "pending_review", "enriched_md_path": "gs://b/processed/x.md"}
        latest = {"dt": "2026-06-22", "archived_at": datetime(2026, 6, 22, 10, 0)}
        with (
            patch.object(la, "get_version_meta", return_value=meta),
            patch.object(la, "get_latest_archived_version", return_value=latest),
        ):
            r = la.archive_note("p1", "2026-06-01", "ML")
        self.assertEqual(r["status"], "archived_conflict")


class TestArchiveRetiresSiblings(unittest.TestCase):
    """archive_note 歸檔後，退役同頁其他 pending_review 版本（overwritten / rejected）。"""

    def test_siblings_retired_by_hash(self):
        meta = {
            "status": "pending_review",
            "enriched_md_path": "gs://b/processed-notes/dt=2026-06-22/n.md",
            "html_sha_hash": "H2",
            "onenote_user_id": "u1",
            "notebook": "nb",
            "section": "sec",
            "page_title": "n",
            "attached_images": [],
        }
        siblings = [
            {"page_id": "p1", "dt": "2026-06-08", "html_sha_hash": "H2"},  # 同 hash → overwritten
            {"page_id": "p1", "dt": "2026-06-15", "html_sha_hash": "H3"},  # 不同 hash → rejected
        ]
        with (
            patch.object(la, "get_version_meta", return_value=meta),
            patch.object(la, "get_latest_archived_version", return_value={}),
            patch.object(la.gcs, "archived_note_prefix", return_value="archived-notes/u1/nb/sec/dt=2026-06-22"),
            patch.object(la.gcs, "copy_blob", return_value="md5"),
            patch.object(la.gcs, "gs_uri", side_effect=lambda b: f"gs://b/{b}"),
            patch.object(la.gcs, "download_text", return_value="---\ntype: x\n---\n\nbody"),
            patch.object(la, "get_sibling_pending_versions", return_value=siblings),
            patch.object(la, "upsert_version_meta") as up,
        ):
            r = la.archive_note("p1", "2026-06-22", "ML")

        self.assertEqual(r["status"], "archived")
        # 收集所有退役兄弟版本的 upsert（status=review_closed）
        retired = {
            c.args[1]: c.kwargs["set_fields"]
            for c in up.call_args_list
            if c.kwargs["set_fields"].get("status") == "review_closed"
        }
        self.assertEqual(retired["2026-06-08"]["review_result"], "overwritten")
        self.assertEqual(retired["2026-06-15"]["review_result"], "rejected")
        # 退役版本不寫 reviewed_by_role（非逐一人工審閱）
        self.assertNotIn("reviewed_by_role", retired["2026-06-08"])
        self.assertNotIn("reviewed_by_role", retired["2026-06-15"])


class TestRejectNote(unittest.TestCase):
    """reject_note：翻 C3 + 背景寫 md_frontmatter，不寫 GCS。"""

    def test_reject_not_found(self):
        with patch.object(la, "get_version_meta", return_value={}):
            r = la.reject_note("p1", "2026-07-01", "ML")
        self.assertEqual(r["status"], "not_found")

    def test_reject_writes_review_closed_and_frontmatter(self):
        meta = {
            "enriched_md_path": "gs://b/processed/x.md",
            "page_title": "x",
            "attached_images": [{"raw_image_path": "gs://b/raw/dt=x/_images/a.png", "raw_image_md5": "m"}],
        }
        md_str = "---\ntags: [t]\ndate: 2026-07-01\ntype: daily_log\nalias: [x]\n---\n\n![i](_images/a.png)"
        with (
            patch.object(la, "get_version_meta", return_value=meta),
            patch.object(la.gcs, "download_text", return_value=md_str),
            patch.object(la, "upsert_version_meta") as up,
        ):
            r = la.reject_note("p1", "2026-07-01", "ML")
        self.assertEqual(r["review_result"], "rejected")
        # 兩次 upsert：狀態翻 review_closed + 寫品質欄位（md_frontmatter/md_body/dismatched/topic）
        self.assertEqual(up.call_count, 2)
        self.assertEqual(up.call_args_list[0].kwargs["set_fields"]["status"], "review_closed")
        quality = up.call_args_list[1].kwargs["set_fields"]
        self.assertEqual(quality["md_body"]["valid_img_count"], 1)  # a.png 命中 raw_image_path
        self.assertNotIn("valid_img", quality["md_frontmatter"])
        self.assertEqual(quality["dismatched_img_count"], 0)
        self.assertIn("topic", quality)
        self.assertIn("md_body", quality)

    def test_reject_without_md_skips_frontmatter(self):
        with (
            patch.object(la, "get_version_meta", return_value={"enriched_md_path": None}),
            patch.object(la, "upsert_version_meta") as up,
        ):
            r = la.reject_note("p1", "2026-07-01", "ML")
        self.assertEqual(r["review_result"], "rejected")
        up.assert_called_once()  # 只翻狀態、不寫 frontmatter


class TestNormalizers(unittest.TestCase):
    def test_normalize_str_list(self):
        self.assertEqual(la._normalize_str_list(["a", " b "]), ["a", "b"])
        self.assertEqual(la._normalize_str_list("a, b ,c"), ["a", "b", "c"])
        self.assertEqual(la._normalize_str_list(None), [])

    def test_normalize_date(self):
        from datetime import date

        self.assertIsInstance(la._normalize_date(date(2026, 7, 1)), datetime)
        self.assertIsInstance(la._normalize_date("2026-07-01"), datetime)
        self.assertIsInstance(la._normalize_date(datetime(2026, 7, 1)), datetime)
        self.assertIsNone(la._normalize_date("not-a-date"))
        self.assertIsNone(la._normalize_date(None))


if __name__ == "__main__":
    unittest.main()
