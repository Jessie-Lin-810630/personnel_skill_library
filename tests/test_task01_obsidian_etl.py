import os
import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import frontmatter

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


class ResolveImagePathTests(unittest.TestCase):
    def test_strips_size_alias_and_keeps_basename_under_note_dir(self):
        # ![[img.png|492]] 的尺寸/別名要被去掉，圖片掛在「該 .md 所在目錄」的 _attachment/
        self.assertEqual(
            e_scan_obsidian.resolve_image_blob_path("img.png|492", "u/from-obsidian/01-daily/x.md"),
            "u/from-obsidian/01-daily/_attachment/img.png",
        )

    def test_ref_with_subpath_uses_basename_only(self):
        # ref 帶子路徑時只取檔名，避免把 ref 的路徑誤拼進 blob path
        self.assertEqual(
            e_scan_obsidian.resolve_image_blob_path("sub/img.png", "u/01-daily/x.md"),
            "u/01-daily/_attachment/img.png",
        )

    def test_alias_with_surrounding_spaces_is_trimmed(self):
        self.assertEqual(
            e_scan_obsidian.resolve_image_blob_path("img.png | 300 ", "u/01-daily/x.md"),
            "u/01-daily/_attachment/img.png",
        )


class ExtractAttachedImagesTests(unittest.TestCase):
    def test_dedups_same_image_keeps_order_and_attaches_md5(self):
        # ![[a.png|300]] 與 ![[a.png]] 解析到同一 blob → 去重；出現順序保留
        index = {
            "u/01-daily/_attachment/a.png": "MD5A",
            "u/01-daily/_attachment/b.png": "MD5B",
        }
        body = "![[b.png]] 文字 ![[a.png|300]] 再來 ![[a.png]]"

        result = e_scan_obsidian.extract_attached_images(body, "u/01-daily/note.md", index)

        self.assertEqual(
            result,
            [
                {"image_path": "u/01-daily/_attachment/b.png", "image_md5_hash": "MD5B"},
                {"image_path": "u/01-daily/_attachment/a.png", "image_md5_hash": "MD5A"},
            ],
        )

    def test_image_missing_in_index_is_skipped(self):
        # GCS 找不到的圖片 (已刪 / 非 _attachment 結構) 不記血緣
        body = "![[gone.png]]"
        self.assertEqual(
            e_scan_obsidian.extract_attached_images(body, "u/01-daily/note.md", {}),
            [],
        )

    def test_body_without_images_returns_empty_list(self):
        self.assertEqual(
            e_scan_obsidian.extract_attached_images("純文字沒有圖片", "u/01-daily/note.md", {}),
            [],
        )


class InferDateTests(unittest.TestCase):
    def test_valid_iso_date_parses(self):
        self.assertEqual(e_scan_obsidian._infer_date("2026-06-27"), datetime(2026, 6, 27))

    def test_empty_or_none_returns_none(self):
        self.assertIsNone(e_scan_obsidian._infer_date(""))
        self.assertIsNone(e_scan_obsidian._infer_date(None))

    def test_none_stringified_returns_none(self):
        # scan_vault_gs 以 str(fm.get("date")) 餵入，date 缺值時會傳 "None" 字串
        self.assertIsNone(e_scan_obsidian._infer_date("None"))

    def test_non_iso_formats_return_none(self):
        self.assertIsNone(e_scan_obsidian._infer_date("2026/06/27"))
        # 帶時間的字串不符合 %Y-%m-%d，回 None (見下方 misposition 髒資料的關聯)
        self.assertIsNone(e_scan_obsidian._infer_date("2026-06-27 10:30"))


class InferMispositionMetadataTests(unittest.TestCase):
    """_infer_misposition_metadata：frontmatter 漏寫進正文時的補救解析 (髒資料來源)。"""

    @staticmethod
    def _post(content: str) -> frontmatter.Post:
        return frontmatter.Post(content)

    def test_parses_tags_date_alias_from_body(self):
        post = self._post("tags: [python, sql]\ndate: 2026-06-27\nalias: [foo, bar]\n")

        fm = e_scan_obsidian._infer_misposition_metadata(post)

        self.assertEqual(fm["tags"], "python, sql")
        self.assertEqual(fm["date"], "2026-06-27")
        self.assertEqual(fm["alias"], ["foo", "bar"])

    def test_full_width_colon_is_supported(self):
        post = self._post("tags：python\ndate：2026-06-27\n")

        fm = e_scan_obsidian._infer_misposition_metadata(post)

        self.assertEqual(fm["tags"], "python")
        self.assertEqual(fm["date"], "2026-06-27")

    def test_empty_body_returns_defaults(self):
        fm = e_scan_obsidian._infer_misposition_metadata(self._post(""))
        self.assertEqual(fm, {"tags": "", "date": "", "alias": []})

    def test_value_containing_colon_should_not_crash(self):
        # 髒資料 Bug A（已修）：value 內含冒號 (如時間 "10:30"、URL) 原本會讓
        # feature.split(":") 拋 ValueError: too many values to unpack，使該筆記在
        # scan_vault_gs 的 try/except 中被「靜默丟棄」。已改 split(":", 1) 只切第一個冒號。
        post = self._post("date: 2026-06-27 10:30\n")
        fm = e_scan_obsidian._infer_misposition_metadata(post)
        self.assertEqual(fm["date"], "2026-06-27 10:30")

    def test_inline_hash_tags_should_not_be_truncated(self):
        # 髒資料 Bug B（已修）：原本 content.split("#")[0] 會在第一個 '#' 處截斷，
        # Obsidian 行內標籤 (tags: #python) 連同後面的 date 一起被切掉。已改為逐行掃描、
        # 只在真正的 Markdown 標題行 (行首 '# ') 才停，行內標籤不再誤截。
        post = self._post("tags: #python #sql\ndate: 2026-06-27\n")
        fm = e_scan_obsidian._infer_misposition_metadata(post)
        self.assertTrue(fm["tags"])
        self.assertEqual(fm["date"], "2026-06-27")


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
