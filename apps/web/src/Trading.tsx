import { useCallback, useState } from "react";
import { Calculator, ShieldCheck } from "lucide-react";
import type { EChartsOption } from "echarts";
import type { Scope, Theme, Trading as TradingData } from "./types";
import { query, useResource, fmt, request, time } from "./api";
import { Panel, Status } from "./components";
import Chart, { baseOption, color } from "./Chart";

export default function Trading({
  scope,
  theme,
  revision,
  onRefresh,
}: {
  scope: Scope;
  theme: Theme;
  revision: number;
  onRefresh: () => void;
}) {
  const result = useResource<TradingData>(
    "/api/v1/workbench/trading?" + query(scope),
    revision,
  );
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const plans = result.data?.plans || [];
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
          {busy ? "正在重算…" : "重新测算并落库"}
        </button>
      </div>
      <Status
        loading={result.loading}
        error={result.error || error}
        empty={!!result.data && !plans.length}
      />
      {!!plans.length && (
        <>
          <div className="plan-grid">
            {plans.map((p) => (
              <section className="plan" key={p.plan_id}>
                <div className="plan-title">
                  <h2>{p.plan_name}</h2>
                  <span className="badge">合成沙盘</span>
                </div>
                <span className="muted">配对范围净收益</span>
                <strong>
                  {fmt(p.net_revenue_yuan)}
                  <small>元</small>
                </strong>
                <dl>
                  <dt>超阈考核</dt>
                  <dd className="text-error">
                    {fmt(-p.components.penalty)} 元
                  </dd>
                  <dt>结算覆盖</dt>
                  <dd>
                    {p.settled_count} / {p.settled_count + p.unsettled_count}{" "}
                    时段
                  </dd>
                </dl>
                <p>{p.unsettled_count} 个时段未结算</p>
              </section>
            ))}
          </div>
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
          <Panel
            title="结算规则与边界"
            subtitle="演示规则已版本化落库；正式市场规则与真实合同尚未接入"
          >
            <div className="rule-grid">
              <div>
                <strong>中长期锁价</strong>
                <p>日前基准电量的 70%，380 元/MWh</p>
              </div>
              <div>
                <strong>偏差免考阈值</strong>
                <p>
                  装机容量 ±{fmt(plans[0].rule.exempt_fraction * 100, 0)}% ×
                  0.25h
                </p>
              </div>
              <div>
                <strong>超额偏差罚金</strong>
                <p>
                  {fmt(plans[0].rule.penalty_yuan_mwh, 0)}{" "}
                  元/MWh，超过免考部分计费
                </p>
              </div>
            </div>
            <div className="panel-note warning-copy">{plans[0].warning}</div>
            <div className="formula">
              合同电量 × 合同价 + (申报电量 − 合同电量) × 日前价 + (实测电量 −
              申报电量) × 实时价 − 超免考偏差电量 × 考核单价
            </div>
          </Panel>
        </>
      )}
    </>
  );
}
