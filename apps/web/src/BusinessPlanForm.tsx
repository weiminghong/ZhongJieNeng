import { businessText } from "./presentation";
import type { BusinessPrediction, PlanParameters } from "./businessTypes";

export const defaultPlanParameters: PlanParameters = { mode: "manual", bid_ratio: 1, fee_yuan_mwh: 0, min_ratio: 0, max_ratio: 1.5, spread_threshold: 0, ratio_step: .1, max_bid_mwh: null };
export default function BusinessPlanForm({ predictions, record, setRecord, parameters: p, setParameters, priceRecords, setPriceRecords }: {
  predictions: BusinessPrediction[]; record: string; setRecord: (record: string) => void;
  parameters: PlanParameters; setParameters: (parameters: PlanParameters) => void;
  priceRecords: Record<string, string>; setPriceRecords: (records: Record<string, string>) => void;
}) {
  const numeric = (field: keyof PlanParameters, value: string) => setParameters({ ...p, [field]: field === "max_bid_mwh" && value === "" ? null : Number(value) });
  const prices = [
    { key: "da_record_id", task: "da_price_reference", name: "日前价格预测" },
    { key: "rt_record_id", task: "rt_price_day_ahead_reference", name: "实时价格预测" },
    { key: "spread_record_id", task: "prebid_spread_reference", name: "申报前价差预测" },
  ];
  const bound = predictions.find((r) => r.record_id === record);
  const compatible = predictions.filter((r) => bound && r.input_source_hash === bound.input_source_hash && r.cutoff_at === bound.cutoff_at && r.information_budget === bound.information_budget);
  return <div className="business-form-grid">
    <label className="business-form-wide">绑定的光伏日前预测<select aria-label="方案绑定的光伏日前预测" value={record} onChange={(e) => setRecord(e.target.value)}><option value="">请选择已保存的预测</option>{predictions.filter((r) => r.task === "pv_day_ahead_reference").map((r) => <option key={r.id} value={r.record_id}>{businessText(r.name)}</option>)}</select></label>
    <label>申报方式<select value={p.mode} onChange={(e) => setParameters({ ...p, mode: e.target.value as PlanParameters["mode"] })}><option value="manual">固定申报系数</option><option value="spread_rule">按预测价差调整</option></select></label>
    <label>基础申报系数<input type="number" min={0} max={1.5} step={.05} value={p.bid_ratio} onChange={(e) => numeric("bid_ratio", e.target.value)} /></label>
    <label>单位费用 / 元/MWh<input type="number" min={0} step={.1} value={p.fee_yuan_mwh} onChange={(e) => numeric("fee_yuan_mwh", e.target.value)} /></label>
    <label>每小时申报上限 / MWh<input type="number" min={0} step={1} value={p.max_bid_mwh ?? ""} placeholder="不额外限制" onChange={(e) => numeric("max_bid_mwh", e.target.value)} /></label>
    {p.mode === "spread_rule" && <>
      <label>价差触发阈值 / 元/MWh<input type="number" step={1} value={p.spread_threshold} onChange={(e) => numeric("spread_threshold", e.target.value)} /></label>
      <label>每次系数调整<input type="number" min={0} max={1.5} step={.05} value={p.ratio_step} onChange={(e) => numeric("ratio_step", e.target.value)} /></label>
      <label>最低申报系数<input type="number" min={0} max={1.5} step={.05} value={p.min_ratio} onChange={(e) => numeric("min_ratio", e.target.value)} /></label>
      <label>最高申报系数<input type="number" min={0} max={1.5} step={.05} value={p.max_ratio} onChange={(e) => numeric("max_ratio", e.target.value)} /></label>
    </>}
    {prices.map((field) => <label key={field.key}>{field.name}<select value={priceRecords[field.key] || ""} onChange={(e) => setPriceRecords({ ...priceRecords, [field.key]: e.target.value })}><option value="">暂不绑定</option>{compatible.filter((r) => r.task === field.task).map((r) => <option key={r.id} value={r.record_id}>{businessText(r.name)}</option>)}</select>{bound && !compatible.some((r) => r.task === field.task) && <small className="research-help">缺少与所选光伏预测同来源版本、同决策时点、同输入条件的保存预测。</small>}</label>)}
    <p className="research-help business-form-wide">价格预测最多绑定两类，用于形成预计净额；实际价格只在实绩结算时使用。所有参数随方案版本保存，已有方案不会被覆盖。</p>
  </div>;
}
