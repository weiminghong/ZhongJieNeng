"""Append-only proactive briefs from PIT signals and deterministic settlement."""

import json
from datetime import date, timedelta
from types import SimpleNamespace
from uuid import uuid4
from .model_runtime import run_model_inference
from .serving import build_intervals, daily_kpi, day_bounds, now, rows
from .storage import encoded, instant
from .workbench_analytics import trading_sandbox


def forecast_sandbox(store, scope, cutoff, intervals, base, scenario):
    args = SimpleNamespace(**{**scope, "plan_id": None, "bid_multiplier": 1.0,
                              "exempt_fraction": 0.05, "penalty_yuan_mwh": None})
    before = trading_sandbox(store, args, cutoff, intervals, forecast_points=base["points"])
    after = trading_sandbox(store, args, cutoff, intervals, forecast_points=scenario["points"])
    b, a = before["simulated"], after["simulated"]
    return dict(baseline=b, simulated=a, settled_count=after["settled_count"], unsettled_count=after["unsettled_count"],
                delta_net_revenue_yuan=a["net_revenue_yuan"]-b["net_revenue_yuan"] if a["net_revenue_yuan"] is not None else None,
                delta_penalty_yuan=a["components"]["penalty"]-b["components"]["penalty"] if a["components"]["penalty"] is not None else None,
                warning="以相同已到达实测与电价比较两条预测的假设申报；±5%仅演示规则，不外推未来收益")


def run_proactive_analysis(store, scope, trigger_type="manual_scan"):
    if trigger_type not in {"manual_scan", "scheduled_watchdog", "data_arrival"}:
        raise ValueError("未知主动研判触发类型")
    station, day, source = scope["station_id"], scope["date"], scope["source_mode"]
    cutoff = instant(scope["cutoff_at"])
    intervals = build_intervals(store, station, day, cutoff, source, registry_cutoff=cutoff)
    config = store.as_of("station_config_version", cutoff, filters={"station_id": station}, target=day_bounds(day)[0], allow_synthetic=source == "synthetic")
    config = [c for c in config if (c["availability_basis"] == "synthetic") == (source == "synthetic")]
    if len(config) != 1:
        raise ValueError("场站容量配置不唯一")
    capacity = config[0]["capacity_ac_mw"]
    deviation = [dict(interval_start=r["interval_start"], error_mw=r["actual_mw"]-r["da_forecast_mw"])
                 for r in intervals if r["actual_mw"] is not None and r["da_forecast_mw"] is not None
                 and abs(r["actual_mw"]-r["da_forecast_mw"]) > capacity*0.05]
    extreme = [dict(interval_start=r["interval_start"], spread_yuan_mwh=r["spread_yuan_mwh"])
               for r in intervals if r["spread_yuan_mwh"] is not None and abs(r["spread_yuan_mwh"]) >= 300]
    spreads = [r["spread_yuan_mwh"] for r in intervals if r["spread_yuan_mwh"] is not None]
    drift = rows(store, "SELECT * FROM drift_check_run WHERE station_id=? AND source_mode=? AND created_at<=? ORDER BY created_at DESC LIMIT 1", (station, source, cutoff))
    missing = [r["interval_start"] for r in intervals if r["quality_flag"] == "missing"]
    signals = [dict(type="capacity_deviation", count=len(deviation), threshold_mw=capacity*0.05, intervals=deviation),
               dict(type="price_spread", count=len(extreme), threshold_yuan_mwh=300, intervals=extreme,
                    range_yuan_mwh=max(spreads)-min(spreads) if spreads else None),
               dict(type="drift", count=sum(d["drifted_feature_count"] for d in drift), records=drift),
               dict(type="missing", count=len(missing), intervals=missing)]
    registry_cutoff = cutoff if scope.get("mode") == "replay" else now()
    inference = run_model_inference(store, station_id=station, trading_date=day, cutoff_at=cutoff, source_mode=source, registry_cutoff=registry_cutoff)
    previous_day = (date.fromisoformat(day)-timedelta(days=1)).isoformat()
    previous = build_intervals(store, station, previous_day, cutoff, source, registry_cutoff=cutoff)
    paired = [(a, b) for a, b in zip(intervals, previous) if all(r["actual_mw"] is not None and r["da_forecast_mw"] is not None for r in (a, b))]
    if paired:
        current_mae = sum(abs(a["actual_mw"]-a["da_forecast_mw"]) for a, _ in paired)/len(paired)
        previous_mae = sum(abs(b["actual_mw"]-b["da_forecast_mw"]) for _, b in paired)/len(paired)
        signals[2]["matched_error_comparison"] = dict(current_mae=current_mae, previous_mae=previous_mae,
            paired_slots=len(paired), previous_day=previous_day, basis="相邻交易日相同时段可见配对；天气差异未控制，仅作复核信号")
        if current_mae > previous_mae*1.2 and current_mae-previous_mae > 0.1:
            signals[2]["count"] += 1
    defensive = run_model_inference(store, model_version_id=inference["model_version_id"], station_id=station, trading_date=day, cutoff_at=cutoff, source_mode=source, overrides={"cloud_delta_pct": 15}, registry_cutoff=registry_cutoff)
    try:
        sandbox = forecast_sandbox(store, scope, cutoff, intervals, inference, defensive)
    except ValueError as exc:
        sandbox = {"status": "unavailable", "reason": str(exc)}
    severity = "critical" if len(deviation) >= 8 or len(missing) >= 8 else "warning" if any(s["count"] for s in signals) else "info"
    headline = f"{len(deviation)} 个超阈偏差时段 · {len(extreme)} 个极端价差 · {len(missing)} 个应到缺测"
    summary = headline + "。已完成 PIT 小模型复算与云量+15个百分点防御申报沙盘。气象仅为同期线索，建议人工复核。"
    summary += " 合成演示输入与现场拟合不代表真实生产精度；±5%仅为演示规则。" if source == "synthetic" else " 生产输入现场拟合，尚未完成独立精度验收。"
    citations = [ref for r in intervals for ref in json.loads(r["lineage_refs_json"])]
    citations += [dict(table="drift_check_run", record_id=d["drift_run_id"], available_at=d["created_at"]) for d in drift]
    actions = dict(rsi_intervals=[d["interval_start"] for d in deviation], missing_intervals=missing,
                   suggested_action="复核异常时段并比较申报；不自动交易或写入训练集", sandbox=sandbox)
    brief = dict(brief_id=str(uuid4()), station_id=station, trading_date=day, cutoff_at=cutoff, source_mode=source,
                 trigger_type=trigger_type, severity=severity, headline=headline, summary_markdown=summary,
                 signals_json=encoded(signals), model_inference_json=encoded({k:v for k,v in inference.items() if k != "points"}),
                 recommended_action_json=encoded(actions), citations_json=encoded(citations), created_at=now())
    with store.db:
        store.append("agent_proactive_brief", brief)
    return {**brief, "signals": signals, "model_inference": json.loads(brief["model_inference_json"]), "recommended_action": actions, "citations": citations}


def latest_proactive_briefs(store, station_id, trading_date, source_mode, cutoff_at, limit=10):
    if not 1 <= limit <= 100:
        raise ValueError("limit 必须为 1..100")
    cutoff = instant(cutoff_at)
    briefs = rows(store, "SELECT * FROM agent_proactive_brief WHERE station_id=? AND trading_date=? AND source_mode=? AND cutoff_at<=? AND created_at<=? ORDER BY created_at DESC,rowid DESC LIMIT ?", (station_id, trading_date, source_mode, cutoff, cutoff, limit))
    for b in briefs:
        for name in ("signals", "model_inference", "recommended_action", "citations"):
            b[name] = json.loads(b[name+"_json"]) if b[name+"_json"] else None
    return briefs
