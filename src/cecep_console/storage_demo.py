"""Persist the existing fixed synthetic scenario; never a real-source adapter."""

from datetime import datetime, timedelta, timezone
from uuid import uuid5, NAMESPACE_URL
import math
from .storage import instant, encoded, digest


def sid(value):
    return str(uuid5(NAMESPACE_URL, "cecep-demo-v1:" + value))


def seed_demo(store):
    from .data import STATIONS, DATES, DEMO_NOW, records

    source = "demo-scenario-v1"
    batch = "demo-scenario-v1-fixed"
    early = "2026-11-17T00:00:00+08:00"
    now = instant(DEMO_NOW)
    added = 0

    def put(table, row):
        nonlocal added
        added += store.append(table, row)

    def visible(**kwargs):
        return dict(
            available_at=early, availability_basis="synthetic", revision_no=0, **kwargs
        )

    def evidence(record_id, available):
        return dict(
            source_id=source,
            batch_id=batch,
            source_record_id=record_id,
            published_at=available,
            first_seen_at=available,
            available_at=available,
            availability_basis="synthetic",
            source_version="demo-scenario-v1",
            revision_no=0,
            quality_flag="valid",
            raw_record_ref="synthetic://existing-scenario/" + record_id,
            created_at=early,
        )

    with store.db:
        put(
            "data_source",
            dict(
                source_id=source,
                source_name="Existing synthetic scenario",
                source_type="synthetic",
                provider_name="cecep_console.data",
                data_scope="synthetic demonstration; not production or model evidence",
                default_timezone="Asia/Shanghai",
                expected_update_interval="15min",
                access_method="local deterministic generator",
                enabled=1,
                created_at=early,
            ),
        )
        put(
            "ingestion_batch",
            dict(
                batch_id=batch,
                source_id=source,
                dataset_name="existing-2station-3day-scenario-v1",
                started_at=early,
                finished_at=now,
                status="complete",
                record_count=576,
                file_hash=digest(
                    {"source": source, "dates": DATES, "seed": "date+station-index"}
                ),
                parser_version="storage-demo-v1",
            ),
        )
        put(
            "market_location",
            visible(
                market_location_id="demo-market",
                location_code="DEMO_ONLY",
                location_name="Synthetic market position, not verified Zhejiang node",
                location_type="synthetic",
                market_code="DEMO",
                timezone="Asia/Shanghai",
                effective_from=early,
            ),
        )
        for station, details in STATIONS.items():
            put(
                "station",
                visible(
                    station_id=station,
                    station_code=station,
                    station_name=details["name"],
                    station_type="photovoltaic",
                    province_code="DEMO",
                    latitude=details["latitude"],
                    longitude=details["longitude"],
                    timezone="Asia/Shanghai",
                    status="demo",
                    created_at=early,
                ),
            )
            put(
                "station_config_version",
                visible(
                    config_version_id=sid(station + "-config"),
                    station_id=station,
                    effective_from=early,
                    capacity_ac_mw=details["capacity"],
                    source_id=source,
                    published_at=early,
                    first_seen_at=early,
                ),
            )
            location = station + "-demo-weather"
            put(
                "weather_location",
                visible(
                    weather_location_id=location,
                    source_id=source,
                    location_code=location,
                    location_name=location,
                    location_type="synthetic",
                    latitude=details["latitude"],
                    longitude=details["longitude"],
                    measurement_plane="synthetic_ghi_proxy",
                    timezone="Asia/Shanghai",
                    status="demo",
                ),
            )
            put(
                "station_weather_binding",
                visible(
                    binding_id=sid(station + "-weather"),
                    station_id=station,
                    weather_location_id=location,
                    binding_role="forecast",
                    selection_method="synthetic_single_point",
                    effective_from=early,
                    confirmed_status="confirmed",
                    recorded_at=early,
                ),
            )
            put(
                "station_market_binding",
                visible(
                    binding_id=sid(station + "-market"),
                    station_id=station,
                    market_location_id="demo-market",
                    binding_role="price",
                    effective_from=early,
                    mapping_basis="synthetic only",
                    confirmed_status="confirmed",
                    recorded_at=early,
                ),
            )
            for day in DATES:
                for row in records(station, day):
                    start = datetime.fromisoformat(row["timestamp"])
                    end = start + timedelta(minutes=15)
                    target = instant(start)
                    end = instant(end)
                    key = station + "-" + target
                    if datetime.fromisoformat(end.replace("Z", "+00:00")) <= DEMO_NOW:
                        put(
                            "station_actual",
                            dict(
                                actual_id=sid(key + "-actual"),
                                station_id=station,
                                measurement_point_code="demo-point",
                                measurement_boundary="synthetic_station_ac",
                                interval_start=target,
                                interval_end=end,
                                sampling_method="interval_average",
                                power_mw=row["actual"],
                                generated_energy_mwh=(
                                    None
                                    if row["actual"] is None
                                    else row["actual"] * 0.25
                                ),
                                available_capacity_mw=details["capacity"],
                                **{
                                    **evidence(key + "-actual", end),
                                    "quality_flag": (
                                        "missing" if row["actual"] is None else "valid"
                                    ),
                                },
                            ),
                        )
                        put(
                            "weather_observation",
                            dict(
                                observation_id=sid(key + "-weather-obs"),
                                weather_location_id=location,
                                interval_start=target,
                                interval_end=end,
                                sampling_method="interval_average",
                                ghi_wm2=row["irradiance"],
                                air_temperature_c=row["temperature"],
                                cloud_cover_pct=100 * row["cloud"],
                                **evidence(key + "-weather-obs", end),
                            ),
                        )
                    put(
                        "station_forecast_snapshot",
                        dict(
                            forecast_snapshot_id=sid(key + "-da"),
                            station_id=station,
                            measurement_boundary="synthetic_station_ac",
                            forecast_type="day_ahead",
                            issued_at=row["forecast_issued_at"],
                            target_start=target,
                            target_end=end,
                            forecast_power_mw=row["forecast"],
                            provider_model_name="synthetic scenario",
                            provider_model_version=source,
                            scenario_code="demo",
                            **evidence(key + "-da", row["forecast_issued_at"]),
                        ),
                    )
                    put(
                        "weather_forecast",
                        dict(
                            weather_forecast_id=sid(key + "-weather-fc"),
                            weather_location_id=location,
                            forecast_product="synthetic-weather",
                            forecast_method="scenario",
                            issued_at=row["forecast_issued_at"],
                            target_start=target,
                            target_end=end,
                            air_temperature_c=row["temperature"],
                            cloud_cover_pct=100 * row["cloud"],
                            **evidence(key + "-weather-fc", row["forecast_issued_at"]),
                        ),
                    )
                    price_key = "market-" + target
                    published = (
                        start.replace(hour=16, minute=0) - timedelta(days=1)
                    ).isoformat()
                    if instant(published) <= now:
                        put(
                            "market_price",
                            dict(
                                price_id=sid(price_key + "-da"),
                                market_location_id="demo-market",
                                interval_start=target,
                                interval_end=end,
                                market_stage="day_ahead",
                                price_type="synthetic",
                                price_component="total",
                                price_yuan_mwh=row["da_price"],
                                currency="CNY",
                                is_final=1,
                                **evidence(price_key + "-da", published),
                            ),
                        )
                    # Two stations have different synthetic real-time noise. Preserve distinct sources/locations?
                    # The selected demo market curve uses lanneng only, explicitly and deterministically.
                    if station == "lanneng" and row["rt_price"] is not None:
                        put(
                            "market_price",
                            dict(
                                price_id=sid(price_key + "-rt"),
                                market_location_id="demo-market",
                                interval_start=target,
                                interval_end=end,
                                market_stage="real_time",
                                price_type="synthetic",
                                price_component="total",
                                price_yuan_mwh=row["rt_price"],
                                currency="CNY",
                                is_final=1,
                                **evidence(price_key + "-rt", end),
                            ),
                        )
        # Example output records are scenario outputs, not fitted models or accepted deployments.
        tasks = [
            "day_ahead_power",
            "day_ahead_price",
            "prebid_spread",
            "intraday_power",
            "intraday_spread",
        ]
        for task in tasks:
            put(
                "model_version",
                dict(
                    model_version_id=sid(task + "-model"),
                    model_name="demo-scenario",
                    version="1",
                    task=task,
                    feature_version="pit-evidence-v1",
                    label_version="synthetic-v1",
                    parameters_json="{}",
                    metrics_json="{}",
                    status="demo_untrained",
                    source_mode="synthetic",
                    created_at=early,
                ),
            )
        for station in STATIONS:
            for day in DATES:
                rows = records(station, day)
                for task in tasks:
                    intraday = task.startswith("intraday")
                    cutoff = (
                        day + "T10:00:00+08:00"
                        if intraday
                        else rows[0]["forecast_issued_at"]
                    )
                    if instant(cutoff) > now:
                        continue
                    start = day + ("T10:00:00+08:00" if intraday else "T00:00:00+08:00")
                    end = (
                        datetime.fromisoformat(day) + timedelta(days=1)
                    ).isoformat() + "+08:00"
                    run_id = sid(station + day + task + "-run")
                    if store.db.execute(
                        "SELECT 1 FROM prediction_run WHERE run_id=?", (run_id,)
                    ).fetchone():
                        continue
                    snapshot = store.bundle(
                        task, station, start, end, cutoff, allow_synthetic=True
                    )
                    snapshot_id = sid(station + day + task + "-snapshot")
                    put(
                        "feature_snapshot",
                        dict(
                            snapshot_id=snapshot_id,
                            task=task,
                            station_id=station,
                            target_start=start,
                            target_end=end,
                            cutoff_at=cutoff,
                            created_at=early,
                            feature_version="pit-evidence-v1",
                            source_mode="synthetic",
                            payload_json=encoded(snapshot),
                            content_hash=digest(snapshot),
                        ),
                    )
                    for table, inputs in snapshot["records"].items():
                        from .storage import CATALOG

                        for item in inputs:
                            record_id = item[CATALOG[table]["pk"]]
                            put(
                                "feature_input",
                                dict(
                                    input_id=sid(snapshot_id + table + record_id),
                                    snapshot_id=snapshot_id,
                                    table_name=table,
                                    record_id=record_id,
                                    available_at=item["available_at"],
                                    record_hash=digest(item),
                                    payload_json=encoded(item),
                                ),
                            )
                    put(
                        "prediction_run",
                        dict(
                            run_id=run_id,
                            model_version_id=sid(task + "-model"),
                            snapshot_id=snapshot_id,
                            task=task,
                            station_id=station,
                            market_location_id=(
                                "demo-market"
                                if "price" in task or "spread" in task
                                else None
                            ),
                            cutoff_at=cutoff,
                            issued_at=cutoff,
                            available_at=cutoff,
                            target_start=start,
                            target_end=end,
                            status="demo",
                            source_mode="synthetic",
                            created_at=early,
                        ),
                    )
                    errors = []
                    for row in rows:
                        if instant(row["timestamp"]) < instant(start):
                            continue
                        if task == "day_ahead_power":
                            value = row["forecast"]
                        elif task == "intraday_power":
                            value = row["corrected"]
                        elif task == "day_ahead_price":
                            value = row["da_pred"]
                        elif task == "intraday_spread":
                            value = round(row["rt_pred"] - row["da_price"], 2)
                        else:
                            value = (
                                1
                                if row["rt_pred"] > row["da_pred"]
                                else -1 if row["rt_pred"] < row["da_pred"] else 0
                            )
                        if value is None:
                            continue
                        a = datetime.fromisoformat(row["timestamp"])
                        b = a + timedelta(minutes=15)
                        put(
                            "prediction_value",
                            dict(
                                prediction_id=sid(run_id + row["timestamp"]),
                                run_id=run_id,
                                target_start=a,
                                target_end=b,
                                value=value,
                                unit=(
                                    "MW"
                                    if "power" in task
                                    else (
                                        "direction"
                                        if task == "prebid_spread"
                                        else "yuan/MWh"
                                    )
                                ),
                                quality_flag="synthetic",
                            ),
                        )
                        if task == "day_ahead_power" and row["actual"] is not None:
                            errors.append(value - row["actual"])
                    if errors:
                        eid = sid(run_id + "-evaluation")
                        put(
                            "evaluation_run",
                            dict(
                                evaluation_id=eid,
                                run_id=run_id,
                                label_cutoff_at=now,
                                measurement_boundary="synthetic_station_ac",
                                scorer_version="matched-interval-v1",
                                sample_count=len(errors),
                                status="synthetic_only",
                                source_mode="synthetic",
                                created_at=now,
                            ),
                        )
                        for metric, value in [
                            ("mae", sum(abs(x) for x in errors) / len(errors)),
                            (
                                "rmse",
                                math.sqrt(sum(x * x for x in errors) / len(errors)),
                            ),
                        ]:
                            put(
                                "evaluation_metric",
                                dict(
                                    metric_id=sid(eid + metric),
                                    evaluation_id=eid,
                                    metric_name=metric,
                                    metric_value=value,
                                    unit="MW",
                                    sample_count=len(errors),
                                ),
                            )
    return {
        "inserted": added,
        "source": "synthetic",
        "demo_as_of": now,
        "warning": "Demonstration only; not trained model or Zhejiang market evidence.",
        **store.inspect(),
    }
