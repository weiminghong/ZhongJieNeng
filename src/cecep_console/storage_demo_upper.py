"""Explicit synthetic fixtures for the complete workbench; never trains a model."""

from datetime import datetime, timedelta
import math
from .storage import encoded, digest, instant
from .storage_demo import sid
from .serving import (
    rows,
    build_intervals,
    data_clock,
    day_bounds,
    now,
    refresh_serving_tables,
)

EARLY = "2026-11-17T00:00:00+08:00"
RULE = "demo-rule-capacity-5pct-v1"


def seed_upper_demo(store):
    from .data import STATIONS, DATES

    count = 0

    def put(table, record):
        nonlocal count
        count += store.append(table, record)

    clock = data_clock(store)
    with store.db:
        put(
            "rule_version",
            dict(
                rule_version_id=RULE,
                market_code="DEMO",
                rule_code="SYNTHETIC_SETTLEMENT",
                title="合成演示容量±5%免考参考规则",
                version="1",
                effective_from=EARLY,
                published_at=EARLY,
                available_at=EARLY,
                availability_basis="synthetic",
                source_id="demo-scenario-v1",
                document_uri="synthetic://rules/5pct",
                content_hash=digest({"rule": "demo-5pct-v1"}),
                parameters_json=encoded(
                    {
                        "exempt_fraction": 0.05,
                        "threshold_basis": "capacity",
                        "penalty_yuan_mwh": 600,
                        "contract_ratio": 0.7,
                        "description": "演示参考：按装机容量±5%免考、超额偏差600元/MWh；非浙江正式规则",
                        "source_mode": "synthetic",
                    }
                ),
                review_status="synthetic_demo",
                revision_no=0,
            ),
        )
        for version, status in [
            ("2.0", "archived"),
            ("2.1", "production"),
            ("2.2-cand", "candidate"),
        ]:
            put(
                "model_version",
                dict(
                    model_version_id="lgbm-demo-v" + version,
                    model_name="lgbm-demo",
                    version=version,
                    task="day_ahead_power",
                    feature_version="pit-evidence-v1",
                    label_version="synthetic-v1",
                    parameters_json=encoded(
                        {
                            "source_mode": "synthetic",
                            "trained": False,
                            "description": "确定性场景版本；未训练LightGBM，不代表生产模型",
                        }
                    ),
                    metrics_json="{}",
                    status=status,
                    source_mode="synthetic",
                    created_at=EARLY,
                ),
            )
        put(
            "model_version",
            dict(
                model_version_id="intraday-corr-demo-v1",
                model_name="intraday-corr-demo",
                version="1",
                task="intraday_power",
                feature_version="pit-evidence-v1",
                label_version="synthetic-v1",
                parameters_json=encoded(
                    {"trained": False, "description": "合成日内场景"}
                ),
                metrics_json="{}",
                status="production",
                source_mode="synthetic",
                created_at=EARLY,
            ),
        )
        for day in DATES:
            put(
                "calendar_day",
                dict(
                    calendar_id=sid(day + "-calendar"),
                    market_code="DEMO",
                    calendar_date=day,
                    day_type="demo_workday",
                    calendar_version="synthetic-v1",
                    source_id="demo-scenario-v1",
                    published_at=EARLY,
                    available_at=EARLY,
                    availability_basis="synthetic",
                    revision_no=0,
                ),
            )
        base_runs = rows(
            store,
            "SELECT * FROM prediction_run WHERE model_version_id=?",
            (sid("day_ahead_power-model"),),
        )
        for base in base_runs:
            predictions = rows(
                store,
                "SELECT * FROM prediction_value WHERE run_id=? ORDER BY target_start",
                (base["run_id"],),
            )
            for version, factor in [("2.0", 1.055), ("2.1", 1.0), ("2.2-cand", 0.975)]:
                run_id = sid(base["run_id"] + version)
                put(
                    "prediction_run",
                    {
                        **base,
                        "run_id": run_id,
                        "model_version_id": "lgbm-demo-v" + version,
                    },
                )
                errors = []
                for p in predictions:
                    value = round(p["value"] * factor, 4)
                    put(
                        "prediction_value",
                        {
                            **p,
                            "prediction_id": sid(run_id + p["target_start"]),
                            "run_id": run_id,
                            "value": value,
                            "lower_value": max(0, round(value * 0.84, 4)),
                            "upper_value": round(value * 1.16, 4),
                        },
                    )
                    actual = store.db.execute(
                        "SELECT power_mw FROM station_actual WHERE station_id=? AND interval_start=? AND available_at<=? ORDER BY revision_no DESC LIMIT 1",
                        (base["station_id"], p["target_start"], clock),
                    ).fetchone()
                    if actual and actual[0] is not None:
                        errors.append(value - actual[0])
                if errors:
                    eid = sid(run_id + "-eval")
                    put(
                        "evaluation_run",
                        dict(
                            evaluation_id=eid,
                            run_id=run_id,
                            label_cutoff_at=clock,
                            measurement_boundary="synthetic_station_ac",
                            scorer_version="matched-interval-v1",
                            sample_count=len(errors),
                            status="synthetic_only",
                            source_mode="synthetic",
                            created_at=clock,
                        ),
                    )
                    for metric, value in [
                        ("mae", sum(map(abs, errors)) / len(errors)),
                        ("rmse", math.sqrt(sum(x * x for x in errors) / len(errors))),
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
        for base in rows(
            store,
            "SELECT * FROM prediction_run WHERE model_version_id=?",
            (sid("intraday_power-model"),),
        ):
            run_id = sid(base["run_id"] + "-corr-v1")
            put(
                "prediction_run",
                {**base, "run_id": run_id, "model_version_id": "intraday-corr-demo-v1"},
            )
            for p in rows(
                store,
                "SELECT * FROM prediction_value WHERE run_id=?",
                (base["run_id"],),
            ):
                put(
                    "prediction_value",
                    {
                        **p,
                        "prediction_id": sid(run_id + p["target_start"]),
                        "run_id": run_id,
                    },
                )
        for station in STATIONS:
            put(
                "drift_check_run",
                dict(
                    drift_run_id=sid(station + "-drift"),
                    station_id=station,
                    task="day_ahead_power",
                    reference_start=day_bounds(DATES[0])[0],
                    reference_end=day_bounds(DATES[0])[1],
                    current_start=day_bounds(DATES[1])[0],
                    current_end=clock,
                    drifted_feature_count=1,
                    total_feature_count=3,
                    summary_json=encoded(
                        {
                            "source_mode": "synthetic",
                            "computed_by": "demo_fixture",
                            "description": "合成漂移告警示例，非Evidently实测结果",
                            "features": ["cloud_cover_pct"],
                        }
                    ),
                    report_uri="http://10.21.179.91:8502",
                    triggered_rsi=1,
                    source_mode="synthetic",
                    created_at=clock,
                ),
            )
            for day in DATES:
                base = next(
                    (
                        r
                        for r in base_runs
                        if r["station_id"] == station
                        and r["target_start"] == day_bounds(day)[0]
                    ),
                    None,
                )
                if not base:
                    continue
                run_id = sid(base["run_id"] + "2.1")
                price = store.db.execute(
                    "SELECT run_id FROM prediction_run WHERE station_id=? AND task='day_ahead_price' AND target_start=? LIMIT 1",
                    (station, day_bounds(day)[0]),
                ).fetchone()
                values = rows(
                    store,
                    "SELECT * FROM prediction_value WHERE run_id=? ORDER BY target_start",
                    (run_id,),
                )
                for p in values:
                    put(
                        "contract_position",
                        dict(
                            contract_id=sid(station + p["target_start"] + "contract"),
                            station_id=station,
                            market_location_id="demo-market",
                            contract_type="monthly",
                            interval_start=p["target_start"],
                            interval_end=p["target_end"],
                            contract_energy_mwh=round(p["value"] * 0.25 * 0.7, 6),
                            contract_price_yuan_mwh=380,
                            effective_from=EARLY,
                            available_at=EARLY,
                            source_id="demo-scenario-v1",
                            revision_no=0,
                            source_mode="synthetic",
                        ),
                    )
                for tag, name, factor in [
                    ("base", "基准预测", 1.0),
                    ("p25", "保守防考核 p25", 0.92),
                    ("spread", "价差套利", None),
                ]:
                    pid = sid(station + day + tag)
                    put(
                        "bidding_plan",
                        dict(
                            plan_id=pid,
                            station_id=station,
                            market_location_id="demo-market",
                            trading_date=day,
                            plan_name=name,
                            power_run_id=run_id,
                            price_run_id=price[0] if price else None,
                            rule_version_id=RULE,
                            status="synthetic_sandbox",
                            created_by="demo-seeder",
                            source_mode="synthetic",
                            created_at=EARLY,
                        ),
                    )
                    for p in values:
                        # Arbitrage uses predicted prices only, never ex-post actual prices.
                        h = datetime.fromisoformat(
                            p["target_start"].replace("Z", "+00:00")
                        ).hour
                        f = (
                            factor
                            if factor is not None
                            else (0.94 if math.sin((h + 8) * 1.5) > 0 else 1.04)
                        )
                        power = round(p["value"] * f, 4)
                        put(
                            "bidding_plan_item",
                            dict(
                                plan_item_id=sid(pid + p["target_start"]),
                                plan_id=pid,
                                interval_start=p["target_start"],
                                interval_end=p["target_end"],
                                bid_power_mw=power,
                                bid_energy_mwh=power * 0.25,
                                bid_price_yuan_mwh=0,
                                strategy_tag=tag,
                                rationale_json=encoded(
                                    {
                                        "source_mode": "synthetic",
                                        "description": (
                                            "演示分位数近似，未经概率校准"
                                            if tag == "p25"
                                            else "确定性合成策略；无收益保证"
                                        ),
                                        "forecast_factor": f,
                                    }
                                ),
                            ),
                        )
                interval_rows = build_intervals(store, station, day, clock)
                for r in interval_rows:
                    if r["actual_mw"] is None or r["da_forecast_mw"] is None:
                        continue
                    error = r["actual_mw"] - r["da_forecast_mw"]
                    if abs(error) > STATIONS[station]["capacity"] * 0.05:
                        put(
                            "deviation_case",
                            dict(
                                case_id=sid(station + r["interval_start"] + "-case"),
                                station_id=station,
                                prediction_run_id=run_id,
                                interval_start=r["interval_start"],
                                interval_end=r["interval_end"],
                                actual_value=r["actual_mw"],
                                predicted_value=r["da_forecast_mw"],
                                error_value=error,
                                severity=(
                                    "high"
                                    if abs(error) > STATIONS[station]["capacity"] * 0.1
                                    else "medium"
                                ),
                                auto_clues_json=encoded(
                                    {
                                        "cloud_cover_pct": r["cloud_cover_pct"],
                                        "active_event_flag": r["active_event_flag"],
                                        "note": "同期气象/事件仅为线索，未作因果判定",
                                    }
                                ),
                                status="pending_review",
                                source_mode="synthetic",
                                created_at=clock,
                            ),
                        )
        candidate_eval = store.db.execute(
            "SELECT evaluation_id FROM evaluation_run WHERE run_id IN (SELECT run_id FROM prediction_run WHERE model_version_id='lgbm-demo-v2.2-cand') ORDER BY evaluation_id LIMIT 1"
        ).fetchone()
        put(
            "iteration_candidate",
            dict(
                candidate_id="demo-candidate-v2.2",
                base_model_version_id="lgbm-demo-v2.1",
                candidate_model_version_id="lgbm-demo-v2.2-cand",
                feedback_ids_json="[]",
                hypothesis="合成演示候选：下调场景预测倍率；未训练，审批仅改变演示注册状态",
                evaluation_id=candidate_eval[0] if candidate_eval else None,
                status="awaiting_review",
                created_at=clock,
            ),
        )
        documents = [
            (
                "market_rule",
                "偏差免考与合约结算演示规则",
                "偏差 免考 考核 合约 结算 市场规则：本演示使用装机容量 ±5% 免考阈值。70% 中长期合约锁价380元/MWh。净收益等于中长期加日前现货加实时偏差减超额偏差考核。仅合成参考，不代表浙江正式交易规则。",
            ),
            (
                "domain_manual",
                "光伏云量变化与预测复核手册",
                "云量 天气 辐照 光伏 功率 偏差 根因：云团快速经过可能引起短时辐照下降。需要核对实测、气象可用时点与限电事件，不可仅凭相关性确认因果。",
            ),
            (
                "dispatch_notice",
                "合成调度公告与时点规则",
                "调度 公告 限电 事件 回放 cutoff available_at：仅使用当时已到达的公告。合成场景无真实调度指令，请勿据此执行生产调度。",
            ),
            (
                "rsi_case",
                "偏差归因与人工审核案例范式",
                "审核 RSI 案例 模型 上线 回滚：先核验数据质量，再确认根因和训练可用性。人工确认的案例才可沉淀入知识库。示例不代表已确认生产结论。",
            ),
        ]
        for collection, title, content in documents:
            doc_id = "demo-doc-" + collection
            put(
                "rag_document",
                dict(
                    doc_id=doc_id,
                    collection=collection,
                    title=title,
                    market_code="DEMO",
                    effective_from=EARLY,
                    source_uri="synthetic://knowledge/" + collection,
                    content_hash=digest(content),
                    version="1",
                    status="active",
                    source_mode="synthetic",
                    created_at=EARLY,
                ),
            )
            put(
                "rag_chunk",
                dict(
                    chunk_id=doc_id + "-0",
                    doc_id=doc_id,
                    chunk_index=0,
                    heading_path=title,
                    content_text=content,
                    metadata_json=encoded(
                        {"source_mode": "synthetic", "demo_notice": "演示文档"}
                    ),
                    token_count=len(content),
                    embedding_model=None,
                    created_at=EARLY,
                ),
            )
        from .trading import simulate_plan

        for p in rows(
            store, "SELECT plan_id FROM bidding_plan WHERE source_mode='synthetic'"
        ):
            simulate_plan(store, p["plan_id"], persist=True)
        refresh_serving_tables(store)
    return count
