import hashlib
import json
import sqlite3
from pathlib import Path
import unittest

from fastapi.testclient import TestClient
from tests import test_learning as fixtures
from cecep_console import learning as ml, data_flow
from cecep_console.api import create_app
from cecep_console.storage import Store, BASE, instant


class TypedRegistryTests(unittest.TestCase):
    def setUp(self):
        self.fixture=fixtures.LearningTests(); self.fixture.setUp(); self.store=self.fixture.store

    def tearDown(self):
        self.fixture.tearDown()

    def test_version5_upgrade_backfills_relations_without_rewriting_evidence(self):
        _, ids=self.fixture.trained()
        pred=ml.prediction(self.store,ids[0],"2024-02-26")
        data_flow.reconcile(self.store,self.fixture.sha)
        path=self.fixture.base/"old5.sqlite3"
        with Store(path) as old:
            old.db.execute("CREATE TABLE schema_migration(version INTEGER PRIMARY KEY,checksum TEXT NOT NULL,applied_at TEXT NOT NULL)")
            for p in sorted((BASE/"storage_sql").glob("*.sql")):
                version=int(p.name.split("_")[0])
                if version>5:continue
                text=p.read_text(encoding="utf-8")
                old.db.executescript(text)
                old.db.execute("INSERT INTO schema_migration VALUES(?,?,?)",(version,hashlib.sha256(text.encode()).hexdigest(),ml.now()))
                old.db.commit()
            for table in ("ml_object","ml_job","ml_event"):
                for row in self.store.db.execute("SELECT * FROM "+table+" ORDER BY rowid"):
                    old.db.execute("INSERT INTO "+table+" VALUES("+",".join("?" for _ in row)+")",tuple(row))
            old.db.commit()
            before=[tuple(r) for r in old.db.execute("SELECT * FROM ml_object ORDER BY rowid")]
            checksums=[tuple(r) for r in old.db.execute("SELECT version,checksum FROM schema_migration")]
            old.initialize()
            self.assertEqual(old.inspect()["schema_version"],9)
            self.assertEqual([tuple(r) for r in old.db.execute("SELECT * FROM ml_object ORDER BY rowid")],before)
            self.assertEqual([tuple(r) for r in old.db.execute("SELECT version,checksum FROM schema_migration WHERE version<=5")],checksums)
            joined=old.db.execute("SELECT p.prediction_id,m.model_version_id,d.dataset_id FROM ml_prediction_registry p JOIN ml_model_registry m USING(model_version_id) JOIN ml_dataset_registry d USING(dataset_id)").fetchone()
            self.assertEqual(tuple(joined),(pred["id"],ids[0],self.fixture.ds["id"]))
            self.assertFalse(old.inspect()["foreign_key_errors"])
            old.initialize()

    def test_wrong_dataset_kind_cannot_be_used_for_training_even_direct_sql(self):
        _, ids=self.fixture.trained()
        with self.assertRaisesRegex(sqlite3.IntegrityError,"typed dataset"):
            self.store.db.execute("INSERT INTO ml_job VALUES(?,?,?,?,?,?)",("invalid-job",ids[0],None,"invalid-job-key","{}",ml.now()))
        self.store.db.rollback()

    def test_model_cannot_be_attached_to_a_different_jobs_dataset(self):
        _, ids=self.fixture.trained()
        original=ml.get_object(self.store,ids[0])
        other=ml.add_object(self.store,"dataset",self.fixture.ds["payload"],self.fixture.sha,object_id="other-generated-dataset")
        self.store.db.commit()
        with self.assertRaisesRegex(sqlite3.IntegrityError,"model and job dataset mismatch"):
            ml.add_object(self.store,"model",{**original["payload"],"dataset_id":other},self.fixture.sha,other)
        self.store.db.rollback()

    def test_feedback_cannot_point_at_another_predictions_observations(self):
        _, ids=self.fixture.trained()
        one=ml.prediction(self.store,ids[0],"2024-02-26")
        two=ml.prediction(self.store,ids[0],"2024-02-27")
        data_flow.reconcile(self.store,self.fixture.sha)
        obs=data_flow.latest_observation(self.store,two["id"])
        original=ml.feedback(self.store,one["id"],1,"test","generated review")
        with self.assertRaisesRegex(sqlite3.IntegrityError,"another prediction"):
            ml.add_object(self.store,"feedback",{**original["payload"],"observation_id":obs["id"]},self.fixture.sha,one["id"])
        self.store.db.rollback()
        with self.assertRaisesRegex(sqlite3.IntegrityError,"append-only"):
            self.store.db.execute("DELETE FROM ml_prediction_registry WHERE prediction_id=?",(one["id"],))
        self.store.db.rollback()
        plan=" ".join(str(tuple(r)) for r in self.store.db.execute("EXPLAIN QUERY PLAN SELECT observation_id FROM ml_observation_registry WHERE prediction_id=? ORDER BY rowid DESC LIMIT 1",(one["id"],)))
        self.assertIn("ml_observation_prediction",plan)
        with TestClient(create_app()) as client:
            s=client.get("/api/v1/research/schema").json()
            self.assertEqual(s["version"],9)
            self.assertEqual(len(s["tables"]),23)
            self.assertEqual(s["foreign_key_errors"],[])

    def test_prediction_cannot_claim_different_model_weights(self):
        _, ids=self.fixture.trained()
        original=ml.prediction(self.store,ids[0],"2024-02-26")
        cutoff=self.store.db.execute("SELECT cutoff_at FROM ml_prediction_registry WHERE prediction_id=?",(original["id"],)).fetchone()[0]
        self.assertEqual(cutoff,instant(original["payload"]["logical_cutoff"]))
        with self.assertRaisesRegex(sqlite3.IntegrityError,"weights do not match"):
            ml.add_object(self.store,"prediction",{**original["payload"],"weights_hash":"0"*64},self.fixture.sha,ids[0])
        self.store.db.rollback()


if __name__ == "__main__":unittest.main()
