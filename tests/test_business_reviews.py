import unittest

from fastapi.testclient import TestClient
from tests import test_learning as fixtures
from cecep_console import learning as ml, business_reviews as reviews
from cecep_console.api import create_app


class BusinessReviewTests(unittest.TestCase):
    def setUp(self):
        from tests import test_multitask_learning
        from cecep_console import business_workflow as bw, data_flow
        import copy
        self.f=test_multitask_learning.MultitaskLearningTests();self.f.setUp();self.s=self.f.s
        _, ids=self.f.train("pv_day_ahead_reference")
        pred=ml.prediction(self.s,ids[0],"2024-02-26")
        data_flow.reconcile(self.s,self.f.sha)
        obs=data_flow.latest_observation(self.s,pred["id"])
        body=bw.Command(action="create_plan",trading_date="2024-02-26",record_id=pred["id"],actor="测试处理人",reason="生成测试方案",key="review-test")
        payload,sha,parent=bw.create_plan(self.s,body)
        self.plan=ml.add_object(self.s,"business_plan",payload,sha,parent)
        original=bw.calculate_settlement(self.s,ml.get_object(self.s,self.plan),obs,"测试处理人","核对结算")
        self.original=ml.add_object(self.s,"business_settlement",original,obs["source_hash"],self.plan)
        derived=bw.Command(action="derive_plan",trading_date="2024-02-26",plan_id=self.plan,parameters=bw.Parameters(bid_ratio=.5),actor="测试处理人",reason="生成对照方案",key="review-compare")
        payload,sha,parent=bw.create_plan(self.s,derived)
        new_plan=ml.add_object(self.s,"business_plan",payload,sha,parent)
        new=bw.calculate_settlement(self.s,ml.get_object(self.s,new_plan),obs,"测试处理人","核对对照结算")
        self.new=ml.add_object(self.s,"business_settlement",new,obs["source_hash"],new_plan)
        self.expected_delta=sum(h["value"] for h in new["hours"] if h["value"] is not None)-sum(h["value"] for h in original["hours"] if h["value"] is not None)
        bad=copy.deepcopy(original);bad["hours"][0]["value"]=None;bad["hours"][0]["complete"]=False
        self.bad=ml.add_object(self.s,"business_settlement",bad,obs["source_hash"],self.plan)
        self.s.db.commit()

    def tearDown(self):self.f.tearDown()

    def body(self,action,**kw):
        return dict(action=action,source_key="market:shandong",date="2024-02-26",plan_id=self.plan,
                    settlement_id=self.original,category="strategy",actor="测试处理人",reason="测试核对方案",**kw)

    def test_processing_requires_evidence_and_matched_quantitative_verification(self):
        with TestClient(create_app()) as c:
            def post(action,**kw):return c.post("/api/v1/business/review-commands",json=self.body(action,**kw))
            a=post("create");self.assertEqual(a.status_code,200,a.text);oid=a.json()["id"]
            self.assertEqual(post("create").json()["id"],oid)
            self.assertEqual(post("verify",issue_id=oid).status_code,400)
            self.assertEqual(post("start",issue_id=oid).json()["state"],"in_progress")
            self.assertEqual(post("resolve",issue_id=oid).status_code,400)
            self.assertEqual(post("resolve",issue_id=oid,evidence="已保存对照方案和实际结算").json()["state"],"resolved")
            for compare in [self.original,self.bad]:
                self.assertEqual(post("verify",issue_id=oid,verification=dict(kind="settlement_comparison",comparison_object_id=compare)).status_code,400)
            result=post("verify",issue_id=oid,verification=dict(kind="settlement_comparison",comparison_object_id=self.new))
            self.assertEqual(result.status_code,200,result.text)
            self.assertAlmostEqual(result.json()["verification"]["delta"],self.expected_delta)
            self.assertEqual(result.json()["verification"]["improved"],self.expected_delta>0)
            self.assertEqual(len(result.json()["history"]),4)
            reopened=post("reopen",issue_id=oid)
            self.assertEqual(reopened.json()["state"],"in_progress")
            self.assertIsNone(reopened.json()["verification"])
            self.assertFalse(ml.get_object(self.s,oid)["payload"]["training_eligible"])

    def test_foreign_scope_cannot_process_issue_or_rewrite_saved_history(self):
        with TestClient(create_app()) as c:
            r=c.post("/api/v1/business/review-commands",json=self.body("create"));oid=r.json()["id"]
            b=self.body("start",issue_id=oid);b["source_key"]="station:lanneng:synthetic"
            self.assertEqual(c.post("/api/v1/business/review-commands",json=b).status_code,400)
            b["source_key"]="market:shandong";b["date"]="2024-02-27"
            self.assertEqual(c.post("/api/v1/business/review-commands",json=b).status_code,400)
            self.assertEqual(ml.state(self.s,oid)["state"],"pending")
            with self.assertRaises(Exception):
                self.s.db.execute("DELETE FROM ml_object WHERE object_id=?",(oid,))
            self.s.db.rollback()
