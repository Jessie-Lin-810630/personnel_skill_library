import os
import unittest
from types import SimpleNamespace
from unittest.mock import mock_open, patch

import pandas as pd
from pandas.testing import assert_frame_equal

from task05_googlesheet_skill_etl import e_fetch_google_sheet
from task05_googlesheet_skill_etl import l_load_to_mongodb
from task05_googlesheet_skill_etl import main
from task05_googlesheet_skill_etl import t_transform_skills


class GoogleSheetExtractTests(unittest.TestCase):
    def test_get_google_sheet_client_reads_service_account_file_and_authorizes(self):
        fake_client = object()

        with patch("builtins.open", mock_open(read_data='{"type":"service_account"}')) as mocked_open, patch.object(
            e_fetch_google_sheet.pygsheets, "authorize", return_value=fake_client
        ) as authorize:
            client = e_fetch_google_sheet.get_google_sheet_client("/tmp/creds.json")

        mocked_open.assert_called_once_with("/tmp/creds.json", "r")
        authorize.assert_called_once_with(service_account_json='{"type":"service_account"}')
        self.assertIs(client, fake_client)

    def test_open_spreadsheet_get_worksheet_returns_dataframe(self):
        expected_df = pd.DataFrame([{"skill": "python"}])
        worksheet = SimpleNamespace(get_as_df=lambda numeric=False: expected_df)
        spreadsheet = SimpleNamespace(
            title="Personal Skill Radar Calculation",
            worksheet=lambda mode, title: worksheet,
        )
        client = SimpleNamespace(open=lambda title: spreadsheet)

        result_df = e_fetch_google_sheet.open_spreadsheet_get_worksheet(
            client, "Personal Skill Radar Calculation", "生技"
        )

        assert_frame_equal(result_df, expected_df)

    def test_open_spreadsheet_get_worksheet_raises_when_spreadsheet_missing(self):
        client = SimpleNamespace(
            open=lambda title: (_ for _ in ()).throw(e_fetch_google_sheet.pygsheets.SpreadsheetNotFound())
        )

        with self.assertRaises(e_fetch_google_sheet.pygsheets.SpreadsheetNotFound):
            e_fetch_google_sheet.open_spreadsheet_get_worksheet(
                client, "Personal Skill Radar Calculation", "生技"
            )

    def test_open_spreadsheet_get_worksheet_raises_when_worksheet_missing(self):
        spreadsheet = SimpleNamespace(
            title="Personal Skill Radar Calculation",
            worksheet=lambda mode, title: (_ for _ in ()).throw(
                e_fetch_google_sheet.pygsheets.WorksheetNotFound()
            ),
        )
        client = SimpleNamespace(open=lambda title: spreadsheet)

        with self.assertRaises(e_fetch_google_sheet.pygsheets.WorksheetNotFound):
            e_fetch_google_sheet.open_spreadsheet_get_worksheet(
                client, "Personal Skill Radar Calculation", "生技"
            )


class SkillTransformTests(unittest.TestCase):
    def test_build_biotech_task_docs_filters_axes_and_calculates_scores(self):
        df = pd.DataFrame(
            [
                {
                    "雷達軸": "流程設計能力",
                    "經手任務": "task-a",
                    "複雜性 - 純紀錄": "Y",
                    "複雜性 - 執行操作": "",
                    "複雜性 - 制定方向": "Y",
                    "複雜性 - 優化與故障排除": "",
                    "獨立性 - 需要指導後才能照規章做": "",
                    "獨立性 - 不需指導即可理解並遵照組織規章做": "Y",
                    "獨立性 - 自訂架構": "",
                    "影響力 - 具備公司外出教學經驗": "",
                    "影響力 - 具備跨部門教學經驗": "Y",
                    "影響力 - 具備部門內教學經驗": "",
                    "影響力 -  不具備教學的經驗": "",
                },
                {
                    "雷達軸": "不在範圍",
                    "經手任務": "task-b",
                    "複雜性 - 純紀錄": "Y",
                    "複雜性 - 執行操作": "",
                    "複雜性 - 制定方向": "",
                    "複雜性 - 優化與故障排除": "",
                    "獨立性 - 需要指導後才能照規章做": "",
                    "獨立性 - 不需指導即可理解並遵照組織規章做": "",
                    "獨立性 - 自訂架構": "",
                    "影響力 - 具備公司外出教學經驗": "",
                    "影響力 - 具備跨部門教學經驗": "",
                    "影響力 - 具備部門內教學經驗": "",
                    "影響力 -  不具備教學的經驗": "",
                },
            ]
        )

        result = t_transform_skills.build_biotech_task_docs(df, ["流程設計能力"])

        self.assertEqual(len(result), 1)
        row = result.iloc[0]
        self.assertEqual(row["複雜性總分"], 4)
        self.assertEqual(row["獨立性總分"], 5)
        self.assertEqual(row["影響力總分"], 5)
        self.assertEqual(row["單項任務總分"], 19)

    def test_build_de_task_docs_filters_axes_and_calculates_scores(self):
        df = pd.DataFrame(
            [
                {
                    "雷達軸": "Orchestration",
                    "經手任務": "task-a",
                    "複雜性 - 純紀錄與理解": "",
                    "複雜性 - 開發測試": "Y",
                    "複雜性 - 接手部署": "",
                    "複雜性 - 優化與故障排除": "Y",
                    "獨立性 - 需要指導後才能照規章做": "Y",
                    "獨立性 - 不需指導即可理解並遵照組織規章做": "",
                    "獨立性 - 自訂架構": "Y",
                    "影響力 - 具備公司外出教學經驗": "",
                    "影響力 - 具備跨部門教學經驗": "",
                    "影響力 - 具備部門內教學經驗": "Y",
                    "影響力 -  不具備教學的經驗": "",
                }
            ]
        )

        result = t_transform_skills.build_de_task_docs(df, ["Orchestration"])

        row = result.iloc[0]
        self.assertEqual(row["複雜性總分"], 6)
        self.assertEqual(row["獨立性總分"], 10)
        self.assertEqual(row["影響力總分"], 1)
        self.assertEqual(row["單項任務總分"], 27)

    def test_build_summary_for_radar_groups_scores_and_assigns_level(self):
        df = pd.DataFrame(
            [
                {"雷達軸": "流程設計能力", "經手任務": "task-a", "單項任務總分": 10},
                {"雷達軸": "流程設計能力", "經手任務": "task-b", "單項任務總分": 12},
                {"雷達軸": "文件撰寫能力", "經手任務": "task-c", "單項任務總分": 4},
            ]
        )

        result = t_transform_skills.build_summary_for_radar(df, "雷達圖1生技")

        self.assertEqual(list(result["雷達圖名稱"].unique()), ["雷達圖1生技"])
        self.assertEqual(set(result["雷達軸"]), {"流程設計能力", "文件撰寫能力"})

        top_row = result.iloc[0]
        self.assertEqual(top_row["雷達軸"], "流程設計能力")
        self.assertEqual(top_row["經手任務個數"], 2)
        self.assertEqual(top_row["各軸向任務最高分"], 12)
        self.assertEqual(top_row["任務經驗值"], 1.0)
        self.assertEqual(top_row["單軸總分"], 13.0)
        self.assertEqual(top_row["level"], 3)

    def test_build_combined_summaries_concatenates_dataframes(self):
        df1 = pd.DataFrame([{"雷達軸": "A", "單軸總分": 10}])
        df2 = pd.DataFrame([{"雷達軸": "B", "單軸總分": 12}])

        combined = t_transform_skills.build_combined_summaries([df1, df2])

        self.assertEqual(len(combined), 2)
        self.assertEqual(list(combined["雷達軸"]), ["A", "B"])


class FakeCollection:
    def __init__(self):
        self.bulk_operations = None

    def bulk_write(self, operations):
        self.bulk_operations = operations
        return SimpleNamespace(upserted_count=1, modified_count=2)


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


class SkillLoadTests(unittest.TestCase):
    def test_get_db_returns_named_database_from_client(self):
        fake_client = {"skill_library": object()}

        with patch.object(l_load_to_mongodb, "MongoClient", return_value=fake_client) as mongo:
            db = l_load_to_mongodb.get_db("mongodb://localhost:27017", "skill_library")

        mongo.assert_called_once_with("mongodb://localhost:27017")
        self.assertIs(db, fake_client["skill_library"])

    def test_upsert_skill_scores_builds_operations_by_radar_axis(self):
        db = FakeDb()
        df = pd.DataFrame(
            [
                {"雷達軸": "流程設計能力", "單軸總分": 13.0},
                {"雷達軸": "文件撰寫能力", "單軸總分": 4.0},
            ]
        )

        with patch.object(l_load_to_mongodb, "UpdateOne", FakeUpdateOne):
            l_load_to_mongodb.upsert_skill_scores(db, "skill_scores_biotech", df)

        collection = db.collections["skill_scores_biotech"]
        self.assertEqual(len(collection.bulk_operations), 2)
        self.assertEqual(collection.bulk_operations[0].filter_doc, {"雷達軸": "流程設計能力"})
        self.assertEqual(
            collection.bulk_operations[0].update_doc,
            {"$set": {"雷達軸": "流程設計能力", "單軸總分": 13.0}},
        )
        self.assertTrue(collection.bulk_operations[0].upsert)

    def test_upsert_skill_radar_summary_builds_composite_key_operations(self):
        db = FakeDb()
        df = pd.DataFrame(
            [
                {
                    "snapshot_date": "2026-05-09",
                    "雷達軸": "流程設計能力",
                    "雷達圖名稱": "雷達圖1生技",
                    "單軸總分": 13.0,
                }
            ]
        )

        with patch.object(l_load_to_mongodb, "UpdateOne", FakeUpdateOne):
            l_load_to_mongodb.upsert_skill_radar_summary(db, df)

        collection = db.collections["skill_radar_summary"]
        self.assertEqual(len(collection.bulk_operations), 1)
        self.assertEqual(
            collection.bulk_operations[0].filter_doc,
            {
                "snapshot_date": "2026-05-09",
                "雷達軸": "流程設計能力",
                "雷達圖名稱": "雷達圖1生技",
            },
        )
        self.assertTrue(collection.bulk_operations[0].upsert)


class Task05MainTests(unittest.TestCase):
    def test_run_task05_executes_extract_transform_load_pipeline(self):
        fake_client = object()
        df_biotech = pd.DataFrame([{"雷達軸": "流程設計能力"}])
        df_de = pd.DataFrame([{"雷達軸": "Orchestration"}])
        df_biotech_stats = pd.DataFrame([{"雷達軸": "流程設計能力", "單項任務總分": 19}])
        df_de_stats = pd.DataFrame([{"雷達軸": "Orchestration", "單項任務總分": 27}])
        df_summary_1 = pd.DataFrame([{"雷達軸": "流程設計能力", "雷達圖名稱": "雷達圖1生技"}])
        df_summary_2 = pd.DataFrame([{"雷達軸": "Orchestration", "雷達圖名稱": "雷達圖2資料工程"}])
        df_both_summary = pd.DataFrame([{"雷達軸": "流程設計能力"}, {"雷達軸": "Orchestration"}])
        db = object()

        with patch.dict(
            os.environ,
            {
                "GS_CREDENTIAL_FILE_PATH": "/tmp/creds.json",
                "MONGO_URI": "mongodb://localhost:27017",
                "MONGO_DB_NAME": "skill_library",
            },
            clear=False,
        ), patch.object(main, "get_google_sheet_client", return_value=fake_client) as get_client, patch.object(
            main,
            "open_spreadsheet_get_worksheet",
            side_effect=[df_biotech, df_de],
        ) as open_worksheet, patch.object(
            main, "build_biotech_task_docs", return_value=df_biotech_stats
        ) as build_biotech, patch.object(
            main, "build_de_task_docs", return_value=df_de_stats
        ) as build_de, patch.object(
            main, "build_summary_for_radar", side_effect=[df_summary_1, df_summary_2]
        ) as build_summary, patch.object(
            main, "build_combined_summaries", return_value=df_both_summary
        ) as combine_summaries, patch.object(
            main, "get_db", return_value=db
        ) as get_db, patch.object(
            main, "upsert_skill_scores"
        ) as upsert_scores, patch.object(
            main, "upsert_skill_radar_summary"
        ) as upsert_summary:
            main.run_task05()

        get_client.assert_called_once_with("/tmp/creds.json")
        self.assertEqual(open_worksheet.call_count, 2)
        build_biotech.assert_called_once_with(df_biotech, main.BIOTECH_RADAR_LABELS)
        build_de.assert_called_once_with(df_de, main.DE_RADER_LABELS)
        self.assertEqual(build_summary.call_count, 2)
        first_summary_args = build_summary.call_args_list[0].args
        second_summary_args = build_summary.call_args_list[1].args
        assert_frame_equal(first_summary_args[0], df_biotech_stats)
        self.assertEqual(first_summary_args[1], "雷達圖1生技")
        assert_frame_equal(second_summary_args[0], df_de_stats)
        self.assertEqual(second_summary_args[1], "雷達圖2資料工程")
        combine_summaries.assert_called_once_with([df_summary_1, df_summary_2])
        get_db.assert_called_once_with("mongodb://localhost:27017", "skill_library")
        self.assertEqual(upsert_scores.call_count, 2)
        first_upsert_args = upsert_scores.call_args_list[0].args
        second_upsert_args = upsert_scores.call_args_list[1].args
        self.assertEqual(first_upsert_args[:2], (db, "skill_scores_biotech"))
        assert_frame_equal(first_upsert_args[2], df_biotech_stats)
        self.assertEqual(second_upsert_args[:2], (db, "skill_scores_data_eng"))
        assert_frame_equal(second_upsert_args[2], df_de_stats)
        upsert_summary.assert_called_once_with(db, df_both_summary)

    def test_run_task05_raises_when_required_env_vars_are_missing(self):
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(EnvironmentError):
                main.run_task05()


if __name__ == "__main__":
    unittest.main()
