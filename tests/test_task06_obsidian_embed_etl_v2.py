import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from task06_obsidian_embed_etl_v2 import e_scan_metadata, l_load_to_mongodb, t_chunk_embed


# --------------------------- functional fakes ---------------------------
def _matches(doc, filt):
    return all(doc.get(k) == v for k, v in (filt or {}).items())


class FakeCollection:
    def __init__(self, docs=None):
        self.docs = [dict(d) for d in (docs or [])]

    def find(self, filt=None, projection=None):
        return [dict(d) for d in self.docs if _matches(d, filt)]

    def delete_many(self, filt):
        before = len(self.docs)
        self.docs = [d for d in self.docs if not _matches(d, filt)]
        return SimpleNamespace(deleted_count=before - len(self.docs))

    def insert_many(self, docs):
        self.docs.extend(dict(d) for d in docs)

    def update_one(self, filt, update, upsert=False):
        for d in self.docs:
            if _matches(d, filt):
                d.update(update.get("$set", {}))
                return SimpleNamespace(matched_count=1)
        return SimpleNamespace(matched_count=0)


class FakeDb:
    def __init__(self):
        self.collections = {}

    def __getitem__(self, name):
        self.collections.setdefault(name, FakeCollection())
        return self.collections[name]

    def preset(self, name, docs):
        self.collections[name] = FakeCollection(docs)


# --------------------------- Task 2.3: gate ---------------------------
class GateTests(unittest.TestCase):
    def test_gate_selects_archived_and_not_embedded(self):
        db = FakeDb()
        db.preset(
            e_scan_metadata.NOTE_METADATA,
            [
                {"raw_md_path": "a", "status": "archived", "embedded_status": False},  # 挑
                {"raw_md_path": "b", "status": "archived", "embedded_status": True},  # 已向量化 → 略
                {"raw_md_path": "c", "status": "deleted", "embedded_status": False},  # 非 archived → 略
            ],
        )
        result = e_scan_metadata.get_embedding_gate_list(db)
        self.assertEqual({d["raw_md_path"] for d in result}, {"a"})

    def test_blob_name_from_uri(self):
        self.assertEqual(
            e_scan_metadata.blob_name_from_uri("gs://personal-vaults/archived-notes/u/x.md", "personal-vaults"),
            "archived-notes/u/x.md",
        )


# --------------------------- Task 3.4: chunk+embed produces raw_md_path & archived images ---------------------------
class _FakeImgBlob:
    def exists(self):
        return True


class _FakeBucket:
    def blob(self, name):
        return _FakeImgBlob()


class _FakeStorageClient:
    def bucket(self, name):
        return _FakeBucket()


class _FakeGenaiClient:
    class models:
        @staticmethod
        def embed_content(model, contents, config):
            # 回傳 [3.0, 4.0] → _normalize 後 [0.6, 0.8]
            return SimpleNamespace(embeddings=[SimpleNamespace(values=[3.0, 4.0])])


class ChunkEmbedV2Tests(unittest.TestCase):
    def test_vector_docs_keyed_on_raw_md_path_with_archived_image_source(self):
        gate_list = [
            {
                "raw_md_path": "gs://personal-vaults/raw-notes/u/nb/01-d/x.md",
                "archived_md_path": "gs://personal-vaults/archived-notes/u/nb/01-d/x.md",
                "archived_md_md5_hash": "M1",
                "archived_md_frontmatter": {"tags": ["python"], "type": "daily-log", "alias": ["X"]},
                "file_name": "x.md",
            }
        ]
        md_body = "# 標題\n本文 ![[a.png]] 內容\n"

        with (
            patch.object(t_chunk_embed, "fetch_archived_content", return_value=md_body),
            patch.object(t_chunk_embed.storage, "Client", return_value=_FakeStorageClient()),
        ):
            docs, md5_map = t_chunk_embed.t_chunk_and_embed_v2(
                gate_list, "personal-vaults", genai_client=_FakeGenaiClient()
            )

        self.assertTrue(docs)
        for d in docs:
            self.assertEqual(d["raw_md_path"], "gs://personal-vaults/raw-notes/u/nb/01-d/x.md")
            self.assertEqual(d["embedding"], [0.6, 0.8])
        # 圖片來源指向 archived-notes 的 _attachment（非 raw-notes）
        all_imgs = [p for d in docs for p in d["image_paths"]]
        self.assertIn("gs://personal-vaults/archived-notes/u/nb/01-d/_attachment/a.png", all_imgs)
        # md5 map 供 Load 端 CAS 守衛
        self.assertEqual(md5_map, {"gs://personal-vaults/raw-notes/u/nb/01-d/x.md": "M1"})


# --------------------------- Task 4.3: load + CAS ---------------------------
class LoadVectorsTests(unittest.TestCase):
    def _db(self, md5="M1"):
        db = FakeDb()
        db.preset(
            l_load_to_mongodb.NOTE_METADATA,
            [{"raw_md_path": "r1", "embedded_status": False, "archived_md_md5_hash": md5}],
        )
        return db

    def test_delete_then_insert_and_cas_flip(self):
        db = self._db()
        # 舊 3 chunk（先刪後插應清光）
        db.preset(l_load_to_mongodb.VECTORS_V2, [{"raw_md_path": "r1", "chunk_index": i} for i in range(3)])
        new_docs = [{"raw_md_path": "r1", "chunk_index": 0}, {"raw_md_path": "r1", "chunk_index": 1}]  # 新 2 chunk

        l_load_to_mongodb.load_vectors_incremental_v2(db, new_docs, {"r1": "M1"})

        vecs = db.collections[l_load_to_mongodb.VECTORS_V2].docs
        self.assertEqual(len(vecs), 2)  # 先刪後插，無孤兒
        note = db.collections[l_load_to_mongodb.NOTE_METADATA].docs[0]
        self.assertTrue(note["embedded_status"])
        self.assertIn("embedded_at", note)

    def test_cas_miss_when_md5_changed_does_not_flip(self):
        db = self._db(md5="M1")
        new_docs = [{"raw_md_path": "r1", "chunk_index": 0}]

        l_load_to_mongodb.load_vectors_incremental_v2(db, new_docs, {"r1": "M2"})  # 版本已變

        note = db.collections[l_load_to_mongodb.NOTE_METADATA].docs[0]
        self.assertFalse(note["embedded_status"])  # CAS 未命中不翻


# --------------------------- Task 5.3: purge ---------------------------
class PurgeTests(unittest.TestCase):
    def _db(self):
        db = FakeDb()
        db.preset(
            l_load_to_mongodb.NOTE_METADATA,
            [
                {"raw_md_path": "d1", "status": "deleted", "embedded_status": True},
                {"raw_md_path": "a1", "status": "archived", "embedded_status": True},
            ],
        )
        db.preset(
            l_load_to_mongodb.VECTORS_V2,
            [
                {"raw_md_path": "d1", "chunk_index": 0},
                {"raw_md_path": "d1", "chunk_index": 1},
                {"raw_md_path": "a1", "chunk_index": 0},
            ],
        )
        return db

    def test_purges_deleted_vectors_and_flips_embedded_status(self):
        db = self._db()
        n = l_load_to_mongodb.purge_deleted_vectors(db)

        self.assertEqual(n, 1)
        vecs = {d["raw_md_path"] for d in db.collections[l_load_to_mongodb.VECTORS_V2].docs}
        self.assertEqual(vecs, {"a1"})  # d1 向量清除、a1 保留
        d1 = next(d for d in db.collections[l_load_to_mongodb.NOTE_METADATA].docs if d["raw_md_path"] == "d1")
        self.assertFalse(d1["embedded_status"])

    def test_rerun_is_idempotent(self):
        db = self._db()
        l_load_to_mongodb.purge_deleted_vectors(db)
        n_again = l_load_to_mongodb.purge_deleted_vectors(db)
        self.assertEqual(n_again, 0)


# --------------------------- 空值 / None 邊界 ---------------------------
class EdgeCaseTests(unittest.TestCase):
    def test_fetch_archived_content_raises_real_error(self):
        # GCS 失敗時應如實拋原例外，而非吞掉後拋 UnboundLocalError
        class _Boom:
            def bucket(self, name):
                raise RuntimeError("gcs down")

        with patch.object(e_scan_metadata.storage, "Client", return_value=_Boom()):
            with self.assertRaises(RuntimeError):
                e_scan_metadata.fetch_archived_content("gs://personal-vaults/archived-notes/u/x.md")

    def test_empty_gate_returns_empty_without_genai_client(self):
        # 空 gate 不應觸發 _get_genai_client（無 env 也不該 raise）
        docs, md5 = t_chunk_embed.t_chunk_and_embed_v2([], "personal-vaults")
        self.assertEqual(docs, [])
        self.assertEqual(md5, {})

    def test_malformed_gate_doc_is_skipped(self):
        # 缺 archived_md_path 的畸形 gate doc → 略過該筆、不 crash
        with patch.object(t_chunk_embed.storage, "Client", return_value=_FakeStorageClient()):
            docs, md5 = t_chunk_embed.t_chunk_and_embed_v2(
                [{"raw_md_path": "r1"}], "personal-vaults", genai_client=_FakeGenaiClient()
            )
        self.assertEqual(docs, [])
        self.assertEqual(md5, {})

    def test_note_title_empty_note(self):
        self.assertEqual(t_chunk_embed._note_title({}), "")

    def test_normalize_empty_and_zero_vector(self):
        self.assertEqual(t_chunk_embed._normalize([]), [])
        self.assertEqual(t_chunk_embed._normalize([0.0, 0.0]), [0.0, 0.0])

    def test_load_empty_chunk_note_deletes_old_and_flips(self):
        # 空切塊 note：vector_docs 空但 md5 map 有此筆 → 舊向量清光、仍翻 embedded_status
        db = FakeDb()
        db.preset(
            l_load_to_mongodb.NOTE_METADATA,
            [{"raw_md_path": "r1", "embedded_status": False, "archived_md_md5_hash": "M1"}],
        )
        db.preset(l_load_to_mongodb.VECTORS_V2, [{"raw_md_path": "r1", "chunk_index": 0}])

        l_load_to_mongodb.load_vectors_incremental_v2(db, [], {"r1": "M1"})

        self.assertEqual(db.collections[l_load_to_mongodb.VECTORS_V2].docs, [])
        self.assertTrue(db.collections[l_load_to_mongodb.NOTE_METADATA].docs[0]["embedded_status"])


if __name__ == "__main__":
    unittest.main()
