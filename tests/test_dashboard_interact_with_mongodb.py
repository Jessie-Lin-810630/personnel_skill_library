import os
import sys
import time
import unittest
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

PROJECT_ROOT = Path(__file__).resolve().parents[1]
# Option A：把 dashboard_ui/ 加進 path，讓模組的裸 import（utils）如 app 實際跑法般解析
sys.path.insert(0, str(PROJECT_ROOT / "dashboard_ui"))

from utils.interact_with_mongodb import get_onenote_attachment_dismatch, to_tpe_time_text

# ── helpers ──────────────────────────────────────────────────────────────────


class _FakeAggCollection:
    """記錄 aggregate() 收到的 pipeline，並回傳預設 docs 的假 collection。"""

    def __init__(self, docs=None):
        self._docs = list(docs or [])
        self.pipeline = None

    def aggregate(self, pipeline):
        self.pipeline = pipeline
        return iter(self._docs)


class _FakeDB:
    """記錄被索引的 collection 名稱的假 DB。"""

    def __init__(self, collection):
        self._collection = collection
        self.accessed_name = None

    def __getitem__(self, name):
        self.accessed_name = name
        return self._collection


# ── OnenoteAttachmentDismatchTests ────────────────────────────────────────────


class OnenoteAttachmentDismatchTests(unittest.TestCase):
    def _run(self, docs=None, collection=None):
        coll = _FakeAggCollection(docs=docs)
        db = _FakeDB(coll)
        kwargs = {"collection": collection} if collection else {}
        result = get_onenote_attachment_dismatch(db, **kwargs)
        return result, coll, db

    def test_defaults_to_onenote_note_metadata_collection(self):
        _, _, db = self._run()
        self.assertEqual(db.accessed_name, "onenote_note_metadata")

    def test_custom_collection_name_is_honored(self):
        _, _, db = self._run(collection="onenote_note_metadata_staging")
        self.assertEqual(db.accessed_name, "onenote_note_metadata_staging")

    def test_match_stage_filters_archived_and_rejected_only(self):
        _, coll, _ = self._run()
        self.assertEqual(
            coll.pipeline[0],
            {"$match": {"status": {"$in": ["archived", "rejected"]}}},
        )

    def test_group_stage_keys_on_status_and_embedded_status(self):
        _, coll, _ = self._run()
        group = coll.pipeline[1]["$group"]
        self.assertEqual(group["_id"], {"status": "$status", "embedded_status": "$embedded_status"})

    def test_group_stage_counts_dismatched_and_pushes_counts(self):
        _, coll, _ = self._run()
        group = coll.pipeline[1]["$group"]
        self.assertEqual(
            group["md_cnt_has_dismatched_img"],
            {"$sum": {"$cond": ["$md_has_dismatched", 1, 0]}},
        )
        self.assertEqual(group["dismatched_img_count"], {"$push": "$dismatched_img_count"})

    def test_project_stage_drops_id_and_lifts_group_fields(self):
        _, coll, _ = self._run()
        project = coll.pipeline[2]["$project"]
        self.assertEqual(project["_id"], 0)
        self.assertEqual(project["status"], "$_id.status")
        self.assertEqual(project["embedded_status"], "$_id.embedded_status")
        self.assertEqual(project["md_cnt_has_dismatched_img"], 1)
        self.assertEqual(project["dismatched_img_count"], 1)

    def test_pipeline_has_exactly_three_stages(self):
        _, coll, _ = self._run()
        self.assertEqual(len(coll.pipeline), 3)

    def test_aggregate_result_is_returned_as_list(self):
        docs = [
            {
                "status": "archived",
                "embedded_status": False,
                "md_cnt_has_dismatched_img": 2,
                "dismatched_img_count": [1, 0, 2],
            },
            {
                "status": "rejected",
                "embedded_status": False,
                "md_cnt_has_dismatched_img": 0,
                "dismatched_img_count": [0],
            },
        ]
        result, _, _ = self._run(docs=docs)
        self.assertIsInstance(result, list)
        self.assertEqual(result, docs)

    def test_empty_aggregate_result_returns_empty_list(self):
        result, _, _ = self._run(docs=[])
        self.assertEqual(result, [])


# ── ToTpeTimeTextTests ────────────────────────────────────────────────────────


class ToTpeTimeTextTests(unittest.TestCase):
    """驗證時區換算：UTC 02:30 一律顯示為台北 10:30，且不因執行機器的系統時區而改變。"""

    def setUp(self):
        # 刻意把系統時區設成非 UTC，模擬本地開發機；naive 值若未補 UTC 就會換算錯誤
        self._saved_tz = os.environ.get("TZ")
        os.environ["TZ"] = "America/New_York"
        time.tzset()
        self.addCleanup(self._restore_tz)

    def _restore_tz(self):
        if self._saved_tz is None:
            os.environ.pop("TZ", None)
        else:
            os.environ["TZ"] = self._saved_tz
        time.tzset()

    def test_naive_datetime_is_read_as_utc(self):
        self.assertEqual(to_tpe_time_text(datetime(2026, 8, 19, 2, 30, 5)), "2026-08-19 10:30:05")

    def test_aware_utc_datetime_is_converted(self):
        aware = datetime(2026, 8, 19, 2, 30, 5, tzinfo=timezone.utc)
        self.assertEqual(to_tpe_time_text(aware), "2026-08-19 10:30:05")

    def test_aware_non_utc_datetime_is_converted_by_its_own_offset(self):
        aware = datetime(2026, 8, 19, 4, 30, 5, tzinfo=ZoneInfo("Asia/Tokyo"))
        self.assertEqual(to_tpe_time_text(aware), "2026-08-19 03:30:05")

    def test_iso_string_without_offset_is_read_as_utc(self):
        self.assertEqual(to_tpe_time_text("2026-08-19T02:30:05"), "2026-08-19 10:30:05")

    def test_iso_string_with_offset_is_converted(self):
        self.assertEqual(to_tpe_time_text("2026-08-19T02:30:05+00:00"), "2026-08-19 10:30:05")

    def test_microseconds_are_truncated_to_seconds(self):
        self.assertEqual(to_tpe_time_text(datetime(2026, 8, 19, 2, 30, 5, 123456)), "2026-08-19 10:30:05")

    def test_unparsable_string_is_returned_as_is(self):
        self.assertEqual(to_tpe_time_text("N/A"), "N/A")

    def test_long_unparsable_string_is_truncated_to_19_chars(self):
        self.assertEqual(to_tpe_time_text("x" * 30), "x" * 19)

    def test_empty_string_returns_empty_string(self):
        self.assertEqual(to_tpe_time_text(""), "")

    def test_none_returns_its_text_form(self):
        self.assertEqual(to_tpe_time_text(None), "None")


if __name__ == "__main__":
    unittest.main()
