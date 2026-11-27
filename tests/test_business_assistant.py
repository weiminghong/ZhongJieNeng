import csv
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from fastapi.testclient import TestClient
from tests import test_learning as fixtures
from cecep_console import learning as ml, data_flow, public_data, business_workflow as business
from cecep_console import business_assistant as assistant
from cecep_console.api import create_app


class BusinessAssistantTests(unittest.TestCase):
    def setUp(self):
        self.f = fixtures.LearningTests(); self.f.setUp(); self.s = self.f.store
        ds = ml.register_dataset(self.s, self.f.sha, "pv_day_ahead_reference")
        job = ml.submit(self.s, ds["id"], 1, "business-assistant-fixture")
        ids = ml.execute(self.s, job["id"])
        ml.event(self.s, job["id"], "succeeded", observed_exit_code=0); self.s.db.commit()
        self.pred = ml.prediction(self.s, ids[0], "2024-02-26")
        data_flow.reconcile(self.s, self.f.sha)
        self.obs = data_flow.latest_observation(self.s, self.pred["id"])
        b = business.Command(action="create_plan", trading_date="2024-02-26", record_id=self.pred["id"],
                             actor="测试人员", reason="验证业务对象分析", key="fixture-plan",
                             parameters=business.Parameters(bid_ratio=1.2, fee_yuan_mwh=43.5))
        p, sha, parent = business.create_plan(self.s, b)
        pid = ml.add_object(self.s, "business_plan", p, sha, parent)
        self.plan = ml.get_object(self.s, pid)
        settled = business.calculate_settlement(self.s, self.plan, self.obs, "测试人员", "测试实际核对")
        sid = ml.add_object(self.s, "business_settlement", settled, self.f.sha, pid)
        self.settlement = ml.get_object(self.s, sid)
        self.s.db.commit()
        self.settings = patch("cecep_console.model_settings.load_settings", return_value=SimpleNamespace(ready=False))
        self.settings.start()

    def tearDown(self):
        self.settings.stop(); self.f.tearDown()

    def body(self, oid):
        return dict(action="analyze", source_key="market:shandong", date="2024-02-26",
                    task_id="pv_day_ahead_reference", business_object_id=oid,
                    actor="测试分析者", reason="分析当前业务对象与保存证据")

    def test_analysis_uses_saved_parameters_and_settlement_not_default_live_calculation(self):
        with TestClient(create_app()) as client, patch("cecep_console.public_settlement.calculate", side_effect=AssertionError("must not recalculate")):
            result = client.post("/api/v1/workspace/commands", json=self.body(self.settlement["id"]))
        self.assertEqual(result.status_code, 200, result.text)
        data = result.json()
        self.assertEqual(data["business_object"]["parameters"]["fee_yuan_mwh"], 43.5)
        self.assertEqual(data["business_object"]["parameters"]["bid_ratio"], 1.2)
        self.assertIn("结算复盘", data["answer_markdown"])
        self.assertIn("43.5", data["answer_markdown"])
        self.assertIn(f"{self.settlement['payload']['actual']['value']:,.2f}元", data["answer_markdown"])
        self.assertNotIn("None", data["answer_markdown"])
        self.assertFalse(any(t["name"] == "核算同范围量价参考" for t in data["tools"]))
        saved = ml.get_object(self.s, data["id"], "analysis")
        self.assertEqual(saved["source_hash"], self.settlement["source_hash"])
        self.assertEqual(saved["payload"]["business_snapshot"]["settlement"], self.settlement["payload"])
        self.assertEqual(saved["payload"]["evidence_snapshot"]["points"], [])

    def test_source_date_task_record_and_replay_boundaries_reject_foreign_object(self):
        for kwargs in [dict(source_key="station:lanneng:synthetic"), dict(day="2024-02-27"),
                       dict(task=ml.TASK), dict(record_id="foreign-record"), dict(model_id="foreign-model"),
                       dict(mode="replay", until="23:59")]:
            params = dict(source_key="market:shandong", day="2024-02-26", task="pv_day_ahead_reference")
            params.update(kwargs)
            with self.assertRaises(ValueError):
                assistant.load(self.s, self.plan["id"], **params)

    def test_issue_analysis_preserves_evidence_and_reports_declared_progress(self):
        p = self.plan["payload"]
        payload = dict(source_key=p["source_key"], date=p["date"], task=p["task"], model_id=p["model_id"],
                       record_id=p["record_id"], plan_id=self.plan["id"], settlement_id=self.settlement["id"],
                       slot=0, category="strategy", reason="核对申报系数", actor="测试提出人", owner="测试处理人",
                       evidence_snapshot=dict(plan=p, settlement=self.settlement["payload"]))
        oid = ml.add_object(self.s, "business_review_issue", payload, self.f.sha, self.plan["id"])
        ml.event(self.s, oid, "resolved", owner="接续处理人", evidence="已追加对照方案，尚待量化验证")
        self.s.db.commit()
        with TestClient(create_app()) as client:
            response = client.post("/api/v1/workspace/commands", json=self.body(oid))
        self.assertEqual(response.status_code, 200, response.text)
        self.assertIn("待验证", response.json()["answer_markdown"])
        self.assertIn("接续处理人", response.json()["answer_markdown"])
        self.assertIn("尚待量化验证", response.json()["answer_markdown"])
        self.assertEqual(ml.state(self.s, oid)["state"], "resolved")

    def test_later_source_revision_does_not_replace_old_settlement_analysis_snapshot(self):
        with self.f.csv.open(encoding="utf-8", newline="") as stream:
            reader = csv.DictReader(stream); columns = reader.fieldnames; rows = list(reader)
        for row in rows:
            if row["日期"] == "2024-02-26":
                row["光伏总加(实际)"] = "900"
        with self.f.csv.open("w", encoding="utf-8", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=columns); writer.writeheader(); writer.writerows(rows)
        public_data._load.cache_clear()
        current = public_data.dataset()[0]["source_hash"]
        data_flow.archive_current(self.s, current); data_flow.reconcile(self.s, current)
        with TestClient(create_app()) as client:
            response = client.post("/api/v1/workspace/commands", json=self.body(self.settlement["id"]))
        self.assertEqual(response.status_code, 200, response.text)
        saved = ml.get_object(self.s, response.json()["id"], "analysis")
        self.assertEqual(saved["payload"]["business_snapshot"]["settlement"]["actual"], self.settlement["payload"]["actual"])
        self.assertEqual(saved["source_hash"], self.f.sha)


if __name__ == "__main__":
    unittest.main()
