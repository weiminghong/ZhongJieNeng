"""Public-file scope, changing time windows, calculations and immutable evidence."""

import csv
import json
import os
from pathlib import Path
import sqlite3
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient
from cecep_console.api import create_app
from cecep_console import public_data
from cecep_console.model_settings import ProviderError
from cecep_console.storage import Store


class PublicDataTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.path = self.root / "integration-fixture.csv"
        self.rows = []
        for day in ["2024-01-01", "2024-01-02"]:
            for slot in range(96):
                minutes = (slot+1)*15
                row = {"日期": day, "时刻": f"{minutes//60:02d}:{minutes%60:02d}", "是否节假日": "是"}
                row.update({column: str(slot+100) for column, _ in public_data.FIELDS.values()})
                row["光伏总加(实际)"] = str(slot+101 if slot else -1)
                row["日前价格"] = "200" if slot else ""
                row["实时价格"] = str(209+slot)
                self.rows.append(row)
        self.write_csv()
        self.db_path = self.root/"test.sqlite"
        self.env = patch.dict(os.environ, {"CECEP_PUBLIC_MARKET_CSV": str(self.path), "CECEP_DB_PATH": str(self.db_path), "CECEP_LLM_SETTINGS_PATH": str(self.root/"unused-private.json"), "CECEP_LLM_API_KEY": ""})
        self.env.start()
        self.store = Store(self.db_path); self.store.initialize()

    def tearDown(self):
        self.store.close(); self.env.stop(); public_data._load.cache_clear(); self.tmp.cleanup()

    def write_csv(self):
        with self.path.open("w", encoding="utf-8-sig", newline="") as out:
            writer = csv.DictWriter(out, fieldnames=list(self.rows[0])); writer.writeheader(); writer.writerows(self.rows)

    def test_catalog_actual_dates_hash_and_unavailable_not_synthetic_fallback(self):
        result = public_data.catalog()
        self.assertEqual(result["metadata"]["row_count"], 192)
        self.assertEqual(result["metadata"]["day_count"], 2)
        self.assertEqual(result["default_date"], "2024-01-02")
        self.assertFalse(result["metadata"]["availability_timestamps_verified"])
        self.path.unlink()
        self.assertFalse(public_data.catalog()["available"])

    def test_replay_changes_metrics_and_never_exposes_future_source_fields(self):
        early = public_data.series("2024-01-01", 1)
        later = public_data.series("2024-01-01", 2)
        self.assertEqual(early["summary"]["visible_records"], 1)
        self.assertEqual(later["summary"]["visible_records"], 2)
        self.assertNotEqual(early["summary"]["pv_mae_mw"], later["summary"]["pv_mae_mw"])
        self.assertEqual(early["points"][0]["pv_actual_mw"], -1)
        self.assertIsNone(early["points"][1]["pv_actual_mw"])
        self.assertIsNone(early["points"][1]["source_values"])
        self.assertEqual(early["points"][0]["interval_start"], "2024-01-01T00:00:00+08:00")
        self.assertEqual(public_data.series("2024-01-01")["points"][-1]["interval_end"], "2024-01-02T00:00:00+08:00")
        self.assertIsNone(public_data.series("2024-01-01", 0)["summary"]["pv_mae_mw"])

    def test_scenario_hand_calculation_and_missing_price_are_not_zero(self):
        result = public_data.scenario("2024-01-01", 2, 2, 3)
        self.assertEqual(result["paired_intervals"], 1)
        self.assertEqual(result["unsettled_intervals"], 1)
        self.assertEqual(result["net_spread_yuan"], 14)
        self.assertIsNone(public_data.scenario("2024-01-01", 1, 2, 3)["net_spread_yuan"])
        self.assertNotEqual(public_data.scenario("2024-01-01", 3, 2, 3)["net_spread_yuan"], result["net_spread_yuan"])
        self.assertEqual(self.store.db.execute("SELECT count(*) FROM public_reference_run").fetchone()[0], 0)

    def test_changed_file_updates_revision_and_old_scope_cannot_be_written(self):
        before = public_data.catalog()["metadata"]["source_hash"]
        old_run = public_data.analyze(self.store, "2024-01-01", 2, "check", before)
        self.rows[1]["实时价格"] = "456.789"
        self.write_csv()
        after = public_data.catalog()["metadata"]["source_hash"]
        self.assertNotEqual(before, after)
        self.assertEqual(public_data.series("2024-01-01", 2)["latest"]["rt_price"], 456.789)
        with self.assertRaisesRegex(ValueError, "版本"):
            public_data.review(self.store, "2024-01-01", 2, 1, "review", before)
        public_data.review(self.store, "2024-01-01", 2, 1, "new version review", after)
        all_versions = public_data.history(self.store, None, "2024-01-01")["runs"]
        self.assertEqual(len(all_versions), 2)
        old = next(r for r in all_versions if r["run_id"] == old_run["run_id"])
        self.assertEqual(old["evidence"]["source_records"][1]["rt_price"], 210)
        self.assertEqual(len(public_data.history(self.store, after, "2024-01-01")["runs"]), 1)

    def test_duplicate_time_fails_instead_of_silent_deduplication(self):
        self.rows.append(self.rows[0]); self.write_csv()
        with self.assertRaisesRegex(ValueError, "重复"):
            public_data.catalog()

    def test_analysis_and_review_are_append_only_and_snapshot_source_rows(self):
        source_hash = public_data.catalog()["metadata"]["source_hash"]
        analyzed = public_data.analyze(self.store, "2024-01-01", 2, "inspect", source_hash)
        self.assertEqual(analyzed["llm_mode"], "deterministic_tools_only")
        self.assertEqual(len(analyzed["evidence"]["source_records"]), 2)
        self.assertEqual(analyzed["evidence"]["source_lines"], [2, 3])
        with self.assertRaisesRegex(ValueError, "已经展示"):
            public_data.review(self.store, "2024-01-01", 2, 2, "not visible", source_hash)
        review = public_data.review(self.store, "2024-01-01", 2, 1, "needs validation", source_hash)
        saved = public_data.history(self.store, source_hash, "2024-01-01")["runs"]
        self.assertEqual(saved[0]["run_id"], review["run_id"])
        self.assertFalse(saved[0]["output"]["training_eligible"])
        for sql in ["UPDATE public_reference_run SET answer_text='changed'", "DELETE FROM public_reference_run"]:
            with self.assertRaisesRegex(sqlite3.IntegrityError, "append-only"):
                self.store.db.execute(sql)

    def test_provider_failure_is_visible_and_audited(self):
        source_hash = public_data.catalog()["metadata"]["source_hash"]
        with patch("cecep_console.public_data.load_settings", return_value=SimpleNamespace(ready=True)), patch("cecep_console.public_data.select_evidence", side_effect=ProviderError("provider_unreachable")):
            with TestClient(create_app()) as client:
                response = client.post("/api/v1/public-data/analyze", json={"date": "2024-01-01", "cursor": 2, "source_hash": source_hash})
        self.assertEqual(response.status_code, 502)
        record = self.store.db.execute("SELECT * FROM public_reference_run").fetchone()
        self.assertEqual(record["status"], "provider_failed")
        self.assertEqual(json.loads(record["output_json"])["summary"]["visible_records"], 2)

    def test_api_round_trip_default_scope_validation_and_explicit_scenario_save(self):
        with TestClient(create_app()) as client:
            catalog = client.get("/api/v1/public-data/catalog").json()
            body = {"date": "2024-01-01", "cursor": 2, "source_hash": catalog["metadata"]["source_hash"]}
            self.assertEqual(client.get("/api/v1/public-data/series", params=body).status_code, 200)
            self.assertEqual(client.get("/api/v1/public-data/series", params={**body, "cursor": 97}).status_code, 422)
            self.assertEqual(client.post("/api/v1/public-data/scenario", json={**body, "quantity_mwh": -1}).status_code, 422)
            self.assertEqual(client.post("/api/v1/public-data/scenario", json=body).status_code, 200)
            self.assertEqual(self.store.db.execute("SELECT count(*) FROM public_reference_run").fetchone()[0], 0)
            saved = client.post("/api/v1/public-data/scenario", json={**body, "persist": True})
            self.assertEqual(saved.status_code, 200, saved.text)
            self.assertTrue(saved.json()["saved"]["run_id"])
            self.assertEqual(client.post("/api/v1/public-data/review", json={**body, "selected_slot": 1, "reason": "source review"}).status_code, 200)
            self.assertEqual(len(client.get("/api/v1/public-data/history", params={"date": body["date"], "source_hash": body["source_hash"]}).json()["runs"]), 2)


if __name__ == "__main__":
    unittest.main()
