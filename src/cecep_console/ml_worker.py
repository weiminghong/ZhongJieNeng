"""One persistent CPU queue controller; each child owns one immutable attempt."""
import argparse
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time
import shutil

# Set before importing NumPy, in controller and child alike.
for name in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "NUMEXPR_NUM_THREADS"):
    os.environ[name] = "4"

from .storage import Store
from . import learning as ml


def birth(pid):
    try:
        return Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()[19]
    except (OSError, IndexError):
        return None


def matches(pid, token, jid):
    try:
        args = Path(f"/proc/{pid}/cmdline").read_bytes().split(b"\0")
        return token is not None and birth(pid) == token and jid.encode() in args and b"cecep_console.ml_worker" in args
    except OSError:
        return False


def controller():
    import fcntl
    base = ml.root()
    os.environ["TMPDIR"] = str(base / "tmp")
    os.environ["XDG_CACHE_HOME"] = str(base / "cache")
    Path(os.environ["TMPDIR"]).mkdir(exist_ok=True)
    Path(os.environ["XDG_CACHE_HOME"]).mkdir(exist_ok=True)
    # Descriptor stays open for the entire controller lifetime.
    with (base / "controller.lock").open("a+") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return
        stopping = False
        child = None
        def stop(*_):
            nonlocal stopping
            stopping = True
        signal.signal(signal.SIGTERM, stop)
        signal.signal(signal.SIGINT, stop)
        with Store() as store:
            ml.event(store, "worker", "ready", pid=os.getpid(), birth=birth(os.getpid()), device="CPU", threads=4)
            store.db.commit()
            # Audit old ownership. Never duplicate a surviving worker or invent its exit.
            for r in store.db.execute("SELECT job_id FROM ml_job ORDER BY rowid").fetchall():
                j = ml.job(store, r[0])
                if j["state"] not in ml.TERMINAL | {"queued"}:
                    ownership = store.db.execute("SELECT payload_json FROM ml_event WHERE subject_id=? AND state='started' ORDER BY rowid DESC LIMIT 1", ("ownership:"+j["id"],)).fetchone()
                    detail = json.loads(ownership[0]) if ownership else {}
                    if matches(detail.get("pid"), detail.get("birth"), j["id"]):
                        ml.event(store, "worker", "waiting_owned_child", job_id=j["id"])
                        store.db.commit()
                        while matches(detail["pid"], detail["birth"], j["id"]) and not stopping:
                            time.sleep(1)
                    if stopping:
                        return
                    ml.event(store, j["id"], "unknown_exit", reason="原控制器未观测退出；保留已有产物，可显式创建新尝试")
                    store.db.commit()
            heartbeat = 0
            source_check = 0
            while not stopping:
                if time.monotonic()-source_check >= ml.POLICY["monitor"]["interval_seconds"]:
                    ml.monitor_source(store); source_check = time.monotonic()
                if time.monotonic()-heartbeat >= 15:
                    ml.event(store, "worker", "ready", pid=os.getpid(), birth=birth(os.getpid()), checked_at=ml.now())
                    store.db.commit(); heartbeat = time.monotonic()
                pending = [ml.job(store, r[0]) for r in store.db.execute("SELECT job_id FROM ml_job ORDER BY rowid")]
                pending = [j for j in pending if j["state"] == "queued"]
                if not pending:
                    time.sleep(1); continue
                j = pending[0]; jid = j["id"]
                stats = os.statvfs(base)
                if shutil.disk_usage(base).free < 1024**3 or stats.f_favail < 1000:
                    ml.event(store, jid, "failed", error="产物磁盘不足1GiB或inode不足，未启动训练")
                    store.db.commit(); continue
                log = ml.file_path(f"jobs/{jid}/worker.log")
                log.parent.mkdir(parents=True, exist_ok=True)
                # Claim transaction competes with cancellation, then spawn only this child.
                store.db.execute("BEGIN IMMEDIATE")
                if ml.state(store, jid)["state"] != "queued":
                    store.db.rollback(); continue
                ml.event(store, jid, "claimed", controller_pid=os.getpid()); store.db.commit()
                started = time.monotonic()
                with log.open("ab") as stream:
                    child = subprocess.Popen([sys.executable, "-m", "cecep_console.ml_worker", "--job", jid], stdout=stream, stderr=stream, close_fds=True)
                    ml.event(store, "ownership:"+jid, "started", pid=child.pid, birth=birth(child.pid), controller_pid=os.getpid())
                    store.db.commit()
                    cancelled = False; timed_out = False
                    while child.poll() is None:
                        if time.monotonic()-heartbeat >= 15:
                            ml.event(store, "worker", "busy", pid=os.getpid(), birth=birth(os.getpid()), job_id=jid)
                            store.db.commit(); heartbeat = time.monotonic()
                        cancelled = ml.state(store, jid)["state"] == "cancel_requested"
                        timed_out = time.monotonic()-started > ml.POLICY["timeout_seconds"]
                        if cancelled or timed_out or stopping:
                            child.terminate()
                            try:
                                child.wait(timeout=10)
                            except subprocess.TimeoutExpired:
                                child.kill(); child.wait()
                            break
                        time.sleep(.5)
                    code = child.wait()
                    latest = ml.state(store, jid)
                    if stopping:
                        status = "interrupted"
                    elif cancelled:
                        status = "cancelled"
                    elif code == 0 and latest["state"] == "child_complete":
                        status = "succeeded"
                    else:
                        status = "failed"
                    ml.event(store, jid, status, **latest["detail"], observed_exit_code=code, timeout=timed_out, log_path=str(log.relative_to(base)))
                    store.db.commit(); child = None
            ml.event(store, "worker", "stopped", pid=os.getpid()); store.db.commit()


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--job")
    args = p.parse_args()
    if not args.job:
        controller(); return
    with Store() as store:
        try:
            # Parent records birth identity before this child may change job state.
            deadline = time.monotonic()+10
            while ml.state(store, "ownership:"+args.job)["state"] != "started":
                if time.monotonic() > deadline:
                    raise ValueError("缺少父控制器的启动归属记录")
                time.sleep(.05)
            if ml.state(store, args.job)["state"] in {"cancelled", "cancel_requested"}:
                raise ValueError("任务已取消")
            ml.execute(store, args.job)
        except Exception as exc:
            ml.event(store, args.job, "child_failed", error=str(exc), error_type=type(exc).__name__)
            store.db.commit()
            raise


if __name__ == "__main__":
    main()
