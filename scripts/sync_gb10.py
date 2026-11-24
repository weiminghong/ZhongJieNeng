"""Publish a verified commit + local dist, then validate real GB10 HTTP/SQLite.

Run with the workstation's existing paramiko installation. Credentials are read
from CECEP_GB10_PASSWORD or SSH keys; never written into the receipt.
"""

from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import subprocess
import time
from urllib.request import Request, urlopen
from uuid import uuid4
import paramiko

ROOT = Path(__file__).resolve().parents[1]
REMOTE = "/home/priv/ZhongJieNeng"
BRANCH = "codex/agent-workbench"


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="10.21.179.91")
    parser.add_argument("--user", default="priv")
    parser.add_argument("--verify-only", action="store_true")
    parser.add_argument("--release-manifest", type=Path)
    args = parser.parse_args()
    head = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
    ).strip()
    receipt = {
        "commit": head,
        "host": args.host,
        "remote_root": REMOTE,
        "started_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "checks": [],
    }
    release = None
    dist = ROOT / "apps/web/dist"
    if args.release_manifest:
        manifest_path = args.release_manifest.resolve()
        if not manifest_path.is_relative_to((ROOT / "runtime").resolve()):
            raise RuntimeError("Release manifest must be inside project runtime")
        release = json.loads(manifest_path.read_text(encoding="utf-8"))
        tree = subprocess.check_output(["git", "rev-parse", "HEAD^{tree}"], cwd=ROOT, text=True).strip()
        if release["tree"] != tree:
            raise RuntimeError("Release was not built from the committed source tree")
        dist = Path(release["dist_dir"]).resolve()
        if not dist.is_relative_to((ROOT / "runtime").resolve()):
            raise RuntimeError("Verified dist must be inside project runtime")
        receipt["build_source_tree"] = tree
    client = paramiko.SSHClient()
    client.load_system_host_keys()
    # Explicitly selected private GB10 endpoint. Unknown keys are accepted for this
    # connection only; existing known-host mismatches remain hard errors.
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(
        args.host,
        username=args.user,
        password=os.environ.get("CECEP_GB10_PASSWORD"),
        key_filename=str(Path.home() / ".ssh/id_ed25519"),
        timeout=15,
    )

    def run(command, timeout=180):
        _, out, err = client.exec_command(command, timeout=timeout)
        # Read both streams concurrently: installers must not block on stderr.
        import threading

        errors = []
        reader = threading.Thread(
            target=lambda: errors.append(err.read().decode("utf-8", errors="replace"))
        )
        reader.start()
        output = out.read().decode("utf-8", errors="replace")
        reader.join()
        status = out.channel.recv_exit_status()
        if status:
            raise RuntimeError(
                f"Remote command failed ({status}): {command}\n{output[-3000:]}\n{''.join(errors)[-3000:]}"
            )
        return output.strip()

    def python(code):
        return run(
            f"cd {REMOTE} && PYTHONPATH={REMOTE}/src .venv/bin/python -c "
            + shlex.quote(code)
        )

    def http(path, body=None):
        start = time.perf_counter()
        req = Request(
            f"http://{args.host}:8503" + path,
            data=(
                json.dumps(body, ensure_ascii=False).encode()
                if body is not None
                else None
            ),
            headers={"Content-Type": "application/json"} if body is not None else {},
        )
        with urlopen(req, timeout=60) as response:
            content = response.read()
            status = response.status
        receipt["checks"].append(
            {
                "path": path.split("?")[0],
                "method": "POST" if body is not None else "GET",
                "status": status,
                "bytes": len(content),
                "elapsed_ms": round((time.perf_counter() - start) * 1000, 2),
            }
        )
        return content

    def api(path, body=None):
        return json.loads(http(path, body))

    def inspect():
        return json.loads(
            python(
                "from cecep_console.storage import Store; import json; s=Store(readonly=True); print(json.dumps(s.inspect())); s.close()"
            )
        )

    try:
        receipt["remote_before"] = run(
            f"cd {REMOTE} && pwd -P && git rev-parse HEAD && git status --short && df -h . && df -i ."
        )
        receipt["other_ports_before"] = run(
            "ss -ltn '( sport = :8501 or sport = :8502 )'"
        )
        settings_before = api("/api/v1/settings/llm")
        private_before = python("import hashlib;from cecep_console.model_settings import settings_path;p=settings_path();print(hashlib.sha256(p.read_bytes()).hexdigest() if p.is_file() else 'absent')")
        for port in (8501, 8502):
            with urlopen(f"http://{args.host}:{port}", timeout=15) as response:
                receipt[f"port_{port}_http_before"] = response.status
        if not args.verify_only:
            if release is None:
                subprocess.run(
                    ["git", "diff", "--quiet", "--ignore-submodules"], cwd=ROOT, check=True
                )
                subprocess.run(["git", "diff", "--cached", "--quiet"], cwd=ROOT, check=True)
            if not (dist / "index.html").is_file():
                raise RuntimeError("Build apps/web before deploying")
            files = {
                p.relative_to(dist).as_posix(): {
                    "sha256": sha(p),
                    "bytes": p.stat().st_size,
                }
                for p in dist.rglob("*")
                if p.is_file()
            }
            receipt["dist_files"] = files
            if release is not None and release["files"] != files:
                raise RuntimeError("Verified release artifact hashes no longer match")
            run(
                f'cd {REMOTE} && test "$(pwd -P)" = {REMOTE} && git diff --quiet --ignore-submodules && git diff --cached --quiet && git fetch origin {BRANCH} && test "$(git rev-parse origin/{BRANCH})" = {head} && git merge --ff-only origin/{BRANCH}'
            )
            receipt["remote_head"] = run(f"cd {REMOTE} && git rev-parse HEAD")
            if receipt["remote_head"] != head:
                raise RuntimeError("Remote HEAD does not match verified commit")
            receipt["db_before"] = inspect()
            # Online SQLite backup preserves pre-migration data without stopping reads.
            receipt["backup"] = python(
                "from pathlib import Path; import sqlite3,json; root=Path('.').resolve(); db=(root/'runtime/data/cecep.sqlite3').resolve(); assert db.is_relative_to(root); dest=root/'runtime/backups'/('before-workbench-"
                + head[:12]
                + ".sqlite3'); dest.parent.mkdir(parents=True,exist_ok=True); print(json.dumps({'db':str(db),'bytes':db.stat().st_size,'backup':str(dest)})); source=sqlite3.connect(db); target=sqlite3.connect(dest); source.backup(target); target.close(); source.close()"
            )
            receipt["install"] = run(
                f"cd {REMOTE} && mkdir -p runtime/tmp runtime/cache/pip && TMPDIR={REMOTE}/runtime/tmp XDG_CACHE_HOME={REMOTE}/runtime/cache PIP_CACHE_DIR={REMOTE}/runtime/cache/pip .venv/bin/pip install -e .",
                timeout=600,
            )[-3000:]
            staging = f"{REMOTE}/apps/web/.dist-upload-{uuid4().hex}"
            run("mkdir -p " + shlex.quote(staging + "/assets"))
            with client.open_sftp() as sftp:
                for rel in files:
                    # Vite emits only index + assets; no arbitrary path traversal.
                    if not re.fullmatch(r"((?:index|settings)\.html|assets/[A-Za-z0-9_.-]+)", rel):
                        raise RuntimeError("Unexpected dist path: " + rel)
                    sftp.put(str(dist / rel), staging + "/" + rel)
            check_code = (
                """from pathlib import Path
import hashlib,json,os,shutil
root=Path('/home/priv/ZhongJieNeng').resolve()
staging=Path(STAGING).resolve()
assert staging.is_relative_to(root/'apps/web') and staging.is_dir()
files=FILES
for rel,spec in files.items():
    p=staging/rel
    assert p.stat().st_size==spec['bytes']
    assert hashlib.sha256(p.read_bytes()).hexdigest()==spec['sha256']
dist=root/'apps/web/dist'
previous=root/'runtime/backups'/('web-dist-before-'+HEAD)
if dist.exists():
    assert not previous.exists(), 'Existing backup must be preserved'
    dist.rename(previous)
staging.rename(dist)
print(json.dumps({'uploaded_files':len(files),'bytes':sum(f['bytes'] for f in files.values()),'sha256_verified':True}))
""".replace("STAGING", repr(staging))
                .replace("FILES", repr(files))
                .replace("HEAD", repr(head[:12]))
            )
            receipt["upload"] = json.loads(python(check_code))
            receipt["migration"] = json.loads(
                python(
                    "from cecep_console.storage import Store;from cecep_console.storage_demo import seed_demo;import json;s=Store();s.initialize();r=seed_demo(s);print(json.dumps(r));s.close()"
                )
            )
            receipt["seed_idempotence"] = json.loads(
                python(
                    "from cecep_console.storage import Store;from cecep_console.storage_demo import seed_demo;import json;s=Store();s.initialize();print(json.dumps({'inserted':seed_demo(s)['inserted']}));s.close()"
                )
            )
            assert receipt["seed_idempotence"]["inserted"] == 0
            run("systemctl --user restart cecep-storage.service")
            # Bounded readiness retries, with no long blind sleeps.
            for attempt in range(20):
                try:
                    if api("/api/health")["service"] == "cecep-workbench-v1":
                        break
                except OSError:
                    time.sleep(0.5)
            else:
                raise RuntimeError("8503 readiness failed")
        receipt["service"] = run(
            "systemctl --user show cecep-storage.service --property=ActiveState,SubState,MainPID,ExecMainStatus"
        )
        html = http("/").decode()
        assert '<div id="root">' in html and 'src="/assets/' in html
        assets = re.findall(r'(?:src|href)="(/assets/[^"]+)"', html)
        for asset in assets:
            content = http(asset)
            local = dist / asset.removeprefix("/")
            assert local.is_file() and hashlib.sha256(content).hexdigest() == sha(
                local
            ), asset
        receipt["spa_fallback"] = b'<div id="root">' in http("/workbench/forecast")
        settings_html = http("/settings").decode()
        assert 'src="/assets/' in settings_html
        for asset in re.findall(r'(?:src|href)="(/assets/[^"]+)"', settings_html):
            local = dist / asset.removeprefix("/")
            assert local.is_file() and hashlib.sha256(http(asset)).hexdigest() == sha(local)
        model_settings = api("/api/v1/settings/llm")
        assert "api_key" not in model_settings
        receipt["model_settings"] = {
            "model": model_settings["model"],
            "ready": model_settings["ready"],
            "api_key_configured": model_settings["api_key_configured"],
        }
        bootstrap = api("/api/v1/workbench/bootstrap")
        assert (
            len(bootstrap["stations"]) == 2
            and bootstrap["llm_mode"] in (
                "deterministic_tools_only", "openai_compatible_evidence_summary"
            )
        )
        overview = api("/api/v1/workbench/overview")
        assert len(overview["intervals"]) == 96 and "serving_" in overview["query_path"]
        receipt["overview"] = {
            "query_path": overview["query_path"],
            "kpi": overview["kpi"],
            "cutoff_at": overview["cutoff_at"],
        }
        replay = api(
            "/api/v1/workbench/overview?mode=replay&cutoff_at=2026-11-20T01%3A00%3A00Z"
        )
        assert "pit_engine" in replay["query_path"]
        assert all(
            r["actual_mw"] is None
            for r in replay["intervals"]
            if r["interval_end"] > replay["cutoff_at"]
        )
        assert all(
            ref["available_at"] <= replay["cutoff_at"]
            for r in replay["intervals"]
            for ref in json.loads(r["lineage_refs_json"])
        )
        receipt["replay"] = {
            "query_path": replay["query_path"],
            "cutoff_at": replay["cutoff_at"],
            "no_future_actuals": True,
            "all_lineage_visible": True,
        }
        raw = api("/api/v1/workbench/raw")
        line = api(
            "/api/v1/workbench/lineage?interval_start="
            + raw["intervals"][48]["interval_start"].replace(":", "%3A")
        )
        assert line["evidence"] and all(
            e["available_before_cutoff"] for e in line["evidence"]
        )
        comparison = api("/api/v1/workbench/compare")
        assert (
            len(comparison["versions"]) >= 3
            and len({v["cutoff_at"] for v in comparison["versions"]}) == 1
        )
        receipt["compare"] = {
            "query_path": comparison["query_path"],
            "versions": len(comparison["versions"]),
            "matched_samples": [v["sample_count"] for v in comparison["versions"]],
        }
        trading = api("/api/v1/workbench/trading")
        assert len(trading["plans"]) == 3
        recalculated = api("/api/v1/workbench/trading/recalculate", {})
        assert [p["net_revenue_yuan"] for p in trading["plans"]] == [
            p["net_revenue_yuan"] for p in recalculated["plans"]
        ]
        receipt["trading"] = [
            {
                k: p[k]
                for k in (
                    "plan_name",
                    "net_revenue_yuan",
                    "settled_count",
                    "unsettled_count",
                    "revenue_run_id",
                )
            }
            for p in trading["plans"]
        ]
        agent = api(
            "/api/v1/agent/query",
            {"question": "部署验收：偏差免考和合约收益有哪些依据？"},
        )
        assert (
            agent["llm_mode"] == bootstrap["llm_mode"]
            and len(agent["tool_calls"]) == 6
            and agent["grounded_check_passed"]
        )
        history = api("/api/v1/agent/history")
        assert history["history"][0]["response_id"] == agent["response_id"]
        rsi = api("/api/v1/workbench/rsi")
        assert rsi["cases"]
        case = rsi["cases"][0]
        feedback = api(
            "/api/v1/rsi/feedback",
            {
                "case_id": case["case_id"],
                "reason": "部署验收天气复核：合成场景云量关联线索，仅用于演示持久化验证，非生产因果结论。",
                "training_eligible": False,
                "reviewer_id": "deployment-verifier",
            },
        )
        ingest = api("/api/v1/rsi/rag-ingest", {"feedback_id": feedback["feedback_id"]})
        refreshed = api("/api/v1/workbench/rsi")
        persisted = next(
            c for c in refreshed["cases"] if c["case_id"] == case["case_id"]
        )
        assert (
            persisted["feedback"]["feedback_id"] == feedback["feedback_id"]
            and persisted["rag_doc_id"] == ingest["doc_id"]
        )
        rag_agent = api("/api/v1/agent/query", {"question": "部署验收天气复核"})
        assert ingest["chunk_id"] in [c.get("chunk_id") for c in rag_agent["citations"]]
        receipt["writes"] = {
            "agent_run_id": agent["agent_run_id"],
            "tool_calls": len(agent["tool_calls"]),
            "feedback_id": feedback["feedback_id"],
            "rag_doc_id": ingest["doc_id"],
            "rag_retrieved_after_ingest": True,
        }
        candidate = next(
            m
            for m in refreshed["models"]
            if m["model_version_id"] == "lgbm-demo-v2.2-cand"
        )
        if candidate["effective_status"] == "production":
            raise RuntimeError(
                "Candidate already production: preserve existing decision; manual lifecycle test required"
            )
        approve = api(
            "/api/v1/rsi/approve",
            {
                "candidate_id": "demo-candidate-v2.2",
                "action": "approve",
                "reason": "部署验收：演示注册生命周期上线验证",
                "reviewer_id": "deployment-verifier",
            },
        )
        check = api("/api/v1/workbench/rsi")
        assert (
            next(
                m
                for m in check["models"]
                if m["model_version_id"] == "lgbm-demo-v2.2-cand"
            )["effective_status"]
            == "production"
        )
        rollback = api(
            "/api/v1/rsi/approve",
            {
                "candidate_id": "demo-candidate-v2.2",
                "action": "rollback",
                "reason": "部署验收：恢复演示基线状态",
                "reviewer_id": "deployment-verifier",
            },
        )
        check = api("/api/v1/workbench/rsi")
        assert (
            next(
                m for m in check["models"] if m["model_version_id"] == "lgbm-demo-v2.1"
            )["effective_status"]
            == "production"
        )
        receipt["lifecycle"] = {
            "approval_decision_id": approve["decision_id"],
            "rollback_decision_id": rollback["decision_id"],
            "events_added": len(approve["events"]) + len(rollback["events"]),
        }
        for endpoint in [
            "health",
            "query?table=station_actual&cutoff=2026-11-20T06%3A00%3A00Z&demo=1",
            "features?station=lanneng&task=day_ahead_power&start=2026-11-21T00%3A00%3A00%2B08%3A00&end=2026-11-22T00%3A00%3A00%2B08%3A00&cutoff=2026-11-20T06%3A00%3A00Z&demo=1",
            "predictions?station=lanneng&task=day_ahead_power&start=2026-11-21T00%3A00%3A00%2B08%3A00&end=2026-11-22T00%3A00%3A00%2B08%3A00&cutoff=2026-11-20T06%3A00%3A00Z&demo=1",
        ]:
            api("/api/storage/" + endpoint)
        receipt["db_after"] = inspect()
        learning = api("/api/v1/ml/overview")
        capabilities = api("/api/v1/ml/capabilities")
        assert capabilities["tasks"][0]["task"] == "rt_price_day_ahead_reference"
        assert capabilities["tasks"][0]["production_eligible"] is False
        assert learning["policy"]["time_policy"] == "historical_assumed"
        receipt["learning_readiness"] = {"worker": learning["worker"]["state"], "jobs": len(learning["jobs"]), "models": len(learning["models"]), "production_eligible": False}
        assert (
            receipt["db_after"]["integrity"] == "ok"
            and not receipt["db_after"]["foreign_key_errors"]
            and receipt["db_after"]["schema_version"] == 5
        )
        receipt["db_write_verification"] = json.loads(
            python(
                "import json;from cecep_console.storage import Store;s=Store(readonly=True);print(json.dumps({'agent_tools':s.db.execute('SELECT count(*) FROM agent_tool_call WHERE agent_run_id=?',("
                + repr(agent["agent_run_id"])
                + ",)).fetchone()[0],'feedback':s.db.execute('SELECT count(*) FROM review_feedback WHERE feedback_id=?',("
                + repr(feedback["feedback_id"])
                + ",)).fetchone()[0],'rag_fts':s.db.execute('SELECT count(*) FROM rag_chunk_fts WHERE chunk_id=?',("
                + repr(ingest["chunk_id"])
                + ",)).fetchone()[0]}));s.close()"
            )
        )
        assert receipt["db_write_verification"] == {
            "agent_tools": 6,
            "feedback": 1,
            "rag_fts": 1,
        }
        receipt["other_ports_after"] = run(
            "ss -ltn '( sport = :8501 or sport = :8502 )'"
        )
        for port in (8501, 8502):
            with urlopen(f"http://{args.host}:{port}", timeout=15) as response:
                receipt[f"port_{port}_http_status"] = response.status
        runtime_models = api("/api/v1/models/runtime")
        assert any(m["ready"] and m["adapter_type"] == "builtin" for m in runtime_models["models"])
        prediction = api("/api/v1/models/predict", {"persist": True})
        assert len(prediction["points"]) == 96 and prediction["persisted_run_id"]
        brief = api("/api/v1/agent/proactive/run", {})
        assert brief["brief_id"] and len(brief["signals"]) == 4
        latest = api("/api/v1/agent/proactive")
        assert latest["briefs"][0]["brief_id"] == brief["brief_id"]
        model_agent = api("/api/v1/agent/query", {"question": "调用小模型实时预测，比较线上预测"})
        assert any(c["tool_name"] == "invoke_forecast_model" for c in model_agent["tool_calls"])
        scenario_agent = api("/api/v1/agent/query", {"question": "云量+30%场景推演，联动收益沙盘"})
        assert any(c["tool_name"] == "run_what_if_forecast" for c in scenario_agent["tool_calls"])
        receipt["runtime_inference"] = {k:v for k,v in prediction.items() if k != "points"}
        receipt["proactive_brief"] = {"brief_id": brief["brief_id"], "severity": brief["severity"], "headline": brief["headline"]}
        receipt["runtime_db_verification"] = json.loads(python(
            "import json;from cecep_console.storage import Store;s=Store(readonly=True);print(json.dumps({'prediction_points':s.db.execute('SELECT count(*) FROM prediction_value WHERE run_id=?',(" + repr(prediction["persisted_run_id"]) + ",)).fetchone()[0],'brief_rows':s.db.execute('SELECT count(*) FROM agent_proactive_brief WHERE brief_id=?',(" + repr(brief["brief_id"]) + ",)).fetchone()[0],'inference_tool_rows':s.db.execute(\"SELECT count(*) FROM agent_tool_call WHERE agent_run_id=? AND tool_name='invoke_forecast_model'\",(" + repr(model_agent["agent_run_id"]) + ",)).fetchone()[0]}));s.close()"))
        assert receipt["runtime_db_verification"] == {"prediction_points":96, "brief_rows":1, "inference_tool_rows":1}
        receipt["scenario"] = {"agent_run_id":scenario_agent["agent_run_id"], "artifacts":len(scenario_agent["artifacts"]),
                               "sandbox":next(c["output"]["sandbox"] for c in scenario_agent["tool_calls"] if c["tool_name"] == "run_what_if_forecast")}
        public_catalog = api("/api/v1/public-data/catalog")
        assert public_catalog["available"] and public_catalog["metadata"]["row_count"] > 0
        public_day = public_catalog["default_date"]
        public_hash = public_catalog["metadata"]["source_hash"]
        public_scope = {"date": public_day, "cursor": 48, "source_hash": public_hash}
        public_url = "/api/v1/public-data/series?date=" + public_day + "&source_hash=" + public_hash
        public_early = api(public_url + "&cursor=48")
        public_next = api(public_url + "&cursor=49")
        assert public_early["summary"]["visible_records"] == 48 and public_next["summary"]["visible_records"] == 49
        assert all(p["source_values"] is None and p["pv_actual_mw"] is None for p in public_early["points"][48:])
        public_scenario = api("/api/v1/public-data/scenario", {**public_scope, "quantity_mwh": 2, "fee_yuan_mwh": 3})
        price_pairs = [p for p in public_early["points"] if p["visible"] and p["spread_yuan_mwh"] is not None]
        expected_exposure = sum((p["rt_price"] - p["da_price"] - 3) * 2 for p in price_pairs)
        assert price_pairs and abs(public_scenario["net_spread_yuan"] - expected_exposure) < 1e-8
        public_answer = api("/api/v1/public-data/analyze", {**public_scope, "question": "分析当前公开历史范围的光伏列误差和价差，说明数据来源与适用边界"})
        assert public_answer["status"] == "completed" and len(public_answer["evidence"]["source_records"]) == 48
        public_review = api("/api/v1/public-data/review", {**public_scope, "selected_slot": 47, "reason": "部署验收公开样例复核：核对源文件行号、日期与价差，不代表生产归因，不纳入训练。"})
        public_history = api("/api/v1/public-data/history?date=" + public_day + "&source_hash=" + public_hash)
        public_ids = {run["run_id"] for run in public_history["runs"]}
        assert public_answer["run_id"] in public_ids and public_review["run_id"] in public_ids
        receipt["public_data"] = {"metadata": public_catalog["metadata"], "verified_date": public_day,
                                  "visible_records": [48, 49], "future_records_hidden": True,
                                  "scenario_net_spread_yuan": public_scenario["net_spread_yuan"],
                                  "analysis_run_id": public_answer["run_id"], "review_run_id": public_review["run_id"],
                                  "analysis_mode": public_answer["llm_mode"]}
        private_after = python("import hashlib;from cecep_console.model_settings import settings_path;p=settings_path();print(hashlib.sha256(p.read_bytes()).hexdigest() if p.is_file() else 'absent')")
        assert private_after == private_before and api("/api/v1/settings/llm") == settings_before
        receipt["private_llm_configuration_unchanged"] = True
        receipt["db_after"] = inspect()
        assert receipt["db_after"]["integrity"] == "ok" and not receipt["db_after"]["foreign_key_errors"]
        if "db_before" in receipt:
            assert all(receipt["db_after"]["tables"].get(table,0) >= count for table,count in receipt["db_before"]["tables"].items() if not table.startswith("serving_"))
            receipt["old_table_row_counts_preserved"] = True
        if (ROOT / "runtime/agent-runtime-local-validation.json").is_file():
            receipt["local_validation"] = json.loads((ROOT / "runtime/agent-runtime-local-validation.json").read_text(encoding="utf-8"))
        receipt["status"] = "passed"
    except BaseException as exc:
        receipt["status"] = "failed"
        receipt["error"] = str(exc)
        raise
    finally:
        client.close()
        target = ROOT / "runtime/gb10-deploy-receipt.json"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(
            json.dumps(receipt, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        (ROOT / "runtime/agent-runtime-proactive-audit.json").write_text(
            json.dumps(receipt, ensure_ascii=False, indent=2), encoding="utf-8")
        print(
            json.dumps(
                {
                    "status": receipt["status"],
                    "commit": head,
                    "receipt": str(target),
                    "http_checks": len(receipt["checks"]),
                },
                ensure_ascii=False,
            )
        )


if __name__ == "__main__":
    main()
