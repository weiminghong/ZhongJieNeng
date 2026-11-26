"""Frozen research tasks over the existing regional source, never site telemetry."""

from datetime import date, timedelta
import math

PRICE_TASK = "rt_price_day_ahead_reference"
TASKS = {
    PRICE_TASK: dict(
        name="实时电价预测",
        unit="CNY/MWh",
        display_unit="元/MWh",
        target="rt_price",
        hourly=False,
        intraday=False,
    ),
    "pv_day_ahead_reference": dict(
        name="区域光伏日前预测",
        unit="MW",
        display_unit="MW",
        target="pv_actual_mw",
        hourly=False,
        intraday=False,
    ),
    "pv_intraday_reference": dict(
        name="区域光伏日内预测",
        unit="MW",
        display_unit="MW",
        target="pv_actual_mw",
        hourly=False,
        intraday=True,
    ),
    "da_price_reference": dict(
        name="日前小时电价预测",
        unit="CNY/MWh",
        display_unit="元/MWh",
        target="da_price",
        hourly=True,
        intraday=False,
    ),
    "prebid_spread_reference": dict(
        name="申报前小时价差预测",
        unit="CNY/MWh",
        display_unit="元/MWh",
        target="spread",
        hourly=True,
        intraday=False,
    ),
    "intraday_spread_reference": dict(
        name="日内小时价差预测",
        unit="CNY/MWh",
        display_unit="元/MWh",
        target="spread",
        hourly=True,
        intraday=True,
    ),
}
BASE_FEATURES = [
    "target_lag_2d",
    "target_lag_3d",
    "target_lag_7d",
    "target_mean_d2",
    "target_min_d2",
    "target_max_d2",
    "target_mean_d7",
    "slot_sin",
    "slot_cos",
    "weekday_sin",
    "weekday_cos",
    "month_sin",
    "month_cos",
]
INTRADAY_FEATURES = [
    "last_released_reference",
    "earlier_released_reference",
    "recent_released_mean",
]


def spec(task):
    if task not in TASKS:
        raise ValueError("未登记的预测任务")
    return TASKS[task]


def slots(task):
    return list(range(3, 96, 4)) if spec(task)["hourly"] else list(range(96))


def hour_value(day, slot, field):
    """Hour-end source rows, or four explicit quarters; never fill partial hours."""
    end = slot // 4 * 4 + 3
    values = [day.get(i, {}).get(field) for i in range(end - 3, end + 1)]
    if all(v is not None for v in values):
        return sum(values) / 4
    if (
        field == "da_price"
        and values[-1] is not None
        and all(v is None for v in values[:-1])
    ):
        return values[-1]
    return None


def target(task, day, slot):
    s = spec(task)
    if s["hourly"]:
        if slot % 4 != 3:
            return None
        da = hour_value(day, slot, "da_price")
        if s["target"] == "da_price":
            return da
        rt = hour_value(day, slot, "rt_price")
        return rt - da if rt is not None and da is not None else None
    return day.get(slot, {}).get(s["target"])


def features(days, day, slot, task):
    s = spec(task)
    d = date.fromisoformat(day)

    def previous(n):
        return days.get((d - timedelta(days=n)).isoformat(), {})

    def at(rows, i):
        value = target(task, rows, i)
        return float("nan") if value is None else value

    def values(n):
        return [
            v for i in slots(task) if (v := target(task, previous(n), i)) is not None
        ]

    d2, d7 = values(2), values(7)
    angles = [
        2 * math.pi * slot / 96,
        2 * math.pi * d.weekday() / 7,
        2 * math.pi * (d.month - 1) / 12,
    ]
    result = (
        [at(previous(n), slot) for n in (2, 3, 7)]
        + [
            sum(d2) / len(d2) if d2 else float("nan"),
            min(d2) if d2 else float("nan"),
            max(d2) if d2 else float("nan"),
            sum(d7) / len(d7) if d7 else float("nan"),
        ]
        + [v for a in angles for v in (math.sin(a), math.cos(a))]
    )
    if s["intraday"]:
        # Conservative event-time delay. Actual publication times remain unverified.
        lag = 8 if s["hourly"] else 5
        step = 4 if s["hourly"] else 1

        def recent(offset):
            absolute = slot - lag - offset
            prior_day = (d + timedelta(days=absolute // 96)).isoformat()
            return at(days.get(prior_day, {}), absolute % 96)

        recent_values = [recent(i * step) for i in range(4)]
        finite = [v for v in recent_values if math.isfinite(v)]
        result += [
            recent_values[0],
            recent_values[1],
            sum(finite) / len(finite) if finite else float("nan"),
        ]
    return result


def policy(task, legacy):
    s = spec(task)
    if task == PRICE_TASK:
        return legacy
    return dict(
        legacy,
        contract="cecep-public-multitask-v1",
        task=task,
        unit=s["unit"],
        features=BASE_FEATURES + (INTRADAY_FEATURES if s["intraday"] else []),
        target=s["target"],
        target_points=len(slots(task)),
        hourly=s["hourly"],
        intraday=s["intraday"],
        cutoff=(
            "rolling interval start; event-time observations delayed at least one hour"
            if s["intraday"]
            else legacy["cutoff"]
        ),
        initial_baseline=(
            "zero_spread"
            if s["target"] == "spread"
            else "recent_observation" if s["intraday"] else "seasonal_naive_d2"
        ),
        label_policy="Original signed power retained; DA native hour-end or four explicit quarters; spread uses complete-hour RT mean minus DA; no target imputation",
        retrain_alpha=10,
        seed=42,
    )


def seal(model):
    p = model["payload"]
    return (
        "final:" + model["source_hash"]
        if p["task"] == PRICE_TASK
        else "final:" + p["task"] + ":" + model["source_hash"]
    )


def notice(task):
    s = spec(task)
    text = "区域公开历史研究，不代表岚能或凌光生产能力；原始发布时间未核验。"
    if s["hourly"]:
        text += "按完整小时对齐；缺失小时不补标签。"
    if s["intraday"]:
        text += "逐时段滚动重演，仅使用至少一小时前的观测；不构成已验证的在线时点回测。"
    if s["unit"] == "MW":
        text += "源出力中的小幅负值保留并单独统计，计量边界尚未核验。"
    return text
