"""Read-only workbench views over existing source records and saved ML evidence.

These routes never train, unseal an audit, alter labels, or invent arrival times.
"""

import csv
from datetime import date, datetime, timedelta
from functools import lru_cache
import hashlib
import io
import json
from typing import Literal

import numpy as np
from fastapi import APIRouter, Depends, Query
from fastapi.responses import Response

from . import learning as ml, public_data
from . import data_flow
from .learning_api import store_dep
from .storage import Store, REGISTRY_TABLES

router = APIRouter(prefix="/api/v1/research", tags=["research-workbench-views"])


def source_display_name(store, source_hash):
    oid = data_flow.revision_id(source_hash)
    return (
        ml.get_object(store, oid)["display_name"]
        if store.db.execute(
            "SELECT 1 FROM ml_object WHERE object_id=?", (oid,)
        ).fetchone()
        else "当前历史数据"
    )


@router.get("/flow")
def flow(
    model_id: str | None = None,
    prediction_id: str | None = None,
    store: Store = Depends(store_dep),
):
    return data_flow.flow(store, model_id, prediction_id)


@router.get("/schema")
def schema(store: Store = Depends(store_dep)):
    roles = {
        "ml_source_registry": "原始数据版本",
        "ml_dataset_registry": "冻结训练数据集",
        "ml_model_registry": "模型与权重版本",
        "ml_prediction_registry": "预测记录与输入版本",
        "ml_observation_registry": "后续观测核对",
        "ml_feedback_registry": "人工反馈",
        "ml_retrain_registry": "重训提案",
        "ml_audit_registry": "最终审计",
    }
    tables = []
    for name in sorted(REGISTRY_TABLES):
        tables.append(
            dict(
                name=name,
                role=roles.get(name, roles.get(name.removesuffix("_v2"), "研究记录")),
                rows=store.db.execute(f"SELECT count(*) FROM {name}").fetchone()[0],
                columns=[
                    dict(r) for r in store.db.execute(f"PRAGMA table_info({name})")
                ],
                foreign_keys=[
                    dict(r)
                    for r in store.db.execute(f"PRAGMA foreign_key_list({name})")
                ],
                indexes=[
                    dict(r) for r in store.db.execute(f"PRAGMA index_list({name})")
                ],
            )
        )
    return dict(
        version=store.db.execute(
            "SELECT max(version) FROM schema_migration"
        ).fetchone()[0],
        tables=tables,
        foreign_key_errors=[
            tuple(r) for r in store.db.execute("PRAGMA foreign_key_check")
        ],
        storage_policy="结构化关联表由不可变记录自动生成；外键检查归属，JSON保留完整证据，大文件与权重按哈希留在服务器。",
    )


@router.get("/source-catalog")
def source_catalog(source_hash: str, store: Store = Depends(store_dep)):
    meta, dates, _ = data_flow.source_version(store, source_hash)
    metadata = dict(
        meta,
        display_name=source_display_name(store, source_hash),
        archived_version=meta.get("archived_version", False),
    )
    return dict(
        available=True,
        checked_at=ml.now(),
        metadata=metadata,
        dates=dates,
        default_date=dates[-1],
    )


@router.get("/source-series")
def source_series(
    source_hash: str,
    trading_date: date,
    cursor: int = Query(default=96, ge=0, le=96),
    store: Store = Depends(store_dep),
):
    meta, dates, days = data_flow.source_version(store, source_hash)
    metadata = dict(meta, archived_version=meta.get("archived_version", False))
    return public_data.series(
        trading_date.isoformat(),
        cursor,
        source_hash,
        source_dataset=(metadata, dates, days),
    )


def current(expected=None):
    result = public_data.dataset()
    if expected and result[0]["source_hash"] != expected:
        raise ValueError("源文件已变化，请刷新版本后重试")
    return result


@lru_cache(maxsize=2)
def quality(source_hash):
    meta, dates, days = current(source_hash)
    records = [r for day in days.values() for r in day.values()]
    fields = []
    for key, (column, unit) in public_data.FIELDS.items():
        values = [r[key] for r in records if r[key] is not None]
        missing = len(records) - len(values)
        fields.append(
            dict(
                key=key,
                column=column,
                unit=unit,
                valid=len(values),
                missing=missing,
                missing_percent=100 * missing / len(records),
                negative=sum(v < 0 for v in values),
                minimum=min(values) if values else None,
                maximum=max(values) if values else None,
            )
        )
    full_dates = (date.fromisoformat(dates[-1]) - date.fromisoformat(dates[0])).days + 1
    return dict(
        metadata=meta,
        fields=fields,
        expected_records=full_dates * 96,
        missing_intervals=full_dates * 96 - len(records),
        incomplete_days=sum(len(v) != 96 for v in days.values()),
        original_preview=[r["source_values"] for r in records[:12]],
        checked_at=ml.now(),
        delete_allowed=False,
        training_source="original CSV; no serving tables",
    )


@router.get("/data-quality")
def data_quality(source_hash: str | None = None):
    meta, _, _ = current(source_hash)
    return quality(meta["source_hash"])


def event_history(store, limit=40):
    records = store.db.execute(
        "SELECT subject_id,state,payload_json,created_at FROM ml_event WHERE subject_id NOT IN ('worker','monitor') ORDER BY rowid DESC LIMIT ?",
        (limit,),
    ).fetchall()
    result = []
    for r in records:
        exists = store.db.execute(
            "SELECT 1 FROM ml_object WHERE object_id=?", (r[0],)
        ).fetchone()
        known_job = store.db.execute(
            "SELECT 1 FROM ml_job WHERE job_id=?", (r[0],)
        ).fetchone()
        label = (
            ml.get_object(store, r[0])["display_name"]
            if exists
            else ml.job(store, r[0])["display_name"] if known_job else "业务操作"
        )
        result.append(
            dict(
                subject_id=r[0],
                display_name=label,
                state=r[1],
                detail=json.loads(r[2]),
                created_at=r[3],
            )
        )
    return result


def prediction_list(
    store, model_id=None, trading_date=None, limit=50, offset=0, task=None
):
    clauses = ["1=1"]
    params = []
    if model_id:
        clauses.append("d.model_version_id=?")
        params.append(model_id)
    if trading_date:
        clauses.append("d.trading_date=?")
        params.append(trading_date)
    if task:
        clauses.append(
            "d.model_version_id IN (SELECT model_version_id FROM ml_models WHERE task=?)"
        )
        params.append(task)
    params.append(limit)
    params.append(offset)
    result = []
    for r in store.db.execute(
        "SELECT o.object_id,o.source_hash,o.payload_json,o.created_at FROM ml_predictions d JOIN ml_object o ON o.object_id=d.prediction_id WHERE "
        + " AND ".join(clauses)
        + " ORDER BY o.rowid DESC LIMIT ? OFFSET ?",
        params,
    ):
        p = json.loads(r[2])
        result.append(
            dict(
                id=r[0],
                display_name=ml.get_object(store, r[0])["display_name"],
                model_name=ml.get_object(store, p["model_id"])["display_name"],
                source_hash=r[1],
                created_at=r[3],
                model_id=p["model_id"],
                date=p["date"],
                scores=p["scores"],
                validation_only=p["validation_only"],
                logical_cutoff=p["logical_cutoff"],
                count=len(p["points"]),
            )
        )
    return result


@router.get("/predictions")
def predictions(
    model_id: str | None = None,
    trading_date: date | None = None,
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0, le=1000000),
    store: Store = Depends(store_dep),
):
    day = trading_date.isoformat() if trading_date else None
    total = store.db.execute(
        "SELECT count(*) FROM ml_predictions WHERE (? IS NULL OR model_version_id=?) AND (? IS NULL OR trading_date=?)",
        (model_id, model_id, day, day),
    ).fetchone()[0]
    return dict(
        records=prediction_list(store, model_id, day, limit, offset),
        total=total,
        offset=offset,
        limit=limit,
    )


@router.get("/summary")
def summary(store: Store = Depends(store_dep)):
    catalog = public_data.catalog()
    active = ml.active(store)
    active_id = active["detail"].get("model_id")
    model = ml.get_object(store, active_id, "model") if active_id else None
    recent = prediction_list(store, active_id, limit=1) if active_id else []
    latest = ml.get_object(store, recent[0]["id"], "prediction") if recent else None
    model_count = store.db.execute("SELECT count(*) FROM ml_models").fetchone()[0]
    jobs = [
        ml.job(store, r[0])
        for r in store.db.execute(
            "SELECT job_id FROM ml_job ORDER BY rowid DESC LIMIT 50"
        )
    ]
    return dict(
        catalog=catalog,
        checked_at=ml.now(),
        active_model=model,
        latest_prediction=latest,
        model_count=model_count,
        jobs=jobs,
        worker=ml.state(store, "worker"),
        monitor=ml.state(store, "monitor"),
        events=event_history(store),
        prediction_count=store.db.execute(
            "SELECT count(*) FROM ml_predictions"
        ).fetchone()[0],
        production_eligible=False,
        time_policy="historical_assumed",
    )


@router.get("/events")
def events(store: Store = Depends(store_dep)):
    return dict(events=event_history(store, 100))


@router.get("/decomposition")
def decomposition(
    trading_date: date,
    field: Literal["rt_price", "pv_actual_mw", "load_actual_mw"] = "rt_price",
    days: int = Query(default=14, ge=3, le=31),
    cursor: int = Query(default=96, ge=0, le=96),
    source_hash: str | None = None,
):
    meta, dates, records = current(source_hash)
    last = trading_date.isoformat()
    if last not in records:
        raise ValueError("所选日期没有源记录")
    start = trading_date - timedelta(days=days - 1)
    points = []
    for n in range(days):
        day = (start + timedelta(days=n)).isoformat()
        for slot in range(cursor if day == last else 96):
            original = records.get(day, {}).get(slot)
            if day < dates[0]:
                continue
            points.append(
                dict(
                    date=day,
                    slot=slot,
                    timestamp=(
                        datetime.fromisoformat(day).replace(tzinfo=public_data.TZ)
                        + timedelta(minutes=15 * slot)
                    ).isoformat(),
                    source_line=original["source_line"] if original else None,
                    actual=original[field] if original else None,
                )
            )
    if sum(p["actual"] is not None for p in points) < 3 * 96:
        raise ValueError("需要至少三个完整日周期的有效数据；请扩大范围或推进回放")
    y = np.array([p["actual"] for p in points], dtype=float)
    valid = np.isfinite(y)
    sums = np.concatenate(([0.0], np.cumsum(np.where(valid, y, 0))))
    counts = np.concatenate(([0], np.cumsum(valid)))
    right = np.arange(len(y)) + 1
    left = np.maximum(0, right - 96)
    count = counts[right] - counts[left]
    trend = np.divide(
        sums[right] - sums[left], count, out=np.full(len(y), np.nan), where=count >= 48
    )
    detrended = y - trend
    slot_values = {
        s: [
            detrended[i]
            for i, p in enumerate(points)
            if p["slot"] == s and np.isfinite(detrended[i])
        ]
        for s in range(96)
    }
    seasonal = np.array(
        [
            np.median(slot_values[p["slot"]]) if slot_values[p["slot"]] else np.nan
            for p in points
        ]
    )
    residual = y - trend - seasonal
    for i, p in enumerate(points):
        p.update(
            {
                key: float(a[i]) if np.isfinite(a[i]) else None
                for key, a in (
                    ("trend", trend),
                    ("seasonal", seasonal),
                    ("residual", residual),
                )
            }
        )
    return dict(
        source_hash=meta["source_hash"],
        field=field,
        unit=public_data.FIELDS[field][1],
        points=points,
        method="96点后向均值趋势 + 窗口内同时段中位周期 + 剩余项；首48点不足时趋势保留为空",
        scope=dict(
            start=points[0]["timestamp"],
            end=points[-1]["timestamp"],
            cursor=cursor,
            retrospective=True,
        ),
        notice="历史描述，不是因果解释；不补造缺失实测，不进入训练或未来预测输入。",
    )


def compare(store, model_id, partition):
    ref = ml.get_object(store, model_id, "model")
    p = ref["payload"]
    if partition == "final_audit":
        audits = [
            a
            for a in ml.objects(store, "audit")
            if a["payload"]["model_id"] == model_id
        ]
        if not audits:
            raise ValueError("该模型没有已启封的最终审计，不能临时重算终评")
        audited = audits[0]["payload"]
        report = audited["report"][partition]
        native = ml.read_npz(audited["predictions"])
        original_models = {
            m["payload"]["algorithm"]: m
            for m in ml.objects(store, "model")
            if m["payload"]["job_id"] == p["job_id"]
        }
        rows = [
            dict(
                model_id=original_models[name]["id"],
                algorithm=name,
                alpha=p["alpha"] if name == "ridge" else None,
                state=original_models[name]["state"],
                scores=score,
                aliases=[original_models[name]["id"]],
            )
            for name, score in report["scores"].items()
        ]
        data = {k: native[k] for k in ("y", "days", "slots")}
        predictions_by_name = {name: native[name] for name in report["scores"]}
    else:
        report = p["report"][partition]
        rows, seen, predictions_by_name = [], {}, {}
        data = None
        candidates = [
            m
            for m in ml.objects(store, "model")
            if m["payload"]["dataset_id"] == p["dataset_id"]
            and m["source_hash"] == ref["source_hash"]
        ]
        candidates.sort(
            key=lambda m: (m["id"] != model_id, m["state"] != "research_active")
        )
        for m in candidates:
            mp = m["payload"]
            r = mp["report"][partition]
            if (
                r["row_mask_hash"] != report["row_mask_hash"]
                or ml.job(store, mp["job_id"])["state"] != "succeeded"
            ):
                continue
            values = ml.read_npz(mp["evaluation_predictions"])
            algorithm = mp["algorithm"]
            predicted = values[f"{partition}_{algorithm}"]
            identity = (algorithm, hashlib.sha256(predicted.tobytes()).hexdigest())
            if identity in seen:
                seen[identity]["aliases"].append(m["id"])
                continue
            row = dict(
                model_id=m["id"],
                algorithm=algorithm,
                alpha=mp["alpha"],
                state=m["state"],
                scores=r["scores"][algorithm],
                aliases=[m["id"]],
            )
            rows.append(row)
            seen[identity] = row
            predictions_by_name[m["id"]] = predicted
            if data is None:
                data = {k: values[f"{partition}_{k}"] for k in ("y", "days", "slots")}
        if data is None:
            raise ValueError("该组尚无具备成功退出记录的可比模型")
    start, end = p["splits"][partition]
    from .task_catalog import slots

    expected = ((date.fromisoformat(end) - date.fromisoformat(start)).days + 1) * len(
        slots(p["task"])
    )
    daily = []
    for day in np.unique(data["days"]):
        mask = data["days"] == day
        daily.append(
            dict(
                date=str(day),
                n=int(mask.sum()),
                mae={
                    name: float(np.mean(abs(values[mask] - data["y"][mask])))
                    for name, values in predictions_by_name.items()
                },
            )
        )
    return dict(
        model_id=model_id,
        dataset_id=p["dataset_id"],
        source_hash=ref["source_hash"],
        partition=partition,
        start=start,
        end=end,
        rows=rows,
        daily=daily,
        report=report,
        expected=expected,
        label_coverage=report["rows"] / expected,
        time_policy="historical_assumed",
        unit="CNY/MWh",
        notice="按同一数据版本、分区和标签掩码比较；重复输出折叠为同一行。最终审计只显示已冻结候选的既有结果。",
    )


@router.get("/comparison")
def comparison(
    model_id: str,
    partition: Literal["tune", "promotion", "final_audit"] = "promotion",
    store: Store = Depends(store_dep),
):
    return compare(store, model_id, partition)


@router.get("/prediction-details/{oid}")
def prediction_details(
    oid: str, confidence: float = Query(default=0.95), store: Store = Depends(store_dep)
):
    if confidence not in {0.8, 0.9, 0.95}:
        raise ValueError("经验范围仅支持80%、90%或95%")
    record = ml.get_object(store, oid, "prediction")
    p = record["payload"]
    model = ml.get_object(store, p["model_id"], "model")
    m = model["payload"]
    result = dict(
        prediction_id=oid,
        view_protocol="research-display-v1",
        unit=p["unit"],
        confidence=confidence,
        model_name=model["display_name"],
        input_name=source_display_name(store, record["source_hash"]),
        range=None,
        explanation=None,
        source_hash=record["source_hash"],
        weights_hash=p["weights_hash"],
        notice="点预测不变。经验范围来自既有调参误差，不是独立校准区间或概率保证；解释项不代表因果。",
    )
    observation = data_flow.latest_observation(store, oid)
    result["observation"] = observation
    if (
        p["date"]
        > (date.fromisoformat(m["selection_end"]) + timedelta(days=1)).isoformat()
        and not p["validation_only"]
    ):
        native = ml.read_npz(m["evaluation_predictions"])
        error = abs(native["tune_" + m["algorithm"]] - native["tune_y"])
        half = float(np.quantile(error, confidence))
        points = [
            {**r, "lower": r["predicted"] - half, "upper": r["predicted"] + half}
            for r in p["points"]
        ]
        observed = [r for r in points if r["actual"] is not None]
        result["range"] = dict(
            points=points,
            mean_width=2 * half,
            calibration_points=len(error),
            observed_points=len(observed),
            observed_coverage=(
                sum(r["lower"] <= r["actual"] <= r["upper"] for r in observed)
                / len(observed)
                if observed
                else None
            ),
            calibration_artifact=m["evaluation_predictions"]["sha256"],
            calibration_end=m["selection_end"],
        )
    else:
        result["range_unavailable"] = (
            "当前记录属于调参验证，不能用同窗标签为自己回算误差范围。"
        )
    source_error = None
    try:
        meta, _, days = data_flow.source_version(store, record["source_hash"])
    except ValueError as exc:
        meta, days, source_error = None, None, str(exc)
    if m["algorithm"] == "ridge" and days is not None:
        from . import task_catalog as tasks

        x = np.array(
            [
                (
                    ml.features_for(days, p["date"], s)
                    if m["task"] == ml.TASK
                    else tasks.features(days, p["date"], s, m["task"])
                )
                for s in tasks.slots(m["task"])
            ],
            dtype=float,
        )
        if hashlib.sha256(x.tobytes()).hexdigest() != p["feature_value_hash"]:
            raise ValueError("输入特征校验不符，不能展示该记录的模型解释")
        a = ml.validate_model(ml.read_npz(m["weights"]), len(m["policy"]["features"]))
        contributions = (
            ml.transform(x, a["medians"], a["mean"], a["scale"]) * a["coefficients"]
        )
        groups = [
            ("历史同时段目标量", [0, 1, 2]),
            ("历史日均与极值", [3, 4, 5, 6]),
            ("日内时段", [7, 8]),
            ("星期", [9, 10]),
            ("月份", [11, 12]),
        ]
        if len(m["policy"]["features"]) > 13:
            groups.append(("近期已知观测", [13, 14, 15]))
        items = [
            dict(
                name=name,
                value=float(
                    contributions[
                        :, indices + [i + len(m["policy"]["features"]) for i in indices]
                    ]
                    .sum(1)
                    .mean()
                ),
            )
            for name, indices in groups
        ]
        items.append(dict(name="模型截距", value=float(a["intercept"])))
        predicted_mean = float(
            np.mean([r.get("raw_predicted", r["predicted"]) for r in p["points"]])
        )
        if not np.isclose(
            sum(i["value"] for i in items), predicted_mean, rtol=1e-9, atol=1e-8
        ):
            raise ValueError("模型项贡献与已保存预测不一致")
        result["explanation"] = dict(
            items=items,
            prediction_mean=predicted_mean,
            reconstruction_verified=True,
            output_constrained=bool(m.get("output_bounds")),
            postprocessed_prediction_mean=float(
                np.mean([r["predicted"] for r in p["points"]])
            ),
            method=(
                "约束前线性项及缺失指示项的日均贡献；出力约束后的结果以保存点预测为准。"
                if m.get("output_bounds")
                else "标准化线性项及缺失指示项的日均贡献；含截距后重构日均预测"
            ),
        )
    else:
        result["explanation_unavailable"] = (
            source_error or "该基线没有Ridge线性项；保留预测快照，不制造解释。"
        )
    return result


def csv_response(name, columns, rows):
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=columns)
    writer.writeheader()
    writer.writerows(rows)
    return Response(
        content=("\ufeff" + stream.getvalue()).encode("utf-8"),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{name}.csv"'},
    )


@router.get("/predictions/{oid}/export")
def export_prediction(
    oid: str, observation_id: str | None = None, store: Store = Depends(store_dep)
):
    r = ml.get_object(store, oid, "prediction")
    p = r["payload"]
    observation = (
        ml.get_object(store, observation_id, "observation_match")
        if observation_id
        else None
    )
    if observation and observation["parent_id"] != oid:
        raise ValueError("实际值核对记录不属于所选预测")
    selected = observation["payload"]["points"] if observation else p["points"]
    model_name = ml.get_object(store, p["model_id"], "model")["display_name"]
    actual_source = "最新已核对观测" if observation else "原预测保存快照"
    unit = "MW" if p["unit"] == "MW" else "元/MWh"
    rows = [
        {
            "交易日": p["date"],
            "时段": f"{x['slot']//4:02d}:{x['slot']%4*15:02d}",
            "预测值（" + unit + "）": x["predicted"],
            "实际值（" + unit + "）": x["actual"],
            "预测模型": model_name,
            "实际值来源": actual_source,
        }
        for x in selected
    ]
    return csv_response("price-prediction-" + p["date"], list(rows[0]), rows)
