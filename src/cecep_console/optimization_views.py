"""Read saved optimization evidence without training or changing serving pointers."""

from datetime import date, datetime, timedelta
import json
import numpy as np
from fastapi import APIRouter, Depends
from .storage import Store
from .learning_api import store_dep
from . import learning as ml, task_catalog as tc

router = APIRouter(prefix="/api/v1/optimization", tags=["optimization-evidence"])
NAMES = {
    "candidate": "优化流程",
    "old_ridge": "原线性方法（同截止日重训）",
    "reference": "两日前同期参考",
    "calendar": "时段与星期参考",
    "majority": "多数方向参考",
    "old_regression": "原回归方法的方向判断",
}


def title(p):
    if p["contract"].get("conditional_upstream_required"):
        return "上游预测条件方案（发布时间未核验）"
    if p.get("evaluation_family") == "direction":
        return "申报前方向模型"
    name = p["contract"]["contract_id"]
    return (
        "早间观测方案"
        if "-v3-" in name
        else "双重风险约束方案" if "-v4-" in name else "稳健历史方案"
    )


def rows(scores, task, family):
    result = []
    for key in (
        ("candidate", "old_regression", "calendar", "majority")
        if family == "direction"
        else ("candidate", "old_ridge", "reference")
    ):
        if key not in scores:
            continue
        name = NAMES[key]
        if key == "reference" and not task.startswith("pv_"):
            name = "零价差参考"
        result.append(dict(name=name, **scores[key]))
    return result


def ci_label(ci, family, unit):
    if not ci:
        return "暂无匹配的区间估计"
    lo, hi = ci.get("lower95"), ci.get("upper95")
    if lo is None or hi is None:
        return "有效日期不足，改善尚不确定"
    if family == "direction":
        conclusion = (
            "命中率改善有支持"
            if lo > 0
            else "命中率更低" if hi < 0 else "命中率改善尚不确定"
        )
        return f"按自然周成组比较，命中率差值95%区间 [{lo*100:.2f}, {hi*100:.2f}] 个百分点；{conclusion}。"
    conclusion = (
        "平均绝对误差降低有支持"
        if hi < 0
        else "平均绝对误差更高" if lo > 0 else "平均绝对误差改善尚不确定"
    )
    return (
        f"按自然周成组比较，误差差值95%区间 [{lo:.3f}, {hi:.3f}] {unit}；{conclusion}。"
    )


@router.get("/summary")
def summary(task_id: str, store: Store = Depends(store_dep)):
    spec = tc.spec(task_id)
    reports = []
    for obj in ml.objects(store, "optimization_result", 50):
        p = obj["payload"]
        if p["task"] != task_id:
            continue
        family = p.get("evaluation_family", "amplitude")
        s = p["summary"]
        reference = "calendar" if family == "direction" else "reference"
        replay = p["folds"][-1]
        reports.append(
            dict(
                id=obj["id"],
                name=title(p),
                family=family,
                created_at=obj["created_at"],
                unit="%" if family == "direction" else spec["display_unit"],
                rows=s["rows"],
                days=s["days"],
                scores=rows(s["scores"], task_id, family),
                evidence=ci_label(
                    s["comparisons"].get(reference), family, spec["display_unit"]
                ),
                old_evidence=ci_label(
                    s["comparisons"].get(
                        "old_regression" if family == "direction" else "old_ridge"
                    ),
                    family,
                    spec["display_unit"],
                ),
                input_notice=(
                    "需要在申报前实际取得目标日上游预测；源文件没有发布时间，因此本组不能视为已经核验的申报前预测能力。"
                    if p["contract"].get("conditional_upstream_required")
                    else (
                        "另用前一日08:00前的观测，假设一小时到达延迟；不使用目标日预测列。"
                        if "-v3-" in p["contract"]["contract_id"]
                        else "使用两日及更早历史；日内观测至少滞后一小时，不使用目标日预测列。"
                    )
                ),
                replay=dict(
                    start=replay["fold"]["start"],
                    end=replay["fold"]["end"],
                    scores=rows(replay["scores"], task_id, family),
                    evidence=ci_label(
                        replay["comparisons"].get(reference),
                        family,
                        spec["display_unit"],
                    ),
                ),
                folds=[
                    dict(
                        name=f["fold"]["name"],
                        start=f["fold"]["start"],
                        end=f["fold"]["end"],
                        candidate=f["scores"]["candidate"],
                        reference=f["scores"][reference],
                        choice=(
                            "保持参考，未输出新信号"
                            if f["choice"].get("recipe") == "reference"
                            or f["choice"].get("kind") == "calendar"
                            else "内层选出的优化模型"
                        ),
                    )
                    for f in p["folds"][:-1]
                ],
            )
        )
    return dict(
        reports=reports,
        notice="这里比较的是按时间滚动训练的优化流程，每折均只使用更早的数据；不是同一个模型倒推早年数据。均为历史研究验证，旧最终窗口只作复盘，原审计不重开。研究主版本不会因这里出现较小误差而自动替换。",
    )


@router.get("/predictions")
def predictions(
    result_id: str, trading_date: date, task_id: str, store: Store = Depends(store_dep)
):
    obj = ml.get_object(store, result_id, "optimization_result")
    p = obj["payload"]
    if p["task"] != task_id:
        raise ValueError("优化记录不属于当前任务")
    day = trading_date.isoformat()
    fold = next(
        (f for f in p["folds"] if f["fold"]["start"] <= day <= f["fold"]["end"]), None
    )
    if not fold:
        return dict(
            available=False,
            points=[],
            notice="该日期不在已保存的滚动验证或复盘范围内；本页不临时计算或补造预测。",
        )
    a = ml.read_npz(fold["predictions"])
    mask = a["days"] == day
    family = p.get("evaluation_family", "amplitude")
    points = []
    for i in np.flatnonzero(mask):
        slot = int(a["slots"][i])
        hourly = tc.spec(task_id)["hourly"]
        start = datetime.fromisoformat(day + "T00:00:00+08:00") + timedelta(
            minutes=(slot - 3 if hourly else slot) * 15
        )
        if family == "direction":
            prob = a["candidate"][i]
            points.append(
                dict(
                    start=start.isoformat(),
                    actual=int(a["y"][i]),
                    predicted=int(np.argmax(prob)) - 1,
                    negative=float(prob[0]),
                    flat=float(prob[1]),
                    positive=float(prob[2]),
                )
            )
        else:
            points.append(
                dict(
                    start=start.isoformat(),
                    actual=float(a["y"][i]),
                    predicted=float(a["candidate"][i]),
                    old=float(a["old_ridge"][i]),
                    reference=float(a["reference"][i]),
                )
            )
    return dict(
        available=bool(points),
        family=family,
        points=points,
        notice=(
            "已保存的外层验证预测。"
            if fold["fold"].get("outer_validation", True)
            else "已使用最终窗口的历史复盘，不是新的独立终评。"
        ),
    )
