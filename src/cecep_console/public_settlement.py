"""Deterministic, hourly public-data sandbox linked to saved PV predictions."""

from . import data_flow, task_catalog


def calculate_points(points, day_rows, bid_ratio=1, fee=0):
    byslot = {p["slot"]: p for p in points}
    hours = []
    negative = 0
    for end in range(3, 96, 4):
        group = [byslot.get(i) for i in range(end - 3, end + 1)]
        da = task_catalog.hour_value(day_rows, end, "da_price")
        if da is None or any(
            p is None
            or p["actual"] is None
            or p["predicted"] is None
            or p["rt_price"] is None
            for p in group
        ):
            continue
        bid = sum(max(p["predicted"], 0) * bid_ratio * 0.25 for p in group)
        actual = sum(p["actual"] * 0.25 for p in group)
        spot = sum(p["actual"] * 0.25 * p["rt_price"] for p in group)
        imbalance = sum(
            (p["actual"] - max(p["predicted"], 0) * bid_ratio) * 0.25 * p["rt_price"]
            for p in group
        )
        charges = sum(abs(p["actual"] * 0.25) * fee for p in group)
        negative += sum(p["actual"] < 0 for p in group)
        hours.append(
            dict(
                hour=end // 4,
                bid_mwh=bid,
                actual_mwh=actual,
                day_ahead_value=bid * da,
                imbalance_value=imbalance,
                fee=charges,
                value=bid * da + imbalance - charges,
                reference=spot - charges,
            )
        )
    return dict(
        hours=hours,
        settled_intervals=len(hours) * 4,
        excluded_intervals=96 - len(hours) * 4,
        negative_intervals=negative,
        value=sum(h["value"] for h in hours) if hours else None,
        reference=sum(h["reference"] for h in hours) if hours else None,
        delta=sum(h["value"] - h["reference"] for h in hours) if hours else None,
        bid_ratio=bid_ratio,
        fee=fee,
        rule="申报电量=max(所选日前预测出力,0)×申报系数×0.25小时；日前电量×小时均价+实时偏差电量×实时价−费用。",
        notice="区域公开数据的历史结算沙盘，不含正式合约和考核规则，不代表场站实际收益。保留源负出力并单独计数；不完整小时不结算。",
    )


def calculate(store, view, bid_ratio=1, fee=0):
    if view["source"]["task"] != "pv_day_ahead_reference" or not view["record_id"]:
        return None
    _, _, days = data_flow.source_version(store, view["metadata"]["source_hash"])
    return calculate_points(view["points"], days[view["date"]], bid_ratio, fee)
