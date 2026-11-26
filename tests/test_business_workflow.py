import copy
import csv
import unittest
from fastapi.testclient import TestClient
from cecep_console import business_workflow as bw, learning as ml, data_flow
from cecep_console.api import create_app
from tests import test_multitask_learning as fixtures


class BusinessWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.f=fixtures.MultitaskLearningTests();self.f.setUp();self.s=self.f.s
        self.pred={}
        for role,task in dict(pv=bw.PV_TASK,**bw.PRICE_TASKS).items():
            if role=='spread':continue
            _,ids=self.f.train(task)
            self.pred[role]=ml.prediction(self.s,ids[0],"2024-02-26")
        data_flow.reconcile(self.s,self.f.sha)
        self.base=dict(source_key=bw.SOURCE,trading_date="2024-02-26",record_id=self.pred['pv']['id'],
                       da_record_id=self.pred['da']['id'],rt_record_id=self.pred['rt']['id'],
                       actor="测试处理人",reason="验证完整量价业务链",key="plan-first")

    def tearDown(self):self.f.tearDown()

    def test_plan_derive_settle_decomposition_and_idempotency(self):
        with TestClient(create_app()) as c:
            body=dict(self.base,action="create_plan",parameters=dict(bid_ratio=.8))
            first=c.post('/api/v1/business/commands',json=body)
            self.assertEqual(first.status_code,200,first.text)
            plan=first.json()['plan'];self.assertEqual(plan['estimated']['priced_hours'],24)
            self.assertEqual(c.post('/api/v1/business/commands',json=body).json()['plan']['id'],plan['id'])
            wrong=dict(body,parameters=dict(bid_ratio=.7))
            self.assertEqual(c.post('/api/v1/business/commands',json=wrong).status_code,400)
            original=ml.get_object(self.s,plan['id'])['payload']
            obs=data_flow.latest_observation(self.s,self.pred['pv']['id'])
            settlement=c.post('/api/v1/business/commands',json=dict(self.base,action='settle',plan_id=plan['id'],observation_id=obs['id'],key='settle-first'))
            self.assertEqual(settlement.status_code,200,settlement.text)
            result=settlement.json()['settlement'];comparison=result['comparison']
            self.assertEqual(result['actual']['settled_hours'],24)
            self.assertAlmostEqual(comparison['delta'],comparison['power_effect']+comparison['price_effect']+comparison['fee_effect'])
            derived=c.post('/api/v1/business/commands',json=dict(self.base,action='derive_plan',plan_id=plan['id'],parameters=dict(bid_ratio=.6),key='derive-second'))
            self.assertEqual(derived.status_code,200,derived.text)
            self.assertEqual(derived.json()['plan']['parent_plan_id'],plan['id'])
            self.assertEqual(ml.get_object(self.s,plan['id'])['payload'],original)
            self.assertEqual(self.s.db.execute('PRAGMA foreign_key_check').fetchall(),[])

    def test_expected_results_do_not_read_target_day_actuals(self):
        b=bw.Command(**self.base,action='create_plan')
        before=bw.create_plan(self.s,b)[0]
        with self.f.f.csv.open(encoding='utf-8',newline='') as f:
            reader=csv.DictReader(f);fields=reader.fieldnames;rows=list(reader)
        for row in rows:
            if row['日期']=='2024-02-26':
                row['实时价格']='999999';row['日前价格']='-999999';row['光伏总加(实际)']='999999'
        with self.f.f.csv.open('w',encoding='utf-8',newline='') as f:
            writer=csv.DictWriter(f,fieldnames=fields);writer.writeheader();writer.writerows(rows)
        after=bw.create_plan(self.s,b)[0]
        self.assertEqual(before['estimated'],after['estimated'])
        self.assertEqual(before['hours'],after['hours'])
        self.assertEqual(before['risk'],after['risk'])

    def test_unpriced_plan_stays_empty_and_wrong_scope_is_rejected(self):
        args=dict(self.base);args.pop('da_record_id');args.pop('rt_record_id')
        p,sha,parent=bw.create_plan(self.s,bw.Command(**args,action='create_plan'))
        self.assertIsNone(p['estimated']['expected_value'])
        self.assertEqual(p['estimated']['priced_hours'],0)
        validation=ml.prediction(self.s,self.pred['pv']['payload']['model_id'],"2024-02-24",True)
        invalid=dict(args,record_id=validation['id'],trading_date="2024-02-24")
        with self.assertRaisesRegex(ValueError,"调参验证"):
            bw.create_plan(self.s,bw.Command(**invalid,action='create_plan'))
        with self.assertRaises(ValueError):
            bw.create_plan(self.s,bw.Command(**args,action='create_plan',parameters=bw.Parameters(mode='spread_rule')))
        bad=copy.deepcopy(p);bad['source_key']='station:lanneng:synthetic'
        with self.assertRaises(Exception):ml.add_object(self.s,'business_plan',bad,sha,parent)
        self.s.db.rollback()
