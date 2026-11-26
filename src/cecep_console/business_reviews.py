"""Append-only business issue processing and matched-result verification."""

import json
from datetime import date
from urllib.parse import urlsplit

import numpy as np
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from . import learning as ml
from .learning_api import store_dep
from .storage import Store

router = APIRouter(prefix="/api/v1/business", tags=["business-reviews"])
CATEGORIES = dict(data="数据问题", event="运行事件", model="模型偏差", strategy="申报策略", unknown="原因待查")
STATES = dict(pending="待调查", in_progress="处理中", resolved="待验证", verified="已验证")


def owned_issue(store, oid, source_key, day):
    obj = ml.get_object(store, oid, "business_review_issue")
    if obj["payload"]["source_key"] != source_key or obj["payload"]["date"] != day:
        raise ValueError("处理事项不属于当前数据范围和日期")
    return obj


def display(store, obj):
    p, d = obj["payload"], obj["detail"]
    history = [dict(state=r["state"], state_name=STATES.get(r["state"], "处理记录"),
                    created_at=r["created_at"], **json.loads(r["payload_json"]))
               for r in store.db.execute("SELECT * FROM ml_event WHERE subject_id=? ORDER BY rowid", (obj["id"],))]
    return dict(id=obj["id"], name=f"{CATEGORIES[p['category']]} · {p['date']}",
                date=p["date"], plan_id=p["plan_id"], settlement_id=p["settlement_id"],
                slot=p["slot"], category=p["category"], category_name=CATEGORIES[p["category"]],
                reason=p["reason"], actor=p["actor"], state=obj["state"],
                state_name=STATES[obj["state"]], owner=d.get("owner", p["owner"]),
                evidence=d.get("evidence", ""), verification=d.get("verification"), history=history)


@router.get("/reviews")
def list_reviews(source_key: str, trading_date: date, plan_id: str | None = None,
                 store: Store = Depends(store_dep)):
    if plan_id:
        from .business_workflow import owned_plan
        owned_plan(store, plan_id, source_key, trading_date.isoformat())
    records = []
    for r in store.db.execute("SELECT object_id FROM ml_object WHERE kind='business_review_issue' "
                             "AND json_extract(payload_json,'$.source_key')=? "
                             "AND json_extract(payload_json,'$.date')=? ORDER BY rowid DESC",
                             (source_key, trading_date.isoformat())):
        obj = ml.get_object(store, r[0])
        if not plan_id or obj["payload"]["plan_id"] == plan_id:
            records.append(display(store, obj))
    return dict(records=records, categories=[dict(key=k, name=v) for k,v in CATEGORIES.items()],
                notice="处理意见与证据追加保存；已验证表示完成核对，改善与否由对照结果单独说明。")


class ReviewCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")
    action: str
    source_key: str
    date: date
    plan_id: str | None = None
    settlement_id: str | None = None
    issue_id: str | None = None
    slot: int | None = Field(default=None, ge=0, le=95)
    category: str = "unknown"
    actor: str = Field(min_length=1, max_length=100)
    reason: str = Field(min_length=1, max_length=4000)
    owner: str = Field(default="", max_length=100)
    evidence: str = Field(default="", max_length=6000)
    verification: dict | None = None


def verify_result(store, issue, selection):
    from .business_workflow import owned_settlement
    p = issue["payload"]
    if not selection or not selection.get("comparison_object_id"):
        raise ValueError("请选择实际保存的对照结果")
    oid = selection["comparison_object_id"]
    if selection.get("kind") == "settlement_comparison":
        if not p["settlement_id"] or oid == p["settlement_id"]:
            raise ValueError("请选择与原结算不同的同日结算记录")
        original = owned_settlement(store, p["settlement_id"], p["source_key"], p["date"])["payload"]
        new = owned_settlement(store, oid, p["source_key"], p["date"])["payload"]
        if original["observation_source_hash"] != new["observation_source_hash"]:
            raise ValueError("实际观测版本不同，不能把数据修订当作策略改善")
        if original.get("rule") != new.get("rule"):
            raise ValueError("结算规则不同，不能直接比较改善")
        old_hours = [h for h in original["hours"] if h.get("complete", True) and h.get("value") is not None]
        new_hours = [h for h in new["hours"] if h.get("complete", True) and h.get("value") is not None]
        if [h["hour"] for h in old_hours] != [h["hour"] for h in new_hours] or not old_hours:
            raise ValueError("结算时段不匹配，不能比较改善")
        for a, b in zip(old_hours, new_hours):
            for key in ("actual_mwh", "da_price", "rt_price"):
                if a.get(key) != b.get(key):
                    raise ValueError("结算实际出力或价格不一致，不能比较策略改善")
        before = sum(h["value"] for h in old_hours)
        after = sum(h["value"] for h in new_hours)
        return dict(kind="settlement_comparison", comparison_object_id=oid, metric="同观测同小时净值",
                    before=before, after=after, delta=after-before, unit="元",
                    improved=after>before, outcome="改善" if after>before else "未改善",
                    matched_hours=len(old_hours), notice="历史研究核对，不代表正式交易收益。")
    if selection.get("kind") == "prediction_comparison":
        if oid == p["record_id"]:
            raise ValueError("请选择不同的预测记录")
        old = ml.get_object(store,p["record_id"],"prediction")
        new = ml.get_object(store,oid,"prediction")
        a,b = old["payload"],new["payload"]
        old_model=ml.get_object(store,a["model_id"],"model")["payload"]
        new_model=ml.get_object(store,b["model_id"],"model")["payload"]
        if (old_model["policy"].get("information_budget","d2_history") != new_model["policy"].get("information_budget","d2_history")
                or a["logical_cutoff"] != b["logical_cutoff"]):
            raise ValueError("预测使用的信息条件或决策时点不同，不能直接验证模型改善")
        if (p["source_key"]!="market:shandong" or old["source_hash"]!=new["source_hash"]
                or a["date"]!=b["date"] or b["date"]!=p["date"] or a["task"]!=b["task"]):
            raise ValueError("预测的来源、日期或任务不一致")
        av={v["slot"]:v for v in a["points"] if v["actual"] is not None}
        bv={v["slot"]:v for v in b["points"] if v["actual"] is not None}
        if not av or av.keys()!=bv.keys() or any(av[k]["actual"]!=bv[k]["actual"] for k in av):
            raise ValueError("预测比较的实际值与时段不一致")
        before=float(np.mean([abs(v["predicted"]-v["actual"]) for v in av.values()]))
        after=float(np.mean([abs(v["predicted"]-v["actual"]) for v in bv.values()]))
        return dict(kind="prediction_comparison", comparison_object_id=oid, metric="配对平均绝对误差",
                    before=before, after=after, delta=after-before, unit=a["unit"], improved=after<before,
                    outcome="改善" if after<before else "未改善", matched_points=len(av),
                    notice="同日历史核对，不构成新的独立模型终评。")
    raise ValueError("请选择结算或预测对照，不接受手填改善数值")


@router.post("/review-commands")
def command(body: ReviewCommand, request: Request, store: Store = Depends(store_dep)):
    from .business_workflow import owned_plan, owned_settlement
    if request.headers.get("origin") and urlsplit(request.headers["origin"]).netloc != request.headers.get("host"):
        raise HTTPException(403,"请从本站操作")
    if not body.actor.strip() or not body.reason.strip():
        raise ValueError("请填写操作人与依据")
    day=body.date.isoformat()
    store.db.execute("BEGIN IMMEDIATE")
    try:
        if body.action=="create":
            if not body.plan_id or body.category not in CATEGORIES:
                raise ValueError("请选择申报方案和问题类型")
            plan=owned_plan(store,body.plan_id,body.source_key,day)
            settlement=owned_settlement(store,body.settlement_id,body.source_key,day) if body.settlement_id else None
            if settlement and settlement["payload"]["plan_id"]!=body.plan_id:
                raise ValueError("结算记录不属于该申报方案")
            p=plan["payload"]
            payload=dict(source_key=body.source_key,date=day,task=p["task"],model_id=p["model_id"],
                         record_id=p["record_id"],plan_id=body.plan_id,settlement_id=body.settlement_id,
                         slot=body.slot,category=body.category,reason=body.reason,actor=body.actor,
                         owner=body.owner.strip() or body.actor,actor_verification="intranet_declared",
                         training_eligible=False,evidence_snapshot=dict(plan=p,settlement=settlement["payload"] if settlement else None))
            oid="business_review_issue_"+ml.digest(payload)[:28]
            if not store.db.execute("SELECT 1 FROM ml_object WHERE object_id=?",(oid,)).fetchone():
                ml.add_object(store,"business_review_issue",payload,plan["source_hash"],plan["id"],oid)
                ml.event(store,oid,"pending",actor=body.actor,reason=body.reason,owner=payload["owner"])
        else:
            if not body.issue_id:
                raise ValueError("请选择处理事项")
            obj=owned_issue(store,body.issue_id,body.source_key,day);oid=obj["id"]
            if body.plan_id and body.plan_id!=obj["payload"]["plan_id"]:
                raise ValueError("处理事项不属于该申报方案")
            allowed={"start":({"pending"},"in_progress"),"resolve":({"in_progress"},"resolved"),
                     "verify":({"resolved"},"verified"),"reopen":({"resolved","verified"},"in_progress")}
            if body.action not in allowed or obj["state"] not in allowed[body.action][0]:
                raise ValueError("当前处理阶段不允许执行此操作，请刷新事项")
            d=dict(obj["detail"],actor=body.actor,reason=body.reason)
            if body.owner.strip():d["owner"]=body.owner.strip()
            if body.action=="resolve":
                if not body.evidence.strip():raise ValueError("请填写实际处理动作和证据")
                d["evidence"]=body.evidence.strip()
            if body.action=="verify":d["verification"]=verify_result(store,obj,body.verification)
            if body.action=="reopen":d["verification"]=None
            ml.event(store,oid,allowed[body.action][1],**d)
        store.db.commit()
        return display(store,ml.get_object(store,oid))
    except Exception:
        store.db.rollback()
        raise
