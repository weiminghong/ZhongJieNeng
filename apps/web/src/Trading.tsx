import { businessText } from "./presentation";
import { useCallback, useState } from "react";
import { Calculator, ShieldCheck } from "lucide-react";
import type { CustomSeriesOption, EChartsOption } from "echarts";
import type { Scope, Theme, Trading as TradingData } from "./types";
import { query, useResource, fmt, request, time } from "./api";
import { Panel, Status, Segments } from "./components";
import { SandboxPanel, PricePanel } from "./TradingAnalytics";
import Chart, { baseOption, color } from "./Chart";

export default function Trading({
  scope,
  theme,
  revision,
  onRefresh,
  onDateChange,
}: {
  scope: Scope;
  theme: Theme;
  revision: number;
  onRefresh: () => void;
  onDateChange: (date: string) => void;
}) {
  const result = useResource<TradingData>(
    "/api/v1/workbench/trading?" + query(scope),
    revision,
  );
  const [view, setView] = useState("revenue");
  const [planId, setPlanId] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const plans = [...(result.data?.plans || [])].sort((a, b) => {
    const rank = (name: string) =>
      name.includes("基准") ? 0 : name.includes("保守") ? 1 : 2;
    return rank(a.plan_name) - rank(b.plan_name);
  });
  const chosen = plans.find((p) => p.plan_id === planId) || plans[0];
  const waterfall = useCallback((): EChartsOption => {
    const b = baseOption();
    const names = [
      "中长期合同",
      "+日前现货",
      "±实时偏差",
      "−偏差考核",
      "净收益",
    ];
    const components = ["contract", "day_ahead", "real_time", "penalty"];
    let running = 0;
    const values = components.map((key, index) => {
      const from = running,
        delta = chosen?.components[key] ?? 0;
      running += delta;
      return [index, from, running, delta];
    });
    values.push([4, 0, running, running]);
    const tokens = ["primary", "data", "warning", "error", "success"];
    const series: CustomSeriesOption = {
      type: "custom",
      name: "收益构成",
      encode: { x: 0, y: [1, 2] },
      data: chosen?.net_revenue_yuan == null ? [] : values,
      renderItem: (params, api) => {
        const index = Number(api.value(0));
        const from = api.coord([index, Number(api.value(1))]);
        const to = api.coord([index, Number(api.value(2))]);
        const size = api.size?.([1, 0]) as number[];
        const width = Math.min(Math.abs(size[0]) * 0.6, 70);
        return {
          type: "rect",
          shape: {
            x: from[0] - width / 2,
            y: Math.min(from[1], to[1]),
            width,
            height: Math.max(Math.abs(from[1] - to[1]), 1),
          },
          style: { fill: color(tokens[params.dataIndex]) },
        };
      },
    };
    return {
      ...b,
      legend: { show: false },
      xAxis: {
        type: "category",
        axisLine: { lineStyle: { color: color("outline") } },
        boundaryGap: true,
        data: names,
        axisLabel: { interval: 0, fontSize: 10 },
      },
      yAxis: { ...b.yAxis, name: "元" },
      tooltip: {
        ...b.tooltip,
        trigger: "item",
        formatter: (p: unknown) => {
          const index = (p as { dataIndex: number }).dataIndex;
          return `${names[index]}<br/>${fmt(values[index][3])} 元<br/>累计 ${fmt(values[index][2])} 元`;
        },
      },
      series: [series],
    };
  }, [chosen]);
  const decomposition = useCallback((): EChartsOption => {
    const b = baseOption();
    return {
      ...b,
      xAxis: { type: "category", data: plans.map((p) => p.plan_name) },
      yAxis: { ...b.yAxis, name: "元" },
      series: [
        ...[
          ["contract", "中长期合同", "primary"],
          ["day_ahead", "日前现货", "data"],
          ["real_time", "实时偏差", "warning"],
          ["penalty", "偏差考核（扣减）", "error"],
        ].map(([key, name, token]) => ({
          name,
          type: "bar" as const,
          data: plans.map((p) =>
            p.net_revenue_yuan === null ? null : p.components[key],
          ),
          itemStyle: { color: color(token) },
          barMaxWidth: 30,
        })),
        {
          name: "净收益",
          type: "bar",
          data: plans.map((p) => p.net_revenue_yuan),
          itemStyle: { color: color("success") },
          barMaxWidth: 30,
        },
      ],
    };
  }, [plans]);
  const quantity = useCallback((): EChartsOption => {
    const b = baseOption();
    return {
      ...b,
      xAxis: {
        ...b.xAxis,
        data: plans[0]?.items.map((i) => time(i.interval_start)) || [],
      },
      yAxis: { ...b.yAxis, name: "MW" },
      dataZoom: [
        { type: "inside" },
        {
          type: "slider",
          height: 16,
          bottom: 8,
          fillerColor: color("primary-container"),
          borderColor: color("outline"),
        },
      ],
      series: plans.map((p, i) => ({
        name: p.plan_name,
        type: "line",
        symbol: "none",
        data: p.items.map((x) => x.bid_power_mw),
        itemStyle: { color: color(["primary", "success", "warning"][i]) },
      })),
    };
  }, [plans]);
  async function recalculate() {
    setBusy(true);
    setError("");
    try {
      await request("/api/v1/workbench/trading/recalculate", scope);
      onRefresh();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  return (
    <>
      <div className="notice">
        <ShieldCheck size={18} />
        <p>
          确定性结算引擎 ·
          数值全部来自数据库与规则参数。仅结算实测和价格齐备时段，未来收益保持未结算。
        </p>
        <button onClick={recalculate} disabled={busy}>
          <Calculator size={15} />
          {busy ? "正在计算并保存…" : "保存本次结算测算"}
        </button>
      </div>
      <Status
        loading={result.loading}
        error={result.error || error}
        empty={!!result.data && !plans.length}
      />
      {!!plans.length && (
        <>
          <div className="presentation-metrics">
            {plans.map((p) => (
              <div key={p.plan_id}>
                <span>{p.plan_name} · 净收益</span>
                <strong>
                  {fmt(p.net_revenue_yuan)}
                  <small> 元</small>
                </strong>
                <small>超阈考核 {fmt(-p.components.penalty)} 元</small>
              </div>
            ))}
            <div>
              <span>结算覆盖</span>
              <strong>
                {plans[0].settled_count} /{" "}
                {plans[0].settled_count + plans[0].unsettled_count}
              </strong>
              <small>{plans[0].unsettled_count} 个时段尚未结算</small>
            </div>
          </div>
          <Segments
            label="申报策略视图"
            value={view}
            onChange={setView}
            options={[
              ["revenue", "收益瀑布与对比"],
              ["sandbox", "调参沙盘与风险"],
              ["prices", "电价热力图与峰谷"],
              ["quantity", "96 点申报与规则"],
            ]}
          />
          {(view === "revenue" || view === "sandbox") && (
            <Segments
              label="结算方案"
              value={chosen.plan_id}
              onChange={setPlanId}
              options={plans.map((p) => [p.plan_id, p.plan_name] as const)}
            />
          )}
          {view === "sandbox" && (
            <SandboxPanel
              key={scope.station_id + scope.date + scope.mode}
              scope={scope}
              theme={theme}
              plan={chosen}
              revision={revision}
            />
          )}
          {view === "prices" && (
            <PricePanel
              scope={scope}
              theme={theme}
              revision={revision}
              onDateChange={onDateChange}
            />
          )}
          {view === "revenue" && (
            <>
              <Panel
                title={`${chosen.plan_name} · 收益瀑布`}
                subtitle="每一阶显示实际增减与累计金额，末阶为净收益；缺少配对记录不绘制金额"
              >
                <Chart
                  label="中长期、日前、实时、考核至净收益的累计收益瀑布图"
                  option={waterfall}
                  theme={theme}
                />
              </Panel>
              <Panel
                title="收益构成与方案比较"
                subtitle="中长期 + 日前现货 + 实时偏差 − 偏差考核 = 净收益；已实现配对范围内比较"
              >
                <Chart
                  label="三套申报方案的合同、日前、实时、考核与净收益柱图"
                  option={decomposition}
                  theme={theme}
                />
              </Panel>
              <Panel
                title="同口径方案结算明细"
                subtitle="相同实测与价格齐备时段 · 确定性引擎结果"
              >
                <div className="table-wrap">
                  <table className="presentation-table">
                    <thead>
                      <tr>
                        <th>申报方案</th>
                        <th>中长期合同</th>
                        <th>日前现货</th>
                        <th>实时偏差</th>
                        <th>偏差考核</th>
                        <th>净收益 / 元</th>
                      </tr>
                    </thead>
                    <tbody>
                      {plans.map((p) => (
                        <tr key={p.plan_id}>
                          <td>{p.plan_name}</td>
                          <td>{fmt(p.components.contract)}</td>
                          <td>{fmt(p.components.day_ahead)}</td>
                          <td>{fmt(p.components.real_time)}</td>
                          <td>{fmt(p.components.penalty)}</td>
                          <td>
                            <strong>{fmt(p.net_revenue_yuan)}</strong>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </Panel>
            </>
          )}
          {view === "quantity" && (
            <Panel
              title="96 点申报电量策略"
              subtitle="图示为功率报量 MW，分时电量按 0.25 小时换算 MWh；价差策略只使用预测信息"
            >
              <Chart
                label="三套申报方案的96点报量曲线"
                option={quantity}
                theme={theme}
                compact
              />
            </Panel>
          )}
          {view === "quantity" && (
            <Panel
              title="结算规则与边界"
              subtitle="演示规则已版本化落库；正式市场规则与真实合同尚未接入"
            >
              <div className="rule-grid">
                <div>
                  <strong>目标日已登记合约</strong>
                  <p>
                    {fmt(chosen.contract_summary.registered_energy_mwh)} MWh ·{" "}
                    {fmt(chosen.contract_summary.price_min_yuan_mwh)}—
                    {fmt(chosen.contract_summary.price_max_yuan_mwh)} 元/MWh
                  </p>
                  <small>{chosen.contract_summary.basis}</small>
                </div>
                <div>
                  <strong>偏差免考阈值</strong>
                  <p>
                    装机容量 ±{fmt(chosen.rule.exempt_fraction * 100, 0)}% ×
                    0.25h
                  </p>
                </div>
                <div>
                  <strong>超额偏差罚金</strong>
                  <p>
                    {fmt(chosen.rule.penalty_yuan_mwh, 0)}{" "}
                    元/MWh，超过免考部分计费
                  </p>
                </div>
              </div>
              <div className="panel-note warning-copy">
                {businessText(chosen.warning)}
              </div>
              <div className="formula">
                合同电量 × 合同价 + (申报电量 − 合同电量) × 日前价 + (实测电量 −
                申报电量) × 实时价 − 超免考偏差电量 × 考核单价
              </div>
            </Panel>
          )}
        </>
      )}
    </>
  );
}
