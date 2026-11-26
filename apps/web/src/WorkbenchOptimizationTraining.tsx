import { useState } from "react";
import { stamp, useResource } from "./api";
import { Panel, Status } from "./components";
import { businessText } from "./presentation";

type Report = { id: string; name: string; created_at: string; candidate_eligible?: boolean; blocked_reason?: string; input_notice: string };
export default function OptimizationTraining({ task, revision, canSubmit, submit, monitor }: {
  task: string;
  revision: number;
  canSubmit: boolean;
  submit: (parameters: Record<string, unknown>) => void;
  monitor: () => void;
}) {
  const reports = useResource<{ reports: Report[] }>("/api/v1/optimization/summary?" + new URLSearchParams({ task_id: task }), revision, 10000);
  const [chosen, setChosen] = useState("");
  const report = reports.data?.reports.find((r) => r.id === chosen)
    || reports.data?.reports.find((r) => r.candidate_eligible)
    || reports.data?.reports[0];
  return <Panel title="将优化方案训练为可运行候选" subtitle="复用已验证方案的训练流程，重新训练并保存独立模型；历史验证报告不会直接变成当前运行模型。">
    <Status loading={reports.loading} error={reports.error} />
    {!reports.loading && !reports.error && !report && <p className="research-empty">当前任务尚无已完成的优化方案；仍可使用上方线性模型训练。</p>}
    {report && <>
      <div className="research-filters"><label>候选训练方案<select aria-label="候选训练方案" value={report.id} onChange={(e) => setChosen(e.target.value)}>{reports.data?.reports.map((r) => <option key={r.id} value={r.id}>{businessText(r.name)} · {stamp(r.created_at)}</option>)}</select></label></div>
      <p>{businessText(report.input_notice)}</p>
      <p className="research-help">{report.candidate_eligible ? "使用上方填写的操作人与训练依据提交。任务排队完成后，在模型列表选择新候选生成独立预测，再继续复核与同口径比较。" : businessText(report.blocked_reason || "该方案尚未具备可运行候选资格，暂不能提交训练。")}</p>
      <div className="research-filters">
        <button className="primary-button" disabled={!canSubmit || !report.candidate_eligible || reports.refreshing} onClick={() => submit({ optimization_result_id: report.id, alpha: 1, key: crypto.randomUUID() })}>提交优化候选训练</button>
        <button onClick={monitor}>查看训练实际进展</button>
      </div>
      <p className="research-help">只提交真实后台训练作业。完成后仍是研究候选，不自动替换研究主版本，也不重新开启已经使用过的最终评估窗口。</p>
    </>}
  </Panel>;
}
