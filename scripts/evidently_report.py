"""用 Evidently 原生报告检视上游模拟数据，不训练或发布模型。"""

from __future__ import annotations

import argparse
import hashlib
import html
import json
import os
from pathlib import Path

os.environ.setdefault("EVIDENTLY_DISABLE_TELEMETRY", "1")
os.environ.setdefault("DO_NOT_TRACK", "1")

import pandas as pd
from evidently import DataDefinition, Dataset, Regression, Report
from evidently.presets import DataDriftPreset, DataSummaryPreset, RegressionPreset

ROOT = Path(__file__).resolve().parents[1]
WEATHER = ["ghi_kwh_m2", "temperature_c", "cloud_cover_pct", "wind_speed_ms"]


def load_data(directory: Path) -> pd.DataFrame:
    actual = pd.read_csv(directory / "actual_generation.csv")
    forecast = pd.read_csv(directory / "generation_forecast.csv")
    weather = pd.read_csv(directory / "weather.csv")
    for frame in (actual, forecast, weather):
        frame["date"] = pd.to_datetime(frame["date"], errors="raise")
        if frame["date"].duplicated().any():
            raise ValueError("发现重复日期，需要先确认版本口径")
    merged = actual.merge(forecast, on="date", validate="one_to_one", how="outer")
    merged = merged.merge(weather, on="date", validate="one_to_one", how="outer")
    return merged.sort_values("date").reset_index(drop=True)


def export_report(snapshot, output: Path, name: str, note: str):
    """增加中文显示层和数据口径说明，保留原始指标及报告交互。"""
    path = output / f"{name}.html"
    snapshot.save_html(str(path))
    original = path.read_text(encoding="utf-8")
    banner = (
        '<div style="padding:16px 24px;background:#fff8dd;color:#55451c;font:14px/1.8 sans-serif">'
        f'<strong>合成数据试用报告</strong>　{html.escape(note)}'
        '</div>'
    )
    start = original.find(">", original.lower().find("<body")) + 1
    if start <= 0:
        raise ValueError("Evidently HTML 缺少 body，无法标注来源")
    localized = original[:start] + banner + original[start:]
    title = {"quality": "数据质量与分布", "drift": "影响因素分布变化", "regression": "日发电量预测表现"}[name]
    translation = (ROOT / "scripts/evidently_zh.js").read_text(encoding="utf-8")
    localized = localized.replace("</head>", f"<title>{title} · Evidently</title></head>")
    localized = localized.replace("</body>", f"<script>{translation}</script></body>")
    path.write_text(localized, encoding="utf-8")
    snapshot.save_json(str(output / f"{name}.json"))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input-dir", type=Path, default=ROOT / "vendor/ai-energy-trading-platform/data/simulated")
    parser.add_argument("--output-dir", type=Path, default=ROOT / "runtime/evidently-reports")
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    frame = load_data(args.input_dir)
    features = WEATHER + ["availability_pct"]
    columns = ["date", *features, "weather_type", "actual_energy_mwh", "forecast_energy_mwh"]
    definition = DataDefinition(
        numerical_columns=features,
        categorical_columns=["weather_type"],
        datetime_columns=["date"],
        timestamp="date",
        regression=[Regression(target="actual_energy_mwh", prediction="forecast_energy_mwh")],
    )
    current = frame.loc[frame["date"] >= "2025-03-01", columns]
    reference = frame.loc[frame["date"] < "2025-03-01", columns]
    if len(current) < 10 or len(reference) < 10:
        raise ValueError("参考期或当前期样本不足")
    current_dataset = Dataset.from_pandas(current, data_definition=definition)
    reference_dataset = Dataset.from_pandas(reference, data_definition=definition)
    common = "上游阿尔法示例电站模拟数据；日级记录。参考期 2025 年 1–2 月，当前期 3 月。"
    reports = [
        ("quality", DataSummaryPreset(), "原始缺失与分布检视；未人为注入异常。"),
        ("drift", DataDriftPreset(), "跨季节比较中的分布变化可能来自季节性；漂移不等于模型失效。"),
        ("regression", RegressionPreset(), "目标为实际日发电量，预测为上游已提供的日预测电量，单位 MWh；未重新训练。天气用于事后分组，未核验其日前可用性。"),
    ]
    for name, preset, note in reports:
        snapshot = Report([preset]).run(current_data=current_dataset, reference_data=reference_dataset)
        export_report(snapshot, args.output_dir, name, common + note)
        print(f"Generated {name}.html", flush=True)
    valid = current.dropna(subset=["actual_energy_mwh", "forecast_energy_mwh"])
    error = valid["forecast_energy_mwh"] - valid["actual_energy_mwh"]
    metrics = {
        "source": "ai-energy-trading-platform upstream synthetic data",
        "granularity": "daily",
        "reference_rows": len(reference),
        "current_rows": len(current),
        "matched_rows": len(valid),
        "mae_mwh": float(error.abs().mean()),
        "rmse_mwh": float((error.pow(2).mean()) ** 0.5),
        "inputs": {name: hashlib.sha256((args.input_dir / name).read_bytes()).hexdigest() for name in ("actual_generation.csv", "generation_forecast.csv", "weather.csv")},
    }
    (args.output_dir / "manifest.json").write_text(json.dumps(metrics, ensure_ascii=False, indent=2), encoding="utf-8")
    links = "".join(f'<li><a href="{name}.html">{label}</a></li>' for name, label in (
        ("quality", "数据质量与分布"), ("drift", "参考期与当前期漂移"), ("regression", "日发电量预测误差")))
    index = f'''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><title>Evidently 试用报告</title>
<body style="max-width:900px;margin:48px auto;font:16px/1.9 sans-serif;padding:0 24px">
<h1>Evidently 试用报告</h1><p>{html.escape(common)}</p><ul>{links}</ul>
<p>当前期有效配对 {len(valid)} 天；平均绝对误差（MAE）{metrics['mae_mwh']:.2f} MWh；均方根误差（RMSE）{metrics['rmse_mwh']:.2f} MWh。</p>
<p>这组报告用于体验 Evidently 的数据和模型监测界面。它不自动确定影响因素，不执行模型训练或 Agent 自进化。</p>
<a href="manifest.json">数据来源与独立复算指标</a></body></html>'''
    (args.output_dir / "index.html").write_text(index, encoding="utf-8")
    print(json.dumps(metrics, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
