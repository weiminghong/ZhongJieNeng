"""Read saved business objects without substituting live/default calculations."""

import json
from . import learning as ml
from .storage import instant
from .serving import now


def load(store, object_id, source_key, day, task=None, model_id=None, record_id=None,
         mode="post", until="23:59"):
    obj = ml.get_object(store, object_id)
    kind = obj["kind"]
    if kind == "business_plan":
        from .business_workflow import owned_plan
        obj = owned_plan(store, object_id, source_key, day)
        plan, settlement, issue = obj["payload"], None, None
        title = "申报方案"
    elif kind == "business_settlement":
        from .business_workflow import owned_plan, owned_settlement
        obj = owned_settlement(store, object_id, source_key, day)
        settlement = obj["payload"]
        plan = owned_plan(store, settlement["plan_id"], source_key, day)["payload"]
        issue, title = None, "结算复盘"
    elif kind == "business_review_issue":
        from .business_reviews import owned_issue
        obj = owned_issue(store, object_id, source_key, day)
        issue = obj["payload"]
        evidence = issue["evidence_snapshot"]
        plan, settlement = evidence["plan"], evidence.get("settlement")
        title = "业务处理事项"
    else:
        raise ValueError("所选记录不是可分析的方案、结算或业务处理事项")
    cutoff = instant(f"{day}T{until}:00+08:00") if mode == "replay" else now()
    if obj["created_at"] > cutoff:
        raise ValueError("所选业务对象在当前回放时点尚未创建，不能提前读取")
    for payload in (plan, settlement, issue):
        if payload and (payload.get("source_key") != source_key or payload.get("date") != day):
            raise ValueError("业务对象的证据快照不属于当前来源和日期")
    if task and task != plan["task"]:
        raise ValueError("业务对象不属于当前预测任务")
    if model_id and model_id != plan["model_id"]:
        raise ValueError("业务对象不属于当前模型，请恢复方案保存的模型范围")
    if record_id and record_id != plan["record_id"]:
        raise ValueError("业务对象不属于当前预测，请恢复方案保存的预测范围")
    if settlement and settlement.get("record_id") != plan["record_id"]:
        raise ValueError("结算快照与申报方案的预测关联不一致")
    if issue and issue.get("record_id") != plan["record_id"]:
        raise ValueError("处理事项与申报方案的预测关联不一致")
    latest = store.db.execute(
        "SELECT state,payload_json FROM ml_event WHERE subject_id=? AND created_at<=? ORDER BY created_at DESC,rowid DESC LIMIT 1",
        (object_id, cutoff),
    ).fetchone()
    return dict(id=obj["id"], kind=kind, title=title, created_at=obj["created_at"],
                task=plan["task"], model_id=plan["model_id"], record_id=plan["record_id"],
                parameters=plan["parameters"], plan=plan, settlement=settlement, issue=issue,
                state=dict(state=latest["state"], detail=json.loads(latest["payload_json"])) if latest else dict(state="registered", detail={}),
                snapshot_notice="分析采用此业务对象保存的方案参数及证据快照；不把当前数据或默认参数替换进去，不把预计结果当成实际收益。")


def evidence(business):
    plan, settlement, issue = business["plan"], business["settlement"], business["issue"]
    facts = [f"当前分析对象：{business['title']}，交易日{plan['date']}。{business['snapshot_notice']}"]
    parameters = business["parameters"]
    names = {"bid_ratio":"申报系数", "fee_yuan_mwh":"每兆瓦时费用（元）", "min_ratio":"系数下限",
             "max_ratio":"系数上限", "ratio_step":"系数调整步长", "spread_threshold":"价差触发阈值（元/MWh）",
             "max_bid_mwh":"每小时申报上限（MWh）"}
    readable = [f"{names[k]}{'未设置' if v is None else v}" for k, v in parameters.items() if k in names]
    if readable:
        facts.append("保存的方案参数：" + "，".join(readable) + "。")
    if parameters.get("hourly_ratios") is not None:
        facts.append("该方案保存了逐小时申报系数，分析沿用这24项系数，不用单个默认系数替换。")
    facts.append("申报方式：" + ("按保存的价差预测及确定性规则调整系数。" if parameters.get("mode") == "spread_rule" else "按保存的手动申报系数。"))
    def number(value, unit):
        return "未形成完整可计算结果" if value is None else f"{value:,.2f}{unit}" if unit == "元" else f"{value:,.3f}{unit}"
    tools = [dict(name="核对业务对象快照", display_name="核对业务对象快照",
                  summary=f"已恢复{business['title']}的原方案、参数和预测关联。", output=business,
                  input=dict(business_object_id=business["id"], date=plan["date"], source_key=plan["source_key"]))]
    if plan.get("estimated"):
        est = plan["estimated"]
        facts.append(f"保存方案的预测电量{number(est.get('forecast_mwh'),'MWh')}，申报电量{number(est.get('bid_mwh'),'MWh')}；预计金额{number(est.get('expected_value'),'元')}，价格预测完整{est.get('priced_hours',0)}/24小时；这是预测预计，不能称为实际收益。")
        tools.append(dict(name="核对保存的预计结果", display_name="核对保存的预计结果",
                          summary=f"保存方案预计金额{number(est.get('expected_value'),'元')}；只使用所选保存预测。", output=plan["estimated"]))
    risk = plan.get("risk")
    if risk:
        if risk.get("available"):
            facts.append(f"风险说明采用训练期{risk.get('sample_hours',0)}个小时的残差描述，电量误差范围{number(risk.get('lower_error_mwh'),'MWh')}至{number(risk.get('upper_error_mwh'),'MWh')}；这是历史误差描述，未经独立区间覆盖率校准，不是未来损失保证。")
        else:
            facts.append("保存方案没有可用的训练期误差描述，不补造风险区间或风险评级。")
    if settlement:
        actual, comparison = settlement["actual"], settlement["comparison"]
        facts.append(f"保存结算完成{actual.get('settled_hours',0)}/24小时，排除{actual.get('excluded_hours',0)}小时；结算金额{number(actual.get('value'),'元')}，同范围全实时对照{number(actual.get('reference'),'元')}，与全实时对照差额{number(actual.get('delta'),'元')}。缺失小时不补零，结果仍是区域历史研究口径。")
        facts.append(f"预计与实际可比{comparison.get('matched_hours',0)}小时，差额{number(comparison.get('delta'),'元')}；电量项{number(comparison.get('power_effect'),'元')}、价格项{number(comparison.get('price_effect'),'元')}、费用项{number(comparison.get('fee_effect'),'元')}。这是代数分解，不证明天气或设备因果。")
        tools.append(dict(name="核对保存的结算复盘", display_name="核对保存的结算复盘",
                          summary=f"按原观测快照结算{actual.get('settled_hours',0)}小时，金额{number(actual.get('value'),'元')}；不使用后来修订值替换。", output=settlement))
    if issue:
        state = business["state"]
        state_name = {"pending":"待调查", "in_progress":"处理中", "resolved":"待验证", "verified":"已验证"}.get(state["state"], "处理状态待核对")
        detail = state["detail"]
        facts.append(f"处理事项：{issue['reason']}。当前为{state_name}，声明处理人：{detail.get('owner') or issue.get('owner') or '尚未指定'}；此项不是新的预测或模型重训。")
        if detail.get("evidence"):
            facts.append("处理人追加的证据说明：" + detail["evidence"] + "。该声明与量化对照分开核验。")
        verification = detail.get("verification")
        if verification:
            facts.append(f"已保存核对的同范围结果差额{number(verification.get('delta'),'元')}；是否改善以该次对照结论为准，不能把处理完成等同于模型或收益已提升。")
        tools.append(dict(name="核对业务处理进展", display_name="核对业务处理进展",
                          summary="读取问题的原始证据快照和追加的处理状态；不把完成声明当成已核验效果。",
                          output=dict(issue=issue, state=business["state"])))
    return facts, tools
