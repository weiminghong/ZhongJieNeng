"""Public regional price research: immutable lineage and real NumPy inference.

Historical availability is assumed, never certified. No serving-table inputs.
"""

from datetime import date, timedelta, datetime
import hashlib
import json
import os
from pathlib import Path
import time
from uuid import uuid4

import numpy as np

from . import public_data
from .storage import digest, encoded
from .serving import now
from . import task_catalog as tasks

TASK = "rt_price_day_ahead_reference"
SPLITS = {
    "train": ["2024-01-08", "2025-08-30"],
    "tune": ["2025-09-01", "2025-09-29"],
    "promotion": ["2025-10-01", "2025-11-29"],
    "final_audit": ["2025-12-01", "2026-01-14"],
}
FEATURES = [
    "rt_lag_2d_same_slot",
    "rt_lag_3d_same_slot",
    "rt_lag_7d_same_slot",
    "rt_mean_d2",
    "rt_min_d2",
    "rt_max_d2",
    "rt_mean_d7",
    "slot_sin",
    "slot_cos",
    "weekday_sin",
    "weekday_cos",
    "month_sin",
    "month_cos",
]
BASELINES = ["seasonal_naive_d2", "seasonal_naive_d7", "train_weekday_slot_median"]
TERMINAL = {"succeeded", "failed", "cancelled", "interrupted", "unknown_exit"}
POLICY = dict(
    contract="cecep-closed-loop-v1",
    task=TASK,
    unit="CNY/MWh",
    source_kind="public_reference",
    time_policy="historical_assumed",
    production_eligible=False,
    availability_timestamps_verified=False,
    features=FEATURES,
    cutoff="D-1 09:00 Asia/Shanghai; inputs through D-2",
    alpha_choices=[0.1, 1, 10, 100],
    baseline_missing="train target median",
    promotion_gate="paired 7-day block bootstrap upper95(delta MAE)<0 and RMSE<=incumbent",
    bootstrap=dict(block_days=7, replicates=2000, seed=42),
    monitor=dict(
        interval_seconds=30, expected_intervals=96, missing_target_warn_above=0
    ),
    actor_verification="intranet_declared",
    threads=4,
    timeout_seconds=1800,
)


def is_trained_algorithm(name):
    return name in {"ridge", "controlled_optimization"}


def validate_payload(payload):
    a = read_npz(payload["weights"])
    if payload["algorithm"] == "controlled_optimization":
        from .optimized_models import validate
        validate(a, len(payload["policy"]["features"]))
        meta = json.loads(a["metadata"].astype(np.uint8).tobytes())
        if meta["task"] != payload["task"] or digest(dict(recipe=meta["recipe"], blend=meta["blend"])) != payload["recipe_hash"]:
            raise ValueError("优化权重与模型任务或方案不一致")
        return a
    return validate_model(a, len(payload["policy"]["features"]))


def predict_payload(payload, data):
    a = validate_payload(payload)
    if payload["algorithm"] == "controlled_optimization":
        from .optimized_models import predict
        return predict(a, data)
    return bounded_outputs(a, data, payload["task"], payload.get("output_bounds"))[payload["algorithm"]]


def root():
    p = Path(
        os.environ.get(
            "CECEP_ML_ROOT", Path(__file__).resolve().parents[2] / "runtime/ml"
        )
    ).resolve()
    p.mkdir(parents=True, exist_ok=True)
    if not os.access(p, os.W_OK):
        raise ValueError("模型产物目录不可写")
    return p


def file_path(relative):
    p = (root() / relative).resolve()
    if not p.is_relative_to(root()):
        raise ValueError("产物路径越界")
    return p


def checksum(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def atomic(relative, content):
    p = file_path(relative)
    p.parent.mkdir(parents=True, exist_ok=True)
    if p.exists():
        raise ValueError("不可覆盖已有产物")
    temporary = p.with_name(p.name + "." + uuid4().hex + ".tmp")
    try:
        with temporary.open("xb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        temporary.replace(p)
    finally:
        temporary.unlink(missing_ok=True)
    return {"path": relative, "sha256": checksum(p), "bytes": p.stat().st_size}


def write_npz(relative, **arrays):
    import io

    buffer = io.BytesIO()
    np.savez_compressed(buffer, **arrays)
    return atomic(relative, buffer.getvalue())


def read_npz(ref):
    p = file_path(ref["path"])
    if checksum(p) != ref["sha256"]:
        raise ValueError("产物校验失败，禁止推理或评估")
    with np.load(p, allow_pickle=False) as values:
        return {k: values[k] for k in values.files}


def event(store, subject, state, **payload):
    store.db.execute(
        "INSERT INTO ml_event VALUES(?,?,?,?,?)",
        (uuid4().hex, subject, state, encoded(payload), now()),
    )


def state(store, subject):
    r = store.db.execute(
        "SELECT state,payload_json,created_at FROM ml_event WHERE subject_id=? ORDER BY rowid DESC LIMIT 1",
        (subject,),
    ).fetchone()
    return (
        dict(state=r[0], detail=json.loads(r[1]), updated_at=r[2])
        if r
        else dict(state="registered", detail={})
    )


def add_object(store, kind, payload, source_hash, parent=None, object_id=None):
    oid = object_id or kind + "_" + uuid4().hex
    store.db.execute(
        "INSERT INTO ml_object VALUES(?,?,?,?,?,?)",
        (oid, kind, parent, source_hash, encoded(payload), now()),
    )
    return oid


def get_object(store, oid, kind=None):
    r = store.db.execute("SELECT * FROM ml_object WHERE object_id=?", (oid,)).fetchone()
    if not r or (kind and r["kind"] != kind):
        raise ValueError("指定对象不存在或类型不符")
    payload = json.loads(r["payload_json"])
    family = payload.get("algorithm") if r["kind"] == "model" else None
    n = store.db.execute(
        "SELECT count(*) FROM ml_object WHERE kind=? AND rowid<=(SELECT rowid FROM ml_object WHERE object_id=?)"
        + (" AND json_extract(payload_json,'$.algorithm')=?" if family else ""),
        (r["kind"], oid, family) if family else (r["kind"], oid),
    ).fetchone()[0]
    prefix = {
        "dataset": "研究数据",
        "source_revision": "历史数据",
        "prediction": "预测记录",
        "observation_match": "观测核对",
        "feedback": "复核记录",
        "proposal": "重训提案",
        "audit": "审核记录",
        "analysis": "分析记录",
        "scenario": "量价测算",
    }.get(r["kind"], "研究记录")
    if family:
        prefix = {
            "ridge": "电价预测模型",
            "controlled_optimization": "受控优化预测模型",
            "seasonal_naive_d2": "两日前同期基线",
            "seasonal_naive_d7": "七日前同期基线",
            "train_weekday_slot_median": "历史同期基线",
        }.get(family, "研究模型")
    if family:
        n = store.db.execute(
            "SELECT count(*) FROM ml_object WHERE kind='model' AND json_extract(payload_json,'$.algorithm')=? AND json_extract(payload_json,'$.task')=? AND rowid<=(SELECT rowid FROM ml_object WHERE object_id=?)",
            (family, payload["task"], oid),
        ).fetchone()[0]
        if family == "ridge" and payload["task"] != TASK:
            prefix = tasks.spec(payload["task"])["name"] + "模型"
        if family == "recent_observation":
            prefix = "近期已知观测基线"
        if family == "zero_spread":
            prefix = "零价差参考"
        if family == "controlled_optimization" and payload.get("selected_recipe", {}).get("kind") == "reference":
            prefix = "优化筛选后保留的参考方案"
    if family == "ridge" and payload.get("output_bounds"):
        prefix = tasks.spec(payload["task"])["name"] + "（出力约束修正）"
    label = (
        f"{prefix}（第{n}版）"
        if r["kind"] in {"model", "dataset", "source_revision"}
        else f"{prefix}（第{n}次）"
    )
    return dict(
        id=r["object_id"],
        display_name=label,
        kind=r["kind"],
        parent_id=r["parent_id"],
        source_hash=r["source_hash"],
        created_at=r["created_at"],
        payload=json.loads(r["payload_json"]),
        **state(store, oid),
    )


def objects(store, kind, limit=200):
    return [
        get_object(store, r[0])
        for r in store.db.execute(
            "SELECT object_id FROM ml_object WHERE kind=? ORDER BY rowid DESC LIMIT ?",
            (kind, limit),
        )
    ]


def splits():
    # Only generated integration fixtures can replace the frozen production contract.
    if os.environ.get("CECEP_ML_TEST_CONTRACT"):
        if os.environ.get("CECEP_ML_TEST_FIXTURE") != "1":
            raise ValueError("测试合同只能用于显式生成的测试数据")
        return json.loads(os.environ["CECEP_ML_TEST_CONTRACT"])
    return SPLITS


def features_for(days, day, slot):
    d = date.fromisoformat(day)

    def previous(n):
        return days.get((d - timedelta(days=n)).isoformat(), {})

    def price(n):
        return previous(n).get(slot, {}).get("rt_price")

    def values(n):
        return [
            p["rt_price"] for p in previous(n).values() if p["rt_price"] is not None
        ]

    d2, d7 = values(2), values(7)
    angles = [
        2 * np.pi * slot / 96,
        2 * np.pi * d.weekday() / 7,
        2 * np.pi * (d.month - 1) / 12,
    ]
    return [
        price(2),
        price(3),
        price(7),
        np.mean(d2) if d2 else None,
        min(d2) if d2 else None,
        max(d2) if d2 else None,
        np.mean(d7) if d7 else None,
        *[f(a) for a in angles for f in (np.sin, np.cos)],
    ]


def register_dataset(store, source_hash, task=TASK):
    meta, dates, _ = public_data.dataset()
    if meta["source_hash"] != source_hash:
        raise ValueError("数据版本变化，重新核对源文件")
    from .data_flow import archive_current

    source_revision = archive_current(store, source_hash)
    contract = dict(
        policy=tasks.policy(task, POLICY),
        splits=splits(),
        source_hash=source_hash,
        source_rows=meta["row_count"],
        source_commit=meta["source_commit"],
        source_file=meta["source_file"],
        date_start=dates[0],
        date_end=dates[-1],
        fixture=os.environ.get("CECEP_ML_TEST_FIXTURE") == "1",
    )
    oid = "dataset_" + digest(contract)[:24]
    if not store.db.execute(
        "SELECT 1 FROM ml_object WHERE object_id=?", (oid,)
    ).fetchone():
        add_object(
            store,
            "dataset",
            contract,
            source_hash,
            parent=source_revision["id"],
            object_id=oid,
        )
        event(
            store, oid, "registered", note="冻结源文件和划分；行清单由训练准备阶段生成"
        )
        store.db.commit()
    return get_object(store, oid)


def build_arrays(ds, store=None):
    if store is None:
        meta, dates, days = public_data.dataset()
    else:
        from .data_flow import source_version

        meta, dates, days = source_version(store, ds["source_hash"])
    if meta["source_hash"] != ds["source_hash"]:
        raise ValueError("源文件已变更，旧数据集禁止训练；请登记新版本")
    task = ds["payload"]["policy"]["task"]
    result, manifest = {}, []
    for partition, (start, end) in ds["payload"]["splits"].items():
        xs, ys, row_days, slots = [], [], [], []
        current = date.fromisoformat(start)
        while current <= date.fromisoformat(end):
            day = current.isoformat()
            for slot in range(96):
                r = days.get(day, {}).get(slot)
                label = tasks.target(task, days.get(day, {}), slot)
                reason = (
                    "outside_target_grid"
                    if slot not in tasks.slots(task)
                    else (
                        "missing_record"
                        if r is None
                        else (
                            "missing_target"
                            if label is None
                            else (
                                "warmup"
                                if current
                                < date.fromisoformat(dates[0]) + timedelta(days=7)
                                else None
                            )
                        )
                    )
                )
                manifest.append(
                    dict(
                        split=partition,
                        date=day,
                        slot=slot,
                        source_line=r["source_line"] if r else None,
                        included=reason is None,
                        exclusion=reason,
                    )
                )
                if reason is None:
                    xs.append(
                        features_for(days, day, slot)
                        if task == TASK
                        else tasks.features(days, day, slot, task)
                    )
                    ys.append(label)
                    row_days.append(day)
                    slots.append(slot)
            current += timedelta(days=1)
        if not ys:
            raise ValueError(f"{partition} 没有可用标签，停止任务")
        result[partition] = dict(
            x=np.array(xs, dtype=np.float64),
            y=np.array(ys, dtype=np.float64),
            days=np.array(row_days),
            slots=np.array(slots, dtype=np.int64),
        )
    assigned = {r["date"] for r in manifest}
    for day in dates:
        if day not in assigned:
            for slot, record in days[day].items():
                manifest.append(
                    dict(
                        split="excluded",
                        date=day,
                        slot=slot,
                        source_line=record["source_line"],
                        included=False,
                        exclusion=(
                            "warmup"
                            if day < ds["payload"]["splits"]["train"][0]
                            else "boundary_or_outside_contract"
                        ),
                    )
                )
    return result, manifest


def transform(x, medians, mean, scale):
    missing = np.isnan(x)
    return np.concatenate(
        ((np.where(missing, medians, x) - mean) / scale, missing.astype(float)), axis=1
    )


def fit(train, alpha):
    x, y = train["x"], train["y"]
    med = np.array(
        [np.median(c[np.isfinite(c)]) if np.isfinite(c).any() else 0 for c in x.T]
    )
    filled = np.where(np.isnan(x), med, x)
    mean, scale = filled.mean(0), filled.std(0)
    scale[scale == 0] = 1
    z = transform(x, med, mean, scale)
    zmean, intercept = z.mean(0), y.mean()
    centered = z - zmean
    coefficients = np.linalg.solve(
        centered.T @ centered + alpha * np.eye(z.shape[1]), centered.T @ (y - intercept)
    )
    fallback = float(np.median(y))
    calendar = np.full((7, 96), fallback)
    wd = np.array([date.fromisoformat(d).weekday() for d in train["days"]])
    for weekday in range(7):
        for slot in range(96):
            mask = (wd == weekday) & (train["slots"] == slot)
            if mask.any():
                calendar[weekday, slot] = np.median(y[mask])
    return dict(
        medians=med,
        mean=mean,
        scale=scale,
        coefficients=coefficients,
        intercept=np.array(intercept - zmean @ coefficients),
        calendar=calendar,
        fallback=np.array(fallback),
        spike_threshold=np.array(np.quantile(y, 0.95)),
    )


def validate_model(a, feature_count=13):
    shapes = dict(
        medians=(feature_count,),
        mean=(feature_count,),
        scale=(feature_count,),
        coefficients=(2 * feature_count,),
        intercept=(),
        calendar=(7, 96),
        fallback=(),
        spike_threshold=(),
    )
    if (
        set(a) != set(shapes)
        or any(
            a[k].shape != v or not np.isfinite(a[k]).all() for k, v in shapes.items()
        )
        or (a["scale"] <= 0).any()
    ):
        raise ValueError("模型参数维度或数值无效")
    return a


def outputs(a, data, task=TASK):
    x = data["x"]
    wd = [date.fromisoformat(d).weekday() for d in data["days"]]
    result = dict(
        ridge=transform(x, a["medians"], a["mean"], a["scale"]) @ a["coefficients"]
        + a["intercept"],
        seasonal_naive_d2=np.where(np.isnan(x[:, 0]), a["fallback"], x[:, 0]),
        seasonal_naive_d7=np.where(np.isnan(x[:, 2]), a["fallback"], x[:, 2]),
        train_weekday_slot_median=a["calendar"][wd, data["slots"]],
    )
    if x.shape[1] > 13:
        result["recent_observation"] = np.where(
            np.isnan(x[:, 13]), a["fallback"], x[:, 13]
        )
    if tasks.spec(task)["target"] == "spread":
        result["zero_spread"] = np.zeros(len(x))
    return result


def scores(y, p):
    if not len(y):
        return dict(n=0, mae=None, rmse=None, mbe=None)
    error = p - y
    return dict(
        n=len(y),
        mae=float(np.mean(abs(error))),
        rmse=float(np.sqrt(np.mean(error**2))),
        mbe=float(np.mean(error)),
    )


def paired_ci(days, candidate_errors, baseline_errors):
    daily = np.array(
        [
            np.mean(candidate_errors[days == d]) - np.mean(baseline_errors[days == d])
            for d in np.unique(days)
        ]
    )
    n = len(daily)
    if n < 14:
        return dict(
            days=n,
            delta_mae=float(daily.mean()),
            lower95=None,
            upper95=None,
            conclusion="insufficient_days",
        )
    rng = np.random.default_rng(42)
    starts = rng.integers(0, n - 7 + 1, size=(2000, (n + 6) // 7))
    indices = (starts[:, :, None] + np.arange(7)).reshape(2000, -1)[:, :n]
    low, high = np.quantile(daily[indices].mean(1), [0.025, 0.975])
    return dict(
        days=n,
        delta_mae=float(daily.mean()),
        lower95=float(low),
        upper95=float(high),
        conclusion="improved" if high < 0 else "worse" if low > 0 else "inconclusive",
    )


def bounded_outputs(a, data, task, bounds=None):
    result = outputs(a, data, task)
    if bounds:
        if (
            not task.startswith("pv_")
            or bounds.get("kind") != "train_signed_power_floor_v1"
        ):
            raise ValueError("出力约束与任务不匹配")
        result["ridge"] = np.maximum(result["ridge"], bounds["lower"])
    return result


def evaluate(a, arrays, partitions=("tune", "promotion"), task=TASK, bounds=None):
    report = {}
    for part in partitions:
        data = arrays[part]
        y = data["y"]
        predictions = bounded_outputs(a, data, task, bounds)
        report[part] = dict(
            rows=len(y),
            days=len(np.unique(data["days"])),
            row_mask_hash=digest(
                list(zip(data["days"].tolist(), data["slots"].tolist()))
            ),
            scores={
                name: dict(
                    **scores(y, p),
                    negative=scores(y[y < 0], p[y < 0]),
                    spike=scores(
                        y[y >= a["spike_threshold"]], p[y >= a["spike_threshold"]]
                    ),
                )
                for name, p in predictions.items()
            },
            comparisons={
                name: paired_ci(
                    data["days"],
                    abs(predictions["ridge"] - y),
                    abs(predictions[name] - y),
                )
                for name in predictions
                if name != "ridge"
            },
            fallback_counts={
                "seasonal_naive_d2": int(np.isnan(data["x"][:, 0]).sum()),
                "seasonal_naive_d7": int(np.isnan(data["x"][:, 2]).sum()),
            },
        )
        if task != TASK:
            for name, predicted in predictions.items():
                report[part]["scores"][name]["positive_output"] = scores(
                    y[y > 0], predicted[y > 0]
                )
                if tasks.spec(task)["target"] == "spread":
                    classes = np.unique(np.sign(y))
                    recalls = [
                        (
                            float(np.mean(np.sign(predicted[y == 0]) == 0))
                            if c == 0
                            else float(
                                np.mean(np.sign(predicted[np.sign(y) == c]) == c)
                            )
                        )
                        for c in classes
                    ]
                    report[part]["scores"][name].update(
                        direction_accuracy=float(
                            np.mean(np.sign(predicted) == np.sign(y))
                        ),
                        balanced_direction_accuracy=float(np.mean(recalls)),
                    )
    return report


def job(store, jid):
    r = store.db.execute("SELECT * FROM ml_job WHERE job_id=?", (jid,)).fetchone()
    if not r:
        raise ValueError("训练任务不存在")
    n = store.db.execute(
        "SELECT count(*) FROM ml_job WHERE rowid<=(SELECT rowid FROM ml_job WHERE job_id=?)",
        (jid,),
    ).fetchone()[0]
    return dict(
        id=jid,
        display_name=f"训练任务（第{n}次）",
        dataset_id=r["dataset_id"],
        parent_job_id=r["parent_job_id"],
        config=json.loads(r["config_json"]),
        created_at=r["created_at"],
        **state(store, jid),
    )


def submit(store, dataset_id, alpha, key, parent=None, proposal_id=None):
    ds = get_object(store, dataset_id, "dataset")
    if alpha not in ds["payload"]["policy"]["alpha_choices"]:
        raise ValueError("正则参数不在预先冻结的候选集合")
    config = dict(
        alpha=alpha,
        policy_hash=digest(ds["payload"]["policy"]),
        proposal_id=proposal_id,
    )
    if ds["payload"]["policy"].get("engine"):
        config["engine"] = ds["payload"]["policy"]["engine"]
    if proposal_id:
        recipe = get_object(store, proposal_id, "proposal")["payload"].get(
            "output_recipe"
        )
        if recipe:
            config["output_recipe"] = recipe
    prior = store.db.execute(
        "SELECT job_id FROM ml_job WHERE idempotency_key=?", (key,)
    ).fetchone()
    if prior:
        result = job(store, prior[0])
        if (
            result["dataset_id"] != dataset_id
            or result["config"] != config
            or result["parent_job_id"] != parent
        ):
            raise ValueError("幂等键已绑定另一任务")
        return result
    if not ds["payload"]["fixture"] and os.environ.get("CECEP_ML_WORKER") != "1":
        raise ValueError("训练执行器未启用，不创建无人执行的任务")
    if parent and job(store, parent)["state"] not in TERMINAL:
        raise ValueError("父任务尚未结束")
    jid = "job_" + uuid4().hex
    store.db.execute(
        "INSERT INTO ml_job VALUES(?,?,?,?,?,?)",
        (jid, dataset_id, parent, key, encoded(config), now()),
    )
    event(store, jid, "queued", stage="等待唯一 CPU 执行器", completed_units=0)
    store.db.commit()
    return job(store, jid)


def execute(store, jid):
    started = time.monotonic()
    j = job(store, jid)
    ds = get_object(store, j["dataset_id"], "dataset")
    policy = ds["payload"]["policy"]
    if policy.get("engine"):
        if policy["engine"] == "controlled_candidate_v1":
            from .optimized_models import execute as candidate
            return candidate(store, jid, policy)
        from .optimization_bridge import execute as optimize

        return optimize(store, jid, policy)
    task = policy["task"]
    dim = len(policy["features"])

    def stage(name, **info):
        store.db.execute("BEGIN IMMEDIATE")
        if state(store, jid)["state"] == "cancel_requested":
            store.db.rollback()
            raise ValueError("训练已请求取消")
        event(store, jid, name, **info)
        store.db.commit()

    stage("preparing", stage="验证源文件与完整样本清单")
    arrays, manifest = build_arrays(ds, store)
    manifest_ref = atomic(
        f"jobs/{jid}/rows.jsonl",
        ("\n".join(encoded(r) for r in manifest) + "\n").encode(),
    )
    data_ref = write_npz(
        f"jobs/{jid}/data.npz",
        **{f"{p}_{k}": v for p, data in arrays.items() for k, v in data.items()},
    )
    counts = {
        p: dict(
            included=len(data["y"]),
            excluded=sum(r["split"] == p and not r["included"] for r in manifest),
            days=len(np.unique(data["days"])),
        )
        for p, data in arrays.items()
    }
    feature_hash = hashlib.sha256(
        b"".join(arrays[p]["x"].tobytes() for p in arrays)
    ).hexdigest()
    stage(
        "training",
        stage="训练集拟合缺失值、标准化与 Ridge 权重",
        counts=counts,
        manifest=manifest_ref,
    )
    a = validate_model(fit(arrays["train"], j["config"]["alpha"]), dim)
    ref = write_npz(f"models/{jid}/weights.npz", **a)
    loaded = validate_model(read_npz(ref), dim)
    probe = arrays["tune"]
    if not np.array_equal(outputs(a, probe)["ridge"], outputs(loaded, probe)["ridge"]):
        raise ValueError("模型重载推理不一致")
    stage(
        "evaluating",
        stage="按共同标签掩码评估；最终审计集封存",
        completed_units=counts["train"]["included"],
    )
    bounds = (
        dict(
            kind="train_signed_power_floor_v1",
            lower=float(np.quantile(arrays["train"]["y"], 0.001)),
            quantile=0.001,
        )
        if j["config"].get("output_recipe") == "train_signed_power_floor_v1"
        and task.startswith("pv_")
        else None
    )
    report = evaluate(loaded, arrays, task=task, bounds=bounds)
    evaluation_ref = atomic(f"jobs/{jid}/evaluation.json", encoded(report).encode())
    prediction_arrays = {}
    for partition in ("tune", "promotion"):
        data = arrays[partition]
        prediction_arrays.update(
            {
                f"{partition}_{k}": v
                for k, v in bounded_outputs(loaded, data, task, bounds).items()
            }
        )
        prediction_arrays.update(
            {f"{partition}_{k}": data[k] for k in ("y", "days", "slots")}
        )
    prediction_ref = write_npz(
        f"jobs/{jid}/evaluation_predictions.npz", **prediction_arrays
    )
    elapsed = time.monotonic() - started
    try:
        import resource

        rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    except ImportError:
        rss = None  # Windows fixture tests; real Linux jobs record kernel RSS.
    import subprocess

    # Git's caller-injected config can be malformed in test runners. Resolve the
    # repository identity using its own configuration, without changing it.
    git_env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_CONFIG_")}
    code_commit = subprocess.check_output(
        ["git", "rev-parse", "HEAD"],
        cwd=Path(__file__).resolve().parents[2],
        env=git_env,
        text=True,
    ).strip()
    common = dict(
        task=task,
        unit=policy["unit"],
        policy=policy,
        code_commit=code_commit,
        job_id=jid,
        dataset_id=ds["id"],
        weights=ref,
        arrays=data_ref,
        manifest=manifest_ref,
        counts=counts,
        feature_value_hash=feature_hash,
        report=report,
        evaluation=evaluation_ref,
        evaluation_predictions=prediction_ref,
        splits=ds["payload"]["splits"],
        measured_seconds=elapsed,
        peak_rss_kib=rss,
        artifact_load_verified=True,
        training_label_end=ds["payload"]["splits"]["train"][1],
        selection_end=ds["payload"]["splits"]["tune"][1],
        final_audit="sealed",
    )
    ids = []
    if bounds:
        common["output_bounds"] = bounds
    for algorithm in [
        "ridge",
        *BASELINES,
        *(["recent_observation"] if policy.get("intraday") else []),
        *(["zero_spread"] if tasks.spec(task)["target"] == "spread" else []),
    ]:
        oid = add_object(
            store,
            "model",
            dict(
                **common,
                algorithm=algorithm,
                trainable_parameters=2 * dim + 1 if algorithm == "ridge" else 0,
                fitted_statistics=(
                    "train-only imputer/scaler"
                    if algorithm == "ridge"
                    else (
                        "train weekday/slot median"
                        if algorithm == "train_weekday_slot_median"
                        else "train target median fallback"
                    )
                ),
                alpha=j["config"]["alpha"] if algorithm == "ridge" else None,
            ),
            ds["source_hash"],
            ds["id"],
        )
        event(store, oid, "evaluated", evidence=evaluation_ref)
        ids.append(oid)
    event(
        store,
        jid,
        "child_complete",
        models=ids,
        measured_seconds=elapsed,
        peak_rss_kib=rss,
        counts=counts,
        manifest=manifest_ref,
        feature_value_hash=feature_hash,
    )
    store.db.commit()
    return ids


def active(store, task=TASK):
    tasks.spec(task)
    return state(store, "release:" + task)


def guard_power_model(store, mid, actor, reason):
    original = get_object(store, mid, "model")
    p = original["payload"]
    if not p["task"].startswith("pv_") or p["algorithm"] != "ridge":
        raise ValueError("训练期出力约束只用于光伏线性模型")
    if p.get("output_bounds"):
        return original
    if job(store, p["job_id"])["state"] != "succeeded":
        raise ValueError("原训练作业尚无成功退出记录")
    all_arrays = read_npz(p["arrays"])
    arrays = {
        part: {k: all_arrays[part + "_" + k] for k in ("x", "y", "days", "slots")}
        for part in ("train", "tune", "promotion")
    }
    bounds = dict(
        kind="train_signed_power_floor_v1",
        lower=float(np.quantile(arrays["train"]["y"], 0.001)),
        quantile=0.001,
    )
    oid = "model_" + digest(dict(variant_of=mid, bounds=bounds))[:32]
    if store.db.execute("SELECT 1 FROM ml_object WHERE object_id=?", (oid,)).fetchone():
        return get_object(store, oid, "model")
    a = validate_model(read_npz(p["weights"]), len(p["policy"]["features"]))
    report = evaluate(a, arrays, task=p["task"], bounds=bounds)
    evaluation = atomic(
        f"models/output-variants/{oid}/evaluation.json", encoded(report).encode()
    )
    values = {}
    for part in ("tune", "promotion"):
        values.update(
            {
                part + "_" + k: v
                for k, v in bounded_outputs(a, arrays[part], p["task"], bounds).items()
            }
        )
        values.update({part + "_" + k: arrays[part][k] for k in ("y", "days", "slots")})
    predictions = write_npz(
        f"models/output-variants/{oid}/evaluation_predictions.npz", **values
    )
    payload = dict(
        p,
        output_bounds=bounds,
        variant_of=mid,
        variant_kind="prediction_constraint_not_weight_retraining",
        report=report,
        evaluation=evaluation,
        evaluation_predictions=predictions,
    )
    add_object(store, "model", payload, original["source_hash"], p["dataset_id"], oid)
    event(store, oid, "evaluated", actor=actor, reason=reason, weights_reused=True)
    store.db.commit()
    return get_object(store, oid, "model")


def prediction(store, model_id, day, validation=False, input_source_hash=None):
    m = get_object(store, model_id, "model")
    p = m["payload"]
    task = p["task"]
    grid = tasks.slots(task)
    if job(store, p["job_id"])["state"] != "succeeded":
        raise ValueError("所属训练任务尚无成功退出记录")
    d = date.fromisoformat(day)
    cutoff = d - timedelta(days=1)
    if validation and not p["splits"]["tune"][0] <= day <= p["splits"]["tune"][1]:
        raise ValueError("调参验证只能使用冻结的调参窗口；其他日期请选择研究推理")
    if day < p["splits"]["tune"][0] or (
        not validation
        and d <= date.fromisoformat(p["selection_end"]) + timedelta(days=1)
    ):
        raise ValueError("预测日必须晚于训练标签和选择边界；调参集仅能显式验证")
    final_state = state(store, tasks.seal(m))
    if p["splits"]["final_audit"][0] <= day <= p["splits"]["final_audit"][1] and not (
        final_state["state"] == "consumed"
        and final_state["detail"].get("model_id") == model_id
    ):
        raise ValueError("最终审计集仍封存，请先冻结唯一候选并执行一次审计")
    meta, _, days = public_data.dataset()
    if input_source_hash and input_source_hash != meta["source_hash"]:
        raise ValueError("指定输入源已变化，请刷新后重试")
    if meta["source_hash"] != m["source_hash"] and (
        validation or not input_source_hash
    ):
        raise ValueError(
            "源文件版本不匹配；新输入须显式绑定新源哈希，不能混入旧模型评估"
        )
    if day not in days:
        raise ValueError("所选交易日不在已有公开数据中")
    from .data_flow import archive_current

    archive_current(store, meta["source_hash"])
    a = validate_payload(p)
    x = np.array(
        [
            (
                features_for(days, day, s)
                if task == TASK
                else tasks.features(days, day, s, task)
            )
            for s in grid
        ],
        dtype=float,
    )
    if p["algorithm"] == "controlled_optimization":
        from .optimized_models import input_data
        x = input_data(days, day, task, p["policy"])["x"]
    data = dict(x=x, days=np.array([day] * len(grid)), slots=np.array(grid))
    if p["algorithm"] == "controlled_optimization":
        from .optimized_models import predict
        raw_pred = pred = predict(a, data)
    else:
        raw_pred = outputs(a, data, task)[p["algorithm"]]
        pred = bounded_outputs(a, data, task, p.get("output_bounds"))[p["algorithm"]]
    if not np.isfinite(pred).all():
        raise ValueError("推理出现非有限值")
    points = [
        dict(
            slot=s,
            predicted=float(pred[i]),
            raw_predicted=float(raw_pred[i]),
            actual=tasks.target(task, days[day], s),
            source_line=days[day].get(s, {}).get("source_line"),
            source_lines=[
                days[day].get(j, {}).get("source_line")
                for j in (range(s - 3, s + 1) if tasks.spec(task)["hourly"] else [s])
            ],
            issue_slot=s - 3 if tasks.spec(task)["hourly"] else s,
        )
        for i, s in enumerate(grid)
    ]
    paired = [r for r in points if r["actual"] is not None]
    payload = dict(
        model_id=model_id,
        task=task,
        unit=p["unit"],
        date=day,
        validation_only=validation,
        logical_cutoff=cutoff.isoformat() + "T09:00:00+08:00",
        latest_feature_day=(d - timedelta(days=2)).isoformat(),
        feature_value_hash=hashlib.sha256(x.tobytes()).hexdigest(),
        weights_hash=p["weights"]["sha256"],
        time_policy="historical_assumed",
        production_eligible=False,
        training_source_hash=m["source_hash"],
        input_source_hash=meta["source_hash"],
        points=points,
        scores=scores(
            np.array([r["actual"] for r in paired]),
            np.array([r["predicted"] for r in paired]),
        ),
    )
    if p["algorithm"] == "controlled_optimization":
        payload.update(independent_evidence=False, inference_kind="fixed_split_research_inference",
                       optimization_result_id=p["optimization_result_id"], information_budget=p["policy"]["information_budget"])
        if p["policy"].get("early_observations"):
            payload["latest_feature_day"]=cutoff.isoformat()
    if tasks.spec(task)["intraday"]:
        for point in points:
            issue = datetime.fromisoformat(day + "T00:00:00+08:00") + timedelta(
                minutes=point["issue_slot"] * 15
            )
            point.update(
                logical_cutoff=issue.isoformat(),
                latest_feature_at=(issue - timedelta(hours=1)).isoformat(),
            )
        payload.update(
            logical_cutoff=points[-1]["logical_cutoff"],
            latest_feature_day=day,
            inference_kind="rolling_historical_replay",
            cutoff_policy="per_point",
        )
    oid = add_object(store, "prediction", payload, meta["source_hash"], model_id)
    event(store, oid, "succeeded", count=len(grid))
    store.db.commit()
    return get_object(store, oid)


def feedback(store, prediction_id, slot, actor, reason, observation_id=None):
    pred = get_object(store, prediction_id, "prediction")
    if not 0 <= slot <= 95:
        raise ValueError("时段越界")
    point = next((p for p in pred["payload"]["points"] if p["slot"] == slot), None)
    if point is None:
        raise ValueError("此任务没有所选时段")
    observation = (
        get_object(store, observation_id, "observation_match")
        if observation_id
        else None
    )
    if observation and observation["parent_id"] != prediction_id:
        raise ValueError("实际值核对记录不属于该预测")
    if observation:
        point = next(p for p in observation["payload"]["points"] if p["slot"] == slot)
    payload = dict(
        prediction_id=prediction_id,
        model_id=pred["payload"]["model_id"],
        date=pred["payload"]["date"],
        slot=slot,
        point=point,
        actor=actor,
        reason=reason,
        actor_verification="intranet_declared",
        observation_id=observation_id,
        input_source_hash=pred["source_hash"],
        observation_source_hash=(
            observation["source_hash"] if observation else pred["source_hash"]
        ),
        training_eligible=False,
        note="复核意见不改写原始标签，不自动增加训练样本",
    )
    oid = add_object(
        store,
        "feedback",
        payload,
        observation["source_hash"] if observation else pred["source_hash"],
        prediction_id,
    )
    event(store, oid, "submitted", actor=actor, reason=reason)
    store.db.commit()
    return get_object(store, oid)


def confirm_feedback(store, oid, actor, reason):
    get_object(store, oid, "feedback")
    if state(store, oid)["state"] != "submitted":
        raise ValueError("只有已提交的反馈可确认")
    event(store, oid, "confirmed", actor=actor, reason=reason, training_eligible=False)
    store.db.commit()
    return get_object(store, oid)


def analyze_prediction(store, oid, question):
    from .model_settings import load_settings, select_evidence, ProviderError

    prediction = get_object(store, oid, "prediction")
    p = prediction["payload"]
    model_name = get_object(store, p["model_id"], "model")["display_name"]
    paired = [r for r in p["points"] if r["actual"] is not None]
    worst = sorted(
        paired, key=lambda r: abs(r["predicted"] - r["actual"]), reverse=True
    )[:3]
    facts = [
        f"{model_name}在{p['date']}的预测覆盖{len(p['points'])}个时段，单位为{tasks.spec(p['task'])['display_unit']}。",
        (
            f"原始标签有效 {p['scores']['n']} 条，MAE {p['scores']['mae']:.3f}，RMSE {p['scores']['rmse']:.3f}，MBE {p['scores']['mbe']:.3f}。"
            if p["scores"]["n"]
            else "本次96点推理尚无有效实际标签，不计算误差。"
        ),
        f"使用的历史输入最晚到{p['latest_feature_day']}，原始发布时间尚未核验，结果按历史研究口径解读。",
        (
            "调参验证结果不可称为独立测试或场站生产效果。"
            if p["validation_only"]
            else "结果属于省级公开市场研究，不代表浙江场站收益或生产精度。"
        ),
    ]
    facts += [
        f"{r['slot']//4:02d}:{r['slot']%4*15:02d}时段，预测 {r['predicted']:.3f}，实际 {r['actual']:.3f}。这些数据只能说明偏差，不能确认气象或设备根因。"
        for r in worst
    ]
    settings = load_settings()
    indices = list(range(len(facts)))
    failure = None
    mode = "deterministic_tools_only"
    if settings.ready:
        mode = "openai_compatible_evidence_summary"
        try:
            indices = select_evidence(settings, facts, question)
        except ProviderError as exc:
            failure = exc.code
    answer = (
        "外部摘要调用失败；真实推理与工具证据已保存，请重试。"
        if failure
        else "\n\n".join(facts[i] for i in indices)
    )
    aid = add_object(
        store,
        "analysis",
        dict(
            prediction_id=oid,
            model_id=p["model_id"],
            tool="registered_numpy_price_inference",
            facts=facts,
            question=question,
            llm_mode=mode,
            provider_error=failure,
            answer=answer,
        ),
        prediction["source_hash"],
        oid,
    )
    event(
        store,
        aid,
        "provider_failed" if failure else "succeeded",
        prediction_id=oid,
        llm_mode=mode,
    )
    store.db.commit()
    return get_object(store, aid)


def proposal(store, fid, alpha, actor, reason):
    fb = get_object(store, fid, "feedback")
    m = get_object(store, fb["payload"]["model_id"], "model")
    if fb["state"] != "confirmed":
        raise ValueError("反馈尚未人工确认")
    if fb["source_hash"] != m["source_hash"]:
        raise ValueError("输入源已变化，需新数据合同，不能沿用旧切片选参")
    if fb["payload"]["date"] > m["payload"]["selection_end"]:
        raise ValueError(
            "反馈已涉及提升或审计窗口，不能用同一窗口再次选参；需另行批准新的未来评估合同"
        )
    controlled = m["payload"]["algorithm"] == "controlled_optimization"
    if alpha not in POLICY["alpha_choices"] or (not controlled and alpha == m["payload"]["alpha"]):
        raise ValueError("选择一个不同的、合同允许的正则参数")
    if controlled and alpha != m["payload"]["alpha"]:
        raise ValueError("优化方案重训保持冻结配置，不用正则参数冒充树模型调参")
    oid = add_object(
        store,
        "proposal",
        dict(
            feedback_id=fid,
            model_id=m["id"],
            dataset_id=m["payload"]["dataset_id"],
            alpha=alpha,
            actor=actor,
            reason=reason,
            change="rerun_frozen_optimization" if controlled else "parameter_only",
            incorporates_labels=False,
            output_recipe=m["payload"].get("output_bounds", {}).get("kind"),
        ),
        fb["source_hash"],
        fid,
    )
    event(
        store,
        oid,
        "ready",
        note="复核触发冻结方案重跑；不追加标签或承诺提升" if controlled else "沿用原训练数据；复核调参集后重新训练，提升窗口保持隔离",
    )
    store.db.commit()
    return get_object(store, oid)


def train_proposal(store, oid, key):
    p = get_object(store, oid, "proposal")["payload"]
    model = get_object(store, p["model_id"], "model")
    return submit(
        store, p["dataset_id"], p["alpha"], key, model["payload"]["job_id"], oid
    )


def release(store, oid, action, actor, reason):
    # Serialize pointer checks and append together to prevent racing approvals.
    store.db.execute("BEGIN IMMEDIATE")
    try:
        m = get_object(store, oid, "model")
        p = m["payload"]
        if job(store, p["job_id"])["state"] != "succeeded":
            raise ValueError("所属训练任务尚无成功退出记录")
        task = p["task"]
        dim = len(p["policy"]["features"])
        current = active(store, task)
        previous = current["detail"].get("model_id")
        if action == "reject":
            if previous == oid:
                raise ValueError("当前主版本不可直接拒绝，请先回滚")
            event(store, oid, "rejected", actor=actor, reason=reason)
        elif action == "shadow":
            if m["state"] not in {"evaluated", "shadow"}:
                raise ValueError("该模型状态不允许进入影子验证")
            event(store, oid, "shadow", actor=actor, reason=reason)
        elif action == "rollback":
            if m["state"] == "rejected":
                raise ValueError("已拒绝版本不能作为回滚目标")
            if current["detail"].get("previous_model_id") != oid:
                raise ValueError("只能回滚到上一实际主版本")
            validate_payload(p)
            event(
                store,
                "release:" + task,
                "research_active",
                model_id=oid,
                previous_model_id=previous,
                action=action,
                actor=actor,
                reason=reason,
            )
            event(store, oid, "research_active", actor=actor, reason=reason)
            if previous:
                event(store, previous, "retired", actor=actor, reason=reason)
        else:
            if m["state"] not in {"evaluated", "shadow", "retired"}:
                raise ValueError("该模型状态不可审批")
            if previous == oid:
                raise ValueError("已经是当前主版本")
            validate_payload(p)
            if not previous:
                if p["algorithm"] != p["policy"].get(
                    "initial_baseline", "seasonal_naive_d2"
                ):
                    raise ValueError("首次仅可初始化合同中的参考基线，不宣称模型提升")
                gate = dict(initial_baseline=True)
            else:
                old = get_object(store, previous, "model")
                controlled = "controlled_optimization" in (p["algorithm"], old["payload"]["algorithm"])
                if old["source_hash"] != m["source_hash"] or (
                    not controlled and old["payload"]["dataset_id"] != p["dataset_id"]
                ) or (controlled and old["payload"]["splits"] != p["splits"]):
                    raise ValueError("版本数据或评估合同不匹配，不能直接审批")
                if controlled and p["policy"].get("information_budget", "d2_history") != old["payload"]["policy"].get("information_budget", "d2_history"):
                    raise ValueError("版本使用的信息条件不同，需同条件对照，不能直接审批")
                if not is_trained_algorithm(p["algorithm"]):
                    raise ValueError("升级候选必须是真实训练模型")
                arrays = read_npz(p["arrays"])
                data = {
                    k: arrays["promotion_" + k] for k in ("x", "y", "days", "slots")
                }
                old_arrays = read_npz(old["payload"]["arrays"])
                old_data = {k: old_arrays["promotion_"+k] for k in ("x", "y", "days", "slots")}
                if any(not np.array_equal(data[k], old_data[k]) for k in ("y", "days", "slots")):
                    raise ValueError("版本比较的日期、时段或标签不一致，不能直接审批")
                candidate = predict_payload(p, data)
                incumbent = predict_payload(old["payload"], old_data)
                gate = paired_ci(
                    data["days"], abs(candidate - data["y"]), abs(incumbent - data["y"])
                )
                if (
                    gate["upper95"] is None
                    or gate["upper95"] >= 0
                    or scores(data["y"], candidate)["rmse"]
                    > scores(data["y"], incumbent)["rmse"]
                ):
                    raise ValueError(
                        "候选未通过预先冻结的 MAE 置信区间与 RMSE 门槛；保留现任主版本"
                    )
                if p["algorithm"] == "controlled_optimization":
                    reference = p["policy"]["initial_baseline"]
                    report = p["report"]["promotion"]
                    ci = report["comparisons"][reference]
                    if ci["upper95"] is None or ci["upper95"] >= 0 or report["scores"][p["algorithm"]]["rmse"] > report["scores"][reference]["rmse"]:
                        raise ValueError("优化候选尚未同时胜过合同参考；保留影子研究状态")
                    gate["reference_comparison"] = ci
                    gate["independent_evidence"] = False
                    gate["notice"] = "已使用历史窗口的研究比较，未恢复独立检验资格"
            event(
                store,
                "release:" + task,
                "research_active",
                model_id=oid,
                previous_model_id=previous,
                action="activate",
                actor=actor,
                reason=reason,
                gate=gate,
            )
            event(store, oid, "research_active", actor=actor, reason=reason)
            if previous:
                event(store, previous, "retired", actor=actor, reason=reason)
        store.db.commit()
    except Exception:
        store.db.rollback()
        raise
    return active(store, task)


def final_audit(store, oid, actor, reason):
    m = get_object(store, oid, "model")
    p = m["payload"]
    if job(store, p["job_id"])["state"] != "succeeded":
        raise ValueError("所属任务尚无成功退出记录，不能启封最终审计")
    seal = tasks.seal(m)
    window_seal = "final_window:" + p["task"] + ":" + digest(p["splits"]["final_audit"])
    store.db.execute("BEGIN IMMEDIATE")
    try:
        if state(store, window_seal)["state"] != "registered":
            raise ValueError("同一最终审计窗口已经启封；源文件变更不能重置独立检验资格")
        for audit in objects(store, "audit", 10000):
            previous_model = get_object(store, audit["payload"]["model_id"], "model")
            if (
                previous_model["payload"]["task"] == p["task"]
                and previous_model["payload"]["splits"]["final_audit"]
                == p["splits"]["final_audit"]
            ):
                raise ValueError(
                    "同一最终审计窗口已经使用；更换源文件版本不能重新声称独立检验，需新的未来评估合同"
                )
        if state(store, seal)["state"] != "registered":
            raise ValueError("此源版本最终审计已开启，不允许换候选或重复独立检验")
        if p["algorithm"] != "ridge" or m["state"] not in {
            "evaluated",
            "shadow",
            "research_active",
            "retired",
        }:
            raise ValueError("只能冻结已评估的训练候选")
        # Commit the seal BEFORE reading labels. Failed audit remains consumed.
        event(
            store,
            seal,
            "frozen",
            model_id=oid,
            weights_hash=p["weights"]["sha256"],
            actor=actor,
            reason=reason,
        )
        event(
            store,
            window_seal,
            "frozen",
            model_id=oid,
            source_hash=m["source_hash"],
            actor=actor,
            reason=reason,
        )
        store.db.commit()
        arrays = read_npz(p["arrays"])
        data = {
            "final_audit": {
                k: arrays["final_audit_" + k] for k in ("x", "y", "days", "slots")
            }
        }
        a = validate_model(read_npz(p["weights"]), len(p["policy"]["features"]))
        report = evaluate(
            a, data, ("final_audit",), task=p["task"], bounds=p.get("output_bounds")
        )
        native = data["final_audit"]
        prediction_ref = write_npz(
            f"evaluations/{oid}/final_predictions.npz",
            **bounded_outputs(a, native, p["task"], p.get("output_bounds")),
            y=native["y"],
            days=native["days"],
            slots=native["slots"],
        )
        result = add_object(
            store,
            "audit",
            dict(
                model_id=oid,
                report=report,
                predictions=prediction_ref,
                actor=actor,
                reason=reason,
                interpretation="一次性最终检验；之后调参不得再称此窗口为独立测试",
            ),
            m["source_hash"],
            oid,
        )
        event(store, seal, "consumed", model_id=oid, audit_id=result)
        event(store, window_seal, "consumed", model_id=oid, audit_id=result)
        store.db.commit()
        return get_object(store, result)
    except Exception:
        store.db.rollback()
        raise


def overview(store):
    jobs = [
        job(store, r[0])
        for r in store.db.execute(
            "SELECT job_id FROM ml_job ORDER BY rowid DESC LIMIT 50"
        )
    ]
    worker = state(store, "worker")
    return dict(
        policy=POLICY,
        splits=splits(),
        active=active(store),
        worker=worker,
        monitor=state(store, "monitor"),
        datasets=objects(store, "dataset"),
        models=objects(store, "model"),
        jobs=jobs,
        feedback=objects(store, "feedback")[:50],
        proposals=objects(store, "proposal")[:50],
        audits=objects(store, "audit"),
        predictions=objects(store, "prediction", 10),
        events=[
            dict(subject_id=r[0], state=r[1], detail=json.loads(r[2]), created_at=r[3])
            for r in store.db.execute(
                "SELECT subject_id,state,payload_json,created_at FROM ml_event ORDER BY rowid DESC LIMIT 100"
            )
        ],
    )


def monitor_source(store):
    """Observe only the configured source; changes trigger quality and safe inference."""
    try:
        meta, dates, days = public_data.dataset()
        from .data_flow import archive_current, reconcile

        revision = archive_current(store, meta["source_hash"])
        matched_count = reconcile(store, meta["source_hash"])
        previous = state(store, "monitor")["detail"].get("source_hash")
        detail = dict(
            source_hash=meta["source_hash"],
            date_end=dates[-1],
            source_rows=meta["row_count"],
            changed=previous != meta["source_hash"],
            checked_at=now(),
            source_revision_id=revision["id"],
            observation_matches_added=matched_count,
        )
        if previous != meta["source_hash"]:
            latest = days[dates[-1]]
            missing = (
                sum(p["rt_price"] is None for p in latest.values()) + 96 - len(latest)
            )
            ds = register_dataset(store, meta["source_hash"])
            detail.update(
                dataset_id=ds["id"],
                latest_missing_targets=missing,
                quality="missing_target_warning" if missing else "complete_latest_day",
            )
            current = active(store)["detail"].get("model_id")
            if current:
                try:
                    inference = prediction(
                        store, current, dates[-1], False, meta["source_hash"]
                    )
                    analysis = analyze_prediction(
                        store,
                        inference["id"],
                        "核对新版本输入的预测偏差、缺失及研究边界",
                    )
                    detail.update(
                        prediction_id=inference["id"], analysis_id=analysis["id"]
                    )
                except ValueError as exc:
                    detail["inference_blocked"] = str(exc)
            else:
                detail["inference_blocked"] = (
                    "尚未批准研究主版本；仅检查数据，不自动训练"
                )
            detail["task_updates"] = {}
            for task in tasks.TASKS:
                if task == TASK:
                    continue
                selected = active(store, task)["detail"].get("model_id")
                if not selected:
                    continue
                try:
                    task_ds = register_dataset(store, meta["source_hash"], task)
                    inference = prediction(
                        store, selected, dates[-1], False, meta["source_hash"]
                    )
                    detail["task_updates"][task] = dict(
                        dataset_id=task_ds["id"],
                        prediction_id=inference["id"],
                        state="succeeded",
                    )
                except ValueError as exc:
                    detail["task_updates"][task] = dict(
                        state="blocked", reason=str(exc)
                    )
            add_object(store, "monitor_snapshot", detail, meta["source_hash"], ds["id"])
        event(store, "monitor", "checked", **detail)
        store.db.commit()
    except (OSError, ValueError) as exc:
        store.db.rollback()
        event(store, "monitor", "failed", error=str(exc), checked_at=now())
        store.db.commit()
