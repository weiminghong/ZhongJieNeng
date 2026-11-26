import json
import csv
import unittest
from fastapi.testclient import TestClient
from tests import test_learning as fixtures
from cecep_console.api import create_app
from cecep_console import learning as ml, workbench_context as wb
from cecep_console.storage_demo import seed_demo


class UnifiedWorkbenchTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.LearningTests()
        self.fixture.setUp()
        self.store = self.fixture.store
        seed_demo(self.store)
        _, self.ids = self.fixture.trained()
        self.price = ml.prediction(self.store, self.ids[0], "2024-02-26")

    def tearDown(self):
        self.fixture.tearDown()

    def test_catalog_and_context_keep_source_units_and_one_contract(self):
        sources = wb.catalog(self.store)["sources"]
        self.assertTrue(any(s["key"] == "market:shandong" for s in sources))
        site = next(s for s in sources if s["key"] == "station:lanneng:synthetic")
        market = wb.context(
            self.store, "market:shandong", "2024-02-26", self.ids[0], self.price["id"]
        )
        station = wb.context(self.store, site["key"])
        self.assertEqual(set(market), set(station))
        self.assertEqual(market["source"]["unit"], "元/MWh")
        self.assertEqual(station["source"]["unit"], "MW")
        self.assertFalse(station["source"]["can_train"])
        self.assertTrue(station["points"])
        self.assertTrue(
            all(r["n"] == station["comparison"][0]["n"] for r in station["comparison"])
        )

    def test_foreign_model_record_and_date_are_rejected(self):
        for kwargs in [dict(mid=self.ids[0]), dict(rid=self.price["id"])]:
            with self.assertRaises(ValueError):
                wb.context(self.store, "station:lanneng:synthetic", **kwargs)
        station = wb.context(self.store, "station:lanneng:synthetic")
        with self.assertRaises(ValueError):
            wb.context(self.store, "market:shandong", "2024-02-26", station["model_id"])
        with self.assertRaises(ValueError):
            wb.context(
                self.store,
                "market:shandong",
                "2024-02-27",
                self.ids[0],
                self.price["id"],
            )
        with self.assertRaises(ValueError):
            wb.context(
                self.store, "station:lingguang:synthetic", rid=station["record_id"]
            )

    def test_selected_model_without_record_never_uses_another_models_curve(self):
        native = wb.context(self.store, "station:lanneng:synthetic")
        runtime = next(
            m for m in native["models"] if m["id"] == "pv-residual-ridge-synthetic"
        )
        empty = wb.context(
            self.store, "station:lanneng:synthetic", native["date"], runtime["id"]
        )
        self.assertIsNone(empty["record_id"])
        self.assertTrue(all(p["predicted"] is None for p in empty["points"]))
        self.assertEqual(empty["cases"], [])

    def test_replay_masks_future_actual_and_review_pairs_follow_selected_record(self):
        market = wb.context(
            self.store,
            "market:shandong",
            "2024-02-26",
            self.ids[0],
            self.price["id"],
            "replay",
            "12:00",
        )
        self.assertEqual(market["metrics"]["n"], 48)
        self.assertTrue(all(p["actual"] is None for p in market["points"][48:]))
        native = wb.context(self.store, "station:lanneng:synthetic")
        self.assertTrue(
            all(
                c["predicted"] == native["points"][c["slot"]]["predicted"]
                for c in native["cases"]
            )
        )

    def test_one_review_command_confirms_both_domains_and_rejects_cross_source(self):
        with TestClient(create_app()) as client:
            for key, day, mid, rid in [
                ("market:shandong", "2024-02-26", self.ids[0], self.price["id"]),
                ("station:lanneng:synthetic", None, None, None),
            ]:
                c = wb.context(self.store, key, day, mid, rid)
                case = c["cases"][0]
                body = dict(
                    action="feedback",
                    source_key=key,
                    date=c["date"],
                    model_id=c["model_id"],
                    record_id=c["record_id"],
                    case_id=case["id"],
                    slot=case["slot"],
                    context_version=c["context_version"],
                    confirmed=True,
                    actor="test",
                    reason="核对当前来源的实际数据",
                )
                response = client.post("/api/v1/workspace/commands", json=body)
                self.assertEqual(response.status_code, 200, response.text)
                after = wb.context(
                    self.store, key, c["date"], c["model_id"], c["record_id"]
                )
                self.assertEqual(
                    next(p for p in after["cases"] if p["slot"] == case["slot"])[
                        "state"
                    ],
                    "confirmed",
                )
                history = client.get(
                    "/api/v1/workspace/reviews",
                    params=dict(source_key=key, trading_date=c["date"]),
                )
                self.assertEqual(history.status_code, 200, history.text)
                self.assertTrue(history.json()["records"])
            bad = client.post(
                "/api/v1/workspace/commands",
                json=dict(
                    action="predict",
                    source_key="station:lanneng:synthetic",
                    date="2026-11-20",
                    model_id=self.ids[0],
                    actor="test",
                    reason="不能串来源",
                ),
            )
            self.assertEqual(bad.status_code, 400)

    def test_native_runtime_prediction_is_saved_owned_and_reviewable(self):
        with TestClient(create_app()) as client:
            response = client.post(
                "/api/v1/workspace/commands",
                json=dict(
                    action="predict",
                    source_key="station:lanneng:synthetic",
                    date="2026-11-20",
                    model_id="pv-residual-ridge-synthetic",
                    actor="test",
                    reason="按当前来源进行历史拟合预测",
                ),
            )
            self.assertEqual(response.status_code, 200, response.text)
            rid = response.json()["id"]
            c = wb.context(
                self.store,
                "station:lanneng:synthetic",
                "2026-11-20",
                "pv-residual-ridge-synthetic",
                rid,
            )
            self.assertEqual(c["record_id"], rid)
            self.assertEqual(len(c["points"]), 96)
            self.assertTrue(c["cases"])
            self.assertTrue(any(r["id"] == rid for r in c["comparison"]))

    def test_review_snapshot_changes_require_new_confirmation(self):
        with TestClient(create_app()) as client:
            c = wb.context(
                self.store,
                "market:shandong",
                "2024-02-26",
                self.ids[0],
                self.price["id"],
            )
            case = c["cases"][0]
            body = dict(
                action="feedback",
                source_key=c["source"]["key"],
                date=c["date"],
                model_id=c["model_id"],
                record_id=c["record_id"],
                slot=case["slot"],
                context_version=c["context_version"],
                confirmed=True,
                actor="test",
                reason="核对原观测",
            )
            self.assertEqual(
                client.post("/api/v1/workspace/commands", json=body).status_code, 200
            )
            with self.fixture.csv.open(encoding="utf-8", newline="") as f:
                reader = csv.DictReader(f)
                fields = reader.fieldnames
                records = list(reader)
            for row in records:
                if row["日期"] == c["date"]:
                    row["实时价格"] = str(float(row["实时价格"]) + 100)
            with self.fixture.csv.open("w", encoding="utf-8", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=fields)
                writer.writeheader()
                writer.writerows(records)
            ml.monitor_source(self.store)
            after = wb.context(
                self.store, c["source"]["key"], c["date"], c["model_id"], c["record_id"]
            )
            self.assertNotEqual(c["context_version"], after["context_version"])
            self.assertTrue(all(p["state"] == "pending" for p in after["cases"]))
            history = client.get(
                "/api/v1/workspace/reviews",
                params=dict(source_key=c["source"]["key"], trading_date=c["date"]),
            )
            self.assertTrue(history.json()["records"])
            self.assertEqual(
                client.post("/api/v1/workspace/commands", json=body).status_code, 400
            )
            params = dict(
                source_key=c["source"]["key"],
                trading_date=c["date"],
                model_id=c["model_id"],
                record_id=c["record_id"],
            )
            old = client.get(
                "/api/v1/workspace/scenario", params=dict(params, basis="snapshot")
            )
            new = client.get(
                "/api/v1/workspace/scenario", params=dict(params, basis="latest")
            )
            self.assertEqual(old.status_code, 200, old.text)
            self.assertEqual(new.status_code, 200, new.text)
            self.assertAlmostEqual(new.json()["value"] - old.json()["value"], 96 * 100)
            historical = client.get(
                "/api/v1/workspace/history",
                params=dict(params, basis="snapshot", days=3),
            )
            self.assertEqual(historical.status_code, 200, historical.text)
            self.assertEqual(
                historical.json()["points"][-96]["actual"], c["points"][0]["actual"]
            )
            stale = client.get(
                "/api/v1/workspace/export",
                params=dict(params, expected_version=c["context_version"]),
            )
            self.assertEqual(stale.status_code, 400)

    def test_future_review_export_and_source_owned_details(self):
        with TestClient(create_app()) as client:
            c = wb.context(
                self.store,
                "market:shandong",
                "2024-02-26",
                self.ids[0],
                self.price["id"],
                "replay",
                "12:00",
            )
            response = client.post(
                "/api/v1/workspace/commands",
                json=dict(
                    action="feedback",
                    source_key=c["source"]["key"],
                    date=c["date"],
                    model_id=c["model_id"],
                    record_id=c["record_id"],
                    slot=95,
                    context_version=c["context_version"],
                    mode="replay",
                    until="12:00",
                    confirmed=True,
                    actor="test",
                    reason="未来不可复核",
                ),
            )
            self.assertEqual(response.status_code, 400)
            p = dict(
                source_key=c["source"]["key"],
                trading_date=c["date"],
                model_id=c["model_id"],
                record_id=c["record_id"],
                mode="replay",
                until="12:00",
            )
            exported = client.get("/api/v1/workspace/export", params=p)
            self.assertEqual(exported.status_code, 200, exported.text)
            rows = list(
                csv.DictReader(exported.content.decode("utf-8-sig").splitlines())
            )
            self.assertEqual(len(rows), 96)
            self.assertTrue(all(row["实际值"] == "" for row in rows[48:]))
            p.pop("mode")
            p.pop("until")
            details = client.get("/api/v1/workspace/prediction-details", params=p)
            self.assertEqual(details.status_code, 200, details.text)
            self.assertTrue(details.json()["explanation"]["reconstruction_verified"])
            p["source_key"] = "station:lanneng:synthetic"
            self.assertEqual(
                client.get(
                    "/api/v1/workspace/prediction-details", params=p
                ).status_code,
                400,
            )

    def test_job_control_and_final_audit_keep_existing_guards(self):
        with TestClient(create_app()) as client:
            j = ml.submit(self.store, self.fixture.ds["id"], 10, "unified-cancel")
            body = dict(
                source_key="market:shandong",
                date="2024-02-26",
                actor="test",
                reason="核对任务生命周期",
                job_id=j["id"],
            )
            cancelled = client.post(
                "/api/v1/workspace/commands", json=dict(body, action="cancel")
            )
            self.assertEqual(cancelled.status_code, 200, cancelled.text)
            retry = client.post(
                "/api/v1/workspace/commands",
                json=dict(body, action="retry", key="unified-retry"),
            )
            self.assertEqual(retry.status_code, 200, retry.text)
            self.assertNotEqual(retry.json()["id"], j["id"])
            final = dict(
                source_key="market:shandong",
                date="2024-02-26",
                actor="test",
                reason="冻结研究候选",
                action="final_audit",
                model_id=self.ids[0],
            )
            self.assertEqual(
                client.post("/api/v1/workspace/commands", json=final).status_code, 400
            )
            final["confirmed"] = True
            self.assertEqual(
                client.post("/api/v1/workspace/commands", json=final).status_code, 200
            )
            self.assertEqual(
                client.post("/api/v1/workspace/commands", json=final).status_code, 400
            )

    def test_native_arrival_updates_without_rebuilding_serving_and_invalidates_review(
        self,
    ):
        from cecep_console.serving import now

        c = wb.context(self.store, "station:lanneng:synthetic")
        case = c["cases"][0]
        with TestClient(create_app()) as client:
            body = dict(
                action="feedback",
                source_key=c["source"]["key"],
                date=c["date"],
                model_id=c["model_id"],
                record_id=c["record_id"],
                case_id=case["id"],
                slot=case["slot"],
                context_version=c["context_version"],
                confirmed=True,
                actor="test",
                reason="确认当前场站观测",
            )
            self.assertEqual(
                client.post("/api/v1/workspace/commands", json=body).status_code, 200
            )
            actual = dict(
                self.store.db.execute(
                    "SELECT * FROM station_actual WHERE station_id='lanneng' AND interval_start=? ORDER BY revision_no DESC LIMIT 1",
                    (case["start"],),
                ).fetchone()
            )
            batch = dict(
                self.store.db.execute(
                    "SELECT * FROM ingestion_batch WHERE batch_id=?",
                    (actual["batch_id"],),
                ).fetchone()
            )
            arrival = now()
            batch.update(
                batch_id="native-arrival-regression",
                file_hash=ml.digest("new generated arrival"),
                started_at=arrival,
                finished_at=arrival,
            )
            self.store.append("ingestion_batch", batch)
            actual.update(
                actual_id="native-arrival-regression",
                batch_id=batch["batch_id"],
                source_record_id="native-arrival-regression",
                source_version="regression",
                revision_no=actual["revision_no"] + 1,
                power_mw=case["actual"] + 17,
                available_at=arrival,
                first_seen_at=arrival,
                created_at=arrival,
            )
            self.store.append("station_actual", actual)
            self.store.db.commit()
            after = wb.context(
                self.store, c["source"]["key"], c["date"], c["model_id"], c["record_id"]
            )
            self.assertEqual(
                after["points"][case["slot"]]["actual"], actual["power_mw"]
            )
            self.assertNotEqual(c["context_version"], after["context_version"])
            self.assertEqual(
                next(p for p in after["cases"] if p["slot"] == case["slot"])["state"],
                "pending",
            )
            self.assertEqual(
                client.post("/api/v1/workspace/commands", json=body).status_code, 400
            )


if __name__ == "__main__":
    unittest.main()
