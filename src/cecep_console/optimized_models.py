"""Fixed-split candidates from frozen optimization protocols, never fold imports.

Training runs in the existing isolated server environment. Serving reads only
checksummed numeric NPZ trees, without importing sklearn or loading pickle.
"""

from datetime import date, timedelta
import hashlib
import json
import os
from pathlib import Path
import runpy
import sys
import time

import numpy as np

from . import task_catalog as tc

ALGORITHM = "controlled_optimization"
ENGINE = "controlled_candidate_v1"
OWN_LAGS = (4, 5, 6, 10, 14, 21, 28)
FIELDS = ("pv_actual_mw", "load_actual_mw", "wind_actual_mw", "rt_price", "da_price")


def feature_names(task, early=False):
    base = list(tc.BASE_FEATURES + (tc.INTRADAY_FEATURES if tc.spec(task)["intraday"] else []))
    rich = base + [f"own_lag_{n}d" for n in OWN_LAGS] + [
        "own_median_d2_d7", "own_mean_d2_d7", "own_d2_minus_d3", "own_d2_minus_d7",
        "own_d2_relative_peak", "slot_fraction", "doy_sin", "doy_cos",
        "slot_sin_doy_sin", "slot_cos_doy_cos",
    ] + [f"{field}_lag_{n}d" for n in (2, 7) for field in FIELDS] + [f"{field}_daily_mean_d2" for field in FIELDS]
    if early:
        rich += [f"early_d1_{field}_{stat}" for field in (*FIELDS, "own_target") for stat in ("mean", "last", "min", "max", "std", "change")]
    return rich


def features(days, day, slot, task, early=False):
    """Frozen history and delayed intraday observations; no scoring label required."""
    d = date.fromisoformat(day)
    grid = tc.slots(task)

    def prior(n):
        return days.get((d - timedelta(days=n)).isoformat(), {})

    def value(rows, s, field="own_target"):
        v = tc.target(task, rows, s) if field == "own_target" else (
            tc.hour_value(rows, s, field) if tc.spec(task)["hourly"] or field == "da_price" else rows.get(s, {}).get(field)
        )
        return np.nan if v is None else float(v)

    def valid(rows, field="own_target", positions=None):
        a = np.array([value(rows, s, field) for s in (grid if positions is None else positions)])
        return a[np.isfinite(a)]

    base = tc.features(days, day, slot, task)
    earlier = np.array([value(prior(n), slot) for n in range(2, 8)])
    earlier = earlier[np.isfinite(earlier)]
    doy = 2 * np.pi * (d.timetuple().tm_yday - 1) / 365.25
    angle = 2 * np.pi * slot / 96
    two, three, seven = (value(prior(n), slot) for n in (2, 3, 7))
    rich = base + [value(prior(n), slot) for n in OWN_LAGS] + [
        float(np.median(earlier)) if len(earlier) else np.nan,
        float(earlier.mean()) if len(earlier) else np.nan, two-three, two-seven,
        two/max(base[5], 1) if np.isfinite(base[5]) else np.nan,
        slot/95, np.sin(doy), np.cos(doy), np.sin(angle)*np.sin(doy), np.cos(angle)*np.cos(doy),
    ] + [value(prior(n), slot, f) for n in (2, 7) for f in FIELDS]
    for field in FIELDS:
        a = valid(prior(2), field)
        rich.append(float(a.mean()) if len(a) else np.nan)
    if early:
        for field in (*FIELDS, "own_target"):
            a = valid(prior(1), field, [s for s in grid if s < 32])
            rich += [float(a.mean()), float(a[-1]), float(a.min()), float(a.max()), float(a.std()), float(a[-1]-a[0])] if len(a) else [np.nan]*6
    return rich


def input_data(days, day, task, policy):
    grid = tc.slots(task)
    return dict(x=np.array([features(days, day, s, task, policy.get("early_observations", False)) for s in grid]), days=np.array([day]*len(grid)), slots=np.array(grid))


def register_candidate(store, result_id):
    from . import learning as ml
    from .data_flow import archive_current
    from .optimization_bridge import validated_runner

    origin = ml.get_object(store, result_id, "optimization_result")
    p, task = origin["payload"], origin["payload"]["task"]
    c = p["contract"]
    if p.get("evaluation_family") == "direction" or c.get("conditional_upstream_required"):
        raise ValueError("方向与上游条件方案不能登记为金额回归模型")
    if task not in ("pv_day_ahead_reference", "prebid_spread_reference", "intraday_spread_reference"):
        raise ValueError("此优化任务尚未登记日常候选协议")
    runner = c["runner"]
    runner_config = dict(path=runner["path"], sha256=runner["runner_sha256"], environment=c["environment"]["name"])
    validated_runner(dict(engine="controlled_research_v2", optimization_runner=runner_config))
    revision = archive_current(store, origin["source_hash"])
    early = "-v3-" in c["contract_id"]
    policy = dict(tc.policy(task, ml.POLICY), engine=ENGINE, features=feature_names(task, early),
                  early_observations=early, optimization_runner=runner_config,
                  optimization_contract=c, optimization_result_id=result_id,
                  execution_scope="fixed_split_candidate", information_budget="d2_history_early_d1" if early else "d2_history",
                  independent_evidence=False, source_kind="public_reference", production_eligible=False)
    if early and not tc.spec(task)["intraday"]:
        policy["cutoff"] = "D-1 09:00 Asia/Shanghai; D-2 history and D-1 observations ending before 08:00 under assumed one-hour delay"
    contract = dict(policy=policy, splits=ml.splits(), source_hash=origin["source_hash"],
                    source_rows=revision["payload"]["metadata"]["row_count"],
                    fixture=os.environ.get("CECEP_ML_TEST_FIXTURE")=="1")
    oid = "dataset_" + ml.digest(contract)[:24]
    if not store.db.execute("SELECT 1 FROM ml_object WHERE object_id=?", (oid,)).fetchone():
        ml.add_object(store, "dataset", contract, origin["source_hash"], revision["id"], oid)
        ml.event(store, oid, "registered", note="既有切分重新训练；原折权重不导入，最终窗口不重开")
        store.db.commit()
    return ml.get_object(store, oid)


def numeric_package(package):
    """Export only numeric tree state. No arbitrary Python deserialization."""
    meta = {k: package[k] for k in ("recipe", "task", "fallback", "floor", "train_start", "train_end", "n", "blend")}
    meta["reference_fallback"] = package.get("reference_fallback", package["fallback"])
    out = dict(metadata=np.frombuffer(json.dumps(meta, allow_nan=False).encode(), dtype=np.uint8))
    if "linear" in package:
        out.update({"linear_"+k: v for k, v in package["linear"].items()})
    elif "tree" in package:
        tree = package["tree"]
        out["tree_bias"] = np.array(float(tree._baseline_prediction.ravel()[0]))
        offsets, nodes, total = [], [], 0
        for predictors in tree._predictors:
            if len(predictors) != 1:
                raise ValueError("只允许单输出回归树")
            n = predictors[0].nodes
            if np.any(n["is_categorical"]):
                raise ValueError("不支持未登记的分类特征树")
            offsets.append(total)
            a = np.column_stack([n[f] for f in ("value", "feature_idx", "num_threshold", "missing_go_to_left", "left", "right", "is_leaf")]).astype(np.float64)
            a[:, 4:6] += total
            nodes.append(a)
            total += len(n)
        out.update(tree_offsets=np.array(offsets, dtype=np.int64), tree_nodes=np.concatenate(nodes))
    return out


def validate(a, feature_count):
    from . import learning as ml
    try:
        meta = json.loads(a["metadata"].astype(np.uint8).tobytes())
        if not isinstance(meta["recipe"], dict) or not 0 <= meta["blend"] <= 1 or not np.isfinite(meta["fallback"]):
            raise ValueError()
        if "linear_coefficients" in a:
            cfg = meta["recipe"]
            dim = feature_count if cfg["kind"] == "ridge_rich" else (16 if tc.spec(meta["task"])["intraday"] else 13)
            ml.validate_model({k.removeprefix("linear_"): v for k,v in a.items() if k.startswith("linear_")}, dim)
        elif "tree_nodes" in a:
            n, offsets = a["tree_nodes"], a["tree_offsets"]
            if n.ndim != 2 or n.shape[1] != 7 or not np.isfinite(n[:,[0,1,3,4,5,6]]).all() or np.isnan(n[:,2]).any() or not np.isfinite(a["tree_bias"]).all() or not len(offsets) or np.any(offsets<0) or np.any(offsets>=len(n)):
                raise ValueError()
            internal = n[:,6] == 0
            if np.any(n[internal,1] < 0) or np.any(n[internal,1] >= feature_count) or np.any(n[internal,4:6] <= np.flatnonzero(internal)[:,None]) or np.any(n[internal,4:6] >= len(n)):
                raise ValueError()
        elif meta["recipe"]["kind"] != "reference":
            raise ValueError()
    except (KeyError, TypeError, IndexError, json.JSONDecodeError, ValueError):
        raise ValueError("优化模型数值权重或结构无效") from None
    return a


def predict(a, data):
    from . import learning as ml
    meta = json.loads(a["metadata"].astype(np.uint8).tobytes())
    x, cfg, task = data["x"], meta["recipe"], meta["task"]
    reference = np.where(np.isfinite(x[:,0]), x[:,0], meta["reference_fallback"]) if task.startswith("pv_") else np.zeros(len(x))
    if cfg["kind"] == "reference":
        return reference
    if "linear_coefficients" in a:
        aa = {k.removeprefix("linear_"): v for k,v in a.items() if k.startswith("linear_")}
        xx = x if cfg["kind"] == "ridge_rich" else x[:,:len(aa["medians"])]
        y = ml.transform(xx, aa["medians"], aa["mean"], aa["scale"]) @ aa["coefficients"] + aa["intercept"]
    else:
        y = np.full(len(x), float(a["tree_bias"]))
        nodes = a["tree_nodes"]
        for offset in a["tree_offsets"]:
            at = np.full(len(x), int(offset), dtype=np.int64)
            for _ in range(len(nodes)):
                active = nodes[at,6] == 0
                if not active.any():
                    break
                rows = np.flatnonzero(active)
                n = nodes[at[active]]
                v = x[rows, n[:,1].astype(int)]
                left = np.where(np.isnan(v), n[:,3] != 0, v <= n[:,2])
                at[active] = np.where(left, n[:,4], n[:,5]).astype(np.int64)
            else:
                raise ValueError("优化树遍历无有效终点")
            y += nodes[at,0]
        if cfg.get("residual"):
            anchor = np.zeros(len(x)) if task == "prebid_spread_reference" else np.where(np.isfinite(x[:,13 if tc.spec(task)["intraday"] else 0]), x[:,13 if tc.spec(task)["intraday"] else 0], meta["fallback"])
            scale = np.maximum(x[:,5],1) if task.startswith("pv_") else np.ones(len(x))
            y = anchor + y*scale
    if meta["floor"] is not None and cfg["kind"] != "ridge_raw":
        y = np.maximum(y, meta["floor"])
    y = meta["blend"]*y + (1-meta["blend"])*reference
    if not np.isfinite(y).all():
        raise ValueError("优化模型推理出现非有限值")
    return y


def fitted_parameter_count(a):
    if "linear_coefficients" in a:
        return int(a["linear_coefficients"].size + 1)
    if "tree_nodes" in a:
        return int(np.count_nonzero(a["tree_nodes"][:, 6]) + 1)
    return 0


def execute(store, jid, policy):
    from . import learning as ml
    from .optimization_bridge import validated_runner
    from .data_flow import source_version
    runner, environment, python = validated_runner(dict(policy, engine="controlled_research_v2"))
    if ml.job(store, jid)["config"]["policy_hash"] != ml.digest(policy):
        raise ValueError("候选训练协议已变化")
    if Path(sys.prefix).resolve() != environment:
        ml.event(store,jid,"preparing",stage="进入隔离候选训练环境")
        store.db.commit()
        env = dict(os.environ, PYTHONPATH=str(Path(__file__).resolve().parents[1]))
        store.close()
        os.execve(str(python), [str(python),"-m","cecep_console.ml_worker","--job",jid],env)
    started = time.monotonic()
    j = ml.job(store,jid)
    ds = ml.get_object(store,j["dataset_id"],"dataset")
    task, split, contract = policy["task"], ds["payload"]["splits"], policy["optimization_contract"]
    module = runpy.run_path(str(runner),run_name="cecep_fixed_split_recipe")
    for name in ("numpy", "scipy", "sklearn"):
        actual = np.__version__ if name=="numpy" else module[name].__version__
        if actual != contract["environment"][name]:
            raise ValueError("候选训练环境版本与冻结协议不一致")
    # The frozen server feature builder reads the same configured source. Check
    # both archive and current metadata before any fit; never substitute a fold.
    meta, dates, days = source_version(store,ds["source_hash"])
    if module["feature_names"](task) != policy["features"]:
        raise ValueError("特征方案与冻结优化协议不一致")
    # Construct only the registered non-final partitions. Missing targets are
    # excluded from training, while input_data serves every grid point at inference.
    records = []
    warmup = date.fromisoformat(dates[0])+timedelta(days=28)
    for day in dates:
        if date.fromisoformat(day) < warmup or not any(start <= day <= end for key,(start,end) in split.items() if key!="final_audit"):
            continue
        for slot in tc.slots(task):
            y=tc.target(task,days[day],slot)
            if y is not None:
                records.append((day,slot,y))
    data=dict(days=np.array([r[0] for r in records]),slots=np.array([r[1] for r in records]),y=np.array([r[2] for r in records]),
              xb=np.array([tc.features(days,d,s,task) for d,s,_ in records]),
              xr=np.array([features(days,d,s,task,policy.get("early_observations",False)) for d,s,_ in records]))
    train = module["mask"](data,*split["train"])
    tune = np.flatnonzero(module["mask"](data,*split["tune"]))
    promo = np.flatnonzero(module["mask"](data,*split["promotion"]))
    if not train.any() or not len(tune) or not len(promo):
        raise ValueError("固定训练、调参或比较窗口没有完整标签")
    fallback = float(np.median(data["y"][train]))
    ref = module["base_reference"](data,tune,task,fallback)
    target = data["y"][tune]
    reference_score = ml.scores(target,ref)
    ml.event(store,jid,"training",stage="仅在既有训练集拟合，在调参集选择方案；最终窗口不读取")
    store.db.commit()
    selection = [dict(recipe="reference",blend=0,**ml.scores(target,ref),eligible=True)]
    packages = {}
    old = module["fit_recipe"](data,train,task,dict(kind="ridge_raw",name="old_ridge",alpha=j["config"]["alpha"]))
    oldscore = ml.scores(target,module["predict"](old,data,tune))
    for recipe in contract["recipes"]:
        if recipe.get("power_only") and not task.startswith("pv_") or task in recipe.get("exclude_tasks",[]):
            continue
        package = module["fit_recipe"](data,train,task,recipe)
        packages[recipe["name"]] = package
        pp = module["predict"](package,data,tune)
        for blend in contract["blend_values"]:
            score = ml.scores(target,blend*pp+(1-blend)*ref)
            eligible = score["rmse"] <= reference_score["rmse"]
            if "-v4-" in contract["contract_id"]:
                eligible = eligible and score["rmse"] <= oldscore["rmse"]
            selection.append(dict(recipe=recipe["name"],blend=blend,**score,eligible=eligible))
        if ml.state(store,jid)["state"] == "cancel_requested":
            raise ValueError("候选训练已取消")
    choice = min((v for v in selection if v["eligible"]),key=lambda v:(v["mae"],v["rmse"],v["recipe"]))
    package = packages[choice["recipe"]] if choice["recipe"] != "reference" else dict(recipe=dict(kind="reference",name="reference"),task=task,fallback=fallback,floor=None,train_start=split["train"][0],train_end=split["train"][1],n=int(train.sum()))
    package["blend"] = choice["blend"]
    package["reference_fallback"] = fallback
    a = numeric_package(package)
    ref_weights = ml.write_npz(f"models/{jid}/controlled.npz",**a)
    loaded = validate(ml.read_npz(ref_weights),len(policy["features"]))
    report, native, counts = {}, {}, {}
    for part in ("train","tune","promotion"):
        idx = np.flatnonzero(module["mask"](data,*split[part]))
        y = data["y"][idx]
        current = dict(x=data["xr"][idx],y=y,days=data["days"][idx],slots=data["slots"][idx])
        pred = predict(loaded,current)
        reference = module["base_reference"](data,idx,task,fallback)
        expected = reference if choice["recipe"] == "reference" else choice["blend"]*module["predict"](package,data,idx)+(1-choice["blend"])*reference
        if not np.allclose(pred,expected,rtol=1e-12,atol=1e-9):
            raise ValueError("优化权重导出后与原生模型推理不一致")
        counts[part] = dict(included=len(y),excluded=0,days=len(np.unique(current["days"])))
        native.update({f"{part}_{k}":v for k,v in current.items()})
        if part != "train":
            comparison = module["calendar_ci"](current["days"],pred,reference,y)
            report[part] = dict(rows=len(y),days=len(np.unique(current["days"])),row_mask_hash=ml.digest(list(zip(current["days"].tolist(),current["slots"].tolist()))),scores={ALGORITHM:ml.scores(y,pred),policy.get("initial_baseline","seasonal_naive_d2"):ml.scores(y,reference)},comparisons={policy.get("initial_baseline","seasonal_naive_d2"):comparison})
            native[f"{part}_{ALGORITHM}"] = pred
    manifest = []
    for part in ("train","tune","promotion"):
        start,end=split[part]
        current=date.fromisoformat(start)
        included={(str(d),int(s)) for d,s in zip(native[part+"_days"],native[part+"_slots"])}
        while current <= date.fromisoformat(end):
            day=current.isoformat()
            for slot in tc.slots(task):
                ok=(day,slot) in included
                manifest.append(dict(split=part,date=day,slot=slot,included=ok,source_line=days.get(day,{}).get(slot,{}).get("source_line"),exclusion=None if ok else "outside_grid_missing_label_or_warmup"))
            current+=timedelta(days=1)
        counts[part]["excluded"]=sum(r["split"]==part and not r["included"] for r in manifest)
    arrays=ml.write_npz(f"jobs/{jid}/data.npz",**native)
    manifest_ref=ml.atomic(f"jobs/{jid}/rows.jsonl",("\n".join(ml.encoded(r) for r in manifest)+"\n").encode())
    evidence=ml.atomic(f"jobs/{jid}/evaluation.json",ml.encoded(dict(report=report,choice=choice,selection=selection)).encode())
    payload=dict(algorithm=ALGORITHM,task=task,unit=policy["unit"],policy=policy,job_id=jid,dataset_id=ds["id"],weights=ref_weights,arrays=arrays,manifest=manifest_ref,counts=counts,report=report,evaluation=evidence,evaluation_predictions=arrays,splits=split,artifact_load_verified=True,training_label_end=split["train"][1],selection_end=split["tune"][1],final_audit="sealed",optimization_result_id=policy["optimization_result_id"],recipe_hash=ml.digest(dict(recipe=package["recipe"],blend=package["blend"])),selected_recipe=package["recipe"],selection=choice,alpha=j["config"]["alpha"],trainable_parameters=fitted_parameter_count(a),serialized_numeric_values=int(sum(v.size for k,v in a.items() if k!="metadata")),measured_seconds=time.monotonic()-started,execution_scope="fixed_split_candidate",information_budget=policy["information_budget"],independent_evidence=False,production_eligible=False,feature_value_hash=hashlib.sha256(data["xr"].tobytes()).hexdigest())
    payload.update(effective_training_rows=package["n"],effective_training_start=package["train_start"],effective_training_end=package["train_end"],
                   fitted_statistics="Frozen recipe selection on tune; weights and power floor fit on train only")
    if "tree_nodes" in a:
        payload["fitted_tree_nodes"]=len(a["tree_nodes"])
    oid=ml.add_object(store,"model",payload,ds["source_hash"],ds["id"])
    ml.event(store,oid,"evaluated",evidence=evidence,note="历史研究候选；已使用窗口不恢复独立资格")
    ml.event(store,jid,"child_complete",models=[oid],counts=counts,measured_seconds=payload["measured_seconds"],manifest=manifest_ref)
    store.db.commit()
    return [oid]
