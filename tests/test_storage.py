"""Adversarial time/version/lineage contracts, backed by a real temporary SQLite DB."""

import json
import os
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from cecep_console.storage import Store, instant, CATALOG, digest, encoded
from cecep_console.storage_demo import seed_demo


class StorageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fixture = tempfile.TemporaryDirectory()
        cls.fixture_db = Path(cls.fixture.name) / "fixture.sqlite"
        with Store(cls.fixture_db) as store:
            store.initialize()
            seed_demo(store)

    @classmethod
    def tearDownClass(cls):
        cls.fixture.cleanup()

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.tmp.name) / "test.sqlite")
        with closing(sqlite3.connect(self.fixture_db)) as source:
            source.backup(self.store.db)

    def tearDown(self):
        self.store.close()
        self.tmp.cleanup()

    def actual(self):
        return dict(
            self.store.db.execute(
                "SELECT * FROM station_actual WHERE station_id='lanneng' ORDER BY interval_start LIMIT 1"
            ).fetchone()
        )

    def test_initialization_idempotent_and_packaged_schema(self):
        self.store.initialize()
        self.store.initialize()
        self.assertEqual(self.store.inspect()["integrity"], "ok")
        self.assertEqual(self.store.inspect()["foreign_key_errors"], [])
        self.assertEqual(len(CATALOG), 34)
        for table, definition in CATALOG.items():
            self.assertEqual(
                {x[1] for x in self.store.db.execute(f"PRAGMA table_info({table})")},
                set(definition["fields"]) | {definition["pk"]},
            )

    def test_seed_is_idempotent(self):
        self.assertEqual(seed_demo(self.store)["inserted"], 0)

    def test_synthetic_requires_explicit_opt_in(self):
        self.assertEqual(
            self.store.as_of("station_actual", "2026-11-20T14:00:00+08:00"), []
        )
        self.assertTrue(
            self.store.as_of(
                "station_actual", "2026-11-20T14:00:00+08:00", allow_synthetic=True
            )
        )

    def test_future_actual_and_timezone(self):
        cutoff = "2026-11-20T10:00:00+08:00"
        rows = self.store.as_of("station_actual", cutoff, allow_synthetic=True)
        self.assertTrue(all(r["interval_end"] <= instant(cutoff) for r in rows))
        self.assertEqual(instant(cutoff), instant("2026-11-20T02:00:00Z"))
        with self.assertRaises(ValueError):
            instant("2026-11-20T10:00:00")

    def test_late_revision_never_rewrites_earlier_view(self):
        original = self.actual()
        revision = {
            **original,
            "actual_id": "late",
            "revision_no": 1,
            "power_mw": 99,
            "available_at": "2026-11-22T10:00:00+08:00",
            "first_seen_at": "2026-11-22T10:00:00+08:00",
            "published_at": "2026-11-22T10:00:00+08:00",
        }
        self.store.ingest({"station_actual": [revision]})
        filters = {
            "station_id": "lanneng",
            "interval_start": original["interval_start"],
        }
        before = self.store.as_of(
            "station_actual",
            "2026-11-20T14:00:00+08:00",
            filters=filters,
            allow_synthetic=True,
        )
        after = self.store.as_of(
            "station_actual",
            "2026-11-23T14:00:00+08:00",
            filters=filters,
            allow_synthetic=True,
        )
        self.assertEqual(before[0]["actual_id"], original["actual_id"])
        self.assertEqual(after[0]["power_mw"], 99)

    def test_unknown_latest_revision_does_not_resurrect_old_data(self):
        original = self.actual()
        revision = {
            **original,
            "actual_id": "unknown",
            "revision_no": 1,
            "availability_basis": "unknown",
        }
        self.store.ingest({"station_actual": [revision]})
        rows = self.store.as_of(
            "station_actual",
            "2026-11-20T14:00:00+08:00",
            filters={
                "interval_start": original["interval_start"],
                "station_id": "lanneng",
            },
            allow_synthetic=True,
        )
        self.assertEqual(rows, [])

    def test_source_batch_mismatch_rejected_atomically(self):
        source = dict(self.store.db.execute("SELECT * FROM data_source").fetchone())
        source.update(source_id="other-source", source_name="Other source")
        bad = {**self.actual(), "actual_id": "bad-source", "source_id": "other-source"}
        with self.assertRaises(sqlite3.IntegrityError):
            self.store.ingest({"data_source": [source], "station_actual": [bad]})
        self.assertIsNone(
            self.store.db.execute(
                "SELECT 1 FROM data_source WHERE source_id='other-source'"
            ).fetchone()
        )

    def test_immutable_conflicts_and_nonfinite_values(self):
        original = self.actual()
        with self.assertRaises(ValueError):
            self.store.append("station_actual", {**original, "power_mw": 91})
        with self.assertRaises(ValueError):
            self.store.append(
                "station_actual",
                {**original, "actual_id": "nan", "power_mw": float("nan")},
            )
        with self.assertRaises(sqlite3.IntegrityError):
            self.store.db.execute("UPDATE station_actual SET power_mw=3")

    def test_observation_cannot_arrive_before_interval_end(self):
        row = {
            **self.actual(),
            "actual_id": "too-early",
            "interval_end": "2026-11-25T00:00:00Z",
        }
        with self.assertRaises(sqlite3.IntegrityError):
            self.store.ingest({"station_actual": [row]})

    def test_configuration_is_also_point_in_time(self):
        row = dict(
            self.store.db.execute(
                "SELECT * FROM station_config_version WHERE station_id='lanneng'"
            ).fetchone()
        )
        updated = {
            **row,
            "config_version_id": "late-config",
            "revision_no": 1,
            "capacity_ac_mw": 150,
            "available_at": "2026-11-22T00:00:00Z",
        }
        self.store.ingest({"station_config_version": [updated]})
        actual = self.store.as_of(
            "station_config_version",
            "2026-11-20T00:00:00Z",
            filters={"station_id": "lanneng"},
            target="2026-11-23T00:00:00Z",
            allow_synthetic=True,
        )
        self.assertEqual(actual[0]["capacity_ac_mw"], 112)

    def test_prebid_has_no_future_day_ahead_actual_price(self):
        payload = self.store.bundle(
            "prebid_spread",
            "lanneng",
            "2026-11-20T00:00:00+08:00",
            "2026-11-21T00:00:00+08:00",
            "2026-11-19T09:00:00+08:00",
            allow_synthetic=True,
        )
        self.assertTrue(
            all(
                r["interval_end"] <= payload["cutoff_at"]
                for r in payload["records"]["market_price"]
            )
        )

    def test_intraday_requires_published_baseline_and_snapshot_lineage(self):
        payload = self.store.bundle(
            "intraday_spread",
            "lanneng",
            "2026-11-20T11:00:00+08:00",
            "2026-11-20T12:00:00+08:00",
            "2026-11-20T10:00:00+08:00",
            allow_synthetic=True,
            persist=True,
        )
        self.assertNotIn("published_day_ahead_price", payload["missing"])
        self.assertIn("market_supply_forecast", payload["missing"])
        for table, rows in payload["records"].items():
            self.assertTrue(
                all(r["available_at"] <= payload["cutoff_at"] for r in rows)
            )
        saved = self.store.db.execute(
            "SELECT * FROM feature_snapshot WHERE snapshot_id=?",
            (payload["snapshot_id"],),
        ).fetchone()
        self.assertEqual(
            digest(json.loads(saved["payload_json"])), saved["content_hash"]
        )

    def test_prediction_outputs_obey_issue_time_and_mode(self):
        args = (
            "lanneng",
            "day_ahead_power",
            "2026-11-20T00:00:00+08:00",
            "2026-11-21T00:00:00+08:00",
        )
        self.assertEqual(
            self.store.predictions(*args, "2026-11-18T00:00:00Z", allow_synthetic=True),
            [],
        )
        self.assertEqual(self.store.predictions(*args, "2026-11-20T00:00:00Z"), [])
        self.assertEqual(
            len(
                self.store.predictions(
                    *args, "2026-11-20T00:00:00Z", allow_synthetic=True
                )
            ),
            384,  # Original scenario plus three independently versioned day-ahead runs.
        )

    def test_invalid_prediction_snapshot_link_rejected(self):
        run = dict(
            self.store.db.execute("SELECT * FROM prediction_run LIMIT 1").fetchone()
        )
        run.update(run_id="mismatched", cutoff_at="2026-11-15T00:00:00Z")
        with self.assertRaises(sqlite3.IntegrityError):
            self.store.ingest({"prediction_run": [run]})

    def test_missing_is_not_zero(self):
        rows = self.store.as_of(
            "station_actual", "2026-11-20T14:00:00+08:00", allow_synthetic=True
        )
        self.assertTrue(
            any(r["power_mw"] is None and r["quality_flag"] == "missing" for r in rows)
        )
        self.assertTrue(
            any(r["power_mw"] == 0 and r["quality_flag"] == "valid" for r in rows)
        )

    def test_filters_cannot_inject_sql(self):
        with self.assertRaises(ValueError):
            self.store.as_of(
                "station_actual",
                "2026-11-20T14:00:00+08:00",
                filters={"station_id OR 1=1": "x"},
            )
        with self.assertRaises(ValueError):
            self.store.as_of(
                "station_actual; DROP TABLE station", "2026-11-20T14:00:00+08:00"
            )


if __name__ == "__main__":
    unittest.main()
