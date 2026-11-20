"""固定日期、固定种子的合成演示数据，未接入中节能真实生产数据。"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from functools import lru_cache

import numpy as np
import pandas as pd

from .adapters import solar_components

STATIONS = {
    "lanneng": {"name": "镇海岚能", "capacity": 112, "latitude": 29.96, "longitude": 121.65},
    "lingguang": {"name": "镇海凌光", "capacity": 82, "latitude": 29.96, "longitude": 121.64},
}
DATES = ["2026-11-19", "2026-11-20", "2026-11-21"]
DEMO_NOW = datetime(2026, 11, 20, 14, 0, tzinfo=timezone(timedelta(hours=8)))


def available_context() -> dict:
    return {
        "stations": [{"id": key, **value} for key, value in STATIONS.items()],
        "dates": DATES,
        "default_date": DATES[0],
        "source": "合成演示数据",
        "as_of": DEMO_NOW.isoformat(),
        "timezone": "Asia/Shanghai",
    }


@lru_cache(maxsize=12)
def records(station_id: str, selected_date: str) -> tuple[dict, ...]:
    station = STATIONS[station_id]
    seed = int(selected_date.replace("-", "")) + list(STATIONS).index(station_id)
    rng = np.random.default_rng(seed)
    index = pd.date_range(selected_date, periods=96, freq="15min", tz="Asia/Shanghai")
    hours = index.hour.to_numpy() + index.minute.to_numpy() / 60
    Site, clear_sky_power = solar_components()
    site = Site(
        name=station_id,
        latitude=station["latitude"],
        longitude=station["longitude"],
        timezone="Asia/Shanghai",
        altitude_m=10,
        tilt_deg=20,
        panel_area_m2=station["capacity"] * 1e6 / (0.18 * 0.8 * 1000),
    )
    physical = np.clip(clear_sky_power(site, index).to_numpy() / 1e6, 0, station["capacity"])
    cloud = np.clip(0.24 + 0.12 * np.sin(hours) + 0.48 * np.exp(-((hours - 12.5) / 0.8) ** 2), 0, 1)
    daytime = physical > 0.1
    actual = np.maximum(physical * (1 - cloud * 0.65) + rng.normal(0, 1.2, 96) * daytime, 0)
    original = np.maximum(physical * (1 - cloud * 0.38) + 0.6 * np.sin(hours) * daytime, 0)
    corrected = np.maximum(physical * (1 - cloud * 0.56) + 0.35 * np.cos(hours) * daytime, 0)
    temperature = 15 + np.maximum(0, 7 * np.sin((hours - 7) / 13 * np.pi))
    da_price = 365 + 58 * np.cos((hours - 19) / 24 * 2 * np.pi) - 125 * np.exp(-((hours - 12) / 2.2) ** 2)
    rt_price = da_price + 25 * np.sin(hours * 1.5) + rng.normal(0, 9, 96)
    da_pred = da_price + 16 * np.sin(hours * 1.1) + 8
    rt_pred = da_price + 20 * np.sin(hours * 1.5)
    previous_date = (date.fromisoformat(selected_date) - timedelta(days=1)).isoformat()
    rows = []
    for i, timestamp in enumerate(index):
        observed = timestamp.to_pydatetime() + timedelta(minutes=15) <= DEMO_NOW
        missing_actual = observed and i == 39
        corrected_available = timestamp.hour >= 10 and date.fromisoformat(selected_date) <= DEMO_NOW.date()
        rows.append({
            "time": timestamp.strftime("%H:%M"),
            "timestamp": timestamp.isoformat(),
            "actual": None if not observed or missing_actual else round(float(actual[i]), 2),
            "forecast": round(float(original[i]), 2),
            "corrected": round(float(corrected[i]), 2) if corrected_available else None,
            "physical": round(float(physical[i]), 2),
            "irradiance": None if i == 48 or not observed else round(float(actual[i] / station["capacity"] * 1000), 1),
            "cloud": round(float(cloud[i]), 2),
            "temperature": round(float(temperature[i]), 1),
            "availability": 1.0,
            "da_pred": round(float(da_pred[i]), 2),
            "da_price": round(float(da_price[i]), 2),
            "rt_price": round(float(rt_price[i]), 2) if observed else None,
            "rt_pred": round(float(rt_pred[i]), 2),
            "quality": "实发缺失" if missing_actual else "待实测" if not observed else "辐照度缺失" if i == 48 else "有效",
            "forecast_issued_at": previous_date + "T09:00:00+08:00",
            "correction_issued_at": selected_date + "T10:00:00+08:00" if corrected_available else None,
        })
    return tuple(rows)

