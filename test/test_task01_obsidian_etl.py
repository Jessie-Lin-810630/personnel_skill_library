from task01_obsidian_etl import main
from task01_obsidian_etl import t_clean_obsidian
from task01_obsidian_etl import l_load_to_mongodb
from task01_obsidian_etl import e_scan_obsidian
import os
import sys
import tempfile
import unittest
from datetime import timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


PROJECT_ROOT = Path(__file__).resolve().parents[1]
TASK_DIR = PROJECT_ROOT / "task01_obsidian_etl"
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(TASK_DIR))


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
    def test_build_note_documents_adds_utc_created_at(self):
        raw_notes = [{"file_path": "a.md"}, {"file_path": "b.md"}]

        notes = t_clean_obsidian.build_note_documents(raw_notes)

        self.assertIs(notes, raw_notes)
        self.assertIn("created_at", notes[0])
        self.assertEqual(notes[0]["created_at"], notes[1]["created_at"])
        self.assertEqual(notes[0]["created_at"].tzinfo, timezone.utc)

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

    def bulk_write(self, operations):
        self.bulk_operations = operations
        return SimpleNamespace(upserted_count=1, modified_count=2)

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


class FakeUpdateOne:
    def __init__(self, filter_doc, update_doc, upsert=False):
        self.filter_doc = filter_doc
        self.update_doc = update_doc
        self.upsert = upsert


class LoadToMongoDbTests(unittest.TestCase):
    def test_get_db_returns_named_database_from_client(self):
        fake_client = {"skill_library": object()}

        with patch.object(l_load_to_mongodb, "MongoClient", return_value=fake_client) as mongo:
            db = l_load_to_mongodb.get_db("mongodb://localhost:27017", "skill_library")

        mongo.assert_called_once_with("mongodb://localhost:27017")
        self.assertIs(db, fake_client["skill_library"])

    def test_upsert_notes_builds_bulk_operations_by_file_path(self):
        db = FakeDb()
        notes = [
            {"file_path": "/vault/a.md", "topic": "python"},
            {"file_path": "/vault/b.md", "topic": "database"},
        ]

        with patch.object(l_load_to_mongodb, "UpdateOne", FakeUpdateOne):
            l_load_to_mongodb.upsert_notes(db, notes)

        collection = db.collections["obsidian_notes"]
        self.assertEqual(len(collection.bulk_operations), 2)
        self.assertEqual(collection.bulk_operations[0].filter_doc, {"file_path": "/vault/a.md"})
        self.assertEqual(collection.bulk_operations[0].update_doc, {"$set": notes[0]})
        self.assertTrue(collection.bulk_operations[0].upsert)

    def test_upsert_summary_uses_snapshot_date_as_unique_key(self):
        db = FakeDb()
        summary = {"snapshot_date": "2026-04-23", "total_notes": 2}

        l_load_to_mongodb.upsert_summary(db, summary)

        collection = db.collections["obsidian_summary"]
        self.assertEqual(collection.update_filter, {"snapshot_date": "2026-04-23"})
        self.assertEqual(collection.update_doc, {"$set": summary})
        self.assertTrue(collection.update_upsert)


class MainRunTests(unittest.TestCase):
    def test_run_executes_extract_transform_load_steps(self):
        raw_notes = [{"file_path": "/vault/a.md", "note_type": "daily-log", "topic": "python"}]
        cleaned_notes = [{"file_path": "/vault/a.md", "created_at": object()}]
        summary = {"snapshot_date": "2026-04-23", "total_notes": 1}
        db = object()

        with patch.dict(
            os.environ,
            {
                "OBSIDIAN_VAULT_PATH": "/vault",
                "MONGO_URI": "mongodb://localhost:27017",
                "MONGO_DB_NAME": "skill_library",
            },
            clear=False,
        ), patch.object(main, "scan_vault", return_value=raw_notes) as scan_vault, patch.object(
            main, "build_note_documents", return_value=cleaned_notes
        ) as build_notes, patch.object(
            main, "build_summary_document", return_value=summary
        ) as build_summary, patch.object(
            main, "get_db", return_value=db
        ) as get_db, patch.object(
            main, "upsert_notes"
        ) as upsert_notes, patch.object(
            main, "upsert_summary"
        ) as upsert_summary:
            main.run()

        scan_vault.assert_called_once_with("/vault")
        build_notes.assert_called_once_with(raw_notes)
        build_summary.assert_called_once_with(raw_notes)
        get_db.assert_called_once_with("mongodb://localhost:27017", "skill_library")
        upsert_notes.assert_called_once_with(db, cleaned_notes)
        upsert_summary.assert_called_once_with(db, summary)

    def test_run_raises_when_required_env_vars_are_missing(self):
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(EnvironmentError):
                main.run()


if __name__ == "__main__":
    unittest.main()
