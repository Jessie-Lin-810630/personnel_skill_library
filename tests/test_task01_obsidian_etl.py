import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parents[1]
TASK_DIR = PROJECT_ROOT / "task01_obsidian_etl"
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(TASK_DIR))

from task01_obsidian_etl import e_scan_obsidian, l_load_to_mongodb, main, t_clean_obsidian


class ScanObsidianTests(unittest.TestCase):
    def test_infer_note_type_prefers_frontmatter_type(self):
        md_path = Path("/vault/04_project/example.md")

        self.assertEqual(
            e_scan_obsidian._infer_note_type(md_path, {"type": "Daily Log"}),
            "daily-log",
        )
        self.assertEqual(
            e_scan_obsidian._infer_note_type(md_path, {"type": "Knowledge Base"}),
            "knowledge-summary",
        )
        self.assertEqual(
            e_scan_obsidian._infer_note_type(md_path, {"type": "Project"}),
            "project",
        )

    def test_infer_note_type_falls_back_to_folder_prefix(self):
        self.assertEqual(
            e_scan_obsidian._infer_note_type(Path("/vault/02_notes/python.md"), {}),
            "knowledge-summary",
        )
        self.assertEqual(
            e_scan_obsidian._infer_note_type(Path("/vault/99_misc/random.md"), {}),
            "unknown",
        )

    def test_infer_topic_uses_tags_before_filename_and_returns_other(self):
        self.assertEqual(
            e_scan_obsidian._infer_topic(["mongodb", "python"], "docker-notes"),
            "python",
        )
        self.assertEqual(
            e_scan_obsidian._infer_topic(["misc"], "docker-compose-guide"),
            "dockerize",
        )
        self.assertEqual(e_scan_obsidian._infer_topic(["misc"], "journal"), "other")

    def test_scan_vault_reads_supported_folders_and_normalizes_metadata(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            vault = Path(tmp_dir)
            included = vault / "01_daily"
            included.mkdir()
            ignored = vault / "03_ignore"
            ignored.mkdir()

            (included / "daily.md").write_text(
                "---\n"
                "type: daily\n"
                "tags: python, pandas\n"
                "alias: Today\n"
                "date: 2026-04-23\n"
                "---\n"
                "hello world from obsidian\n",
                encoding="utf-8",
            )
            (ignored / "ignored.md").write_text(
                "---\ntags: [mongodb]\n---\nshould not be scanned\n",
                encoding="utf-8",
            )

            results = e_scan_obsidian.scan_vault(str(vault))

        self.assertEqual(len(results), 1)
        note = results[0]
        self.assertEqual(note["file_name"], "daily.md")
        self.assertEqual(note["note_type"], "daily-log")
        self.assertEqual(note["tags"], ["python", "pandas"])
        self.assertEqual(note["alias"], "Today")
        self.assertEqual(note["date"], "2026-04-23")
        self.assertEqual(note["topic"], "python")
        self.assertEqual(note["word_count"], 4)

    def test_scan_vault_raises_when_path_does_not_exist(self):
        with self.assertRaises(FileNotFoundError):
            e_scan_obsidian.scan_vault("/path/that/does/not/exist")


class CleanObsidianTests(unittest.TestCase):
    def test_build_note_documents_is_passthrough(self):
        # 時間戳改由 load 層的 CDC 狀態機決定 (created_at 只在 insert、updated_at 只在變更)，
        # 故 build_note_documents 不再注入 created_at，只做 passthrough。
        raw_notes = [{"file_path": "a.md"}, {"file_path": "b.md"}]

        notes = t_clean_obsidian.build_note_documents(raw_notes)

        self.assertIs(notes, raw_notes)
        self.assertNotIn("created_at", notes[0])

    def test_build_summary_document_counts_notes_by_type_and_topic(self):
        raw_notes = [
            {"note_type": "daily-log", "topic": "python"},
            {"note_type": "daily-log", "topic": "python"},
            {"note_type": "project", "topic": "database"},
        ]

        summary = t_clean_obsidian.build_summary_document(raw_notes)

        self.assertEqual(summary["total_notes"], 3)
        self.assertRegex(summary["snapshot_date"], r"^\d{4}-\d{2}-\d{2}$")
        self.assertEqual(summary["by_type"], {"daily-log": 2, "project": 1})
        self.assertEqual(summary["by_topic"], {"python": 2, "database": 1})


class FakeCollection:
    def __init__(self):
        self.bulk_operations = None
        self.update_filter = None
        self.update_doc = None
        self.update_upsert = None
        # sync_notes 用：find 預設回傳的現況 docs、被刪除的 filter
        self.preset_find_docs = []
        self.deleted_filter = None

    def bulk_write(self, operations, ordered=True):
        self.bulk_operations = operations
        return SimpleNamespace(upserted_count=1, modified_count=2)

    def find(self, filter_doc=None, projection=None):
        return list(self.preset_find_docs)

    def delete_many(self, filter_doc):
        self.deleted_filter = filter_doc
        in_list = filter_doc.get("file_path", {}).get("$in", [])
        return SimpleNamespace(deleted_count=len(in_list))

    def update_one(self, filter_doc, update_doc, upsert=False):
        self.update_filter = filter_doc
        self.update_doc = update_doc
        self.update_upsert = upsert


class FakeDb:
    def __init__(self):
        self.collections = {}

    def __getitem__(self, collection_name):
        self.collections.setdefault(collection_name, FakeCollection())
        return self.collections[collection_name]


class LoadToMongoDbTests(unittest.TestCase):
    def test_get_db_returns_named_database_from_client(self):
        fake_client = {"skill_library": object()}

        with patch.object(l_load_to_mongodb, "MongoClient", return_value=fake_client) as mongo:
            db = l_load_to_mongodb.get_db("mongodb://localhost:27017", "skill_library")

        mongo.assert_called_once_with("mongodb://localhost:27017")
        self.assertIs(db, fake_client["skill_library"])

    def test_sync_notes_inserts_updates_skips_and_deletes(self):
        from pymongo import InsertOne, UpdateOne

        db = FakeDb()
        notes_col = db["obsidian_notes"]
        # DB 現況：changed.md (md5 將不同)、same.md (md5 相同)、gone.md (GCS 已不存在)
        notes_col.preset_find_docs = [
            {"file_path": "changed.md", "file_md5_hash": "OLD", "attached_images": []},
            {"file_path": "same.md", "file_md5_hash": "SAME", "attached_images": []},
            {"file_path": "gone.md", "file_md5_hash": "X", "attached_images": []},
        ]
        # GCS 掃描結果：new.md (新增)、changed.md (md5 變)、same.md (未變)
        notes = [
            {"file_path": "new.md", "file_md5_hash": "N", "attached_images": []},
            {"file_path": "changed.md", "file_md5_hash": "NEW", "attached_images": []},
            {"file_path": "same.md", "file_md5_hash": "SAME", "attached_images": []},
        ]

        l_load_to_mongodb.sync_notes(db, notes)

        ops = notes_col.bulk_operations
        inserts = [o for o in ops if isinstance(o, InsertOne)]
        updates = [o for o in ops if isinstance(o, UpdateOne)]
        self.assertEqual(len(inserts), 1)  # new.md → insert
        self.assertEqual(len(updates), 1)  # changed.md → update (same.md 未變，不產生 op)
        # gone.md → delete_many
        self.assertEqual(notes_col.deleted_filter, {"file_path": {"$in": ["gone.md"]}})

    def test_sync_notes_changed_image_md5_triggers_update(self):
        from pymongo import UpdateOne

        db = FakeDb()
        notes_col = db["obsidian_notes"]
        # .md md5 相同，但圖片 md5 變了 (換圖、檔名不變) → 應視為變更
        notes_col.preset_find_docs = [
            {
                "file_path": "n.md",
                "file_md5_hash": "SAME",
                "attached_images": [{"image_path": "n/_attachment/x.png", "image_md5_hash": "IMG_OLD"}],
            },
        ]
        notes = [
            {
                "file_path": "n.md",
                "file_md5_hash": "SAME",
                "attached_images": [{"image_path": "n/_attachment/x.png", "image_md5_hash": "IMG_NEW"}],
            },
        ]

        l_load_to_mongodb.sync_notes(db, notes)

        updates = [o for o in notes_col.bulk_operations if isinstance(o, UpdateOne)]
        self.assertEqual(len(updates), 1)

    def test_upsert_summary_uses_snapshot_date_as_unique_key(self):
        db = FakeDb()
        summary = {"snapshot_date": "2026-04-23", "total_notes": 2}

        l_load_to_mongodb.upsert_note_summary(db, summary)

        collection = db.collections["obsidian_summary"]
        self.assertEqual(collection.update_filter, {"snapshot_date": "2026-04-23"})
        self.assertEqual(collection.update_doc, {"$set": summary})
        self.assertTrue(collection.update_upsert)


class MainRunTests(unittest.TestCase):
    def test_run_executes_extract_transform_load_steps(self):
        raw_notes = [{"file_path": "01_daily/a.md", "note_type": "daily-log", "topic": "python"}]
        cleaned_notes = [{"file_path": "01_daily/a.md"}]
        summary = {"snapshot_date": "2026-04-23", "total_notes": 1}
        db = object()

        with (
            patch.dict(
                os.environ,
                {
                    "MONGO_ALTAS_URI": "mongodb://localhost:27017",
                    "MONGO_DB_NAME": "skill_library",
                },
                clear=False,
            ),
            patch.object(main, "scan_vault_gs", return_value=raw_notes) as scan_vault_gs,
            patch.object(main, "build_note_documents", return_value=cleaned_notes) as build_notes,
            patch.object(main, "build_summary_document", return_value=summary) as build_summary,
            patch.object(main, "get_db", return_value=db) as get_db,
            patch.object(main, "sync_notes") as sync_notes,
            patch.object(main, "upsert_note_summary") as upsert_summary,
        ):
            main.run_task01()

        scan_vault_gs.assert_called_once_with("personal-vaults")
        build_notes.assert_called_once_with(raw_notes)
        build_summary.assert_called_once_with(raw_notes)
        get_db.assert_called_once_with("mongodb://localhost:27017", "skill_library")
        sync_notes.assert_called_once_with(db, cleaned_notes)
        upsert_summary.assert_called_once_with(db, summary)

    def test_run_raises_when_required_env_vars_are_missing(self):
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(EnvironmentError):
                main.run_task01()


if __name__ == "__main__":
    unittest.main()
