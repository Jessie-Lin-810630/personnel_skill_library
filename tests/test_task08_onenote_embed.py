"""tests/test_task08_onenote_embed.py

Unit tests for task08_onenote_embed_etl：gate 過濾、markdown 圖片解析、向量 doc 結構、
先刪後插 + CAS。全部 mock，不連 GCS / MongoDB / Vertex AI。
"""

import unittest
from unittest.mock import MagicMock, patch

from task08_onenote_embed_etl import e_scan_metadata as e
from task08_onenote_embed_etl import l_load_to_mongodb as l
from task08_onenote_embed_etl import t_chunk_embed as t


class GateListTests(unittest.TestCase):
    def test_filter_and_projection(self):
        mock_col = MagicMock()
        mock_col.find.return_value = [{"page_id": "p1"}]
        db = {"onenote_note_metadata": mock_col}
        result = e.get_embedding_gate_list(db)
        self.assertEqual(result, [{"page_id": "p1"}])
        query, projection = mock_col.find.call_args[0]
        self.assertEqual(query, {"status": "archived", "embedded_status": False})
        # 投影必含向量血緣與 CAS 守衛所需欄位
        for key in ("archived_md_path", "md_md5_hash", "md_frontmatter", "page_title", "attached_images"):
            self.assertIn(key, projection)


class BlobNameTests(unittest.TestCase):
    def test_strips_gs_prefix(self):
        self.assertEqual(
            e.blob_name_from_uri("gs://onenote-vaults/archived-notes/u/n.md", "onenote-vaults"),
            "archived-notes/u/n.md",
        )

    def test_passthrough_when_no_prefix(self):
        self.assertEqual(e.blob_name_from_uri("archived-notes/u/n.md", "onenote-vaults"), "archived-notes/u/n.md")


class ResolveChunkImagesTests(unittest.TestCase):
    def test_markdown_link_basename_match(self):
        archived_by_basename = {
            "r1.png": "gs://onenote-vaults/archived-notes/u/nb/sec/dt=2026-07-01/_images/r1.png",
        }
        text = "先講原理\n\n![示意圖](_images/r1.png)\n\n後續說明"
        text_for_model, uris = t._resolve_chunk_images(text, archived_by_basename)
        self.assertEqual(uris, [archived_by_basename["r1.png"]])
        self.assertNotIn("![", text_for_model)  # 圖片語法已從文字移除

    def test_unmatched_link_skipped(self):
        text = "![壞連結](_images/typo.png)"
        text_for_model, uris = t._resolve_chunk_images(text, {})
        self.assertEqual(uris, [])
        self.assertEqual(text_for_model, "")


class NoteHelperTests(unittest.TestCase):
    def test_archived_by_basename_only_archived(self):
        note = {
            "attached_images": [
                {"raw_image_path": "gs://b/raw/_images/a.png", "archived_image_path": "gs://b/arch/_images/a.png"},
                {"raw_image_path": "gs://b/raw/_images/b.png"},  # 未歸檔 → 略過
            ]
        }
        mapping = t._archived_by_basename(note)
        self.assertEqual(mapping, {"a.png": "gs://b/arch/_images/a.png"})

    def test_note_title_prefers_alias(self):
        self.assertEqual(t._note_title({"md_frontmatter": {"alias": ["別名"]}, "page_title": "標題"}), "別名")
        self.assertEqual(t._note_title({"md_frontmatter": {"alias": []}, "page_title": "標題"}), "標題")


class ChunkAndEmbedTests(unittest.TestCase):
    def _fake_client(self):
        client = MagicMock()
        emb = MagicMock()
        emb.embeddings = [MagicMock(values=[3.0, 4.0])]  # L2 normalize → [0.6, 0.8]
        client.models.embed_content.return_value = emb
        return client

    def test_empty_gate_returns_empty(self):
        docs, md5map = t.t_chunk_and_embed_onenote([])
        self.assertEqual((docs, md5map), ([], {}))

    @patch("task08_onenote_embed_etl.t_chunk_embed.fetch_archived_content")
    def test_vector_doc_shape_and_md5_map(self, mock_fetch):
        mock_fetch.return_value = "# 標題\n\n內文段落。\n\n![圖](_images/r1.png)\n"
        note = {
            "archived_md_path": "gs://onenote-vaults/archived-notes/u/nb/sec/dt=2026-07-01/n.md",
            "md_md5_hash": "MD5",
            "page_title": "python-note",
            "md_frontmatter": {
                "tags": ["python"],
                "type": "knowledge_summary",
                "date": "2026-07-01",
                "alias": ["別名"],
            },
            "attached_images": [
                {"archived_image_path": "gs://onenote-vaults/archived-notes/u/nb/sec/dt=2026-07-01/_images/r1.png"}
            ],
        }
        docs, md5map = t.t_chunk_and_embed_onenote([note], genai_client=self._fake_client())

        self.assertEqual(md5map, {note["archived_md_path"]: "MD5"})
        self.assertTrue(docs)
        d = docs[0]
        # 向量血緣欄 md_path（note_vectors_multimodal 欄位）存 C3 的 archived_md_path 值
        self.assertEqual(d["md_path"], note["archived_md_path"])
        self.assertEqual(d["file_name"], "python-note")
        self.assertEqual(d["tags"], ["python"])
        self.assertEqual(d["note_type"], "knowledge_summary")
        self.assertEqual(d["chunk_total"], len(docs))
        # embedding 已 L2 normalize
        self.assertAlmostEqual(sum(v * v for v in d["embedding"]), 1.0, places=5)
        # 命中的圖片來源為 archived 路徑
        img_chunks = [x for x in docs if x["image_paths"]]
        self.assertTrue(img_chunks)
        self.assertEqual(img_chunks[0]["image_paths"], [note["attached_images"][0]["archived_image_path"]])

    @patch("task08_onenote_embed_etl.t_chunk_embed.fetch_archived_content")
    def test_empty_body_still_counts_as_processed(self, mock_fetch):
        mock_fetch.return_value = "   "  # 切塊為空
        note = {"archived_md_path": "gs://b/arch/n.md", "md_md5_hash": "M", "page_title": "n", "md_frontmatter": {}}
        docs, md5map = t.t_chunk_and_embed_onenote([note], genai_client=self._fake_client())
        self.assertEqual(docs, [])
        self.assertEqual(md5map, {"gs://b/arch/n.md": "M"})

    @patch("task08_onenote_embed_etl.t_chunk_embed.fetch_archived_content")
    def test_failed_note_excluded_from_md5_map(self, mock_fetch):
        mock_fetch.side_effect = RuntimeError("download boom")
        note = {"archived_md_path": "gs://b/arch/n.md", "md_md5_hash": "M", "page_title": "n", "md_frontmatter": {}}
        docs, md5map = t.t_chunk_and_embed_onenote([note], genai_client=self._fake_client())
        self.assertEqual(docs, [])
        self.assertEqual(md5map, {})  # 失敗檔不列入，下輪重試


class LoadTests(unittest.TestCase):
    def _db(self):
        vectors, notes = MagicMock(), MagicMock()
        return {"note_vectors_multimodal": vectors, "onenote_note_metadata": notes}, vectors, notes

    def test_delete_before_insert_and_cas_flip(self):
        db, vectors, notes = self._db()
        notes.update_one.return_value = MagicMock(matched_count=1)
        md_path = "gs://onenote-vaults/archived-notes/u/n.md"
        vector_docs = [{"md_path": md_path, "chunk_index": 0}, {"md_path": md_path, "chunk_index": 1}]
        l.load_vectors_incremental_onenote(db, vector_docs, {md_path: "MD5"})

        vectors.delete_many.assert_called_once_with({"md_path": md_path})
        vectors.insert_many.assert_called_once()
        # CAS 以 archived_md_path 定位版本 + md_md5_hash 守衛 + embedded_status=false
        cas_filter = notes.update_one.call_args[0][0]
        self.assertEqual(cas_filter, {"archived_md_path": md_path, "embedded_status": False, "md_md5_hash": "MD5"})
        cas_update = notes.update_one.call_args[0][1]
        self.assertTrue(cas_update["$set"]["embedded_status"])
        self.assertIn("embedded_at", cas_update["$set"])
        # embedded_at 與 updated_at 同一時戳，避免 embedded_at 晚於 updated_at 的矛盾
        self.assertIn("updated_at", cas_update["$set"])
        self.assertEqual(cas_update["$set"]["embedded_at"], cas_update["$set"]["updated_at"])

    def test_cas_miss_does_not_error(self):
        db, vectors, notes = self._db()
        notes.update_one.return_value = MagicMock(matched_count=0)  # 版本已變 → 未命中
        md_path = "gs://b/arch/n.md"
        # 切塊為空的檔：md5map 有、但 vector_docs 無對應 chunk → 只刪不插
        l.load_vectors_incremental_onenote(db, [], {md_path: "M"})
        vectors.delete_many.assert_called_once_with({"md_path": md_path})
        vectors.insert_many.assert_not_called()


if __name__ == "__main__":
    unittest.main()
