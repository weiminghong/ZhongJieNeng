import csv
import unittest

import numpy as np
from fastapi.testclient import TestClient
from cecep_console.api import create_app

from tests import test_learning as fixtures
from cecep_console import learning as ml, public_data, data_flow, research_views


class DataFlowTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.LearningTests(); self.fixture.setUp()
        self.store = self.fixture.store

    def tearDown(self):
        self.fixture.tearDown()

    def revise_tune_label(self):
        path = self.fixture.csv
        with path.open(encoding="utf-8", newline="") as stream:
            reader = csv.DictReader(stream); columns = reader.fieldnames; rows = list(reader)
        row = next(r for r in rows if r["日期"] == "2024-02-10" and r["时刻"] == "00:30")
        self.assertEqual(row["实时价格"], "")
        row["实时价格"] = "-123.45"
        with path.open("w", encoding="utf-8", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=columns); writer.writeheader(); writer.writerows(rows)
        public_data._load.cache_clear()
        return public_data.dataset()[0]["source_hash"]

    def test_original_bytes_archived_once_with_real_ingestion_time(self):
        rev = data_flow.archive_current(self.store, self.fixture.sha)
        self.assertEqual(ml.checksum(ml.file_path(rev["payload"]["archive"]["path"])), self.fixture.sha)
        self.assertEqual(rev["payload"]["source_mode"], "synthetic")
        self.assertFalse(rev["payload"]["historical_arrival_verified"])
        self.assertEqual(len(ml.objects(self.store, "source_revision")), 1)
        self.assertEqual(data_flow.archive_current(self.store)["id"], rev["id"])

    def test_later_observations_append_without_changing_old_prediction_or_scores(self):
        _, ids = self.fixture.trained()
        saved = ml.prediction(self.store, ids[0], "2024-02-10", True)
        original = ml.get_object(self.store, saved["id"])
        self.assertIsNone(original["payload"]["points"][1]["actual"])
        new_sha = self.revise_tune_label()
        data_flow.archive_current(self.store, new_sha)
        self.assertEqual(data_flow.reconcile(self.store, new_sha), 1)
        matched = data_flow.latest_observation(self.store, saved["id"])
        self.assertEqual(matched["payload"]["observed_points"], 96)
        self.assertEqual(matched["payload"]["points"][1]["actual"], -123.45)
        self.assertEqual(matched["payload"]["changed_from_snapshot"], 1)
        self.assertEqual(ml.get_object(self.store, saved["id"])["payload"], original["payload"])
        self.assertEqual(matched["payload"]["input_source_hash"], self.fixture.sha)
        self.assertEqual(matched["payload"]["observation_source_hash"], new_sha)
        self.assertEqual(data_flow.reconcile(self.store, new_sha), 0)
        detail = research_views.prediction_details(saved["id"], .95, self.store)
        self.assertTrue(detail["explanation"]["reconstruction_verified"])
        self.assertEqual(detail["observation"]["id"], matched["id"])
        reviewed=ml.feedback(self.store,saved["id"],1,"test","核对新观测",matched["id"])
        self.assertEqual(reviewed["payload"]["point"]["actual"],-123.45)
        self.assertEqual(reviewed["source_hash"],new_sha)
        self.assertEqual(reviewed["payload"]["input_source_hash"],self.fixture.sha)
        self.assertFalse(reviewed["payload"]["training_eligible"])

    def test_frozen_training_reads_archived_version_after_live_file_changes(self):
        before, _ = ml.build_arrays(self.fixture.ds, self.store)
        self.revise_tune_label()
        after, _ = ml.build_arrays(self.fixture.ds, self.store)
        for partition in before:
            for key in before[partition]:
                np.testing.assert_array_equal(before[partition][key], after[partition][key])

    def test_flow_rejects_mismatched_model_and_prediction(self):
        _, ids = self.fixture.trained()
        p = ml.prediction(self.store, ids[0], "2024-02-26")
        with self.assertRaises(ValueError):
            data_flow.flow(self.store, ids[1], p["id"])
        result = data_flow.flow(self.store, ids[0], p["id"])
        self.assertEqual(result["dataset"]["id"], self.fixture.ds["id"])
        self.assertEqual(result["archive"]["source_hash"], self.fixture.sha)

    def test_corrupt_archive_stops_frozen_input(self):
        rev = data_flow.archive_current(self.store)
        ml.file_path(rev["payload"]["archive"]["path"]).write_bytes(b"corrupt generated fixture")
        with self.assertRaisesRegex(ValueError, "归档校验失败"):
            ml.build_arrays(self.fixture.ds, self.store)

    def test_archived_raw_view_and_review_do_not_silently_use_latest_file(self):
        new_sha = self.revise_tune_label()
        data_flow.archive_current(self.store,new_sha)
        with TestClient(create_app()) as client:
            url="/api/v1/research/source-series?trading_date=2024-02-10&cursor=96&source_hash="
            old=client.get(url+self.fixture.sha).json()
            new=client.get(url+new_sha).json()
            self.assertIsNone(old["points"][1]["rt_price"])
            self.assertEqual(new["points"][1]["rt_price"],-123.45)
            review=client.post("/api/v1/public-data/review",json=dict(date="2024-02-10",cursor=96,source_hash=self.fixture.sha,archived=True,selected_slot=1,reason="核对旧输入"))
            self.assertEqual(review.status_code,200)
            saved=review.json()
            self.assertEqual(saved["evidence"]["source_hash"],self.fixture.sha)
            self.assertIsNone(saved["evidence"]["source_records"][1]["rt_price"])

    def test_new_source_hash_does_not_reset_used_final_window(self):
        _, ids=self.fixture.trained()
        ml.final_audit(self.store,ids[0],"test","初次最终检验")
        new_sha=self.revise_tune_label()
        ds=ml.register_dataset(self.store,new_sha)
        job=ml.submit(self.store,ds["id"],1,"new-version-fixture")
        models=ml.execute(self.store,job["id"])
        ml.event(self.store,job["id"],"succeeded",observed_exit_code=0);self.store.db.commit()
        with self.assertRaisesRegex(ValueError,"同一最终审计窗口"):
            ml.final_audit(self.store,models[0],"test","不能重置窗口")


if __name__ == "__main__":
    unittest.main()
