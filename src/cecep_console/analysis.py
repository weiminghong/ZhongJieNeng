"""指标及 Agent 本地工具，共享同一组经过筛选的时段。"""

from __future__ import annotations

from .adapters import evaluate_predictions
from .data import STATIONS, available_context, records


def paired_metrics(rows: list[dict], predicted: str, actual: str) -> dict:
    pairs = [row for row in rows if row[predicted] is not None and row[actual] is not None]
    if not pairs:
        return {"n": 0, "mae": None, "rmse": None}
    return evaluate_predictions([row[actual] for row in pairs], [row[predicted] for row in pairs])


def dataset(station_id: str, selected_date: str, daylight: bool = False) -> dict:
    all_rows = list(records(station_id, selected_date))
    rows = [row for row in all_rows if row["physical"] > 0.1] if daylight else all_rows
    observed = [row for row in rows if row["actual"] is not None]
    correction_pairs = [row for row in rows if row["corrected"] is not None and row["actual"] is not None]
    return {
        "station": STATIONS[station_id],
        "date": selected_date,
        "source": "合成演示数据",
        "as_of": available_context()["as_of"],
        "model": "demo-scenario-v1",
        "interval_minutes": 15,
        "scope": "白昼时段" if daylight else "全天时段",
        "rows": rows,
        "metrics": {
            "generation": paired_metrics(rows, "forecast", "actual"),
            "baseline_matched": paired_metrics(correction_pairs, "forecast", "actual"),
            "correction_matched": paired_metrics(correction_pairs, "corrected", "actual"),
            "price": paired_metrics(rows, "da_pred", "da_price"),
            "rt_price": paired_metrics(rows, "rt_pred", "rt_price"),
            "energy_actual": round(sum(row["actual"] * 0.25 for row in observed), 2),
            "energy_forecast_matched": round(sum(row["forecast"] * 0.25 for row in observed), 2),
            "energy_forecast": round(sum(row["forecast"] * 0.25 for row in rows), 2),
            "observed_count": len(observed),
            "due_count": sum(row["quality"] != "待实测" for row in rows),
            "quality_count": sum(row["quality"] in ("实发缺失", "辐照度缺失") for row in rows),
        },
    }


def answer_question(question: str, payload: dict) -> dict:
    rows = payload["rows"]
    metrics = payload["metrics"]
    observed = [row for row in rows if row["actual"] is not None]
    context = f"{payload['station']['name']}，{payload['date']}，{payload['scope']}"
    if any(word in question for word in ("价", "市场")):
        settled = [row for row in rows if row["rt_price"] is not None]
        if not settled:
            text = "实时价格尚未到达，可查看日前和实时预测曲线。"
        else:
            worst = max(settled, key=lambda row: abs(row["rt_price"] - row["da_price"]))
            spread = worst["rt_price"] - worst["da_price"]
            text = f"已到达 {len(settled)} 个实时价格时段。最大绝对价差发生在 {worst['time']}，实时减日前为 {spread:+.2f} 元/MWh。"
        tools = ["market_data", "spread_analysis"]
        link = "price"
    elif any(word in question for word in ("缺", "原始", "数据质量")):
        text = f"共有 {len(rows)} 个时段，已到期 {metrics['due_count']} 个，实发可用 {metrics['observed_count']} 个。发现 {metrics['quality_count']} 条实发或辐照度缺失记录。未来待实测时段单独标记。"
        tools = ["source_records", "quality_check"]
        link = "raw"
    elif observed:
        worst = max(observed, key=lambda row: abs(row["forecast"] - row["actual"]))
        text = f"已实测时段累计发电 {metrics['energy_actual']:.2f} MWh，同期日前预测 {metrics['energy_forecast_matched']:.2f} MWh。最大绝对功率偏差出现在 {worst['time']}，为 {abs(worst['forecast'] - worst['actual']):.2f} MW。同期云量为 {worst['cloud']:.0%}，设备可用率为 {worst['availability']:.0%}，可作为人工复核线索。"
        tools = ["generation_data", "matched_evaluation", "weather_context"]
        link = "analysis"
    else:
        text = "当前日期尚无实测结果。可查看预测走势，实测到达后再计算误差。"
        tools = ["generation_data"]
        link = "generation"
    return {"text": text, "context": context, "tools": tools, "link": link, "mode": "本地工具分析", "source": payload["source"]}
