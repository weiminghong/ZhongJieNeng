"""Read models built exclusively from stored, point-in-time visible evidence."""

from datetime import datetime, timedelta, timezone
import json
import math
from .storage import instant, encoded

TZ = timezone(timedelta(hours=8))


def now():
    return instant(datetime.now(timezone.utc))


def rows(store, sql, args=()):
    return [dict(r) for r in store.db.execute(sql, args)]


def day_bounds(day):
    start = datetime.fromisoformat(day).replace(tzinfo=TZ)
    return instant(start), instant(start + timedelta(days=1))


def data_clock(store, source_mode="synthetic"):
    if source_mode == "synthetic":
        value = store.db.execute(
            "SELECT max(b.finished_at) FROM ingestion_batch b JOIN data_source s USING(source_id) WHERE s.source_type='synthetic'"
        ).fetchone()[0]
        if value:
            return value
    return now()


def metrics(actual, predicted):
    errors = [
        p - a for a, p in zip(actual, predicted) if a is not None and p is not None
    ]
    return {
        "mae": sum(map(abs, errors)) / len(errors) if errors else None,
        "rmse": math.sqrt(sum(x * x for x in errors) / len(errors)) if errors else None,
        "sample_count": len(errors),
    }


def build_intervals(
    store, station_id, day, cutoff, source_mode="synthetic", *, registry_cutoff=None
):
    """PIT path. Every displayed input and prediction is cut off before joining."""
    start, end = day_bounds(day)
    cutoff = instant(cutoff)
    synthetic = source_mode == "synthetic"

    def get(table, filters, **extra):
        result = store.as_of(
            table, cutoff, filters=filters, allow_synthetic=synthetic, **extra
        )
        if not synthetic:
            return result
        # Explicit scope prevents synthetic and production rows from pooling.
        return [r for r in result if r.get("availability_basis") == "synthetic"]

    stations = get("station", {"station_id": station_id})
    if len(stations) != 1:
        raise ValueError("场站在所选时点不可见")
    config = get("station_config_version", {"station_id": station_id}, target=start)
    actuals = get("station_actual", {"station_id": station_id}, start=start, end=end)
    forecasts = get(
        "station_forecast_snapshot",
        {"station_id": station_id, "forecast_type": "day_ahead"},
        start=start,
        end=end,
    )
    market = get(
        "station_market_binding",
        {"station_id": station_id, "confirmed_status": "confirmed"},
        target=start,
    )
    weather = get(
        "station_weather_binding",
        {"station_id": station_id, "confirmed_status": "confirmed"},
        target=start,
    )
    if len(market) > 1 or len(weather) > 1 or len(config) > 1:
        raise ValueError("场站映射/配置存在歧义，需先核验")
    prices = (
        get(
            "market_price",
            {"market_location_id": market[0]["market_location_id"]},
            start=start,
            end=end,
        )
        if market
        else []
    )
    observations = (
        get(
            "weather_observation",
            {"weather_location_id": weather[0]["weather_location_id"]},
            start=start,
            end=end,
        )
        if weather
        else []
    )
    weather_fc = (
        get(
            "weather_forecast",
            {"weather_location_id": weather[0]["weather_location_id"]},
            start=start,
            end=end,
        )
        if weather
        else []
    )
    events = get("station_operation_event", {"station_id": station_id})

    # Fail on ambiguous independent evidence rather than silently selecting a source.
    def indexed(items, key):
        result = {}
        for item in items:
            k = key(item)
            if k in result:
                raise ValueError("同一时段有多个独立来源，需明确映射后再展示")
            result[k] = item
        return result

    actual_map = indexed(actuals, lambda r: r["interval_start"])
    forecast_map = indexed(forecasts, lambda r: r["target_start"])
    price_map = indexed(prices, lambda r: (r["interval_start"], r["market_stage"]))
    obs_map = indexed(observations, lambda r: r["interval_start"])
    weather_map = indexed(weather_fc, lambda r: r["target_start"])
    versions = {
        r["run_id"]: r
        for r in rows(
            store,
            "SELECT r.*,m.version,m.model_name FROM prediction_run r JOIN model_version m USING(model_version_id) WHERE r.station_id=?",
            (station_id,),
        )
    }
    from .rsi import model_states

    active = next(
        (
            m["model_version_id"]
            for m in model_states(store, registry_cutoff)
            if m["model_name"] == "lgbm-demo"
            and m["source_mode"] == source_mode
            and m["effective_status"] == "production"
        ),
        "lgbm-demo-v2.1",
    )
    predictions = {}
    for task in (
        "day_ahead_power",
        "intraday_power",
        "day_ahead_price",
        "intraday_spread",
    ):
        for p in store.predictions(
            station_id, task, start, end, cutoff, allow_synthetic=synthetic
        ):
            if p["source_mode"] != source_mode:
                continue
            version = versions[p["run_id"]]
            role = (
                "compare"
                if version["version"] == "2.0"
                else "main" if version["model_version_id"] == active else "other"
            )
            if task != "day_ahead_power":
                role = "main"
            if task == "day_ahead_power" and role == "other":
                continue
            predictions[(task, role, p["target_start"])] = p
    physical = [None] * 96
    if config:
        import pandas as pd
        from .adapters import solar_components

        Site, clear_sky = solar_components()
        station, capacity = stations[0], config[0]["capacity_ac_mw"]
        site = Site(
            name=station_id,
            latitude=station["latitude"],
            longitude=station["longitude"],
            timezone="Asia/Shanghai",
            altitude_m=10,
            tilt_deg=20,
            panel_area_m2=capacity * 1e6 / (0.18 * 0.8 * 1000),
        )
        physical = [
            round(min(capacity, max(0, float(v) / 1e6)), 2)
            for v in clear_sky(
                site, pd.date_range(day, periods=96, freq="15min", tz="Asia/Shanghai")
            )
        ]
    result = []
    for i in range(96):
        a = instant(
            datetime.fromisoformat(start.replace("Z", "+00:00"))
            + timedelta(minutes=15 * i)
        )
        b = instant(
            datetime.fromisoformat(a.replace("Z", "+00:00")) + timedelta(minutes=15)
        )
        actual, fc = actual_map.get(a, {}), forecast_map.get(a, {})
        obs, wfc = obs_map.get(a, {}), weather_map.get(a, {})
        da, rt = price_map.get((a, "day_ahead"), {}), price_map.get(
            (a, "real_time"), {}
        )
        power = predictions.get(("day_ahead_power", "main", a), {})
        compare = predictions.get(("day_ahead_power", "compare", a), {})
        corrected = predictions.get(("intraday_power", "main", a), {})
        dp = predictions.get(("day_ahead_price", "main", a), {})
        sp = predictions.get(("intraday_spread", "main", a), {})
        refs = []
        for table, item, pk in [
            ("station_actual", actual, "actual_id"),
            ("station_forecast_snapshot", fc, "forecast_snapshot_id"),
            ("weather_observation", obs, "observation_id"),
            ("weather_forecast", wfc, "weather_forecast_id"),
            ("market_price", da, "price_id"),
            ("market_price", rt, "price_id"),
        ]:
            if item:
                refs.append(
                    {
                        "table": table,
                        "record_id": item[pk],
                        "available_at": item["available_at"],
                    }
                )
        for item in (power, compare, corrected, dp, sp):
            if item:
                refs.append(
                    {
                        "table": "prediction_value",
                        "record_id": item["prediction_id"],
                        "run_id": item["run_id"],
                        "available_at": item["available_at"],
                    }
                )
        matched_events = [
            e
            for e in events
            if e["effective_start"] < b
            and (e.get("effective_end") is None or e["effective_end"] > a)
        ]
        refs.extend(
            {
                "table": "station_operation_event",
                "record_id": e["event_revision_id"],
                "available_at": e["available_at"],
            }
            for e in matched_events
        )
        av, dv, rv = (
            actual.get("power_mw"),
            da.get("price_yuan_mwh"),
            rt.get("price_yuan_mwh"),
        )
        row = dict(
            station_id=station_id,
            interval_start=a,
            interval_end=b,
            trading_date=day,
            source_mode=source_mode,
            actual_mw=av,
            physical_clear_sky_mw=physical[i],
            da_forecast_mw=power.get("value", fc.get("forecast_power_mw")),
            compare_forecast_mw=compare.get("value"),
            id_corrected_mw=corrected.get("value"),
            lower_mw=power.get("lower_value"),
            upper_mw=power.get("upper_value"),
            da_pred_price=dp.get("value"),
            da_price=dv,
            rt_pred_price=dv + sp["value"] if dv is not None and sp else None,
            rt_price=rv,
            spread_yuan_mwh=rv - dv if rv is not None and dv is not None else None,
            ghi_wm2=obs.get("ghi_wm2"),
            air_temp_c=obs.get("air_temperature_c", wfc.get("air_temperature_c")),
            cloud_cover_pct=obs.get("cloud_cover_pct", wfc.get("cloud_cover_pct")),
            active_event_flag=int(bool(matched_events)),
            quality_flag=(
                "valid" if av is not None else "missing" if b <= cutoff else "pending"
            ),
            lineage_refs_json=encoded(refs),
            refreshed_at=now(),
        )
        result.append(row)
    return result


def daily_kpi(intervals, cutoff):
    paired = [
        r
        for r in intervals
        if r["actual_mw"] is not None and r["da_forecast_mw"] is not None
    ]
    m = metrics([r["actual_mw"] for r in paired], [r["da_forecast_mw"] for r in paired])
    spreads = [
        r["spread_yuan_mwh"] for r in intervals if r["spread_yuan_mwh"] is not None
    ]
    prices = [
        abs(r["rt_price"] - r["rt_pred_price"])
        for r in intervals
        if r["rt_price"] is not None and r["rt_pred_price"] is not None
    ]
    worst = max(
        paired, key=lambda r: abs(r["actual_mw"] - r["da_forecast_mw"]), default=None
    )
    return dict(
        energy_actual_mwh=(
            sum(r["actual_mw"] * 0.25 for r in intervals if r["actual_mw"] is not None)
            if paired
            else None
        ),
        energy_forecast_matched_mwh=(
            sum(r["da_forecast_mw"] * 0.25 for r in paired) if paired else None
        ),
        power_mae_mw=m["mae"],
        power_rmse_mw=m["rmse"],
        price_mae=sum(prices) / len(prices) if prices else None,
        avg_spread=sum(spreads) / len(spreads) if spreads else None,
        max_abs_spread=max(map(abs, spreads), default=None),
        observed_count=len(paired),
        due_count=sum(r["interval_end"] <= cutoff for r in intervals),
        missing_count=sum(r["quality_flag"] == "missing" for r in intervals),
        worst_interval_json=encoded(worst),
        estimated_net_revenue_yuan=None,
        estimated_penalty_yuan=None,
    )


def compare_versions(store, station_id, day, cutoff, source_mode="synthetic"):
    start, end = day_bounds(day)
    ps = store.predictions(
        station_id,
        "day_ahead_power",
        start,
        end,
        cutoff,
        allow_synthetic=source_mode == "synthetic",
    )
    actuals = store.as_of(
        "station_actual",
        cutoff,
        filters={"station_id": station_id},
        start=start,
        end=end,
        allow_synthetic=source_mode == "synthetic",
    )
    actual = {
        r["interval_start"]: r["power_mw"]
        for r in actuals
        if r["availability_basis"]
        == ("synthetic" if source_mode == "synthetic" else r["availability_basis"])
        and r["power_mw"] is not None
    }
    runs = rows(
        store,
        "SELECT r.*,m.version,m.model_name FROM prediction_run r JOIN model_version m USING(model_version_id) WHERE r.station_id=? AND r.task='day_ahead_power' AND r.source_mode=? AND r.available_at<=? AND r.target_start>=? AND r.target_end<=? ORDER BY m.version",
        (station_id, source_mode, cutoff, start, end),
    )
    grouped = {
        r["run_id"]: {p["target_start"]: p for p in ps if p["run_id"] == r["run_id"]}
        for r in runs
    }
    result = []
    # Exact same cutoff and target interval; shared valid actual mask across all versions.
    cohorts = {}
    for run in runs:
        cohorts.setdefault(
            (run["cutoff_at"], run["target_start"], run["target_end"]), []
        ).append(run)
    for _, cohort in cohorts.items():
        matched = set(actual)
        for run in cohort:
            matched &= set(grouped[run["run_id"]])
        for run in cohort:
            m = metrics(
                [actual[k] for k in sorted(matched)],
                [grouped[run["run_id"]][k]["value"] for k in sorted(matched)],
            )
            result.append(
                {
                    **run,
                    **m,
                    "comparison_basis": "同 cutoff 对比",
                    "matched_intervals": sorted(matched),
                    "values": [
                        {"interval_start": k, "value": p["value"]}
                        for k, p in sorted(grouped[run["run_id"]].items())
                    ],
                }
            )
    return result


def refresh_serving_tables(store, station_id=None):
    """Idempotent per station/day, atomic with the caller's transaction."""
    args = (station_id,) if station_id else ()
    scopes = rows(
        store,
        "SELECT DISTINCT station_id,substr(datetime(target_start,'+8 hours'),1,10) AS day,source_mode FROM prediction_run"
        + (" WHERE station_id=?" if station_id else ""),
        args,
    )

    def insert(table, record):
        store.db.execute(
            f"INSERT INTO {table} ({','.join(record)}) VALUES ({','.join('?' for _ in record)})",
            list(record.values()),
        )

    for scope in scopes:
        station, day, mode = scope["station_id"], scope["day"], scope["source_mode"]
        cutoff = data_clock(store, mode)
        intervals = build_intervals(store, station, day, cutoff, mode)
        for table in ("serving_interval_wide", "serving_daily_kpi"):
            store.db.execute(
                f"DELETE FROM {table} WHERE station_id=? AND trading_date=? AND source_mode=?",
                (station, day, mode),
            )
        for r in intervals:
            insert("serving_interval_wide", r)
        kpi = daily_kpi(intervals, cutoff)
        revenue = store.db.execute(
            "SELECT sum(i.amount_yuan),sum(CASE WHEN i.component='penalty' THEN -i.amount_yuan ELSE 0 END) FROM revenue_item i JOIN revenue_run r USING(revenue_run_id) WHERE r.revenue_run_id=(SELECT revenue_run_id FROM revenue_run WHERE station_id=? AND scenario_name LIKE '%基准%' AND period_start=? ORDER BY created_at DESC,revenue_run_id DESC LIMIT 1)",
            (station, day_bounds(day)[0]),
        ).fetchone()
        kpi.update(
            estimated_net_revenue_yuan=revenue[0], estimated_penalty_yuan=revenue[1]
        )
        insert(
            "serving_daily_kpi",
            dict(
                station_id=station,
                trading_date=day,
                scope="all",
                source_mode=mode,
                **kpi,
                refreshed_at=now(),
            ),
        )
        store.db.execute(
            "DELETE FROM serving_version_compare WHERE station_id=? AND date_start=? AND source_mode=?",
            (station, day, mode),
        )
        comparisons = compare_versions(store, station, day, cutoff, mode)
        if comparisons:
            base = next(
                (r for r in comparisons if r["version"] == "2.1"), comparisons[0]
            )
            for other in comparisons:
                if other["cutoff_at"] != base["cutoff_at"]:
                    continue
                insert(
                    "serving_version_compare",
                    dict(
                        compare_key=f'{station}:{day}:{mode}:{other["run_id"]}',
                        task="day_ahead_power",
                        station_id=station,
                        date_start=day,
                        date_end=day,
                        run_a_id=base["run_id"],
                        run_b_id=other["run_id"],
                        scope="same_cutoff",
                        matched_sample_count=other["sample_count"],
                        metrics_a_json=encoded(base),
                        metrics_b_json=encoded(other),
                        delta_json=encoded(
                            {
                                "mae": (
                                    other["mae"] - base["mae"]
                                    if other["mae"] is not None
                                    and base["mae"] is not None
                                    else None
                                )
                            }
                        ),
                        top_diff_intervals_json="[]",
                        source_mode=mode,
                        refreshed_at=now(),
                    ),
                )
    return {"refreshed_scopes": len(scopes), "query_path": "serving_*"}
