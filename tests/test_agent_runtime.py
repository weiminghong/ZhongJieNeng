"""Real PIT adapters, immutable migration, grounded artifacts and HTTP boundaries."""

from contextlib import closing
import hashlib
import io
import json
import os
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch
from fastapi.testclient import TestClient
from cecep_console.api import create_app
from cecep_console.agent_service import query_agent, agent_history
from cecep_console.model_runtime import (
    run_model_inference, register_runtime_model, list_runtime_models, artifact_path,
    endpoint, remote, readiness, builtin_model,
)
from cecep_console.model_settings import _NoRedirect
from cecep_console.proactive import run_proactive_analysis, latest_proactive_briefs
from cecep_console.storage import Store, BASE, instant
from cecep_console.storage_demo import seed_demo
from cecep_console.serving import data_clock, now, metrics


class RuntimeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.shared = tempfile.TemporaryDirectory()
        cls.fixture = Path(cls.shared.name)/"fixture.sqlite"
        with Store(cls.fixture) as s:
            s.initialize(); seed_demo(s)

    @classmethod
    def tearDownClass(cls):
        cls.shared.cleanup()

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.tmp.name)/"test.sqlite")
        with closing(sqlite3.connect(self.fixture)) as original:
            original.backup(self.store.db)
        self.scope = dict(station_id="lanneng", date="2026-11-20", mode="live", source_mode="synthetic", cutoff_at=data_clock(self.store))
        self.env = patch.dict(os.environ, {"CECEP_DB_PATH": str(self.store.path), "CECEP_LLM_API_KEY": "", "CECEP_LLM_SETTINGS_PATH": str(Path(self.tmp.name)/"private.json")})
        self.env.start()

    def tearDown(self):
        self.env.stop(); self.store.close(); self.tmp.cleanup()

    def infer(self, **kwargs):
        return run_model_inference(self.store, **{**dict(station_id="lanneng", trading_date="2026-11-20", cutoff_at=self.scope["cutoff_at"], source_mode="synthetic"), **kwargs})

    def test_v2_upgrade_preserves_all_old_rows_checksums(self):
        with Store(Path(self.tmp.name)/"v2.sqlite") as old:
            old.db.execute("CREATE TABLE schema_migration(version INTEGER PRIMARY KEY,checksum TEXT NOT NULL,applied_at TEXT NOT NULL)")
            checksums = []
            for v, filename in enumerate(["001_initial.sql", "002_upper_layers.sql"], 1):
                script = (BASE/"storage_sql"/filename).read_text(encoding="utf-8")
                old.db.executescript(script)
                checksum = hashlib.sha256(script.encode()).hexdigest()
                old.db.execute("INSERT INTO schema_migration VALUES(?,?,?)", (v, checksum, now()))
                checksums.append(checksum)
            sentinel = dict(self.store.db.execute("SELECT * FROM data_source LIMIT 1").fetchone())
            old.append("data_source", sentinel); old.db.commit(); old.initialize()
            self.assertEqual(dict(old.db.execute("SELECT * FROM data_source").fetchone()), sentinel)
            self.assertEqual([r[0] for r in old.db.execute("SELECT checksum FROM schema_migration WHERE version<3 ORDER BY version")], checksums)
            self.assertEqual(old.inspect()["schema_version"], 7)
            self.assertEqual(old.inspect()["foreign_key_errors"], [])
            old.initialize()

    def test_original_migration_hashes(self):
        for name, expected in [("001_initial.sql", "6614fb9d0ac78d15d37de97e41d751e5a0ad6a6829b360b26ee785e8bf093007"), ("002_upper_layers.sql", "df4db5063b345733581bbc87262997beaf903346df16aa0b6f69d3cf793ee4ab")]:
            self.assertEqual(hashlib.sha256((BASE/"storage_sql"/name).read_bytes()).hexdigest(), expected)

    def test_deterministic_inference_and_paired_metrics(self):
        a, b = self.infer(), self.infer()
        self.assertEqual(a["points"], b["points"])
        self.assertEqual(a["feature_hash"], b["feature_hash"])
        self.assertEqual(len(a["points"]), 96)
        self.assertEqual(a["trained_scope"], "pit_synthetic_demo")
        self.assertGreater(a["training_pair_count"], 0)
        expected = metrics([p["actual_mw"] for p in a["points"]], [p["predicted_mw"] for p in a["points"]])
        self.assertEqual(a["metrics"]["mae"], expected["mae"])

    def test_future_weather_revision_does_not_change_inference(self):
        before = self.infer()
        row = dict(self.store.db.execute("SELECT * FROM weather_forecast WHERE target_start>=? AND target_start<? ORDER BY target_start LIMIT 1", (instant("2026-11-20T00:00:00+08:00"),instant("2026-11-21T00:00:00+08:00"))).fetchone())
        row.update(weather_forecast_id="future-weather", revision_no=99, available_at=instant("2026-12-01T00:00:00Z"), cloud_cover_pct=100)
        self.store.append("weather_forecast", row)
        after = self.infer()
        self.assertEqual(before["feature_hash"], after["feature_hash"])
        self.assertEqual(before["points"], after["points"])

    def test_future_actual_revision_does_not_change_metrics(self):
        before = self.infer()
        row = dict(self.store.db.execute("SELECT * FROM station_actual WHERE interval_start>=? AND available_at<=? LIMIT 1", (instant("2026-11-20T00:00:00+08:00"), self.scope["cutoff_at"])).fetchone())
        row.update(actual_id="future-actual", revision_no=99, power_mw=99, available_at=instant("2026-12-01T00:00:00Z"))
        self.store.append("station_actual", row)
        self.assertEqual(before["metrics"], self.infer()["metrics"])

    def test_target_actual_is_not_a_training_feature(self):
        before = self.infer()
        row = dict(self.store.db.execute("SELECT * FROM station_actual WHERE interval_start>=? AND available_at<=? ORDER BY power_mw DESC LIMIT 1", (instant("2026-11-20T00:00:00+08:00"), self.scope["cutoff_at"])).fetchone())
        row.update(actual_id="actual-revised", revision_no=99, power_mw=row["power_mw"]+10)
        self.store.append("station_actual", row)
        after = self.infer()
        self.assertEqual(before["feature_hash"], after["feature_hash"])
        self.assertEqual([p["predicted_mw"] for p in before["points"]], [p["predicted_mw"] for p in after["points"]])
        self.assertNotEqual(before["metrics"]["mae"], after["metrics"]["mae"])

    def test_persist_false_has_no_writes(self):
        before = self.store.db.total_changes
        r = self.infer()
        self.assertIsNone(r["persisted_run_id"])
        self.assertEqual(self.store.db.total_changes, before)

    def test_persist_true_records_snapshot_and_96_points(self):
        r = self.infer(persist=True)
        run = self.store.db.execute("SELECT * FROM prediction_run WHERE run_id=?", (r["persisted_run_id"],)).fetchone()
        self.assertEqual(run["cutoff_at"], self.scope["cutoff_at"])
        self.assertGreaterEqual(run["available_at"], now()[:10])
        self.assertEqual(self.store.db.execute("SELECT count(*) FROM prediction_value WHERE run_id=?", (run["run_id"],)).fetchone()[0], 96)
        self.assertGreater(self.store.db.execute("SELECT count(*) FROM feature_input WHERE snapshot_id=?", (run["snapshot_id"],)).fetchone()[0], 0)
        self.assertEqual(self.store.inspect()["foreign_key_errors"], [])

    def test_cloud_and_temperature_and_cap_response(self):
        base = self.infer()
        for overrides in [{"cloud_delta_pct":30}, {"temp_delta_c":5}, {"curtailment_cap_mw":2}]:
            changed = self.infer(overrides=overrides)
            self.assertLess(sum(p["predicted_mw"] for p in changed["points"]), sum(p["predicted_mw"] for p in base["points"]))
        self.assertLessEqual(max(p["predicted_mw"] for p in self.infer(overrides={"curtailment_cap_mw":2})["points"]), 2)

    def test_invalid_perturbations_fail(self):
        for overrides in [{"cloud_delta_pct":51}, {"temp_delta_c":float("nan")}, {"curtailment_cap_mw":-1}, {"unknown":1}]:
            with self.subTest(overrides=overrides), self.assertRaises(ValueError):
                self.infer(overrides=overrides)

    def test_unsafe_paths_rejected(self):
        for uri in ["local_joblib://../outside.pkl", "local_joblib://C:/Windows/system.ini", "local_joblib://runtime/models/missing.pkl"]:
            with self.subTest(uri=uri), self.assertRaises(ValueError):
                artifact_path(uri)

    def test_unsafe_urls_and_redirects_rejected(self):
        for uri in ["http://user:secret@localhost/predict", "https://model.test/predict?token=hidden", "https://model.test/#fragment", "file:///tmp/model"]:
            with self.subTest(uri=uri), self.assertRaises(ValueError):
                endpoint(uri)
        self.assertIsNone(_NoRedirect().redirect_request(None, None, 302, "redirect", {}, "https://other.test"))

    def test_missing_dependencies_and_hash_are_explicit(self):
        path = Path(self.tmp.name)/"models/test.onnx"; path.parent.mkdir(); path.write_bytes(b"test")
        model = dict(artifact_uri="local_onnx://models/test.onnx", artifact_hash="0"*64)
        with patch("cecep_console.model_runtime.ROOT", Path(self.tmp.name)):
            with self.assertRaisesRegex(ValueError, "SHA-256"):
                readiness(model)
            model["artifact_hash"] = hashlib.sha256(path.read_bytes()).hexdigest()
            with patch("cecep_console.model_runtime.importlib.util.find_spec", return_value=None), self.assertRaisesRegex(ValueError, "onnxruntime"):
                readiness(model)

    def test_remote_protocol_and_error(self):
        with patch("cecep_console.model_runtime.provider_open", return_value=io.BytesIO(b'{"predictions":[1]}')) as transport:
            self.assertEqual(remote("https://model.test/predict", {"features":[]})["predictions"], [1])
            self.assertEqual(transport.call_args.kwargs["timeout"], 15)
        with patch("cecep_console.model_runtime.provider_open", side_effect=TimeoutError()), self.assertRaisesRegex(ValueError, "TimeoutError"):
            remote("https://model.test/predict")

    def test_registered_http_model_is_candidate_and_live_callable(self):
        payload = dict(model_name="operator-model", version="1", artifact_uri="http://localhost:9000/predict", source_mode="synthetic")
        with patch("cecep_console.model_runtime.remote", return_value={"status":"ok"}):
            model = register_runtime_model(self.store, payload)
        self.assertEqual(model["effective_status"], "candidate")
        with patch("cecep_console.model_runtime.remote", return_value={"predictions":[1]*96}):
            r = self.infer(model_version_id=model["model_version_id"], registry_cutoff=now())
        self.assertEqual(r["points"][0]["predicted_mw"], 1)
        with self.assertRaisesRegex(ValueError, "不可见"):
            self.infer(model_version_id=model["model_version_id"])
        self.assertEqual(self.store.inspect()["foreign_key_errors"], [])

    def test_bad_remote_shape_fails_without_fallback(self):
        payload = dict(model_name="bad-shape", version="1", artifact_uri="https://model.test/predict")
        with patch("cecep_console.model_runtime.remote", return_value={}):
            model = register_runtime_model(self.store, payload)
            with self.assertRaisesRegex(ValueError, "96"):
                self.infer(model_version_id=model["model_version_id"], registry_cutoff=now())

    def test_agent_model_tool_artifacts_match_audit_and_history(self):
        r = query_agent(self.store, "调用小模型实时预测", self.scope)
        output = next(c["output"] for c in r["tool_calls"] if c["tool_name"] == "invoke_forecast_model")
        artifact = next(a for a in r["artifacts"] if a["type"] == "forecast_overlay")
        self.assertEqual(artifact["data"], output)
        history = agent_history(self.store, "lanneng")["history"][0]
        self.assertEqual(history["artifacts"], r["artifacts"])

    def test_agent_what_if_uses_exact_predictions_in_settlement(self):
        r = query_agent(self.store, "云量+30%场景推演", self.scope)
        tool = next(c for c in r["tool_calls"] if c["tool_name"] == "run_what_if_forecast")
        self.assertEqual(tool["output"]["overrides"], {"cloud_delta_pct":30})
        sandbox = tool["output"]["sandbox"]
        self.assertEqual(sandbox["delta_net_revenue_yuan"], sandbox["simulated"]["net_revenue_yuan"]-sandbox["baseline"]["net_revenue_yuan"])
        self.assertNotEqual(sandbox["delta_penalty_yuan"], 0)

    def test_weather_evidence_question_does_not_request_hypothetical_parameters(self):
        result = query_agent(self.store, "请核对云量、辐照和限电原因，分析光伏预测偏差", self.scope)
        self.assertTrue(result["answer_markdown"])
        self.assertFalse(any(c["tool_name"] == "run_what_if_forecast" for c in result["tool_calls"]))
        with self.assertRaisesRegex(ValueError, "场景参数"):
            query_agent(self.store, "假设云量发生变化，进行场景推演", self.scope)

    def test_explicit_curtailment_parameters_keep_scenario_dispatch(self):
        for question in ["限电至20MW", "限电上限20MW", "限电20MW"]:
            with self.subTest(question=question):
                result = query_agent(self.store, question, self.scope)
                output = next(c["output"] for c in result["tool_calls"] if c["tool_name"] == "run_what_if_forecast")
                self.assertEqual(output["overrides"], {"curtailment_cap_mw": 20})

    def test_proactive_brief_immutable_and_four_signal_types(self):
        brief = run_proactive_analysis(self.store, self.scope)
        self.assertEqual(len(brief["signals"]), 4)
        self.assertIn(brief["severity"], {"info","warning","critical"})
        self.assertTrue(brief["citations"])
        self.assertTrue(all(c["available_at"] <= self.scope["cutoff_at"] for c in brief["citations"]))
        for sql in ["UPDATE agent_proactive_brief SET headline='changed'", "DELETE FROM agent_proactive_brief"]:
            with self.assertRaisesRegex(sqlite3.IntegrityError, "append-only"):
                self.store.db.execute(sql)

    def test_replay_never_reads_later_created_brief(self):
        brief = run_proactive_analysis(self.store, self.scope)
        self.assertEqual(latest_proactive_briefs(self.store, "lanneng", "2026-11-20", "synthetic", self.scope["cutoff_at"]), [])
        self.assertEqual(latest_proactive_briefs(self.store, "lanneng", "2026-11-20", "synthetic", now())[0]["brief_id"], brief["brief_id"])

    def test_registration_same_origin_and_failed_probe_do_not_write(self):
        with TestClient(create_app()) as client:
            payload = dict(model_name="test", version="1", artifact_uri="https://model.test/predict")
            self.assertEqual(client.post("/api/v1/models/register", json=payload).status_code, 403)
            self.assertEqual(client.post("/api/v1/models/register", json=payload, headers={"X-CECEP-Settings":"1", "Origin":"https://other.test"}).status_code, 403)
            with patch("cecep_console.model_runtime.remote", side_effect=ValueError("probe failed")):
                self.assertEqual(client.post("/api/v1/models/register", json=payload, headers={"X-CECEP-Settings":"1"}).status_code, 400)
            self.assertFalse(any(m["model_name"] == "test" for m in client.get("/api/v1/models/runtime").json()["models"]))

    def test_runtime_and_proactive_api_roundtrip(self):
        with TestClient(create_app()) as client:
            self.assertEqual(client.get("/api/v1/models/runtime").status_code, 200)
            predicted = client.post("/api/v1/models/predict", json={**self.scope,"persist":True})
            self.assertEqual(predicted.status_code, 200, predicted.text)
            self.assertTrue(predicted.json()["persisted_run_id"])
            brief = client.post("/api/v1/agent/proactive/run", json=self.scope)
            self.assertEqual(brief.status_code, 200, brief.text)
            latest = client.get("/api/v1/agent/proactive").json()["briefs"]
            self.assertEqual(latest[0]["brief_id"], brief.json()["brief_id"])
            replay = client.get("/api/v1/agent/proactive", params={**self.scope, "mode":"replay"}).json()["briefs"]
            self.assertEqual(replay, [])

    def test_registration_route_success_then_real_protocol_predict(self):
        with TestClient(create_app()) as client:
            with patch("cecep_console.model_runtime.remote", return_value={"status":"ready"}):
                result = client.post("/api/v1/models/register", json=dict(model_name="route-model", version="1", artifact_uri="http://localhost:9000/predict"), headers={"X-CECEP-Settings":"1", "Origin":"http://testserver"})
            self.assertEqual(result.status_code, 200, result.text)
            with patch("cecep_console.model_runtime.remote", return_value={"predictions":[2]*96}):
                prediction = client.post("/api/v1/models/predict", json={"model_version_id": result.json()["model_version_id"]})
            self.assertEqual(prediction.status_code, 200, prediction.text)
            self.assertEqual(prediction.json()["points"][0]["predicted_mw"], 2)

    def test_source_mode_mismatch_rejected(self):
        with self.assertRaisesRegex(ValueError, "不匹配|不可见"):
            self.infer(model_version_id="lgbm-demo-v2.1", source_mode="production")
        self.assertEqual(len([m for m in list_runtime_models(self.store) if m["adapter_type"] == "builtin"]), 2)


if __name__ == "__main__":
    unittest.main()
