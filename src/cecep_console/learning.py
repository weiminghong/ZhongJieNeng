"""Public regional price research: immutable lineage and real NumPy inference.

Historical availability is assumed, never certified. No serving-table inputs.
"""
from datetime import date, timedelta
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

TASK = "rt_price_day_ahead_reference"
SPLITS = {"train": ["2024-01-08", "2025-08-30"],
          "tune": ["2025-09-01", "2025-09-29"],
          "promotion": ["2025-10-01", "2025-11-29"],
          "final_audit": ["2025-12-01", "2026-01-14"]}
FEATURES = ["rt_lag_2d_same_slot", "rt_lag_3d_same_slot", "rt_lag_7d_same_slot",
            "rt_mean_d2", "rt_min_d2", "rt_max_d2", "rt_mean_d7", "slot_sin",
            "slot_cos", "weekday_sin", "weekday_cos", "month_sin", "month_cos"]
BASELINES = ["seasonal_naive_d2", "seasonal_naive_d7", "train_weekday_slot_median"]
TERMINAL = {"succeeded", "failed", "cancelled", "interrupted", "unknown_exit"}
POLICY = dict(contract="cecep-closed-loop-v1", task=TASK, unit="CNY/MWh",
              source_kind="public_reference", time_policy="historical_assumed",
              production_eligible=False, availability_timestamps_verified=False,
              features=FEATURES, cutoff="D-1 09:00 Asia/Shanghai; inputs through D-2",
              alpha_choices=[0.1, 1, 10, 100], baseline_missing="train target median",
              promotion_gate="paired 7-day block bootstrap upper95(delta MAE)<0 and RMSE<=incumbent",
              bootstrap=dict(block_days=7, replicates=2000, seed=42),
              monitor=dict(interval_seconds=30, expected_intervals=96, missing_target_warn_above=0),
              actor_verification="intranet_declared", threads=4, timeout_seconds=1800)


def root():
    p = Path(os.environ.get("CECEP_ML_ROOT", Path(__file__).resolve().parents[2] / "runtime/ml")).resolve()
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
    store.db.execute("INSERT INTO ml_event VALUES(?,?,?,?,?)",
                     (uuid4().hex, subject, state, encoded(payload), now()))


def state(store, subject):
    r = store.db.execute("SELECT state,payload_json,created_at FROM ml_event WHERE subject_id=? ORDER BY rowid DESC LIMIT 1", (subject,)).fetchone()
    return dict(state=r[0], detail=json.loads(r[1]), updated_at=r[2]) if r else dict(state="registered", detail={})


def add_object(store, kind, payload, source_hash, parent=None, object_id=None):
    oid = object_id or kind + "_" + uuid4().hex
    store.db.execute("INSERT INTO ml_object VALUES(?,?,?,?,?,?)", (oid, kind, parent, source_hash, encoded(payload), now()))
    return oid


def get_object(store, oid, kind=None):
    r = store.db.execute("SELECT * FROM ml_object WHERE object_id=?", (oid,)).fetchone()
    if not r or (kind and r["kind"] != kind):
        raise ValueError("指定对象不存在或类型不符")
    return dict(id=r["object_id"], kind=r["kind"], parent_id=r["parent_id"], source_hash=r["source_hash"],
                created_at=r["created_at"], payload=json.loads(r["payload_json"]), **state(store, oid))


def objects(store, kind, limit=200):
    return [get_object(store, r[0]) for r in store.db.execute("SELECT object_id FROM ml_object WHERE kind=? ORDER BY rowid DESC LIMIT ?", (kind, limit))]


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
        return days.get((d-timedelta(days=n)).isoformat(), {})
    def price(n):
        return previous(n).get(slot, {}).get("rt_price")
    def values(n):
        return [p["rt_price"] for p in previous(n).values() if p["rt_price"] is not None]
    d2, d7 = values(2), values(7)
    angles = [2*np.pi*slot/96, 2*np.pi*d.weekday()/7, 2*np.pi*(d.month-1)/12]
    return [price(2), price(3), price(7), np.mean(d2) if d2 else None,
            min(d2) if d2 else None, max(d2) if d2 else None, np.mean(d7) if d7 else None,
            *[f(a) for a in angles for f in (np.sin, np.cos)]]


def register_dataset(store, source_hash):
    meta, dates, _ = public_data.dataset()
    if meta["source_hash"] != source_hash:
        raise ValueError("数据版本变化，重新核对源文件")
    from .data_flow import archive_current
    source_revision = archive_current(store, source_hash)
    contract = dict(policy=POLICY, splits=splits(), source_hash=source_hash, source_rows=meta["row_count"],
                    source_commit=meta["source_commit"], source_file=meta["source_file"],
                    date_start=dates[0], date_end=dates[-1], fixture=os.environ.get("CECEP_ML_TEST_FIXTURE") == "1")
    oid = "dataset_" + digest(contract)[:24]
    if not store.db.execute("SELECT 1 FROM ml_object WHERE object_id=?", (oid,)).fetchone():
        add_object(store, "dataset", contract, source_hash, parent=source_revision["id"], object_id=oid)
        event(store, oid, "registered", note="冻结源文件和划分；行清单由训练准备阶段生成")
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
    result, manifest = {}, []
    for partition, (start, end) in ds["payload"]["splits"].items():
        xs, ys, row_days, slots = [], [], [], []
        current = date.fromisoformat(start)
        while current <= date.fromisoformat(end):
            day = current.isoformat()
            for slot in range(96):
                r = days.get(day, {}).get(slot)
                reason = "missing_record" if r is None else "missing_target" if r["rt_price"] is None else "warmup" if current < date.fromisoformat(dates[0])+timedelta(days=7) else None
                manifest.append(dict(split=partition, date=day, slot=slot, source_line=r["source_line"] if r else None,
                                     included=reason is None, exclusion=reason))
                if reason is None:
                    xs.append(features_for(days, day, slot)); ys.append(r["rt_price"])
                    row_days.append(day); slots.append(slot)
            current += timedelta(days=1)
        if not ys:
            raise ValueError(f"{partition} 没有可用标签，停止任务")
        result[partition] = dict(x=np.array(xs, dtype=np.float64), y=np.array(ys, dtype=np.float64),
                                 days=np.array(row_days), slots=np.array(slots, dtype=np.int64))
    assigned = {r["date"] for r in manifest}
    for day in dates:
        if day not in assigned:
            for slot, record in days[day].items():
                manifest.append(dict(split="excluded", date=day, slot=slot, source_line=record["source_line"], included=False,
                                     exclusion="warmup" if day < ds["payload"]["splits"]["train"][0] else "boundary_or_outside_contract"))
    return result, manifest


def transform(x, medians, mean, scale):
    missing = np.isnan(x)
    return np.concatenate(((np.where(missing, medians, x)-mean)/scale, missing.astype(float)), axis=1)


def fit(train, alpha):
    x, y = train["x"], train["y"]
    med = np.array([np.median(c[np.isfinite(c)]) if np.isfinite(c).any() else 0 for c in x.T])
    filled = np.where(np.isnan(x), med, x)
    mean, scale = filled.mean(0), filled.std(0)
    scale[scale == 0] = 1
    z = transform(x, med, mean, scale)
    zmean, intercept = z.mean(0), y.mean()
    centered = z-zmean
    coefficients = np.linalg.solve(centered.T@centered + alpha*np.eye(z.shape[1]), centered.T@(y-intercept))
    fallback = float(np.median(y))
    calendar = np.full((7, 96), fallback)
    wd = np.array([date.fromisoformat(d).weekday() for d in train["days"]])
    for weekday in range(7):
        for slot in range(96):
            mask = (wd == weekday) & (train["slots"] == slot)
            if mask.any():
                calendar[weekday, slot] = np.median(y[mask])
    return dict(medians=med, mean=mean, scale=scale, coefficients=coefficients,
                intercept=np.array(intercept-zmean@coefficients), calendar=calendar,
                fallback=np.array(fallback), spike_threshold=np.array(np.quantile(y, .95)))


def validate_model(a):
    shapes = dict(medians=(13,), mean=(13,), scale=(13,), coefficients=(26,), intercept=(), calendar=(7, 96), fallback=(), spike_threshold=())
    if set(a) != set(shapes) or any(a[k].shape != v or not np.isfinite(a[k]).all() for k, v in shapes.items()) or (a["scale"] <= 0).any():
        raise ValueError("模型参数维度或数值无效")
    return a


def outputs(a, data):
    x = data["x"]
    wd = [date.fromisoformat(d).weekday() for d in data["days"]]
    return dict(ridge=transform(x, a["medians"], a["mean"], a["scale"])@a["coefficients"]+a["intercept"],
                seasonal_naive_d2=np.where(np.isnan(x[:, 0]), a["fallback"], x[:, 0]),
                seasonal_naive_d7=np.where(np.isnan(x[:, 2]), a["fallback"], x[:, 2]),
                train_weekday_slot_median=a["calendar"][wd, data["slots"]])


def scores(y, p):
    if not len(y):
        return dict(n=0, mae=None, rmse=None, mbe=None)
    error = p-y
    return dict(n=len(y), mae=float(np.mean(abs(error))), rmse=float(np.sqrt(np.mean(error**2))), mbe=float(np.mean(error)))


def paired_ci(days, candidate_errors, baseline_errors):
    daily = np.array([np.mean(candidate_errors[days == d])-np.mean(baseline_errors[days == d]) for d in np.unique(days)])
    n = len(daily)
    if n < 14:
        return dict(days=n, delta_mae=float(daily.mean()), lower95=None, upper95=None, conclusion="insufficient_days")
    rng = np.random.default_rng(42)
    starts = rng.integers(0, n-7+1, size=(2000, (n+6)//7))
    indices = (starts[:, :, None]+np.arange(7)).reshape(2000, -1)[:, :n]
    low, high = np.quantile(daily[indices].mean(1), [.025, .975])
    return dict(days=n, delta_mae=float(daily.mean()), lower95=float(low), upper95=float(high),
                conclusion="improved" if high < 0 else "worse" if low > 0 else "inconclusive")


def evaluate(a, arrays, partitions=("tune", "promotion")):
    report = {}
    for part in partitions:
        data = arrays[part]; y = data["y"]; predictions = outputs(a, data)
        report[part] = dict(rows=len(y), days=len(np.unique(data["days"])),
                           row_mask_hash=digest(list(zip(data["days"].tolist(), data["slots"].tolist()))),
                           scores={name: dict(**scores(y, p), negative=scores(y[y < 0], p[y < 0]),
                                               spike=scores(y[y >= a["spike_threshold"]], p[y >= a["spike_threshold"]])) for name, p in predictions.items()},
                           comparisons={name: paired_ci(data["days"], abs(predictions["ridge"]-y), abs(predictions[name]-y)) for name in BASELINES},
                           fallback_counts={"seasonal_naive_d2": int(np.isnan(data["x"][:, 0]).sum()), "seasonal_naive_d7": int(np.isnan(data["x"][:, 2]).sum())})
    return report


def job(store, jid):
    r = store.db.execute("SELECT * FROM ml_job WHERE job_id=?", (jid,)).fetchone()
    if not r:
        raise ValueError("训练任务不存在")
    return dict(id=jid, dataset_id=r["dataset_id"], parent_job_id=r["parent_job_id"], config=json.loads(r["config_json"]), created_at=r["created_at"], **state(store, jid))


def submit(store, dataset_id, alpha, key, parent=None, proposal_id=None):
    ds = get_object(store, dataset_id, "dataset")
    if alpha not in POLICY["alpha_choices"]:
        raise ValueError("正则参数不在预先冻结的候选集合")
    config = dict(alpha=alpha, policy_hash=digest(POLICY), proposal_id=proposal_id)
    prior = store.db.execute("SELECT job_id FROM ml_job WHERE idempotency_key=?", (key,)).fetchone()
    if prior:
        result = job(store, prior[0])
        if result["dataset_id"] != dataset_id or result["config"] != config or result["parent_job_id"] != parent:
            raise ValueError("幂等键已绑定另一任务")
        return result
    if not ds["payload"]["fixture"] and os.environ.get("CECEP_ML_WORKER") != "1":
        raise ValueError("训练执行器未启用，不创建无人执行的任务")
    if parent and job(store, parent)["state"] not in TERMINAL:
        raise ValueError("父任务尚未结束")
    jid = "job_"+uuid4().hex
    store.db.execute("INSERT INTO ml_job VALUES(?,?,?,?,?,?)", (jid, dataset_id, parent, key, encoded(config), now()))
    event(store, jid, "queued", stage="等待唯一 CPU 执行器", completed_units=0)
    store.db.commit()
    return job(store, jid)


def execute(store, jid):
    started = time.monotonic(); j = job(store, jid)
    ds = get_object(store, j["dataset_id"], "dataset")
    def stage(name, **info):
        store.db.execute("BEGIN IMMEDIATE")
        if state(store, jid)["state"] == "cancel_requested":
            store.db.rollback()
            raise ValueError("训练已请求取消")
        event(store, jid, name, **info); store.db.commit()
    stage("preparing", stage="验证源文件与完整样本清单")
    arrays, manifest = build_arrays(ds, store)
    manifest_ref = atomic(f"jobs/{jid}/rows.jsonl", ("\n".join(encoded(r) for r in manifest)+"\n").encode())
    data_ref = write_npz(f"jobs/{jid}/data.npz", **{f"{p}_{k}": v for p, data in arrays.items() for k, v in data.items()})
    counts = {p: dict(included=len(data["y"]), excluded=sum(r["split"] == p and not r["included"] for r in manifest),
                      days=len(np.unique(data["days"]))) for p, data in arrays.items()}
    feature_hash = hashlib.sha256(b"".join(arrays[p]["x"].tobytes() for p in arrays)).hexdigest()
    stage("training", stage="训练集拟合缺失值、标准化与 Ridge 权重", counts=counts, manifest=manifest_ref)
    a = validate_model(fit(arrays["train"], j["config"]["alpha"]))
    ref = write_npz(f"models/{jid}/weights.npz", **a)
    loaded = validate_model(read_npz(ref))
    probe = arrays["tune"]
    if not np.array_equal(outputs(a, probe)["ridge"], outputs(loaded, probe)["ridge"]):
        raise ValueError("模型重载推理不一致")
    stage("evaluating", stage="按共同标签掩码评估；最终审计集封存", completed_units=counts["train"]["included"])
    report = evaluate(loaded, arrays)
    evaluation_ref = atomic(f"jobs/{jid}/evaluation.json", encoded(report).encode())
    prediction_arrays = {}
    for partition in ("tune", "promotion"):
        data = arrays[partition]
        prediction_arrays.update({f"{partition}_{k}": v for k, v in outputs(loaded, data).items()})
        prediction_arrays.update({f"{partition}_{k}": data[k] for k in ("y", "days", "slots")})
    prediction_ref = write_npz(f"jobs/{jid}/evaluation_predictions.npz", **prediction_arrays)
    elapsed = time.monotonic()-started
    try:
        import resource
        rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    except ImportError:
        rss = None  # Windows fixture tests; real Linux jobs record kernel RSS.
    import subprocess
    # Git's caller-injected config can be malformed in test runners. Resolve the
    # repository identity using its own configuration, without changing it.
    git_env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_CONFIG_")}
    code_commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=Path(__file__).resolve().parents[2], env=git_env, text=True).strip()
    common = dict(task=TASK, unit="CNY/MWh", policy=POLICY, code_commit=code_commit, job_id=jid, dataset_id=ds["id"],
                  weights=ref, arrays=data_ref, manifest=manifest_ref, counts=counts,
                  feature_value_hash=feature_hash, report=report, evaluation=evaluation_ref, evaluation_predictions=prediction_ref,
                  splits=ds["payload"]["splits"],
                  measured_seconds=elapsed, peak_rss_kib=rss, artifact_load_verified=True,
                  training_label_end=ds["payload"]["splits"]["train"][1],
                  selection_end=ds["payload"]["splits"]["tune"][1], final_audit="sealed")
    ids = []
    for algorithm in ["ridge", *BASELINES]:
        oid = add_object(store, "model", dict(**common, algorithm=algorithm,
                         trainable_parameters=27 if algorithm == "ridge" else 0,
                         fitted_statistics="train-only imputer/scaler" if algorithm == "ridge" else "train weekday/slot median" if algorithm == "train_weekday_slot_median" else "train target median fallback",
                         alpha=j["config"]["alpha"] if algorithm == "ridge" else None), ds["source_hash"], ds["id"])
        event(store, oid, "evaluated", evidence=evaluation_ref)
        ids.append(oid)
    event(store, jid, "child_complete", models=ids, measured_seconds=elapsed, peak_rss_kib=rss,
          counts=counts, manifest=manifest_ref, feature_value_hash=feature_hash)
    store.db.commit()
    return ids


def active(store):
    return state(store, "release:"+TASK)


def prediction(store, model_id, day, validation=False, input_source_hash=None):
    m = get_object(store, model_id, "model"); p = m["payload"]
    d = date.fromisoformat(day)
    cutoff = d-timedelta(days=1)
    if validation and not p["splits"]["tune"][0] <= day <= p["splits"]["tune"][1]:
        raise ValueError("调参验证只能使用冻结的调参窗口；其他日期请选择研究推理")
    if day < p["splits"]["tune"][0] or (not validation and d <= date.fromisoformat(p["selection_end"])+timedelta(days=1)):
        raise ValueError("预测日必须晚于训练标签和选择边界；调参集仅能显式验证")
    final_state = state(store, "final:"+m["source_hash"])
    if p["splits"]["final_audit"][0] <= day <= p["splits"]["final_audit"][1] and not (final_state["state"] == "consumed" and final_state["detail"].get("model_id") == model_id):
        raise ValueError("最终审计集仍封存，请先冻结唯一候选并执行一次审计")
    meta, _, days = public_data.dataset()
    if input_source_hash and input_source_hash != meta["source_hash"]:
        raise ValueError("指定输入源已变化，请刷新后重试")
    if meta["source_hash"] != m["source_hash"] and (validation or not input_source_hash):
        raise ValueError("源文件版本不匹配；新输入须显式绑定新源哈希，不能混入旧模型评估")
    if day not in days:
        raise ValueError("所选交易日不在已有公开数据中")
    from .data_flow import archive_current
    archive_current(store,meta["source_hash"])
    a = validate_model(read_npz(p["weights"]))
    x = np.array([features_for(days, day, s) for s in range(96)], dtype=float)
    data = dict(x=x, days=np.array([day]*96), slots=np.arange(96))
    pred = outputs(a, data)[p["algorithm"]]
    if not np.isfinite(pred).all():
        raise ValueError("推理出现非有限值")
    points = [dict(slot=s, predicted=float(pred[s]), actual=days[day].get(s, {}).get("rt_price"),
                   source_line=days[day].get(s, {}).get("source_line")) for s in range(96)]
    paired = [r for r in points if r["actual"] is not None]
    payload = dict(model_id=model_id, task=TASK, unit="CNY/MWh", date=day, validation_only=validation,
                   logical_cutoff=cutoff.isoformat()+"T09:00:00+08:00", latest_feature_day=(d-timedelta(days=2)).isoformat(),
                   feature_value_hash=hashlib.sha256(x.tobytes()).hexdigest(), weights_hash=p["weights"]["sha256"],
                   time_policy="historical_assumed", production_eligible=False, training_source_hash=m["source_hash"],
                   input_source_hash=meta["source_hash"], points=points,
                   scores=scores(np.array([r["actual"] for r in paired]), np.array([r["predicted"] for r in paired])))
    oid = add_object(store, "prediction", payload, meta["source_hash"], model_id)
    event(store, oid, "succeeded", count=96); store.db.commit()
    return get_object(store, oid)


def feedback(store, prediction_id, slot, actor, reason, observation_id=None):
    pred = get_object(store, prediction_id, "prediction")
    if not 0 <= slot <= 95:
        raise ValueError("时段越界")
    point = pred["payload"]["points"][slot]
    observation = get_object(store, observation_id, "observation_match") if observation_id else None
    if observation and observation["parent_id"] != prediction_id:
        raise ValueError("实际值核对记录不属于该预测")
    if observation:
        point = observation["payload"]["points"][slot]
    payload = dict(prediction_id=prediction_id, model_id=pred["payload"]["model_id"], date=pred["payload"]["date"],
                   slot=slot, point=point, actor=actor, reason=reason, actor_verification="intranet_declared",
                   observation_id=observation_id, input_source_hash=pred["source_hash"],
                   observation_source_hash=observation["source_hash"] if observation else pred["source_hash"],
                   training_eligible=False, note="人工意见不改写原始价格，不自动增加训练标签")
    oid = add_object(store, "feedback", payload, observation["source_hash"] if observation else pred["source_hash"], prediction_id)
    event(store, oid, "submitted", actor=actor, reason=reason); store.db.commit()
    return get_object(store, oid)


def confirm_feedback(store, oid, actor, reason):
    get_object(store, oid, "feedback")
    if state(store, oid)["state"] != "submitted":
        raise ValueError("只有已提交的反馈可确认")
    event(store, oid, "confirmed", actor=actor, reason=reason, training_eligible=False)
    store.db.commit(); return get_object(store, oid)


def analyze_prediction(store, oid, question):
    from .model_settings import load_settings, select_evidence, ProviderError
    prediction = get_object(store, oid, "prediction"); p = prediction["payload"]
    paired = [r for r in p["points"] if r["actual"] is not None]
    worst = sorted(paired, key=lambda r: abs(r["predicted"]-r["actual"]), reverse=True)[:3]
    facts = [f"本站真实权重推理：模型 {p['model_id']}，权重 SHA256 {p['weights_hash']}，交易日 {p['date']}，96点，单位元/MWh。",
             f"原始标签有效 {p['scores']['n']} 条，MAE {p['scores']['mae']:.3f}，RMSE {p['scores']['rmse']:.3f}，MBE {p['scores']['mbe']:.3f}。" if p['scores']['n'] else "本次96点推理尚无有效实际标签，不计算误差。",
             f"逻辑截止 {p['logical_cutoff']}，特征最晚 {p['latest_feature_day']}；时点口径 historical_assumed，历史到达时间未经核验。",
             "调参验证结果不可称为独立测试或场站生产效果。" if p["validation_only"] else "结果属于省级公开市场研究，不代表浙江场站收益或生产精度。"]
    facts += [f"偏差时段 slot={r['slot']}，源行 {r['source_line']}，预测 {r['predicted']:.3f}，实际 {r['actual']:.3f}。数据只能证明偏差，不能确认气象或设备根因。" for r in worst]
    settings = load_settings(); indices = list(range(len(facts))); failure = None
    mode = "deterministic_tools_only"
    if settings.ready:
        mode = "openai_compatible_evidence_summary"
        try:
            indices = select_evidence(settings, facts, question)
        except ProviderError as exc:
            failure = exc.code
    answer = "外部摘要调用失败；真实推理与工具证据已保存，请重试。" if failure else "\n\n".join(facts[i] for i in indices)
    aid = add_object(store, "analysis", dict(prediction_id=oid, model_id=p["model_id"], tool="registered_numpy_price_inference",
                     facts=facts, question=question, llm_mode=mode, provider_error=failure, answer=answer), prediction["source_hash"], oid)
    event(store, aid, "provider_failed" if failure else "succeeded", prediction_id=oid, llm_mode=mode)
    store.db.commit(); return get_object(store, aid)


def proposal(store, fid, alpha, actor, reason):
    fb = get_object(store, fid, "feedback")
    m = get_object(store, fb["payload"]["model_id"], "model")
    if fb["state"] != "confirmed":
        raise ValueError("反馈尚未人工确认")
    if fb["source_hash"] != m["source_hash"]:
        raise ValueError("输入源已变化，需新数据合同，不能沿用旧切片选参")
    if fb["payload"]["date"] > m["payload"]["selection_end"]:
        raise ValueError("反馈已涉及提升或审计窗口，不能用同一窗口再次选参；需另行批准新的未来评估合同")
    if alpha not in POLICY["alpha_choices"] or alpha == m["payload"]["alpha"]:
        raise ValueError("选择一个不同的、合同允许的正则参数")
    oid = add_object(store, "proposal", dict(feedback_id=fid, model_id=m["id"], dataset_id=m["payload"]["dataset_id"], alpha=alpha,
                     actor=actor, reason=reason, change="parameter_only", incorporates_labels=False), fb["source_hash"], fid)
    event(store, oid, "ready", note="沿用原训练数据；复核调参集后重新训练，提升窗口保持隔离")
    store.db.commit(); return get_object(store, oid)


def train_proposal(store, oid, key):
    p = get_object(store, oid, "proposal")["payload"]
    model = get_object(store, p["model_id"], "model")
    return submit(store, p["dataset_id"], p["alpha"], key, model["payload"]["job_id"], oid)


def release(store, oid, action, actor, reason):
    # Serialize pointer checks and append together to prevent racing approvals.
    store.db.execute("BEGIN IMMEDIATE")
    try:
        m = get_object(store, oid, "model"); p = m["payload"]
        if job(store, p["job_id"])["state"] != "succeeded":
            raise ValueError("所属训练任务尚无成功退出记录")
        current = active(store); previous = current["detail"].get("model_id")
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
            validate_model(read_npz(p["weights"]))
            event(store, "release:"+TASK, "research_active", model_id=oid, previous_model_id=previous, action=action, actor=actor, reason=reason)
            event(store, oid, "research_active", actor=actor, reason=reason)
            if previous:
                event(store, previous, "retired", actor=actor, reason=reason)
        else:
            if m["state"] not in {"evaluated", "shadow", "retired"}:
                raise ValueError("该模型状态不可审批")
            if previous == oid:
                raise ValueError("已经是当前主版本")
            validate_model(read_npz(p["weights"]))
            if not previous:
                if p["algorithm"] != "seasonal_naive_d2":
                    raise ValueError("首次仅可初始化 D-2 基线为研究主版本，不宣称模型提升")
                gate = dict(initial_baseline=True)
            else:
                old = get_object(store, previous, "model")
                if old["source_hash"] != m["source_hash"] or old["payload"]["dataset_id"] != p["dataset_id"]:
                    raise ValueError("版本数据或评估合同不匹配，不能直接审批")
                if p["algorithm"] != "ridge":
                    raise ValueError("升级候选必须是训练得到的 Ridge")
                arrays = read_npz(p["arrays"])
                data = {k: arrays["promotion_"+k] for k in ("x", "y", "days", "slots")}
                aa = validate_model(read_npz(p["weights"])); bb = validate_model(read_npz(old["payload"]["weights"]))
                candidate = outputs(aa, data)[p["algorithm"]]; incumbent = outputs(bb, data)[old["payload"]["algorithm"]]
                gate = paired_ci(data["days"], abs(candidate-data["y"]), abs(incumbent-data["y"]))
                if gate["upper95"] is None or gate["upper95"] >= 0 or scores(data["y"], candidate)["rmse"] > scores(data["y"], incumbent)["rmse"]:
                    raise ValueError("候选未通过预先冻结的 MAE 置信区间与 RMSE 门槛；保留现任主版本")
            event(store, "release:"+TASK, "research_active", model_id=oid, previous_model_id=previous, action="activate", actor=actor, reason=reason, gate=gate)
            event(store, oid, "research_active", actor=actor, reason=reason)
            if previous:
                event(store, previous, "retired", actor=actor, reason=reason)
        store.db.commit()
    except Exception:
        store.db.rollback(); raise
    return active(store)


def final_audit(store, oid, actor, reason):
    m = get_object(store, oid, "model"); p = m["payload"]
    if job(store, p["job_id"])["state"] != "succeeded":
        raise ValueError("所属任务尚无成功退出记录，不能启封最终审计")
    seal = "final:"+m["source_hash"]
    window_seal = "final_window:"+p["task"]+":"+digest(p["splits"]["final_audit"])
    store.db.execute("BEGIN IMMEDIATE")
    try:
        if state(store,window_seal)["state"]!="registered":
            raise ValueError("同一最终审计窗口已经启封；源文件变更不能重置独立检验资格")
        for audit in objects(store,"audit",10000):
            previous_model=get_object(store,audit["payload"]["model_id"],"model")
            if previous_model["payload"]["task"]==p["task"] and previous_model["payload"]["splits"]["final_audit"]==p["splits"]["final_audit"]:
                raise ValueError("同一最终审计窗口已经使用；更换源文件版本不能重新声称独立检验，需新的未来评估合同")
        if state(store, seal)["state"] != "registered":
            raise ValueError("此源版本最终审计已开启，不允许换候选或重复独立检验")
        if p["algorithm"] != "ridge" or m["state"] not in {"evaluated", "shadow", "research_active", "retired"}:
            raise ValueError("只能冻结已评估的训练候选")
        # Commit the seal BEFORE reading labels. Failed audit remains consumed.
        event(store, seal, "frozen", model_id=oid, weights_hash=p["weights"]["sha256"], actor=actor, reason=reason)
        event(store, window_seal, "frozen", model_id=oid, source_hash=m["source_hash"], actor=actor, reason=reason)
        store.db.commit()
        arrays = read_npz(p["arrays"])
        data = {"final_audit": {k: arrays["final_audit_"+k] for k in ("x", "y", "days", "slots")}}
        report = evaluate(validate_model(read_npz(p["weights"])), data, ("final_audit",))
        native = data["final_audit"]
        prediction_ref = write_npz(f"evaluations/{oid}/final_predictions.npz", **outputs(validate_model(read_npz(p["weights"])), native),
                                   y=native["y"], days=native["days"], slots=native["slots"])
        result = add_object(store, "audit", dict(model_id=oid, report=report, predictions=prediction_ref, actor=actor, reason=reason,
                            interpretation="一次性最终检验；之后调参不得再称此窗口为独立测试"), m["source_hash"], oid)
        event(store, seal, "consumed", model_id=oid, audit_id=result)
        event(store, window_seal, "consumed", model_id=oid, audit_id=result); store.db.commit()
        return get_object(store, result)
    except Exception:
        store.db.rollback(); raise


def overview(store):
    jobs = [job(store, r[0]) for r in store.db.execute("SELECT job_id FROM ml_job ORDER BY rowid DESC LIMIT 50")]
    worker = state(store, "worker")
    return dict(policy=POLICY, splits=splits(), active=active(store), worker=worker, monitor=state(store, "monitor"), datasets=objects(store, "dataset"),
                models=objects(store, "model"), jobs=jobs, feedback=objects(store, "feedback")[:50],
                proposals=objects(store, "proposal")[:50], audits=objects(store, "audit"),
                predictions=objects(store, "prediction", 10),
                events=[dict(subject_id=r[0], state=r[1], detail=json.loads(r[2]), created_at=r[3]) for r in store.db.execute("SELECT subject_id,state,payload_json,created_at FROM ml_event ORDER BY rowid DESC LIMIT 100")])


def monitor_source(store):
    """Observe only the configured source; changes trigger quality and safe inference."""
    try:
        meta, dates, days = public_data.dataset()
        from .data_flow import archive_current, reconcile
        revision = archive_current(store, meta["source_hash"])
        matched_count = reconcile(store, meta["source_hash"])
        previous = state(store, "monitor")["detail"].get("source_hash")
        detail = dict(source_hash=meta["source_hash"], date_end=dates[-1], source_rows=meta["row_count"],
                      changed=previous != meta["source_hash"], checked_at=now(), source_revision_id=revision["id"], observation_matches_added=matched_count)
        if previous != meta["source_hash"]:
            latest = days[dates[-1]]
            missing = sum(p["rt_price"] is None for p in latest.values())+96-len(latest)
            ds = register_dataset(store, meta["source_hash"])
            detail.update(dataset_id=ds["id"], latest_missing_targets=missing,
                          quality="missing_target_warning" if missing else "complete_latest_day")
            current = active(store)["detail"].get("model_id")
            if current:
                try:
                    inference = prediction(store, current, dates[-1], False, meta["source_hash"])
                    analysis = analyze_prediction(store, inference["id"], "核对新版本输入的预测偏差、缺失及研究边界")
                    detail.update(prediction_id=inference["id"], analysis_id=analysis["id"])
                except ValueError as exc:
                    detail["inference_blocked"] = str(exc)
            else:
                detail["inference_blocked"] = "尚未批准研究主版本；仅检查数据，不自动训练"
            add_object(store, "monitor_snapshot", detail, meta["source_hash"], ds["id"])
        event(store, "monitor", "checked", **detail)
        store.db.commit()
    except (OSError, ValueError) as exc:
        store.db.rollback(); event(store, "monitor", "failed", error=str(exc), checked_at=now()); store.db.commit()
