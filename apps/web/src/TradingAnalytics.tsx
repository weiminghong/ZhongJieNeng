import { businessText } from "./presentation";
import { useCallback, useEffect, useState } from "react";
import type { EChartsOption } from "echarts";
import type { MultiDay, Plan, Sandbox, Scope, Theme } from "./types";
import { fmt, query, request, stamp, useResource } from "./api";
import Chart, { baseOption, color } from "./Chart";
import { Panel, Segments, Status } from "./components";

export function SandboxPanel({
  scope,
  theme,
  plan,
  revision,
}: {
  scope: Scope;
  theme: Theme;
  plan: Plan;
  revision: number;
}) {
  const [bid, setBid] = useState(1);
  const [exempt, setExempt] = useState(plan.rule.exempt_fraction);
  const [penalty, setPenalty] = useState<number | null>(null);
  const [result, setResult] = useState<Sandbox | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const scopeKey = query(scope);
  useEffect(() => {
    setExempt(plan.rule.exempt_fraction);
    setPenalty(null);
  }, [plan.plan_id, plan.rule.exempt_fraction]);
  useEffect(() => {
    const controller = new AbortController();
    setLoading(true);
    setError("");
    setResult(null);
    const timer = window.setTimeout(() => {
      request<Sandbox>(
        "/api/v1/workbench/trading/sandbox",
        {
          ...Object.fromEntries(new URLSearchParams(scopeKey)),
          plan_id: plan.plan_id,
          bid_multiplier: bid,
          exempt_fraction: exempt,
          penalty_yuan_mwh: penalty,
        },
        controller.signal,
      )
        .then((value) => {
          if (!controller.signal.aborted) setResult(value);
        })
        .catch((e: Error) => {
          if (!controller.signal.aborted) setError(e.message);
        })
        .finally(() => {
          if (!controller.signal.aborted) setLoading(false);
        });
    }, 300);
    return () => {
      window.clearTimeout(timer);
      controller.abort();
    };
  }, [scopeKey, plan.plan_id, bid, exempt, penalty, revision]);
  const compare = useCallback((): EChartsOption => {
    const b = baseOption();
    return {
      ...b,
      xAxis: {
        type: "category",
        axisLine: { lineStyle: { color: color("outline") } },
        boundaryGap: true,
        data: ["中长期", "日前", "实时", "考核", "净收益"],
      },
      yAxis: { ...b.yAxis, name: "元" },
      series: (
        [
          ["baseline", "基准", "data"],
          ["simulated", "沙盘", "primary"],
        ] as const
      ).map(([key, name, token]) => ({
        name,
        type: "bar",
        barMaxWidth: 28,
        itemStyle: { color: color(token) },
        data: ["contract", "day_ahead", "real_time", "penalty"]
          .map((k) => result?.[key].components[k] ?? null)
          .concat(result?.[key].net_revenue_yuan ?? null),
      })),
    };
  }, [result]);
  const risk = result?.risk_assessment;
  return (
    <div className="analytics-grid sandbox-grid">
      <Panel
        title="参数沙盘"
        subtitle={`${plan.plan_name} · 调参后自动重算，仅在内存计算`}
        action={
          <button
            onClick={() => {
              setBid(1);
              setExempt(plan.rule.exempt_fraction);
              setPenalty(null);
            }}
          >
            一键重置
          </button>
        }
      >
        <div className="sandbox-controls">
          <label htmlFor="sandbox-bid">
            申报系数 <strong>{fmt(bid, 2)}×</strong>
            <input
              id="sandbox-bid"
              type="range"
              min="0.7"
              max="1.3"
              step="0.01"
              value={bid}
              onChange={(e) => setBid(Number(e.target.value))}
            />
          </label>
          <label htmlFor="sandbox-exempt">
            免考比例 <strong>{fmt(exempt * 100, 0)}%</strong>
            <input
              id="sandbox-exempt"
              type="range"
              min="0.01"
              max="0.15"
              step="0.01"
              value={exempt}
              onChange={(e) => setExempt(Number(e.target.value))}
            />
          </label>
          <label htmlFor="sandbox-penalty">
            考核单价{" "}
            <strong>
              {penalty === null
                ? `继承规则 ${fmt(plan.rule.penalty_yuan_mwh, 0)}`
                : fmt(penalty, 0)}{" "}
              元/MWh
            </strong>
            <input
              id="sandbox-penalty"
              type="range"
              min="0"
              max="500"
              step="10"
              value={penalty ?? Math.min(500, plan.rule.penalty_yuan_mwh)}
              onChange={(e) => setPenalty(Number(e.target.value))}
            />
          </label>
          <p className="muted">
            手调单价范围
            0–500；重置继承方案原规则（可高于手调上限），滑块此时停在上限。免考按装机容量
            × 比例 × 0.25h。
          </p>
        </div>
        <Status loading={loading} error={error} />
        {result && (
          <>
            <div className="sandbox-delta">
              <span>沙盘 − 基准净收益 Δ</span>
              <strong>
                {fmt(result.delta_net_revenue_yuan)} <small>元</small>
              </strong>
              <p>
                基准 {fmt(result.baseline.net_revenue_yuan)} → 沙盘{" "}
                {fmt(result.simulated.net_revenue_yuan)} 元 · 考核收益变动{" "}
                {fmt(result.delta_penalty_yuan)} 元
              </p>
              <p>
                {result.settled_count} 段已结算 · {result.unsettled_count}{" "}
                段未结算 · 超阈 {result.baseline.exceeded_count} →{" "}
                {result.simulated.exceeded_count} 段
              </p>
            </div>
            <Chart
              label="基准和沙盘的分项及净收益对比"
              option={compare}
              theme={theme}
              compact
            />
            <div className="panel-note warning-copy">{result.warning}</div>
          </>
        )}
      </Panel>
      <Panel
        title="三维风险与策略参考"
        subtitle="价格 40% + 偏差 30% + 天气 30% · 可见数据确定性评分"
      >
        {!result && <Status loading={loading} error={error} />}
        {risk && (
          <>
            <div className="risk-score">
              <span>综合风险 · {risk.level}</span>
              <strong>
                {fmt(risk.overall_score, 1)} <small>/ 100</small>
              </strong>
            </div>
            <div className="risk-dimensions">
              {(
                [
                  ["price_risk", "价格波动"],
                  ["deviation_risk", "偏差考核"],
                  ["weather_risk", "天气不确定性"],
                ] as const
              ).map(([key, label]) => (
                <div key={key}>
                  <label htmlFor={`risk-${key}`}>
                    {label}
                    <strong>{fmt(risk[key], 1)}</strong>
                  </label>
                  {risk[key] !== null && (
                    <progress
                      id={`risk-${key}`}
                      max={100}
                      value={risk[key]!}
                      aria-label={label}
                    />
                  )}
                </div>
              ))}
            </div>
            <div className="panel-note">{businessText(risk.basis)}</div>
            <div className="table-wrap">
              <table className="presentation-table strategy-matrix">
                <caption>合成演示沙盘口径 · 风险分档参考规则</caption>
                <thead>
                  <tr>
                    <th>档位 / 风险分</th>
                    <th>参考规则</th>
                  </tr>
                </thead>
                <tbody>
                  {result.strategy_matrix.map((row) => (
                    <tr
                      key={row.name}
                      className={row.active ? "selected-row" : ""}
                    >
                      <td>
                        <strong>{row.name}</strong>
                        <small>
                          {row.score_range}
                          {row.active ? " · 当前命中" : ""}
                        </small>
                      </td>
                      <td>{row.rule}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </>
        )}
      </Panel>
    </div>
  );
}

export function PricePanel({
  scope,
  theme,
  revision,
  onDateChange,
}: {
  scope: Scope;
  theme: Theme;
  revision: number;
  onDateChange: (date: string) => void;
}) {
  const result = useResource<MultiDay>(
    "/api/v1/workbench/multi-day?" + query(scope),
    revision,
  );
  const [metric, setMetric] = useState("da_price");
  const key = metric as "da_price" | "rt_price" | "spread_yuan_mwh";
  const data = result.data;
  const cells = data?.price_heatmap.cells.filter((c) => c[key] !== null) || [];
  const heatmap = useCallback((): EChartsOption => {
    const b = baseOption(),
      dates = data?.price_heatmap.dates || [];
    const values = cells.map((c) => c[key]!);
    const extent = Math.max(...values.map(Math.abs), 1);
    const min = key === "spread_yuan_mwh" ? -extent : Math.min(...values, 0);
    const max = key === "spread_yuan_mwh" ? extent : Math.max(...values, 1);
    return {
      ...b,
      grid: { left: 96, right: 30, top: 18, bottom: 86 },
      legend: { show: false },
      tooltip: {
        ...b.tooltip,
        trigger: "item",
        formatter: (p: unknown) => {
          const item = p as { dataIndex: number };
          const c = cells[item.dataIndex];
          return c
            ? `${c.trading_date} ${String(c.hour).padStart(2, "0")}:00<br/>${{ da_price: "日前", rt_price: "实时", spread_yuan_mwh: "RT−DA" }[key]} ${fmt(c[key])} 元/MWh`
            : "";
        },
      },
      xAxis: {
        type: "category",
        data: Array.from({ length: 24 }, (_, h) => String(h)),
        name: "小时",
        splitArea: {
          show: true,
          areaStyle: { color: [color("surface"), color("surface-container")] },
        },
      },
      yAxis: {
        type: "category",
        data: dates,
        axisLabel: { color: color("on-surface-variant") },
      },
      visualMap: {
        min,
        max,
        calculable: true,
        orient: "horizontal",
        left: "center",
        bottom: 6,
        text: ["高", "低"],
        textStyle: { color: color("on-surface-variant") },
        inRange: {
          color:
            key === "spread_yuan_mwh"
              ? [color("warning"), color("surface-container"), color("success")]
              : [
                  color("surface-container"),
                  color("primary-container"),
                  color("primary"),
                ],
        },
      },
      series: [
        {
          type: "heatmap",
          name: "小时均价",
          data: cells.map((c) => [
            c.hour,
            dates.indexOf(c.trading_date),
            c[key]!,
          ]),
          itemStyle: { borderWidth: 1, borderColor: color("surface") },
          emphasis: {
            itemStyle: { borderColor: color("on-surface"), borderWidth: 2 },
          },
        },
      ],
    };
  }, [data, cells, key]);
  const selectCell = useCallback(
    (index: number) => {
      if (cells[index]) onDateChange(cells[index].trading_date);
    },
    [cells, onDateChange],
  );
  if (result.loading || result.error || !data?.days.length)
    return (
      <Status
        loading={result.loading}
        error={result.error}
        empty={!data?.days.length}
      />
    );
  const periods = data.price_periods,
    backtest = periods.price_backtest;
  return (
    <>
      <Panel
        title="日期 × 24h 现货电价热力图"
        subtitle="库内多日可见记录的小时均值 · 无数据保留空白 · 点击单元格切换全局交易日"
      >
        <div className="panel-toolbar">
          <Segments
            label="热力图价格口径"
            value={metric}
            onChange={setMetric}
            options={[
              ["da_price", "日前"],
              ["rt_price", "实时"],
              ["spread_yuan_mwh", "价差 Δ"],
            ]}
          />
          <label>
            切换交易日{" "}
            <select
              aria-label="热力图交易日"
              value={scope.date}
              onChange={(e) => onDateChange(e.target.value)}
            >
              {data.days.map((d) => (
                <option key={d.trading_date}>{d.trading_date}</option>
              ))}
            </select>
          </label>
        </div>
        <Chart
          label="可点击切日的日期和24小时现货电价热力图"
          theme={theme}
          option={heatmap}
          onPoint={selectCell}
        />
        {!cells.length && (
          <div className="empty-inline">当前价格口径没有有效记录。</div>
        )}
      </Panel>
      <div className="presentation-metrics price-periods">
        {periods.periods.map((p) => (
          <div key={p.name}>
            <span>
              {p.name} · {p.window}
            </span>
            <strong>
              {fmt(p.spread_yuan_mwh)}
              <small> 元/MWh Δ</small>
            </strong>
            <small>
              日前 {fmt(p.da_price)} · 实时 {fmt(p.rt_price)} · 配对{" "}
              {p.sample_count}
            </small>
          </div>
        ))}
      </div>
      <Panel
        title="峰谷极值与电价回测"
        subtitle="库内多日可见预测与实测配对 · 指标不推断未来结算价格"
      >
        <div className="rule-grid">
          <div>
            <strong>最大正价差</strong>
            <p>
              {periods.max_positive
                ? `${stamp(periods.max_positive.interval_start)} · ${fmt(periods.max_positive.spread_yuan_mwh)} 元/MWh`
                : "无有效记录"}
            </p>
          </div>
          <div>
            <strong>最大负价差</strong>
            <p>
              {periods.max_negative
                ? `${stamp(periods.max_negative.interval_start)} · ${fmt(periods.max_negative.spread_yuan_mwh)} 元/MWh`
                : "无有效记录"}
            </p>
          </div>
          <div>
            <strong>日前电价 MAE</strong>
            <p>
              {fmt(backtest.da_price_mae)} 元/MWh ·{" "}
              {backtest.da_price_sample_count} 段
            </p>
          </div>
          <div>
            <strong>价差方向命中率</strong>
            <p>
              {fmt(backtest.spread_direction_accuracy_pct)}% ·{" "}
              {backtest.sample_count} 段
            </p>
          </div>
        </div>
        <div className="panel-note">{businessText(backtest.basis)}</div>
      </Panel>
    </>
  );
}
