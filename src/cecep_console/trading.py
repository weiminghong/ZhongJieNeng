"""Deterministic demonstration settlement. No LLM arithmetic or hidden prices."""

import json
from .storage import encoded, digest
from .serving import build_intervals, data_clock, rows, day_bounds, now


def settle_interval(
    actual_mwh,
    bid_mwh,
    contract_mwh,
    contract_price,
    da_price,
    rt_price,
    tolerance_mwh,
    penalty_rate,
):
    values = (
        actual_mwh,
        bid_mwh,
        contract_mwh,
        contract_price,
        da_price,
        rt_price,
        tolerance_mwh,
        penalty_rate,
    )
    if any(v is None for v in values):
        raise ValueError("缺少结算输入，禁止以零代替缺失值")
    if min(actual_mwh, bid_mwh, contract_mwh, tolerance_mwh, penalty_rate) < 0:
        raise ValueError("电量/免考电量/考核单价必须非负")
    return {
        "contract": contract_mwh * contract_price,
        "day_ahead": (bid_mwh - contract_mwh) * da_price,
        "real_time": (actual_mwh - bid_mwh) * rt_price,
        "penalty": -max(0, abs(actual_mwh - bid_mwh) - tolerance_mwh) * penalty_rate,
    }


def simulate_plan(store, plan_id, *, cutoff=None, persist=False):
    plan = store.db.execute(
        "SELECT * FROM bidding_plan WHERE plan_id=?", (plan_id,)
    ).fetchone()
    if not plan:
        raise ValueError("申报方案不存在")
    plan = dict(plan)
    cutoff = cutoff or data_clock(store, plan["source_mode"])
    rule = store.db.execute(
        "SELECT * FROM rule_version WHERE rule_version_id=? AND available_at<=?",
        (plan["rule_version_id"], cutoff),
    ).fetchone()
    if not rule:
        raise ValueError("规则在当前 cutoff 不可见")
    rule = dict(rule)
    parameters = json.loads(rule["parameters_json"])
    if parameters.get("threshold_basis") != "capacity":
        raise ValueError("不支持的偏差阈值口径")
    start, end = day_bounds(plan["trading_date"])
    if rule["effective_from"] > start or (
        rule["effective_to"] and rule["effective_to"] < end
    ):
        raise ValueError("规则生效期不覆盖方案")
    configs = store.as_of(
        "station_config_version",
        cutoff,
        filters={"station_id": plan["station_id"]},
        target=start,
        allow_synthetic=plan["source_mode"] == "synthetic",
    )
    if len(configs) != 1:
        raise ValueError("场站容量配置不唯一")
    interval_map = {
        r["interval_start"]: r
        for r in build_intervals(
            store, plan["station_id"], plan["trading_date"], cutoff, plan["source_mode"]
        )
    }
    contracts = rows(
        store,
        "SELECT * FROM contract_position WHERE station_id=? AND market_location_id=? AND source_mode=? AND available_at<=? AND effective_from<=? AND (effective_to IS NULL OR effective_to>=?) ORDER BY revision_no DESC",
        (
            plan["station_id"],
            plan["market_location_id"],
            plan["source_mode"],
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
        (plan_id,),
    )
    totals = {k: 0.0 for k in ("contract", "day_ahead", "real_time", "penalty")}
    settled = []
    for item in items:
        evidence = interval_map.get(item["interval_start"])
        if evidence is None or any(
            evidence[k] is None for k in ("actual_mw", "da_price", "rt_price")
        ):
            continue
        contract = contract_map.get(item["interval_start"])
        if contract is None:
            raise ValueError("缺少分时合约，不能静默假定零合约")
        tolerance = configs[0]["capacity_ac_mw"] * parameters["exempt_fraction"] * 0.25
        components = settle_interval(
            evidence["actual_mw"] * 0.25,
            item["bid_energy_mwh"],
            contract["contract_energy_mwh"],
            contract["contract_price_yuan_mwh"],
            evidence["da_price"],
            evidence["rt_price"],
            tolerance,
            parameters["penalty_yuan_mwh"],
        )
        for key, value in components.items():
            totals[key] += value
        settled.append(
            {
                "interval_start": item["interval_start"],
                "interval_end": item["interval_end"],
                "components": components,
                "inputs": {
                    **item,
                    "actual_mwh": evidence["actual_mw"] * 0.25,
                    "contract_id": contract["contract_id"],
                    "contract_mwh": contract["contract_energy_mwh"],
                    "da_price": evidence["da_price"],
                    "rt_price": evidence["rt_price"],
                    "tolerance_mwh": tolerance,
                    "lineage_refs": json.loads(evidence["lineage_refs_json"]),
                },
            }
        )
    revenue_id = (
        "revenue-"
        + digest(
            {
                "plan_id": plan_id,
                "cutoff": cutoff,
                "rule": rule["rule_version_id"],
                "settled": settled,
            }
        )[:32]
    )
    if (
        persist
        and not store.db.execute(
            "SELECT 1 FROM revenue_run WHERE revenue_run_id=?", (revenue_id,)
        ).fetchone()
    ):
        snapshot = store.db.execute(
            "SELECT snapshot_id FROM prediction_run WHERE run_id=?",
            (plan["power_run_id"],),
        ).fetchone()[0]
        store.append(
            "revenue_run",
            dict(
                revenue_run_id=revenue_id,
                station_id=plan["station_id"],
                rule_version_id=plan["rule_version_id"],
                snapshot_id=snapshot,
                period_start=start,
                period_end=end,
                scenario_name=plan["plan_name"],
                status="observed_partial" if len(settled) < len(items) else "complete",
                source_mode=plan["source_mode"],
                created_at=now(),
            ),
        )
        for entry in settled:
            for component, amount in entry["components"].items():
                store.append(
                    "revenue_item",
                    dict(
                        revenue_item_id=digest(
                            {
                                "run": revenue_id,
                                "start": entry["interval_start"],
                                "component": component,
                            }
                        ),
                        revenue_run_id=revenue_id,
                        interval_start=entry["interval_start"],
                        interval_end=entry["interval_end"],
                        component=component,
                        energy_mwh=entry["inputs"]["actual_mwh"],
                        price_yuan_mwh=(
                            parameters["penalty_yuan_mwh"]
                            if component == "penalty"
                            else entry["inputs"]["rt_price"]
                        ),
                        amount_yuan=amount,
                        calculation_json=encoded(
                            {
                                "engine_version": "settlement-v1",
                                "rule_version_id": rule["rule_version_id"],
                                **entry["inputs"],
                            }
                        ),
                    ),
                )
    return {
        **plan,
        "revenue_run_id": revenue_id,
        "components": totals,
        "net_revenue_yuan": sum(totals.values()) if settled else None,
        "settled_count": len(settled),
        "unsettled_count": len(items) - len(settled),
        "scope": "仅已到达实测与结算价的配对时段",
        "items": items,
        "rule": parameters,
        "rule_version_id": rule["rule_version_id"],
        "contract_summary": {
            "record_count": len(contract_map),
            "registered_energy_mwh": sum(c["contract_energy_mwh"] for c in contract_map.values()) if contract_map else None,
            "price_min_yuan_mwh": min((c["contract_price_yuan_mwh"] for c in contract_map.values()), default=None),
            "price_max_yuan_mwh": max((c["contract_price_yuan_mwh"] for c in contract_map.values()), default=None),
            "basis": "目标日已登记且在截止时点可见的分时合约；不等同已结算电量",
        },
        "cutoff_at": cutoff,
        "warning": (
            "合成演示沙盘；±5% 容量免考为示例口径，非真实市场结算规则"
            if plan["source_mode"] == "synthetic"
            else None
        ),
    }


def trading_overview(
    store, station_id, day, source_mode="synthetic", cutoff=None, persist=False
):
    plans = rows(
        store,
        "SELECT plan_id FROM bidding_plan WHERE station_id=? AND trading_date=? AND source_mode=? ORDER BY plan_name",
        (station_id, day, source_mode),
    )
    return {
        "plans": [
            simulate_plan(store, p["plan_id"], cutoff=cutoff, persist=persist)
            for p in plans
        ],
        "engine": "deterministic_settlement_v1",
        "source_mode": source_mode,
    }
