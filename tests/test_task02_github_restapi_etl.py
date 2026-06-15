from task02_github_restapi_etl import t_transform_github
from task02_github_restapi_etl import main
from task02_github_restapi_etl import l_load_to_mongodb
from task02_github_restapi_etl import e_request_github_api
import base64
import os
import requests
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


PROJECT_ROOT = Path(__file__).resolve().parents[1]
TASK_DIR = PROJECT_ROOT / "task02_github_restapi_etl"
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(TASK_DIR))


class FakeResponse:
    def __init__(self, status_code=200, payload=None, headers=None):
        self.status_code = status_code
        self._payload = payload if payload is not None else []
        self.headers = headers or {}

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"HTTP {self.status_code}")


class GithubExtractTests(unittest.TestCase):
    def test_get_headers_builds_github_headers(self):
        headers = e_request_github_api._get_headers("token-123", "jessie")

        self.assertEqual(headers["Authorization"], "Bearer token-123")
        self.assertEqual(headers["Accept"], "application/vnd.github+json")
        self.assertEqual(headers["X-GitHub-Api-Version"], "2026-03-10")
        self.assertEqual(headers["User-Agent"], "jessie")

    def test_check_and_wait_rate_limit_uses_retry_after_first(self):
        response = FakeResponse(headers={"retry-after": "7"})

        with patch.object(e_request_github_api.time, "sleep") as sleep:
            e_request_github_api._check_and_wait_rate_limit(response)

        sleep.assert_called_once_with(7)

    def test_check_and_wait_rate_limit_waits_until_reset_when_buffer_is_low(self):
        response = FakeResponse(
            headers={"x-ratelimit-remaining": "3", "x-ratelimit-reset": "120"}
        )
        fake_now = datetime.fromtimestamp(100, tz=timezone.utc)

        with patch.object(e_request_github_api.time, "sleep") as sleep, patch.object(
            e_request_github_api, "datetime"
        ) as fake_datetime:
            fake_datetime.now.return_value = fake_now
            fake_datetime.fromtimestamp.side_effect = datetime.fromtimestamp
            e_request_github_api._check_and_wait_rate_limit(response, rate_limit_buffer=5)

        sleep.assert_called_once_with(25)

    def test_paginate_collects_all_pages(self):
        responses = [
            FakeResponse(status_code=200, payload=[{"id": 1}], headers={}),
            FakeResponse(status_code=200, payload=[{"id": 2}], headers={}),
            FakeResponse(status_code=200, payload=[], headers={}),
        ]

        with patch.object(
            e_request_github_api.requests, "get", side_effect=responses
        ) as request_get, patch.object(
            e_request_github_api, "_check_and_wait_rate_limit"
        ) as check_rate_limit:
            results = e_request_github_api._paginate(
                "https://api.github.com/user/repos", {"Authorization": "Bearer token"}
            )

        self.assertEqual(results, [{"id": 1}, {"id": 2}])
        self.assertEqual(request_get.call_count, 3)
        self.assertEqual(check_rate_limit.call_count, 3)

    def test_paginate_retries_after_rate_limit_response(self):
        responses = [
            FakeResponse(status_code=403, payload=[], headers={}),
            FakeResponse(status_code=200, payload=[{"id": 1}], headers={}),
            FakeResponse(status_code=200, payload=[], headers={}),
        ]

        with patch.object(
            e_request_github_api.requests, "get", side_effect=responses
        ) as request_get, patch.object(
            e_request_github_api, "_check_and_wait_rate_limit"
        ), patch.object(e_request_github_api.time, "sleep") as sleep:
            results = e_request_github_api._paginate(
                "https://api.github.com/user/repos", {"Authorization": "Bearer token"}
            )

        self.assertEqual(results, [{"id": 1}])
        self.assertEqual(request_get.call_count, 3)
        sleep.assert_called_once_with(300)

    def test_fetch_repos_calls_paginate(self):
        with patch.object(
            e_request_github_api, "_paginate", return_value=[{"id": 1}, {"id": 2}]
        ) as paginate:
            repos = e_request_github_api.fetch_repos({"Authorization": "Bearer token"})

        paginate.assert_called_once_with(
            "https://api.github.com/user/repos", {"Authorization": "Bearer token"}
        )
        self.assertEqual(repos, [{"id": 1}, {"id": 2}])

    def test_fetch_a_repo_commits_calls_paginate_with_repo_url(self):
        with patch.object(
            e_request_github_api, "_paginate", return_value=[{"sha": "abc123"}]
        ) as paginate:
            commits = e_request_github_api.fetch_a_repo_commits(
                "octocat", "hello-world", {"Authorization": "Bearer token"}, ["main"]
            )

        paginate.assert_called_once_with(
            "https://api.github.com/repos/octocat/hello-world/commits",
            {"Authorization": "Bearer token"},
            {"sha": "main"},
            timeout=30,
        )
        self.assertEqual(commits, [{"sha": "abc123"}])

    def test_fetch_a_repo_readme_returns_decoded_summary(self):
        content = base64.b64encode("README body for test".encode("utf-8")).decode("utf-8")
        response = FakeResponse(
            status_code=200,
            payload={
                "html_url": "https://github.com/octocat/hello-world/blob/main/README.md",
                "content": content,
            },
        )

        with patch.object(e_request_github_api.requests, "get", return_value=response) as request_get:
            readme = e_request_github_api.fetch_a_repo_readme(
                "octocat", "hello-world", {"Authorization": "Bearer token"}, returned_max_chars=10
            )

        request_get.assert_called_once_with(
            "https://api.github.com/repos/octocat/hello-world/readme",
            headers={"Authorization": "Bearer token"},
            timeout=10,
        )
        self.assertEqual(
            readme["readme_html_url"],
            "https://github.com/octocat/hello-world/blob/main/README.md",
        )
        self.assertEqual(readme["readme_summary"], "README bod")

    def test_fetch_a_repo_readme_returns_empty_string_when_not_found(self):
        response = FakeResponse(status_code=404, payload={})

        with patch.object(e_request_github_api.requests, "get", return_value=response):
            readme = e_request_github_api.fetch_a_repo_readme(
                "octocat", "hello-world", {"Authorization": "Bearer token"}
            )

        self.assertEqual(readme, {"readme_html_url": "", "readme_summary": ""})


class GithubTransformTests(unittest.TestCase):
    def test_build_repo_document_normalizes_repo_fields(self):
        raw_repo = {
            "id": 10,
            "name": "hello-world",
            "full_name": "jessie/hello-world",
            "description": "demo repo",
            "language": None,
            "private": False,
            "owner": {"login": "jessie"},
            "created_at": "2026-04-01T00:00:00Z",
            "pushed_at": "2026-04-20T12:00:00Z",
            "stargazers_count": 8,
            "topics": ["python", "etl"],
        }
        raw_commits = [
            {
                "sha": "abcdef123456",
                "commit": {
                    "message": "initial commit",
                    "author": {"date": "2026-04-20T12:00:00Z"},
                    "committer": {"email": "jessie@example.com"},
                },
            }
        ]
        raw_readme = {
            "readme_summary": "hello readme",
            "readme_html_url": "https://github.com/jessie/hello-world/blob/main/README.md",
        }

        repo_doc = t_transform_github.build_repo_document(
            raw_repo, "jessie", "jessie@example.com", raw_commits, raw_readme
        )

        self.assertEqual(repo_doc["repo_id"], 10)
        self.assertEqual(repo_doc["repo_name"], "hello-world")
        self.assertEqual(repo_doc["language"], "others")
        self.assertEqual(repo_doc["role"], "owner")
        self.assertEqual(repo_doc["commit_counts"], 1)
        self.assertEqual(
            repo_doc["commits"],
            [
                {
                    "sha": "abcdef1",
                    "message": "initial commit",
                    "committed_at": "2026-04-20T12:00:00Z",
                }
            ],
        )
        self.assertEqual(repo_doc["readme_summary"], "hello readme")
        self.assertEqual(
            repo_doc["readme_url"],
            "https://github.com/jessie/hello-world/blob/main/README.md",
        )
        self.assertEqual(repo_doc["fetched_at"].tzinfo, timezone.utc)

    def test_build_repo_document_marks_collaborator_when_owner_differs(self):
        raw_repo = {
            "id": 20,
            "name": "shared-repo",
            "full_name": "team/shared-repo",
            "private": True,
            "owner": {"login": "team"},
            "created_at": "2026-04-01T00:00:00Z",
        }

        repo_doc = t_transform_github.build_repo_document(raw_repo, "jessie", "", [], {})

        self.assertEqual(repo_doc["role"], "collaborator")
        self.assertEqual(repo_doc["language"], "others")
        self.assertEqual(repo_doc["topics"], [])
        self.assertEqual(repo_doc["commit_counts"], 0)

    def test_build_summary_document_aggregates_roles_languages_and_recent_repos(self):
        all_repo_docs = [
            {
                "repo_name": "alpha",
                "role": "owner",
                "language": "Python",
                "commit_counts": 5,
                "pushed_at": "2026-04-21T10:00:00Z",
                "description": "alpha desc",
            },
            {
                "repo_name": "beta",
                "role": "collaborator",
                "language": "Go",
                "commit_counts": 2,
                "pushed_at": "2026-04-25T10:00:00Z",
                "description": "beta desc",
            },
            {
                "repo_name": "gamma",
                "role": "owner",
                "language": "Python",
                "commit_counts": 7,
                "pushed_at": None,
                "description": "gamma desc",
            },
            {
                "repo_name": "delta",
                "role": "owner",
                "language": "Rust",
                "commit_counts": 1,
                "pushed_at": "2026-04-24T10:00:00Z",
                "description": "delta desc",
            },
        ]

        summary = t_transform_github.build_summary_document(all_repo_docs)

        self.assertRegex(summary["snapshot_date"], r"^\d{4}-\d{2}-\d{2}$")
        self.assertEqual(summary["total_repos"], 4)
        self.assertEqual(summary["by_role"], {"owner": 3, "collaborator": 1})
        self.assertEqual(summary["by_language"], {"Python": 2, "Go": 1, "Rust": 1})
        self.assertEqual(summary["total_commits"], 15)
        self.assertEqual(
            summary["recent_three_repos"],
            [
                {
                    "repo_name": "beta",
                    "pushed_at": "2026-04-25T10:00:00Z",
                    "language": "Go",
                    "description": "beta desc",
                },
                {
                    "repo_name": "delta",
                    "pushed_at": "2026-04-24T10:00:00Z",
                    "language": "Rust",
                    "description": "delta desc",
                },
                {
                    "repo_name": "alpha",
                    "pushed_at": "2026-04-21T10:00:00Z",
                    "language": "Python",
                    "description": "alpha desc",
                },
            ],
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


class GithubLoadTests(unittest.TestCase):
    def test_get_db_returns_named_database_from_client(self):
        fake_client = {"skill_library": object()}

        with patch.object(l_load_to_mongodb, "MongoClient", return_value=fake_client) as mongo:
            db = l_load_to_mongodb.get_db("mongodb://localhost:27017", "skill_library")

        mongo.assert_called_once_with("mongodb://localhost:27017")
        self.assertIs(db, fake_client["skill_library"])

    def test_upsert_repos_builds_bulk_operations_by_repo_id(self):
        db = FakeDb()
        docs = [{"repo_id": 1, "repo_name": "alpha"}, {"repo_id": 2, "repo_name": "beta"}]

        with patch.object(l_load_to_mongodb, "UpdateOne", FakeUpdateOne):
            l_load_to_mongodb.upsert_repos(db, docs)

        collection = db.collections["github_repos"]
        self.assertEqual(len(collection.bulk_operations), 2)
        self.assertEqual(collection.bulk_operations[0].filter_doc, {"repo_id": 1})
        self.assertEqual(collection.bulk_operations[0].update_doc, {"$set": docs[0]})
        self.assertTrue(collection.bulk_operations[0].upsert)

    def test_upsert_repo_summary_uses_snapshot_date(self):
        db = FakeDb()
        summary = {"snapshot_date": "2026-04-29", "total_repos": 4}

        l_load_to_mongodb.upsert_repo_summary(db, summary)

        collection = db.collections["github_summary"]
        self.assertEqual(collection.update_filter, {"snapshot_date": "2026-04-29"})
        self.assertEqual(collection.update_doc, {"$set": summary})
        self.assertTrue(collection.update_upsert)


class GithubMainTests(unittest.TestCase):
    def test_run_task02_executes_full_etl_pipeline(self):
        raw_repos = [
            {"name": "alpha", "owner": {"login": "jessie"}},
            {"name": "beta", "owner": {"login": "team"}},
        ]
        repo_docs = [{"repo_id": 1}, {"repo_id": 2}]
        summary = {"snapshot_date": "2026-04-29", "total_repos": 2}
        db = object()

        with patch.dict(
            os.environ,
            {
                "GITHUB_TOKEN": "token-123",
                "GITHUB_USERNAME": "jessie",
                "GITHUB_MAIL": "jessie@example.com",
                "MONGO_URI": "mongodb://localhost:27017",
                "MONGO_DB_NAME": "skill_library",
            },
            clear=False,
        ), patch.object(main, "_get_headers", return_value={"Authorization": "Bearer token-123"}) as get_headers, patch.object(
            main, "fetch_repos", return_value=raw_repos
        ) as fetch_repos, patch.object(
            main, "fetch_all_branches", side_effect=[["main"], ["main"]]
        ) as fetch_all_branches, patch.object(
            main, "fetch_a_repo_commits", side_effect=[["c1"], ["c2"]]
        ) as fetch_commits, patch.object(
            main, "fetch_a_repo_readme", side_effect=[{"readme_summary": "a"}, {"readme_summary": "b"}]
        ) as fetch_readme, patch.object(
            main, "build_repo_document", side_effect=repo_docs
        ) as build_repo_document, patch.object(
            main, "build_summary_document", return_value=summary
        ) as build_summary_document, patch.object(
            main, "get_db", return_value=db
        ) as get_db, patch.object(
            main, "upsert_repos"
        ) as upsert_repos, patch.object(
            main, "upsert_repo_summary"
        ) as upsert_repo_summary:
            main.run_task02()

        get_headers.assert_called_once_with("token-123", "jessie")
        fetch_repos.assert_called_once_with({"Authorization": "Bearer token-123"})
        self.assertEqual(fetch_all_branches.call_count, 2)
        self.assertEqual(fetch_commits.call_count, 2)
        self.assertEqual(fetch_readme.call_count, 2)
        self.assertEqual(build_repo_document.call_count, 2)
        build_repo_document.assert_any_call(
            raw_repos[0], "jessie", "jessie@example.com", ["c1"], {"readme_summary": "a"}
        )
        build_repo_document.assert_any_call(
            raw_repos[1], "jessie", "jessie@example.com", ["c2"], {"readme_summary": "b"}
        )
        build_summary_document.assert_called_once_with(repo_docs)
        get_db.assert_called_once_with("mongodb://localhost:27017", "skill_library")
        upsert_repos.assert_called_once_with(db, repo_docs)
        upsert_repo_summary.assert_called_once_with(db, summary)

    def test_run_task02_raises_when_required_env_vars_are_missing(self):
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(EnvironmentError):
                main.run_task02()


if __name__ == "__main__":
    unittest.main()
