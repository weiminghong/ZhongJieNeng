"""Source-owned confirmed cases and deterministic evidence tools for one workspace.

Cases preserve observations and declared opinions. They never become labels or
causal ground truth, and source revisions are not silently pooled for retrieval.
"""

from collections import Counter
from datetime import datetime
import json
import math

from . import learning as ml, public_data
from .agent_service import terms, search_knowledge_rag
from .storage import instant
from .serving import now, build_intervals


NOTICE = "仅检索当前来源、任务及可见时点的已确认意见；意见不改写标签，不代表因果已经验证，也不自动触发重训。"


def knowledge_cutoff(view, mode, until):
    return instant(f"{view['date']}T{until}:00+08:00") if mode == "replay" else now()


def save_case(store, view, feedback_id, slot):
    """Idempotently archive a confirmed review, after verifying its exact binding."""
    source = view["source"]
    point = next((p for p in view["points"] if p["slot"] == slot), None)
    if not point or point["actual"] is None or point["predicted"] is None:
        raise ValueError("当前范围没有可沉淀的预测与实际值配对")
    if source["domain"] == "market":
        review = ml.get_object(store, feedback_id, "feedback")
        p = review["payload"]
        expected_observation = next(
            (c.get("observation_id") for c in view["cases"] if c["slot"] == slot), None
        )
        if (review["state"] != "confirmed" or p["prediction_id"] != view["record_id"]
                or p["slot"] != slot or p.get("observation_id") != expected_observation
                or p["point"]["actual"] != point["actual"]
                or p["point"]["predicted"] != point["predicted"]):
            raise ValueError("复核意见与当前预测或观测版本不一致，请重新核对")
        actor, reason = p["actor"], p["reason"]
        parent = feedback_id
    else:
        review = store.db.execute(
            "SELECT * FROM review_feedback WHERE feedback_id=? AND status='confirmed'",
            (feedback_id,),
        ).fetchone()
        binding = ml.state(store, feedback_id)
        p = binding["detail"]
        if (not review or binding["state"] != "workbench_review_snapshot"
                or p.get("source_key") != source["key"]
                or p.get("record_id") != view["record_id"] or p.get("slot") != slot
                or p.get("observation_key") != point["observation_key"]
                or p.get("actual") != point["actual"]
                or p.get("predicted") != point["predicted"]):
            raise ValueError("既有意见没有匹配当前观测的确认快照，请重新复核")
        actor, reason = review["reviewer_id"], review["reason"]
        parent = None
    oid = "knowledge_" + ml.digest(dict(feedback=feedback_id, scope=source["key"]))[:32]
    if store.db.execute("SELECT 1 FROM ml_object WHERE object_id=?", (oid,)).fetchone():
        return ml.get_object(store, oid, "knowledge_case")
    model = next((m for m in view["models"] if m["id"] == view["model_id"]), None)
    sha = view["metadata"].get("source_hash") or ml.digest(
        dict(source=source["key"], date=view["date"], observation=point["observation_key"])
    )
    payload = dict(
        source_key=source["key"], source_mode=source["source_mode"], task=source["task"],
        source_name=source["name"], task_name=source["task_name"], unit=source["unit"],
        source_hash=view["metadata"].get("source_hash"), date=view["date"],
        record_id=view["record_id"], model_id=view["model_id"],
        model_name=model["name"] if model else "所选模型", feedback_id=feedback_id,
        slot=slot, start=point["start"], actual=point["actual"], predicted=point["predicted"],
        observation_key=point["observation_key"], context_version=view["context_version"],
        actor=actor, reason=reason, actor_verification="intranet_declared",
        evidence_kind="confirmed_observation_and_declared_opinion", training_eligible=False,
        production_eligible=False, notice=NOTICE,
    )
    ml.add_object(store, "knowledge_case", payload, sha, parent, oid)
    ml.event(store, oid, "confirmed_case_saved", feedback_id=feedback_id)
    return ml.get_object(store, oid, "knowledge_case")


def search_cases(store, view, question="", mode="post", until="23:59", limit=5):
    source = view["source"]
    cutoff = knowledge_cutoff(view, mode, until)
    candidates = []
    station_observations = {}
    for row in store.db.execute(
        "SELECT * FROM ml_object WHERE kind='knowledge_case' AND created_at<=? "
        "AND json_extract(payload_json,'$.source_key')=? "
        "AND json_extract(payload_json,'$.task')=? ORDER BY created_at DESC,rowid DESC",
        (cutoff, source["key"], source["task"]),
    ):
        p = json.loads(row["payload_json"])
        if p["source_mode"] != source["source_mode"]:
            continue
        if p["date"] > view["date"]:
            continue
        if source["domain"] == "market" and p.get("source_hash") != view["metadata"].get("source_hash"):
            continue
        if mode == "replay" and instant(p["start"]) > cutoff:
            continue
        # A different model's record cannot carry an old observation forward.
        if p["date"] == view["date"]:
            current = next((q for q in view["points"] if q["slot"] == p["slot"]), None)
            if not current or current["observation_key"] != p["observation_key"]:
                continue
        elif source["domain"] == "station":
            if p["date"] not in station_observations:
                intervals = build_intervals(store, source["station_id"], p["date"],
                                            view["metadata"]["cutoff_at"], source["source_mode"])
                station_observations[p["date"]] = {
                    q["interval_start"]: ml.digest([r for r in json.loads(q["lineage_refs_json"])
                                                    if r["table"] == "station_actual"])
                    for q in intervals
                }
            if station_observations[p["date"]].get(p["start"]) != p["observation_key"]:
                continue
        candidates.append(dict(id=row["object_id"], created_at=row["created_at"], **p,
                               snapshot_notice="引用复核当时保存的预测与观测快照，不表示该意见已被验证为因果。"))
    tokens = set(terms(question))
    counts = [Counter(terms(c["task_name"] + " 预测 实际 偏差 复核 " + c["reason"])) for c in candidates]
    ranked = []
    for c, words in zip(candidates, counts):
        score = sum((1 + math.log(words[t])) * math.log(1 + len(counts) / (1 + sum(t in x for x in counts)))
                    for t in tokens if t in words)
        if tokens and not score:
            continue
        ranked.append(dict(**c, relevance=score))
    return sorted(ranked, key=lambda c: (c["relevance"], c["created_at"]), reverse=True)[:limit]


def selected_point(view, slot):
    if slot is None:
        return None
    point = next((p for p in view["points"] if p["slot"] == slot), None)
    if point is None and view["source"]["domain"] == "market":
        from .task_catalog import spec
        if spec(view["source"]["task"])["hourly"]:
            point = next((p for p in view["points"] if p["slot"] // 4 == slot // 4), None)
    return point


def evidence_tools(store, view, question, mode="post", until="23:59", slot=None):
    """All numerical tools consume the same already-validated workspace snapshot."""
    source = view["source"]
    base = dict(context_version=view["context_version"], source_key=source["key"],
                task=source["task"], date=view["date"], record_id=view["record_id"], mode=mode, until=until)
    tools = []

    def call(name, output, summary):
        tools.append(dict(name=name, display_name=name, summary=summary, input=base, output=output))
        return output

    call("核对预测与实际值", dict(metrics=view["metrics"], points=view["points"]), f"当前范围有{view['metrics']['n']}个预测与实际配对时段，单位{source['unit']}。")
    point = selected_point(view, slot)
    if slot is not None and not point:
        raise ValueError("所选时段不属于当前任务时间网格")
    if point:
        selected_time = datetime.fromisoformat(point["start"].replace("Z", "+00:00")).astimezone(public_data.TZ).strftime("%H:%M")
        call("核对所选时段", point, f"所选时段{selected_time}，仅使用当前查看时点可见的预测、实际值与价格。")
    versions = view["comparison"] if mode != "replay" else []
    comparison_notice = (view["comparison_notice"] or "当前没有可比较的同口径评估。") if mode != "replay" else "回放不引用完整事后评估窗口，避免把游标之后的标签带入当前分析。"
    score_lines = [f"{v['name']}：{v['n']}个共同样本，平均绝对误差{v['score']['mae']:.3f}{source['unit']}"
                   for v in versions[:4] if v["score"].get("mae") is not None]
    call("比较同口径版本", dict(notice=comparison_notice, versions=versions), comparison_notice + ("；" + "；".join(score_lines) if score_lines else ""))
    worst = sorted(view["cases"], key=lambda p: abs(p["error"]), reverse=True)[:3]
    call("核对偏差线索", dict(cases=worst, notice="偏差只说明相关线索，因果须独立验证。"), f"核对{len(worst)}个较大偏差时段；仅凭偏差不能确认天气或设备根因。")
    call("检查数据完整性", dict(
        total=len(view["points"]), paired=view["metrics"]["n"],
        missing=sum(p["quality"] == "missing" for p in view["points"]),
        pending=sum(p["quality"] == "pending" for p in view["points"]),
    ), f"共有{len(view['points'])}个目标时段，缺测与未来待到分别保留，不以零替代。")
    if source["domain"] == "market" and source["task"] == "pv_day_ahead_reference":
        from .public_settlement import calculate
        try:
            result = calculate(store, view)
            call("核算同范围量价参考", result, f"按所选已保存预测及同版本观测核算{result['settled_intervals'] if result else 0}个完整时段；仅作历史研究沙盘。")
        except (ValueError, OSError) as exc:
            call("核算同范围量价参考", dict(status="unavailable", error=str(exc)), "当前范围的量价核算未完成；保留其他工具证据，不补造测算结果。")
    citations = []
    for c in search_cases(store, view, question, mode, until):
        citations.append(dict(
            id=c["id"], title=f"已确认复核 · {c['date']} {datetime.fromisoformat(c['start'].replace('Z','+00:00')).astimezone(public_data.TZ).strftime('%H:%M')}",
            date=c["date"], start=c["start"], source_name=c["source_name"], task_name=c["task_name"],
            actor=c["actor"], created_at=c["created_at"], kind="confirmed_case",
            text=f"复核当时保存的快照：预测 {c['predicted']:.3f}、实际 {c['actual']:.3f} {c['unit']}。声明复核人：{c['actor']}；意见：{c['reason']}。该意见不作为已经验证的因果或新增训练标签。",
        ))
    if source["domain"] == "station":
        for d in search_knowledge_rag(store, question, source["station_id"], knowledge_cutoff(view, mode, until), source["source_mode"]):
            # Legacy cases lack task/observation binding; only reference documents
            # may supplement the unified confirmed-case channel.
            if d["collection"] == "rsi_case":
                continue
            citations.append(dict(id=d["chunk_id"], title=d["title"], text=d["content_text"], kind="reference_document", created_at=d["created_at"]))
    call("检索同范围已确认案例与资料", dict(citations=citations, notice=NOTICE), f"检索到{len(citations)}条当前来源和可见时点内的案例或资料。" + NOTICE)
    return tools, citations
