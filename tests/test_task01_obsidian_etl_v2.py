import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import frontmatter

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from task01_obsidian_etl_v2.gold_notes_metadata_snapshot import l_upsert_summary_to_mongodb, t_build_summary
from task01_obsidian_etl_v2.silver_transform_markdown import (
    e_get_changed_files,
    l_archive_markdown,
    l_upsert_metadata_to_mongodb,
    t_build_metadata_docs,
)


# --------------------------- Fakes ---------------------------
class FakeBlob:
    def __init__(self, name, md5_hash="MD5", updated=None, text="", bucket=None):
        self.name = name
        self.md5_hash = md5_hash
        self.updated = updated
        self._text = text
        self._bucket = bucket

    def download_as_text(self, encoding="utf-8"):
        return self._text

    def upload_from_string(self, data, content_type=None):
        if self._bucket is not None:
            self._bucket.uploads[self.name] = data
        self.md5_hash = "ARCH_" + Path(self.name).name

    def reload(self):
        pass


class FakeBucket:
    def __init__(self, texts=None):
        self.copies = []
        self.uploads = {}  # dest_name -> 上傳的字串內容
        self._texts = texts or {}  # src_name -> raw .md 內文

    def blob(self, name):
        return FakeBlob(name, text=self._texts.get(name, ""), bucket=self)

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
            l_archive_markdown.blob_name_from_uri(uri, "personal-vaults"),
            "raw-notes/u/nb/01-d/x.md",
        )

    def test_parse_note_path_splits_user_notebook_section_file(self):
        parsed = t_build_metadata_docs._parse_note_path("raw-notes/lucky460721/data-engineering/01-daily-logs/x.md")
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

        result = e_get_changed_files.select_changed_blobs([same, changed, new], existing, {}, bucket)

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

        result = e_get_changed_files.select_changed_blobs([note], existing, image_index, bucket)

        self.assertEqual({b.name for b in result}, {note.name})

    def test_note_included_when_referenced_image_deleted(self):
        # .md 未變，但引用圖片在 GCS 已消失（image_index 查不到）→ 仍納入以刷新血緣
        bucket = "personal-vaults"
        note = FakeBlob("raw-notes/u/nb/01-d/note.md", md5_hash="SAME")
        img_path = "raw-notes/u/nb/01-d/_attachment/a.png"
        existing = {
            f"gs://{bucket}/{note.name}": {"md_md5": "SAME", "images": {img_path: "IMG_OLD"}},
        }

        result = e_get_changed_files.select_changed_blobs([note], existing, {}, bucket)

        self.assertEqual({b.name for b in result}, {note.name})

    def test_note_skipped_when_md_and_images_unchanged(self):
        bucket = "personal-vaults"
        note = FakeBlob("raw-notes/u/nb/01-d/note.md", md5_hash="SAME")
        img_path = "raw-notes/u/nb/01-d/_attachment/a.png"
        existing = {
            f"gs://{bucket}/{note.name}": {"md_md5": "SAME", "images": {img_path: "IMG"}},
        }
        image_index = {img_path: "IMG"}  # 圖片 md5 也相同

        result = e_get_changed_files.select_changed_blobs([note], existing, image_index, bucket)

        self.assertEqual(result, [])


# --------------------------- Task 4.4: cleaning + image lineage ---------------------------
class BuildNoteDocumentTests(unittest.TestCase):
    def test_cleans_metadata_and_extracts_raw_image_lineage(self):
        blob = FakeBlob("raw-notes/u/nb/01-daily/note.md", md5_hash="RAWMD5", updated="2026-07-06")
        text = "---\ntype: daily\ntags: python, sql\ndate: 2026-07-06\n---\n本文 ![[a.png]] 內容\n"
        image_index = {"raw-notes/u/nb/01-daily/_attachment/a.png": "IMG_A"}

        doc = t_build_metadata_docs.build_note_document(blob, text, "personal-vaults", image_index)

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
        doc = t_build_metadata_docs.build_note_document(blob, text, "personal-vaults", {})
        self.assertEqual(doc["attached_images"], [])


# --------------------------- Task 5.x: archive + upsert ---------------------------
class ArchiveNoteTests(unittest.TestCase):
    def test_uploads_md_copies_images_and_fills_archived_fields(self):
        # md 走 _upload_clean_md（upload_from_string），圖片走 copy_blob
        bucket = FakeBucket()
        note_doc = {
            "raw_md_path": "gs://personal-vaults/raw-notes/u/nb/01-d/x.md",
            "archived_md_frontmatter": {"tags": ["python"], "type": "daily-log", "date": None, "alias": []},
            "attached_images": [{"raw_image_path": "raw-notes/u/nb/01-d/_attachment/a.png", "raw_image_md5": "A"}],
        }

        out = l_archive_markdown.archive_note(note_doc, bucket, "personal-vaults")

        self.assertEqual(out["archived_md_path"], "gs://personal-vaults/archived-notes/u/nb/01-d/x.md")
        self.assertEqual(out["archived_md_md5_hash"], "ARCH_x.md")
        img = out["attached_images"][0]
        self.assertEqual(img["archived_image_path"], "gs://personal-vaults/archived-notes/u/nb/01-d/_attachment/a.png")
        self.assertEqual(img["archived_image_md5"], "ARCH_a.png")
        self.assertEqual(len(bucket.uploads), 1)  # md 上傳一次
        self.assertEqual(len(bucket.copies), 1)  # 圖片複製一次
        self.assertEqual(out["error_msg"], "")

    def test_upload_exception_sets_error_msg_and_reraises(self):
        class BoomBlob:
            name = "x.md"

            def download_as_text(self, encoding="utf-8"):
                return "---\ntype: daily\n---\n本文\n"

            def upload_from_string(self, data, content_type=None):
                raise RuntimeError("boom")

        class BoomBucket:
            def blob(self, name):
                return BoomBlob()

        note_doc = {
            "raw_md_path": "gs://personal-vaults/raw-notes/u/nb/01-d/x.md",
            "archived_md_frontmatter": {"type": "daily-log"},
            "attached_images": [],
        }

        with self.assertRaises(RuntimeError):
            l_archive_markdown.archive_note(note_doc, BoomBucket(), "personal-vaults")

        self.assertIn("boom", note_doc["error_msg"])


class DeleteMispositionMetadataTests(unittest.TestCase):
    def test_strips_leading_keyvalue_block_before_first_heading(self):
        # 正文頂端誤植的 frontmatter 區塊在第一個真標題前，應被清掉
        post = frontmatter.Post(content="tags: python, sql\ndate: 2026-07-06\n# 真標題\n本文內容\n")

        l_archive_markdown._delete_misposition_metadata(post)

        self.assertNotIn("tags: python, sql", post.content)
        self.assertNotIn("date: 2026-07-06", post.content)
        self.assertIn("# 真標題", post.content)
        self.assertIn("本文內容", post.content)

    def test_content_starting_with_heading_is_untouched(self):
        # 正文直接以真標題開頭（無錯位 frontmatter）時內容不動
        original = "# 標題\n內文有 tags: 這個字\n"
        post = frontmatter.Post(content=original)

        l_archive_markdown._delete_misposition_metadata(post)

        self.assertEqual(post.content, original)


class UploadCleanMdTests(unittest.TestCase):
    def test_overwrites_frontmatter_and_strips_misposition_block(self):
        # 誤植情境：無正規 --- 區塊，frontmatter 直接漏進正文頂端
        raw = "tags: python, sql\ndate: 2026-07-06\n# 真標題\n本文內容\n"
        bucket = FakeBucket(texts={"raw-notes/u/x.md": raw})
        clean_fm = {"tags": ["python"], "type": "daily-log", "date": None, "alias": []}

        md5 = l_archive_markdown._upload_clean_md(bucket, "raw-notes/u/x.md", "archived-notes/u/x.md", clean_fm)

        uploaded = frontmatter.loads(bucket.uploads["archived-notes/u/x.md"])
        # 乾淨 frontmatter 已覆寫進 metadata
        self.assertEqual(uploaded["type"], "daily-log")
        self.assertEqual(uploaded["tags"], ["python"])
        # 錯位 frontmatter 已從正文刪除，不與乾淨版本並存
        self.assertNotIn("tags: python, sql", uploaded.content)
        self.assertNotIn("date: 2026-07-06", uploaded.content)
        # 真正內容保留
        self.assertIn("# 真標題", uploaded.content)
        self.assertIn("本文內容", uploaded.content)
        self.assertEqual(md5, "ARCH_x.md")


class UpsertNoteTests(unittest.TestCase):
    def test_upsert_keyed_on_raw_md_path_with_setoninsert(self):
        db = FakeDb()
        note_doc = {"raw_md_path": "gs://b/raw-notes/u/x.md", "topic": "python"}

        l_upsert_metadata_to_mongodb.upsert_note(db, note_doc)

        col = db.collections[l_upsert_metadata_to_mongodb.NOTE_METADATA]
        filter_doc, update, upsert = col.last_update_one
        self.assertEqual(filter_doc, {"raw_md_path": "gs://b/raw-notes/u/x.md"})
        self.assertEqual(update["$set"]["status"], "archived")
        self.assertIs(update["$setOnInsert"]["embedded_status"], False)
        self.assertTrue(upsert)

    def test_upsert_is_idempotent_on_same_raw_md_path(self):
        db = FakeDb()
        note_doc = {"raw_md_path": "gs://b/raw-notes/u/x.md", "topic": "python"}
        l_upsert_metadata_to_mongodb.upsert_note(db, note_doc)
        l_upsert_metadata_to_mongodb.upsert_note(db, {**note_doc, "topic": "database"})
        col = db.collections[l_upsert_metadata_to_mongodb.NOTE_METADATA]
        self.assertEqual(len(col.docs), 1)
        self.assertEqual(col.docs[0]["topic"], "database")


class MarkNoteErrorTests(unittest.TestCase):
    def test_upserts_status_error_with_message(self):
        db = FakeDb()

        l_upsert_metadata_to_mongodb.mark_note_error(db, "gs://b/raw-notes/u/x.md", "boom")

        col = db.collections[l_upsert_metadata_to_mongodb.NOTE_METADATA]
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
            l_upsert_metadata_to_mongodb.NOTE_METADATA,
            [
                {"raw_md_path": "gs://b/raw-notes/u/keep.md", "status": "archived"},
                {"raw_md_path": "gs://b/raw-notes/u/gone.md", "status": "archived"},
            ],
        )
        return db

    def test_missing_note_is_marked_deleted_and_present_untouched(self):
        db = self._db_with_notes()
        present = {"gs://b/raw-notes/u/keep.md"}

        n = l_upsert_metadata_to_mongodb.soft_delete_missing(db, present)

        docs = {d["raw_md_path"]: d for d in db.collections[l_upsert_metadata_to_mongodb.NOTE_METADATA].docs}
        self.assertEqual(n, 1)
        self.assertEqual(docs["gs://b/raw-notes/u/gone.md"]["status"], "deleted")
        self.assertEqual(docs["gs://b/raw-notes/u/keep.md"]["status"], "archived")

    def test_rerun_is_idempotent(self):
        db = self._db_with_notes()
        present = {"gs://b/raw-notes/u/keep.md"}
        l_upsert_metadata_to_mongodb.soft_delete_missing(db, present)
        n_again = l_upsert_metadata_to_mongodb.soft_delete_missing(db, present)
        self.assertEqual(n_again, 0)

    def test_empty_present_set_skips_and_does_not_mass_delete(self):
        # 防呆：present 為空（上游掃描異常）時不得把全表標 deleted
        db = self._db_with_notes()
        n = l_upsert_metadata_to_mongodb.soft_delete_missing(db, set())
        self.assertEqual(n, 0)
        for d in db.collections[l_upsert_metadata_to_mongodb.NOTE_METADATA].docs:
            self.assertEqual(d["status"], "archived")


# --------------------------- 空值 / None 邊界 ---------------------------
class EmptyInputTests(unittest.TestCase):
    def test_select_changed_blobs_all_empty(self):
        self.assertEqual(e_get_changed_files.select_changed_blobs([], {}, {}, "personal-vaults"), [])

    def test_build_note_document_empty_text(self):
        blob = FakeBlob("raw-notes/u/nb/01-d/x.md", md5_hash="M")
        doc = t_build_metadata_docs.build_note_document(blob, "", "personal-vaults", {})
        self.assertEqual(doc["word_count"], 0)
        self.assertEqual(doc["attached_images"], [])

    def test_build_summary_empty_collection(self):
        db = FakeDb()
        summary = t_build_summary.build_summary(db, "obsidian_note_metadata")
        self.assertEqual(summary["snapshot_source"], "obsidian_note_metadata")
        s = summary["summary"]
        self.assertEqual(s["archived_notes"], 0)
        self.assertEqual(s["rejected_notes"], 0)
        self.assertEqual(s["embedded_notes"], 0)
        self.assertEqual(dict(s["by_type_in_archived_notes"]), {})
        self.assertEqual(dict(s["by_topic_in_archived_notes"]), {})
        self.assertEqual(dict(s["by_tag_in_rejected_notes"]), {})

        # upsert 空快照仍應寫入一筆全零的 notes_summary
        l_upsert_summary_to_mongodb.upsert_summary(db, [summary])
        docs = db.collections[l_upsert_summary_to_mongodb.NOTES_SUMMARY].docs
        self.assertEqual(len(docs), 1)
        self.assertEqual(docs[0]["total_notes"], 0)


# --------------------------- Task 7.2: gold snapshot ---------------------------
class SummaryTests(unittest.TestCase):
    def test_snapshot_counts_exclude_deleted_and_overwrite_same_day(self):
        db = FakeDb()
        db.preset(
            l_upsert_metadata_to_mongodb.NOTE_METADATA,
            [
                {
                    "status": "archived",
                    "topic": "python",
                    "embedded_status": True,
                    "archived_md_frontmatter": {"type": "daily-log", "tags": ["etl", "gcs"]},
                },
                {
                    "status": "archived",
                    "topic": "database",
                    "embedded_status": False,
                    "archived_md_frontmatter": {"type": "project", "tags": ["etl"]},
                },
                {
                    "status": "review_closed",
                    "review_result": "rejected",
                    "topic": "ml",
                    "embedded_status": False,
                    "archived_md_frontmatter": {"type": "draft", "tags": ["wip"]},
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

        summary = t_build_summary.build_summary(db, "obsidian_note_metadata")
        s = summary["summary"]
        # archived + rejected 兩桶，排除 deleted / error
        self.assertEqual(s["embedded_notes"], 1)

        # archived 桶
        self.assertEqual(s["archived_notes"], 2)
        self.assertEqual(dict(s["by_tag_in_archived_notes"]), {"etl": 2, "gcs": 1})
        self.assertEqual(dict(s["by_topic_in_archived_notes"]), {"python": 1, "database": 1})
        self.assertEqual(dict(s["by_type_in_archived_notes"]), {"daily-log": 1, "project": 1})

        # rejected 桶
        self.assertEqual(s["rejected_notes"], 1)
        self.assertEqual(dict(s["by_tag_in_rejected_notes"]), {"wip": 1})
        self.assertEqual(dict(s["by_topic_in_rejected_notes"]), {"ml": 1})
        self.assertEqual(dict(s["by_type_in_rejected_notes"]), {"draft": 1})

        # upsert 後的全域統計涵蓋 archived + rejected
        l_upsert_summary_to_mongodb.upsert_summary(db, [summary])
        snap = db.collections[l_upsert_summary_to_mongodb.NOTES_SUMMARY].docs[0]
        self.assertEqual(snap["total_notes"], 3)
        self.assertEqual(snap["embedded_notes"], 1)
        self.assertEqual(snap["archived_notes"], 2)
        self.assertEqual(snap["rejected_notes"], 1)

        l_upsert_summary_to_mongodb.upsert_summary(db, [summary])  # 同日重跑
        self.assertEqual(len(db.collections[l_upsert_summary_to_mongodb.NOTES_SUMMARY].docs), 1)


if __name__ == "__main__":
    unittest.main()
