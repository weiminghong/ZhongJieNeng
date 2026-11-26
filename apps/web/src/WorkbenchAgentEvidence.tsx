import { useState } from "react";
import { useResource, stamp, fmt, time } from "./api";
import { Panel, Status } from "./components";
import { businessText, toolLabel } from "./presentation";
import type { Selection } from "./workspaceState";

export type Citation = { id: string; title: string; text: string; kind: string; created_at: string; date?: string; source_name?: string; task_name?: string; actor?: string };
export type AnalysisTool = { name: string; display_name?: string; summary?: string; input?: unknown; output?: unknown };
type KnowledgeCase = { id: string; created_at: string; reason: string; model_name: string; source_name: string; task_name: string; date: string; start: string; actor: string; actual: number; predicted: number; unit: string; notice: string };
export default function AgentEvidence({ selection: s, revision, citations, tools, notice, showAnalysis }: {
  selection: Selection;
  revision: string;
  citations: Citation[];
  tools: AnalysisTool[];
  notice: string;
  showAnalysis: boolean;
}) {
  const params = new URLSearchParams({ source_key: s.source, task_id: s.task, trading_date: s.date, mode: s.mode, until: s.until, basis: s.basis });
  if (s.model) params.set("model_id", s.model);
  if (s.record) params.set("record_id", s.record);
  const knowledge = useResource<{ records: KnowledgeCase[]; notice: string }>("/api/v1/workspace/knowledge?" + params, revision, 10000);
  const [page, setPage] = useState(0);
  const cases = knowledge.data?.records || [];
  const visiblePage = Math.min(page, Math.max(0, Math.ceil(cases.length / 8) - 1));
  return <>
    {showAnalysis && <Panel title="本次分析的工具与引用" subtitle="引用保留业务来源和日期，供人工逐条核对。">
      {!!tools.length && <div className="unified-analysis-tools">{tools.map((t, i) => <article key={i}><h3>{businessText(t.display_name || toolLabel(t.name))}</h3><p>{businessText(t.summary || (typeof t.output === "string" ? t.output : "计算依据见本次分析与引用。"))}</p></article>)}</div>}
      <p className="research-help">{businessText(notice)}</p>
      {citations.length ? citations.map((x) => <article className="unified-review-history" key={x.id}>
        <h3>{businessText(x.title)}</h3>
        <p>{businessText(x.text)}</p>
        <small>{businessText([x.source_name, x.task_name, x.date, x.actor].filter(Boolean).join(" · "))}{x.created_at ? " · " + stamp(x.created_at) : ""}</small>
      </article>) : <p className="research-empty">本次分析没有返回可列出的案例引用；请以当前数据事实核对。</p>}
    </Panel>}
    <Panel title="当前范围的业务案例" subtitle="由已确认的人工复核沉淀；旧案例仅供参考，不能替代本次实际值核对。">
      <Status loading={knowledge.loading} error={knowledge.error} />
      {knowledge.data && <p className="research-help">{businessText(knowledge.data.notice)}</p>}
      {!knowledge.loading && !knowledge.error && !knowledge.data?.records.length && <p className="research-empty">当前来源与任务尚无可检索业务案例。完成复核确认后，可在这里继续使用。</p>}
      {cases.slice(visiblePage * 8, (visiblePage + 1) * 8).map((x) => <article className="unified-review-history" key={x.id}>
        <h3>{x.date} {time(x.start)} · {businessText(x.model_name)}</h3>
        <p>预测 {fmt(x.predicted, 3)} / 实际 {fmt(x.actual, 3)} {x.unit}</p>
        <p>{businessText(x.reason)}</p>
        <small>{businessText([x.source_name, x.task_name, x.date, x.actor].filter(Boolean).join(" · "))}{x.created_at ? " · " + stamp(x.created_at) : ""}</small>
      </article>)}
      {cases.length > 8 && <div className="research-filters"><button disabled={!visiblePage} onClick={() => setPage(visiblePage - 1)}>上一页</button><span>第 {visiblePage + 1} 页 · {cases.length} 条案例</span><button disabled={(visiblePage + 1) * 8 >= cases.length} onClick={() => setPage(visiblePage + 1)}>下一页</button></div>}
    </Panel>
  </>;
}
