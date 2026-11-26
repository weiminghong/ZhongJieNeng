import { useCallback } from "react";
import type { EChartsOption } from "echarts";
import type { Interval, MultiDay, Scope, Theme } from "./types";
import { fmt, query, stamp, useResource } from "./api";
import Chart, { baseOption, color } from "./Chart";
import { Panel, Status } from "./components";

export default function ForecastAnalytics({
  view,
  scope,
  theme,
  revision,
  intervals,
  capacity,
  direction,
  onSelect,
  onDateChange,
}: {
  view: string;
  scope: Scope;
  theme: Theme;
  revision: number;
  intervals: Interval[];
  capacity: number;
  direction:
    | {
        positive: { count: number; mean_bias_mw: number | null };
        negative: { count: number; mean_bias_mw: number | null };
      }
    | undefined;
  onSelect: (value: string) => void;
  onDateChange: (date: string) => void;
}) {
  const result = useResource<MultiDay>(
    "/api/v1/workbench/multi-day?" + query(scope),
    revision,
  );
  const data = result.data;
  const paired = intervals.filter(
    (r) => r.actual_mw !== null && r.da_forecast_mw !== null,
  );
  const continuous = useCallback((): EChartsOption => {
    const b = baseOption();
    const series = data?.series || [];
    const first = series.findIndex((r) => r.trading_date === scope.date);
    const last = series.map((r) => r.trading_date).lastIndexOf(scope.date);
    return {
      ...b,
      xAxis: { ...b.xAxis, data: series.map((r) => stamp(r.interval_start)) },
      yAxis: { ...b.yAxis, name: "MW" },
      dataZoom: [
        { type: "inside" },
        {
          type: "slider",
          height: 18,
          bottom: 8,
          borderColor: color("outline"),
          fillerColor: color("primary-container"),
        },
      ],
      series: (
        [
          ["actual_mw", "实测", "success"],
          ["physical_clear_sky_mw", "晴空基线", "data"],
          ["da_forecast_mw", "日前预测", "primary"],
          ["id_corrected_mw", "日内修正", "warning"],
        ] as const
      ).map(([field, name, token], i) => ({
        name,
        type: "line",
        showSymbol: false,
        connectNulls: false,
        data: series.map((r) => r[field]),
        itemStyle: { color: color(token) },
        lineStyle: { type: i === 1 ? "dashed" : "solid" },
        ...(i === 0 && first >= 0
          ? {
              markArea: {
                silent: true,
                itemStyle: { color: color("primary-container"), opacity: 0.5 },
                label: { color: color("primary"), position: "insideTop" },
                data: [
                  [
                    { name: `选中日 ${scope.date}`, xAxis: first },
                    { xAxis: last },
                  ],
                ],
              },
            }
          : {}),
      })),
    };
  }, [data, scope.date]);
  const scatter = useCallback((): EChartsOption => {
    const b = baseOption();
    const max = Math.max(
      capacity,
      ...paired.flatMap((r) => [r.actual_mw!, r.da_forecast_mw!]),
      1,
    );
    return {
      ...b,
      tooltip: {
        ...b.tooltip,
        trigger: "item",
        formatter: (p: unknown) => {
          const item = p as { dataIndex: number };
          const r = paired[item.dataIndex];
          return r
            ? `${stamp(r.interval_start)}<br/>预测 ${fmt(r.da_forecast_mw)} / 实测 ${fmt(r.actual_mw)} MW<br/>${Math.abs(r.actual_mw! - r.da_forecast_mw!) > capacity * 0.05 ? "超±5%容量容差" : "容差内"}`
            : "";
        },
      },
      xAxis: { type: "value", name: "预测 MW", min: 0, max },
      yAxis: { ...b.yAxis, name: "实测 MW", min: 0, max },
      series: [
        {
          name: "配对时段",
          type: "scatter",
          symbolSize: 9,
          data: paired.map((r) => ({
            value: [r.da_forecast_mw, r.actual_mw],
            itemStyle: {
              color: color(
                Math.abs(r.actual_mw! - r.da_forecast_mw!) > capacity * 0.05
                  ? "error"
                  : "success",
              ),
            },
          })),
          markLine: {
            silent: true,
            symbol: "none",
            label: { formatter: "y=x", color: color("data") },
            lineStyle: { color: color("data"), type: "dashed" },
            data: [[{ coord: [0, 0] }, { coord: [max, max] }]],
          },
        },
      ],
    };
  }, [paired, capacity]);
  const histogram = useCallback((): EChartsOption => {
    const b = baseOption();
    const errors = paired.map((r) => r.actual_mw! - r.da_forecast_mw!);
    const extent = Math.max(...errors.map(Math.abs), 1),
      width = (extent * 2) / 12;
    const counts = Array<number>(12).fill(0);
    errors.forEach(
      (e) => counts[Math.min(11, Math.floor((e + extent) / width))]++,
    );
    return {
      ...b,
      legend: { show: false },
      xAxis: {
        type: "category",
        axisLine: { lineStyle: { color: color("outline") } },
        boundaryGap: true,
        name: "MW",
        data: counts.map(
          (_, i) =>
            `${fmt(-extent + i * width, 1)}~${fmt(-extent + (i + 1) * width, 1)}`,
        ),
        axisLabel: { rotate: 35, fontSize: 10 },
      },
      yAxis: { ...b.yAxis, name: "时段数", minInterval: 1 },
      series: [
        {
          type: "bar",
          name: "偏差频数",
          barCategoryGap: "5%",
          data: counts.map((v, i) => ({
            value: v,
            itemStyle: { color: color(i < 6 ? "warning" : "success") },
          })),
        },
      ],
    };
  }, [paired]);
  const weather = useCallback((): EChartsOption => {
    const b = baseOption(),
      buckets = data?.weather_buckets || [];
    return {
      ...b,
      xAxis: {
        type: "category",
        axisLine: { lineStyle: { color: color("outline") } },
        boundaryGap: true,
        data: buckets.map((r) => `${r.name}\n样本 ${r.sample_count}`),
      },
      yAxis: { ...b.yAxis, name: "MAE / MW" },
      series: [
        {
          name: "MAE",
          type: "bar",
          barMaxWidth: 44,
          data: buckets.map((r) => r.mae),
          itemStyle: { color: color("primary") },
        },
      ],
    };
  }, [data]);
  const times = useCallback((): EChartsOption => {
    const b = baseOption(),
      buckets = data?.time_buckets || [];
    return {
      ...b,
      xAxis: {
        type: "category",
        axisLine: { lineStyle: { color: color("outline") } },
        boundaryGap: true,
        data: buckets.map((r) => `${r.name}\n样本 ${r.sample_count}`),
        axisLabel: { interval: 0, fontSize: 10 },
      },
      yAxis: { ...b.yAxis, name: "MW" },
      series: (
        [
          ["mae", "MAE", "primary"],
          ["mbe", "MBE", "warning"],
        ] as const
      ).map(([key, name, token]) => ({
        name,
        type: "bar",
        barMaxWidth: 24,
        data: buckets.map((r) => r[key]),
        itemStyle: { color: color(token) },
      })),
    };
  }, [data]);
  const selectPair = useCallback(
    (index: number) => {
      if (paired[index]) onSelect(paired[index].interval_start);
    },
    [paired, onSelect],
  );
  if (result.loading || result.error || !data?.days.length)
    return (
      <Status
        loading={result.loading}
        error={result.error}
        empty={!data?.days.length}
      />
    );
  if (view === "multi")
    return (
      <>
        <Panel
          title="连续多日功率曲线"
          subtitle="库内可见交易日 · 滑块缩放 · 浅蓝区域标记全局选中日"
        >
          <Chart
            label="连续多日实测、晴空、日前和日内功率曲线"
            theme={theme}
            option={continuous}
          />
        </Panel>
        <Panel
          title="每日 KPI 对比"
          subtitle="点击日期行切换全局日期并返回单日精看；电量与误差保留有效配对口径"
        >
          <div className="table-wrap">
            <table className="presentation-table">
              <thead>
                <tr>
                  {[
                    "交易日",
                    "实测 MWh",
                    "同期预测 MWh",
                    "MAE MW",
                    "RMSE MW",
                    "MBE MW",
                    "均价差 元/MWh",
                    "配对 / 应到",
                  ].map((t) => (
                    <th key={t}>{t}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {data.days.map((d) => (
                  <tr
                    key={d.trading_date}
                    tabIndex={0}
                    aria-label={`切换至 ${d.trading_date}`}
                    className={
                      scope.date === d.trading_date ? "selected-row" : ""
                    }
                    onClick={() => onDateChange(d.trading_date)}
                    onKeyDown={(e) => {
                      if (e.key === "Enter" || e.key === " ") {
                        e.preventDefault();
                        onDateChange(d.trading_date);
                      }
                    }}
                  >
                    <td>
                      <button
                        onClick={(e) => {
                          e.stopPropagation();
                          onDateChange(d.trading_date);
                        }}
                      >
                        {d.trading_date}
                      </button>
                    </td>
                    <td>{fmt(d.energy_actual_mwh)}</td>
                    <td>{fmt(d.energy_forecast_matched_mwh)}</td>
                    <td>{fmt(d.power_mae_mw)}</td>
                    <td>{fmt(d.power_rmse_mw)}</td>
                    <td>{fmt(d.mbe_mw)}</td>
                    <td>{fmt(d.avg_spread)}</td>
                    <td>
                      {d.observed_count} / {d.due_count}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Panel>
      </>
    );
  return (
    <div className="analytics-grid">
      <Panel
        title="预测 vs 实测"
        subtitle={`${scope.date} · y=x 理想线 · 红点表示超±5%容量偏差，点击联动选中时段`}
      >
        <Chart
          label="预测与实测散点图，红点超容差，可点击时段联动"
          theme={theme}
          option={scatter}
          onPoint={selectPair}
          compact
        />
        {!paired.length && (
          <div className="empty-inline">当前日没有配对功率记录。</div>
        )}
        <div className="panel-note">
          <label>
            键盘选中时段{" "}
            <select
              aria-label="诊断配对时段"
              value={scope.selected_interval || ""}
              onChange={(e) => {
                if (e.target.value) onSelect(e.target.value);
              }}
            >
              <option value="">请选择</option>
              {paired.map((r) => (
                <option key={r.interval_start} value={r.interval_start}>
                  {stamp(r.interval_start)}
                </option>
              ))}
            </select>
          </label>
        </div>
      </Panel>
      <Panel
        title="偏差分布"
        subtitle="当日实测 − 预测 MW · 正值为模型低估，负值为模型高估"
      >
        <Chart
          label="当日功率偏差频数直方图"
          theme={theme}
          option={histogram}
          compact
        />
        <div className="panel-note">
          正偏差 {direction?.positive.count ?? 0} 段 / 均值{" "}
          {fmt(direction?.positive.mean_bias_mw)} MW · 负偏差{" "}
          {direction?.negative.count ?? 0} 段 / 均值{" "}
          {fmt(direction?.negative.mean_bias_mw)} MW
        </div>
      </Panel>
      <Panel
        title="分天气类型误差"
        subtitle="库内多日真实配对 · 云量缺失不分组 · n 为配对样本数"
      >
        <Chart
          label="晴朗、少云和多云阴天的功率MAE与样本数"
          theme={theme}
          option={weather}
          compact
        />
      </Panel>
      <Panel
        title="白昼爬坡与午峰误差"
        subtitle="库内多日配对 · MAE 为幅度，MBE 保留方向"
      >
        <Chart
          label="四个白昼时段的MAE和MBE"
          theme={theme}
          option={times}
          compact
        />
      </Panel>
    </div>
  );
}
