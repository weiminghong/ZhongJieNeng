"""Migration, PIT routing, real SQLite writes and complete API contracts."""

from contextlib import closing
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch
from fastapi.testclient import TestClient
from cecep_console.storage import Store, BASE, instant, CATALOG
from cecep_console.storage_demo import seed_demo
from cecep_console.serving import (
    refresh_serving_tables,
    build_intervals,
    data_clock,
    now,
    metrics,
    daily_kpi,
)
from cecep_console.trading import settle_interval, simulate_plan
from cecep_console.agent_service import search_knowledge_rag
from cecep_console.rsi import (
    review_feedback,
    ingest_feedback,
    approve_model,
    model_states,
    rsi_overview,
)
from cecep_console.api import create_app


class WorkbenchTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.fixture = Path(cls.tmp.name) / "fixture.sqlite"
        with Store(cls.fixture) as store:
            store.initialize()
            seed_demo(store)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def setUp(self):
        self.tmpcase = tempfile.TemporaryDirectory()
        self.path = Path(self.tmpcase.name) / "test.sqlite"
        self.store = Store(self.path)
        with closing(sqlite3.connect(self.fixture)) as source:
            source.backup(self.store.db)
        self.env = patch.dict(os.environ, {"CECEP_DB_PATH": str(self.path)})
        self.env.start()

    def tearDown(self):
        self.env.stop()
        self.store.close()
        self.tmpcase.cleanup()

    def test_001_upgrade_preserves_data_and_checksum(self):
        oldpath = Path(self.tmpcase.name) / "old.sqlite"
        script = (BASE / "storage_sql/001_initial.sql").read_text(encoding="utf-8")
        checksum = hashlib.sha256(script.encode()).hexdigest()
        with Store(oldpath) as old:
            old.db.executescript(script)
            old.db.execute(
                "CREATE TABLE schema_migration(version INTEGER PRIMARY KEY,checksum TEXT NOT NULL,applied_at TEXT NOT NULL)"
            )
            old.db.execute(
                "INSERT INTO schema_migration VALUES(1,?,?)", (checksum, now())
            )
            sentinel = dict(
                self.store.db.execute("SELECT * FROM data_source LIMIT 1").fetchone()
            )
            sentinel.update(source_id="sentinel", source_name="preserved")
            old.append("data_source", sentinel)
            old.db.commit()
            old.initialize()
            self.assertEqual(
                old.db.execute(
                    "SELECT source_name FROM data_source WHERE source_id='sentinel'"
                ).fetchone()[0],
                "preserved",
            )
            self.assertEqual(
                old.db.execute(
                    "SELECT checksum FROM schema_migration WHERE version=1"
                ).fetchone()[0],
                checksum,
            )
            self.assertEqual(old.inspect()["schema_version"], 7)
            self.assertEqual(
                len(old.db.execute("SELECT * FROM schema_migration").fetchall()), 7
            )
            old.initialize()

    def test_checksum_mismatch_is_rejected(self):
        self.store.db.execute(
            "UPDATE schema_migration SET checksum='wrong' WHERE version=1"
        )
        self.store.db.commit()
        with self.assertRaisesRegex(ValueError, "checksum"):
            self.store.initialize()

    def test_serving_refresh_idempotent_and_lineage_cutoff(self):
        before = self.store.db.execute(
            "SELECT count(*) FROM serving_interval_wide"
        ).fetchone()[0]
        with self.store.db:
            refresh_serving_tables(self.store, "lanneng")
        self.assertEqual(
            self.store.db.execute(
                "SELECT count(*) FROM serving_interval_wide"
            ).fetchone()[0],
            before,
        )
        cutoff = instant("2026-11-20T09:00:00+08:00")
        intervals = build_intervals(self.store, "lanneng", "2026-11-20", cutoff)
        self.assertEqual(len(intervals), 96)
        self.assertTrue(
            all(r["actual_mw"] is None for r in intervals if r["interval_end"] > cutoff)
        )
        self.assertTrue(
            all(
                ref["available_at"] <= cutoff
                for r in intervals
                for ref in json.loads(r["lineage_refs_json"])
            )
        )
        self.assertTrue(all(r["id_corrected_mw"] is None for r in intervals))

    def test_deterministic_settlement_hand_calculated(self):
        actual = settle_interval(10, 8, 5, 380, 300, 400, 0.5, 600)
        self.assertEqual(
            actual,
            {"contract": 1900, "day_ahead": 900, "real_time": 800, "penalty": -900},
        )
        self.assertEqual(sum(actual.values()), 2700)
        self.assertEqual(
            settle_interval(8.5, 8, 5, 380, 300, 400, 0.5, 600)["penalty"], 0
        )
        with self.assertRaises(ValueError):
            settle_interval(None, 8, 5, 380, 300, 400, 0.5, 600)

    def test_revenue_reuses_identical_run_and_missing_is_unsettled(self):
        pid = self.store.db.execute(
            "SELECT plan_id FROM bidding_plan WHERE station_id='lanneng' AND trading_date='2026-11-20' LIMIT 1"
        ).fetchone()[0]
        with self.store.db:
            a = simulate_plan(self.store, pid, persist=True)
            b = simulate_plan(self.store, pid, persist=True)
        self.assertEqual(a["revenue_run_id"], b["revenue_run_id"])
        self.assertEqual(a["settled_count"], 55)
        self.assertEqual(a["unsettled_count"], 41)
        total = self.store.db.execute(
            "SELECT sum(amount_yuan) FROM revenue_item WHERE revenue_run_id=?",
            (a["revenue_run_id"],),
        ).fetchone()[0]
        self.assertAlmostEqual(a["net_revenue_yuan"], total, places=6)

    def test_fts_and_confirmed_feedback_ingestion(self):
        fts = self.store.db.execute(
            "SELECT chunk_id FROM rag_chunk_fts WHERE rag_chunk_fts MATCH ?",
            ('"偏差"',),
        ).fetchall()
        self.assertTrue(fts)
        results = search_knowledge_rag(self.store, "偏差免考合约结算", "lanneng", now())
        self.assertTrue(any(r["collection"] == "market_rule" for r in results))
        case = self.store.db.execute(
            "SELECT case_id FROM deviation_case WHERE station_id='lanneng' LIMIT 1"
        ).fetchone()[0]
        with self.store.db:
            feedback = review_feedback(self.store, case, "唯一复核测试云团变化", False)
            document = ingest_feedback(self.store, feedback["feedback_id"])
            duplicate = ingest_feedback(self.store, feedback["feedback_id"])
        self.assertEqual(duplicate["status"], "already_ingested")
        results = search_knowledge_rag(
            self.store, "唯一复核测试云团变化", "lanneng", now()
        )
        self.assertIn(document["chunk_id"], [r["chunk_id"] for r in results])
        past = search_knowledge_rag(
            self.store, "唯一复核测试云团变化", "lanneng", data_clock(self.store)
        )
        self.assertNotIn(document["chunk_id"], [r["chunk_id"] for r in past])
        with self.assertRaises(ValueError):
            ingest_feedback(self.store, "nonexistent")

    def test_approval_and_rollback_append_events_and_preserve_models(self):
        original = self.store.db.execute(
            "SELECT status FROM model_version WHERE model_version_id='lgbm-demo-v2.1'"
        ).fetchone()[0]
        with self.store.db:
            approved = approve_model(
                self.store, "demo-candidate-v2.2", "approve", "人工确认合成测试"
            )
        states = {
            m["model_version_id"]: m["effective_status"]
            for m in model_states(self.store)
        }
        self.assertEqual(states["lgbm-demo-v2.2-cand"], "production")
        self.assertEqual(states["lgbm-demo-v2.1"], "archived")
        self.assertEqual(len(approved["events"]), 2)
        with self.store.db:
            approve_model(self.store, "demo-candidate-v2.2", "rollback", "回滚验证")
        states = {
            m["model_version_id"]: m["effective_status"]
            for m in model_states(self.store)
        }
        self.assertEqual(states["lgbm-demo-v2.1"], "production")
        self.assertEqual(states["lgbm-demo-v2.2-cand"], "rolled_back")
        self.assertEqual(
            self.store.db.execute(
                "SELECT status FROM model_version WHERE model_version_id='lgbm-demo-v2.1'"
            ).fetchone()[0],
            original,
        )
        self.assertEqual(
            self.store.db.execute(
                "SELECT count(*) FROM model_lifecycle_event"
            ).fetchone()[0],
            4,
        )

    def test_upper_audit_is_immutable_and_fk_integrity(self):
        with self.assertRaises(sqlite3.IntegrityError):
            self.store.db.execute("DELETE FROM rag_chunk")
        self.assertEqual(self.store.inspect()["foreign_key_errors"], [])

    def test_replay_hides_later_governance_events_and_model_promotion(self):
        cutoff = instant("2026-11-20T09:00:00+08:00")
        before = build_intervals(
            self.store, "lanneng", "2026-11-20", cutoff, registry_cutoff=cutoff
        )
        with self.store.db:
            approve_model(
                self.store, "demo-candidate-v2.2", "approve", "回放状态隔离验证"
            )
        after = build_intervals(
            self.store, "lanneng", "2026-11-20", cutoff, registry_cutoff=cutoff
        )
        self.assertEqual(
            [r["da_forecast_mw"] for r in before],
            [r["da_forecast_mw"] for r in after],
        )
        governance = rsi_overview(self.store, "lanneng", "2026-11-20", cutoff=cutoff)
        self.assertEqual(governance["cases"], [])
        self.assertEqual(governance["lifecycle"], [])
        self.assertEqual(governance["candidates"], [])
        states = {
            m["model_version_id"]: m["effective_status"] for m in governance["models"]
        }
        self.assertEqual(states["lgbm-demo-v2.1"], "production")

    def test_api_all_reads_and_performance_route(self):
        with TestClient(create_app()) as client:
            with patch(
                "cecep_console.api.build_intervals",
                side_effect=AssertionError("live must not invoke PIT"),
            ):
                r = client.get("/api/v1/workbench/overview")
                self.assertEqual(r.status_code, 200)
                self.assertIn("serving_", r.json()["query_path"])
                self.assertEqual(len(r.json()["intervals"]), 96)
            for endpoint in ["bootstrap", "raw", "compare", "trading", "rsi"]:
                self.assertEqual(
                    client.get("/api/v1/workbench/" + endpoint).status_code,
                    200,
                    endpoint,
                )
            r = client.get(
                "/api/v1/workbench/overview",
                params={"mode": "replay", "cutoff_at": "2026-11-20T09:00:00+08:00"},
            )
            self.assertEqual(r.status_code, 200)
            self.assertIn("pit_engine", r.json()["query_path"])
            self.assertEqual(
                client.get(
                    "/api/v1/workbench/overview", params={"mode": "replay"}
                ).status_code,
                400,
            )
            self.assertEqual(
                client.get(
                    "/api/v1/workbench/overview", params={"date": "bad"}
                ).status_code,
                400,
            )
            self.assertEqual(
                client.get(
                    "/api/v1/workbench/overview", params={"source_mode": "production"}
                ).json()["intervals"],
                [],
            )
            interval = client.get("/api/v1/workbench/raw").json()["intervals"][48][
                "interval_start"
            ]
            lineage = client.get(
                "/api/v1/workbench/lineage", params={"interval_start": interval}
            )
            self.assertEqual(lineage.status_code, 200)
            self.assertTrue(
                all(e["available_before_cutoff"] for e in lineage.json()["evidence"])
            )
            self.assertEqual(
                client.post(
                    "/api/v1/workbench/trading/recalculate", json={}
                ).status_code,
                200,
            )
            self.assertEqual(client.get("/api/v1/does-not-exist").status_code, 404)

    def test_api_all_writes_and_persistence(self):
        with (
            TestClient(create_app()) as client,
            patch.dict(os.environ, {"CECEP_LLM_API_KEY": ""}),
        ):
            result = client.post(
                "/api/v1/agent/query", json={"question": "偏差考核和合约收益的依据？"}
            )
            self.assertEqual(result.status_code, 200, result.text)
            agent = result.json()
            self.assertEqual(agent["llm_mode"], "deterministic_tools_only")
            self.assertEqual(len(agent["tool_calls"]), 6)
            self.assertTrue(agent["citations"])
            case = client.get("/api/v1/workbench/rsi").json()["cases"][0]
            f = client.post(
                "/api/v1/rsi/feedback",
                json={
                    "case_id": case["case_id"],
                    "reason": "API确认云团测试",
                    "training_eligible": False,
                },
            )
            self.assertEqual(f.status_code, 200)
            self.assertEqual(
                client.post(
                    "/api/v1/rsi/rag-ingest",
                    json={"feedback_id": f.json()["feedback_id"]},
                ).status_code,
                200,
            )
            for action in ["approve", "rollback"]:
                result = client.post(
                    "/api/v1/rsi/approve",
                    json={
                        "candidate_id": "demo-candidate-v2.2",
                        "action": action,
                        "reason": "API生命周期验收",
                    },
                )
                self.assertEqual(result.status_code, 200, result.text)
        with TestClient(create_app()) as client:
            self.assertEqual(
                client.get("/api/v1/agent/history").json()["history"][0]["response_id"],
                agent["response_id"],
            )
            cases = client.get("/api/v1/workbench/rsi").json()["cases"]
            self.assertTrue(
                next(c for c in cases if c["case_id"] == case["case_id"])["rag_doc_id"]
            )
        with Store(self.path, readonly=True) as check:
            self.assertEqual(
                check.db.execute(
                    "SELECT count(*) FROM agent_tool_call WHERE agent_run_id=?",
                    (agent["agent_run_id"],),
                ).fetchone()[0],
                6,
            )
            self.assertEqual(check.inspect()["foreign_key_errors"], [])

    def test_provider_failure_is_explicit_and_audited(self):
        with (
            TestClient(create_app()) as client,
            patch.dict(os.environ, {"CECEP_LLM_API_KEY": "test-only"}),
            patch("cecep_console.agent_service.urlopen", side_effect=TimeoutError()),
        ):
            result = client.post("/api/v1/agent/query", json={"question": "偏差"})
            self.assertEqual(result.status_code, 502)
            self.assertEqual(result.json()["llm_mode"], "provider_failed")
            self.assertFalse(result.json()["grounded_check_passed"])
            self.assertEqual(
                client.get("/api/v1/agent/history").json()["history"][0]["llm_mode"],
                "provider_failed",
            )

    def test_legacy_storage_routes(self):
        with TestClient(create_app()) as client:
            self.assertEqual(
                client.get("/api/storage/health").json()["schema_version"], 7
            )
            common = {"cutoff": "2026-11-20T14:00:00+08:00", "demo": "1"}
            self.assertEqual(
                client.get(
                    "/api/storage/query", params={**common, "table": "station_actual"}
                ).status_code,
                200,
            )
            scope = {
                **common,
                "station": "lanneng",
                "task": "day_ahead_power",
                "start": "2026-11-21T00:00:00+08:00",
                "end": "2026-11-22T00:00:00+08:00",
            }
            self.assertEqual(
                client.get("/api/storage/features", params=scope).status_code, 200
            )
            self.assertEqual(
                client.get("/api/storage/predictions", params=scope).status_code, 200
            )
            self.assertEqual(
                client.get(
                    "/api/storage/query", params={**common, "table": "bad"}
                ).status_code,
                400,
            )

    def test_metrics_bias_skill_coverage_and_direction_hand_calculated(self):
        m = metrics(
            [10, 4, 8, None], [8, 6, 8, 10], [6, 8, 4, 0], [8, 5, 7, 0], [11, 7, 9, 20]
        )
        self.assertEqual(m["mbe"], 0)
        self.assertAlmostEqual(m["rmse"], (8 / 3) ** 0.5)
        self.assertAlmostEqual(m["skill_score"], 1 - (8 / 3) ** 0.5 / 4)
        self.assertAlmostEqual(m["interval_coverage_pct"], 200 / 3)
        self.assertEqual(
            m["direction_breakdown"],
            {
                "positive": {"count": 1, "mean_bias_mw": 2},
                "negative": {"count": 1, "mean_bias_mw": -2},
                "zero_count": 1,
            },
        )
        self.assertEqual(metrics([10, 8], [7, 7])["mbe"], 2)

    def test_metrics_missing_and_zero_baseline_stay_null(self):
        for baseline in (None, [10, 8], [9, None]):
            m = metrics([10, 8], [7, 7], baseline)
            self.assertIsNone(m["skill_score"])
        self.assertIsNone(metrics([], [])["mbe"])
        self.assertIsNone(
            metrics([10], [8], lower=[None], upper=[12])["interval_coverage_pct"]
        )
        self.assertEqual(
            metrics([10, None], [8, None], lower=[10, 0], upper=[10, 0])[
                "interval_coverage_pct"
            ],
            100,
        )

    def multi(self, **params):
        with TestClient(create_app()) as client:
            r = client.get("/api/v1/workbench/multi-day", params=params)
            self.assertEqual(r.status_code, 200, r.text)
            return r.json()

    def test_multi_day_aggregation_and_source_isolation(self):
        with patch(
            "cecep_console.workbench_analytics.build_intervals",
            side_effect=AssertionError("live uses serving"),
        ):
            data = self.multi()
        self.assertGreaterEqual(len(data["days"]), 2)
        self.assertEqual(len(data["series"]), 96 * len(data["days"]))
        self.assertEqual(
            sorted(r["interval_start"] for r in data["series"]),
            [r["interval_start"] for r in data["series"]],
        )
        for d in data["days"]:
            paired = [
                r
                for r in data["series"]
                if r["trading_date"] == d["trading_date"]
                and r["actual_mw"] is not None
                and r["da_forecast_mw"] is not None
            ]
            if paired:
                self.assertAlmostEqual(
                    d["mbe_mw"],
                    sum(r["actual_mw"] - r["da_forecast_mw"] for r in paired)
                    / len(paired),
                )
                self.assertAlmostEqual(
                    d["energy_forecast_matched_mwh"],
                    sum(r["da_forecast_mw"] * 0.25 for r in paired),
                )
        self.assertEqual(self.multi(source_mode="production")["series"], [])
        self.assertEqual(self.multi(station_id="unknown")["days"], [])

    def test_multi_day_heatmap_matrix_and_missing_cells(self):
        data = self.multi()
        heatmap = data["price_heatmap"]
        self.assertEqual(heatmap["hours"], list(range(24)))
        self.assertEqual(len(heatmap["cells"]), len(heatmap["dates"]) * 24)
        self.assertEqual(
            len({(r["trading_date"], r["hour"]) for r in heatmap["cells"]}),
            len(heatmap["cells"]),
        )
        from cecep_console.workbench_analytics import hour

        nulls = 0
        for c in heatmap["cells"]:
            rs = [
                r["rt_price"]
                for r in data["series"]
                if r["trading_date"] == c["trading_date"]
                and hour(r) == c["hour"]
                and r["rt_price"] is not None
            ]
            if rs:
                self.assertAlmostEqual(c["rt_price"], sum(rs) / len(rs))
            else:
                nulls += 1
                self.assertIsNone(c["rt_price"])
        self.assertGreater(nulls, 0)

    def test_multi_day_weather_bucket_boundaries_and_metrics(self):
        # Serving is a disposable read projection; original evidence stays append-only.
        with self.store.db:
            self.store.db.execute(
                "UPDATE serving_interval_wide SET cloud_cover_pct=CASE WHEN actual_mw IS NULL THEN NULL WHEN actual_mw=0 THEN 25 ELSE 60 END WHERE station_id='lanneng'"
            )
        data = self.multi()
        for bucket, lo, hi in zip(data["weather_buckets"], [0, 25, 60], [25, 60, 101]):
            rs = [
                r
                for r in data["series"]
                if r["actual_mw"] is not None
                and r["da_forecast_mw"] is not None
                and r["cloud_cover_pct"] is not None
                and lo <= r["cloud_cover_pct"] < hi
            ]
            self.assertEqual(bucket["sample_count"], len(rs))
            if rs:
                errors = [r["actual_mw"] - r["da_forecast_mw"] for r in rs]
                self.assertAlmostEqual(bucket["mae"], sum(map(abs, errors)) / len(rs))
                self.assertAlmostEqual(
                    bucket["rmse"], (sum(e * e for e in errors) / len(rs)) ** 0.5
                )
                self.assertAlmostEqual(bucket["mbe"], sum(errors) / len(rs))
            else:
                self.assertIsNone(bucket["mae"])
        self.assertEqual(data["weather_buckets"][0]["sample_count"], 0)

    def test_multi_day_time_buckets_exclude_night_and_missing(self):
        from cecep_console.workbench_analytics import hour

        data = self.multi()
        count = 0
        for bucket, lo in zip(data["time_buckets"], [6, 9, 12, 15]):
            rs = [
                r
                for r in data["series"]
                if lo <= hour(r) < lo + 3
                and r["actual_mw"] is not None
                and r["da_forecast_mw"] is not None
            ]
            self.assertEqual(bucket["sample_count"], len(rs))
            count += len(rs)
        self.assertLess(count, sum(d["observed_count"] for d in data["days"]))

    def test_multi_day_price_backtest_and_periods(self):
        data = self.multi()
        b = data["price_periods"]["price_backtest"]
        da = [
            r
            for r in data["series"]
            if r["da_price"] is not None and r["da_pred_price"] is not None
        ]
        sp = [
            r
            for r in data["series"]
            if r["spread_yuan_mwh"] is not None
            and r["rt_pred_price"] is not None
            and r["da_price"] is not None
        ]
        sign = lambda v: (v > 0) - (v < 0)
        self.assertEqual(b["da_price_sample_count"], len(da))
        self.assertEqual(b["sample_count"], len(sp))
        self.assertAlmostEqual(
            b["da_price_mae"],
            sum(abs(r["da_price"] - r["da_pred_price"]) for r in da) / len(da),
        )
        self.assertAlmostEqual(
            b["spread_direction_accuracy_pct"],
            100
            * sum(
                sign(r["spread_yuan_mwh"]) == sign(r["rt_pred_price"] - r["da_price"])
                for r in sp
            )
            / len(sp),
        )
        self.assertEqual(len(data["price_periods"]["periods"]), 4)
        self.assertEqual(
            sum(p["sample_count"] for p in data["price_periods"]["periods"]),
            sum(r["spread_yuan_mwh"] is not None for r in data["series"]),
        )
        for key in ("max_positive", "max_negative"):
            extreme = data["price_periods"][key]
            if extreme:
                self.assertIn(
                    extreme["interval_start"],
                    [r["interval_start"] for r in data["series"]],
                )

    def test_multi_day_replay_strict_pit_and_ignores_cache(self):
        cutoff = instant("2026-11-20T09:00:00+08:00")
        before = self.multi(mode="replay", cutoff_at=cutoff)
        with self.store.db:
            self.store.db.execute(
                "UPDATE serving_interval_wide SET actual_mw=99999,cloud_cover_pct=99"
            )
            approve_model(
                self.store, "demo-candidate-v2.2", "approve", "多日PIT隔离测试"
            )
        with patch(
            "cecep_console.workbench_analytics.build_intervals", wraps=build_intervals
        ) as pit:
            after = self.multi(mode="replay", cutoff_at=cutoff)
            self.assertTrue(pit.called)
            self.assertTrue(
                all(c.kwargs["registry_cutoff"] == cutoff for c in pit.call_args_list)
            )
        self.assertEqual(before["days"], after["days"])
        self.assertTrue(
            all(
                r["actual_mw"] is None
                for r in after["series"]
                if r["interval_end"] > cutoff
            )
        )
        self.assertTrue(
            all(
                ref["available_at"] <= cutoff
                for r in after["series"]
                for ref in json.loads(r["lineage_refs_json"])
            )
        )
        with TestClient(create_app()) as client:
            self.assertEqual(
                client.get("/api/v1/workbench/multi-day?mode=replay").status_code, 400
            )

    def test_new_metrics_present_on_daily_overview_and_versions(self):
        with TestClient(create_app()) as client:
            data = client.get("/api/v1/workbench/overview").json()
            expected = daily_kpi(data["intervals"], data["cutoff_at"])
            for key in (
                "mbe",
                "skill_score",
                "interval_coverage_pct",
                "direction_breakdown",
            ):
                self.assertEqual(data["kpi"][key], expected[key])
            versions = client.get("/api/v1/workbench/compare").json()["versions"]
            self.assertTrue(versions)
            actual = {r["interval_start"]: r for r in data["intervals"]}
            for v in versions:
                vals = {r["interval_start"]: r["value"] for r in v["values"]}
                errors = [
                    actual[k]["actual_mw"] - vals[k] for k in v["matched_intervals"]
                ]
                self.assertAlmostEqual(v["mbe"], sum(errors) / len(errors))
                self.assertIn("skill_score", v)
                self.assertIn("interval_coverage_pct", v)

    def test_sandbox_manual_parameters_and_no_side_effects(self):
        from cecep_console.serving import day_bounds, rows
        from cecep_console.api import SandboxInput, overview, resolve_scope
        from cecep_console.workbench_analytics import trading_sandbox

        body = SandboxInput(
            bid_multiplier=1.2, exempt_fraction=0.01, penalty_yuan_mwh=400
        )
        # Direct invocation also verifies total_changes, including attempted writes.
        scope = body.model_copy()
        from cecep_console.api import Scope

        regular = Scope(
            **body.model_dump(
                exclude={
                    "plan_id",
                    "bid_multiplier",
                    "exempt_fraction",
                    "penalty_yuan_mwh",
                }
            )
        )
        cutoff = resolve_scope(regular, self.store)
        evidence = overview(self.store, regular)["intervals"]
        changes = self.store.db.total_changes
        count = self.store.db.execute("SELECT count(*) FROM revenue_run").fetchone()[0]
        a = trading_sandbox(self.store, scope, cutoff, evidence)
        b = trading_sandbox(self.store, scope, cutoff, evidence)
        self.assertEqual(a, b)
        self.assertEqual(self.store.db.total_changes, changes)
        start, _ = day_bounds(body.date)
        capacity = self.store.as_of(
            "station_config_version",
            cutoff,
            filters={"station_id": body.station_id},
            target=start,
            allow_synthetic=True,
        )[0]["capacity_ac_mw"]
        bids = {
            r["interval_start"]: r
            for r in rows(
                self.store,
                "SELECT * FROM bidding_plan_item WHERE plan_id=?",
                (a["plan_id"],),
            )
        }
        contracts = {
            r["interval_start"]: r
            for r in rows(
                self.store,
                "SELECT * FROM contract_position WHERE station_id=? AND available_at<=? ORDER BY revision_no",
                (body.station_id, cutoff),
            )
        }
        totals = {k: 0.0 for k in ("contract", "day_ahead", "real_time", "penalty")}
        n = 0
        for r in evidence:
            if r["interval_start"] not in bids or any(
                r[k] is None for k in ("actual_mw", "da_price", "rt_price")
            ):
                continue
            item, c = bids[r["interval_start"]], contracts[r["interval_start"]]
            bid, actual = item["bid_energy_mwh"] * 1.2, r["actual_mw"] * 0.25
            totals["contract"] += (
                c["contract_energy_mwh"] * c["contract_price_yuan_mwh"]
            )
            totals["day_ahead"] += (bid - c["contract_energy_mwh"]) * r["da_price"]
            totals["real_time"] += (actual - bid) * r["rt_price"]
            totals["penalty"] -= (
                max(0, abs(actual - bid) - capacity * 0.01 * 0.25) * 400
            )
            n += abs(actual - bid) > capacity * 0.01 * 0.25
        self.assertEqual(a["simulated"]["exceeded_count"], n)
        for k in totals:
            self.assertAlmostEqual(a["simulated"]["components"][k], totals[k])
        self.assertAlmostEqual(a["simulated"]["net_revenue_yuan"], sum(totals.values()))
        with TestClient(create_app()) as client:
            for payload in (
                {},
                {"bid_multiplier": 0.7},
                {"exempt_fraction": 0.15},
                {"penalty_yuan_mwh": 0},
            ):
                r = client.post("/api/v1/workbench/trading/sandbox", json=payload)
                self.assertEqual(r.status_code, 200, r.text)
            self.assertEqual(
                self.store.db.execute("SELECT count(*) FROM revenue_run").fetchone()[0],
                count,
            )

    def test_sandbox_default_matches_existing_and_risk_weights(self):
        with TestClient(create_app()) as client:
            r = client.post("/api/v1/workbench/trading/sandbox", json={})
            self.assertEqual(r.status_code, 200, r.text)
            data = r.json()
        self.assertEqual(data["baseline"], data["simulated"])
        self.assertEqual(data["delta_net_revenue_yuan"], 0)
        plan = simulate_plan(self.store, data["plan_id"])
        self.assertEqual(data["settled_count"], plan["settled_count"])
        self.assertAlmostEqual(
            data["baseline"]["net_revenue_yuan"], plan["net_revenue_yuan"]
        )
        risk = data["risk_assessment"]
        self.assertAlmostEqual(
            risk["overall_score"],
            0.4 * risk["price_risk"]
            + 0.3 * risk["deviation_risk"]
            + 0.3 * risk["weather_risk"],
        )
        self.assertTrue(0 <= risk["overall_score"] <= 100)
        self.assertEqual(sum(r["active"] for r in data["strategy_matrix"]), 1)
        self.assertTrue(
            all(r["source_mode"] == "synthetic" for r in data["strategy_matrix"])
        )

    def test_sandbox_invalid_parameters_422_and_plan_scope(self):
        with TestClient(create_app()) as client:
            for field, value in (
                ("bid_multiplier", 0.69),
                ("bid_multiplier", 1.31),
                ("exempt_fraction", 0),
                ("exempt_fraction", 0.16),
                ("penalty_yuan_mwh", -1),
                ("penalty_yuan_mwh", 501),
            ):
                self.assertEqual(
                    client.post(
                        "/api/v1/workbench/trading/sandbox", json={field: value}
                    ).status_code,
                    422,
                )
            self.assertEqual(
                client.post(
                    "/api/v1/workbench/trading/sandbox", json={"plan_id": "unknown"}
                ).status_code,
                400,
            )
            self.assertEqual(
                client.post(
                    "/api/v1/workbench/trading/sandbox",
                    json={"source_mode": "production"},
                ).status_code,
                400,
            )
            self.assertEqual(
                client.post(
                    "/api/v1/workbench/trading/sandbox", json={"mode": "replay"}
                ).status_code,
                400,
            )

    def test_sandbox_missing_settlement_and_weather_not_zero_filled(self):
        with self.store.db:
            self.store.db.execute(
                "UPDATE serving_interval_wide SET actual_mw=NULL,rt_price=NULL,cloud_cover_pct=NULL WHERE station_id='lanneng'"
            )
        with TestClient(create_app()) as client:
            r = client.post("/api/v1/workbench/trading/sandbox", json={})
            self.assertEqual(r.status_code, 200, r.text)
            data = r.json()
        self.assertEqual(data["settled_count"], 0)
        self.assertIsNone(data["simulated"]["net_revenue_yuan"])
        self.assertIsNone(data["delta_net_revenue_yuan"])
        self.assertIsNone(data["risk_assessment"]["overall_score"])
        self.assertFalse(any(r["active"] for r in data["strategy_matrix"]))

    def test_api_request_connections_allow_worker_handoff_and_concurrent_reads(self):
        from concurrent.futures import ThreadPoolExecutor
        from cecep_console.api import get_store

        dependency = get_store()
        request_store = next(dependency)
        with ThreadPoolExecutor(max_workers=4) as pool:
            self.assertEqual(
                pool.submit(
                    lambda: request_store.db.execute("SELECT 1").fetchone()[0]
                ).result(),
                1,
            )
            pool.submit(dependency.close).result()
            with TestClient(create_app()) as client:
                paths = ["overview", "compare", "multi-day", "trading"] * 3
                results = list(
                    pool.map(
                        lambda path: client.get("/api/v1/workbench/" + path), paths
                    )
                )
        self.assertTrue(all(r.status_code == 200 for r in results))


    def test_rag_equal_relevance_prefers_recent_visible_case_and_filters_future_chunks(self):
        case_id = self.store.db.execute("SELECT case_id FROM deviation_case WHERE station_id='lanneng' LIMIT 1").fetchone()[0]
        documents = []
        for i in range(7):
            with patch("cecep_console.rsi.now", return_value=f"2026-11-23T10:0{i}:00.000000Z"), self.store.db:
                feedback = review_feedback(self.store, case_id, "相同天气复核证据", False)
                documents.append(ingest_feedback(self.store, feedback["feedback_id"]))
        result = search_knowledge_rag(self.store, "相同天气复核证据", "lanneng", "2026-11-23T10:06:00.000000Z")
        self.assertEqual(result[0]["chunk_id"], documents[-1]["chunk_id"])
        self.assertEqual(len(result), 5)
        chunk = dict(self.store.db.execute("SELECT * FROM rag_chunk WHERE chunk_id=?", (documents[0]["chunk_id"],)).fetchone())
        chunk.update(chunk_id="future-case-chunk", chunk_index=1, created_at="2026-12-01T00:00:00.000000Z")
        with self.store.db:
            self.store.append("rag_chunk", chunk)
        replay = search_knowledge_rag(self.store, "相同天气复核证据", "lanneng", "2026-11-23T10:02:00.000000Z")
        self.assertEqual(replay[0]["chunk_id"], documents[2]["chunk_id"])
        self.assertFalse(any(r["chunk_id"] == "future-case-chunk" for r in replay))

    def test_registered_contract_change_updates_summary_and_settlement(self):
        from cecep_console.serving import day_bounds
        plan = self.store.db.execute("SELECT * FROM bidding_plan WHERE station_id='lanneng' AND trading_date='2026-11-20' LIMIT 1").fetchone()
        start, end = day_bounds("2026-11-20")
        contract = dict(self.store.db.execute("SELECT * FROM contract_position WHERE station_id='lanneng' AND interval_start>=? AND interval_start<? AND contract_energy_mwh>0 ORDER BY interval_start LIMIT 1", (start, end)).fetchone())
        before = simulate_plan(self.store, plan["plan_id"])
        contract.update(contract_id="updated-contract-price", revision_no=contract["revision_no"]+1, contract_price_yuan_mwh=contract["contract_price_yuan_mwh"]+15)
        with self.store.db:
            self.store.append("contract_position", contract)
        after = simulate_plan(self.store, plan["plan_id"])
        self.assertEqual(after["contract_summary"]["price_max_yuan_mwh"], contract["contract_price_yuan_mwh"])
        self.assertEqual(before["contract_summary"]["registered_energy_mwh"], after["contract_summary"]["registered_energy_mwh"])
        self.assertAlmostEqual(after["net_revenue_yuan"]-before["net_revenue_yuan"], contract["contract_energy_mwh"]*15, places=6)

    def test_connection_status_separates_synthetic_inputs_from_production(self):
        with TestClient(create_app()) as client:
            demo = client.get("/api/v1/workbench/readiness?source_mode=synthetic").json()
            production = client.get("/api/v1/workbench/readiness?source_mode=production").json()
            self.assertTrue(any(r["record_count"] for r in demo["inputs"]))
            self.assertTrue(all(r["record_count"] == 0 for r in production["inputs"]))
            self.assertTrue(any(m["ready"] for m in production["models"]))
            self.assertFalse(next(c for c in production["capabilities"] if c["key"] == "training")["available"])
            self.assertEqual(client.get("/api/v1/workbench/bootstrap?source_mode=production").json()["dates"], [])
            self.assertEqual(client.get("/api/v1/workbench/bootstrap?station_id=absent").json()["dates"], [])
            self.assertEqual(client.get("/api/v1/workbench/readiness?source_mode=invalid").status_code, 422)

    def test_connection_status_detects_real_arrival_without_serving_materialization(self):
        source = dict(self.store.db.execute("SELECT * FROM data_source LIMIT 1").fetchone())
        source.update(source_id="real-test-source", source_name="real-test-source", source_type="meter")
        batch = dict(self.store.db.execute("SELECT * FROM ingestion_batch LIMIT 1").fetchone())
        batch.update(batch_id="real-test-batch", source_id=source["source_id"])
        actual = dict(self.store.db.execute("SELECT * FROM station_actual WHERE station_id='lanneng' LIMIT 1").fetchone())
        actual.update(actual_id="real-test-actual", source_id=source["source_id"], batch_id=batch["batch_id"], availability_basis="verified_arrival")
        with self.store.db:
            self.store.append("data_source", source)
            self.store.append("ingestion_batch", batch)
            self.store.append("station_actual", actual)
        with TestClient(create_app()) as client:
            production = client.get("/api/v1/workbench/readiness?source_mode=production").json()
            self.assertEqual(next(r for r in production["inputs"] if r["key"] == "station_actual")["record_count"], 1)
            dates = client.get("/api/v1/workbench/bootstrap?station_id=lanneng&source_mode=production").json()["dates"]
            self.assertEqual(len(dates), 1)
            self.assertEqual(client.get("/api/v1/workbench/bootstrap?station_id=other&source_mode=production").json()["dates"], [])
            overview = client.get("/api/v1/workbench/overview", params={"station_id": "lanneng", "date": dates[0], "source_mode": "production"})
            self.assertEqual(overview.status_code, 400, overview.text)
        station = dict(self.store.db.execute("SELECT * FROM station WHERE station_id='lanneng'").fetchone())
        station.update(station_id="real-test-site", station_code="real-test-site", availability_basis="verified_arrival")
        config = dict(self.store.db.execute("SELECT * FROM station_config_version WHERE station_id='lanneng' LIMIT 1").fetchone())
        config.update(config_version_id="real-test-config", station_id=station["station_id"], source_id=source["source_id"], availability_basis="verified_arrival")
        actual.update(actual_id="real-test-valid-actual", station_id=station["station_id"])
        with self.store.db:
            self.store.append("station", station)
            self.store.append("station_config_version", config)
            self.store.append("station_actual", actual)
        with TestClient(create_app()) as client:
            overview = client.get("/api/v1/workbench/overview", params={"station_id": station["station_id"], "date": dates[0], "source_mode": "production"})
            self.assertEqual(overview.status_code, 200, overview.text)
            self.assertIn("pit_engine", overview.json()["query_path"])


if __name__ == "__main__":
    unittest.main()
