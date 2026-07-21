import os
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from task03_leetcode_ccClub_etl import (
    e_crawler_ccClub,
    e_query_leetcode_graphql,
    l_load_ccClub_doc_to_mongodb,
    l_load_leetcode_doc_to_mongodb,
    main,
    t_transform_ccClub,
    t_transform_leetcode,
)


class FakeResponse:
    def __init__(self, status_code=200, payload=None, headers=None):
        self.status_code = status_code
        self._payload = payload if payload is not None else {}
        self.headers = headers or {}

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise Exception(f"HTTP {self.status_code}")


class LeetCodeExtractTests(unittest.TestCase):
    def test_get_headers_builds_expected_cookie_and_csrf_headers(self):
        headers = e_query_leetcode_graphql._get_headers("csrf-token", "session-token", "jessie")

        self.assertEqual(headers["Content-Type"], "application/json")
        self.assertEqual(headers["Cookie"], "LEETCODE_SESSION=session-token; csrftoken=csrf-token")
        self.assertEqual(headers["x-csrftoken"], "csrf-token")
        self.assertEqual(headers["Referer"], "https://leetcode.com")
        self.assertEqual(headers["User-Agent"], "jessie")

    def test_post_graphql_returns_json_on_success(self):
        response = FakeResponse(status_code=200, payload={"data": {"ok": True}})

        with patch.object(e_query_leetcode_graphql.requests, "post", return_value=response) as request_post:
            data = e_query_leetcode_graphql._post_graphql({"h": "1"}, {"query": "q"})

        request_post.assert_called_once_with(
            e_query_leetcode_graphql.LEETCODE_GRAPHQL_URL,
            headers={"h": "1"},
            json={"query": "q"},
            timeout=30,
        )
        self.assertEqual(data, {"data": {"ok": True}})

    def test_post_graphql_retries_after_429(self):
        responses = [
            FakeResponse(status_code=429, payload={}),
            FakeResponse(status_code=200, payload={"data": {"ok": True}}),
        ]

        with (
            patch.object(e_query_leetcode_graphql.requests, "post", side_effect=responses) as request_post,
            patch.object(e_query_leetcode_graphql.time, "sleep") as sleep,
        ):
            data = e_query_leetcode_graphql._post_graphql({"h": "1"}, {"query": "q"})

        self.assertEqual(data, {"data": {"ok": True}})
        self.assertEqual(request_post.call_count, 2)
        sleep.assert_called_once_with(300)

    def test_post_graphql_raises_when_graphql_body_contains_errors(self):
        response = FakeResponse(
            status_code=200,
            payload={"errors": [{"message": "bad query"}]},
        )

        with patch.object(e_query_leetcode_graphql.requests, "post", return_value=response):
            with self.assertRaises(Exception):
                e_query_leetcode_graphql._post_graphql({"h": "1"}, {"query": "q"})

    def test_fetch_solved_problem_stats_extracts_submission_stats(self):
        payload = {
            "data": {
                "matchedUser": {
                    "submitStatsGlobal": {
                        "acSubmissionNum": [
                            {"difficulty": "Easy", "count": 10},
                            {"difficulty": "Med.", "count": 5},
                        ]
                    }
                }
            }
        }

        with patch.object(e_query_leetcode_graphql, "_post_graphql", return_value=payload) as post_graphql:
            stats = e_query_leetcode_graphql.fetch_solved_problem_stats({"h": "1"}, "jessie")

        self.assertEqual(
            stats,
            [
                {"difficulty": "Easy", "count": 10},
                {"difficulty": "Med.", "count": 5},
            ],
        )
        self.assertTrue(post_graphql.called)

    def test_fetch_solved_problems_features_returns_question_list(self):
        payload = {
            "data": {
                "problemsetQuestionList": {
                    "total": 2,
                    "questions": [
                        {"frontendQuestionId": "1", "title": "Two Sum"},
                        {"frontendQuestionId": "2", "title": "Add Two Numbers"},
                    ],
                }
            }
        }

        with patch.object(e_query_leetcode_graphql, "_post_graphql", return_value=payload):
            problems = e_query_leetcode_graphql.fetch_solved_problems_features({"h": "1"})

        self.assertEqual(len(problems), 2)
        self.assertEqual(problems[0]["title"], "Two Sum")

    def test_fetch_solved_problems_features_returns_empty_when_total_missing(self):
        payload = {"data": {"problemsetQuestionList": {"questions": []}}}

        with patch.object(e_query_leetcode_graphql, "_post_graphql", return_value=payload):
            problems = e_query_leetcode_graphql.fetch_solved_problems_features({"h": "1"})

        self.assertEqual(problems, [])

    def test_login_and_get_csrf_returns_old_and_new_tokens(self):
        class FakeCookies:
            def __init__(self):
                self.values = {"CSRF_TOKEN": "initial-csrf", "LEETCODE_SESSION": "initial-session"}

            def get(self, key):
                return self.values.get(key)

        class FakeSession:
            def __init__(self):
                self.cookies = FakeCookies()

            def get(self, url):
                return FakeResponse(status_code=200)

            def post(self, url, json, headers):
                self.cookies.values["CSRF_TOKEN"] = "new-csrf"
                self.cookies.values["LEETCODE_SESSION"] = "new-session"
                return FakeResponse(status_code=200)

        with patch.object(e_query_leetcode_graphql.requests, "Session", return_value=FakeSession()):
            old_csrf, new_csrf, new_session = e_query_leetcode_graphql._login_and_get_csrf("jessie", "pw")

        self.assertEqual(old_csrf, "initial-csrf")
        self.assertEqual(new_csrf, "new-csrf")
        self.assertEqual(new_session, "new-session")


class CcClubExtractTests(unittest.TestCase):
    def test_get_session_and_headers_raises_when_env_missing(self):
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(EnvironmentError):
                e_crawler_ccClub._get_session_and_headers()

    def test_get_session_and_headers_logs_in_and_refreshes_csrf(self):
        class FakeCookies:
            def __init__(self):
                self.values = {"csrftoken": "initial-token"}

            def get(self, key):
                return self.values.get(key)

        class FakeSession:
            def __init__(self):
                self.cookies = FakeCookies()

            def get(self, url, timeout=30):
                return FakeResponse(status_code=200)

            def post(self, url, json, headers, timeout=30):
                self.cookies.values["csrftoken"] = "rotated-token"
                return FakeResponse(status_code=200)

        with (
            patch.dict(
                os.environ,
                {"CCCLUB_USERNAME": "jessie", "CCCLUB_PASSWORD": "pw"},
                clear=False,
            ),
            patch.object(e_crawler_ccClub.requests, "Session", return_value=FakeSession()),
        ):
            session, headers = e_crawler_ccClub._get_session_and_headers()

        self.assertIsNotNone(session)
        self.assertEqual(headers["X-CSRFToken"], "rotated-token")
        self.assertEqual(headers["Content-Type"], "application/json")

    def test_fetch_solved_problem_ids_merges_acm_and_oi_problems(self):
        profile_payload = {
            "data": {
                "acm_problems_status": {
                    "problems": {
                        "a": {"_id": "p1"},
                    }
                },
                "oi_problems_status": {
                    "problems": {
                        "b": {"_id": "p2", "score": 90},
                    }
                },
            }
        }

        class FakeSession:
            def get(self, url, headers=None, timeout=30):
                return FakeResponse(status_code=200, payload=profile_payload)

        problems = e_crawler_ccClub._fetch_solved_problem_ids(FakeSession(), {"h": "1"})

        self.assertEqual(
            problems,
            [
                {"problem_id": "p1", "problem_type": "ACM", "score": 0},
                {"problem_id": "p2", "problem_type": "OI", "score": 90},
            ],
        )

    def test_fetch_problem_detail_normalizes_difficulty(self):
        class FakeSession:
            def get(self, url, params=None, headers=None, timeout=30):
                return FakeResponse(
                    status_code=200,
                    payload={"data": {"tags": ["dp", "graph"], "difficulty": "Mid"}},
                )

        detail = e_crawler_ccClub._fetch_problem_detail("p1", FakeSession(), {"h": "1"})

        self.assertEqual(detail, {"topic": ["dp", "graph"], "difficulty": "Med."})

    def test_fetch_problem_detail_returns_empty_dict_on_404(self):
        class FakeSession:
            def get(self, url, params=None, headers=None, timeout=30):
                return FakeResponse(status_code=404, payload={})

        detail = e_crawler_ccClub._fetch_problem_detail("p404", FakeSession(), {"h": "1"})

        self.assertEqual(detail, {})

    def test_fetch_all_solved_problems_enriches_topic_and_difficulty(self):
        raw_problems = [
            {"problem_id": "p1", "problem_type": "ACM", "score": 0},
            {"problem_id": "p2", "problem_type": "OI", "score": 80},
        ]

        with (
            patch.object(e_crawler_ccClub, "_fetch_solved_problem_ids", return_value=raw_problems),
            patch.object(
                e_crawler_ccClub,
                "_fetch_problem_detail",
                side_effect=[
                    {"topic": ["array"], "difficulty": "Easy"},
                    {},
                ],
            ),
            patch.object(e_crawler_ccClub.time, "sleep") as sleep,
        ):
            problems = e_crawler_ccClub.fetch_all_solved_problems(
                session=object(),
                headers={"h": "1"},
                throttle_sec=0.1,
            )

        self.assertEqual(
            problems,
            [
                {
                    "problem_id": "p1",
                    "problem_type": "ACM",
                    "score": 0,
                    "topic": ["array"],
                    "difficulty": "Easy",
                },
                {
                    "problem_id": "p2",
                    "problem_type": "OI",
                    "score": 80,
                    "topic": ["Unknown"],
                    "difficulty": "Unknown",
                },
            ],
        )
        self.assertEqual(sleep.call_count, 2)


class LeetCodeTransformTests(unittest.TestCase):
    def test_build_problem_feat_documents_keeps_selected_fields(self):
        raw_solved = [
            {
                "frontendQuestionId": "1",
                "title": "Two Sum",
                "topicTags": [{"name": "Array"}, {"name": "Hash Table"}],
                "difficulty": "Easy",
            }
        ]

        docs = t_transform_leetcode.build_problem_feat_documents(raw_solved)

        self.assertEqual(
            docs,
            [
                {
                    "frontendQuestionId": "1",
                    "title": "Two Sum",
                    "topic": ["Array", "Hash Table"],
                    "difficulty": "Easy",
                }
            ],
        )

    def test_build_leetcode_summary_partial_counts_topics_and_keeps_stats(self):
        feature_docs = [
            {"topic": ["Array", "DP"], "difficulty": "Easy"},
            {"topic": ["Array"], "difficulty": "Med."},
        ]
        solved_problem_stats = [{"difficulty": "Easy", "count": 1}]

        summary = t_transform_leetcode.build_leetcode_summary_partial(feature_docs, solved_problem_stats)

        self.assertRegex(summary["snapshot_date"], r"^\d{4}-\d{2}-\d{2}$")
        self.assertEqual(summary["totalSolvedProblemsOnLeetcode"], 2)
        self.assertEqual(summary["problemDifficultyOnLeetcode"], solved_problem_stats)
        self.assertEqual(summary["topicsPercentOnLeetcode"], {"Array": 66.67, "DP": 33.33})

    def test_build_leetcode_summary_partial_returns_empty_when_features_empty_but_stats_nonzero(self):
        # cookies 過期時上游帶空 feature_docs，但 stats 仍反映有解題數，判定資料不一致，回傳空 dict
        feature_docs = []
        solved_problem_stats = [{"difficulty": "All", "count": 15}]

        summary = t_transform_leetcode.build_leetcode_summary_partial(feature_docs, solved_problem_stats)

        self.assertEqual(summary, {})


class CcClubTransformTests(unittest.TestCase):
    def test_build_ccclub_problem_documents_normalizes_missing_fields(self):
        raw_problems = [
            {"problem_id": "p1", "problem_type": "ACM"},
            {
                "problem_id": "p2",
                "problem_type": "OI",
                "score": 70,
                "topic": ["math"],
                "difficulty": "Hard",
            },
        ]

        docs = t_transform_ccClub.build_ccclub_problem_documents(raw_problems)

        self.assertEqual(
            docs,
            [
                {
                    "problem_id": "p1",
                    "problem_type": "ACM",
                    "score": 0,
                    "topic": ["Unknown"],
                    "difficulty": "Unknown",
                },
                {
                    "problem_id": "p2",
                    "problem_type": "OI",
                    "score": 70,
                    "topic": ["math"],
                    "difficulty": "Hard",
                },
            ],
        )

    def test_build_ccclub_summary_partial_aggregates_difficulty_and_topics(self):
        problem_docs = [
            {"difficulty": "Easy", "topic": ["array", "math"]},
            {"difficulty": "Easy", "topic": ["array"]},
            {"difficulty": "Hard", "topic": ["graph"]},
        ]

        summary = t_transform_ccClub.build_ccclub_summary_partial(problem_docs)

        self.assertRegex(summary["snapshot_date"], r"^\d{4}-\d{2}-\d{2}$")
        self.assertEqual(summary["totalSolvedProblemsOnCCclub"], 3)
        self.assertEqual(
            summary["problemDifficultyOnCCclub"],
            [
                {"difficulty": "Easy", "percentage": 66.67},
                {"difficulty": "Hard", "percentage": 33.33},
            ],
        )
        self.assertEqual(
            summary["topicsPercentOnCCclub"],
            {"array": 50.0, "math": 25.0, "graph": 25.0},
        )


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


class LeetCodeLoadTests(unittest.TestCase):
    def test_get_db_returns_named_database_from_client(self):
        fake_client = {"skill_library": object()}

        with patch.object(l_load_leetcode_doc_to_mongodb, "MongoClient", return_value=fake_client) as mongo:
            db = l_load_leetcode_doc_to_mongodb.get_db("mongodb://localhost:27017", "skill_library")

        mongo.assert_called_once_with("mongodb://localhost:27017")
        self.assertIs(db, fake_client["skill_library"])

    def test_upsert_leetcode_problems_builds_bulk_operations(self):
        db = FakeDb()
        docs = [
            {"frontendQuestionId": "1", "title": "Two Sum"},
            {"frontendQuestionId": "2", "title": "Add Two Numbers"},
        ]

        with patch.object(l_load_leetcode_doc_to_mongodb, "UpdateOne", FakeUpdateOne):
            l_load_leetcode_doc_to_mongodb.upsert_leetcode_problems(db, docs)

        collection = db.collections["solved_problems_on_leetcode"]
        self.assertEqual(len(collection.bulk_operations), 2)
        self.assertEqual(collection.bulk_operations[0].filter_doc, {"frontendQuestionId": "1"})
        self.assertEqual(collection.bulk_operations[0].update_doc, {"$set": docs[0]})
        self.assertTrue(collection.bulk_operations[0].upsert)

    def test_upsert_leetcode_summary_partial_uses_snapshot_date(self):
        db = FakeDb()
        summary = {"snapshot_date": "2026-05-05", "totalSolvedProblemsOnLeetcode": 2}

        l_load_leetcode_doc_to_mongodb.upsert_leetcode_summary_partial(db, summary)

        collection = db.collections["ccClub&leetcode_summary"]
        self.assertEqual(collection.update_filter, {"snapshot_date": "2026-05-05"})
        self.assertEqual(collection.update_doc, {"$set": summary})
        self.assertTrue(collection.update_upsert)

    def test_upsert_leetcode_summary_partial_skips_when_summary_empty(self):
        # 上游回傳空 dict（資料不一致）時，直接跳過 upsert，不觸碰 collection
        db = FakeDb()

        l_load_leetcode_doc_to_mongodb.upsert_leetcode_summary_partial(db, {})

        self.assertNotIn("ccClub&leetcode_summary", db.collections)


class CcClubLoadTests(unittest.TestCase):
    def test_get_db_returns_named_database_from_client(self):
        fake_client = {"skill_library": object()}

        with patch.object(l_load_ccClub_doc_to_mongodb, "MongoClient", return_value=fake_client) as mongo:
            db = l_load_ccClub_doc_to_mongodb.get_db("mongodb://localhost:27017", "skill_library")

        mongo.assert_called_once_with("mongodb://localhost:27017")
        self.assertIs(db, fake_client["skill_library"])

    def test_upsert_ccclub_problems_builds_bulk_operations(self):
        db = FakeDb()
        docs = [
            {"problem_id": "p1", "topic": ["array"]},
            {"problem_id": "p2", "topic": ["graph"]},
        ]

        with patch.object(l_load_ccClub_doc_to_mongodb, "UpdateOne", FakeUpdateOne):
            l_load_ccClub_doc_to_mongodb.upsert_ccclub_problems(db, docs)

        collection = db.collections["solved_problems_on_ccClub"]
        self.assertEqual(len(collection.bulk_operations), 2)
        self.assertEqual(collection.bulk_operations[0].filter_doc, {"problem_id": "p1"})
        self.assertEqual(collection.bulk_operations[0].update_doc, {"$set": docs[0]})
        self.assertTrue(collection.bulk_operations[0].upsert)

    def test_upsert_ccclub_summary_partial_uses_snapshot_date(self):
        db = FakeDb()
        summary = {"snapshot_date": "2026-05-05", "totalSolvedProblemsOnCCclub": 2}

        l_load_ccClub_doc_to_mongodb.upsert_ccclub_summary_partial(db, summary)

        collection = db.collections["ccClub&leetcode_summary"]
        self.assertEqual(collection.update_filter, {"snapshot_date": "2026-05-05"})
        self.assertEqual(collection.update_doc, {"$set": summary})
        self.assertTrue(collection.update_upsert)


class Task03MainTests(unittest.TestCase):
    def test_run_task03_leetcode_executes_full_pipeline(self):
        raw_features = [{"frontendQuestionId": "1"}]
        raw_stats = [{"difficulty": "Easy", "count": 1}]
        feature_docs = [{"frontendQuestionId": "1", "title": "Two Sum"}]
        summary = {"snapshot_date": "2026-05-05", "totalSolvedProblemsOnLeetcode": 1}
        db = object()

        with (
            patch.dict(
                os.environ,
                {
                    "LEETCODE_USERNAME": "jessie",
                    "LEETCODE_SESSION": "session-token",
                    "CSRF_TOKEN": "csrf-token",
                    "MONGO_ALTAS_URI": "mongodb://localhost:27017",
                    "MONGO_DB_NAME": "skill_library",
                },
                clear=False,
            ),
            patch.object(main, "_get_headers", return_value={"h": "1"}) as get_headers,
            patch.object(main, "fetch_solved_problems_features", return_value=raw_features) as fetch_features,
            patch.object(main, "fetch_solved_problem_stats", return_value=raw_stats) as fetch_stats,
            patch.object(main, "build_problem_feat_documents", return_value=feature_docs) as build_docs,
            patch.object(main, "build_leetcode_summary_partial", return_value=summary) as build_summary,
            patch.object(main, "get_db", return_value=db) as get_db,
            patch.object(main, "upsert_leetcode_problems") as upsert_problems,
            patch.object(main, "upsert_leetcode_summary_partial") as upsert_summary,
        ):
            main.run_task03_leetcode()

        get_headers.assert_called_once_with("csrf-token", "session-token", "jessie")
        fetch_features.assert_called_once_with({"h": "1"})
        fetch_stats.assert_called_once_with({"h": "1"}, "jessie")
        build_docs.assert_called_once_with(raw_features)
        build_summary.assert_called_once_with(feature_docs, raw_stats)
        get_db.assert_called_once_with("mongodb://localhost:27017", "skill_library")
        upsert_problems.assert_called_once_with(db, feature_docs)
        upsert_summary.assert_called_once_with(db, summary)

    def test_run_task03_leetcode_raises_when_required_env_vars_are_missing(self):
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(EnvironmentError):
                main.run_task03_leetcode()

    def test_run_task03_ccclub_executes_full_pipeline(self):
        raw_problems = [{"problem_id": "p1"}]
        problem_docs = [{"problem_id": "p1", "topic": ["array"]}]
        summary = {"snapshot_date": "2026-05-05", "totalSolvedProblemsOnCCclub": 1}
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
            patch.object(main, "_get_session_and_headers", return_value=(object(), {"h": "1"})) as get_session,
            patch.object(main, "fetch_all_solved_problems", return_value=raw_problems) as fetch_all,
            patch.object(main, "build_ccclub_problem_documents", return_value=problem_docs) as build_docs,
            patch.object(main, "build_ccclub_summary_partial", return_value=summary) as build_summary,
            patch.object(main, "get_db", return_value=db) as get_db,
            patch.object(main, "upsert_ccclub_problems") as upsert_problems,
            patch.object(main, "upsert_ccclub_summary_partial") as upsert_summary,
        ):
            main.run_task03_ccclub()

        session_obj = get_session.return_value[0]
        get_session.assert_called_once_with()
        fetch_all.assert_called_once_with(session_obj, {"h": "1"})
        build_docs.assert_called_once_with(raw_problems)
        build_summary.assert_called_once_with(problem_docs)
        get_db.assert_called_once_with("mongodb://localhost:27017", "skill_library")
        upsert_problems.assert_called_once_with(db, problem_docs)
        upsert_summary.assert_called_once_with(db, summary)

    def test_run_task03_ccclub_raises_when_required_env_vars_are_missing(self):
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(EnvironmentError):
                main.run_task03_ccclub()


if __name__ == "__main__":
    unittest.main()
