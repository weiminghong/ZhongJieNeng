import copy
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from fastapi.testclient import TestClient

from tests import test_learning as fixtures
from cecep_console import learning as ml, workbench_context as wb, workbench_knowledge as knowledge
from cecep_console.api import create_app
from cecep_console.storage_demo import seed_demo


class WorkspaceKnowledgeTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.LearningTests()
        self.fixture.setUp()
        self.store = self.fixture.store
        seed_demo(self.store)
        _, self.ids = self.fixture.trained()
        self.price = ml.prediction(self.store, self.ids[0], "2024-02-26")
        self.settings = patch("cecep_console.model_settings.load_settings", return_value=SimpleNamespace(ready=False))
        self.settings.start()

    def tearDown(self):
        self.settings.stop()
        self.fixture.tearDown()

    def view(self, native=False):
        return wb.context(self.store, "station:lanneng:synthetic") if native else wb.context(
            self.store, "market:shandong", "2024-02-26", self.ids[0], self.price["id"])

    def body(self, c, action="feedback"):
        case = c["cases"][0]
        return dict(action=action, source_key=c["source"]["key"], task_id=c["source"]["task"],
                    date=c["date"], model_id=c["model_id"], record_id=c["record_id"],
                    slot=case["slot"], case_id=case["id"], context_version=c["context_version"],
                    confirmed=True, actor="测试复核人", reason="已核对预测偏差与实际原始记录；设备原因尚待确认")

    def test_confirmed_reviews_feed_unified_evidence_tools_in_both_domains(self):
        with TestClient(create_app()) as client:
            for native in (False, True):
                c = self.view(native)
                body = self.body(c)
                saved = client.post("/api/v1/workspace/commands", json=body)
                self.assertEqual(saved.status_code, 200, saved.text)
                self.assertTrue(saved.json()["knowledge_saved"])
                analysis = client.post("/api/v1/workspace/commands", json=dict(body, action="analyze", reason="分析预测偏差及已确认复核"))
                self.assertEqual(analysis.status_code, 200, analysis.text)
                result = analysis.json()
                self.assertEqual(result["llm_mode"], "deterministic_tools_only")
                self.assertTrue(result["citations"])
                self.assertIn("测试复核人", result["citations"][0]["text"])
                self.assertIn("所选时段", result["answer_markdown"])
                self.assertIn("实际减预测", result["answer_markdown"])
                self.assertGreaterEqual(len(result["tools"]), 6)
                self.assertTrue(all(t["summary"] for t in result["tools"]))
                record = ml.get_object(self.store, result["id"], "analysis")
                self.assertEqual(record["payload"]["citations"], result["citations"])
                self.assertEqual(record["payload"]["tool_calls"], result["tools"])
                self.assertFalse(ml.get_object(self.store, saved.json()["knowledge_id"])["payload"]["training_eligible"])

    def test_case_index_is_idempotent_and_rejects_old_observation_or_foreign_source(self):
        with TestClient(create_app()) as client:
            for native in (False, True):
                c = self.view(native)
                body = self.body(c)
                saved = client.post("/api/v1/workspace/commands", json=body).json()
                fid = saved.get("feedback_id", saved.get("id"))
                imported = client.post("/api/v1/workspace/commands", json=dict(body, action="ingest_case", feedback_id=fid))
                self.assertEqual(imported.status_code, 200, imported.text)
                self.assertEqual(imported.json()["id"], saved["knowledge_id"])
                old = copy.deepcopy(c)
                next(p for p in old["points"] if p["slot"] == body["slot"])["observation_key"] = "changed"
                self.assertEqual(knowledge.search_cases(self.store, old), [])
                foreign = copy.deepcopy(c)
                foreign["source"]["key"] = "station:lingguang:synthetic" if native else "market:foreign"
                self.assertEqual(knowledge.search_cases(self.store, foreign), [])
                foreign["source"]["key"] = c["source"]["key"]
                foreign["source"]["task"] = "foreign_task"
                self.assertEqual(knowledge.search_cases(self.store, foreign), [])
                bad = client.post("/api/v1/workspace/commands", json=dict(body, action="ingest_case", feedback_id=fid, context_version="stale"))
                self.assertEqual(bad.status_code, 400)

    def test_readonly_index_and_replay_do_not_read_later_confirmations(self):
        c = self.view()
        with TestClient(create_app()) as client:
            body = self.body(c)
            saved = client.post("/api/v1/workspace/commands", json=body)
            self.assertEqual(saved.status_code, 200, saved.text)
            before = self.store.db.execute("SELECT count(*) FROM ml_object").fetchone()[0]
            params = dict(source_key=c["source"]["key"], trading_date=c["date"], model_id=c["model_id"], record_id=c["record_id"])
            result = client.get("/api/v1/workspace/knowledge", params=params)
            self.assertEqual(result.status_code, 200, result.text)
            self.assertEqual(len(result.json()["records"]), 1)
            replay = client.get("/api/v1/workspace/knowledge", params=dict(params, mode="replay", until="23:59"))
            self.assertEqual(replay.status_code, 200, replay.text)
            self.assertEqual(replay.json()["records"], [])
            self.assertEqual(before, self.store.db.execute("SELECT count(*) FROM ml_object").fetchone()[0])

    def test_unconfirmed_and_out_of_scope_reviews_never_create_cases(self):
        c = self.view()
        with TestClient(create_app()) as client:
            body = self.body(c)
            bad = client.post("/api/v1/workspace/commands", json=dict(body, confirmed=False))
            self.assertEqual(bad.status_code, 400)
            self.assertEqual(ml.objects(self.store, "knowledge_case"), [])
            missing = client.post("/api/v1/workspace/commands", json=dict(body, action="ingest_case", feedback_id="not-found"))
            self.assertEqual(missing.status_code, 400)
            self.assertEqual(ml.objects(self.store, "knowledge_case"), [])

    def test_market_revision_change_excludes_cases_without_erasing_them(self):
        c = self.view()
        with TestClient(create_app()) as client:
            client.post("/api/v1/workspace/commands", json=self.body(c)).raise_for_status()
        revised = copy.deepcopy(c)
        revised["metadata"]["source_hash"] = "new-version"
        self.assertEqual(knowledge.search_cases(self.store, revised), [])
        self.assertEqual(len(ml.objects(self.store, "knowledge_case")), 1)
        earlier = copy.deepcopy(c)
        earlier["date"] = "2024-02-25"
        self.assertEqual(knowledge.search_cases(self.store, earlier), [])

    def test_global_analysis_has_no_invented_selected_slot_and_tools_keep_failures(self):
        c = self.view()
        with TestClient(create_app()) as client:
            body = self.body(c, "analyze")
            body.pop("slot")
            result = client.post("/api/v1/workspace/commands", json=body)
            self.assertEqual(result.status_code, 200, result.text)
            self.assertNotIn("所选时段", result.json()["answer_markdown"])
            self.assertFalse(any(t["name"] == "核对所选时段" for t in result.json()["tools"]))
        pv = copy.deepcopy(c)
        pv["source"]["task"] = "pv_day_ahead_reference"
        with patch("cecep_console.public_settlement.calculate", side_effect=ValueError("test missing input")):
            tools, citations = knowledge.evidence_tools(self.store, pv, "分析预测")
        failed = next(t for t in tools if t["name"] == "核算同范围量价参考")
        self.assertEqual(failed["output"]["status"], "unavailable")
        self.assertIn("不补造", failed["summary"])
        tools, _ = knowledge.evidence_tools(self.store, c, "分析预测", "replay", "12:00")
        comparison = next(t for t in tools if t["name"] == "比较同口径版本")
        self.assertEqual(comparison["output"]["versions"], [])


if __name__ == "__main__":
    unittest.main()
