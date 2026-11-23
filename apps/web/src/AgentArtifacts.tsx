import { useCallback } from "react";
import type { EChartsOption } from "echarts";
import Chart, { baseOption, color } from "./Chart";
import type { AgentArtifact, Inference, Theme } from "./types";
import { fmt, time } from "./api";

export function ForecastMini({ data, theme }: { data: Inference; theme: Theme }) {
  const option = useCallback((): EChartsOption => {
    const base = baseOption();
    return { ...base, grid: { left: 44, right: 16, top: 42, bottom: 30 },
      xAxis: { ...base.xAxis, data: data.points.map(p => time(p.interval_start)) },
      yAxis: { ...base.yAxis, name: "MW" },
      series: [
        { name: "小模型实时预测", type: "line", symbol: "none", data: data.points.map(p => p.predicted_mw), lineStyle: { color: color("primary"), type: "dashed" }, itemStyle: { color: color("primary") } },
        { name: "线上预测", type: "line", symbol: "none", data: data.points.map(p => p.online_mw), itemStyle: { color: color("data") } },
        { name: "可见实测", type: "line", symbol: "none", data: data.points.map(p => p.actual_mw), itemStyle: { color: color("success") } },
      ] };
  }, [data]);
  return <Chart compact label="小模型、线上预测与截止时点可见实测对比" theme={theme} option={option} />;
}

export default function AgentArtifacts({ artifacts, theme, onOverlay }: { artifacts: AgentArtifact[]; theme: Theme; onOverlay?: (data: Inference) => void }) {
  return <div className="agent-artifacts">{artifacts.map((a, i) => <section key={i} className="artifact-card">
    <h3>{a.title}</h3>
    {a.type === "forecast_overlay" ? <>
      <ForecastMini data={a.data} theme={theme} />
      <div className="artifact-metrics"><span>小模型 MAE <strong>{fmt(a.data.metrics.online_comparison.runtime_mae)} MW</strong></span><span>线上 MAE <strong>{fmt(a.data.metrics.online_comparison.online_mae)} MW</strong></span><span>共同实测样本 <strong>{a.data.metrics.online_comparison.sample_count}</strong></span></div>
      <p className="muted">{a.data.model_name} v{a.data.version} · {fmt(a.data.latency_ms, 0)} ms · {a.data.trained_scope} · {a.data.source_mode}</p>
      {onOverlay && <button onClick={() => onOverlay(a.data)}>叠加到预测主图</button>}
    </> : a.type === "deviation_top" ? <div className="table-wrap"><table><thead><tr><th>时段</th><th>实测−预测 MW</th><th>判断边界</th></tr></thead><tbody>{a.data.map(r => <tr key={r.interval_start}><td>{time(r.interval_start)}</td><td>{fmt(r.error_mw)}</td><td>{r.interpretation}</td></tr>)}</tbody></table>{!a.data.length && <p>暂无可见配对偏差</p>}</div>
    : Array.isArray(a.data) ? <div className="table-wrap"><table><thead><tr><th>方案</th><th>净收益 / 元</th><th>结算时段</th></tr></thead><tbody>{a.data.map(r => <tr key={r.plan_id}><td>{r.plan_name}</td><td>{fmt(r.net_revenue_yuan)}</td><td>{r.settled_count}</td></tr>)}</tbody></table></div>
    : a.data.status === "unavailable" ? <p role="status">{a.data.reason}</p> : <><div className="artifact-metrics"><span>Δ 净收益 <strong>{fmt(a.data.delta_net_revenue_yuan)} 元</strong></span><span>Δ 考核项 <strong>{fmt(a.data.delta_penalty_yuan)} 元</strong></span><span>已结算 <strong>{a.data.settled_count} 时段</strong></span></div><p className="muted">{a.data.warning}</p></>}
    <small className="muted">证据工具：{a.tool_name}</small>
  </section>)}</div>;
}
