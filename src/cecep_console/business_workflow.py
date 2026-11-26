"""Immutable public-data plans and versioned settlement, with no realized-price forecasts."""

from datetime import date
import json
import math
from urllib.parse import urlsplit

import numpy as np
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from . import data_flow, learning as ml, task_catalog as tc
from .learning_api import store_dep
from .storage import Store

router = APIRouter(prefix="/api/v1/business", tags=["public-business-workflow"])
SOURCE = "market:shandong"
PV_TASK = "pv_day_ahead_reference"
NOTICE = "山东区域公开历史研究方案；原始发布时间未核验，不是岚能、凌光生产申报或浙江正式结算规则。"
RULE = "日前申报量×日前小时价＋逐15分钟偏差电量×实时价－实际电量绝对值×每MWh费用；不含正式合约与考核。"
PRICE_TASKS = {"da": "da_price_reference", "rt": tc.PRICE_TASK, "spread": "prebid_spread_reference"}


class Parameters(BaseModel):
    model_config = ConfigDict(extra="forbid")
    mode: str = "manual"
    bid_ratio: float = Field(default=1, ge=0, le=1.5, allow_inf_nan=False)
    fee_yuan_mwh: float = Field(default=0, ge=0, allow_inf_nan=False)
    min_ratio: float = Field(default=0, ge=0, le=1.5, allow_inf_nan=False)
    max_ratio: float = Field(default=1.5, ge=0, le=1.5, allow_inf_nan=False)
    spread_threshold: float = Field(default=0, ge=0, allow_inf_nan=False)
    ratio_step: float = Field(default=.1, ge=0, le=1.5, allow_inf_nan=False)
    max_bid_mwh: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    hourly_ratios: list[float] | None = Field(default=None, min_length=24, max_length=24)

    @model_validator(mode="after")
    def validate_parameters(self):
        if self.mode not in {"manual", "spread_rule"}:
            raise ValueError("选择手动申报系数或确定性价差规则")
        if not self.min_ratio <= self.bid_ratio <= self.max_ratio:
            raise ValueError("申报系数必须位于设定的上下限内")
        if self.hourly_ratios is not None and (self.mode != "manual" or any(not math.isfinite(v) or not self.min_ratio <= v <= self.max_ratio for v in self.hourly_ratios)):
            raise ValueError("逐小时系数仅用于手动方案，且必须满足上下限")
        return self


class Command(BaseModel):
    model_config = ConfigDict(extra="forbid")
    action: str
    source_key: str = SOURCE
    trading_date: str
    task_id: str = PV_TASK
    record_id: str = ""
    model_id: str = ""
    plan_id: str = ""
    da_record_id: str = ""
    rt_record_id: str = ""
    spread_record_id: str = ""
    observation_id: str = ""
    context_version: str = ""
    parameters: Parameters | None = None
    actor: str = Field(min_length=1, max_length=100)
    reason: str = Field(min_length=1, max_length=4000)
    key: str = Field(min_length=1, max_length=100)

    @field_validator("trading_date")
    @classmethod
    def valid_date(cls, value):
        return date.fromisoformat(value).isoformat()

    @field_validator("actor", "reason", "key")
    @classmethod
    def not_blank(cls, value):
        if not value.strip():
            raise ValueError("操作人、依据和提交标记不能为空")
        return value.strip()


def owned_plan(store, oid, source_key, day):
    obj = ml.get_object(store, oid, "business_plan")
    if obj["payload"]["source_key"] != source_key or obj["payload"]["date"] != day:
        raise ValueError("方案不属于当前数据范围和交易日期")
    return obj


def owned_settlement(store, oid, source_key, day):
    obj = ml.get_object(store, oid, "business_settlement")
    if obj["payload"]["source_key"] != source_key or obj["payload"]["date"] != day:
        raise ValueError("结算记录不属于当前数据范围和交易日期")
    return obj


def information_budget(model):
    return model["payload"]["policy"].get("information_budget", "d2_history")


def prediction(store, oid, task, day):
    obj = ml.get_object(store, oid, "prediction")
    p = obj["payload"]
    model = ml.get_object(store, p["model_id"], "model")
    if p.get("validation_only"):
        raise ValueError("调参验证预测不能作为事前申报方案输入，请选择选参边界之后的研究预测")
    if p["task"] != task or p["date"] != day or model["payload"]["task"] != task:
        raise ValueError("保存预测的任务或日期与当前方案不一致")
    if ml.job(store, model["payload"]["job_id"])["state"] != "succeeded":
        raise ValueError("保存预测所属作业没有真实成功退出记录")
    grid = tc.slots(task)
    points = p["points"]
    if sorted(v["slot"] for v in points) != grid or any(not math.isfinite(v["predicted"]) for v in points):
        raise ValueError("保存预测缺少完整且唯一的任务时段")
    if tc.spec(task)["intraday"]:
        raise ValueError("申报前方案不能使用后来滚动取得的日内信息")
    return obj, model


def public_object(obj):
    p = obj["payload"]
    return dict(p, id=obj["id"], created_at=obj["created_at"], status="saved",
                parent_id=p.get("parent_plan_id") if obj["kind"] == "business_plan" else p["plan_id"])


def settlements(store, plan_id):
    rows = store.db.execute("SELECT object_id FROM ml_object WHERE kind='business_settlement' AND parent_id=? ORDER BY rowid DESC", (plan_id,))
    return [public_object(ml.get_object(store, r[0], "business_settlement")) for r in rows]


def plan_summary(store, obj):
    p = public_object(obj)
    result = {k: p[k] for k in ("id", "name", "version", "parent_id", "source_key", "date", "task", "model_id", "record_id", "status", "parameters", "estimated", "risk", "created_at", "actor", "reason")}
    latest = settlements(store, obj["id"])
    result["latest_settlement"] = latest[0] if latest else None
    result["parent_name"] = p.get("parent_name")
    return result


def list_plans(store, source_key, day):
    return [plan_summary(store, obj) for obj in ml.objects(store, "business_plan", 10000)
            if obj["payload"]["source_key"] == source_key and obj["payload"]["date"] == day]


def catalog_data(store, source_key, day, record_id=""):
    if source_key != SOURCE:
        return dict(source_key=source_key, date=day, context_version="", predictions=[], observations=[], plans=[], notice="申报与结算研究当前仅使用既有山东公开历史数据；此范围暂无可用业务链。")
    predictions, observations = [], []
    for obj in ml.objects(store, "prediction", 10000):
        p = obj["payload"]
        if p["date"] != day or p["task"] not in (PV_TASK, *PRICE_TASKS.values()):
            continue
        try:
            _, model = prediction(store, obj["id"], p["task"], day)
        except ValueError:
            continue
        predictions.append(dict(id=obj["id"], record_id=obj["id"], model_id=model["id"], task=p["task"], date=day,
                                name=model["display_name"]+" · "+obj["display_name"], unit=p["unit"],
                                information_budget=information_budget(model), input_source_hash=obj["source_hash"], cutoff_at=p["logical_cutoff"]))
    if record_id:
        prediction(store, record_id, PV_TASK, day)
        for row in store.db.execute("SELECT observation_id FROM ml_observations WHERE prediction_id=? ORDER BY created_at DESC,observation_id DESC", (record_id,)):
            obs = ml.get_object(store, row[0], "observation_match")
            source_name = ml.get_object(store, obs["payload"]["source_revision_id"], "source_revision")["display_name"]
            observations.append(dict(id=obs["id"], prediction_id=record_id, name=obs["display_name"], source_name=source_name, checked_at=obs["payload"]["checked_at"]))
    version = ml.digest(dict(source=source_key, day=day, record=record_id,
                             predictions=[v["id"] for v in predictions], observations=[v["id"] for v in observations]))
    return dict(source_key=source_key, date=day, context_version=version, predictions=predictions,
                observations=observations, plans=list_plans(store, source_key, day), notice=NOTICE)


def training_risk(model):
    """Training-only residual description, without tune/promotion/final labels."""
    p = model["payload"]
    arrays = ml.read_npz(p["arrays"])
    required = ["train_"+k for k in ("x", "y", "days", "slots")]
    if not all(k in arrays for k in required):
        return dict(available=False, sample_hours=0, lower_error_mwh=None, upper_error_mwh=None, mean_error_mwh=None,
                    notice="此模型未保存可核验的训练期残差，风险区间留空。")
    data = {k: arrays["train_"+k] for k in ("x", "y", "days", "slots")}
    start = p.get("effective_training_start", p["splits"]["train"][0])
    end = p.get("effective_training_end", p["splits"]["train"][1])
    mask = (data["days"] >= start) & (data["days"] <= end)
    data = {k: v[mask] for k, v in data.items()}
    predicted = ml.predict_payload(p, data)
    groups = {}
    for d, slot, actual, value in zip(data["days"], data["slots"], data["y"], predicted):
        groups.setdefault((str(d), int(slot)//4), []).append((int(slot), float(actual), max(float(value), 0)))
    residuals = [sum((a-v)*.25 for _,a,v in values) for values in groups.values() if len(values)==4 and len({s for s,_,_ in values})==4]
    if not residuals:
        return dict(available=False, sample_hours=0, lower_error_mwh=None, upper_error_mwh=None, mean_error_mwh=None,
                    notice="训练期没有完整小时残差，风险区间留空。")
    low, high = np.quantile(residuals, [.1,.9])
    return dict(available=True, sample_hours=len(residuals), lower_error_mwh=float(low), upper_error_mwh=float(high),
                mean_error_mwh=float(np.mean(residuals)), training_start=start, training_end=end,
                notice="仅为训练期拟合残差的10%至90%描述范围；没有使用目标日实际值，不是已校准的预测置信区间。")


def hour_prices(price_objects, end):
    da = next((v["predicted"] for v in price_objects["da"]["payload"]["points"] if v["slot"]==end), None) if price_objects.get("da") else None
    spread = next((v["predicted"] for v in price_objects["spread"]["payload"]["points"] if v["slot"]==end), None) if price_objects.get("spread") else None
    rt = None
    if price_objects.get("rt"):
        byslot = {v["slot"]:v["predicted"] for v in price_objects["rt"]["payload"]["points"]}
        rt = [byslot[s] for s in range(end-3,end+1)]
    if da is not None and rt is not None:
        spread = sum(rt)/4-da
    elif da is not None and spread is not None:
        rt = [da+spread]*4
    elif rt is not None and spread is not None:
        da = sum(rt)/4-spread
    return da, rt, spread


def create_plan(store, b):
    if b.source_key != SOURCE or b.task_id != PV_TASK:
        raise ValueError("当前申报方案仅支持山东区域光伏日前保存预测")
    parent = owned_plan(store, b.plan_id, b.source_key, b.trading_date) if b.action=="derive_plan" else None
    if parent:
        prior = parent["payload"]
        record_id = b.record_id or prior["record_id"]
        ids = {k: getattr(b,k+"_record_id") if k+"_record_id" in b.model_fields_set else prior["price_records"].get(k,{}).get("record_id", "") for k in PRICE_TASKS}
        changes = {k:getattr(b.parameters,k) for k in b.parameters.model_fields_set} if b.parameters else {}
        parameters = Parameters(**{**prior["parameters"], **changes})
    else:
        record_id = b.record_id
        ids = {k:getattr(b,k+"_record_id") for k in PRICE_TASKS}
        parameters = b.parameters or Parameters()
    pv, model = prediction(store, record_id, PV_TASK, b.trading_date)
    if b.model_id and b.model_id != model["id"]:
        raise ValueError("光伏模型与保存预测不一致")
    prices = {}
    if sum(bool(v) for v in ids.values())>2:
        raise ValueError("最多选择两类价格预测，避免三个独立预测的价差口径冲突")
    for role, oid in ids.items():
        if not oid:
            continue
        obj, price_model = prediction(store, oid, PRICE_TASKS[role], b.trading_date)
        if obj["source_hash"] != pv["source_hash"] or information_budget(price_model) != information_budget(model) or obj["payload"]["logical_cutoff"] != pv["payload"]["logical_cutoff"]:
            raise ValueError("量价预测必须绑定同一输入版本、交易日、信息预算和预测截止时点")
        prices[role] = obj
    risk = training_risk(model)
    byslot = {v["slot"]:v["predicted"] for v in pv["payload"]["points"]}
    hours = []
    for end in range(3,96,4):
        raw = [byslot[s]*.25 for s in range(end-3,end+1)]
        q = [max(v,0) for v in raw]
        quantity = sum(q)
        da, rt, spread = hour_prices(prices,end)
        ratio = parameters.hourly_ratios[end//4] if parameters.hourly_ratios else parameters.bid_ratio
        if parameters.mode == "spread_rule":
            if spread is None:
                raise ValueError("确定性价差规则需要申报前价差预测，或同时选择日前与实时价格预测")
            ratio += (-parameters.ratio_step if spread>parameters.spread_threshold else parameters.ratio_step if spread < -parameters.spread_threshold else 0)
        ratio = min(parameters.max_ratio,max(parameters.min_ratio,ratio))
        bid = quantity*ratio
        if parameters.max_bid_mwh is not None:
            bid = min(bid,parameters.max_bid_mwh)
        fee = quantity*parameters.fee_yuan_mwh
        value = bid*da+sum((v-bid/4)*p for v,p in zip(q,rt))-fee if da is not None and rt is not None else None
        hours.append(dict(hour=end//4,time=f"{end//4:02d}:00–{end//4+1:02d}:00",forecast_mwh=quantity,raw_forecast_mwh=sum(raw),bid_mwh=bid,bid_ratio=ratio,
                          da_forecast=da,rt_forecast=sum(rt)/4 if rt is not None else None,spread_forecast=spread,expected_fee=fee,expected_value=value,
                          risk_lower_mwh=max(0,quantity+risk["lower_error_mwh"]) if risk["available"] else None,
                          risk_upper_mwh=max(0,quantity+risk["upper_error_mwh"]) if risk["available"] else None,
                          missing_reason=None if value is not None else "缺少两类可还原完整价格的保存预测，预计金额留空",
                          quarter_forecast_mwh=q,quarter_rt_forecast=rt))
    priced = [h for h in hours if h["expected_value"] is not None]
    estimated = dict(forecast_mwh=sum(h["forecast_mwh"] for h in hours),bid_mwh=sum(h["bid_mwh"] for h in hours),expected_fee=sum(h["expected_fee"] for h in hours),
                     expected_value=sum(h["expected_value"] for h in priced) if priced else None,priced_hours=len(priced),total_hours=24,
                     notice="仅使用保存预测和声明费用；预测负出力不作为可申报电量。实际电价与目标日实绩未用于预计。")
    version = parent["payload"]["version"]+1 if parent else 1
    serial = store.db.execute("SELECT count(*) FROM ml_object WHERE kind='business_plan'").fetchone()[0]+1
    payload = dict(name=f"{b.trading_date} · 申报方案{serial}",version=version,parent_plan_id=parent["id"] if parent else None,parent_name=parent["payload"]["name"] if parent else None,
                   source_key=b.source_key,date=b.trading_date,task=PV_TASK,model_id=model["id"],record_id=record_id,input_source_hash=pv["source_hash"],information_budget=information_budget(model),cutoff_at=pv["payload"]["logical_cutoff"],
                   parameters=parameters.model_dump(),price_records={k:dict(record_id=o["id"],model_id=o["payload"]["model_id"],name=o["display_name"]) for k,o in prices.items()},
                   hours=hours,estimated=estimated,risk=risk,rule=RULE,actor=b.actor,reason=b.reason,actor_verification="intranet_declared",production_eligible=False,time_policy="historical_assumed",notice=NOTICE)
    return payload, pv["source_hash"], parent["id"] if parent else record_id


def calculate_settlement(store, plan, observation, actor, reason):
    p, o = plan["payload"], observation["payload"]
    if observation["parent_id"] != p["record_id"] or o["prediction_id"] != p["record_id"] or o["date"] != p["date"]:
        raise ValueError("实际核对记录不属于方案绑定的预测与交易日")
    _, _, days = data_flow.source_version(store, observation["source_hash"])
    rows = days.get(p["date"],{})
    observed = {v["slot"]:v["actual"] for v in o["points"]}
    if len(observed) != len(o["points"]):
        raise ValueError("实际核对记录存在重复时段")
    for slot, value in observed.items():
        if value != tc.target(PV_TASK,rows,slot):
            raise ValueError("核对实际值与所绑定的原始归档不一致")
    fee_rate = p["parameters"]["fee_yuan_mwh"]
    hours = []
    for saved in p["hours"]:
        h = dict(hour=saved["hour"],time=saved["time"],bid_mwh=saved["bid_mwh"],complete=False,missing_reason=None,
                 actual_mwh=None,da_price=None,rt_price=None,fee=None,value=None,reference=None,expected_value=saved["expected_value"],variance=None,power_effect=None,price_effect=None,fee_effect=None)
        end = saved["hour"]*4+3
        da = tc.hour_value(rows,end,"da_price")
        actual = [observed.get(s) for s in range(end-3,end+1)]
        rt = [rows.get(s,{}).get("rt_price") for s in range(end-3,end+1)]
        if da is None or any(v is None for v in actual+rt):
            h["missing_reason"]="实际功率、实时价格或日前小时价格缺失；整小时不结算，不补零"
            hours.append(h)
            continue
        q = [v*.25 for v in actual]
        fee = sum(abs(v) for v in q)*fee_rate
        bid = saved["bid_mwh"]
        value = bid*da+sum((v-bid/4)*price for v,price in zip(q,rt))-fee
        reference = sum(v*price for v,price in zip(q,rt))-fee
        h.update(complete=True,actual_mwh=sum(q),da_price=da,rt_price=sum(rt)/4,fee=fee,value=value,reference=reference,negative_intervals=sum(v<0 for v in actual))
        if saved["expected_value"] is not None:
            qhat,rthat = saved["quarter_forecast_mwh"],saved["quarter_rt_forecast"]
            power=sum((a-f)*price for a,f,price in zip(q,qhat,rthat))
            price=bid*(da-saved["da_forecast"])+sum((a-bid/4)*(real-forecast) for a,real,forecast in zip(q,rt,rthat))
            fees=saved["expected_fee"]-fee
            variance=value-saved["expected_value"]
            if not math.isclose(power+price+fees,variance,rel_tol=1e-10,abs_tol=1e-6):
                raise ValueError("逐小时量价费用分解未与总差额核平")
            h.update(variance=variance,power_effect=power,price_effect=price,fee_effect=fees)
        hours.append(h)
    complete=[h for h in hours if h["complete"]]
    matched=[h for h in complete if h["expected_value"] is not None]
    def total(key, group):
        return sum(h[key] for h in group) if group else None
    actual=dict(value=total("value",complete),reference=total("reference",complete),delta=sum(h["value"]-h["reference"] for h in complete) if complete else None,
                actual_mwh=total("actual_mwh",complete),bid_mwh=total("bid_mwh",complete),fee=total("fee",complete),settled_hours=len(complete),excluded_hours=24-len(complete),negative_intervals=sum(h.get("negative_intervals",0) for h in complete))
    comparison=dict(expected_value=total("expected_value",matched),actual_value=total("value",matched),delta=total("variance",matched),power_effect=total("power_effect",matched),price_effect=total("price_effect",matched),fee_effect=total("fee_effect",matched),matched_hours=len(matched),unmatched_hours=24-len(matched),notice="仅比较预计与实际都完整的同一小时；正负差额为代数分解，不是天气或设备的因果诊断。")
    return dict(source_key=p["source_key"],date=p["date"],task=PV_TASK,plan_id=plan["id"],record_id=p["record_id"],model_id=p["model_id"],observation_id=observation["id"],observation_name=observation["display_name"],
                observation_source_hash=observation["source_hash"],source_revision_id=o["source_revision_id"],hours=hours,actual=actual,comparison=comparison,parameters=p["parameters"],rule=RULE,
                actor=actor,reason=reason,actor_verification="intranet_declared",production_eligible=False,time_policy="historical_assumed",notice=NOTICE)


def plan_detail(store, oid, source_key, day):
    plan=owned_plan(store,oid,source_key,day)
    return dict(plan=public_object(plan),settlements=settlements(store,oid),notice=NOTICE)


@router.get("/catalog")
def catalog(source_key: str=SOURCE,trading_date: str="",record_id: str="",store: Store=Depends(store_dep)):
    date.fromisoformat(trading_date)
    return catalog_data(store,source_key,trading_date,record_id)


@router.get("/plans")
def plans(source_key: str=SOURCE,trading_date: str="",store: Store=Depends(store_dep)):
    date.fromisoformat(trading_date)
    return dict(plans=list_plans(store,source_key,trading_date),notice=NOTICE)


@router.get("/plans/{oid}")
def detail(oid: str,source_key: str=SOURCE,trading_date: str="",store: Store=Depends(store_dep)):
    return plan_detail(store,oid,source_key,trading_date)


@router.post("/commands")
def command(b: Command,request: Request,store: Store=Depends(store_dep)):
    origin=request.headers.get("origin")
    if origin and urlsplit(origin).netloc != request.headers.get("host"):
        raise HTTPException(403,"请从本站申报与结算页面操作")
    if b.action not in {"create_plan","derive_plan","settle"}:
        raise ValueError("未登记的申报与结算操作")
    fingerprint=ml.digest(dict(command=b.model_dump(),supplied=sorted(b.model_fields_set)))
    subject="business-command:"+ml.digest(b.key)
    previous=ml.state(store,subject)
    if previous["state"]=="saved":
        if previous["detail"]["request_hash"]!=fingerprint:
            raise ValueError("提交标记已用于另一业务操作")
        oid=previous["detail"]["plan_id"]
        result=plan_detail(store,oid,b.source_key,b.trading_date)
        saved=ml.get_object(store,previous["detail"]["object_id"])
        if saved["kind"]=="business_settlement":
            result["settlement"]=public_object(saved)
        return result
    if b.context_version and b.context_version!=catalog_data(store,b.source_key,b.trading_date,b.record_id)["context_version"]:
        raise ValueError("预测或观测范围已变化，请刷新业务数据后重试")
    if b.action in {"create_plan","derive_plan"}:
        payload,source_hash,parent=create_plan(store,b)
        kind="business_plan"
    else:
        plan=owned_plan(store,b.plan_id,b.source_key,b.trading_date)
        if b.record_id and b.record_id!=plan["payload"]["record_id"]:
            raise ValueError("方案与当前选中预测不一致")
        if not b.observation_id:
            raise ValueError("实际结算必须选择已保存的实际核对版本")
        observation=ml.get_object(store,b.observation_id,"observation_match")
        payload=calculate_settlement(store,plan,observation,b.actor,b.reason)
        count=store.db.execute("SELECT count(*) FROM ml_object WHERE kind='business_settlement' AND parent_id=?",(plan["id"],)).fetchone()[0]+1
        payload.update(name=plan["payload"]["name"]+f" · 实际结算{count}",version=count)
        source_hash,parent,kind=observation["source_hash"],plan["id"],"business_settlement"
    store.db.execute("BEGIN IMMEDIATE")
    try:
        prior=ml.state(store,subject)
        if prior["state"]=="saved":
            if prior["detail"]["request_hash"]!=fingerprint:
                raise ValueError("提交标记已用于另一业务操作")
            store.db.rollback()
            result=plan_detail(store,prior["detail"]["plan_id"],b.source_key,b.trading_date)
            saved=ml.get_object(store,prior["detail"]["object_id"])
            if saved["kind"]=="business_settlement":
                result["settlement"]=public_object(saved)
            return result
        if kind=="business_plan":
            serial=store.db.execute("SELECT count(*) FROM ml_object WHERE kind='business_plan'").fetchone()[0]+1
            payload["name"]=f"{b.trading_date} · 申报方案{serial}"
        else:
            count=store.db.execute("SELECT count(*) FROM ml_object WHERE kind='business_settlement' AND parent_id=?",(parent,)).fetchone()[0]+1
            payload.update(name=plan["payload"]["name"]+f" · 实际结算{count}",version=count)
        oid=ml.add_object(store,kind,payload,source_hash,parent)
        plan_id=oid if kind=="business_plan" else payload["plan_id"]
        ml.event(store,oid,"saved",actor=b.actor,reason=b.reason)
        ml.event(store,subject,"saved",request_hash=fingerprint,plan_id=plan_id,object_id=oid)
        store.db.commit()
    except Exception:
        store.db.rollback()
        raise
    result=plan_detail(store,plan_id,b.source_key,b.trading_date)
    if kind=="business_settlement":
        result["settlement"]=public_object(ml.get_object(store,oid,"business_settlement"))
    return result
