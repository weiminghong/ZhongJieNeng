import { useResource } from "./api";
import { Panel, Status } from "./components";
import { businessText } from "./presentation";
import type { Selection } from "./workspaceState";

type Readiness = {
  prediction_inputs: { can_predict: boolean; summary: string; notice: string; feature_rows: number; imputed_feature_rows: number };
  observations: { summary: string; actual_periods: number; expected_periods: number; unit: string };
  settlement: { can_settle: boolean; summary: string; notice: string; usable_hours: number; expected_hours: number };
  source_details: { name: string; valid: number; expected: number; unit: string }[];
  notice: string;
};
export default function DataReadiness({ selection: s, revision }: { selection: Selection; revision: string }) {
  const params = new URLSearchParams({ source_key: s.source, task_id: s.task, trading_date: s.date, mode: s.mode, until: s.until, basis: s.basis });
  if (s.model) params.set("model_id", s.model);
  if (s.record) params.set("record_id", s.record);
  const r = useResource<Readiness>("/api/v1/workspace/data-readiness?" + params, revision, 10000);
  const d = r.data;
  return <Panel title="按业务用途检查数据" subtitle="能否预测、能否评价、能否结算分别核对，实际值未齐不等于模型不能预测。">
    <Status loading={r.loading} error={r.error} />
    {d && <>
      <div className="business-readiness-grid">
        <section><h3>预测输入 · {d.prediction_inputs.can_predict ? "可运行" : "待补齐"}</h3><p>{businessText(d.prediction_inputs.summary)}</p><p className="research-help">{d.prediction_inputs.feature_rows} 个输入时段，其中 {d.prediction_inputs.imputed_feature_rows} 个使用训练期填补规则。</p></section>
        <section><h3>实际值评价 · {d.observations.actual_periods}/{d.observations.expected_periods} {d.observations.unit}</h3><p>{businessText(d.observations.summary)}</p></section>
        <section><h3>实绩结算 · {d.settlement.can_settle ? "有可结算小时" : "待补数据或预测"}</h3><p>{businessText(d.settlement.summary)}</p><p className="research-help">可用 {d.settlement.usable_hours}/{d.settlement.expected_hours} 小时。</p></section>
      </div>
      <dl className="unified-source-facts">{d.source_details.map((item) => <div key={item.name}><dt>{item.name}</dt><dd>{item.valid}/{item.expected} {item.unit}</dd></div>)}</dl>
      <p className="research-help">{businessText(d.prediction_inputs.notice)}</p><p className="research-help">{businessText(d.notice)} {businessText(d.settlement.notice)}</p>
    </>}
  </Panel>;
}
