"""Run a frozen server-side optimization recipe through the existing CPU queue."""

import hashlib
import os
from pathlib import Path
import re
import runpy
import sys

ENGINE = "controlled_research_v2"


def validated_runner(policy):
    from . import learning as ml

    if policy.get("engine") != ENGINE:
        raise ValueError("未登记的优化执行器")
    config = policy["optimization_runner"]
    relative = Path(config["path"])
    if (
        relative.is_absolute()
        or not relative.parts
        or relative.parts[0] != "runs"
        or relative.name != "worker.py"
    ):
        raise ValueError("优化脚本必须属于已登记的服务端运行目录")
    runner = ml.file_path(str(relative))
    if not runner.is_relative_to(ml.file_path("runs")):
        raise ValueError("优化脚本不能越过运行目录")
    if (
        not runner.is_file()
        or hashlib.sha256(runner.read_bytes()).hexdigest() != config["sha256"]
    ):
        raise ValueError("优化脚本与冻结方案不一致")
    name = config["environment"]
    if not re.fullmatch(r"[a-zA-Z0-9_-]+", name):
        raise ValueError("优化环境名称无效")
    environment = ml.file_path("envs/" + name)
    python = environment / "bin/python"
    if not (environment / "pyvenv.cfg").is_file() or not python.is_file():
        raise ValueError("优化运行环境尚未准备完成")
    return runner, environment, python


def execute(store, jid, policy):
    from . import learning as ml

    runner, environment, python = validated_runner(policy)
    if ml.job(store, jid)["config"]["policy_hash"] != ml.digest(policy):
        raise ValueError("优化作业与冻结配置不一致")
    if Path(sys.prefix).resolve() != environment:
        # exec keeps the PID, process birth identity and controller ownership.
        ml.event(store, jid, "preparing", stage="进入隔离的模型优化环境")
        store.db.commit()
        env = dict(os.environ, PYTHONPATH=str(Path(__file__).resolve().parents[1]))
        store.close()
        os.execve(
            str(python),
            [str(python), "-m", "cecep_console.ml_worker", "--job", jid],
            env,
        )
    module = runpy.run_path(str(runner), run_name="cecep_controlled_optimization")
    return module["execute"](store, jid, policy)
