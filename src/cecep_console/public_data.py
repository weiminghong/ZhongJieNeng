"""Existing public market records, kept separate from Zhejiang site telemetry.

The source has event labels, not historical publication/arrival timestamps.
Sequence playback must never be described as a PIT strategy backtest.
"""

import csv
from datetime import date, datetime, timedelta, timezone
from functools import lru_cache
import hashlib
import io
import json
import math
import os
from pathlib import Path
from uuid import uuid4

from .storage import digest, encoded
from .serving import now, metrics, rows
from .model_settings import load_settings, select_evidence, ProviderError

DATASET_ID = "shandong-public-market"
SOURCE_URL = "https://github.com/ronaldowzy/price_forecast"
SOURCE_COMMIT = "96ddcf9b020e98be35c9b8eb1c0f8b6e1fb8dc6f"
TZ = timezone(timedelta(hours=8))
FIELDS = {
    "pv_forecast_mw": ("光伏总加(预测)", "MW"),
    "pv_actual_mw": ("光伏总加(实际)", "MW"),
    "load_forecast_mw": ("直调负荷(预测)", "MW"),
    "load_actual_mw": ("直调负荷(实际)", "MW"),
    "wind_forecast_mw": ("风电总加(预测)", "MW"),
    "wind_actual_mw": ("风电总加(实际)", "MW"),
    "da_price": ("日前价格", "元/MWh"),
    "rt_price": ("实时价格", "元/MWh"),
}
BASIS = "按源文件日期和区间终点顺序回放；源文件没有原始发布时间或到达时间，不构成严格 PIT 回测。预测曲线取自源文件预测列，不是本站已训练模型的输出。"


def source_path():
    return Path(os.environ.get("CECEP_PUBLIC_MARKET_CSV", "/home/priv/cecep_rsi_demo/vendor/price_forecast/data/价格预测数据集.csv")).expanduser().resolve()


def number(value):
    if value is None or str(value).strip().lower() in {"", "nan", "null", "n/a", "--"}:
        return None
    result = float(value)
    if not math.isfinite(result):
        raise ValueError("公开数据存在非有限数值，请检查源文件")
    return result


@lru_cache(maxsize=2)
def _load(path, mtime_ns, size):
    file = Path(path)
    raw = file.read_bytes()
    stat = file.stat()
    if stat.st_mtime_ns != mtime_ns or stat.st_size != size:
        raise ValueError("数据文件正在更新，请稍后重试")
    source_hash = hashlib.sha256(raw).hexdigest()
    reader = csv.DictReader(io.StringIO(raw.decode("utf-8-sig")))
    required = {"日期", "时刻", *(v[0] for v in FIELDS.values())}
    if not required <= set(reader.fieldnames or []):
        raise ValueError("公开市场数据缺少必要日期、光伏、负荷或电价字段")
    days = {}
    row_count = 0
    for line, original in enumerate(reader, 2):
        day = date.fromisoformat(original["日期"].strip()).isoformat()
        hour, minute = map(int, original["时刻"].strip().split(":"))
        minutes = hour * 60 + minute
        if not 0 < minutes <= 1440 or minutes % 15 or not 0 <= minute < 60 or hour > 24:
            raise ValueError(f"第 {line} 行不是有效的15分钟区间终点")
        slot = minutes // 15 - 1
        records = days.setdefault(day, {})
        if slot in records:
            raise ValueError(f"公开数据存在重复的日期/时段：{day} {original['时刻']}")
        end = datetime.fromisoformat(day).replace(tzinfo=TZ) + timedelta(minutes=minutes)
        records[slot] = dict(
            slot=slot, source_line=line, source_time_label=original["时刻"],
            source_values=original,
            interval_start=(end-timedelta(minutes=15)).isoformat(), interval_end=end.isoformat(),
            **{key: number(original[column]) for key, (column, _) in FIELDS.items()},
        )
        row_count += 1
    dates = sorted(days)
    if not dates:
        raise ValueError("公开市场数据文件没有记录")
    meta = dict(dataset_id=DATASET_ID, name="山东公开市场数据", source_url=SOURCE_URL, source_commit=SOURCE_COMMIT,
                source_file=file.name, source_hash=source_hash, bytes=len(raw), row_count=row_count,
                day_count=len(dates), date_start=dates[0], date_end=dates[-1], interval_minutes=15,
                fields=[dict(key=key, source_column=column, unit=unit) for key, (column, unit) in FIELDS.items()],
                source_columns=reader.fieldnames, source_kind="public_reference", region="山东省级聚合市场",
                availability_timestamps_verified=False, current_model_inference=False, basis=BASIS,
                update_policy="历史文件；每30秒检查文件版本。仅在源文件变化时更新，不生成新数值。")
    return meta, dates, days


def dataset():
    path = source_path()
    if not path.is_file():
        raise ValueError("服务器尚未配置已有公开市场数据文件")
    try:
        stat = path.stat()
        return _load(str(path), stat.st_mtime_ns, stat.st_size)
    except OSError:
        raise ValueError("公开数据文件暂时不可读，请检查权限或稍后重试") from None


def catalog():
    if not source_path().is_file():
        return dict(available=False, checked_at=now(), dates=[], metadata=None,
                    notice="公开市场数据文件尚未配置；不会退回合成数据。")
    meta, dates, _ = dataset()
    return dict(available=True, checked_at=now(), metadata=meta, dates=dates, default_date=dates[-1])


def series(day, cursor=96, expected_hash=None, *, source_dataset=None):
    meta, dates, days = source_dataset or dataset()
    if expected_hash and expected_hash != meta["source_hash"]:
        raise ValueError("源文件版本已变化，请重新检查数据后继续")
    if day not in days:
        raise ValueError("所选日期没有公开市场记录")
    if type(cursor) is not int or not 0 <= cursor <= 96:
        raise ValueError("回放位置必须在0到96个时段之间")
    points = []
    day_start = datetime.fromisoformat(day).replace(tzinfo=TZ)
    for slot in range(96):
        start = day_start + timedelta(minutes=slot*15)
        record = days[day].get(slot)
        visible = slot < cursor
        row = dict(slot=slot, interval_start=start.isoformat(), interval_end=(start+timedelta(minutes=15)).isoformat(),
                   visible=visible, source_line=record["source_line"] if record and visible else None,
                   quality="not_revealed" if not visible else "missing_record" if not record else "source_record")
        row.update({key: record[key] if record and visible else None for key in FIELDS})
        row["source_values"] = record["source_values"] if record and visible else None
        row["spread_yuan_mwh"] = row["rt_price"]-row["da_price"] if row["rt_price"] is not None and row["da_price"] is not None else None
        points.append(row)
    visible = [r for r in points if r["visible"] and r["source_line"]]
    pairs = [r for r in visible if r["pv_actual_mw"] is not None and r["pv_forecast_mw"] is not None]
    power = metrics([r["pv_actual_mw"] for r in pairs], [r["pv_forecast_mw"] for r in pairs])
    price_pairs = [r for r in visible if r["spread_yuan_mwh"] is not None]
    max_spread = max(price_pairs, key=lambda r: abs(r["spread_yuan_mwh"])) if price_pairs else None
    worst_power = max(pairs, key=lambda r: abs(r["pv_actual_mw"]-r["pv_forecast_mw"])) if pairs else None
    summary = dict(visible_records=len(visible), revealed_slots=cursor, total_day_records=len(days[day]),
                   pv_mae_mw=power["mae"], pv_rmse_mw=power["rmse"], power_pair_count=len(pairs),
                   pv_actual_mwh=sum(r["pv_actual_mw"]*.25 for r in pairs) if pairs else None,
                   mean_spread_yuan_mwh=sum(r["spread_yuan_mwh"] for r in price_pairs)/len(price_pairs) if price_pairs else None,
                   price_pair_count=len(price_pairs), negative_price_count=sum(r["rt_price"]<0 for r in visible if r["rt_price"] is not None),
                   missing_records=cursor-len(visible), max_abs_spread=max_spread, worst_pv_error=worst_power)
    scope = dict(dataset_id=DATASET_ID, source_hash=meta["source_hash"], date=day, cursor=cursor,
                 replay_until=(day_start+timedelta(minutes=cursor*15)).isoformat())
    return dict(metadata=meta, scope=scope, scope_hash=digest(scope), points=points, summary=summary, latest=visible[-1] if visible else None)


def scenario(day, cursor, quantity_mwh, fee_yuan_mwh, expected_hash=None, *, source_dataset=None):
    data = series(day, cursor, expected_hash, source_dataset=source_dataset)
    if not all(math.isfinite(v) and v >= 0 for v in (quantity_mwh, fee_yuan_mwh)):
        raise ValueError("情景电量与费用必须为有限非负数")
    pairs = [r for r in data["points"] if r["visible"] and r["spread_yuan_mwh"] is not None]
    return dict(scope=data["scope"], quantity_mwh=quantity_mwh, fee_yuan_mwh=fee_yuan_mwh,
                paired_intervals=len(pairs), unsettled_intervals=cursor-len(pairs),
                total_exposure_mwh=quantity_mwh*len(pairs),
                gross_spread_yuan=sum(r["spread_yuan_mwh"]*quantity_mwh for r in pairs) if pairs else None,
                fees_yuan=fee_yuan_mwh*quantity_mwh*len(pairs) if pairs else None,
                net_spread_yuan=sum((r["spread_yuan_mwh"]-fee_yuan_mwh)*quantity_mwh for r in pairs) if pairs else None,
                formula="Σ[(实时价−日前价−每MWh费用)×每时段假设电量]",
                basis="事后价差敞口情景；不是可执行策略回测、场站收益或浙江市场结算。")


def save_run(store, data, kind, text, output, selected_slot=None, status="completed"):
    scope = {**data["scope"], "selected_slot": selected_slot}
    evidence = dict(source_url=SOURCE_URL, source_hash=data["metadata"]["source_hash"], source_file=data["metadata"]["source_file"],
                    source_lines=[r["source_line"] for r in data["points"] if r["visible"] and r["source_line"]],
                    source_records=[r for r in data["points"] if r["visible"] and r["source_line"]])
    run_id = str(uuid4())
    with store.db:
        store.append("public_reference_run", dict(run_id=run_id, dataset_id=DATASET_ID,
                     source_hash=data["metadata"]["source_hash"], kind=kind, scope_json=encoded(scope),
                     evidence_json=encoded(evidence), output_json=encoded(output), answer_text=text,
                     status=status, created_at=now()))
    return dict(run_id=run_id, scope=scope, evidence=evidence, status=status)


def analyze(store, day, cursor, question, expected_hash, *, source_dataset=None):
    if not expected_hash:
        raise ValueError("分析必须绑定数据文件版本")
    data = series(day, cursor, expected_hash, source_dataset=source_dataset)
    k = data["summary"]
    def show(value, suffix=""):
        return "无有效配对" if value is None else f"{value:,.2f}{suffix}"
    facts = [
        f"山东公开市场，{day}，记录顺序回放至 {data['scope']['replay_until']}；已展示 {k['visible_records']} 条、价格配对 {k['price_pair_count']} 条。",
        f"源文件光伏预测与实际列的配对 MAE {show(k['pv_mae_mw'], ' MW')}，RMSE {show(k['pv_rmse_mw'], ' MW')}。这不是本站模型训练效果。",
        f"已展示时段的平均 RT−DA 价差为 {show(k['mean_spread_yuan_mwh'], ' 元/MWh')}，实时负电价时段 {k['negative_price_count']} 个。",
        f"已展示范围中缺少原始记录的时段 {k['missing_records']} 个；源文件负值原样保留，缺失值不补零。",
        BASIS,
    ]
    if k["worst_pv_error"]:
        row = k["worst_pv_error"]
        facts.append(f"当前最大光伏列偏差发生在 {row['interval_start']}，实际减预测 {row['pv_actual_mw']-row['pv_forecast_mw']:.2f} MW；源文件第 {row['source_line']} 行。仅凭这些列不能确认气象或设备根因。")
    if k["max_abs_spread"]:
        row = k["max_abs_spread"]
        facts.append(f"当前绝对值最大的价差发生在 {row['interval_start']}，RT−DA={row['spread_yuan_mwh']:.2f} 元/MWh；源文件第 {row['source_line']} 行。")
    settings = load_settings()
    failed = None
    llm_mode = "deterministic_tools_only"
    indices = list(range(len(facts)))
    if settings.ready:
        llm_mode = "openai_compatible_evidence_summary"
        try:
            indices = select_evidence(settings, facts, question)
        except ProviderError as exc:
            failed = exc.code
    answer = "外部证据摘要调用失败，请重试。工具计算与证据仍已记录。" if failed else "\n\n".join(facts[i] for i in indices)
    tools = dict(summary=k, facts=facts, question=question, llm_mode=llm_mode, provider_error=failed)
    saved = save_run(store, data, "analysis", answer, tools, status="provider_failed" if failed else "completed")
    return {**saved, **tools, "answer_markdown": answer, "error": answer if failed else None}


def review(store, day, cursor, selected_slot, reason, expected_hash, *, source_dataset=None):
    if not expected_hash or not reason.strip():
        raise ValueError("复核必须绑定数据版本并填写结论")
    data = series(day, cursor, expected_hash, source_dataset=source_dataset)
    if selected_slot is None or not 0 <= selected_slot < cursor or not data["points"][selected_slot]["source_line"]:
        raise ValueError("只能复核已经展示的原始记录")
    record = data["points"][selected_slot]
    return save_run(store, data, "review", reason.strip(), dict(record=record, training_eligible=False,
                    notice="仅保存公开样例复核记录，不改变原始数据或触发模型训练。"), selected_slot)


def history(store, source_hash, day):
    result = rows(store, "SELECT * FROM public_reference_run WHERE dataset_id=? AND json_extract(scope_json,'$.date')=?" + (" AND source_hash=?" if source_hash else "") + " ORDER BY created_at DESC,rowid DESC LIMIT 30", (DATASET_ID, day, source_hash) if source_hash else (DATASET_ID, day))
    for record in result:
        for key in ("scope", "evidence", "output"):
            record[key] = json.loads(record.pop(key+"_json"))
    return dict(runs=result)
