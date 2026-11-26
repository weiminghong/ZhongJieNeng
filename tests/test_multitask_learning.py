import csv
import math
import unittest
import numpy as np
from fastapi.testclient import TestClient
from tests import test_learning as fixtures
from cecep_console import learning as ml, public_data, task_catalog as tasks, data_flow
from cecep_console.api import create_app


class MultitaskLearningTests(unittest.TestCase):
    def setUp(self):
        self.f = fixtures.LearningTests()
        self.f.setUp()
        self.s = self.f.store
        with self.f.csv.open(encoding="utf-8", newline="") as file:
            reader = csv.DictReader(file)
            fields = reader.fieldnames
            rows = list(reader)
        for i, r in enumerate(rows):
            slot = i % 96
            n = i // 96
            r["光伏总加(实际)"] = str(
                max(0, math.sin((slot - 24) * math.pi / 48)) * (100 + n) - 1
            )
            if slot % 4 != 3:
                r["日前价格"] = ""
        with self.f.csv.open("w", encoding="utf-8", newline="") as file:
            w = csv.DictWriter(file, fieldnames=fields)
            w.writeheader()
            w.writerows(rows)
        self.sha = public_data.dataset()[0]["source_hash"]

    def tearDown(self):
        self.f.tearDown()

    def train(self, task, alpha=1, parent=None, proposal=None):
        ds = ml.register_dataset(self.s, self.sha, task)
        j = ml.submit(self.s, ds["id"], alpha, task + str(alpha), parent, proposal)
        ids = ml.execute(self.s, j["id"])
        ml.event(self.s, j["id"], "succeeded", observed_exit_code=0)
        self.s.db.commit()
        return j, ids

    def test_real_artifact_shapes_units_and_all_task_predictions(self):
        with TestClient(create_app()) as client:
            caps = client.get("/api/v1/ml/capabilities").json()
            self.assertEqual({p["task"] for p in caps["tasks"]}, set(tasks.TASKS))
            self.assertTrue(
                all(p["production_eligible"] is False for p in caps["tasks"])
            )
        for task in tasks.TASKS:
            if task == ml.TASK:
                continue
            j, ids = self.train(task)
            p = ml.prediction(self.s, ids[0], "2024-02-10", True)
            self.assertEqual(len(p["payload"]["points"]), len(tasks.slots(task)))
            self.assertEqual(p["payload"]["unit"], tasks.spec(task)["unit"])
            model = ml.get_object(self.s, ids[0])["payload"]
            self.assertTrue(model["artifact_load_verified"])
            self.assertEqual(
                model["trainable_parameters"], 2 * len(model["policy"]["features"]) + 1
            )
            self.assertEqual(
                self.s.db.execute(
                    "SELECT task FROM ml_models WHERE model_version_id=?", (ids[0],)
                ).fetchone()[0],
                task,
            )
            self.assertEqual(
                self.s.db.execute(
                    "SELECT point_count FROM ml_predictions WHERE prediction_id=?",
                    (p["id"],),
                ).fetchone()[0],
                len(tasks.slots(task)),
            )
            data_flow.reconcile(self.s, self.sha)
            obs = data_flow.latest_observation(self.s, p["id"])
            self.assertEqual(
                obs["payload"]["points"][0]["actual"],
                p["payload"]["points"][0]["actual"],
            )
        self.assertEqual(self.s.db.execute("PRAGMA foreign_key_check").fetchall(), [])

    def test_hour_labels_and_future_information_are_not_filled_or_leaked(self):
        rows = {
            i: dict(da_price=10 if i == 3 else None, rt_price=i + 1, pv_actual_mw=i)
            for i in range(4)
        }
        self.assertEqual(tasks.target("prebid_spread_reference", rows, 3), -7.5)
        rows[1]["rt_price"] = None
        self.assertIsNone(tasks.target("prebid_spread_reference", rows, 3))
        self.assertIsNone(tasks.target("da_price_reference", rows, 0))
        _, _, days = public_data.dataset()
        day = "2024-02-10"
        for task in ("pv_day_ahead_reference", "pv_intraday_reference"):
            before = tasks.features(days, day, 48, task)
            days[day][95]["pv_actual_mw"] += 100000
            np.testing.assert_array_equal(before, tasks.features(days, day, 48, task))

    def test_confirmed_review_produces_new_weights_and_preserves_dataset(self):
        task = "pv_intraday_reference"
        j, ids = self.train(task)
        p = ml.prediction(self.s, ids[0], "2024-02-10", True)
        f = ml.feedback(
            self.s, p["id"], 48, "generated test operator", "核对生成测试记录"
        )
        ml.confirm_feedback(
            self.s, f["id"], "generated test operator", "确认测试标签未改写"
        )
        proposal = ml.proposal(
            self.s, f["id"], 10, "generated test operator", "固定参数重训"
        )
        retry = ml.train_proposal(self.s, proposal["id"], "retrain-test")
        new = ml.execute(self.s, retry["id"])
        ml.event(self.s, retry["id"], "succeeded", observed_exit_code=0)
        self.s.db.commit()
        a, b = [ml.get_object(self.s, i)["payload"] for i in (ids[0], new[0])]
        self.assertEqual(a["dataset_id"], b["dataset_id"])
        self.assertNotEqual(a["weights"]["sha256"], b["weights"]["sha256"])
        self.assertEqual(retry["parent_job_id"], j["id"])
        ml.release(self.s, ids[-1], "activate", "test", "初始化近期观测参考")
        self.assertEqual(ml.active(self.s, task)["detail"]["model_id"], ids[-1])
        self.assertIsNone(ml.active(self.s)["detail"].get("model_id"))

    def test_task_context_rejects_foreign_models_and_retains_hour_grid(self):
        task = "da_price_reference"
        _, ids = self.train(task)
        p = ml.prediction(self.s, ids[0], "2024-02-10", True)
        with TestClient(create_app()) as client:
            q = dict(
                task_id=task,
                model_id=ids[0],
                record_id=p["id"],
                trading_date="2024-02-10",
            )
            r = client.get("/api/v1/workspace/context", params=q)
            self.assertEqual(r.status_code, 200, r.text)
            c = r.json()
            self.assertEqual(len(c["points"]), 24)
            self.assertEqual(c["source"]["task"], task)
            self.assertTrue(c["points"][0]["start"].startswith("2024-02-10T00:00"))
            q["task_id"] = "pv_day_ahead_reference"
            self.assertEqual(
                client.get("/api/v1/workspace/context", params=q).status_code, 400
            )

    def test_final_audits_are_task_scoped_without_reopening_price(self):
        old = ml.register_dataset(self.s, self.sha)
        j = ml.submit(self.s, old["id"], 1, "legacy-price")
        ids = ml.execute(self.s, j["id"])
        ml.event(self.s, j["id"], "succeeded")
        self.s.db.commit()
        original = ml.final_audit(self.s, ids[0], "test", "冻结价格测试候选")
        _, new = self.train("da_price_reference")
        other = ml.final_audit(self.s, new[0], "test", "冻结日前小时测试候选")
        self.assertNotEqual(original["id"], other["id"])
        with self.assertRaises(ValueError):
            ml.final_audit(self.s, ids[0], "test", "不能重开价格终评")

    def test_saved_forecast_drives_settlement_and_retains_evidence(self):
        from cecep_console.public_settlement import calculate_points

        points = [dict(slot=i, actual=2, predicted=4, rt_price=200) for i in range(4)]
        rows = {i: dict(da_price=100 if i == 3 else None) for i in range(4)}
        hand = calculate_points(points, rows)
        self.assertEqual(hand["settled_intervals"], 4)
        self.assertEqual(hand["value"], 0)
        self.assertEqual(hand["reference"], 400)
        points[0]["actual"] = None
        self.assertEqual(calculate_points(points, rows)["settled_intervals"], 0)
        task = "pv_day_ahead_reference"
        _, ids = self.train(task)
        pred = ml.prediction(self.s, ids[0], "2024-02-26")
        with TestClient(create_app()) as client:
            q = dict(
                source_key="market:shandong",
                task_id=task,
                trading_date="2024-02-26",
                model_id=ids[0],
                record_id=pred["id"],
            )
            c = client.get("/api/v1/workspace/context", params=q).json()
            response = client.post(
                "/api/v1/workspace/commands",
                json=dict(
                    action="scenario",
                    source_key="market:shandong",
                    task_id=task,
                    date="2024-02-26",
                    model_id=ids[0],
                    record_id=pred["id"],
                    context_version=c["context_version"],
                    actor="generated test operator",
                    reason="按保存预测核对结算",
                ),
            )
            self.assertEqual(response.status_code, 200, response.text)
            result = response.json()
            self.assertEqual(
                self.s.db.execute(
                    "SELECT prediction_id FROM ml_business_scenario WHERE scenario_id=?",
                    (result["id"],),
                ).fetchone()[0],
                pred["id"],
            )
            view = client.get("/api/v1/workspace/scenario", params=q).json()
            self.assertTrue(view["history"])

    def test_intraday_replay_hides_predictions_using_later_inputs(self):
        task = "pv_intraday_reference"
        _, ids = self.train(task)
        p = ml.prediction(self.s, ids[0], "2024-02-26")
        self.assertEqual(p["payload"]["cutoff_policy"], "per_point")
        with TestClient(create_app()) as client:
            c = client.get(
                "/api/v1/workspace/context",
                params=dict(
                    task_id=task,
                    trading_date="2024-02-26",
                    model_id=ids[0],
                    record_id=p["id"],
                    mode="replay",
                    until="12:00",
                ),
            ).json()
            self.assertIsNotNone(c["points"][48]["predicted"])
            self.assertTrue(all(x["predicted"] is None for x in c["points"][49:]))

    def test_output_guard_preserves_weights_labels_and_is_explicitly_not_retraining(
        self,
    ):
        task = "pv_day_ahead_reference"
        _, ids = self.train(task)
        old = ml.get_object(self.s, ids[0])
        before = self.f.csv.read_bytes()
        new = ml.guard_power_model(
            self.s, old["id"], "generated technical reviewer", "修正训练期经验边界"
        )
        self.assertEqual(old["payload"]["weights"], new["payload"]["weights"])
        self.assertEqual(
            new["payload"]["variant_kind"],
            "prediction_constraint_not_weight_retraining",
        )
        self.assertEqual(self.f.csv.read_bytes(), before)
        pred = ml.prediction(self.s, new["id"], "2024-02-26")
        self.assertTrue(
            all(
                p["predicted"] >= new["payload"]["output_bounds"]["lower"]
                for p in pred["payload"]["points"]
            )
        )
        self.assertTrue(all("raw_predicted" in p for p in pred["payload"]["points"]))
        self.assertEqual(
            ml.guard_power_model(self.s, old["id"], "test", "重复请求")["id"], new["id"]
        )

    def test_guarded_model_retraining_keeps_train_only_output_recipe(self):
        task = "pv_day_ahead_reference"
        _, ids = self.train(task)
        new = ml.guard_power_model(self.s, ids[0], "test", "训练期边界")
        pred = ml.prediction(self.s, new["id"], "2024-02-10", True)
        f = ml.feedback(self.s, pred["id"], 48, "test", "核对生成标签")
        ml.confirm_feedback(self.s, f["id"], "test", "确认")
        p = ml.proposal(self.s, f["id"], 10, "test", "相同出力约束的参数重训")
        j = ml.train_proposal(self.s, p["id"], "guarded-retrain")
        self.assertEqual(j["config"]["output_recipe"], "train_signed_power_floor_v1")
        models = ml.execute(self.s, j["id"])
        self.assertEqual(
            ml.get_object(self.s, models[0])["payload"]["output_bounds"]["kind"],
            "train_signed_power_floor_v1",
        )


if __name__ == "__main__":
    unittest.main()
