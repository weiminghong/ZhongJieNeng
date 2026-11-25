import unittest
from datetime import date

import numpy as np
from fastapi.testclient import TestClient

from cecep_console import learning as ml, research_views as views
from cecep_console.api import create_app
from tests import test_learning as fixtures


class ResearchViewTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.LearningTests()
        self.fixture.setUp()
        self.store = self.fixture.store

    def tearDown(self):
        self.fixture.tearDown()

    def test_quality_preserves_missing_and_source_version(self):
        q = views.quality(self.fixture.sha)
        price = next(f for f in q["fields"] if f["key"] == "rt_price")
        self.assertEqual(price["missing"], 1)
        self.assertGreater(price["negative"], 0)
        self.assertEqual(q["missing_intervals"], 0)
        self.assertFalse(q["delete_allowed"])
        with self.assertRaises(ValueError):
            views.current("0"*64)

    def test_decomposition_reconstructs_observed_values_and_respects_cursor(self):
        result = views.decomposition(date(2024, 2, 20), "rt_price", 7, 48, self.fixture.sha)
        self.assertTrue(result["scope"]["retrospective"])
        self.assertEqual(result["points"][-1]["slot"], 47)
        for p in result["points"]:
            if all(p[k] is not None for k in ("actual", "trend", "seasonal", "residual")):
                self.assertAlmostEqual(p["actual"], p["trend"]+p["seasonal"]+p["residual"], places=9)
        self.assertEqual(result["points"][0]["trend"], None)

    def test_comparison_deduplicates_only_identical_outputs_and_never_unseals(self):
        _, first = self.fixture.trained()
        self.fixture.trained(key="identical-retry")
        result = views.compare(self.store, first[0], "promotion")
        self.assertEqual(len(result["rows"]), 4)
        self.assertTrue(all(len(r["aliases"]) == 2 for r in result["rows"]))
        self.assertEqual(result["expected"], 15*96)
        with self.assertRaises(ValueError):
            views.compare(self.store, first[0], "final_audit")
        self.assertEqual(ml.state(self.store, "final:"+self.fixture.sha)["state"], "registered")
        ml.final_audit(self.store, first[0], "test", "generated fixture audit")
        audited = views.compare(self.store, first[0], "final_audit")
        self.assertEqual(len(audited["rows"]), 4)
        self.assertEqual(audited["partition"], "final_audit")

    def test_prediction_explanation_reconstructs_and_ranges_use_prior_tune_only(self):
        _, ids = self.fixture.trained()
        prediction = ml.prediction(self.store, ids[0], "2024-02-26")
        narrow = views.prediction_details(prediction["id"], .8, self.store)
        wide = views.prediction_details(prediction["id"], .95, self.store)
        self.assertTrue(wide["explanation"]["reconstruction_verified"])
        expected = np.mean([r["predicted"] for r in prediction["payload"]["points"]])
        self.assertAlmostEqual(sum(i["value"] for i in wide["explanation"]["items"]), expected)
        self.assertGreaterEqual(wide["range"]["mean_width"], narrow["range"]["mean_width"])
        self.assertEqual(wide["range"]["calibration_end"], "2024-02-24")
        tune = ml.prediction(self.store, ids[0], "2024-02-24", True)
        self.assertIsNone(views.prediction_details(tune["id"], .95, self.store)["range"])
        self.assertEqual(wide["range"]["points"][0]["predicted"], prediction["payload"]["points"][0]["predicted"])

    def test_history_and_csv_export_are_immutable_read_views(self):
        _, ids = self.fixture.trained()
        p = ml.prediction(self.store, ids[0], "2024-02-26")
        before = self.store.db.execute("SELECT count(*) FROM ml_object").fetchone()[0]
        with TestClient(create_app()) as client:
            history = client.get("/api/v1/research/predictions").json()
            self.assertEqual(history["records"][0]["id"], p["id"])
            self.assertEqual(history["total"], 1)
            self.assertEqual(client.get("/api/v1/research/predictions?offset=1").json()["records"], [])
            self.assertEqual(client.get("/api/v1/research/predictions?trading_date=2024-01-01").json()["total"], 0)
            response = client.get(f"/api/v1/research/predictions/{p['id']}/export")
            self.assertEqual(response.status_code, 200)
            self.assertEqual(len(response.content.decode("utf-8-sig").splitlines()), 97)
            self.assertIn("CNY/MWh", response.text)
            self.assertEqual(client.get("/api/v1/research/summary").status_code, 200)
        self.assertEqual(self.store.db.execute("SELECT count(*) FROM ml_object").fetchone()[0], before)


if __name__ == "__main__":
    unittest.main()
