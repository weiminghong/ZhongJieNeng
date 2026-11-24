import { useEffect, useRef, useState } from "react";
import {
  ChevronLeft,
  ChevronRight,
  FileSearch,
  Sparkles,
  Send,
  CloudSun,
  Link2,
} from "lucide-react";
import type { Scope, Overview, AgentAnswer } from "./types";
import { fmt, time, request } from "./api";
import { Panel, Status } from "./components";

export default function ContextRail({
  scope,
  data,
  loading,
  error,
  llmMode,
  onSelect,
  onRaw,
  onDraft,
  onFullAgent,
}: {
  scope: Scope;
  data: Overview | null;
  loading: boolean;
  error: string;
  llmMode: string;
  onSelect: (value: string) => void;
  onRaw: () => void;
  onDraft: (value: string) => void;
  onFullAgent: () => void;
}) {
  const intervals = data?.intervals || [];
  const selected =
    intervals.find((r) => r.interval_start === scope.selected_interval) ||
    intervals.find((r) => time(r.interval_start) === "12:30") ||
    intervals[0];
  const index = selected ? intervals.indexOf(selected) : -1;
  useEffect(() => {
    if (selected && !scope.selected_interval) onSelect(selected.interval_start);
  }, [selected, scope.selected_interval, onSelect]);
  const [question, setQuestion] = useState("");
  const [answer, setAnswer] = useState<AgentAnswer | null>(null);
  const [busy, setBusy] = useState(false);
  const [failure, setFailure] = useState("");
  const context = JSON.stringify({
    ...scope,
    selected_interval: selected?.interval_start,
  });
  const activeContext = useRef(context);
  activeContext.current = context;
  useEffect(() => {
    setAnswer(null);
    setFailure("");
  }, [context]);
  async function analyze(prompt: string) {
    if (!selected || busy) return;
    const captured = context;
    onSelect(selected.interval_start);
    setBusy(true);
    setFailure("");
    setAnswer(null);
    try {
      const value = await request<AgentAnswer>("/api/v1/agent/query", {
        ...scope,
        selected_interval: selected.interval_start,
        question: prompt,
      });
      if (captured === activeContext.current) setAnswer(value);
    } catch (e) {
      if (captured === activeContext.current) setFailure((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  const refs: { table: string; record_id: string; available_at: string }[] =
    selected ? JSON.parse(selected.lineage_refs_json) : [];
  return (
    <aside className="context-rail" aria-label="时段详情与智能体">
      <Panel
        title="时段详情"
        action={
          <div className="interval-steppers">
            <button
              aria-label="上一个时段"
              disabled={index <= 0}
              onClick={() => onSelect(intervals[index - 1].interval_start)}
            >
              <ChevronLeft size={16} />
            </button>
            <button
              aria-label="下一个时段"
              disabled={index < 0 || index >= intervals.length - 1}
              onClick={() => onSelect(intervals[index + 1].interval_start)}
            >
              <ChevronRight size={16} />
            </button>
          </div>
        }
      >
        <Status loading={loading} error={error} />
        {selected && !loading && !error && (
          <>
            <label className="interval-picker">
              北京时间
              <select
                aria-label="选中分析时段"
                value={selected.interval_start}
                onChange={(e) => onSelect(e.target.value)}
              >
                {intervals.map((r) => (
                  <option key={r.interval_start} value={r.interval_start}>
                    {time(r.interval_start)}–{time(r.interval_end)}
                  </option>
                ))}
              </select>
            </label>
            <dl className="interval-facts">
              <div>
                <dt>
                  <span className="line-key measured" />
                  实测功率
                </dt>
                <dd>
                  {fmt(selected.actual_mw)} <small>MW</small>
                </dd>
              </div>
              <div>
                <dt>
                  <span className="line-key forecast" />
                  日前预测
                </dt>
                <dd>
                  {fmt(selected.da_forecast_mw)} <small>MW</small>
                </dd>
              </div>
              <div>
                <dt>
                  <span className="line-key intraday" />
                  日内修正
                </dt>
                <dd>
                  {fmt(selected.id_corrected_mw)} <small>MW</small>
                </dd>
              </div>
              <div>
                <dt>实测 − 预测</dt>
                <dd>
                  {fmt(
                    selected.actual_mw !== null &&
                      selected.da_forecast_mw !== null
                      ? selected.actual_mw - selected.da_forecast_mw
                      : null,
                  )}{" "}
                  <small>MW</small>
                </dd>
              </div>
              <div>
                <dt>日前 / 实时电价</dt>
                <dd>
                  {fmt(selected.da_price, 1)} / {fmt(selected.rt_price, 1)}
                  <small> 元/MWh</small>
                </dd>
              </div>
              <div>
                <dt>价差 RT−DA</dt>
                <dd>
                  {fmt(selected.spread_yuan_mwh)} <small>元/MWh</small>
                </dd>
              </div>
            </dl>
            <div className="interval-weather">
              <CloudSun size={20} />
              <span>
                辐照 <strong>{fmt(selected.ghi_wm2, 1)}</strong> W/m²
                <br />
                云量 {fmt(selected.cloud_cover_pct, 0)}% · 气温{" "}
                {fmt(selected.air_temp_c, 1)}°C
              </span>
            </div>
          </>
        )}
      </Panel>
      <Panel title="数据与证据" action={<FileSearch size={17} />}>
        <div className="evidence-summary">
          <p>
            <Link2 size={15} />
            {refs.length} 条关联来源 <span className="badge info">可追溯</span>
          </p>
          <p>
            实测状态{" "}
            <strong>
              {!selected
                ? "未读取"
                : selected.actual_mw !== null
                  ? "已到达"
                  : selected.quality_flag === "missing"
                    ? "应到缺测"
                    : "待到达"}
            </strong>
          </p>
          <p>
            区间口径{" "}
            <span>
              {scope.source_mode === "synthetic"
                ? "演示区间 · 未校准"
                : "以模型校准记录为准"}
            </span>
          </p>
        </div>
        <div className="rail-actions">
          <button
            disabled={!selected}
            onClick={() => {
              onSelect(selected!.interval_start);
              onRaw();
            }}
          >
            原始证据
          </button>
          <button
            className="primary-button"
            disabled={!selected || busy}
            onClick={() =>
              void analyze(
                `请分析 ${time(selected!.interval_start)}—${time(selected!.interval_end)} 的光伏预测偏差，核对辐照、云量和电价证据，区分关联线索与已确认原因。`,
              )
            }
          >
            <Sparkles size={14} />
            {busy ? "分析中…" : "分析此时段"}
          </button>
        </div>
      </Panel>
      <Panel title="智能体助手" action={<Sparkles size={17} />}>
        <p className="rail-mode">
          {llmMode === "deterministic_tools_only"
            ? "确定性工具模式"
            : "外部证据摘要器已配置"}{" "}
          · 同一分析范围
        </p>
        <form
          className="rail-question"
          onSubmit={(e) => {
            e.preventDefault();
            if (question.trim()) void analyze(question.trim());
          }}
        >
          <label className="visually-hidden" htmlFor="rail-question">
            向智能体提问
          </label>
          <textarea
            id="rail-question"
            value={question}
            onChange={(e) => setQuestion(e.target.value)}
            placeholder="询问此时段的偏差、天气或收益…"
            rows={3}
            maxLength={4000}
          />
          <button
            className="primary-button"
            aria-label="发送问题"
            disabled={busy || !selected || !question.trim()}
          >
            <Send size={16} />
          </button>
        </form>
        {failure && (
          <p role="alert" className="inline-error">
            {failure}
          </p>
        )}
        {answer && (
          <div className="rail-answer" aria-live="polite">
            <p>{answer.answer_markdown}</p>
            <small>
              {answer.citations.length} 条引用 · {answer.tool_calls.length}{" "}
              次工具调用 · {answer.llm_mode}
            </small>
            <details>
              <summary>查看工具与证据</summary>
              <pre>
                {JSON.stringify(
                  {
                    citations: answer.citations,
                    tool_calls: answer.tool_calls,
                  },
                  null,
                  2,
                )}
              </pre>
            </details>
            <button onClick={() => onDraft(answer.answer_markdown)}>
              转为人工复核草稿
            </button>
          </div>
        )}
        <button className="rail-full-agent" onClick={onFullAgent}>
          打开完整分析与历史
          <ChevronRight size={14} />
        </button>
      </Panel>
    </aside>
  );
}
