"""Read-only analytical projections and deterministic in-memory settlement."""

from collections import defaultdict
from datetime import datetime
import json
import math

from .serving import TZ, rows, build_intervals, daily_kpi, power_metrics, day_bounds
from .trading import settle_interval


def hour(row):
    return (
        datetime.fromisoformat(row["interval_start"].replace("Z", "+00:00"))
        .astimezone(TZ)
        .hour
    )


def mean(values):
    valid = [v for v in values if v is not None]
    return sum(valid) / len(valid) if valid else None


def price_summary(items):
    return {
        k: mean([r.get(k) for r in items])
        for k in ("da_price", "rt_price", "spread_yuan_mwh")
    }


def multi_day(store, scope, cutoff):
    if scope.mode == "replay":
        # Discover dates only from evidence available then, never from present-day caches.
        dates = set()
        for table, target in (
            ("station_actual", "interval_start"),
            ("station_forecast_snapshot", "target_start"),
        ):
            dates.update(
                r["day"]
                for r in rows(
                    store,
                    f"""
                SELECT DISTINCT substr(datetime({target},'+8 hours'),1,10) AS day
                FROM {table} WHERE station_id=? AND available_at<=?
                AND (availability_basis='synthetic')=?""",
                    (scope.station_id, cutoff, int(scope.source_mode == "synthetic")),
                )
            )
        dates.update(
            r["day"]
            for r in rows(
                store,
                """
            SELECT DISTINCT substr(datetime(target_start,'+8 hours'),1,10) AS day
            FROM prediction_run WHERE station_id=? AND source_mode=? AND available_at<=?""",
                (scope.station_id, scope.source_mode, cutoff),
            )
        )
        grouped = {
            d: build_intervals(
                store,
                scope.station_id,
                d,
                cutoff,
                scope.source_mode,
                registry_cutoff=cutoff,
            )
            for d in sorted(dates)
        }
        cached = {}
        path = "pit_engine: Store.as_of + Store.predictions"
    else:
        grouped = defaultdict(list)
        for row in rows(
            store,
            """SELECT * FROM serving_interval_wide
                WHERE station_id=? AND source_mode=? ORDER BY interval_start""",
            (scope.station_id, scope.source_mode),
        ):
            grouped[row["trading_date"]].append(row)
        cached = {
            r["trading_date"]: r
            for r in rows(
                store,
                """
            SELECT * FROM serving_daily_kpi WHERE station_id=? AND source_mode=? AND scope='all'""",
                (scope.station_id, scope.source_mode),
            )
        }
        path = "serving_interval_wide + serving_daily_kpi"
    days, series, cells = [], [], []
    for day, items in sorted(grouped.items()):
        kpi = {**cached.get(day, {}), **daily_kpi(items, cutoff)}
        days.append(
            {
                "trading_date": day,
                **{
                    k: kpi[k]
                    for k in (
                        "energy_actual_mwh",
                        "energy_forecast_matched_mwh",
                        "power_mae_mw",
                        "power_rmse_mw",
                        "mbe_mw",
                        "avg_spread",
                        "observed_count",
                        "due_count",
                    )
                },
            }
        )
        series.extend(items)
        for h in range(24):
            cells.append(
                {
                    "trading_date": day,
                    "hour": h,
                    **price_summary([r for r in items if hour(r) == h]),
                }
            )
    periods = []
    definitions = [
        ("谷段", "00:00–08:00", set(range(8))),
        ("午峰光伏主力", "09:00–16:00", set(range(9, 16))),
        ("晚峰", "17:00–21:00", set(range(17, 21))),
        ("平段", "其余时段", {8, 16, 21, 22, 23}),
    ]
    for name, window, hours in definitions:
        subset = [r for r in series if hour(r) in hours]
        periods.append(
            {
                "name": name,
                "window": window,
                **price_summary(subset),
                "sample_count": sum(r["spread_yuan_mwh"] is not None for r in subset),
            }
        )
    spreads = [r for r in series if r["spread_yuan_mwh"] is not None]

    def extreme(sign):
        subset = [r for r in spreads if sign * r["spread_yuan_mwh"] > 0]
        best = max(subset, key=lambda r: sign * r["spread_yuan_mwh"], default=None)
        return (
            {k: best[k] for k in ("interval_start", "trading_date", "spread_yuan_mwh")}
            if best
            else None
        )

    da_pairs = [
        r
        for r in series
        if r["da_pred_price"] is not None and r["da_price"] is not None
    ]
    spread_pairs = [
        r
        for r in spreads
        if r["rt_pred_price"] is not None and r["da_price"] is not None
    ]

    def sign(v):
        return (v > 0) - (v < 0)

    backtest = {
        "da_price_mae": mean(
            [abs(r["da_price"] - r["da_pred_price"]) for r in da_pairs]
        ),
        "spread_direction_accuracy_pct": mean(
            [
                100
                * (
                    sign(r["rt_pred_price"] - r["da_price"])
                    == sign(r["spread_yuan_mwh"])
                )
                for r in spread_pairs
            ]
        ),
        "sample_count": len(spread_pairs),
        "da_price_sample_count": len(da_pairs),
        "basis": "可见预测与实测配对；零价差仅与零方向匹配",
    }

    def bucket(name, subset):
        m = power_metrics(subset)
        paired = [
            r
            for r in subset
            if r["actual_mw"] is not None and r["da_forecast_mw"] is not None
        ]
        return {
            "name": name,
            **{k: m[k] for k in ("sample_count", "mae", "rmse", "mbe")},
            "avg_actual_mw": mean([r["actual_mw"] for r in paired]),
        }

    weather = [
        bucket(
            name,
            [
                r
                for r in series
                if r["cloud_cover_pct"] is not None and lo <= r["cloud_cover_pct"] < hi
            ],
        )
        for name, lo, hi in (
            ("晴朗 (<25%)", 0, 25),
            ("少云 (25%–60%)", 25, 60),
            ("多云阴天 (≥60%)", 60, 101),
        )
    ]
    times = [
        bucket(name, [r for r in series if lo <= hour(r) < hi])
        for name, lo, hi in (
            ("06–09 爬坡", 6, 9),
            ("09–12 上午", 9, 12),
            ("12–15 午峰", 12, 15),
            ("15–18 退坡", 15, 18),
        )
    ]
    return {
        "days": days,
        "series": series,
        "price_heatmap": {
            "dates": sorted(grouped),
            "hours": list(range(24)),
            "cells": cells,
        },
        "price_periods": {
            "periods": periods,
            "max_positive": extreme(1),
            "max_negative": extreme(-1),
            "price_backtest": backtest,
        },
        "weather_buckets": weather,
        "time_buckets": times,
        "query_path": path,
        "source_mode": scope.source_mode,
        "cutoff_at": cutoff,
    }


def trading_sandbox(store, scope, cutoff, intervals, forecast_points=None):
    plans = rows(
        store,
        """SELECT * FROM bidding_plan WHERE station_id=? AND trading_date=?
        AND source_mode=? AND created_at<=? ORDER BY CASE WHEN plan_name LIKE '%基准%' THEN 0 ELSE 1 END,plan_id""",
        (scope.station_id, scope.date, scope.source_mode, cutoff),
    )
    plan = next(
        (p for p in plans if scope.plan_id is None or p["plan_id"] == scope.plan_id),
        None,
    )
    if not plan:
        raise ValueError("当前范围与时点没有可用申报方案")
    rule = store.db.execute(
        "SELECT * FROM rule_version WHERE rule_version_id=? AND available_at<=?",
        (plan["rule_version_id"], cutoff),
    ).fetchone()
    if not rule:
        raise ValueError("规则在当前时点不可见")
    start, end = day_bounds(scope.date)
    if rule["effective_from"] > start or (
        rule["effective_to"] and rule["effective_to"] < end
    ):
        raise ValueError("规则生效期不覆盖方案")
    parameters = json.loads(rule["parameters_json"])
    if parameters.get("threshold_basis") != "capacity":
        raise ValueError("不支持的偏差阈值口径")
    configs = store.as_of(
        "station_config_version",
        cutoff,
        filters={"station_id": scope.station_id},
        target=start,
        allow_synthetic=scope.source_mode == "synthetic",
    )
    configs = [
        c
        for c in configs
        if (c["availability_basis"] == "synthetic")
        == (scope.source_mode == "synthetic")
    ]
    if len(configs) != 1:
        raise ValueError("场站容量配置不唯一")
    capacity = configs[0]["capacity_ac_mw"]
    contracts = rows(
        store,
        """SELECT * FROM contract_position WHERE station_id=? AND market_location_id=?
        AND source_mode=? AND available_at<=? AND effective_from<=? AND (effective_to IS NULL OR effective_to>=?)
        ORDER BY revision_no DESC""",
        (
            scope.station_id,
            plan["market_location_id"],
            scope.source_mode,
            cutoff,
            start,
            end,
        ),
    )
    contract_map = {}
    for c in contracts:
        contract_map.setdefault(c["interval_start"], c)
    items = rows(
        store,
        "SELECT * FROM bidding_plan_item WHERE plan_id=? ORDER BY interval_start",
        (plan["plan_id"],),
    )
    visible = {r["interval_start"]: r for r in intervals}
    pairs = []
    for item in items:
        r = visible.get(item["interval_start"])
        if r is None or any(
            r[k] is None for k in ("actual_mw", "da_price", "rt_price")
        ):
            continue
        c = contract_map.get(item["interval_start"])
        if c is None:
            raise ValueError("缺少分时合约，不能静默假定零合约")
        pairs.append((item, r, c))

    scenario_bids = {p["interval_start"]: p["predicted_mw"] for p in (forecast_points or [])}

    def settle(multiplier, fraction, penalty, scenario=False):
        totals = {k: 0.0 for k in ("contract", "day_ahead", "real_time", "penalty")}
        exceeded = 0
        for item, r, c in pairs:
            actual, bid, tolerance = (
                r["actual_mw"] * 0.25,
                item["bid_energy_mwh"] * multiplier,
                capacity * fraction * 0.25,
            )
            if scenario and forecast_points is not None:
                if item["interval_start"] not in scenario_bids:
                    raise ValueError("小模型预测未覆盖沙盘时段")
                bid = scenario_bids[item["interval_start"]] * 0.25 * multiplier
            entry = settle_interval(
                actual,
                bid,
                c["contract_energy_mwh"],
                c["contract_price_yuan_mwh"],
                r["da_price"],
                r["rt_price"],
                tolerance,
                penalty,
            )
            for k, v in entry.items():
                totals[k] += v
            exceeded += abs(actual - bid) > tolerance
        return {
            "components": totals if pairs else {k: None for k in totals},
            "net_revenue_yuan": sum(totals.values()) if pairs else None,
            "exceeded_count": exceeded,
        }

    penalty = (
        scope.penalty_yuan_mwh
        if scope.penalty_yuan_mwh is not None
        else parameters["penalty_yuan_mwh"]
    )
    baseline = settle(1, parameters["exempt_fraction"], parameters["penalty_yuan_mwh"])
    simulated = settle(scope.bid_multiplier, scope.exempt_fraction, penalty, scenario=True)
    prices = [
        r["spread_yuan_mwh"] for r in intervals if r["spread_yuan_mwh"] is not None
    ]
    clouds = [
        r["cloud_cover_pct"]
        for r in intervals
        if r["cloud_cover_pct"] is not None and r["actual_mw"] is not None
    ]
    price_risk = (
        min(100, math.sqrt(mean([v * v for v in prices])) / 300 * 100)
        if prices
        else None
    )
    deviation_risk = simulated["exceeded_count"] / len(pairs) * 100 if pairs else None
    weather_risk = min(100, max(0, mean(clouds))) if clouds else None
    complete = all(v is not None for v in (price_risk, deviation_risk, weather_risk))
    score = (
        0.4 * price_risk + 0.3 * deviation_risk + 0.3 * weather_risk
        if complete
        else None
    )
    level = (
        ("低" if score < 25 else "中" if score < 50 else "较高" if score < 75 else "高")
        if score is not None
        else "数据不足"
    )
    matrix = [
        {
            "name": name,
            "score_range": f"{lo}–{hi}",
            "rule": rule,
            "active": score is not None and lo <= score and (score < hi or hi == 100),
            "source_mode": "synthetic",
        }
        for name, lo, hi, rule in (
            ("进攻型", 0, 25, "低风险参考：围绕基准适度增加报量"),
            ("标准型", 25, 50, "中风险参考：维持基准申报"),
            ("防御型", 50, 75, "较高风险参考：适度降低申报并复核偏差"),
            ("保守型", 75, 100, "高风险参考：降低风险敞口，优先人工复核"),
        )
    ]
    return {
        "plan_id": plan["plan_id"],
        "plan_name": plan["plan_name"],
        "parameters": {
            "bid_multiplier": scope.bid_multiplier,
            "exempt_fraction": scope.exempt_fraction,
            "penalty_yuan_mwh": penalty,
            "inherited_penalty": scope.penalty_yuan_mwh is None,
        },
        "baseline": baseline,
        "simulated": simulated,
        "delta_net_revenue_yuan": (
            simulated["net_revenue_yuan"] - baseline["net_revenue_yuan"]
            if pairs
            else None
        ),
        "delta_penalty_yuan": (
            simulated["components"]["penalty"] - baseline["components"]["penalty"]
            if pairs
            else None
        ),
        "settled_count": len(pairs),
        "unsettled_count": len(items) - len(pairs),
        "risk_assessment": {
            "price_risk": price_risk,
            "deviation_risk": deviation_risk,
            "weather_risk": weather_risk,
            "overall_score": score,
            "level": level,
            "basis": "价格40%：可见价差RMS/300封顶；偏差30%：沙盘超阈比例；天气30%：已观测时段平均云量。缺维度不评分。",
        },
        "strategy_matrix": matrix,
        "source_mode": scope.source_mode,
        "cutoff_at": cutoff,
        "warning": "合成演示沙盘口径与参考策略，非真实市场规则或投资建议；仅内存计算，不写入收益记录。",
    }
