import { useCallback, useState } from "react";
import { ArrowUpRight, Crosshair, GitCompareArrows } from "lucide-react";
import type { EChartsOption, LineSeriesOption } from "echarts";
import type { Scope, Theme, Overview, Comparison, Interval } from "./types";
import { fmt, time, stamp, query, useResource } from "./api";
import { Panel, Status } from "./components";
import Chart, { baseOption, color } from "./Chart";

export default function Forecast({
  scope,
  data,
  loading,
  error,
  theme,
  capacity,
  onSelect,
  onRaw,
  revision,
}: {
  scope: Scope;
  data: Overview | null;
  loading: boolean;
  error: string;
  theme: Theme;
  capacity: number;
  onSelect: (value: string) => void;
  onRaw: () => void;
  revision: number;
}) {
  const compare = useResource<Comparison>(
    "/api/v1/workbench/compare?" + query(scope),
    revision,
  );
  const [version, setVersion] = useState("2.0");
  const intervals = data?.intervals || [];
  const chosen = compare.data?.versions.find((v) => v.version === version);
  const powerOption = useCallback((): EChartsOption => {
    const base = baseOption();
    const series = (
      name: string,
      field: keyof Interval,
      token: string,
      dashed = false,
    ): LineSeriesOption => ({
      name,
      type: "line",
      data: intervals.map((r) => r[field] as number | null),
      showSymbol: false,
      connectNulls: false,
      lineStyle: {
        color: color(token),
        width: 2,
        type: dashed ? "dashed" : "solid",
      },
      itemStyle: { color: color(token) },
    });
    const comparison: LineSeriesOption = {
      ...series(`对比 v${version}`, "compare_forecast_mw", "data", true),
      data: chosen
        ? intervals.map(
            (r) =>
              chosen.values.find((p) => p.interval_start === r.interval_start)
                ?.value ?? null,
          )
        : intervals.map((r) => r.compare_forecast_mw),
    };
    return {
      ...base,
      xAxis: {
        ...base.xAxis,
        data: intervals.map((r) => time(r.interval_start)),
      },
      yAxis: { ...base.yAxis, name: "MW" },
      dataZoom: [
        { type: "inside", start: 20, end: 85 },
        {
          type: "slider",
          height: 17,
          bottom: 10,
          borderColor: color("outline"),
          fillerColor: color("primary-container"),
          handleStyle: { color: color("primary") },
        },
      ],
      series: [
        {
          name: "置信下界",
          type: "line",
          data: intervals.map((r) => r.lower_mw),
          stack: "confidence",
          symbol: "none",
          lineStyle: { opacity: 0 },
          areaStyle: { opacity: 0 },
          tooltip: { show: false },
        },
        {
          name: "p10–p90 演示置信带",
          type: "line",
          data: intervals.map((r) =>
            r.upper_mw !== null && r.lower_mw !== null
              ? r.upper_mw - r.lower_mw
              : null,
          ),
          stack: "confidence",
          symbol: "none",
          lineStyle: { opacity: 0 },
          areaStyle: { color: color("primary-container"), opacity: 0.8 },
          itemStyle: { color: color("primary-container") },
          tooltip: { show: false },
        },
        series("晴空物理基线", "physical_clear_sky_mw", "data", true),
        comparison,
        series("日前主版本", "da_forecast_mw", "primary"),
        series("日内修正 · 新增信息", "id_corrected_mw", "warning"),
        series("实测", "actual_mw", "success"),
        {
          name: "超±5%容量偏差",
          type: "scatter",
          data: intervals.map((r) =>
            r.actual_mw !== null &&
            r.da_forecast_mw !== null &&
            Math.abs(r.actual_mw - r.da_forecast_mw) > capacity * 0.05
              ? r.actual_mw
              : null,
          ),
          symbolSize: 8,
          itemStyle: { color: color("error") },
          z: 8,
        },
      ],
    };
  }, [intervals, version, chosen, capacity]);
  const priceOption = useCallback((): EChartsOption => {
    const b = baseOption();
    return {
      ...b,
      grid: { left: 56, right: 50, top: 35, bottom: 32 },
      xAxis: { ...b.xAxis, data: intervals.map((r) => time(r.interval_start)) },
      yAxis: [
        { ...b.yAxis, name: "元/MWh" },
        { type: "value", name: "Δ RT−DA", splitLine: { show: false } },
      ],
      dataZoom: [{ type: "inside", start: 20, end: 85 }],
      series: [
        {
          name: "日前出清",
          type: "line",
          data: intervals.map((r) => r.da_price),
          symbol: "none",
          itemStyle: { color: color("primary") },
        },
        {
          name: "实时结算",
          type: "line",
          data: intervals.map((r) => r.rt_price),
          symbol: "none",
          itemStyle: { color: color("success") },
        },
        {
          name: "价差 Δ",
          type: "bar",
          yAxisIndex: 1,
          data: intervals.map((r) => ({
            value: r.spread_yuan_mwh,
            itemStyle: {
              color: color(
                (r.spread_yuan_mwh || 0) >= 0
                  ? "success-container"
                  : "warning-container",
              ),
            },
          })),
          barMaxWidth: 12,
        },
      ],
    };
  }, [intervals]);
  const selectIndex = useCallback(
    (i: number) => {
      if (intervals[i]) onSelect(intervals[i].interval_start);
    },
    [intervals, onSelect],
  );
  const k = data?.kpi;
  if (loading || error || !intervals.length)
    return <Status loading={loading} error={error} empty={!intervals.length} />;
  return (
    <>
      <div className="kpi-grid">
        <div className="kpi">
          <span>配对功率 MAE</span>
          <strong>
            {fmt(k?.power_mae_mw)}
            <small>MW</small>
          </strong>
          <p>
            RMSE {fmt(k?.power_rmse_mw)} MW · {k?.observed_count ?? 0}{" "}
            个配对时段
          </p>
        </div>
        <div className="kpi">
          <span>已到达实测电量</span>
          <strong>
            {fmt(k?.energy_actual_mwh)}
            <small>MWh</small>
          </strong>
          <p>同期预测 {fmt(k?.energy_forecast_matched_mwh)} MWh</p>
        </div>
        <div className="kpi">
          <span>实时 − 日前均价差</span>
          <strong>
            {fmt(k?.avg_spread)}
            <small>元/MWh</small>
          </strong>
          <p>仅统计两侧结算价格齐备时段</p>
        </div>
        <div className="kpi">
          <span>数据完整性</span>
          <strong>
            {k?.observed_count ?? 0}
            <small>/ {k?.due_count ?? 0} 应到</small>
          </strong>
          <p>
            <span
              className={k?.missing_count ? "text-warning" : "text-success"}
            >
              {k?.missing_count ?? 0} 个实测缺失
            </span>{" "}
            · 未来实测保持空值
          </p>
        </div>
      </div>
      <Panel
        title="功率预测与版本对比"
        subtitle="15 分钟时间轴 · 点击曲线或异常红点联动分析 · 两图缩放同步"
        action={
          <div className="head-tools">
            <select
              aria-label="对比模型版本"
              value={version}
              onChange={(e) => setVersion(e.target.value)}
            >
              {(compare.data?.versions || []).map((v) => (
                <option key={v.run_id} value={v.version}>
                  {v.model_name} v{v.version}
                </option>
              ))}
            </select>
            <button onClick={onRaw}>
              <ArrowUpRight size={15} />
              底层证据
            </button>
          </div>
        }
      >
        <Chart
          label="实测、预测、日内修正、晴空基线和置信带的96点功率图"
          option={powerOption}
          theme={theme}
          group="forecast-timeline"
          onPoint={selectIndex}
        />
        <div className="panel-note">
          <Crosshair size={14} />
          读取时点 {stamp(data!.cutoff_at)}（北京时间）
          <span>p10–p90 为合成区间示例，未作概率校准</span>
        </div>
      </Panel>
      <Panel
        title="现货电价与价差"
        subtitle="Δ = 实时结算价格 − 日前出清价格；未来结算价不补值"
      >
        <Chart
          label="日前和实时价格及实时减日前价差"
          option={priceOption}
          theme={theme}
          group="forecast-timeline"
          onPoint={selectIndex}
          compact
        />
      </Panel>
      <Panel
        title="同口径版本评估"
        subtitle="相同目标日、cutoff 与共同有效实测样本；演示场景版本未经模型训练"
        action={<GitCompareArrows size={19} className="text-primary" />}
      >
        <Status
          loading={compare.loading}
          error={compare.error}
          empty={!!compare.data && !compare.data.versions.length}
        />
        {!!compare.data?.versions.length && (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>模型版本</th>
                  <th>比较口径</th>
                  <th>cutoff · 北京时间</th>
                  <th>配对数</th>
                  <th>MAE / MW</th>
                  <th>RMSE / MW</th>
                  <th>操作</th>
                </tr>
              </thead>
              <tbody>
                {compare.data.versions.map((v) => (
                  <tr key={v.run_id}>
                    <td>
                      <strong>
                        {v.model_name} v{v.version}
                      </strong>
                    </td>
                    <td>
                      <span className="badge info">同 cutoff 对比</span>
                    </td>
                    <td>{stamp(v.cutoff_at)}</td>
                    <td>{v.sample_count}</td>
                    <td>{fmt(v.mae)}</td>
                    <td>{fmt(v.rmse)}</td>
                    <td>
                      <button
                        onClick={() => setVersion(v.version)}
                        aria-pressed={version === v.version}
                      >
                        叠加对比
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        {compare.data && (
          <div className="panel-note">
            <span className="badge warning">日内新增信息</span>同一批{" "}
            {compare.data.intraday.corrected.sample_count} 个实测时段：日前 MAE{" "}
            {fmt(compare.data.intraday.day_ahead.mae)} → 日内{" "}
            {fmt(compare.data.intraday.corrected.mae)} MW；此差异包含信息更新。
          </div>
        )}
      </Panel>
    </>
  );
}
