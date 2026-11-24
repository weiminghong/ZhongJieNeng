import csv
from datetime import date, timedelta
import json
import math
import os
from pathlib import Path
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np
from fastapi.testclient import TestClient

from cecep_console import learning as ml, public_data
from cecep_console.storage import Store
from cecep_console.api import create_app


class LearningTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.base = Path(self.temp.name)
        self.csv = self.base / "generated.csv"
        with self.csv.open("w", encoding="utf-8", newline="") as f:
            cols = ["日期", "时刻", *[v[0] for v in public_data.FIELDS.values()]]
            writer = csv.DictWriter(f, fieldnames=cols); writer.writeheader()
            for n in range(85):
                day = date(2024, 1, 1)+timedelta(days=n)
                for slot in range(96):
                    minute = (slot+1)*15
                    row = dict.fromkeys(cols, 100)
                    row.update({"日期": day.isoformat(), "时刻": f"{minute//60:02d}:{minute%60:02d}",
                                "实时价格": -50+2*n+30*math.sin(slot*math.pi/48)})
                    if n == 40 and slot == 1:
                        row["实时价格"] = ""
                    writer.writerow(row)
        self.partitions = dict(train=["2024-01-08", "2024-02-08"], tune=["2024-02-10", "2024-02-24"],
                               promotion=["2024-02-26", "2024-03-11"], final_audit=["2024-03-13", "2024-03-25"])
        self.env = patch.dict(os.environ, CECEP_DB_PATH=str(self.base/"db.sqlite3"), CECEP_PUBLIC_MARKET_CSV=str(self.csv),
                              CECEP_ML_ROOT=str(self.base/"ml"), CECEP_ML_TEST_FIXTURE="1",
                              CECEP_ML_TEST_CONTRACT=json.dumps(self.partitions), CECEP_ML_WORKER="0")
        self.env.start(); self.store = Store(); self.store.initialize()
        self.sha = public_data.catalog()["metadata"]["source_hash"]
        self.ds = ml.register_dataset(self.store, self.sha)

    def tearDown(self):
        self.store.close(); self.env.stop(); public_data._load.cache_clear(); self.temp.cleanup()

    def trained(self, alpha=1, key="first"):
        j = ml.submit(self.store, self.ds["id"], alpha, key)
        ids = ml.execute(self.store, j["id"])
        ml.event(self.store, j["id"], "succeeded", observed_exit_code=0)
        self.store.db.commit()
        return j, ids

    def test_complete_training_inference_feedback_retrain_and_release(self):
        j, ids = self.trained()
        ridge, d2 = ids[:2]
        model = ml.get_object(self.store, ridge)
        self.assertTrue(model["payload"]["artifact_load_verified"])
        self.assertEqual(model["payload"]["counts"]["tune"]["excluded"], 1)
        self.assertEqual(model["payload"]["trainable_parameters"], 27)
        baseline = ml.release(self.store, d2, "activate", "tester", "初始化研究基线")
        self.assertEqual(baseline["detail"]["model_id"], d2)
        ml.release(self.store, ridge, "activate", "tester", "通过固定门槛")
        self.assertEqual(ml.active(self.store)["detail"]["model_id"], ridge)
        p = ml.prediction(self.store, ridge, "2024-02-26")
        with self.assertRaisesRegex(ValueError, "调参验证只能"):
            ml.prediction(self.store, ridge, "2024-02-26", True)
        self.assertEqual(len(p["payload"]["points"]), 96)
        ml.release(self.store, d2, "rollback", "tester", "验证回滚")
        back = ml.prediction(self.store, d2, "2024-02-26")
        self.assertNotEqual(p["payload"]["points"][0]["predicted"], back["payload"]["points"][0]["predicted"])
        with self.assertRaises(ValueError):
            ml.prediction(self.store, ridge, "2024-02-10")
        with self.assertRaises(ValueError):
            ml.prediction(self.store, ridge, "2024-02-25")
        validation = ml.prediction(self.store, ridge, "2024-02-10", True)
        with patch("cecep_console.model_settings.load_settings", return_value=SimpleNamespace(ready=False)):
            analysis = ml.analyze_prediction(self.store, validation["id"], "核对真实预测")
        self.assertEqual(analysis["payload"]["llm_mode"], "deterministic_tools_only")
        self.assertEqual(analysis["payload"]["tool"], "registered_numpy_price_inference")
        fb = ml.feedback(self.store, validation["id"], 0, "tester", "核对负价段的偏差")
        self.assertFalse(fb["payload"]["training_eligible"])
        ml.confirm_feedback(self.store, fb["id"], "tester", "已对照原始行")
        proposal = ml.proposal(self.store, fb["id"], 10, "tester", "按固定集合调整正则")
        retrain = ml.train_proposal(self.store, proposal["id"], "retrain")
        self.assertEqual(retrain["dataset_id"], self.ds["id"])
        self.assertEqual(retrain["parent_job_id"], j["id"])
        self.assertFalse(proposal["payload"]["incorporates_labels"])
        ml.execute(self.store, retrain["id"])
        ml.event(self.store, retrain["id"], "succeeded", observed_exit_code=0); self.store.db.commit()
        audit = ml.final_audit(self.store, ridge, "tester", "冻结唯一候选")
        self.assertIn("final_audit", audit["payload"]["report"])
        with self.assertRaises(ValueError):
            ml.final_audit(self.store, ids[1], "tester", "不得重复检验")

    def test_target_day_does_not_enter_features(self):
        _, _, days = public_data.dataset()
        before = np.array(ml.features_for(days, "2024-02-26", 20))
        days["2024-02-26"][20]["rt_price"] = 999999
        after = np.array(ml.features_for(days, "2024-02-26", 20))
        np.testing.assert_array_equal(before, after)

    def test_preprocessing_fits_only_training(self):
        arrays, _ = ml.build_arrays(self.ds)
        original = ml.fit(arrays["train"], 1)
        arrays["promotion"]["x"][:] = 999999
        arrays["tune"]["y"][:] = -999999
        fresh = ml.fit(arrays["train"], 1)
        for name in original:
            np.testing.assert_array_equal(original[name], fresh[name])

    def test_corrupt_artifact_is_rejected_and_final_stays_sealed(self):
        _, ids = self.trained()
        with self.assertRaises(ValueError):
            ml.prediction(self.store, ids[0], "2024-03-13")
        m = ml.get_object(self.store, ids[0])
        ml.file_path(m["payload"]["weights"]["path"]).write_bytes(b"broken")
        with self.assertRaisesRegex(ValueError, "校验"):
            ml.prediction(self.store, ids[0], "2024-02-26")

    def test_idempotence_and_append_only(self):
        a = ml.submit(self.store, self.ds["id"], 1, "one")
        self.assertEqual(a["id"], ml.submit(self.store, self.ds["id"], 1, "one")["id"])
        with self.assertRaises(ValueError):
            ml.submit(self.store, self.ds["id"], 10, "one")
        with self.assertRaises(Exception):
            self.store.db.execute("DELETE FROM ml_job")
        self.store.db.rollback()

    def test_api_cancel_retry_origin_and_declared_actor(self):
        with TestClient(create_app()) as client:
            body = dict(action="train", object_id=self.ds["id"], actor="test", reason="测试", idempotency_key="api")
            first = client.post("/api/v1/ml/commands", json=body).json()
            cancelled = client.post("/api/v1/ml/commands", json=dict(action="cancel", object_id=first["id"], actor="test", reason="取消")).json()
            self.assertEqual(cancelled["state"], "cancelled")
            retried = client.post("/api/v1/ml/commands", json=dict(action="retry", object_id=first["id"], actor="test", reason="重试", idempotency_key="retry")).json()
            self.assertEqual(retried["parent_job_id"], first["id"])
            self.assertEqual(client.post("/api/v1/ml/commands", json=body, headers={"Origin": "http://foreign.invalid"}).status_code, 403)
            self.assertEqual(client.post("/api/v1/ml/commands", json={**body, "actor": " "}).status_code, 422)

    def test_promotion_feedback_cannot_reuse_evaluation_window(self):
        _, ids = self.trained()
        p = ml.prediction(self.store, ids[0], "2024-02-26")
        fb = ml.feedback(self.store, p["id"], 1, "test", "发现偏差")
        ml.confirm_feedback(self.store, fb["id"], "test", "确认")
        with self.assertRaisesRegex(ValueError, "未来评估合同"):
            ml.proposal(self.store, fb["id"], 10, "test", "不能偷用测试窗口")

    def test_ci_native_metric_and_negative_predictions(self):
        self.assertEqual(ml.scores(np.array([-3., 1.]), np.array([-2., -1.]))["mae"], 1.5)
        _, ids = self.trained()
        p = ml.prediction(self.store, ids[0], "2024-02-10", True)
        self.assertEqual(p["payload"]["time_policy"], "historical_assumed")
        self.assertFalse(p["payload"]["production_eligible"])

    def test_failed_promotion_preserves_pointer_and_is_rejectable(self):
        _, ids = self.trained()
        ridge = ml.get_object(self.store, ids[0])
        ml.release(self.store, ids[1], "activate", "test", "初始化")
        a = ml.read_npz(ridge["payload"]["weights"])
        a["coefficients"][:] = 0; a["intercept"] = np.array(100000.)
        ref = ml.write_npz("models/generated-bad/weights.npz", **a)
        bad = ml.add_object(self.store, "model", {**ridge["payload"], "weights": ref}, self.sha, self.ds["id"])
        ml.event(self.store, bad, "evaluated"); self.store.db.commit()
        with self.assertRaisesRegex(ValueError, "未通过"):
            ml.release(self.store, bad, "activate", "test", "验证拒绝")
        self.assertEqual(ml.active(self.store)["detail"]["model_id"], ids[1])
        ml.release(self.store, bad, "reject", "test", "保留失败证据")
        self.assertEqual(ml.state(self.store, bad)["state"], "rejected")

    def test_monitor_detects_only_source_changes_and_never_launches_training(self):
        ml.monitor_source(self.store)
        ml.monitor_source(self.store)
        self.assertEqual(len(ml.objects(self.store, "monitor_snapshot")), 1)
        self.assertEqual(self.store.db.execute("SELECT count(*) FROM ml_job").fetchone()[0], 0)
        self.assertFalse(ml.state(self.store, "monitor")["detail"]["changed"])

    def test_unknown_job_cannot_consume_final_audit_seal(self):
        j, ids = self.trained()
        ml.event(self.store, j["id"], "unknown_exit", reason="generated recovery fixture")
        self.store.db.commit()
        with self.assertRaisesRegex(ValueError, "尚无成功退出"):
            ml.final_audit(self.store, ids[0], "test", "不可消耗封存资格")
        self.assertEqual(ml.state(self.store, "final:"+self.sha)["state"], "registered")


if __name__ == "__main__":
    unittest.main()
