from pathlib import Path
import hashlib
from unittest.mock import patch
import unittest
from tests import test_learning as fixtures
from cecep_console import learning as ml, optimization_bridge as bridge


class OptimizationBridgeTests(unittest.TestCase):
    def setUp(self):
        self.f = fixtures.LearningTests()
        self.f.setUp()
        root = ml.root()
        self.runner = root / "runs/generated-optimizer/worker.py"
        self.runner.parent.mkdir(parents=True)
        self.runner.write_text("def execute(store,jid,policy): return jid\n")
        env = root / "envs/generated-optimizer"
        (env / "bin").mkdir(parents=True)
        (env / "pyvenv.cfg").write_text("generated test only")
        (env / "bin/python").write_text("generated test only")
        self.policy = dict(
            ml.POLICY,
            engine=bridge.ENGINE,
            optimization_runner=dict(
                path="runs/generated-optimizer/worker.py",
                sha256=hashlib.sha256(self.runner.read_bytes()).hexdigest(),
                environment="generated-optimizer",
            ),
        )

    def tearDown(self):
        self.f.tearDown()

    def test_hash_and_path_guards_reject_changed_or_escaping_code(self):
        bridge.validated_runner(self.policy)
        self.runner.write_text("changed")
        with self.assertRaises(ValueError):
            bridge.validated_runner(self.policy)
        self.policy["optimization_runner"]["path"] = "runs/../worker.py"
        with self.assertRaises(ValueError):
            bridge.validated_runner(self.policy)

    def test_registered_engine_uses_same_job_and_validated_environment(self):
        ds = ml.add_object(
            self.f.store,
            "dataset",
            dict(self.f.ds["payload"], policy=self.policy),
            self.f.sha,
            self.f.ds["parent_id"],
        )
        self.f.store.db.commit()
        j = ml.submit(self.f.store, ds, 1, "optimizer-fixture")
        self.assertEqual(j["config"]["engine"], bridge.ENGINE)
        _, env, _ = bridge.validated_runner(self.policy)
        with patch.object(bridge.sys, "prefix", str(env)):
            self.assertEqual(ml.execute(self.f.store, j["id"]), j["id"])


if __name__ == "__main__":
    unittest.main()
