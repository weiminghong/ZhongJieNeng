"""Research-only learning HTTP contract, with explicit user actions."""
import json
from typing import Literal
from datetime import date
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, field_validator
from urllib.parse import urlsplit
from .storage import Store
from . import learning as ml


def store_dep():
    with Store(check_same_thread=False) as store:
        yield store


class Command(BaseModel):
    model_config = ConfigDict(extra="forbid")
    action: Literal["dataset", "train", "cancel", "retry", "predict", "analyze", "feedback", "confirm", "proposal", "train_proposal", "activate", "shadow", "reject", "rollback", "final_audit"]
    object_id: str = Field(default="", max_length=100)
    source_hash: str = Field(default="", max_length=64)
    actor: str = Field(min_length=1, max_length=100)
    reason: str = Field(min_length=1, max_length=4000)
    alpha: float = Field(default=1, allow_inf_nan=False)
    idempotency_key: str = Field(default="", max_length=100)
    date: str | None = None
    slot: int = Field(default=0, ge=0, le=95)
    validation_only: bool = False

    @field_validator("date")
    @classmethod
    def valid_day(cls, value):
        return date.fromisoformat(value).isoformat() if value else None

    @field_validator("actor", "reason")
    @classmethod
    def not_blank(cls, value):
        if not value.strip():
            raise ValueError("不能为空白")
        return value.strip()


router = APIRouter(prefix="/api/v1/ml", tags=["public-research-learning"])


@router.get("/overview")
def overview(store: Store = Depends(store_dep)):
    return ml.overview(store)


@router.get("/capabilities")
def capabilities():
    return dict(tasks=[dict(task=ml.TASK, executable=True, scope="山东省级公开市场", unit="CNY/MWh",
                            production_eligible=False, time_policy="historical_assumed")], policy=ml.POLICY,
                unavailable=["岚能与凌光生产功率训练", "浙江真实收益优化", "企业身份认证"])


@router.get("/lineage/{oid}")
def lineage(oid: str, store: Store = Depends(store_dep)):
    start = ml.get_object(store, oid)
    source = start["source_hash"]
    records = store.db.execute("SELECT object_id,kind,parent_id,payload_json FROM ml_object WHERE source_hash=? ORDER BY rowid", (source,)).fetchall()
    nodes, edges = [], []
    for r in records:
        payload = json.loads(r[3])
        nodes.append(dict(id=r[0], kind=r[1], state=ml.state(store, r[0])["state"]))
        if r[2]:
            edges.append(dict(source=r[2], target=r[0], relation="parent"))
        for key in ("job_id", "dataset_id", "model_id", "prediction_id", "feedback_id"):
            if payload.get(key) and payload[key] != r[2]:
                edges.append(dict(source=payload[key], target=r[0], relation=key))
    for r in store.db.execute("SELECT job_id,dataset_id,parent_job_id FROM ml_job WHERE dataset_id IN (SELECT object_id FROM ml_object WHERE source_hash=?)", (source,)):
        nodes.append(dict(id=r[0], kind="job", state=ml.state(store, r[0])["state"]))
        edges.append(dict(source=r[1], target=r[0], relation="dataset"))
        if r[2]:
            edges.append(dict(source=r[2], target=r[0], relation="retry_or_retrain"))
    return dict(root_id=oid, source_hash=source, nodes=nodes, edges=edges)


@router.get("/objects/{oid}")
def detail(oid: str, store: Store = Depends(store_dep)):
    return ml.get_object(store, oid)


@router.get("/jobs/{jid}")
def job_detail(jid: str, store: Store = Depends(store_dep)):
    result = ml.job(store, jid)
    result["events"] = [dict(state=r[0], detail=json.loads(r[1]), created_at=r[2]) for r in store.db.execute("SELECT state,payload_json,created_at FROM ml_event WHERE subject_id=? ORDER BY rowid", (jid,))]
    return result


@router.post("/commands")
def command(body: Command, request: Request, store: Store = Depends(store_dep)):
    origin = request.headers.get("origin")
    if origin and urlsplit(origin).netloc != request.headers.get("host"):
        raise HTTPException(403, "请从本站研究页面操作")
    b = body
    ml.event(store, "command:"+ml.TASK, b.action, actor=b.actor, reason=b.reason, object_id=b.object_id,
             actor_verification="intranet_declared")
    store.db.commit()
    if b.action == "dataset":
        return ml.register_dataset(store, b.source_hash)
    if b.action == "train":
        if not b.idempotency_key:
            raise ValueError("训练提交必须提供幂等键")
        return ml.submit(store, b.object_id, b.alpha, b.idempotency_key)
    if b.action in {"cancel", "retry"}:
        j = ml.job(store, b.object_id)
        if b.action == "retry":
            if not b.idempotency_key:
                raise ValueError("重试必须提供新幂等键")
            return ml.submit(store, j["dataset_id"], j["config"]["alpha"], b.idempotency_key, j["id"], j["config"].get("proposal_id"))
        store.db.execute("BEGIN IMMEDIATE")
        j = ml.job(store, b.object_id)
        if j["state"] in ml.TERMINAL:
            store.db.rollback(); raise ValueError("任务已结束，不可取消")
        ml.event(store, j["id"], "cancelled" if j["state"] == "queued" else "cancel_requested", actor=b.actor, reason=b.reason)
        store.db.commit(); return ml.job(store, j["id"])
    if b.action == "predict":
        if not b.date:
            raise ValueError("推理必须指定日期")
        return ml.prediction(store, b.object_id, b.date, b.validation_only, b.source_hash or None)
    if b.action == "feedback":
        return ml.feedback(store, b.object_id, b.slot, b.actor, b.reason)
    if b.action == "analyze":
        result = ml.analyze_prediction(store, b.object_id, b.reason)
        if result["payload"]["provider_error"]:
            return JSONResponse({**result, "error": result["payload"]["answer"]}, status_code=502)
        return result
    if b.action == "confirm":
        return ml.confirm_feedback(store, b.object_id, b.actor, b.reason)
    if b.action == "proposal":
        return ml.proposal(store, b.object_id, b.alpha, b.actor, b.reason)
    if b.action == "train_proposal":
        if not b.idempotency_key:
            raise ValueError("重训必须提供幂等键")
        return ml.train_proposal(store, b.object_id, b.idempotency_key)
    if b.action == "final_audit":
        return ml.final_audit(store, b.object_id, b.actor, b.reason)
    return ml.release(store, b.object_id, b.action, b.actor, b.reason)
