"""Read-only, purpose-specific checks; labels are not inference prerequisites."""

from datetime import date, timedelta
import numpy as np

from . import data_flow, learning as ml, task_catalog as tasks, public_data
from .serving import build_intervals


def inspect(store, view, mode="post", until="23:59"):
    source, day = view["source"], view["date"]
    points = view["points"]
    expected = len(tasks.slots(source["task"])) if source["domain"] == "market" else 96
    actual = sum(p["actual"] is not None for p in points)
    missing = sum(p["quality"] == "missing" for p in points)
    pending = sum(p["quality"] == "pending" for p in points)
    selected = next((m for m in view["models"] if m["id"] == view["model_id"]), None)
    reasons = []
    feature_rows = complete_features = missing_features = 0
    data_hours = usable_hours = 0
    supported = source["domain"] == "market" and source["task"] == "pv_day_ahead_reference"
    source_detail = []
    if not selected or not selected.get("can_predict"):
        reasons.append("尚未选择可执行预测的模型，或当前日期的预测资格受限。")
    if source["domain"] == "market":
        _, _, days = data_flow.source_version(store, view["metadata"]["source_hash"])
        rows = days.get(day, {})
        _, _, input_days = public_data.dataset()
        if day not in input_days:
            reasons.append("所选日期没有可读取的已归档输入。")
        if selected:
            payload = ml.get_object(store, selected["id"], "model")["payload"]
            tune = payload["splits"]["tune"]
            if day < tune[0] or (not tune[0] <= day <= tune[1] and
                    date.fromisoformat(day) <= date.fromisoformat(payload["selection_end"]) + timedelta(days=1)):
                reasons.append("日期尚未越过训练和选参边界；请选择合法研究推理日。")
            x = np.asarray([(ml.features_for(input_days, day, s) if source["task"] == ml.TASK else
                             tasks.features(input_days, day, s, source["task"])) for s in tasks.slots(source["task"])])
            if payload["algorithm"] == "controlled_optimization":
                from .optimized_models import input_data
                x = input_data(input_days, day, source["task"], payload["policy"])["x"]
            if mode == "replay" and tasks.spec(source["task"])["intraday"]:
                cursor = (int(until[:2])*60+int(until[3:]))//15
                grid = tasks.slots(source["task"])
                x = x[[s - (3 if tasks.spec(source["task"])["hourly"] else 0) < cursor for s in grid]]
            feature_rows = len(x)
            complete_features = int(np.isfinite(x).all(axis=1).sum())
            missing_features = int((~np.isfinite(x)).sum())
        visible = min(96, (int(until[:2]) * 60 + int(until[3:])) // 15) if mode == "replay" else 96
        byslot = {p["slot"]: p for p in points}
        da_hours = rt_hours = 0
        for end in range(3, 96, 4):
            if end >= visible:
                continue
            da = tasks.hour_value(rows, end, "da_price")
            rt = tasks.hour_value(rows, end, "rt_price")
            da_hours += da is not None
            rt_hours += rt is not None
            complete = da is not None and all(
                rows.get(s, {}).get("pv_actual_mw") is not None and rows.get(s, {}).get("rt_price") is not None
                for s in range(end-3, end+1))
            data_hours += complete
            usable_hours += bool(complete and supported and view["record_id"] and all(
                byslot.get(s, {}).get("predicted") is not None and byslot.get(s, {}).get("actual") is not None
                for s in range(end-3, end+1)))
        source_detail = [dict(name="日前小时价格", valid=da_hours, expected=24, unit="小时"),
                         dict(name="完整小时实时价格", valid=rt_hours, expected=24, unit="小时")]
        prediction_note = "新预测检查当前来源版本；已保存记录的实绩与结算仍按所选快照检查。缺失历史特征按模型训练期填补规则处理，目标日实绩与结算价格不作为日前预测前置条件。原始发布时间未核验，当前为历史研究口径。"
    else:
        intervals = build_intervals(store, source["station_id"], day, view["metadata"]["cutoff_at"], source["source_mode"])
        feature_rows = len(intervals)
        complete_features = sum(p.get("da_forecast_mw") is not None for p in intervals)
        if not complete_features:
            reasons.append("当前场站没有可用的日前预测输入快照；请先核对场站输入。")
        prediction_note = "检查场站已到达的预测输入；实绩用于事后核对，生产输入不以合成数据补齐。具体适配器仍在运行时校验输入。"
    can_predict = not reasons
    return dict(
        source_key=source["key"], date=day, task=source["task"], context_version=view["context_version"],
        prediction_inputs=dict(can_predict=can_predict, status="blocked" if reasons else "partial" if missing_features else "ready",
                               expected_periods=expected, feature_rows=feature_rows, complete_feature_rows=complete_features,
                               imputed_feature_rows=feature_rows-complete_features, missing_feature_values=missing_features,
                               reasons=reasons, summary="；".join(reasons) if reasons else "预测输入可用于运行；输入检查不会替代模型实际执行校验。", notice=prediction_note),
        observations=dict(status="ready" if actual == expected else "partial" if actual else "pending" if pending else "missing",
                          expected_periods=expected, actual_periods=actual, missing_periods=missing, pending_periods=pending,
                          paired_periods=view["metrics"]["n"], unit="小时" if expected == 24 else "时段",
                          summary=f"当前任务实际值{actual}/{expected}个{'小时' if expected == 24 else '时段'}；应到缺测{missing}，未来待到{pending}。"),
        settlement=dict(supported=supported, can_settle=usable_hours > 0, data_hours=data_hours,
                        usable_hours=usable_hours, expected_hours=24, excluded_hours=24-usable_hours,
                        summary=(f"已保存的光伏日前预测可对齐{usable_hours}个完整结算小时；不完整小时排除。" if supported and view["record_id"] else
                                 "请使用已保存的区域光伏日前预测进行量价结算；实绩与完整小时价格独立检查。"),
                        notice="这是历史研究量价口径，不含正式市场合约与考核规则。"),
        source_details=source_detail,
        notice="预测输入、实际值核对和结算完整性分别检查；小时日前价格按24个小时核验，不能把原始季度空位算作96点缺测。",
    )
