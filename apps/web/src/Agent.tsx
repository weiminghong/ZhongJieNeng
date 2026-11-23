import { useEffect, useState } from "react";
import {
  Send,
  FileCheck2,
  Sparkles,
  Wrench,
  BookOpen,
  History,
  Settings2,
} from "lucide-react";
import type { Scope, AgentAnswer } from "./types";
import { request, useResource, time } from "./api";
import { Status, Segments } from "./components";

export default function Agent({
  scope,
  llmMode,
  onDraft,
}: {
  scope: Scope;
  llmMode: string;
  onDraft: (draft: string) => void;
}) {
  const [view, setView] = useState("query");
  const [question, setQuestion] = useState(
    "请分析当前预测偏差，比较申报方案，并给出可追溯的规则依据。",
  );
  const [answer, setAnswer] = useState<AgentAnswer | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [revision, setRevision] = useState(0);
  const history = useResource<{ history: AgentAnswer[] }>(
    "/api/v1/agent/history?station_id=" +
      encodeURIComponent(scope.station_id) +
      "&source_mode=" +
      scope.source_mode,
    revision,
  );
  useEffect(() => {
    setAnswer(null);
    setError("");
  }, [
    scope.station_id,
    scope.date,
    scope.mode,
    scope.cutoff_at,
    scope.selected_interval,
  ]);
  async function send() {
    setBusy(true);
    setError("");
    try {
      const data = await request<AgentAnswer>("/api/v1/agent/query", {
        ...scope,
        question,
      });
      setAnswer(data);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
      setRevision((v) => v + 1);
    }
  }
  const shown = answer;
  return (
    <div className="agent-workspace">
      <div className="agent-intro">
        <div className="agent-mark">
          <Sparkles size={22} />
        </div>
        <div>
          <h2>双通道 Agent 副驾驶</h2>
          <p>结构化数据走 SQL 与确定性计算，业务知识走 FTS5 + TF-IDF 检索。</p>
        </div>
        <a className="button" href="/settings">
          <Settings2 size={15} />
          模型配置
        </a>
      </div>
      <div className="agent-context">
        <span className="badge info">{scope.station_id}</span>
        <span>{scope.date}</span>
        <span>
          {scope.mode === "replay"
            ? "时点回放"
            : scope.mode === "live"
              ? "日内实时"
              : "事后复盘"}
        </span>
        {scope.selected_interval && (
          <span className="badge warning">
            异常焦点 {time(scope.selected_interval)}
          </span>
        )}
      </div>
      <div className="notice small">
        <BookOpen size={16} />
        <p>
          {llmMode === "deterministic_tools_only"
            ? "未接外部大模型 · deterministic_tools_only。由真实工具与知识证据组装结论。"
            : "已配置 OpenAI 兼容摘要器，输出仅允许选择既有证据，禁止自由生成数值。"}
        </p>
      </div>
      <div className="presentation-metrics agent-metrics">
        <div>
          <span>运行模式</span>
          <strong>
            {llmMode === "deterministic_tools_only" ? "确定性工具" : "证据摘要"}
          </strong>
          <small>{llmMode}</small>
        </div>
        <div>
          <span>本次工具调用</span>
          <strong>{shown?.tool_calls.length ?? "—"}</strong>
          <small>SQL 计算与知识检索</small>
        </div>
        <div>
          <span>本次证据引用</span>
          <strong>{shown?.citations.length ?? "—"}</strong>
          <small>随结论提供可追溯入口</small>
        </div>
        <div>
          <span>持久化问答</span>
          <strong>{history.data?.history.length ?? "—"}</strong>
          <small>当前场站与数据口径</small>
        </div>
      </div>
      <Segments
        label="Agent 工作区"
        value={view}
        onChange={setView}
        options={[
          ["query", "业务分析"],
          ["history", "问答记录"],
        ]}
      />
      {view === "query" && (
        <>
          <form
            onSubmit={(e) => {
              e.preventDefault();
              void send();
            }}
            className="question-form"
          >
            <label htmlFor="agent-question">当前业务问题</label>
            <textarea
              id="agent-question"
              value={question}
              onChange={(e) => setQuestion(e.target.value)}
              maxLength={2000}
              rows={3}
              required
              disabled={busy}
            />
            <div className="question-actions">
              <span className="muted">
                自动携带当前场站、日期、模式与选中时段
              </span>
              <button
                className="primary-button"
                disabled={busy || !question.trim()}
              >
                <Send size={15} />
                {busy ? "正在检索与计算…" : "查询证据"}
              </button>
            </div>
          </form>
          {error && (
            <div className="inline-error" role="alert">
              {error}
            </div>
          )}
          {busy && <Status loading />}
          {shown && (
            <article className="agent-answer">
              <header>
                <strong>有据结论</strong>
                <span
                  className={`badge ${shown.grounded_check_passed ? "success" : "error"}`}
                >
                  {shown.grounded_check_passed
                    ? "证据约束通过"
                    : "证据检查失败"}
                </span>
              </header>
              <p className="answer-text">{shown.answer_markdown}</p>
              <div className="citation-list">
                {shown.citations.map((c) => (
                  <a
                    key={c.citation_id}
                    href={"#tool-" + (c.tool_name || "search_knowledge_rag")}
                    className="badge"
                    title={c.title || c.tool_name}
                  >
                    {c.kind === "rag" ? (
                      <BookOpen size={12} />
                    ) : (
                      <Wrench size={12} />
                    )}
                    {c.title || c.tool_name}
                  </a>
                ))}
              </div>
              <div className="tool-chain">
                <h3>可折叠执行证据</h3>
                {shown.tool_calls.map((c, i) => (
                  <details key={i} id={"tool-" + c.tool_name}>
                    <summary>
                      {c.tool_name === "search_knowledge_rag" ? (
                        <BookOpen size={15} />
                      ) : (
                        <Wrench size={15} />
                      )}
                      <span>
                        通道{" "}
                        {c.tool_name === "search_knowledge_rag"
                          ? "2 · RAG 混合召回"
                          : "1 · 数据库 / 确定性引擎"}
                      </span>
                      <strong>{c.tool_name}</strong>
                    </summary>
                    <div className="tool-input">
                      输入上下文<pre>{JSON.stringify(c.input, null, 2)}</pre>
                    </div>
                    <pre>{JSON.stringify(c.output, null, 2)}</pre>
                  </details>
                ))}
              </div>
              <footer>
                <span className="muted">
                  {shown.llm_mode} · {Math.round(shown.latency_ms)} ms · 已落库
                </span>
                <button onClick={() => onDraft(shown.answer_markdown)}>
                  <FileCheck2 size={15} />
                  送入 RSI 审核草稿
                </button>
              </footer>
            </article>
          )}
        </>
      )}
      {view === "history" && (
        <section className="agent-history">
          <h3>
            <History size={16} />
            持久化问答记录
          </h3>
          <Status
            loading={history.loading}
            error={history.error}
            empty={!!history.data && !history.data.history.length}
          />
          {history.data?.history.map((h) => (
            <button
              className="history-item"
              key={h.response_id}
              onClick={() => {
                setAnswer(h);
                setView("query");
              }}
            >
              <span>{h.question}</span>
              <small>{h.llm_mode}</small>
            </button>
          ))}
        </section>
      )}
    </div>
  );
}
