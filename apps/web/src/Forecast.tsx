import { useCallback, useRef, useState } from "react";
import { ArrowUpRight, Crosshair, GitCompareArrows } from "lucide-react";
import type { EChartsOption, LineSeriesOption } from "echarts";
import type { Scope, Theme, Overview, Comparison, Interval, Inference, RuntimeModel } from "./types";
import { fmt, time, stamp, query, useResource, request } from "./api";
import ForecastAnalytics from "./ForecastAnalytics";
import { Panel, Status, Segments } from "./components";
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
  onDateChange,
  overlay,
  onOverlay,
  onClearOverlay,
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
  onDateChange: (date: string) => void;
  overlay: Inference | null;
  onOverlay: (data: Inference) => void;
  onClearOverlay: () => void;
}) {
  const compare = useResource<Comparison>(
    "/api/v1/workbench/compare?" + query(scope),
    revision,
  );
  const [view, setView] = useState("single");
  const [version, setVersion] = useState("2.0");
  const [inferBusy, setInferBusy] = useState(false);
  const [inferError, setInferError] = useState("");
  const [runtimeId, setRuntimeId] = useState("");
  const runtime = useResource<{ models: RuntimeModel[] }>("/api/v1/models/runtime", revision);
  const context = JSON.stringify(scope);
  const currentContext = useRef(context);
  currentContext.current = context;
  async function infer() {
    const captured = context;
    setInferBusy(true); setInferError("");
    try { const result = await request<Inference>("/api/v1/models/predict", { ...scope, model_version_id: runtimeId || null }); if (captured === currentContext.current) onOverlay(result); }
    catch (e) { if (captured === currentContext.current) setInferError((e as Error).message); }
    finally { setInferBusy(false); }
  }
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
      legend: {
        top: 4,
        type: "scroll",
        textStyle: { color: color("on-surface-variant"), fontSize: 11 },
        data: [
          "p10–p90 演示置信带",
          "晴空物理基线",
          `对比 v${version}`,
          "日前主版本",
          "日内修正 · 新增信息",
          "实测",
          "超±5%容量偏差",
          ...(overlay ? ["小模型实时推理"] : []),
        ],
      },
      xAxis: {
        ...base.xAxis,
        data: intervals.map((r) => time(r.interval_start)),
      },
      yAxis: { ...base.yAxis, name: "MW" },
      dataZoom: [
        { type: "inside", start: 0, end: 100 },
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
        ...(overlay ? [{ name: "小模型实时推理", type: "line" as const, symbol: "none", data: intervals.map(r => overlay.points.find(p => p.interval_start === r.interval_start)?.predicted_mw ?? null), lineStyle: { color: color("error"), type: "dashed" as const, width: 2 }, itemStyle: { color: color("error") } }] : []),
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
        {
          ...series("日前主版本", "da_forecast_mw", "primary"),
          areaStyle: {
            color: {
              type: "linear",
              x: 0,
              y: 0,
              x2: 0,
              y2: 1,
              colorStops: [
                { offset: 0, color: color("primary-container") },
                { offset: 1, color: color("surface") },
              ],
            },
            opacity: 0.55,
          },
          markLine: {
            symbol: "none",
            label: {
              formatter: "14:00 数据时钟",
              color: color("on-surface-variant"),
              position: "insideEndTop",
            },
            lineStyle: { color: color("warning"), type: "dashed" },
            data: [{ xAxis: "14:00" }],
          },
        },
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
  }, [intervals, version, chosen, capacity, overlay]);
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
      dataZoom: [{ type: "inside", start: 0, end: 100 }],
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
  const peak = intervals
    .filter((r) => r.da_forecast_mw !== null)
    .reduce<Interval | null>(
      (best, r) =>
        !best || r.da_forecast_mw! > best.da_forecast_mw! ? r : best,
      null,
    );
  if (loading || error || !intervals.length)
    return <Status loading={loading} error={error} empty={!intervals.length} />;
  return (
    <>
      <div className="presentation-metrics">
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
      <Segments
        label="预测分析视图"
        value={view}
        onChange={setView}
        options={[
          ["single", "单日精看"],
          ["multi", "多日连看"],
          ["diagnostics", "误差与天气诊断"],
        ]}
      />
      {view !== "single" && (
        <ForecastAnalytics
          view={view}
          scope={scope}
          theme={theme}
          revision={revision}
          intervals={intervals}
          capacity={capacity}
          direction={k?.direction_breakdown}
          onSelect={onSelect}
          onDateChange={(d) => {
            onDateChange(d);
            setView("single");
          }}
        />
      )}
      {view === "single" && (
        <div className="forecast-workspace">
          <div className="forecast-charts">
            <Panel
              title="功率预测与版本对比"
              subtitle={`15 分钟时间轴 · 预测峰值 ${fmt(peak?.da_forecast_mw)} MW · ${peak ? time(peak.interval_start) : "—"} · 点击联动分析`}
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
              {overlay && <div className="selection-bar"><span>{overlay.model_name} v{overlay.version} · {fmt(overlay.latency_ms, 0)} ms · {overlay.trained_scope}</span><button onClick={onClearOverlay}>清除叠加</button></div>}
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
                <span>
                  p10–p90 实测覆盖率 {fmt(k?.interval_coverage_pct)}% ·
                  合成区间未作概率校准
                </span>
                <span>
                  MBE {fmt(k?.mbe)} MW · Skill Score{" "}
                  {fmt(k?.skill_score == null ? null : k.skill_score * 100)}
                  %（相对晴空基线改进）
                </span>
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
          </div>
          <div className="forecast-insights">
            <Panel
              title="同口径版本对比"
              subtitle="相同目标日、cutoff 与共同有效实测样本；演示场景版本未经模型训练"
              action={<GitCompareArrows size={19} className="text-primary" />}
            >
              <div className="head-tools"><select aria-label="预测小模型运行时" value={runtimeId} onChange={e => setRuntimeId(e.target.value)}><option value="">内置 PIT 残差模型</option>{runtime.data?.models.filter(m => m.ready && m.source_mode === scope.source_mode && m.task === "day_ahead_power").map(m => <option key={m.model_version_id} value={m.model_version_id}>{m.model_name} v{m.version}</option>)}</select><button disabled={inferBusy} onClick={() => void infer()}>{inferBusy ? "正在推理…" : "实时推理叠加"}</button></div>
              <Status error={inferError || runtime.error} />
              <Status
                loading={compare.loading}
                error={compare.error}
                empty={!!compare.data && !compare.data.versions.length}
              />
              {!!compare.data?.versions.length && (
                <div className="comparison-basis">
                  共同截止 {stamp(compare.data.versions[0].cutoff_at)} ·
                  共同有效实测样本
                </div>
              )}
              {!!compare.data?.versions.length && (
                <div className="table-wrap">
                  <table className="presentation-table version-table">
                    <thead>
                      <tr>
                        <th>模型版本</th>

                        <th>配对数</th>
                        <th>MAE / MW</th>
                        <th>MBE / MW</th>
                        <th>Skill / %</th>
                        <th>覆盖率 / %</th>
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
                            <small>同 cutoff · 未训练场景</small>
                          </td>
                          <td>{v.sample_count}</td>
                          <td>
                            <strong>{fmt(v.mae)}</strong>
                            <progress
                              aria-label={`v${v.version} MAE，相同样本比较`}
                              value={v.mae ?? 0}
                              max={Math.max(
                                ...compare.data!.versions.map(
                                  (x) => x.mae ?? 0,
                                ),
                                1,
                              )}
                            />
                            <small>RMSE {fmt(v.rmse)}</small>
                          </td>
                          <td>{fmt(v.mbe)}</td>
                          <td>
                            {fmt(
                              v.skill_score == null
                                ? null
                                : v.skill_score * 100,
                            )}
                          </td>
                          <td>{fmt(v.interval_coverage_pct)}</td>
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
                  {compare.data.intraday.corrected.sample_count}{" "}
                  个实测时段：日前 MAE{" "}
                  {fmt(compare.data.intraday.day_ahead.mae)} → 日内{" "}
                  {fmt(compare.data.intraday.corrected.mae)}{" "}
                  MW；此差异包含信息更新。
                </div>
              )}
            </Panel>
            <Panel
              title="超阈偏差 Top 时段"
              subtitle="按绝对偏差排序 · 合成 ±5% 容量沙盘阈值"
            >
              <div className="deviation-list">
                {intervals
                  .filter(
                    (r) =>
                      r.actual_mw !== null &&
                      r.da_forecast_mw !== null &&
                      Math.abs(r.actual_mw - r.da_forecast_mw) >
                        capacity * 0.05,
                  )
                  .sort(
                    (a, b) =>
                      Math.abs(b.actual_mw! - b.da_forecast_mw!) -
                      Math.abs(a.actual_mw! - a.da_forecast_mw!),
                  )
                  .slice(0, 6)
                  .map((r) => (
                    <button
                      key={r.interval_start}
                      aria-pressed={
                        scope.selected_interval === r.interval_start
                      }
                      onClick={() => onSelect(r.interval_start)}
                    >
                      <span>
                        <strong>
                          {time(r.interval_start)}—{time(r.interval_end)}
                        </strong>
                        <small>
                          实测 {fmt(r.actual_mw)} / 预测 {fmt(r.da_forecast_mw)}
                        </small>
                      </span>
                      <strong className="text-error">
                        {fmt(r.actual_mw! - r.da_forecast_mw!)} MW
                      </strong>
                      <ArrowUpRight size={14} />
                    </button>
                  ))}
                {!intervals.some(
                  (r) =>
                    r.actual_mw !== null &&
                    r.da_forecast_mw !== null &&
                    Math.abs(r.actual_mw - r.da_forecast_mw) > capacity * 0.05,
                ) && (
                  <div className="empty-inline">
                    当前可见实测时段无超阈偏差。
                  </div>
                )}
              </div>
              <div className="panel-note">
                <button onClick={onRaw}>查看选中时段的数据血缘</button>
              </div>
            </Panel>
          </div>
        </div>
      )}
    </>
  );
}
