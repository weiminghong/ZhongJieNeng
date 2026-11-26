import unittest
import numpy as np
from fastapi.testclient import TestClient
from tests import test_learning as fixtures
from cecep_console import learning as ml
from cecep_console.api import create_app


class OptimizationViewTests(unittest.TestCase):
    def setUp(self):
        self.f = fixtures.LearningTests()
        self.f.setUp()
        a = ml.write_npz(
            "generated/outer.npz",
            candidate=np.array([1.0, 2.0]),
            old_ridge=np.array([2.0, 3.0]),
            reference=np.array([3.0, 4.0]),
            y=np.array([1.0, 1.0]),
            days=np.array(["2024-02-26"] * 2),
            slots=np.array([0, 1]),
        )
        score = dict(n=2, mae=1.0, rmse=1.0, mbe=0.0)
        ci = dict(days=20, lower95=-2.0, upper95=-1.0)
        fold = dict(
            fold=dict(
                name="generated",
                start="2024-02-26",
                end="2024-02-26",
                outer_validation=True,
            ),
            choice=dict(recipe="ridge_bounded"),
            scores={k: score for k in ["candidate", "reference", "old_ridge"]},
            comparisons=dict(reference=ci, old_ridge=ci),
            predictions=a,
        )
        payload = dict(
            task="pv_day_ahead_reference",
            contract=dict(contract_id="generated-optimization"),
            summary=dict(
                rows=2, days=1, scores=fold["scores"], comparisons=fold["comparisons"]
            ),
            folds=[
                fold,
                dict(
                    fold,
                    fold=dict(
                        name="replay",
                        start="2024-03-13",
                        end="2024-03-25",
                        outer_validation=False,
                    ),
                ),
            ],
        )
        self.oid = ml.add_object(
            self.f.store, "optimization_result", payload, self.f.sha, self.f.ds["id"]
        )
        self.f.store.db.commit()

    def tearDown(self):
        self.f.tearDown()

    def test_reports_describe_retrospective_evidence_without_exposing_artifact_paths(
        self,
    ):
        with TestClient(create_app()) as c:
            response = c.get(
                "/api/v1/optimization/summary",
                params=dict(task_id="pv_day_ahead_reference"),
            )
            self.assertEqual(response.status_code, 200, response.text)
            body = response.json()
            self.assertEqual(body["reports"][0]["scores"][0]["name"], "优化流程")
            self.assertIn("不是同一个模型", body["notice"])
            self.assertNotIn("predictions", body["reports"][0])
            self.assertNotIn("model_hash", response.text)

    def test_saved_prediction_scope_and_missing_dates_are_checked(self):
        with TestClient(create_app()) as c:
            q = dict(
                result_id=self.oid,
                task_id="pv_day_ahead_reference",
                trading_date="2024-02-26",
            )
            r = c.get("/api/v1/optimization/predictions", params=q)
            self.assertEqual(r.status_code, 200, r.text)
            self.assertEqual(r.json()["points"][0]["predicted"], 1.0)
            q["trading_date"] = "2024-02-01"
            self.assertFalse(
                c.get("/api/v1/optimization/predictions", params=q).json()["available"]
            )
            q["task_id"] = "prebid_spread_reference"
            self.assertEqual(
                c.get("/api/v1/optimization/predictions", params=q).status_code, 400
            )


if __name__ == "__main__":
    unittest.main()
