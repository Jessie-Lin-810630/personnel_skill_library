import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from task01_obsidian_etl_v2 import e_scan_obsidian, l_load_to_mongodb, t_clean_obsidian


# --------------------------- Fakes ---------------------------
class FakeBlob:
    def __init__(self, name, md5_hash="MD5", updated=None, text=""):
        self.name = name
        self.md5_hash = md5_hash
        self.updated = updated
        self._text = text

    def download_as_text(self, encoding="utf-8"):
        return self._text

    def reload(self):
        pass


class FakeBucket:
    def __init__(self):
        self.copies = []

    def blob(self, name):
        return FakeBlob(name)

    def copy_blob(self, src, dest_bucket, new_name):
        self.copies.append((src.name, new_name))
        return FakeBlob(new_name, md5_hash="ARCH_" + Path(new_name).name)


class FakeCollection:
    def __init__(self, docs=None):
        self.docs = [dict(d) for d in (docs or [])]
        self.last_update_one = None

    def find(self, filter_doc=None, projection=None):
        return [dict(d) for d in self.docs]

    def update_one(self, filter_doc, update, upsert=False):
        self.last_update_one = (filter_doc, update, upsert)
        for d in self.docs:
            if all(d.get(k) == v for k, v in filter_doc.items()):
                d.update(update.get("$set", {}))
                return
        if upsert:
            new_doc = {**filter_doc, **update.get("$setOnInsert", {}), **update.get("$set", {})}
            self.docs.append(new_doc)

    def update_many(self, filter_doc, update):
        nin = filter_doc.get("raw_md_path", {}).get("$nin", [])
        ne_status = filter_doc.get("status", {}).get("$ne")
        count = 0
        for d in self.docs:
            if d.get("raw_md_path") in nin:
                continue
            if ne_status is not None and d.get("status") == ne_status:
                continue
            d.update(update.get("$set", {}))
            count += 1
        return SimpleNamespace(modified_count=count)


class FakeDb:
    def __init__(self):
        self.collections = {}

    def __getitem__(self, name):
        self.collections.setdefault(name, FakeCollection())
        return self.collections[name]

    def preset(self, name, docs):
        self.collections[name] = FakeCollection(docs)


# --------------------------- Extract / path helpers ---------------------------
class PathHelperTests(unittest.TestCase):
    def test_blob_name_from_uri_strips_bucket_prefix(self):
        uri = "gs://personal-vaults/raw-notes/u/nb/01-d/x.md"
        self.assertEqual(
            l_load_to_mongodb.blob_name_from_uri(uri, "personal-vaults"),
            "raw-notes/u/nb/01-d/x.md",
        )

    def test_parse_note_path_splits_user_notebook_section_file(self):
        parsed = e_scan_obsidian.parse_note_path("raw-notes/lucky460721/data-engineering/01-daily-logs/x.md")
        self.assertEqual(parsed["note_user_id"], "lucky460721")
        self.assertEqual(parsed["notebook"], "data-engineering")
        self.assertEqual(parsed["section"], "01-daily-logs")
        self.assertEqual(parsed["file_name"], "x.md")


# --------------------------- Task 3.5: CDC gate ---------------------------
class SelectChangedBlobsTests(unittest.TestCase):
    def test_only_new_and_changed_blobs_selected(self):
        bucket = "personal-vaults"
        same = FakeBlob("raw-notes/u/nb/01-d/same.md", md5_hash="S")
        changed = FakeBlob("raw-notes/u/nb/01-d/changed.md", md5_hash="NEW")
        new = FakeBlob("raw-notes/u/nb/01-d/new.md", md5_hash="N")
        existing = {
            f"gs://{bucket}/{same.name}": {"md_md5": "S", "images": {}},  # 未變更 → 略過
            f"gs://{bucket}/{changed.name}": {"md_md5": "OLD", "images": {}},  # md5 異 → 納入
        }

        result = e_scan_obsidian.select_changed_blobs([same, changed, new], existing, {}, bucket)

        self.assertEqual({b.name for b in result}, {changed.name, new.name})

    def test_note_included_when_referenced_image_md5_changed(self):
        # .md 本身 md5 未變，但它 wiki-link 指向的圖片 md5 變了 → 仍要納入 changed
        bucket = "personal-vaults"
        note = FakeBlob("raw-notes/u/nb/01-d/note.md", md5_hash="SAME")
        img_path = "raw-notes/u/nb/01-d/_attachment/a.png"
        existing = {
            f"gs://{bucket}/{note.name}": {"md_md5": "SAME", "images": {img_path: "IMG_OLD"}},
        }
        image_index = {img_path: "IMG_NEW"}  # GCS 現況圖片 md5 已變

        result = e_scan_obsidian.select_changed_blobs([note], existing, image_index, bucket)

        self.assertEqual({b.name for b in result}, {note.name})

    def test_note_included_when_referenced_image_deleted(self):
        # .md 未變，但引用圖片在 GCS 已消失（image_index 查不到）→ 仍納入以刷新血緣
        bucket = "personal-vaults"
        note = FakeBlob("raw-notes/u/nb/01-d/note.md", md5_hash="SAME")
        img_path = "raw-notes/u/nb/01-d/_attachment/a.png"
        existing = {
            f"gs://{bucket}/{note.name}": {"md_md5": "SAME", "images": {img_path: "IMG_OLD"}},
        }

        result = e_scan_obsidian.select_changed_blobs([note], existing, {}, bucket)

        self.assertEqual({b.name for b in result}, {note.name})

    def test_note_skipped_when_md_and_images_unchanged(self):
        bucket = "personal-vaults"
        note = FakeBlob("raw-notes/u/nb/01-d/note.md", md5_hash="SAME")
        img_path = "raw-notes/u/nb/01-d/_attachment/a.png"
        existing = {
            f"gs://{bucket}/{note.name}": {"md_md5": "SAME", "images": {img_path: "IMG"}},
        }
        image_index = {img_path: "IMG"}  # 圖片 md5 也相同

        result = e_scan_obsidian.select_changed_blobs([note], existing, image_index, bucket)

        self.assertEqual(result, [])


# --------------------------- Task 4.4: cleaning + image lineage ---------------------------
class BuildNoteDocumentTests(unittest.TestCase):
    def test_cleans_metadata_and_extracts_raw_image_lineage(self):
        blob = FakeBlob("raw-notes/u/nb/01-daily/note.md", md5_hash="RAWMD5", updated="2026-07-06")
        text = "---\ntype: daily\ntags: python, sql\ndate: 2026-07-06\n---\n本文 ![[a.png]] 內容\n"
        image_index = {"raw-notes/u/nb/01-daily/_attachment/a.png": "IMG_A"}

        doc = t_clean_obsidian.build_note_document(blob, text, "personal-vaults", image_index)

        self.assertEqual(doc["raw_md_path"], "gs://personal-vaults/raw-notes/u/nb/01-daily/note.md")
        self.assertEqual(doc["raw_md_md5_hash"], "RAWMD5")
        self.assertEqual(doc["note_user_id"], "u")
        self.assertEqual(doc["section"], "01-daily")
        self.assertEqual(doc["topic"], "python")
        self.assertEqual(doc["archived_md_frontmatter"]["type"], "daily-log")
        self.assertEqual(doc["archived_md_frontmatter"]["date"], datetime(2026, 7, 6, tzinfo=timezone.utc))
        self.assertEqual(
            doc["attached_images"],
            [{"raw_image_path": "raw-notes/u/nb/01-daily/_attachment/a.png", "raw_image_md5": "IMG_A"}],
        )

    def test_missing_image_in_index_is_skipped(self):
        blob = FakeBlob("raw-notes/u/nb/01-daily/note.md")
        text = "---\ntype: daily\n---\n![[gone.png]]\n"
        doc = t_clean_obsidian.build_note_document(blob, text, "personal-vaults", {})
        self.assertEqual(doc["attached_images"], [])


# --------------------------- Task 5.x: archive + upsert ---------------------------
class ArchiveNoteTests(unittest.TestCase):
    def test_copies_md_and_images_and_fills_archived_fields(self):
        bucket = FakeBucket()
        note_doc = {
            "raw_md_path": "gs://personal-vaults/raw-notes/u/nb/01-d/x.md",
            "attached_images": [{"raw_image_path": "raw-notes/u/nb/01-d/_attachment/a.png", "raw_image_md5": "A"}],
        }

        out = l_load_to_mongodb.archive_note(note_doc, bucket, "personal-vaults")

        self.assertEqual(out["archived_md_path"], "gs://personal-vaults/archived-notes/u/nb/01-d/x.md")
        self.assertEqual(out["archived_md_md5_hash"], "ARCH_x.md")
        img = out["attached_images"][0]
        self.assertEqual(img["archived_image_path"], "gs://personal-vaults/archived-notes/u/nb/01-d/_attachment/a.png")
        self.assertEqual(img["archived_image_md5"], "ARCH_a.png")
        self.assertEqual(len(bucket.copies), 2)
        self.assertEqual(out["error_msg"], "")

    def test_copy_exception_sets_error_msg_and_reraises(self):
        class BoomBucket:
            def blob(self, name):
                return FakeBlob(name)

            def copy_blob(self, src, dest_bucket, new_name):
                raise RuntimeError("boom")

        note_doc = {"raw_md_path": "gs://personal-vaults/raw-notes/u/nb/01-d/x.md", "attached_images": []}

        with self.assertRaises(RuntimeError):
            l_load_to_mongodb.archive_note(note_doc, BoomBucket(), "personal-vaults")

        self.assertIn("boom", note_doc["error_msg"])


class UpsertNoteTests(unittest.TestCase):
    def test_upsert_keyed_on_raw_md_path_with_setoninsert(self):
        db = FakeDb()
        note_doc = {"raw_md_path": "gs://b/raw-notes/u/x.md", "topic": "python"}

        l_load_to_mongodb.upsert_note(db, note_doc)

        col = db.collections[l_load_to_mongodb.NOTE_METADATA]
        filter_doc, update, upsert = col.last_update_one
        self.assertEqual(filter_doc, {"raw_md_path": "gs://b/raw-notes/u/x.md"})
        self.assertEqual(update["$set"]["status"], "archived")
        self.assertIs(update["$setOnInsert"]["embedded_status"], False)
        self.assertTrue(upsert)

    def test_upsert_is_idempotent_on_same_raw_md_path(self):
        db = FakeDb()
        note_doc = {"raw_md_path": "gs://b/raw-notes/u/x.md", "topic": "python"}
        l_load_to_mongodb.upsert_note(db, note_doc)
        l_load_to_mongodb.upsert_note(db, {**note_doc, "topic": "database"})
        col = db.collections[l_load_to_mongodb.NOTE_METADATA]
        self.assertEqual(len(col.docs), 1)
        self.assertEqual(col.docs[0]["topic"], "database")


class MarkNoteErrorTests(unittest.TestCase):
    def test_upserts_status_error_with_message(self):
        db = FakeDb()

        l_load_to_mongodb.mark_note_error(db, "gs://b/raw-notes/u/x.md", "boom")

        col = db.collections[l_load_to_mongodb.NOTE_METADATA]
        filter_doc, update, upsert = col.last_update_one
        self.assertEqual(filter_doc, {"raw_md_path": "gs://b/raw-notes/u/x.md"})
        self.assertEqual(update["$set"]["status"], "error")
        self.assertEqual(update["$set"]["error_msg"], "boom")
        self.assertIs(update["$setOnInsert"]["embedded_status"], False)
        self.assertTrue(upsert)


# --------------------------- Task 6.3: soft delete ---------------------------
class SoftDeleteTests(unittest.TestCase):
    def _db_with_notes(self):
        db = FakeDb()
        db.preset(
            l_load_to_mongodb.NOTE_METADATA,
            [
                {"raw_md_path": "gs://b/raw-notes/u/keep.md", "status": "archived"},
                {"raw_md_path": "gs://b/raw-notes/u/gone.md", "status": "archived"},
            ],
        )
        return db

    def test_missing_note_is_marked_deleted_and_present_untouched(self):
        db = self._db_with_notes()
        present = {"gs://b/raw-notes/u/keep.md"}

        n = l_load_to_mongodb.soft_delete_missing(db, present)

        docs = {d["raw_md_path"]: d for d in db.collections[l_load_to_mongodb.NOTE_METADATA].docs}
        self.assertEqual(n, 1)
        self.assertEqual(docs["gs://b/raw-notes/u/gone.md"]["status"], "deleted")
        self.assertEqual(docs["gs://b/raw-notes/u/keep.md"]["status"], "archived")

    def test_rerun_is_idempotent(self):
        db = self._db_with_notes()
        present = {"gs://b/raw-notes/u/keep.md"}
        l_load_to_mongodb.soft_delete_missing(db, present)
        n_again = l_load_to_mongodb.soft_delete_missing(db, present)
        self.assertEqual(n_again, 0)


# --------------------------- Task 7.2: gold snapshot ---------------------------
class SummaryTests(unittest.TestCase):
    def test_snapshot_counts_exclude_deleted_and_overwrite_same_day(self):
        db = FakeDb()
        db.preset(
            l_load_to_mongodb.NOTE_METADATA,
            [
                {
                    "status": "archived",
                    "topic": "python",
                    "embedded_status": True,
                    "archived_md_frontmatter": {"type": "daily-log"},
                },
                {
                    "status": "archived",
                    "topic": "database",
                    "embedded_status": False,
                    "archived_md_frontmatter": {"type": "project"},
                },
                {
                    "status": "deleted",
                    "topic": "python",
                    "embedded_status": True,
                    "archived_md_frontmatter": {"type": "daily-log"},
                },
                {
                    "status": "error",
                    "topic": "ml",
                    "embedded_status": False,
                    "archived_md_frontmatter": {"type": "unknown"},
                },
            ],
        )

        summary = l_load_to_mongodb.build_and_upsert_summary(db)
        self.assertEqual(summary["total_notes"], 2)  # deleted / error 不計
        self.assertEqual(summary["embedded_notes"], 1)
        self.assertEqual(summary["by_type"], {"daily-log": 1, "project": 1})
        self.assertEqual(summary["by_topic"], {"python": 1, "database": 1})

        l_load_to_mongodb.build_and_upsert_summary(db)  # 同日重跑
        self.assertEqual(len(db.collections[l_load_to_mongodb.NOTES_SUMMARY].docs), 1)


if __name__ == "__main__":
    unittest.main()
