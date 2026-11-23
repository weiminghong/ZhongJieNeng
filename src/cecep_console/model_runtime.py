"""PIT inference adapters. Local artifacts are trusted operator supplied programs."""

from datetime import datetime, timedelta
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import time
from urllib.parse import urlsplit
from urllib.request import Request
from uuid import uuid4

from .model_settings import provider_open
from .rsi import model_states
from .serving import build_intervals, day_bounds, metrics, now, rows
from .storage import CATALOG, digest, encoded, instant

ROOT = Path(__file__).resolve().parents[2]
FEATURES = ["baseline_mw", "cloud_cover_pct", "air_temp_c"]
BUILTIN_URI = "builtin://pv_residual_ridge"


def builtin_model(source_mode="synthetic"):
    return dict(model_version_id="pv-residual-ridge-" + source_mode,
                model_name="pv_residual_ridge", version="1", task="day_ahead_power",
                artifact_uri=BUILTIN_URI, artifact_hash=None, parameters_json="{}",
                effective_status="candidate", status="candidate", source_mode=source_mode)


def adapter(uri):
    scheme = (uri or "").split("://", 1)[0]
    if uri == BUILTIN_URI:
        return "builtin"
    if scheme in {"local_joblib", "local_torch", "local_onnx", "http", "https"}:
        return "http" if scheme in {"http", "https"} else scheme
    raise ValueError("未配置可执行推理适配器")


def artifact_path(uri):
    raw = uri.split("://", 1)[1]
    if not raw or ".." in Path(raw).parts:
        raise ValueError("模型路径不允许目录穿越")
    path = Path(raw).expanduser()
    path = (path if path.is_absolute() else ROOT / path).resolve()
    allowed = [(ROOT / "runtime/models").resolve(), (ROOT / "models").resolve()]
    if not path.is_relative_to(ROOT.resolve()) or not any(path.is_relative_to(base) for base in allowed):
        raise ValueError("模型路径必须在项目 models 或 runtime/models 目录内")
    if not path.is_file():
        raise ValueError("模型权重文件不存在")
    return path


def endpoint(uri):
    parsed = urlsplit(uri)
    if (parsed.scheme not in {"http", "https"} or not parsed.hostname
            or parsed.username is not None or parsed.password is not None
            or parsed.query or parsed.fragment or any(c.isspace() for c in uri)):
        raise ValueError("推理 URL 不得包含凭据、查询参数或片段")
    try:
        parsed.port
    except ValueError:
        raise ValueError("推理 URL 端口无效") from None
    return uri


def remote(uri, payload=None):
    request = Request(endpoint(uri), data=encoded(payload).encode() if payload is not None else None,
                      headers={"Content-Type": "application/json"})
    try:
        with provider_open(request, timeout=15) as response:
            data = response.read(2_000_001)
            if len(data) > 2_000_000:
                raise ValueError("远程模型响应超过大小限制")
            return json.loads(data)
    except Exception as exc:
        # Never copy a remote response body, URL or authentication detail into logs.
        code = getattr(exc, "code", type(exc).__name__)
        raise ValueError(f"远程推理接口失败：{code}") from None


def readiness(model, probe=False):
    kind = adapter(model.get("artifact_uri"))
    if kind == "http":
        endpoint(model["artifact_uri"])
        if probe:
            remote(model["artifact_uri"])
        return kind, "地址校验通过；实际推理时验证输出协议"
    if kind != "builtin":
        path = artifact_path(model["artifact_uri"])
        expected = model.get("artifact_hash")
        if not expected or hashlib.sha256(path.read_bytes()).hexdigest() != expected:
            raise ValueError("模型 SHA-256 校验失败")
        dependency = {"local_joblib": "joblib", "local_torch": "torch", "local_onnx": "onnxruntime"}[kind]
        if importlib.util.find_spec(dependency) is None:
            raise ValueError("缺少模型运行依赖：" + dependency)
    return kind, "可执行；内置模型仅提供 PIT 现场拟合与物理基线" if kind == "builtin" else "文件、SHA-256 与依赖校验通过"


def list_runtime_models(store, cutoff=None):
    models = model_states(store, cutoff)
    ids = {m["model_version_id"] for m in models}
    models += [builtin_model(s) for s in ("synthetic", "production") if builtin_model(s)["model_version_id"] not in ids]
    result = []
    for m in models:
        try:
            kind, note = readiness(m)
            ready = True
        except ValueError as exc:
            kind, note, ready = "unavailable", str(exc), False
        result.append({**{k: m.get(k) for k in ("model_version_id", "model_name", "version", "task", "effective_status", "artifact_uri", "source_mode")},
                       "adapter_type": kind, "ready": ready, "readiness_note": note})
    return result


def register_runtime_model(store, payload):
    model = dict(payload)
    uri = model.get("artifact_uri", "")
    kind = adapter(uri)
    if kind == "builtin":
        raise ValueError("内置模型无需热注册")
    if model.get("task", "day_ahead_power") != "day_ahead_power":
        raise ValueError("当前运行时仅支持 day_ahead_power 的 96 点 MW 协议")
    if model.get("source_mode", "synthetic") not in {"synthetic", "production"}:
        raise ValueError("未知数据模式")
    model.setdefault("artifact_hash", None)
    readiness(model, probe=True)
    created, mid = now(), str(uuid4())
    params = model.get("params_json", {})
    if not isinstance(params, dict):
        raise ValueError("params_json 必须为对象")
    record = dict(model_version_id=mid, model_name=model["model_name"], version=model["version"],
                  task="day_ahead_power", artifact_uri=uri, artifact_hash=model["artifact_hash"],
                  feature_version="runtime-pit-v1", label_version="operator-supplied",
                  parameters_json=encoded(params), metrics_json="{}", status="candidate",
                  source_mode=model.get("source_mode", "synthetic"), created_at=created)
    with store.db:
        store.append("model_version", record)
        candidate, decision = str(uuid4()), str(uuid4())
        store.append("iteration_candidate", dict(candidate_id=candidate, base_model_version_id=mid,
                     candidate_model_version_id=mid, feedback_ids_json="[]", hypothesis="外部权重热注册，待人工验证", status="candidate", created_at=created))
        store.append("approval_decision", dict(decision_id=decision, candidate_id=candidate, reviewer_id="runtime-registrar",
                     decision="register_candidate", reason="安全与存在性/连通探测通过，不代表精度验收", created_at=created))
        store.append("model_lifecycle_event", dict(lifecycle_event_id=str(uuid4()), model_version_id=mid,
                     from_status="candidate", to_status="candidate", decision_id=decision, operator_id="runtime-registrar",
                     reason="已登记推理适配器；尚未获准生产上线", created_at=created))
    return next(m for m in list_runtime_models(store) if m["model_version_id"] == mid)


def validate_overrides(overrides):
    overrides = dict(overrides or {})
    bounds = {"cloud_delta_pct": (-50, 50), "temp_delta_c": (-15, 15), "curtailment_cap_mw": (0, 1e6)}
    if set(overrides) - set(bounds):
        raise ValueError("未知场景扰动参数")
    for key, value in overrides.items():
        if value is None and key == "curtailment_cap_mw":
            continue
        if isinstance(value, bool) or not isinstance(value, (float, int)) or not math.isfinite(value) or not bounds[key][0] <= value <= bounds[key][1]:
            raise ValueError("场景扰动超出允许范围：" + key)
    return overrides


def run_model_inference(store, *, model_version_id=None, station_id, trading_date,
                        cutoff_at, source_mode, overrides=None, persist=False, registry_cutoff=None):
    import numpy as np

    started = time.perf_counter()
    cutoff = instant(cutoff_at)
    if source_mode not in {"synthetic", "production"}:
        raise ValueError("未知数据模式")
    override = validate_overrides(overrides)
    model = builtin_model(source_mode)
    if not model_version_id:
        preferred = next((m for m in list_runtime_models(store, registry_cutoff or cutoff)
                          if m["ready"] and m["effective_status"] == "production"
                          and m["source_mode"] == source_mode and m["task"] == "day_ahead_power"), None)
        model_version_id = preferred["model_version_id"] if preferred else None
    if model_version_id and model_version_id != model["model_version_id"]:
        model = next((m for m in model_states(store, registry_cutoff or cutoff) if m["model_version_id"] == model_version_id), None)
        if model is None:
            raise ValueError("模型在截止时点不可见")
    if model["source_mode"] != source_mode or model["task"] != "day_ahead_power":
        raise ValueError("模型任务或数据模式不匹配")
    if model["effective_status"] in {"archived", "rolled_back"}:
        raise ValueError("模型当前状态不允许推理")
    kind, _ = readiness(model)
    target = build_intervals(store, station_id, trading_date, cutoff, source_mode, registry_cutoff=cutoff)
    if any(r["physical_clear_sky_mw"] is None for r in target):
        raise ValueError("缺少 PIT 可见的场站容量或晴空物理基线")
    start, end = day_bounds(trading_date)
    configs = store.as_of("station_config_version", cutoff, filters={"station_id": station_id}, target=start, allow_synthetic=source_mode == "synthetic")
    configs = [c for c in configs if (c["availability_basis"] == "synthetic") == (source_mode == "synthetic")]
    if len(configs) != 1:
        raise ValueError("场站容量配置不唯一")
    capacity = configs[0]["capacity_ac_mw"]
    # Targets from this day never become training labels, including post mode.
    history = []
    if kind == "builtin":
        days = rows(store, "SELECT DISTINCT substr(interval_start,1,10) AS day FROM station_actual WHERE station_id=? AND available_at<=? AND interval_end<=? ORDER BY day DESC LIMIT 9", (station_id, cutoff, start))
        # UTC dates straddle local days; derive local dates before selecting a window.
        dates = sorted({(datetime.fromisoformat(d["day"]) + timedelta(hours=8)).date().isoformat() for d in days})
        dates = sorted(set(dates + [(datetime.fromisoformat(d) + timedelta(days=1)).date().isoformat() for d in dates]))
        for day in [d for d in dates if d < trading_date][-7:]:
            visible = build_intervals(store, station_id, day, cutoff, source_mode, registry_cutoff=cutoff)
            history.extend(r for r in visible if r["actual_mw"] is not None and r["physical_clear_sky_mw"] is not None)

    def features(r, perturb=False):
        cloud = r["cloud_cover_pct"]
        temp = r["air_temp_c"]
        if cloud is None or temp is None:
            raise ValueError("PIT 可见气象特征不完整，无法执行推理")
        cloud = min(100, max(0, cloud + (override.get("cloud_delta_pct", 0) if perturb else 0)))
        temp += override.get("temp_delta_c", 0) if perturb else 0
        return [r["physical_clear_sky_mw"], cloud, temp]

    target_features = [features(r, True) for r in target]
    train_features = [features(r) for r in history]

    def physical(x):
        return x[0] * max(0, 1 - 0.007 * x[1]) * max(0, 1 - 0.004 * (x[2] - 25))

    # Ridge on a daylight-scaled intercept; weather perturbations remain physically monotone.
    coefficient, sigma = 0.0, 0.0
    if kind == "builtin":
        x = np.asarray([r[0] / capacity for r in train_features])
        y = np.asarray([r["actual_mw"] - physical(f) for r, f in zip(history, train_features)])
        coefficient = float(np.dot(x, y) / (np.dot(x, x) + 1.0)) if len(x) else 0.0
        residuals = y - x * coefficient
        sigma = float(np.sqrt(np.mean(residuals ** 2))) if len(x) else 0.0
        values = [physical(f) + f[0] / capacity * coefficient for f in target_features]
    elif kind == "http":
        output = remote(model["artifact_uri"], {"station_id": station_id, "trading_date": trading_date,
                         "cutoff_at": cutoff, "source_mode": source_mode, "feature_names": FEATURES,
                         "features": target_features, "overrides": override})
        values = output.get("predictions") if isinstance(output, dict) else None
    else:
        path = artifact_path(model["artifact_uri"])
        matrix = np.asarray(target_features, dtype=np.float32)
        try:
            if kind == "local_joblib":
                import joblib
                estimator = joblib.load(path)
                values = estimator.predict(matrix)
            elif kind == "local_torch":
                import torch
                estimator = torch.jit.load(str(path), map_location="cpu").eval()
                with torch.inference_mode():
                    values = estimator(torch.tensor(matrix)).detach().cpu().numpy()
            else:
                import onnxruntime as ort
                session = ort.InferenceSession(str(path), providers=["CPUExecutionProvider"])
                values = session.run(None, {session.get_inputs()[0].name: matrix})[0]
        except Exception as exc:
            raise ValueError("本地模型执行失败：" + type(exc).__name__) from None
    try:
        array = np.asarray(values, dtype=float)
        if array.shape not in {(96,), (96, 1)} or not np.isfinite(array).all():
            raise ValueError()
        values = array.reshape(96).tolist()
    except (ValueError, TypeError):
        raise ValueError("模型输出必须为 96 个有限 MW 数值") from None
    points = []
    for r, value in zip(target, values):
        value = min(capacity, max(0.0, value))
        if override.get("curtailment_cap_mw") is not None:
            value = min(value, override["curtailment_cap_mw"])
        value = round(value, 6)
        points.append(dict(interval_start=r["interval_start"], interval_end=r["interval_end"],
                           predicted_mw=round(value, 6), baseline_mw=r["physical_clear_sky_mw"],
                           online_mw=r["da_forecast_mw"], actual_mw=r["actual_mw"],
                           delta_vs_baseline_mw=round(value-r["physical_clear_sky_mw"], 6),
                           lower_mw=max(0, value-1.645*sigma) if history else None,
                           upper_mw=min(capacity, value+1.645*sigma) if history else None))
    scored = metrics([p["actual_mw"] for p in points], [p["predicted_mw"] for p in points])
    baseline = metrics([p["actual_mw"] for p in points], [p["baseline_mw"] for p in points])
    online = metrics([p["actual_mw"] for p in points], [p["online_mw"] for p in points])
    common = [p for p in points if p["actual_mw"] is not None and p["online_mw"] is not None]
    common_runtime = metrics([p["actual_mw"] for p in common], [p["predicted_mw"] for p in common])
    scored.update(baseline_mae=baseline["mae"], online_mae=online["mae"],
                  online_comparison={"runtime_mae": common_runtime["mae"], "online_mae": online["mae"], "sample_count": len(common)},
                  mae_improvement_mw=baseline["mae"]-scored["mae"] if baseline["mae"] is not None else None)
    feature_payload = dict(features=target_features, history=[dict(features=f, actual_mw=r["actual_mw"], interval_start=r["interval_start"]) for r, f in zip(history, train_features)],
                           cutoff_at=cutoff, source_mode=source_mode, station_id=station_id, trading_date=trading_date,
                           model_version_id=model["model_version_id"], artifact_hash=model.get("artifact_hash"), overrides=override)
    result = dict(model_version_id=model["model_version_id"], model_name=model["model_name"], version=model["version"],
                  source_mode=source_mode, station_id=station_id, trading_date=trading_date, cutoff_at=cutoff,
                  trained_scope=("pit_synthetic_demo" if source_mode == "synthetic" else "pit_production") if history else "physical_only_no_pit_pairs" if kind == "builtin" else "external_artifact_unverified_training",
                  training_pair_count=len(history), evaluation_basis="目标日可见实测配对；历史日前样本拟合，不代表生产精度验证",
                  interval_note="历史拟合残差 1.645σ 区间，未经覆盖率校准" if history else "无历史残差区间",
                  points=points, metrics=scored, feature_hash=digest(feature_payload), overrides=override, persisted_run_id=None)
    if persist:
        created = max(now(), cutoff)
        with store.db:
            if kind == "builtin" and not store.db.execute("SELECT 1 FROM model_version WHERE model_version_id=?", (model["model_version_id"],)).fetchone():
                store.append("model_version", {**{k: model[k] for k in ("model_version_id", "model_name", "version", "task", "artifact_uri", "source_mode", "status", "parameters_json")},
                             "feature_version": "runtime-pit-v1", "label_version": "pit-history", "metrics_json": "{}", "created_at": created})
            sid, rid = str(uuid4()), str(uuid4())
            store.append("feature_snapshot", dict(snapshot_id=sid, task="day_ahead_power", station_id=station_id,
                         target_start=start, target_end=end, cutoff_at=cutoff, created_at=created, feature_version="runtime-pit-v1",
                         source_mode=source_mode, payload_json=encoded(feature_payload), content_hash=digest(feature_payload)))
            refs = {(ref["table"], ref["record_id"]) for r in target+history for ref in json.loads(r["lineage_refs_json"])
                    if ref["table"] in {"weather_forecast", "weather_observation"} or (ref["table"] == "station_actual" and r in history)}
            refs.add(("station_config_version", configs[0]["config_version_id"]))
            for table, pk in sorted(refs):
                original = dict(store.db.execute(f'SELECT * FROM {table} WHERE {CATALOG[table]["pk"]}=?', (pk,)).fetchone())
                store.append("feature_input", dict(input_id=str(uuid4()), snapshot_id=sid, table_name=table, record_id=pk,
                             available_at=original["available_at"], payload_json=encoded(original), record_hash=digest(original)))
            store.append("prediction_run", dict(run_id=rid, model_version_id=model["model_version_id"], snapshot_id=sid,
                         task="day_ahead_power", station_id=station_id, cutoff_at=cutoff, issued_at=created, available_at=created,
                         target_start=start, target_end=end, status="complete", source_mode=source_mode, created_at=created))
            for p in points:
                store.append("prediction_value", dict(prediction_id=str(uuid4()), run_id=rid, target_start=p["interval_start"], target_end=p["interval_end"],
                             value=p["predicted_mw"], lower_value=p["lower_mw"], upper_value=p["upper_mw"], unit="MW", quality_flag="runtime_scenario" if override else "runtime"))
            from .serving import refresh_serving_tables
            refresh_serving_tables(store, station_id)
            result["persisted_run_id"] = rid
    result["latency_ms"] = round((time.perf_counter()-started)*1000, 3)
    return result
