import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
# Option A：把 dashboard_ui/ 加進 path，讓模組的裸 import（utils）如 app 實際跑法般解析
sys.path.insert(0, str(PROJECT_ROOT / "dashboard_ui"))

from utils.interact_with_mongodb import get_onenote_attachment_dismatch

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


if __name__ == "__main__":
    unittest.main()
