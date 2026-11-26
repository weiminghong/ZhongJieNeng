import csv
import unittest
from fastapi.testclient import TestClient
from tests import test_learning as fixtures
from cecep_console import learning as ml, public_data, workbench_context as wb
from cecep_console.api import create_app
from cecep_console.storage_demo import seed_demo


class WorkspaceReadinessTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.LearningTests()
        self.fixture.setUp()
        self.store = self.fixture.store
        seed_demo(self.store)
        _, self.models = self.fixture.trained()

    def tearDown(self):
        self.fixture.tearDown()

    def modify(self, change):
        with self.fixture.csv.open(encoding="utf-8", newline="") as stream:
            reader = csv.DictReader(stream)
            columns = reader.fieldnames
            rows = list(reader)
        for i, row in enumerate(rows):
            change(i, row)
        with self.fixture.csv.open("w", encoding="utf-8", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=columns)
            writer.writeheader()
            writer.writerows(rows)
        public_data._load.cache_clear()

    def get(self, **params):
        with TestClient(create_app()) as client:
            response = client.get("/api/v1/workspace/data-readiness", params=dict(
                source_key="market:shandong", trading_date="2024-02-27", **params))
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def test_missing_target_actuals_do_not_block_day_ahead_inference(self):
        self.modify(lambda i, row: row.update({"实时价格":""}) if row["日期"] == "2024-02-27" else None)
        before = self.store.db.execute("SELECT count(*) FROM ml_object").fetchone()[0]
        result = self.get(model_id=self.models[0])
        self.assertTrue(result["prediction_inputs"]["can_predict"])
        self.assertEqual(result["observations"]["actual_periods"], 0)
        self.assertEqual(result["observations"]["missing_periods"], 96)
        self.assertFalse(result["settlement"]["can_settle"])
        self.assertEqual(before, self.store.db.execute("SELECT count(*) FROM ml_object").fetchone()[0])

    def test_native_hour_end_da_values_count_as_24_valid_hours(self):
        self.modify(lambda i, row: row.update({"日前价格":""}) if i % 4 != 3 else None)
        result = self.get(task_id="da_price_reference")
        self.assertEqual(result["observations"]["expected_periods"], 24)
        self.assertEqual(result["observations"]["actual_periods"], 24)
        self.assertEqual(result["observations"]["missing_periods"], 0)
        self.assertEqual(result["source_details"][0]["valid"], 24)
        self.assertEqual(result["settlement"]["data_hours"], 24)

    def test_incomplete_rt_hour_is_excluded_and_replay_masks_future_labels(self):
        self.modify(lambda i, row: row.update({"实时价格":""}) if row["日期"] == "2024-02-27" and i % 96 == 1 else None)
        result = self.get(task_id="prebid_spread_reference", mode="replay", until="12:00")
        self.assertEqual(result["observations"]["expected_periods"], 24)
        self.assertEqual(result["observations"]["actual_periods"], 11)
        self.assertEqual(result["observations"]["missing_periods"], 1)
        self.assertEqual(result["observations"]["pending_periods"], 12)
        self.assertEqual(result["settlement"]["data_hours"], 11)
        self.assertEqual(result["source_details"][1]["valid"], 11)

    def test_training_boundary_blocks_early_prediction_and_station_keeps_own_inputs(self):
        with TestClient(create_app()) as client:
            early = client.get("/api/v1/workspace/data-readiness", params=dict(
                source_key="market:shandong", trading_date="2024-01-20", model_id=self.models[0]))
            self.assertEqual(early.status_code, 200, early.text)
            self.assertFalse(early.json()["prediction_inputs"]["can_predict"])
            c = wb.context(self.store, "station:lanneng:synthetic")
            native = client.get("/api/v1/workspace/data-readiness", params=dict(
                source_key=c["source"]["key"], trading_date=c["date"], model_id=c["model_id"], record_id=c["record_id"]))
            self.assertEqual(native.status_code, 200, native.text)
            self.assertEqual(native.json()["observations"]["expected_periods"], 96)
            self.assertFalse(native.json()["settlement"]["supported"])


if __name__ == "__main__":
    unittest.main()
