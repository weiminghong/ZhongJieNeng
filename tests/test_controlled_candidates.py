"""Synthetic unit fixtures only; no remote dataset or model assets are copied."""
import copy
import csv
import json
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

import numpy as np

from cecep_console import learning as ml, optimized_models as om, public_data, task_catalog as tc
from tests import test_learning as fixtures
from cecep_console.api import create_app


class ControlledCandidateTests(unittest.TestCase):
    def setUp(self):
        self.f=fixtures.LearningTests()
        self.f.setUp()
        self.s=self.f.store

    def tearDown(self):
        self.f.tearDown()

    def origin(self, **extra):
        task="pv_day_ahead_reference"
        contract=dict(contract_id="generated-v2-unit",runner=dict(path="runs/generated/worker.py",runner_sha256="a"*64),environment=dict(name="generated",numpy=np.__version__,scipy="unit",sklearn="unit"),recipes=[dict(kind="ridge_rich",name="linear",alpha=10)],blend_values=[.5,1])
        payload=dict(task=task,contract=contract,**extra)
        oid=ml.add_object(self.s,"optimization_result",payload,self.f.sha,self.f.ds["id"])
        self.s.db.commit()
        return oid

    def module(self):
        def fit(data, train, task, cfg):
            idx=np.flatnonzero(train)
            native=dict(x=data["xr"][idx],y=data["y"][idx],days=data["days"][idx],slots=data["slots"][idx])
            native["x"]=data["xb"][idx] if cfg["kind"]=="ridge_raw" else data["xr"][idx]
            return dict(recipe=cfg,task=task,fallback=float(np.median(native["y"])),floor=None,n=len(idx),train_start=min(native["days"].tolist()),train_end=max(native["days"].tolist()),linear=ml.fit(native,cfg["alpha"]))
        def predict(package,data,idx):
            a=package["linear"]
            x=data["xb"][idx] if package["recipe"]["kind"]=="ridge_raw" else data["xr"][idx]
            return ml.transform(x,a["medians"],a["mean"],a["scale"])@a["coefficients"]+a["intercept"]
        return dict(feature_names=om.feature_names,mask=lambda data,a,b:(data["days"]>=a)&(data["days"]<=b),base_reference=lambda data,idx,task,median:np.where(np.isfinite(data["xb"][idx,0]),data["xb"][idx,0],median),fit_recipe=fit,predict=predict,calendar_ci=lambda days,p,reference,y:ml.paired_ci(days,abs(p-y),abs(reference-y)),scipy=SimpleNamespace(__version__="unit"),sklearn=SimpleNamespace(__version__="unit"))

    def candidate(self):
        oid=self.origin()
        with patch("cecep_console.optimization_bridge.validated_runner",return_value=(Path("generated"),Path(sys.prefix).resolve(),Path(sys.executable))):
            ds=om.register_candidate(self.s,oid)
            job=ml.submit(self.s,ds["id"],1,"controlled-unit")
            with patch("cecep_console.optimized_models.runpy.run_path",return_value=self.module()):
                ids=ml.execute(self.s,job["id"])
        ml.event(self.s,job["id"],"succeeded",observed_exit_code=0)
        self.s.db.commit()
        return ml.get_object(self.s,ids[0])

    def test_fixed_split_training_is_registered_without_final_arrays_or_pointer_change(self):
        model=self.candidate()
        p=model["payload"]
        self.assertEqual(model["state"],"evaluated")
        self.assertIsNone(ml.active(self.s,p["task"])["detail"].get("model_id"))
        self.assertFalse(p["independent_evidence"])
        self.assertTrue(ml.is_trained_algorithm(p["algorithm"]))
        arrays=ml.read_npz(p["arrays"])
        self.assertFalse(any(k.startswith("final_") for k in arrays))
        self.assertIn("promotion_controlled_optimization",arrays)
        self.assertEqual(self.s.db.execute("SELECT count(*) FROM ml_optimization_origin WHERE model_id=?",(model["id"],)).fetchone()[0],1)
        self.assertEqual(self.s.db.execute("PRAGMA foreign_key_check").fetchall(),[])
        before=self.s.db.execute("SELECT count(*) FROM ml_event").fetchone()[0]
        with self.assertRaises(ValueError):
            ml.prediction(self.s,model["id"],"2024-03-13")
        self.assertEqual(before,self.s.db.execute("SELECT count(*) FROM ml_event").fetchone()[0])
        with self.assertRaises(Exception):
            self.s.db.execute("DELETE FROM ml_model_registry_v3")
        self.s.db.rollback()

    def test_full_inference_grid_does_not_depend_on_unavailable_target_labels(self):
        model=self.candidate()
        _,_,days=public_data.dataset()
        for task in ("pv_day_ahead_reference","prebid_spread_reference","intraday_spread_reference"):
            original=om.input_data(days,"2024-02-26",task,model["payload"]["policy"])
            modified=copy.deepcopy(days)
            for slot,row in modified["2024-02-26"].items():
                if not tc.spec(task)["intraday"] or slot>=48:
                    row["pv_actual_mw"]=None
                    row["rt_price"]=None
                    row["da_price"]=None
            fresh=om.input_data(modified,"2024-02-26",task,model["payload"]["policy"])
            mask=fresh["slots"]<=48 if tc.spec(task)["intraday"] else np.ones(len(fresh["slots"]),dtype=bool)
            np.testing.assert_allclose(original["x"][mask],fresh["x"][mask],equal_nan=True)
            self.assertEqual(len(fresh["slots"]),len(tc.slots(task)))
        prediction=ml.prediction(self.s,model["id"],"2024-02-26")
        self.assertEqual(len(prediction["payload"]["points"]),96)
        self.assertEqual(self.s.db.execute("SELECT point_count FROM ml_predictions WHERE prediction_id=?",(prediction["id"],)).fetchone()[0],96)
        with self.f.csv.open(encoding="utf-8",newline="") as file:
            reader=csv.DictReader(file)
            fields=reader.fieldnames
            source=list(reader)
        for row in source:
            if row["日期"]=="2024-02-26":
                row["光伏总加(实际)"]=""
        with self.f.csv.open("w",encoding="utf-8",newline="") as file:
            writer=csv.DictWriter(file,fieldnames=fields)
            writer.writeheader()
            writer.writerows(source)
        current=public_data.dataset()[0]["source_hash"]
        fresh=ml.prediction(self.s,model["id"],"2024-02-26",input_source_hash=current)
        self.assertTrue(all(p["actual"] is None for p in fresh["payload"]["points"]))
        np.testing.assert_array_equal([p["predicted"] for p in prediction["payload"]["points"]],[p["predicted"] for p in fresh["payload"]["points"]])

    def test_optimized_prediction_feedback_scenario_and_business_context_share_model(self):
        model=self.candidate()
        pred=ml.prediction(self.s,model["id"],"2024-02-10",True)
        f=ml.feedback(self.s,pred["id"],48,"fixture","核对合成测试记录")
        ml.confirm_feedback(self.s,f["id"],"fixture","确认")
        proposal=ml.proposal(self.s,f["id"],1,"fixture","重跑同一冻结优化方案")
        self.assertEqual(proposal["payload"]["change"],"rerun_frozen_optimization")
        retry=ml.train_proposal(self.s,proposal["id"],"controlled-retry")
        self.assertEqual(retry["parent_job_id"],model["payload"]["job_id"])
        self.assertEqual(retry["config"]["engine"],om.ENGINE)
        with self.assertRaisesRegex(ValueError,"正则参数"):
            ml.proposal(self.s,f["id"],10,"fixture","不能伪装树正则调参")
        pred=ml.prediction(self.s,model["id"],"2024-02-26")
        with TestClient(create_app()) as client:
            q=dict(source_key="market:shandong",task_id=model["payload"]["task"],trading_date="2024-02-26",model_id=model["id"],record_id=pred["id"])
            response=client.get("/api/v1/workspace/context",params=q)
            self.assertEqual(response.status_code,200,response.text)
            context=response.json()
            self.assertTrue(next(m for m in context["models"] if m["id"]==model["id"])["trained"])
            details=client.get("/api/v1/workspace/prediction-details",params=q)
            self.assertEqual(details.status_code,200,details.text)
            self.assertIsNone(details.json()["explanation"])
            response=client.post("/api/v1/workspace/commands",json=dict(action="scenario",source_key=q["source_key"],task_id=q["task_id"],date=q["trading_date"],model_id=model["id"],record_id=pred["id"],context_version=context["context_version"],actor="fixture",reason="合成测试量价链路"))
            self.assertEqual(response.status_code,200,response.text)
        self.assertEqual(self.s.db.execute("SELECT count(*) FROM ml_business_scenario_v3").fetchone()[0],1)
        self.assertEqual(self.s.db.execute("PRAGMA foreign_key_check").fetchall(),[])

    def test_direction_and_conditional_evidence_cannot_be_registered_as_amplitude(self):
        oid=self.origin(evaluation_family="direction")
        with self.assertRaisesRegex(ValueError,"方向"):
            om.register_candidate(self.s,oid)
        payload=ml.get_object(self.s,oid)["payload"]
        payload.pop("evaluation_family")
        payload["contract"]["conditional_upstream_required"]=True
        other=ml.add_object(self.s,"optimization_result",payload,self.f.sha,self.f.ds["id"])
        self.s.db.commit()
        with self.assertRaisesRegex(ValueError,"条件"):
            om.register_candidate(self.s,other)

    def test_numeric_tree_predicts_missing_and_infinite_split_without_pickle(self):
        dtype=[(k,"f8") for k in ("value","feature_idx","num_threshold","missing_go_to_left","left","right","is_leaf","is_categorical")]
        nodes=np.zeros(3,dtype=dtype)
        nodes[0]=(0,0,np.inf,0,1,2,0,0)
        nodes[1]=(2,0,0,0,0,0,1,0)
        nodes[2]=(-3,0,0,0,0,0,1,0)
        tree=SimpleNamespace(_baseline_prediction=np.array([[1.]]),_predictors=[[SimpleNamespace(nodes=nodes)]])
        package=dict(recipe=dict(kind="hgb"),task="prebid_spread_reference",fallback=0.,floor=None,train_start="2024-01-01",train_end="2024-02-01",n=10,blend=1,tree=tree)
        a=om.numeric_package(package)
        ref=ml.write_npz("generated/numeric-tree.npz",**a)
        loaded=om.validate(ml.read_npz(ref),45)
        self.assertEqual(om.fitted_parameter_count(loaded),3)
        np.testing.assert_array_equal(om.predict(loaded,dict(x=np.array([[20.],[np.nan]]))),[3.,-2.])
        loaded["tree_nodes"][0,4]=0
        with self.assertRaises(ValueError):
            om.validate(loaded,45)


if __name__=="__main__":
    unittest.main()
