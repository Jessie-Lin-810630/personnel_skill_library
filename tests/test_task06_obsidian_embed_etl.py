import os
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parents[1]
TASK_DIR = PROJECT_ROOT / "task06_obsidian_embed_etl"
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(TASK_DIR))

from task06_obsidian_embed_etl import l_load_to_mongodb, main, t_chunk_embed


# ──────────────────────────────────────────────────────────────────
# 測試替身 (fakes)：模擬 GCS bucket / blob 與 genai client，
# 讓測試完全離線，不碰 GCS、Vertex AI、MongoDB。
# ──────────────────────────────────────────────────────────────────
class FakeBlob:
    def __init__(self, exists: bool):
        self._exists = exists

    def exists(self):
        return self._exists


class FakeBucket:
    """以一組「存在的 blob 路徑」集合模擬 GCS bucket。"""

    def __init__(self, existing_paths=None):
        self.existing_paths = set(existing_paths or [])

    def blob(self, path):
        return FakeBlob(path in self.existing_paths)


class FakeGenaiClient:
    """models.embed_content() 回傳預設向量；記錄收到的 contents 供斷言。"""

    def __init__(self, values):
        self._values = values
        self.received_contents = []
        self.models = SimpleNamespace(embed_content=self._embed_content)

    def _embed_content(self, model, contents, config):
        self.received_contents.append(contents)
        embedding = SimpleNamespace(values=list(self._values))
        return SimpleNamespace(embeddings=[embedding])


# ──────────────────────────────────────────────────────────────────
# t_chunk_embed.py
# ──────────────────────────────────────────────────────────────────
class PreprocessObsidianContentTests(unittest.TestCase):
    def test_returns_str(self):
        result = t_chunk_embed.preprocess_obsidian_content("純文字")
        self.assertIsInstance(result, str)

    def test_removes_block_id(self):
        result = t_chunk_embed.preprocess_obsidian_content("一段內文 ^8e5a21 結尾")
        self.assertNotIn("^8e5a21", result)

    def test_wiki_link_with_alias_keeps_only_display_text(self):
        result = t_chunk_embed.preprocess_obsidian_content("see [[Real Page|顯示文字]] here")
        self.assertIn("顯示文字", result)
        self.assertNotIn("Real Page", result)
        self.assertNotIn("[[", result)

    def test_wiki_link_without_alias_keeps_link_name(self):
        result = t_chunk_embed.preprocess_obsidian_content("ref [[MongoDB 筆記]] end")
        self.assertIn("MongoDB 筆記", result)
        self.assertNotIn("[[", result)

    def test_image_embed_is_preserved_for_multimodal(self):
        # 多模態升級後 ![[圖片]] 不在此處移除，需保留進 chunk
        result = t_chunk_embed.preprocess_obsidian_content("圖： ![[diagram.png]]")
        self.assertIn("![[diagram.png]]", result)

    def test_collapses_excess_blank_lines(self):
        result = t_chunk_embed.preprocess_obsidian_content("a\n\n\n\n\nb")
        self.assertNotIn("\n\n\n", result)


class ChunkMarkdownTests(unittest.TestCase):
    def test_returns_list_of_dicts_with_str_fields(self):
        chunks = t_chunk_embed.chunk_markdown("# 標題\n\n這是一段內文。")
        self.assertIsInstance(chunks, list)
        self.assertGreater(len(chunks), 0)
        for chunk in chunks:
            self.assertIsInstance(chunk, dict)
            self.assertEqual(set(chunk), {"content", "section"})
            self.assertIsInstance(chunk["content"], str)
            self.assertIsInstance(chunk["section"], str)

    def test_section_path_reflects_header_hierarchy(self):
        chunks = t_chunk_embed.chunk_markdown("# H1標題\n## H2標題\n內文文字")
        sections = {c["section"] for c in chunks}
        self.assertTrue(any("H1標題" in s and "H2標題" in s for s in sections))

    def test_empty_content_returns_empty_list(self):
        self.assertEqual(t_chunk_embed.chunk_markdown(""), [])

    def test_whitespace_only_chunks_filtered_out(self):
        chunks = t_chunk_embed.chunk_markdown("   \n\n   ")
        self.assertEqual(chunks, [])


class NormalizeTests(unittest.TestCase):
    def test_returns_unit_vector(self):
        result = t_chunk_embed._normalize([3.0, 4.0])
        self.assertAlmostEqual(result[0], 0.6)
        self.assertAlmostEqual(result[1], 0.8)
        self.assertAlmostEqual(sum(v * v for v in result), 1.0)

    def test_zero_vector_returned_unchanged(self):
        # 避免除以零：norm 為 0 時原樣回傳
        self.assertEqual(t_chunk_embed._normalize([0.0, 0.0]), [0.0, 0.0])

    def test_output_is_list_of_floats(self):
        result = t_chunk_embed._normalize([1.0, 2.0, 2.0])
        self.assertIsInstance(result, list)
        self.assertTrue(all(isinstance(v, float) for v in result))


class ResolveChunkImagesTests(unittest.TestCase):
    def test_existing_image_resolved_to_gs_uri_and_text_stripped(self):
        bucket = FakeBucket(existing_paths={"dir/_attachment/x.png"})
        text_for_model, uris = t_chunk_embed._resolve_chunk_images(
            "說明 ![[x.png]] 文字", "dir/note.md", bucket, "personal-vaults"
        )
        self.assertEqual(uris, ["gs://personal-vaults/dir/_attachment/x.png"])
        self.assertNotIn("![[", text_for_model)
        self.assertIsInstance(text_for_model, str)

    def test_missing_image_is_skipped(self):
        bucket = FakeBucket(existing_paths=set())  # 圖片不存在
        text_for_model, uris = t_chunk_embed._resolve_chunk_images(
            "說明 ![[missing.png]]", "dir/note.md", bucket, "personal-vaults"
        )
        self.assertEqual(uris, [])

    def test_no_image_returns_empty_uri_list(self):
        bucket = FakeBucket()
        text_for_model, uris = t_chunk_embed._resolve_chunk_images(
            "純文字沒有圖片", "dir/note.md", bucket, "personal-vaults"
        )
        self.assertEqual(uris, [])
        self.assertEqual(text_for_model, "純文字沒有圖片")

    def test_returns_tuple_of_str_and_list(self):
        bucket = FakeBucket()
        result = t_chunk_embed._resolve_chunk_images("t", "d/n.md", bucket, "b")
        self.assertIsInstance(result, tuple)
        self.assertIsInstance(result[0], str)
        self.assertIsInstance(result[1], list)


class GetGenaiClientTests(unittest.TestCase):
    def test_returns_client_when_env_set(self):
        with (
            patch.dict(
                os.environ,
                {"AGENT_PLATFORM_USER_CREDENTIALS": "/fake/sa.json", "GCP_PROJECT_ID": "my-project"},
                clear=False,
            ),
            patch.object(t_chunk_embed.Credentials, "from_service_account_file", return_value=object()),
            patch.object(t_chunk_embed.genai, "Client", return_value="CLIENT") as client_ctor,
        ):
            result = t_chunk_embed._get_genai_client()

        self.assertEqual(result, "CLIENT")
        self.assertTrue(client_ctor.called)

    def test_raises_environment_error_when_project_missing(self):
        with (
            patch.dict(
                os.environ, {"AGENT_PLATFORM_USER_CREDENTIALS": "/fake/sa.json", "GCP_PROJECT_ID": ""}, clear=False
            ),
            patch.object(t_chunk_embed.Credentials, "from_service_account_file", return_value=object()),
            patch.object(t_chunk_embed.genai, "Client"),
        ):
            with self.assertRaises(EnvironmentError):
                t_chunk_embed._get_genai_client()


class EmbedChunksTests(unittest.TestCase):
    def test_appends_embedding_and_image_paths_with_correct_types(self):
        client = FakeGenaiClient(values=[3.0, 4.0])
        bucket = FakeBucket(existing_paths={"d/_attachment/x.png"})
        chunks = [{"content": "文字 ![[x.png]]", "section": "S"}]

        result = t_chunk_embed.embed_chunks_a_mardown(
            chunks, client, "d/note.md", "我的筆記", bucket, "personal-vaults"
        )

        self.assertEqual(len(result), 1)
        doc = result[0]
        self.assertEqual(doc["content"], "文字 ![[x.png]]")  # 原始文字保留 ![[ ]]
        self.assertEqual(doc["image_paths"], ["gs://personal-vaults/d/_attachment/x.png"])
        self.assertIsInstance(doc["embedding"], list)
        self.assertTrue(all(isinstance(v, float) for v in doc["embedding"]))
        # 已 L2 normalize
        self.assertAlmostEqual(sum(v * v for v in doc["embedding"]), 1.0)

    def test_text_only_chunk_has_empty_image_paths(self):
        client = FakeGenaiClient(values=[1.0, 0.0])
        bucket = FakeBucket()
        chunks = [{"content": "純文字", "section": ""}]

        result = t_chunk_embed.embed_chunks_a_mardown(chunks, client, "d/note.md", "標題", bucket, "personal-vaults")
        self.assertEqual(result[0]["image_paths"], [])


class ChunkAndEmbedOrchestrationTests(unittest.TestCase):
    """t_chunk_and_embed：以 mock 隔絕 GCS / Vertex，著重例外捕捉與回傳型別。"""

    def _patches(self, fetch_side_effect=None, chunk_return=None, embed_return=None):
        return [
            patch.object(t_chunk_embed, "_get_genai_client", return_value=object()),
            patch.object(
                t_chunk_embed,
                "storage",
                SimpleNamespace(Client=lambda: SimpleNamespace(bucket=lambda name: FakeBucket())),
            ),
            patch.object(t_chunk_embed, "fetch_gcs_note_content", side_effect=fetch_side_effect),
            patch.object(t_chunk_embed, "chunk_markdown", return_value=chunk_return),
            patch.object(t_chunk_embed, "embed_chunks_a_mardown", return_value=embed_return),
        ]

    def test_success_builds_vector_docs_and_returns_tuple(self):
        note = {
            "file_path": "k/a.md",
            "file_name": "a.md",
            "tags": ["MongoDB"],
            "note_type": "knowledge",
            "date": "2026-04-13",
        }
        embedded = [
            {"content": "c0", "section": "S", "image_paths": [], "embedding": [0.1]},
            {"content": "c1", "section": "S", "image_paths": [], "embedding": [0.2]},
        ]
        patches = self._patches(
            fetch_side_effect=lambda *a, **k: "raw md",
            chunk_return=[{"content": "c0", "section": "S"}, {"content": "c1", "section": "S"}],
            embed_return=embedded,
        )
        with patches[0], patches[1], patches[2], patches[3], patches[4]:
            docs, processed = t_chunk_embed.t_chunk_and_embed([note])

        self.assertIsInstance(docs, list)
        self.assertIsInstance(processed, list)
        self.assertEqual(processed, ["k/a.md"])
        self.assertEqual(len(docs), 2)
        self.assertEqual(docs[0]["chunk_index"], 0)
        self.assertEqual(docs[1]["chunk_index"], 1)
        self.assertEqual(docs[0]["chunk_total"], 2)
        self.assertEqual(docs[0]["file_name"], "a.md")
        self.assertEqual(docs[0]["tags"], ["MongoDB"])

    def test_processes_all_notes_without_throttle(self):
        # 迴歸測試：確認舊的 count<=2 限流已移除，所有候選都會被處理
        notes = [{"file_path": f"n{i}.md", "file_name": f"n{i}.md"} for i in range(3)]
        embedded = [{"content": "c", "section": "", "image_paths": [], "embedding": [1.0]}]
        patches = self._patches(
            fetch_side_effect=lambda *a, **k: "raw",
            chunk_return=[{"content": "c", "section": ""}],
            embed_return=embedded,
        )
        with patches[0], patches[1], patches[2], patches[3], patches[4]:
            docs, processed = t_chunk_embed.t_chunk_and_embed(notes)

        self.assertEqual(processed, ["n0.md", "n1.md", "n2.md"])
        self.assertEqual(len(docs), 3)  # 每份 1 chunk，3 份全處理

    def test_exception_during_fetch_is_caught_and_file_not_processed(self):
        note = {"file_path": "bad.md", "file_name": "bad.md"}
        patches = self._patches(
            fetch_side_effect=RuntimeError("GCS 爆炸"),
            chunk_return=[],
            embed_return=[],
        )
        with patches[0], patches[1], patches[2], patches[3], patches[4]:
            docs, processed = t_chunk_embed.t_chunk_and_embed([note])

        # 例外被吞掉 → 不拋出、該檔不列入 processed_files (下輪重試)
        self.assertEqual(docs, [])
        self.assertEqual(processed, [])

    def test_empty_chunks_counts_as_processed_without_vector_docs(self):
        note = {"file_path": "empty.md", "file_name": "empty.md"}
        patches = self._patches(
            fetch_side_effect=lambda *a, **k: "raw",
            chunk_return=[],  # 切塊為空
            embed_return=[],
        )
        with patches[0], patches[1], patches[2], patches[3], patches[4]:
            docs, processed = t_chunk_embed.t_chunk_and_embed([note])

        self.assertEqual(docs, [])
        self.assertEqual(processed, ["empty.md"])  # 空切塊仍視為已處理


# ──────────────────────────────────────────────────────────────────
# l_load_to_mongodb.py
# ──────────────────────────────────────────────────────────────────
class FakeCollection:
    def __init__(self, find_docs=None):
        self.find_docs = find_docs or []
        self.deleted_filters = []
        self.inserted_batches = []
        self.update_calls = []
        self.cas_matched = True  # update_one 是否命中

    def find(self, filter_doc=None, projection=None):
        return list(self.find_docs)

    def delete_many(self, filter_doc):
        self.deleted_filters.append(filter_doc)
        return SimpleNamespace(deleted_count=0)

    def insert_many(self, docs):
        self.inserted_batches.append(list(docs))
        return SimpleNamespace(inserted_ids=list(range(len(docs))))

    def update_one(self, filter_doc, update_doc):
        self.update_calls.append((filter_doc, update_doc))
        return SimpleNamespace(matched_count=1 if self.cas_matched else 0)


class FakeDb:
    def __init__(self):
        self.collections = {}

    def __getitem__(self, name):
        self.collections.setdefault(name, FakeCollection())
        return self.collections[name]


class GetDbTests(unittest.TestCase):
    def test_returns_named_database_from_client(self):
        fake_client = {"skill_library": object()}
        with patch.object(l_load_to_mongodb, "MongoClient", return_value=fake_client) as mongo:
            db = l_load_to_mongodb.get_db("mongodb://localhost:27017", "skill_library")
        mongo.assert_called_once_with("mongodb://localhost:27017")
        self.assertIs(db, fake_client["skill_library"])


class GetNotesStateTests(unittest.TestCase):
    def test_maps_file_path_to_state_dict(self):
        db = FakeDb()
        db["obsidian_notes"].find_docs = [
            {"file_path": "a.md", "file_md5_hash": "H1", "embedding_done": False},
            {"file_path": "b.md", "file_md5_hash": "H2", "embedding_done": True},
        ]
        state = l_load_to_mongodb.get_notes_state(db)

        self.assertIsInstance(state, dict)
        self.assertEqual(state["a.md"], {"file_md5_hash": "H1", "embedding_done": False})
        self.assertEqual(state["b.md"]["embedding_done"], True)

    def test_missing_fields_default_to_none(self):
        db = FakeDb()
        db["obsidian_notes"].find_docs = [{"file_path": "c.md"}]
        state = l_load_to_mongodb.get_notes_state(db)
        self.assertIsNone(state["c.md"]["file_md5_hash"])
        self.assertIsNone(state["c.md"]["embedding_done"])


class LoadVectorsIncrementalTests(unittest.TestCase):
    def test_delete_then_insert_and_cas_flip_for_each_file(self):
        db = FakeDb()
        vector_docs = [
            {"file_path": "a.md", "chunk_index": 0},
            {"file_path": "a.md", "chunk_index": 1},
        ]
        l_load_to_mongodb.load_vectors_incremental(
            db,
            vector_docs,
            processed_file_paths=["a.md"],
            embedded_md5_by_file_path={"a.md": "H1"},
        )

        vectors_col = db.collections["obsidian_vectors_multimodal"]
        notes_col = db.collections["obsidian_notes"]
        # 先刪後插
        self.assertEqual(vectors_col.deleted_filters, [{"file_path": "a.md"}])
        self.assertEqual(len(vectors_col.inserted_batches), 1)
        self.assertEqual(len(vectors_col.inserted_batches[0]), 2)
        # CAS 守衛條件包含 md5 與 embedding_done False
        cas_filter, cas_update = notes_col.update_calls[0]
        self.assertEqual(cas_filter["file_md5_hash"], "H1")
        self.assertEqual(cas_filter["embedding_done"], False)
        self.assertTrue(cas_update["$set"]["embedding_done"])

    def test_empty_chunk_file_still_deletes_and_cas_without_insert(self):
        db = FakeDb()
        l_load_to_mongodb.load_vectors_incremental(
            db,
            vector_docs=[],
            processed_file_paths=["empty.md"],
            embedded_md5_by_file_path={"empty.md": "H"},
        )
        vectors_col = db.collections["obsidian_vectors_multimodal"]
        notes_col = db.collections["obsidian_notes"]
        self.assertEqual(vectors_col.deleted_filters, [{"file_path": "empty.md"}])
        self.assertEqual(vectors_col.inserted_batches, [])  # 無 chunk 不 insert
        self.assertEqual(len(notes_col.update_calls), 1)

    def test_cas_miss_does_not_raise(self):
        db = FakeDb()
        db["obsidian_notes"].cas_matched = False  # 模擬 CAS 未命中
        # 不應拋出例外
        l_load_to_mongodb.load_vectors_incremental(
            db,
            vector_docs=[{"file_path": "a.md", "chunk_index": 0}],
            processed_file_paths=["a.md"],
            embedded_md5_by_file_path={"a.md": "H1"},
        )


# ──────────────────────────────────────────────────────────────────
# main.py
# ──────────────────────────────────────────────────────────────────
class RunTask06Tests(unittest.TestCase):
    def test_gate_only_passes_done_false_and_md5_matching_notes(self):
        notes_on_gcs = [
            {"file_path": "ok.md", "file_md5_hash": "H_OK"},  # 候選：done False + md5 相符
            {"file_path": "done.md", "file_md5_hash": "H_DONE"},  # 已 embedding_done
            {"file_path": "stale.md", "file_md5_hash": "H_NEW"},  # md5 不符
            {"file_path": "absent.md", "file_md5_hash": "H_X"},  # DB 沒記錄
        ]
        notes_state = {
            "ok.md": {"file_md5_hash": "H_OK", "embedding_done": False},
            "done.md": {"file_md5_hash": "H_DONE", "embedding_done": True},
            "stale.md": {"file_md5_hash": "H_OLD", "embedding_done": False},
        }
        db = object()

        with (
            patch.dict(
                os.environ,
                {"MONGO_ALTAS_URI": "mongodb://localhost:27017", "MONGO_DB_NAME": "skill_library"},
                clear=False,
            ),
            patch.object(main, "scan_vault_gs", return_value=notes_on_gcs),
            patch.object(main, "get_db", return_value=db),
            patch.object(main, "get_notes_state", return_value=notes_state),
            patch.object(main, "t_chunk_and_embed", return_value=([], [])) as t_step,
            patch.object(main, "load_vectors_incremental") as load_step,
        ):
            main.run_task06()

        # 只有 ok.md 通過 gate
        (candidates,), _ = t_step.call_args
        self.assertEqual([n["file_path"] for n in candidates], ["ok.md"])
        # embedded_md5_by_file_path 正確帶入 load
        load_args, load_kwargs = load_step.call_args
        self.assertEqual(load_args[3], {"ok.md": "H_OK"})

    def test_raises_when_required_env_vars_missing(self):
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(EnvironmentError):
                main.run_task06()


if __name__ == "__main__":
    unittest.main()
