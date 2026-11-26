"""One source-owned workbench contract over the existing repositories.

The data adapters keep their real units and provenance. A client cannot carry
market model or prediction references into a station scope (or vice versa).
"""

from datetime import date as Date, datetime, timedelta
import json
from typing import Literal

import numpy as np
from fastapi import APIRouter, Depends, Request, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field, field_validator
from urllib.parse import urlsplit
from uuid import uuid4

from .storage import Store, instant
from .serving import rows, now, day_bounds, data_clock, build_intervals
from .learning_api import store_dep
from . import learning as ml, public_data, data_flow
from . import research_views
from .readiness import available_dates
from .rsi import model_states, rsi_overview, review_feedback, approve_model
from .model_runtime import list_runtime_models, builtin_model, run_model_inference
from .model_settings import load_settings
from . import task_catalog as tasks

router = APIRouter(prefix="/api/v1/workspace", tags=["unified-workbench"])


def native_label(name, version):
    names = {
        "pv_residual_ridge": "历史功率拟合模型",
        "lgbm-demo": "光伏功率参考模型",
        "intraday-corr-demo": "日内修正参考模型",
        "demo-scenario": "演示参考模型",
    }
    version = str(version)
    candidate = version.endswith("-cand")
    return f"{names.get(name,name)} · 第{version.removesuffix('-cand')}版" + (
        "（候选）" if candidate else ""
    )


def sources(store):
    public = public_data.catalog()
    past = [
        r[0]
        for r in store.db.execute("SELECT DISTINCT trading_date FROM ml_predictions")
    ]
    public_dates = sorted(set(public["dates"]) | set(past))
    result = [
        dict(
            key="market:shandong",
            name="山东市场历史数据",
            domain="market",
            source_mode="public_reference",
            task=ml.TASK,
            task_name="实时电价预测",
            unit="元/MWh",
            dates=public_dates,
            available=public["available"] or bool(past),
            default_date=next(
                (d for d in reversed(public_dates) if d <= ml.splits()["promotion"][1]),
                public_dates[-1] if public_dates else "",
            ),
            notice="省级公开历史数据，用于研究；原始发布时间未核验。",
            can_train=True,
            tasks=[
                dict(
                    id=k,
                    name=v["name"],
                    unit=v["display_unit"],
                    points=len(tasks.slots(k)),
                    intraday=v["intraday"],
                )
                for k, v in tasks.TASKS.items()
            ],
        )
    ]
    for station in rows(
        store, "SELECT station_id,station_name FROM station ORDER BY station_id"
    ):
        for mode in ("synthetic", "production"):
            dates = available_dates(store, station["station_id"], mode)
            clock_day = (
                datetime.fromisoformat(data_clock(store, mode).replace("Z", "+00:00"))
                .astimezone(public_data.TZ)
                .date()
                .isoformat()
            )
            result.append(
                dict(
                    key=f"station:{station['station_id']}:{mode}",
                    name=station["station_name"]
                    + ("（合成演示）" if mode == "synthetic" else "（生产输入）"),
                    domain="station",
                    source_mode=mode,
                    station_id=station["station_id"],
                    task="day_ahead_power",
                    task_name="日前功率预测",
                    unit="MW",
                    dates=dates,
                    available=bool(dates),
                    default_date=(
                        clock_day if clock_day in dates else dates[-1] if dates else ""
                    ),
                    notice=(
                        "合成演示，不代表场站生产效果。"
                        if mode == "synthetic"
                        else "仅使用已核验到达的生产记录；缺失不以演示数据补齐。"
                    ),
                    can_train=False,
                )
            )
    return result


def source(store, key, task_id=None):
    found = next((s for s in sources(store) if s["key"] == key), None)
    if not found:
        raise ValueError("数据范围不存在，请重新选择")
    if found["domain"] == "market":
        task_id = task_id or ml.TASK
        v = tasks.spec(task_id)
        found.update(
            task=task_id,
            task_name=v["name"],
            unit=v["display_unit"],
            notice=tasks.notice(task_id),
            target_points=len(tasks.slots(task_id)),
            intraday=v["intraday"],
        )
    elif task_id and task_id != found["task"]:
        raise ValueError("此场站范围没有所选任务，请选择公开数据范围")
    else:
        found.update(
            tasks=[
                dict(
                    id=found["task"],
                    name=found["task_name"],
                    unit=found["unit"],
                    points=96,
                    intraday=False,
                )
            ],
            target_points=96,
            intraday=False,
        )
    return found


def station_scope(s, day, mode, until):
    from .api import Scope

    return Scope(
        station_id=s["station_id"],
        date=day,
        source_mode=s["source_mode"],
        mode=mode,
        cutoff_at=f"{day}T{until}:00+08:00" if mode == "replay" else None,
    )


def station_intervals(store, s, day, mode, until, cutoff_at=None):
    from .api import resolve_scope

    sc = station_scope(s, day, mode, until)
    cutoff = cutoff_at or resolve_scope(sc, store)
    return (
        build_intervals(
            store,
            s["station_id"],
            day,
            cutoff,
            s["source_mode"],
            registry_cutoff=cutoff if mode == "replay" else now(),
        ),
        cutoff,
    )


def comparison_evidence(ci, unit):
    if ci.get("upper95") is None:
        return "有效交易日不足，尚不能确认误差改善。"
    conclusion = (
        "支持误差降低"
        if ci["upper95"] < 0
        else "误差更高" if ci["lower95"] > 0 else "改善尚不确定"
    )
    return f"按交易日计算，相对预设参考的平均绝对误差差值95%区间为 [{ci['lower95']:.3f}, {ci['upper95']:.3f}] {unit}；{conclusion}。"


def catalog(store):
    return dict(
        sources=sources(store), default_source="market:shandong", checked_at=now()
    )


@router.get("/catalog")
def get_catalog(store: Store = Depends(store_dep)):
    return catalog(store)


def models(store, s):
    if s["domain"] == "market":
        active = ml.active(store, s["task"])["detail"]
        result = []
        for m in ml.objects(store, "model"):
            p = m["payload"]
            if p["task"] != s["task"]:
                continue
            ready = (
                ml.job(store, p["job_id"])["state"] == "succeeded"
                and m["state"] != "rejected"
            )
            result.append(
                dict(
                    id=m["id"],
                    name=m["display_name"],
                    state=m["state"],
                    trained=p["algorithm"] == "ridge"
                    and ml.job(store, p["job_id"])["state"] == "succeeded",
                    can_predict=ready,
                    can_approve=ready
                    and m["state"] in {"evaluated", "shadow", "retired"},
                    can_rollback=active.get("previous_model_id") == m["id"],
                    created_at=m["created_at"],
                    task=p["task"],
                    unit=s["unit"],
                    dataset_id=p["dataset_id"],
                    can_final_audit=ready
                    and p["algorithm"] == "ridge"
                    and ml.state(
                        store,
                        "final_window:"
                        + p["task"]
                        + ":"
                        + ml.digest(p["splits"]["final_audit"]),
                    )["state"]
                    == "registered",
                    score=p["report"]["promotion"]["scores"][p["algorithm"]],
                    scope_label="提升评估窗口",
                    alpha=p["alpha"],
                )
            )
        return result
    runtime = {m["model_version_id"]: m for m in list_runtime_models(store)}
    candidates = {
        c["candidate_model_version_id"]: c
        for c in rows(store, "SELECT * FROM iteration_candidate")
    }
    result = []
    for m in model_states(store):
        if m["source_mode"] != s["source_mode"] or m["task"] != s["task"]:
            continue
        candidate = candidates.get(m["model_version_id"])
        evaluation = (
            store.db.execute(
                "SELECT r.station_id,r.source_mode,r.target_start FROM evaluation_run e JOIN prediction_run r USING(run_id) WHERE e.evaluation_id=?",
                (candidate["evaluation_id"],),
            ).fetchone()
            if candidate and candidate["evaluation_id"]
            else None
        )
        approval_owned = bool(
            evaluation
            and evaluation["station_id"] == s["station_id"]
            and evaluation["source_mode"] == s["source_mode"]
        )
        approval_day = (
            datetime.fromisoformat(evaluation["target_start"].replace("Z", "+00:00"))
            .astimezone(public_data.TZ)
            .date()
            .isoformat()
            if evaluation
            else None
        )
        belongs = store.db.execute(
            "SELECT 1 FROM prediction_run WHERE model_version_id=? AND station_id=? AND source_mode=? LIMIT 1",
            (m["model_version_id"], s["station_id"], s["source_mode"]),
        ).fetchone()
        if not belongs and not runtime.get(m["model_version_id"], {}).get("ready"):
            continue
        result.append(
            dict(
                id=m["model_version_id"],
                name=native_label(m["model_name"], m["version"]),
                state=m["effective_status"],
                trained=False,
                can_predict=bool(runtime.get(m["model_version_id"], {}).get("ready")),
                can_approve=approval_owned
                and m["effective_status"] in {"candidate", "shadow", "rolled_back"},
                can_rollback=approval_owned and m["effective_status"] == "production",
                candidate_id=candidate["candidate_id"] if candidate else None,
                approval_day=approval_day,
                created_at=m["created_at"],
                task=m["task"],
                unit=s["unit"],
                score=None,
                scope_label="场站参考记录，正式训练证据待核验",
                alpha=None,
            )
        )
    b = builtin_model(s["source_mode"])
    if not any(m["id"] == b["model_version_id"] for m in result):
        result.append(
            dict(
                id=b["model_version_id"],
                name="历史功率拟合模型",
                state="candidate",
                trained=False,
                can_predict=True,
                can_approve=False,
                can_rollback=False,
                created_at=None,
                task=s["task"],
                unit=s["unit"],
                score=None,
                scope_label="按可见历史拟合，未经生产验收",
                alpha=None,
            )
        )
    return result


def records(store, s, day, mode="post", until="24:00"):
    if s["domain"] == "market":
        return [
            dict(
                id=r["id"],
                name=r["display_name"],
                model_id=r["model_id"],
                date=r["date"],
                created_at=r["created_at"],
            )
            for r in research_views.prediction_list(
                store, trading_date=day, limit=100, task=s["task"]
            )
        ]
    start, end = day_bounds(day)
    cutoff = instant(f"{day}T{until}:00+08:00") if mode == "replay" else now()
    return [
        dict(
            id=r["run_id"],
            name=native_label(r["model_name"], r["version"])
            + " · "
            + datetime.fromisoformat(r["created_at"].replace("Z", "+00:00"))
            .astimezone(public_data.TZ)
            .strftime("%m-%d %H:%M"),
            model_id=r["model_version_id"],
            date=day,
            created_at=r["created_at"],
        )
        for r in rows(
            store,
            "SELECT r.*,m.model_name,m.version FROM prediction_run r JOIN model_version m USING(model_version_id) WHERE r.station_id=? AND r.source_mode=? AND r.task=? AND r.target_start>=? AND r.target_end<=? AND r.available_at<=? ORDER BY r.created_at DESC,r.rowid DESC LIMIT 100",
            (s["station_id"], s["source_mode"], s["task"], start, end, cutoff),
        )
    ]


def owned_model(store, s, mid):
    m = next((m for m in models(store, s) if m["id"] == mid), None)
    if not m:
        raise ValueError("所选模型不属于当前数据范围和预测任务，请重新选择")
    return m


def owned_record(store, s, rid, day, mid=None, mode="post", until="23:59"):
    if s["domain"] == "market":
        obj = ml.get_object(store, rid, "prediction")
        p = obj["payload"]
        owned_model(store, s, p["model_id"])
        r = (
            dict(
                id=rid,
                name=obj["display_name"],
                model_id=p["model_id"],
                date=p["date"],
                created_at=obj["created_at"],
            )
            if p["date"] == day
            else None
        )
    else:
        start, end = day_bounds(day)
        cutoff = instant(f"{day}T{until}:00+08:00") if mode == "replay" else now()
        row = store.db.execute(
            "SELECT r.*,m.model_name,m.version FROM prediction_run r JOIN model_version m USING(model_version_id) WHERE r.run_id=? AND r.station_id=? AND r.source_mode=? AND r.task=? AND r.target_start>=? AND r.target_end<=? AND r.available_at<=?",
            (rid, s["station_id"], s["source_mode"], s["task"], start, end, cutoff),
        ).fetchone()
        r = (
            dict(
                id=rid,
                name=native_label(row["model_name"], row["version"]),
                model_id=row["model_version_id"],
                date=day,
                created_at=row["created_at"],
            )
            if row
            else None
        )
    if not r or (mid and r["model_id"] != mid):
        raise ValueError("预测记录与当前来源、日期或模型不一致，请重新选择")
    return r


def snapshot(
    store,
    s,
    day,
    mid=None,
    rid=None,
    mode="post",
    until="23:59",
    basis="latest",
    source_dataset=None,
):
    visible = (
        min(96, (int(until[:2]) * 60 + int(until[3:])) // 15)
        if mode == "replay"
        else 96
    )
    if s["domain"] == "market":
        saved = None
        observation = None
        if rid:
            owned_record(store, s, rid, day, mid, mode, until)
            saved = ml.get_object(store, rid, "prediction")
        elif mid:
            candidate = next(
                (r for r in records(store, s, day) if r["model_id"] == mid), None
            )
            if candidate:
                saved = ml.get_object(store, candidate["id"], "prediction")
        if saved:
            observation = (
                data_flow.latest_observation(store, saved["id"])
                if basis == "latest"
                else None
            )
            selected = (
                observation["payload"]["points"]
                if observation
                else saved["payload"]["points"]
            )
            sha = observation["source_hash"] if observation else saved["source_hash"]
            dataset = data_flow.source_version(store, sha)
            data = public_data.series(day, visible, sha, source_dataset=dataset)
        else:
            selected = []
            dataset = source_dataset or public_data.dataset()
            data = public_data.series(day, visible, source_dataset=dataset)
        day_rows = dataset[2][day]
        task = s["task"]
        hourly = tasks.spec(task)["hourly"]
        byslot = {p["slot"]: p for p in selected}
        points = []
        for p in data["points"]:
            slot = p["slot"]
            if slot not in tasks.slots(task):
                continue
            actual = (
                (
                    byslot.get(slot, {}).get("actual")
                    if saved
                    else tasks.target(task, day_rows, slot)
                )
                if slot < visible
                else None
            )
            issue_slot = slot - 3 if hourly else slot
            predicted = (
                byslot.get(slot, {}).get("predicted")
                if not (s.get("intraday") and mode == "replay" and issue_slot > visible)
                else None
            )
            start = datetime.fromisoformat(
                p["interval_start"].replace("Z", "+00:00")
            ) - timedelta(minutes=45 if hourly else 0)
            points.append(
                dict(
                    slot=slot,
                    start=start.isoformat(),
                    actual=actual,
                    predicted=predicted,
                    observation_key=ml.digest(
                        dict(
                            task=task,
                            source_hash=data["metadata"]["source_hash"],
                            slot=slot,
                        )
                    ),
                    da_price=(
                        (
                            tasks.hour_value(day_rows, slot, "da_price")
                            if hourly
                            else p["da_price"]
                        )
                        if slot < visible
                        else None
                    ),
                    rt_price=(
                        (
                            tasks.hour_value(day_rows, slot, "rt_price")
                            if hourly
                            else p["rt_price"]
                        )
                        if slot < visible
                        else None
                    ),
                    pv_actual=(
                        (
                            tasks.hour_value(day_rows, slot, "pv_actual_mw")
                            if hourly
                            else p["pv_actual_mw"]
                        )
                        if slot < visible
                        else None
                    ),
                    quality=(
                        "valid"
                        if actual is not None
                        else "missing" if slot < visible else "pending"
                    ),
                )
            )
        return points, saved, observation, data["metadata"]
    intervals, cutoff = station_intervals(store, s, day, mode, until)
    selected = {}
    if rid:
        owned_record(store, s, rid, day, mid, mode, until)
        selected = {
            p["target_start"]: p
            for p in rows(
                store, "SELECT * FROM prediction_value WHERE run_id=?", (rid,)
            )
        }
    points = []
    for i, p in enumerate(intervals):
        saved = selected.get(p["interval_start"])
        if basis == "snapshot":
            raise ValueError("场站记录未保存实际值快照，请使用查询时点的实际观测")
        actual = p["actual_mw"]
        if mode == "replay" and p["actual_mw"] is None:
            actual = None
        points.append(
            dict(
                slot=i,
                start=p["interval_start"],
                actual=actual,
                predicted=saved["value"] if saved else None,
                da_price=p["da_price"],
                rt_price=p["rt_price"],
                pv_actual=p["actual_mw"],
                quality=p["quality_flag"],
                observation_key=ml.digest(
                    [
                        r
                        for r in json.loads(p["lineage_refs_json"])
                        if r["table"] == "station_actual"
                    ]
                ),
            )
        )
    return (
        points,
        None,
        None,
        dict(name=s["name"], source_kind=s["source_mode"], cutoff_at=cutoff),
    )


def review_cases(
    store, s, day, points, saved, observation, mode, until, record_id=None
):
    if s["domain"] == "market":
        if not saved:
            return []
        result = []
        feedback = [
            f
            for f in ml.objects(store, "feedback")
            if f["parent_id"] == saved["id"]
            and f["payload"].get("observation_id")
            == (observation["id"] if observation else None)
        ]
        for p in points:
            if p["predicted"] is None or p["actual"] is None:
                continue
            f = next((f for f in feedback if f["payload"]["slot"] == p["slot"]), None)
            result.append(
                dict(
                    id=f"slot:{p['slot']}",
                    slot=p["slot"],
                    start=p["start"],
                    actual=p["actual"],
                    predicted=p["predicted"],
                    error=p["predicted"] - p["actual"],
                    state=f["state"] if f else "pending",
                    reason=f["payload"]["reason"] if f else "",
                    feedback_id=f["id"] if f else None,
                    observation_id=observation["id"] if observation else None,
                )
            )
        return sorted(result, key=lambda p: abs(p["error"]), reverse=True)
    cutoff = instant(f"{day}T{until}:00+08:00") if mode == "replay" else now()
    if not record_id:
        return []
    result = []
    for p in points:
        if p["actual"] is None or p["predicted"] is None:
            continue
        case = store.db.execute(
            "SELECT * FROM deviation_case WHERE prediction_run_id=? AND interval_start=? AND actual_value=? AND predicted_value=? AND json_extract(auto_clues_json,'$.observation_key')=? AND created_at<=? ORDER BY rowid DESC LIMIT 1",
            (
                record_id,
                p["start"],
                p["actual"],
                p["predicted"],
                p["observation_key"],
                cutoff,
            ),
        ).fetchone()
        feedback = store.db.execute(
            "SELECT f.* FROM review_feedback f JOIN prediction_value p USING(prediction_id) WHERE p.run_id=? AND p.target_start=? AND f.created_at<=? ORDER BY f.rowid DESC LIMIT 1",
            (record_id, p["start"], cutoff),
        ).fetchone()
        if feedback:
            binding = ml.state(store, feedback["feedback_id"])
            evidence = binding["detail"]
            if (
                binding["state"] != "workbench_review_snapshot"
                or evidence.get("actual") != p["actual"]
                or evidence.get("predicted") != p["predicted"]
                or evidence.get("source_key") != s["key"]
                or evidence.get("observation_key") != p["observation_key"]
            ):
                feedback = None
        result.append(
            dict(
                id=case["case_id"] if case else f"slot:{p['slot']}",
                slot=p["slot"],
                start=p["start"],
                actual=p["actual"],
                predicted=p["predicted"],
                error=p["predicted"] - p["actual"],
                state="confirmed" if feedback else "pending",
                reason=feedback["reason"] if feedback else "",
                feedback_id=feedback["feedback_id"] if feedback else None,
                observation_id=None,
                observation_key=p["observation_key"],
            )
        )
    return sorted(result, key=lambda p: abs(p["error"]), reverse=True)


def context(
    store,
    key,
    day=None,
    mid=None,
    rid=None,
    mode="post",
    until="23:59",
    basis="latest",
    window="promotion",
    task_id=None,
):
    s = source(store, key, task_id)
    day = day or s["default_date"]
    mm = models(store, s)
    if mid:
        owned_model(store, s, mid)
    if day and day not in s["dates"]:
        raise ValueError("所选日期不属于当前数据范围，请重新选择")
    if s["domain"] == "station":
        for m in mm:
            m["can_approve"] = m["can_approve"] and m.get("approval_day") == day
    else:
        active = ml.active(store, s["task"])["detail"].get("model_id")
        for m in mm:
            obj = ml.get_object(store, m["id"], "model")
            p = obj["payload"]
            if not active and p["algorithm"] != p["policy"].get(
                "initial_baseline", "seasonal_naive_d2"
            ):
                m["can_approve"] = False
            sealed = p["splits"]["final_audit"]
            if (
                sealed[0] <= day <= sealed[1]
                and ml.state(store, tasks.seal(obj))["detail"].get("model_id")
                != m["id"]
            ):
                m["can_predict"] = False
                m["scope_label"] = "当前日期未对这个版本启封，不能运行预测"
    if not day:
        return dict(
            source=s,
            date="",
            models=mm,
            records=[],
            points=[],
            metrics=ml.scores(np.array([]), np.array([])),
            cases=[],
            jobs=[],
            activity=[],
            comparison=[],
            flow=[],
            model_id=None,
            record_id=None,
            checked_at=now(),
        )
    rr = records(store, s, day, mode, until)
    if rid:
        r = owned_record(store, s, rid, day, mid, mode, until)
        mid = r["model_id"]
    if not mid:
        mid = (
            ml.active(store, s["task"])["detail"].get("model_id")
            if s["domain"] == "market"
            else next((m["id"] for m in mm if m["state"] == "production"), None)
        ) or (mm[0]["id"] if mm else None)
    if not rid and s["domain"] == "station":
        candidate = next((r for r in rr if r["model_id"] == mid), None)
        if candidate:
            rid = candidate["id"]
    points, saved, obs, metadata = snapshot(store, s, day, mid, rid, mode, until, basis)
    if saved:
        rid = saved["id"]
        mid = saved["payload"]["model_id"]
    paired = [
        p for p in points if p["actual"] is not None and p["predicted"] is not None
    ]
    scored = ml.scores(
        np.array([p["actual"] for p in paired]),
        np.array([p["predicted"] for p in paired]),
    )
    cases = review_cases(store, s, day, points, saved, obs, mode, until, rid)
    jobs = []
    comparison = []
    comparison_notice = None
    activity = []
    if s["domain"] == "market":
        jobs = [
            ml.job(store, r[0])
            for r in store.db.execute(
                "SELECT j.job_id FROM ml_job j JOIN ml_dataset_registry d USING(dataset_id) WHERE d.task=? ORDER BY j.rowid DESC LIMIT 50",
                (s["task"],),
            )
        ]
        activity = []
        for e in research_views.event_history(store, 150):
            if e["detail"].get("source_key", s["key"]) != s["key"]:
                continue
            if e["subject_id"].startswith("workbench:"):
                e["display_name"] = e["detail"].get("stage", "业务操作")
            if (
                e["subject_id"].startswith("workbench:")
                and e["subject_id"] != "workbench:" + s["key"]
            ):
                continue
            obj = store.db.execute(
                "SELECT payload_json FROM ml_object WHERE object_id=?",
                (e["subject_id"],),
            ).fetchone()
            if obj and json.loads(obj[0]).get("source_key", s["key"]) != s["key"]:
                continue
            if (
                e["subject_id"].startswith("workbench:")
                and e["detail"].get("task_id", ml.TASK) != s["task"]
            ):
                continue
            payload = json.loads(obj[0]) if obj else {}
            event_task = payload.get("task") or payload.get("policy", {}).get("task")
            if not event_task and payload.get("model_id"):
                event_task = ml.get_object(store, payload["model_id"], "model")[
                    "payload"
                ]["task"]
            job_id = e["subject_id"].removeprefix("ownership:")
            jr = store.db.execute(
                "SELECT d.task FROM ml_job j JOIN ml_dataset_registry d USING(dataset_id) WHERE j.job_id=?",
                (job_id,),
            ).fetchone()
            if jr:
                event_task = jr["task"]
            if event_task and event_task != s["task"]:
                continue
            if (
                not event_task
                and not e["subject_id"].startswith("workbench:")
                and s["task"] != ml.TASK
            ):
                continue
            activity.append(e)
        activity = activity[:30]
        if mid:
            try:
                report = research_views.compare(store, mid, window)
                comparison = [
                    dict(
                        id=r["model_id"] + ":" + r["algorithm"],
                        name=next(
                            (m["name"] for m in mm if m["id"] == r["model_id"]),
                            "历史基线",
                        ),
                        score=r["scores"],
                        n=r["scores"]["n"],
                    )
                    for r in report["rows"]
                ]
                comparison_notice = (
                    report["start"]
                    + " 至 "
                    + report["end"]
                    + " · 同一数据版本与有效时段"
                )
                selected = ml.get_object(store, mid, "model")["payload"]
                reference = selected["policy"].get(
                    "initial_baseline", "seasonal_naive_d2"
                )
                ci = report["report"].get("comparisons", {}).get(reference)
                if selected["algorithm"] == "ridge" and ci:
                    comparison_notice += " · " + comparison_evidence(ci, s["unit"])
            except ValueError as exc:
                comparison_notice = str(exc)
        flow = [
            dict(
                name="原始数据",
                state=(
                    "archived"
                    if store.db.execute(
                        "SELECT 1 FROM ml_source_registry WHERE source_hash=?",
                        (metadata["source_hash"],),
                    ).fetchone()
                    else "pending"
                ),
                detail="按版本保留历史文件",
            ),
            dict(
                name="训练与模型",
                state=(
                    "succeeded"
                    if mid
                    and next((m["can_predict"] for m in mm if m["id"] == mid), False)
                    else "pending"
                ),
                detail="使用冻结训练数据和已保存权重",
            ),
            dict(
                name="预测记录",
                state="succeeded" if saved else "pending",
                detail=(
                    f"已保存{len(points)}点预测"
                    if saved
                    else "当前日期尚无所选模型的预测"
                ),
            ),
            dict(
                name="实际值核对",
                state="matched" if obs else "pending",
                detail=(
                    f"{obs['payload']['observed_points']} 个有效实际值"
                    if obs
                    else "等待核对"
                ),
            ),
            dict(
                name="人工复核",
                state=(
                    "confirmed"
                    if any(c["state"] == "confirmed" for c in cases)
                    else "pending"
                ),
                detail=f"{sum(bool(c['feedback_id']) for c in cases)} 条复核记录",
            ),
        ]
    else:
        # Use the same source/date cutoff as points, independently of UI routes.
        cut = (
            instant(f"{day}T{until}:00+08:00")
            if mode == "replay"
            else data_clock(store, s["source_mode"])
        )
        outputs = {
            r["id"]: {
                v["target_start"]: v["value"]
                for v in rows(
                    store,
                    "SELECT target_start,value FROM prediction_value WHERE run_id=?",
                    (r["id"],),
                )
            }
            for r in rr
        }
        common = [
            p
            for p in points
            if p["actual"] is not None
            and outputs
            and all(values.get(p["start"]) is not None for values in outputs.values())
        ]
        for r in rr:
            score = ml.scores(
                np.array([p["actual"] for p in common]),
                np.array([outputs[r["id"]][p["start"]] for p in common]),
            )
            comparison.append(
                dict(id=r["id"], name=r["name"], score=score, n=len(common))
            )
        comparison_notice = day + " · 同一场站、查询时点与有效实际值"
        native = rsi_overview(
            store,
            s["station_id"],
            day,
            s["source_mode"],
            cut if mode == "replay" else now(),
        )
        activity = [
            dict(
                subject_id=e["model_version_id"],
                display_name=next(
                    (m["name"] for m in mm if m["id"] == e["model_version_id"]),
                    "模型审核",
                ),
                state=e["to_status"],
                created_at=e["created_at"],
                detail={"reason": e["reason"]},
            )
            for e in native["lifecycle"][:30]
        ]
        for e in research_views.event_history(store, 150):
            if (
                e["subject_id"] == "workbench:" + s["key"]
                and e["detail"].get("date") == day
            ):
                e["display_name"] = e["detail"].get("stage", "业务操作")
                activity.append(e)
        activity = sorted(activity, key=lambda e: e["created_at"], reverse=True)[:30]
        flow = [
            dict(
                name="原始数据",
                state="succeeded" if points else "pending",
                detail=f"实际观测 {sum(p['actual'] is not None for p in points)} / 96 个时段",
            ),
            dict(
                name="模型与预测",
                state=(
                    "succeeded"
                    if any(p["predicted"] is not None for p in points)
                    else "pending"
                ),
                detail=(
                    "合成参考，不等于正式训练"
                    if s["source_mode"] == "synthetic"
                    else "按已登记模型与可见数据处理"
                ),
            ),
            dict(
                name="实际值核对",
                state="matched" if paired else "pending",
                detail=f"{len(paired)} 个配对实际值",
            ),
            dict(
                name="人工复核",
                state=(
                    "confirmed"
                    if any(c["state"] == "confirmed" for c in cases)
                    else "pending"
                ),
                detail=f"{sum(bool(c['feedback_id']) for c in cases)} 条已复核 / {len(cases)} 个可核对时段",
            ),
        ]
    related = []
    if s["domain"] == "market" and mid:
        model = ml.get_object(store, mid, "model")
        if model["payload"]["algorithm"] == "ridge":
            audit = store.db.execute(
                "SELECT audit_id FROM ml_audits WHERE model_version_id=? ORDER BY created_at DESC LIMIT 1",
                (mid,),
            ).fetchone()
            if audit:
                reference = model["payload"]["policy"].get(
                    "initial_baseline", "seasonal_naive_d2"
                )
                ci = ml.get_object(store, audit[0], "audit")["payload"]["report"][
                    "final_audit"
                ]["comparisons"].get(reference)
                if ci and (ci.get("upper95") is None or ci["upper95"] >= 0):
                    s["notice"] += " 最终窗口：" + comparison_evidence(ci, s["unit"])
        job = ml.job(store, model["payload"]["job_id"])
        proposal_id = job["config"].get("proposal_id")
        proposals = [
            p for p in ml.objects(store, "proposal") if p["payload"]["model_id"] == mid
        ]
        if proposal_id:
            proposals = [ml.get_object(store, proposal_id, "proposal")] + proposals
        follow_job = None
        if proposals:
            proposal = proposals[0]
            feedback = ml.get_object(
                store, proposal["payload"]["feedback_id"], "feedback"
            )
            parent = ml.get_object(store, feedback["payload"]["model_id"], "model")
            related.append(
                dict(
                    name="查看重训复核依据",
                    date=feedback["payload"]["date"],
                    model=parent["id"],
                    record=feedback["parent_id"],
                    slot=feedback["payload"]["slot"],
                    tab="rsi",
                )
            )
            jr = store.db.execute(
                "SELECT job_id FROM ml_job WHERE json_extract(config_json,'$.proposal_id')=? ORDER BY rowid DESC LIMIT 1",
                (proposal["id"],),
            ).fetchone()
            if jr:
                follow_job = ml.job(store, jr[0])
        flow.extend(
            [
                dict(
                    name="重训复核依据",
                    state="confirmed" if proposals else "pending",
                    detail=(
                        (
                            feedback["payload"]["date"]
                            + " · "
                            + feedback["payload"]["actor"]
                        )
                        if proposals
                        else "从调参窗口核对预测与原始标签后提交提案"
                    ),
                ),
                dict(
                    name="重训作业",
                    state=follow_job["state"] if follow_job else "pending",
                    detail=(
                        follow_job["display_name"]
                        if follow_job
                        else "尚未提交关联重训作业"
                    ),
                ),
                dict(
                    name="同口径评估",
                    state="evaluated",
                    detail=str(model["payload"]["report"]["promotion"]["rows"])
                    + " 个共同样本；"
                    + model["payload"]["splits"]["promotion"][0]
                    + " 至 "
                    + model["payload"]["splits"]["promotion"][1],
                ),
                dict(
                    name="研究版本决定",
                    state=model["state"],
                    detail="只变更研究版本；不会冒充场站生产发布",
                ),
            ]
        )
    context_version = ml.digest(
        dict(
            source=key,
            task=s["task"],
            observation=obs["id"] if obs else None,
            date=day,
            model=mid,
            record=rid,
            mode=mode,
            until=until,
            basis=basis,
            points=points,
        )
    )
    return dict(
        source=s,
        date=day,
        model_id=mid,
        record_id=rid,
        context_version=context_version,
        models=mm,
        records=rr,
        points=points,
        metrics=scored,
        cases=cases,
        jobs=jobs,
        activity=activity,
        comparison=comparison,
        comparison_notice=comparison_notice,
        flow=flow,
        metadata=metadata,
        related=related,
        checked_at=now(),
        capabilities=dict(
            train=s["can_train"],
            predict=any(m["can_predict"] for m in mm),
            snapshot_actual=s["domain"] == "market",
            formal_production=False,
            analysis_mode=(
                "openai_compatible_evidence_summary"
                if load_settings().ready
                else "deterministic_tools_only"
            ),
        ),
    )


@router.get("/context")
def get_context(
    source_key: str = "market:shandong",
    trading_date: Date | None = None,
    model_id: str | None = None,
    record_id: str | None = None,
    mode: Literal["live", "post", "replay"] = "post",
    until: str = "23:59",
    basis: Literal["latest", "snapshot"] = "latest",
    window: Literal["tune", "promotion", "final_audit"] = "promotion",
    task_id: str | None = None,
    store: Store = Depends(store_dep),
):
    try:
        datetime.strptime(until, "%H:%M")
    except ValueError:
        raise ValueError("请选择有效的查看时间") from None
    return context(
        store,
        source_key,
        trading_date.isoformat() if trading_date else None,
        model_id,
        record_id,
        mode,
        until,
        basis,
        window,
        task_id=task_id,
    )


@router.get("/scenario")
def scenario(
    source_key: str,
    trading_date: Date,
    quantity: float = Query(default=1, ge=0, le=1000000, allow_inf_nan=False),
    fee: float = Query(default=0, ge=0, le=1000000, allow_inf_nan=False),
    bid_ratio: float = Query(default=1, ge=0, le=1.5, allow_inf_nan=False),
    mode: Literal["live", "post", "replay"] = "post",
    until: str = "23:59",
    model_id: str | None = None,
    record_id: str | None = None,
    basis: Literal["latest", "snapshot"] = "latest",
    expected_version: str = "",
    task_id: str | None = None,
    store: Store = Depends(store_dep),
):
    s = source(store, source_key, task_id)
    day = trading_date.isoformat()
    if day not in s["dates"]:
        raise ValueError("测算日期不属于当前范围")
    view = context(
        store, source_key, day, model_id, record_id, mode, until, basis, task_id=task_id
    )
    if expected_version and expected_version != view["context_version"]:
        raise ValueError("数据已更新，请检查更新后重新测算")
    points = view["points"]
    paired = [
        p for p in points if p["da_price"] is not None and p["rt_price"] is not None
    ]
    value = (
        sum(quantity * (p["rt_price"] - p["da_price"] - fee) for p in paired)
        if paired
        else None
    )
    plans = []
    if s["domain"] == "station":
        from .trading import trading_overview
        from .api import resolve_scope

        scope = station_scope(s, day, mode, until)
        result = trading_overview(
            store, s["station_id"], day, s["source_mode"], view["metadata"]["cutoff_at"]
        )
        plans = [
            dict(
                name=p["plan_name"],
                value=p["net_revenue_yuan"],
                settled=p["settled_count"],
            )
            for p in result.get("plans", [])
        ]
    from .public_settlement import calculate

    settlement = (
        calculate(store, view, bid_ratio, fee) if s["domain"] == "market" else None
    )
    history = []
    for obj in ml.objects(store, "scenario", 100):
        p = obj["payload"]
        if (
            p.get("source_key") == source_key
            and p.get("task") == s["task"]
            and p.get("date") == day
        ):
            history.append(
                dict(
                    name=obj["display_name"],
                    model_name=ml.get_object(store, p["model_id"], "model")[
                        "display_name"
                    ],
                    created_at=obj["created_at"],
                    value=p["result"]["value"],
                    delta=p["result"]["delta"],
                    intervals=p["result"]["settled_intervals"],
                    bid_ratio=p["bid_ratio"],
                    fee=p["fee"],
                    current_observation=obj["source_hash"]
                    == view["metadata"].get("source_hash"),
                )
            )
    return dict(
        available=bool(paired),
        quantity=quantity,
        value=value,
        points=len(paired),
        plans=plans,
        settlement=settlement,
        history=history,
        notice="价差情景只按每个有效时段的假设电量计算，不代表场站真实收益。已登记场站方案的结算结果另行列出。",
    )


@router.get("/history")
def history(
    source_key: str,
    trading_date: Date,
    days: int = Query(default=14, ge=3, le=31),
    mode: Literal["live", "post", "replay"] = "post",
    until: str = "23:59",
    model_id: str | None = None,
    record_id: str | None = None,
    basis: Literal["latest", "snapshot"] = "latest",
    expected_version: str = "",
    task_id: str | None = None,
    store: Store = Depends(store_dep),
):
    s = source(store, source_key, task_id)
    day = trading_date.isoformat()
    if day not in s["dates"]:
        raise ValueError("历史范围不属于当前数据来源")
    view = context(
        store, source_key, day, model_id, record_id, mode, until, basis, task_id=task_id
    )
    if expected_version and expected_version != view["context_version"]:
        raise ValueError("数据已更新，请检查更新后重新查看历史")
    frozen = (
        data_flow.source_version(store, view["metadata"]["source_hash"])
        if s["domain"] == "market"
        else None
    )
    dates = [d for d in (frozen[1] if frozen else s["dates"]) if d <= day][-days:]
    points = []
    for d in dates:
        if s["domain"] == "market":
            rows_for_day, _, _, _ = snapshot(
                store,
                s,
                d,
                mode=mode if d == day else "post",
                until=until,
                source_dataset=frozen,
            )
        else:
            intervals, _ = station_intervals(
                store,
                s,
                d,
                mode,
                until,
                view["metadata"]["cutoff_at"],
            )
            rows_for_day = [
                dict(start=p["interval_start"], actual=p["actual_mw"])
                for p in intervals
            ]
        points.extend(dict(start=p["start"], actual=p["actual"]) for p in rows_for_day)
    y = np.array([p["actual"] for p in points], dtype=float)
    valid = np.isfinite(y)
    sums = np.r_[0, np.cumsum(np.where(valid, y, 0))]
    counts = np.r_[0, np.cumsum(valid)]
    period = len(tasks.slots(s["task"])) if s["domain"] == "market" else 96
    end = np.arange(len(y)) + 1
    begin = np.maximum(0, end - period)
    n = counts[end] - counts[begin]
    trend = np.divide(
        sums[end] - sums[begin], n, out=np.full(len(y), np.nan), where=n >= period // 2
    )
    available = int(valid.sum()) >= 3 * period
    seasonal = np.full(len(y), np.nan)
    if available:
        for slot in range(96):
            indices = [
                i
                for i, p in enumerate(points)
                if (
                    datetime.fromisoformat(p["start"].replace("Z", "+00:00"))
                    .astimezone(public_data.TZ)
                    .hour
                    * 4
                    + datetime.fromisoformat(p["start"].replace("Z", "+00:00")).minute
                    // 15
                )
                == slot
            ]
            residual = y[indices] - trend[indices]
            values = residual[np.isfinite(residual)]
            if len(values):
                seasonal[indices] = np.median(values)
    for i, p in enumerate(points):
        p.update(
            trend=float(trend[i]) if np.isfinite(trend[i]) else None,
            seasonal=float(seasonal[i]) if np.isfinite(seasonal[i]) else None,
            residual=(
                float(y[i] - trend[i] - seasonal[i])
                if np.isfinite(y[i] - trend[i] - seasonal[i])
                else None
            ),
        )
    return dict(
        source_key=source_key,
        unit=s["unit"],
        points=points,
        decomposition_available=available,
        notice="历史描述不参与预测输入。"
        + (
            "有效实际值不足三个完整日周期，暂不展示周期和剩余项。"
            if not available
            else "趋势、同时段周期和剩余项均取自当前来源的历史实际值。"
        ),
    )


@router.get("/export")
def export(
    source_key: str,
    trading_date: Date,
    model_id: str,
    record_id: str,
    mode: Literal["live", "post", "replay"] = "post",
    until: str = "23:59",
    basis: Literal["latest", "snapshot"] = "latest",
    expected_version: str = "",
    task_id: str | None = None,
    store: Store = Depends(store_dep),
):
    c = context(
        store,
        source_key,
        trading_date.isoformat(),
        model_id,
        record_id,
        mode,
        until,
        basis,
        task_id=task_id,
    )
    if expected_version and expected_version != c["context_version"]:
        raise ValueError("数据已更新，请检查更新后重新导出")
    name = next(m["name"] for m in c["models"] if m["id"] == c["model_id"])
    output = [
        {
            "数据范围": c["source"]["name"],
            "日期": c["date"],
            "时段": datetime.fromisoformat(p["start"].replace("Z", "+00:00"))
            .astimezone(public_data.TZ)
            .strftime("%H:%M"),
            "模型": name,
            "单位": c["source"]["unit"],
            "预测值": p["predicted"],
            "实际值": p["actual"],
            "实际值口径": "预测保存快照" if basis == "snapshot" else "查询时点观测",
        }
        for p in c["points"]
    ]
    if not output:
        raise ValueError("当前范围暂无可导出的预测")
    return research_views.csv_response(
        "prediction-" + c["date"], list(output[0]), output
    )


@router.get("/reviews")
def review_history(
    source_key: str,
    trading_date: Date,
    mode: Literal["live", "post", "replay"] = "post",
    until: str = "23:59",
    task_id: str | None = None,
    store: Store = Depends(store_dep),
):
    s = source(store, source_key, task_id)
    day = trading_date.isoformat()
    if day not in s["dates"]:
        raise ValueError("复核日期不属于当前数据范围")
    result = []
    cutoff = instant(f"{day}T{until}:00+08:00") if mode == "replay" else now()
    if s["domain"] == "market":
        for f in ml.objects(store, "feedback", 10000):
            p = f["payload"]
            if p["date"] != day or f["created_at"] > cutoff:
                continue
            try:
                m = owned_model(store, s, p["model_id"])
            except ValueError:
                continue
            result.append(
                dict(
                    id=f["id"],
                    model_id=m["id"],
                    record_id=f["parent_id"],
                    name=m["name"],
                    slot=p["slot"],
                    reason=p["reason"],
                    actor=p["actor"],
                    created_at=f["created_at"],
                    state=f["state"],
                    notice="绑定所保存的预测和观测，不代表更新后的实际值已经复核。",
                )
            )
        for f in public_data.history(store, None, day)["runs"]:
            if f["kind"] != "review" or f["created_at"] > cutoff:
                continue
            result.append(
                dict(
                    id=f["run_id"],
                    model_id=None,
                    record_id=None,
                    name="原始市场数据复核",
                    slot=f["scope"].get("selected_slot"),
                    reason=f["answer_text"],
                    actor="历史记录",
                    created_at=f["created_at"],
                    state="completed",
                    notice="保留原数据版本快照；这条记录未关联模型预测。",
                )
            )
    else:
        start, end = day_bounds(day)
        for f in rows(
            store,
            "SELECT f.*,r.run_id,r.model_version_id,p.target_start,m.model_name,m.version FROM review_feedback f JOIN prediction_value p USING(prediction_id) JOIN prediction_run r USING(run_id) JOIN model_version m USING(model_version_id) WHERE r.station_id=? AND r.source_mode=? AND r.task=? AND p.target_start>=? AND p.target_start<? AND f.created_at<=? ORDER BY f.rowid DESC LIMIT 100",
            (s["station_id"], s["source_mode"], s["task"], start, end, cutoff),
        ):
            t = datetime.fromisoformat(
                f["target_start"].replace("Z", "+00:00")
            ).astimezone(public_data.TZ)
            binding = (
                ml.state(store, f["feedback_id"])["state"]
                == "workbench_review_snapshot"
            )
            result.append(
                dict(
                    id=f["feedback_id"],
                    model_id=f["model_version_id"],
                    record_id=f["run_id"],
                    name=native_label(f["model_name"], f["version"]),
                    slot=t.hour * 4 + t.minute // 15,
                    reason=f["reason"],
                    actor=f["reviewer_id"],
                    created_at=f["created_at"],
                    state=f["status"],
                    notice=(
                        "已绑定复核时的实际值与预测值。"
                        if binding
                        else "既有复核未保存独立观测绑定；保留历史意见，当前实际值需重新核对。"
                    ),
                )
            )
    return dict(
        records=sorted(result, key=lambda r: r["created_at"], reverse=True)[:100]
    )


@router.get("/prediction-details")
def prediction_details(
    source_key: str,
    trading_date: Date,
    model_id: str,
    record_id: str,
    confidence: float = Query(default=0.95),
    task_id: str | None = None,
    store: Store = Depends(store_dep),
):
    s = source(store, source_key, task_id)
    owned_record(store, s, record_id, trading_date.isoformat(), model_id)
    if s["domain"] != "market":
        return dict(
            explanation=None,
            notice="当前场站模型没有已核验的线性项解释记录，不制造模型解释。",
        )
    d = research_views.prediction_details(record_id, confidence, store)
    return dict(
        explanation=d["explanation"],
        unit=s["unit"],
        range=d.get("range"),
        notice=d["notice"],
        explanation_unavailable=d.get("explanation_unavailable"),
        range_unavailable=d.get("range_unavailable"),
    )


class Command(BaseModel):
    model_config = ConfigDict(extra="forbid")
    action: Literal[
        "predict",
        "train",
        "feedback",
        "confirm",
        "proposal",
        "approve",
        "rollback",
        "reject",
        "shadow",
        "analyze",
        "cancel",
        "retry",
        "final_audit",
        "scenario",
    ]
    source_key: str
    task_id: str | None = None
    date: Date
    model_id: str | None = None
    record_id: str | None = None
    case_id: str | None = None
    feedback_id: str | None = None
    job_id: str | None = None
    actor: str = Field(min_length=1, max_length=100)
    reason: str = Field(min_length=1, max_length=4000)
    slot: int = Field(default=0, ge=0, le=95)
    alpha: float = Field(default=1, allow_inf_nan=False)
    key: str = Field(default="", max_length=100)
    mode: Literal["live", "post", "replay"] = "post"
    until: str = "23:59"
    basis: Literal["latest", "snapshot"] = "latest"
    confirmed: bool = False
    context_version: str = ""
    bid_ratio: float = Field(default=1, ge=0, le=1.5, allow_inf_nan=False)
    fee: float = Field(default=0, ge=0, le=1000000, allow_inf_nan=False)

    @field_validator("until")
    @classmethod
    def valid_until(cls, value):
        datetime.strptime(value, "%H:%M")
        return value


@router.post("/commands")
def command(b: Command, request: Request, store: Store = Depends(store_dep)):
    origin = request.headers.get("origin")
    if origin and urlsplit(origin).netloc != request.headers.get("host"):
        raise HTTPException(403, "请从本站操作")
    if not b.actor.strip() or not b.reason.strip():
        raise ValueError("请填写操作人与依据")
    s = source(store, b.source_key, b.task_id)
    day = b.date.isoformat()
    if day not in s["dates"]:
        raise ValueError("日期不属于当前数据范围")
    m = owned_model(store, s, b.model_id) if b.model_id else None
    if b.record_id:
        owned_record(store, s, b.record_id, day, b.model_id, b.mode, b.until)
    operation = str(uuid4())
    labels = {
        "predict": "运行预测",
        "train": "提交训练",
        "feedback": "保存复核",
        "confirm": "确认复核",
        "proposal": "提交重训提案",
        "approve": "审核模型",
        "rollback": "回滚版本",
        "reject": "拒绝候选",
        "shadow": "保留观察版本",
        "analyze": "分析数据",
        "cancel": "取消任务",
        "retry": "重试任务",
        "final_audit": "执行最终评估",
        "scenario": "保存量价测算",
    }
    details = dict(
        operation=operation,
        task_id=s["task"],
        source_key=b.source_key,
        actor=b.actor,
        reason=b.reason,
        date=day,
        model_id=b.model_id,
        record_id=b.record_id,
        stage=labels[b.action],
    )
    ml.event(store, "workbench:" + b.source_key, "submitted", **details)
    store.db.commit()
    try:
        result = execute_command(b, request, store, s, day, m)
    except Exception:
        store.db.rollback()
        ml.event(store, "workbench:" + b.source_key, "failed", **details)
        store.db.commit()
        raise
    ml.event(store, "workbench:" + b.source_key, "succeeded", **details)
    store.db.commit()
    return result


def execute_command(b, request, store, s, day, m):
    if b.action == "scenario":
        view = context(
            store,
            b.source_key,
            day,
            b.model_id,
            b.record_id,
            b.mode,
            b.until,
            b.basis,
            task_id=b.task_id,
        )
        if not b.context_version or b.context_version != view["context_version"]:
            raise ValueError("观测已变化，请重新核对测算范围")
        from .public_settlement import calculate

        result = calculate(store, view, b.bid_ratio, b.fee)
        if not result or not result["settled_intervals"]:
            raise ValueError("请选择有完整小时观测的区域光伏日前预测记录")
        sha = view["metadata"]["source_hash"]
        oid = ml.add_object(
            store,
            "scenario",
            dict(
                source_key=b.source_key,
                task=s["task"],
                date=day,
                model_id=view["model_id"],
                record_id=view["record_id"],
                source_revision_id=data_flow.revision_id(sha),
                context_version=view["context_version"],
                actor=b.actor,
                reason=b.reason,
                bid_ratio=b.bid_ratio,
                fee=b.fee,
                result=result,
                evidence_snapshot=view["points"],
                source_mode="public_reference",
                production_eligible=False,
            ),
            sha,
            view["record_id"],
        )
        ml.event(store, oid, "succeeded", source_key=b.source_key, task_id=s["task"])
        store.db.commit()
        return dict(id=oid, result=result)
    if b.action == "predict":
        if not m or not m["can_predict"]:
            raise ValueError("当前模型没有可执行的预测能力")
        if s["domain"] == "market":
            result = ml.prediction(
                store,
                m["id"],
                day,
                ml.get_object(store, m["id"], "model")["payload"]["splits"]["tune"][0]
                <= day
                <= ml.get_object(store, m["id"], "model")["payload"]["splits"]["tune"][
                    1
                ],
                public_data.dataset()[0]["source_hash"],
            )
            data_flow.reconcile(store, result["source_hash"])
            return result
        scope = station_scope(s, day, b.mode, b.until)
        from .api import resolve_scope

        r = run_model_inference(
            store,
            model_version_id=m["id"],
            station_id=s["station_id"],
            trading_date=day,
            source_mode=s["source_mode"],
            cutoff_at=resolve_scope(scope, store),
            registry_cutoff=scope.cutoff_at if b.mode == "replay" else now(),
            persist=True,
        )
        return dict(id=r["persisted_run_id"], model_id=m["id"], date=day)
    if b.action == "train":
        if not s["can_train"]:
            raise ValueError("此数据范围尚未配置正式训练协议，不能使用市场电价协议代替")
        if not b.key:
            raise ValueError("训练提交缺少请求凭据，请刷新后重试")
        ds = ml.register_dataset(
            store, public_data.dataset()[0]["source_hash"], s["task"]
        )
        return ml.submit(store, ds["id"], b.alpha, b.key)
    if b.action in {"cancel", "retry"}:
        if s["domain"] != "market" or not b.job_id:
            raise ValueError("当前来源没有对应的后台训练任务")
        j = ml.job(store, b.job_id)
        ds = store.db.execute(
            "SELECT task FROM ml_dataset_registry WHERE dataset_id=?",
            (j["dataset_id"],),
        ).fetchone()
        if not ds or ds["task"] != s["task"]:
            raise ValueError("任务不属于当前数据范围")
        from .learning_api import (
            Command as LearningCommand,
            command as learning_command,
        )

        return learning_command(
            LearningCommand(
                action=b.action,
                object_id=b.job_id,
                actor=b.actor,
                reason=b.reason,
                idempotency_key=b.key,
            ),
            request,
            store,
        )
    if b.action == "final_audit":
        if s["domain"] != "market" or not m or not b.confirmed:
            raise ValueError("请明确确认冻结所选研究候选并使用一次性最终评估资格")
        return ml.final_audit(store, m["id"], b.actor, b.reason)
    if b.action == "feedback":
        if not b.confirmed:
            raise ValueError("请先确认已经核对所选时段的原始数据")
        view = context(
            store,
            b.source_key,
            day,
            b.model_id,
            b.record_id,
            b.mode,
            b.until,
            b.basis,
            task_id=b.task_id,
        )
        if not b.context_version or b.context_version != view["context_version"]:
            raise ValueError("所选预测或实际值已变化，请重新核对后保存")
        if s["domain"] == "market":
            if not b.record_id:
                raise ValueError("先选择一条已保存预测")
            if not any(p["slot"] == b.slot for p in view["cases"]):
                raise ValueError("当前查看时点没有这个时段的可复核实际值")
            case = next(p for p in view["cases"] if p["slot"] == b.slot)
            feedback = ml.feedback(
                store, b.record_id, b.slot, b.actor, b.reason, case["observation_id"]
            )
            return ml.confirm_feedback(store, feedback["id"], b.actor, b.reason)
        if not b.record_id:
            raise ValueError("请先选择一条当前范围的预测记录")
        points, _, _, _ = snapshot(
            store, s, day, b.model_id, b.record_id, b.mode, b.until, b.basis
        )
        cases = review_cases(
            store, s, day, points, None, None, b.mode, b.until, b.record_id
        )
        c = next((c for c in cases if c["id"] == b.case_id), None)
        if not c:
            raise ValueError("复核记录不属于当前场站、日期与数据口径")
        if c["slot"] != b.slot:
            raise ValueError("所选复核时段不匹配")
        if c["id"].startswith("slot:"):
            from .storage import digest

            cid = (
                "case-"
                + digest(
                    dict(
                        record=b.record_id,
                        slot=c["slot"],
                        actual=c["actual"],
                        predicted=c["predicted"],
                        observation_key=c["observation_key"],
                    )
                )[:32]
            )
            store.append(
                "deviation_case",
                dict(
                    case_id=cid,
                    station_id=s["station_id"],
                    prediction_run_id=b.record_id,
                    interval_start=c["start"],
                    interval_end=instant(
                        datetime.fromisoformat(c["start"].replace("Z", "+00:00"))
                        + timedelta(minutes=15)
                    ),
                    predicted_value=c["predicted"],
                    actual_value=c["actual"],
                    error_value=c["actual"] - c["predicted"],
                    severity="medium",
                    auto_clues_json=json.dumps(
                        {
                            "note": "人工核对所选预测与当前实际值",
                            "observation_key": c["observation_key"],
                        }
                    ),
                    status="pending_review",
                    source_mode=s["source_mode"],
                    created_at=now(),
                ),
            )
            c["id"] = cid
        r = review_feedback(store, c["id"], b.reason, False, b.actor)
        ml.event(
            store,
            r["feedback_id"],
            "workbench_review_snapshot",
            source_key=s["key"],
            case_id=c["id"],
            record_id=b.record_id,
            slot=c["slot"],
            actual=c["actual"],
            predicted=c["predicted"],
            observation_key=c["observation_key"],
            mode=b.mode,
            until=b.until,
            observed_at=now(),
        )
        store.db.commit()
        return r
    if b.action in {"confirm", "proposal"}:
        if s["domain"] != "market" or not b.feedback_id:
            raise ValueError("当前来源没有对应研究重训提案")
        f = ml.get_object(store, b.feedback_id, "feedback")
        if b.record_id and f["parent_id"] != b.record_id:
            raise ValueError("复核意见不属于所选预测记录")
        owned_record(
            store, s, f["payload"]["prediction_id"], day, b.model_id, b.mode, b.until
        )
        if b.action == "confirm":
            return ml.confirm_feedback(store, f["id"], b.actor, b.reason)
        prop = ml.proposal(store, f["id"], b.alpha, b.actor, b.reason)
        return ml.train_proposal(store, prop["id"], b.key) if b.key else prop
    if b.action in {"approve", "rollback", "reject", "shadow"}:
        if not m:
            raise ValueError("请先选择模型")
        if s["domain"] == "market":
            return ml.release(
                store,
                m["id"],
                "activate" if b.action == "approve" else b.action,
                b.actor,
                b.reason,
            )
        if not m.get("candidate_id") or b.action in {"reject", "shadow"}:
            raise ValueError("当前模型没有可执行的此项审核操作")
        if b.action == "approve" and (
            not m["can_approve"] or m.get("approval_day") != day
        ):
            raise ValueError("模型的评估依据不属于当前场站和日期，不能在此范围审批")
        if b.action == "rollback" and not m["can_rollback"]:
            raise ValueError("该版本不是当前范围可回滚的已审核模型")
        # Candidate feedback must belong to this station when it has case evidence.
        c = store.db.execute(
            "SELECT * FROM iteration_candidate WHERE candidate_id=?",
            (m["candidate_id"],),
        ).fetchone()
        for fid in json.loads(c["feedback_ids_json"]):
            owner = store.db.execute(
                "SELECT r.station_id,r.source_mode FROM review_feedback f JOIN prediction_value p USING(prediction_id) JOIN prediction_run r USING(run_id) WHERE f.feedback_id=?",
                (fid,),
            ).fetchone()
            if owner and (
                owner["station_id"] != s["station_id"]
                or owner["source_mode"] != s["source_mode"]
            ):
                raise ValueError("该提案依据不属于当前场站和数据口径")
        r = approve_model(store, m["candidate_id"], b.action, b.reason, b.actor)
        store.db.commit()
        return r
    return analyze_context(store, b)


def analyze_context(store, b):
    from .model_settings import load_settings, select_evidence, ProviderError
    from .storage import digest

    c = context(
        store,
        b.source_key,
        b.date.isoformat(),
        b.model_id,
        b.record_id,
        b.mode,
        b.until,
        b.basis,
        task_id=b.task_id,
    )
    if b.context_version and b.context_version != c["context_version"]:
        raise ValueError("数据已更新，请重新核对后分析")
    m = next((m for m in c["models"] if m["id"] == c["model_id"]), None)
    n = c["metrics"]["n"]
    facts = [
        f"当前数据范围为{c['source']['name']}，日期{c['date']}，任务为{c['source']['task_name']}，单位{c['source']['unit']}。",
        f"所选模型为{m['name']}。" if m else "当前没有选择模型。",
        (
            f"当前有{n}个预测与实际值配对时段，平均绝对误差{c['metrics']['mae']:.3f}，均方根误差{c['metrics']['rmse']:.3f}。"
            if n
            else "当前没有有效的预测与实际值配对，不能计算误差。"
        ),
        c["source"]["notice"],
    ]
    for case in sorted(c["cases"], key=lambda p: abs(p["error"]), reverse=True)[:3]:
        facts.append(
            f"{case['slot']//4:02d}:{case['slot']%4*15:02d}时段，实际{case['actual']:.3f}，预测{case['predicted']:.3f}。仅凭偏差不能确认气象或设备根因。"
        )
    cfg = load_settings()
    failure = None
    indices = list(range(len(facts)))
    mode = "deterministic_tools_only"
    if cfg.ready:
        mode = "openai_compatible_evidence_summary"
        try:
            indices = select_evidence(cfg, facts, b.reason)
        except ProviderError as exc:
            failure = exc.code
    answer = (
        "摘要服务暂不可用，当前数据与计算结果已保留。"
        if failure
        else "\n\n".join(facts[i] for i in indices)
    )
    sha = c.get("metadata", {}).get("source_hash") or digest(
        dict(source=b.source_key, date=c["date"], points=c["points"])
    )
    oid = ml.add_object(
        store,
        "analysis",
        dict(
            source_key=b.source_key,
            task=c["source"]["task"],
            source_mode=c["source"]["source_mode"],
            date=c["date"],
            model_id=c["model_id"],
            record_id=c["record_id"],
            question=b.reason,
            facts=facts,
            answer=answer,
            llm_mode=mode,
            provider_error=failure,
            context_version=c["context_version"],
            evidence_snapshot=dict(
                points=c["points"],
                metadata=c["metadata"],
                mode=b.mode,
                until=b.until,
                basis=b.basis,
            ),
        ),
        sha,
        c["record_id"] if c["source"]["domain"] == "market" else None,
    )
    ml.event(
        store,
        oid,
        "provider_failed" if failure else "succeeded",
        source_key=b.source_key,
    )
    store.db.commit()
    if failure:
        raise HTTPException(502, answer)
    return dict(
        id=oid,
        answer_markdown=answer,
        llm_mode=mode,
        context_version=c["context_version"],
    )
