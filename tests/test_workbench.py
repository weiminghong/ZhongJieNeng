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
)
from cecep_console.trading import settle_interval, simulate_plan
from cecep_console.agent_service import search_knowledge_rag
from cecep_console.rsi import (
    review_feedback,
    ingest_feedback,
    approve_model,
    model_states,
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
            self.assertEqual(old.inspect()["schema_version"], 2)
            self.assertEqual(
                len(old.db.execute("SELECT * FROM schema_migration").fetchall()), 2
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
                client.get("/api/storage/health").json()["schema_version"], 2
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


if __name__ == "__main__":
    unittest.main()
