"""Read-only connection evidence, separated from training and accuracy claims."""

from .serving import now, data_clock
from .model_runtime import list_runtime_models


def connection_readiness(store, station_id, source_mode):
    cutoff = now()
    basis = "r.availability_basis='synthetic'" if source_mode == "synthetic" else "r.availability_basis IN ('verified_arrival','verified_publication') AND s.source_type!='synthetic'"
    inputs = []
    specifications = [
        ("station_actual", "光伏实测", "r.station_id=?"),
        ("station_forecast_snapshot", "场站预测快照", "r.station_id=?"),
        ("weather_forecast", "数值天气预报", "EXISTS (SELECT 1 FROM station_weather_binding b WHERE b.station_id=? AND b.weather_location_id=r.weather_location_id AND b.available_at<=? AND b.availability_basis IN ({bases}))"),
        ("market_price", "市场价格", "EXISTS (SELECT 1 FROM station_market_binding b WHERE b.station_id=? AND b.market_location_id=r.market_location_id AND b.available_at<=? AND b.availability_basis IN ({bases}))"),
    ]
    bases = "'synthetic'" if source_mode == "synthetic" else "'verified_arrival','verified_publication'"
    for table, label, station_filter in specifications:
        station_filter = station_filter.format(bases=bases)
        args = [station_id] + ([cutoff] if "EXISTS" in station_filter else []) + [cutoff]
        record = store.db.execute(
            f"SELECT count(*) AS record_count,max(r.available_at) AS latest_available_at FROM {table} r JOIN data_source s USING(source_id) WHERE {station_filter} AND r.available_at<=? AND {basis}", args
        ).fetchone()
        inputs.append(dict(key=table, label=label, **dict(record)))
    models = [m for m in list_runtime_models(store) if m["source_mode"] == source_mode]
    return dict(
        station_id=station_id, source_mode=source_mode, checked_at=cutoff, inputs=inputs, models=models,
        capabilities=[
            dict(key="pit", label="时点查询与来源追溯", available=True, note="按到达时间过滤，保留原始记录、修订和预测快照。"),
            dict(key="inference", label="光伏模型推理", available=any(m["ready"] for m in models), note="内置 PIT 残差拟合可执行；本地权重与 HTTP 服务可登记，输入和实际调用结果分别验证。"),
            dict(key="review", label="反馈、案例与审批记录", available=True, note="人工反馈、案例入库、版本审批和回滚均追加保存；演示审批不触发真实训练。"),
            dict(key="settlement", label="确定性收益沙盘", available=True, note="仅对实测与价格齐备时段结算；示例免考阈值不代表正式市场规则。"),
            dict(key="training", label="持久化训练调度", available=False, note="尚未接入训练调度器；现场历史拟合与登记外部权重不等于完成正式训练。"),
            dict(key="production_validation", label="生产效果验收", available=False, note="需真实输入、固定训练与测试划分、模型产物和业务评估记录；本页面不以接口可用代替精度验收。"),
        ],
        notice="合成演示与生产输入严格分开。模型登记状态、适配器就绪和已验证业务效果是不同事实；生产数据与正式规则需要另行接入核验。",
    )


def available_dates(store, station_id, source_mode):
    """Dates come from arrived L1 records and visible predictions, never another mode."""
    cutoff = data_clock(store, source_mode)
    basis = "r.availability_basis='synthetic'" if source_mode == "synthetic" else "r.availability_basis IN ('verified_arrival','verified_publication') AND s.source_type!='synthetic'"
    result = set()
    for table, field in [("station_actual", "interval_start"), ("station_forecast_snapshot", "target_start")]:
        where = " AND r.station_id=?" if station_id else ""
        args = [cutoff] + ([station_id] if station_id else [])
        result.update(r[0] for r in store.db.execute(
            f"SELECT DISTINCT date(r.{field},'+8 hours') FROM {table} r JOIN data_source s USING(source_id) WHERE r.available_at<=? AND {basis}{where}", args
        ))
    where = " AND station_id=?" if station_id else ""
    result.update(r[0] for r in store.db.execute(
        "SELECT DISTINCT date(target_start,'+8 hours') FROM prediction_run WHERE source_mode=? AND available_at<=?" + where,
        [source_mode, cutoff] + ([station_id] if station_id else []),
    ))
    return sorted(d for d in result if d)
