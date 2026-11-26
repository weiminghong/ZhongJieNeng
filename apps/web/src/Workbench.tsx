import { useEffect, useReducer, useRef, useState } from "react";
import {
  Activity,
  ArrowRight,
  ClipboardCheck,
  Database,
  GitCompare,
  LayoutDashboard,
  Radio,
  RefreshCw,
  Settings2,
  Sun,
  ChartNoAxesCombined,
  Sparkles,
  BrainCircuit,
  Layers3,
} from "lucide-react";
import { fmt, request, stamp, time, useResource } from "./api";
import { Panel, Status } from "./components";
import Chart, { baseOption } from "./Chart";
import {
  businessText,
  sourceLabel,
  stateLabel,
  analysisLabel,
} from "./presentation";
import {
  readSelection,
  selectionChange,
  selectionUrl,
  type Selection,
} from "./workspaceState";
import type { Theme } from "./types";
import "./styles/research.css";
import "./styles/settings.css";
import "./styles/unified.css";
import ModelSettings from "./ModelSettings";
import PredictionDetails from "./WorkbenchPredictionDetails";
import ReviewHistory from "./WorkbenchReviewHistory";
import OptimizationEvidence from "./OptimizationEvidence";
import DataOverview, { type SourceMetadata } from "./WorkbenchDataOverview";
import IntervalDetails from "./WorkbenchIntervalDetails";
import AgentEvidence, { type Citation, type AnalysisTool } from "./WorkbenchAgentEvidence";
import OptimizationTraining from "./WorkbenchOptimizationTraining";

type Source = {
  key: string;
  name: string;
  domain: string;
  source_mode: string;
  task: string;
  task_name: string;
  unit: string;
  dates: string[];
  available: boolean;
  notice: string;
  can_train: boolean;
  target_points?: number;
  tasks?: {
    id: string;
    name: string;
    unit: string;
    points: number;
    intraday: boolean;
  }[];
};
type Model = {
  alpha: number | null;
  id: string;
  name: string;
  state: string;
  trained: boolean;
  can_predict: boolean;
  can_approve: boolean;
  can_rollback: boolean;
  can_final_audit?: boolean;
  can_guard_power?: boolean;
  retrain_parameter_kind?: "regularization" | "optimization_recipe";
  created_at: string | null;
  scope_label: string;
  score: Score | null;
};
type Score = {
  direction_accuracy?: number;
  balanced_direction_accuracy?: number;
  positive_output?: { n: number; mae: number | null };
  n: number;
  mae: number | null;
  rmse: number | null;
  mbe: number | null;
};
type Point = {
  slot: number;
  start: string;
  actual: number | null;
  predicted: number | null;
  da_price: number | null;
  rt_price: number | null;
  pv_actual: number | null;
  quality: string;
};
type Case = {
  id: string;
  slot: number;
  start: string;
  actual: number;
  predicted: number;
  error: number;
  state: string;
  reason: string;
  feedback_id: string | null;
  observation_id: string | null;
};
type Job = {
  id: string;
  display_name: string;
  state: string;
  created_at: string;
  detail: { stage?: string; error?: string; measured_seconds?: number };
};
type Context = {
  context_version: string;
  source: Source;
  date: string;
  model_id: string | null;
  record_id: string | null;
  models: Model[];
  records: {
    id: string;
    name: string;
    model_id: string;
    date: string;
    created_at: string;
  }[];
  points: Point[];
  metrics: Score;
  cases: Case[];
  jobs: Job[];
  comparison: { id: string; name: string; score: Score; n: number }[];
  comparison_notice?: string;
  activity: {
    subject_id: string;
    display_name?: string;
    state: string;
    created_at: string;
    detail: { reason?: string; stage?: string; error?: string };
  }[];
  flow: { name: string; state: string; detail: string }[];
  metadata?: SourceMetadata;
  related?: {
    name: string;
    date: string;
    model: string;
    record: string;
    slot: number;
    tab: string;
  }[];
  checked_at: string;
  capabilities?: {
    train: boolean;
    predict: boolean;
    formal_production: boolean;
    snapshot_actual: boolean;
    analysis_mode: string;
  };
};
const nav = [
  { id: "overview", name: "总览", icon: LayoutDashboard },
  { id: "raw", name: "数据管理", icon: Database },
  { id: "learning", name: "训练与模型", icon: BrainCircuit },
  { id: "forecast", name: "预测分析", icon: Activity },
  { id: "compare", name: "评估对比", icon: GitCompare },
  { id: "analytics", name: "历史分析", icon: Layers3 },
  { id: "rsi", name: "复核审批", icon: ClipboardCheck },
  { id: "monitor", name: "运行监测", icon: Radio },
  { id: "flow", name: "数据链路", icon: Layers3 },
  { id: "trading", name: "交易测算", icon: ChartNoAxesCombined },
  { id: "agent", name: "智能体分析", icon: Sparkles },
  { id: "settings", name: "服务设置", icon: Settings2 },
];
export default function Workbench() {
  const [s, change] = useReducer(selectionChange, undefined, () => {
    let saved: Partial<Selection> | undefined;
    try {
      saved =
        JSON.parse(
          sessionStorage.getItem("cecep-workbench-selection") || "null",
        ) || undefined;
    } catch {}
    const selection = readSelection(location.search, saved);
    if (location.pathname === "/settings") selection.tab = "settings";
    return selection;
  });
  const [revision, setRevision] = useState(0);
  const [theme, setTheme] = useState<Theme>(() =>
    localStorage.getItem("cecep-theme") === "high-contrast-light"
      ? "high-contrast-light"
      : "standard-light",
  );
  const catalog = useResource<{ sources: Source[] }>(
    "/api/v1/workspace/catalog",
    revision,
    30000,
  );
  const params = new URLSearchParams({
    source_key: s.source,
    task_id: s.task,
    mode: s.mode,
    until: s.until,
    basis: s.basis,
    window: s.window,
  });
  if (s.date) params.set("trading_date", s.date);
  if (s.model) params.set("model_id", s.model);
  if (s.record) params.set("record_id", s.record);
  const context = useResource<Context>(
    "/api/v1/workspace/context?" + params,
    revision,
    10000,
  );
  const c = context.data;
  const [actor, setActor] = useState(
    () => localStorage.getItem("cecep-research-actor") || "",
  );
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [drafts, setDrafts] = useState<Record<string, string>>({});
  const [alpha, setAlpha] = useState(1);
  const [retrainAlpha, setRetrainAlpha] = useState(10);
  const [casePage, setCasePage] = useState(0);
  const [confirmedKey, setConfirmedKey] = useState("");
  const [auditConfirmedKey, setAuditConfirmedKey] = useState("");
  const [question, setQuestion] = useState("");
  const [answer, setAnswer] = useState("");
  const [answerVersion, setAnswerVersion] = useState("");
  const [analysisEvidence, setAnalysisEvidence] = useState<{ citations: Citation[]; tools: AnalysisTool[]; notice: string }>({ citations: [], tools: [], notice: "" });
  const selectedCase =
    c?.cases.find((x) => x.slot === s.slot) ||
    (s.slot === null ? c?.cases[0] : undefined);
  const scopeKey = [
    s.task,
    s.source,
    s.task,
    s.date,
    s.model,
    s.record,
    s.mode,
    s.until,
    s.basis,
  ].join(":");
  const current = useRef(scopeKey);
  current.current = scopeKey;
  const currentSlot = useRef(s.slot);
  currentSlot.current = s.slot;
  const reasonKey =
    scopeKey +
    ":" +
    (s.tab === "rsi" && selectedCase
      ? selectedCase.id + ":" + c?.context_version
      : s.tab);
  const reason =
    drafts[reasonKey] !== undefined
      ? drafts[reasonKey]
      : s.tab === "rsi"
        ? businessText(selectedCase?.reason || "")
        : "";
  const approvalReason = drafts[scopeKey + ":approval"] || "";
  const hasConfirmed = confirmedKey === reasonKey + ":" + actor;
  useEffect(() => {
    history.replaceState(null, "", "/" + selectionUrl(s));
    sessionStorage.setItem("cecep-workbench-selection", JSON.stringify(s));
    setError("");
    setMessage("");
    setAnswer("");
  }, [
    s.source,
    s.date,
    s.tab,
    s.model,
    s.record,
    s.mode,
    s.until,
    s.slot,
    s.basis,
  ]);
  useEffect(() => setCasePage(0), [c?.context_version]);
  useEffect(() => {
    if (
      c &&
      c.source.key === s.source &&
      (c.source.task !== s.task ||
        c.date !== s.date ||
        (c.model_id || "") !== s.model ||
        (c.record_id || "") !== s.record)
    )
      change({
        type: "hydrate",
        task: c.source.task,
        date: c.date,
        model: c.model_id || "",
        record: c.record_id || "",
      });
  }, [c?.source.key, c?.source.task, c?.date, c?.model_id, c?.record_id]);
  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    localStorage.setItem("cecep-theme", theme);
  }, [theme]);
  const selectedModel = c?.models.find((m) => m.id === s.model);
  const usesOptimizationRecipe = selectedModel?.retrain_parameter_kind === "optimization_recipe" || (selectedModel?.trained === true && selectedModel.alpha === null && c?.source.domain === "market");
  const canGuardPower = selectedModel?.can_guard_power ?? (selectedModel?.trained === true && selectedModel.alpha !== null);
  const selectedRetrainAlpha =
    retrainAlpha === selectedModel?.alpha
      ? selectedModel?.alpha === 1
        ? 10
        : 1
      : retrainAlpha;
  const title =
    s.tab === "settings"
      ? "服务设置"
      : nav.find((n) => n.id === s.tab)?.name || "总览";
  async function act(
    action: string,
    extra: Record<string, unknown> = {},
    success = "操作已保存",
  ) {
    if (busy) return;
    if (!actor.trim()) {
      setError("请先填写操作人");
      return;
    }
    const note =
      (["approve", "rollback", "reject", "final_audit", "shadow"].includes(
        action,
      )
        ? approvalReason
        : reason
      ).trim() ||
      (action === "predict"
        ? "按当前来源、模型与日期运行预测"
        : action === "analyze"
          ? question.trim()
          : "");
    if (!note) {
      setError("请填写本次操作依据");
      return;
    }
    const captured = scopeKey;
    const capturedSlot = s.slot;
    setBusy(action);
    setError("");
    setMessage("");
    localStorage.setItem("cecep-research-actor", actor.trim());
    try {
      const r = await request<Record<string, unknown>>(
        "/api/v1/workspace/commands",
        {
          action,
          source_key: s.source,
          task_id: s.task,
          date: s.date,
          model_id: s.model || null,
          record_id: s.record || null,
          actor: actor.trim(),
          reason: note,
          mode: s.mode,
          until: s.until,
          basis: s.basis,
          context_version: c?.context_version || "",
          ...extra,
        },
      );
      if (current.current !== captured) return;
      if (action === "analyze" && currentSlot.current !== capturedSlot) return;
      if (action === "predict") {
        const id = String(r.id || "");
        if (id)
          change({ type: "record", record: id, model: s.model, date: s.date });
      }
      if (action === "guard_power" && r.id) {
        change({ type: "model", model: String(r.id) });
        change({ type: "tab", tab: "forecast" });
      }
      if (action === "analyze") {
        setAnalysisEvidence({
          citations: Array.isArray(r.citations) ? r.citations as Citation[] : [],
          tools: Array.isArray(r.tools) ? r.tools as AnalysisTool[] : [],
          notice: String(r.knowledge_notice || ""),
        });
        setAnswerVersion(String(r.context_version || c?.context_version || ""));
        setAnswer(
          businessText(
            r.answer_markdown ||
              (r.payload as Record<string, unknown> | undefined)?.answer ||
              "分析结果已保存",
          ),
        );
      }
      setRevision((v) => v + 1);
      setMessage(success);
    } catch (e) {
      if (current.current === captured)
        setError(businessText((e as Error).message));
    } finally {
      setBusy("");
    }
  }
  function note(label = "操作依据", approval = false) {
    const key = approval ? scopeKey + ":approval" : reasonKey;
    const text = approval ? approvalReason : reason;
    return (
      <div className="unified-action-form">
        <label>
          操作人
          <input
            value={actor}
            maxLength={100}
            onChange={(e) => setActor(e.target.value)}
            placeholder="填写姓名"
          />
        </label>
        <label>
          {label}
          <textarea
            rows={2}
            value={text}
            maxLength={4000}
            onChange={(e) =>
              setDrafts((v) => ({ ...v, [key]: e.target.value }))
            }
            placeholder="说明判断依据或本次操作目的"
          />
        </label>
      </div>
    );
  }

  const chart = (kind: "target" | "price" = "target") => (
    <Chart
      theme={theme}
      label={kind === "target" ? "当前范围预测与实际值" : "当前范围电价"}
      onPoint={(index) =>
        change({ type: "slot", slot: c?.points[index]?.slot ?? index })
      }
      option={() => ({
        ...baseOption(),
        xAxis: {
          ...baseOption().xAxis,
          data: c?.points.map((p) => time(p.start)) || [],
        },
        yAxis: {
          ...baseOption().yAxis,
          name: kind === "target" ? c?.source.unit : "元/MWh",
          scale: true,
        },
        series:
          kind === "target"
            ? [
                {
                  name: "模型预测",
                  type: "line",
                  symbol: "none",
                  data: c?.points.map((p) => p.predicted) || [],
                },
                {
                  name: "实际值",
                  type: "line",
                  symbol: "none",
                  lineStyle: { type: "dashed" },
                  data: c?.points.map((p) => p.actual) || [],
                },
              ]
            : [
                {
                  name: "日前电价",
                  type: "line",
                  symbol: "none",
                  data: c?.points.map((p) => p.da_price) || [],
                },
                {
                  name: "实时电价",
                  type: "line",
                  symbol: "none",
                  data: c?.points.map((p) => p.rt_price) || [],
                },
              ],
      })}
    />
  );
  const activity = (
    <div className="research-events">
      {c?.activity.length ? (
        c.activity.map((e, i) => (
          <div className="unified-event" key={i}>
            <strong>
              {stateLabel(e.state)} ·{" "}
              {businessText(e.display_name || "业务操作")}
            </strong>
            <p>
              {businessText(
                e.detail.reason ||
                  e.detail.stage ||
                  e.detail.error ||
                  "进展已记录",
              )}
            </p>
            <time>{stamp(e.created_at)}</time>
          </div>
        ))
      ) : (
        <p className="research-empty">当前数据范围暂无操作记录。</p>
      )}
    </div>
  );
  return (
    <div className="energy-shell research-shell unified-workbench">
      <aside className="energy-sidebar" aria-label="业务导航">
        <a
          className="energy-brand"
          href="?tab=overview"
          onClick={(e) => {
            e.preventDefault();
            change({ type: "tab", tab: "overview" });
          }}
        >
          <Sun size={26} />
          <strong>
            中节能<span>光伏交易工作台</span>
          </strong>
        </a>
        <nav>
          {nav.map((n) => (
            <button
              key={n.id}
              aria-current={s.tab === n.id ? "page" : undefined}
              className={s.tab === n.id ? "is-active" : ""}
              onClick={() => change({ type: "tab", tab: n.id })}
            >
              <n.icon size={19} />
              <span>
                <strong>{n.name}</strong>
              </span>
            </button>
          ))}
        </nav>
        <div className="energy-sidebar-bottom">
          <p>数据、预测与复核在同一范围接续</p>
        </div>
      </aside>
      <main className="energy-main">
        <header className="energy-heading">
          <div className="energy-page-title">
            <h1>{title}</h1>
            {c && s.tab !== "settings" && (
              <span
                className={`badge ${c.source.source_mode === "synthetic" ? "warning" : "info"}`}
              >
                {sourceLabel(c.source.source_mode)}
              </span>
            )}
          </div>
          <div className="energy-actions">
            <button onClick={() => setRevision((v) => v + 1)}>
              <RefreshCw size={16} />
              检查更新
            </button>
            <button
              onClick={() =>
                setTheme((v) =>
                  v === "standard-light"
                    ? "high-contrast-light"
                    : "standard-light",
                )
              }
            >
              {theme === "standard-light" ? "高对比" : "标准显示"}
            </button>
          </div>
        </header>
        {s.tab !== "settings" && (
          <div
            className="energy-filters unified-filters"
            aria-label="统一业务范围"
          >
            <label>
              <span>数据范围</span>
              <select
                aria-label="数据范围"
                value={s.source}
                onChange={(e) =>
                  change({ type: "source", source: e.target.value })
                }
              >
                {catalog.data?.sources.map((x) => (
                  <option key={x.key} value={x.key}>
                    {x.name}
                    {!x.available ? " · 暂无数据" : ""}
                  </option>
                ))}
              </select>
            </label>
            <label>
              <span>预测任务</span>
              <select
                aria-label="预测任务"
                value={s.task || c?.source.task || ""}
                onChange={(e) => change({ type: "task", task: e.target.value })}
              >
                <option value="">选择任务</option>
                {c?.source.tasks?.map((x) => (
                  <option key={x.id} value={x.id}>
                    {x.name}
                  </option>
                ))}
              </select>
            </label>
            <label>
              <span>日期</span>
              <select
                aria-label="交易日期"
                value={s.date}
                onChange={(e) => change({ type: "date", date: e.target.value })}
              >
                <option value="">选择日期</option>
                {(
                  c?.source ||
                  catalog.data?.sources.find((x) => x.key === s.source)
                )?.dates.map((d) => (
                  <option key={d}>{d}</option>
                ))}
              </select>
            </label>
            <label>
              <span>模型</span>
              <select
                aria-label="预测模型"
                value={s.model}
                onChange={(e) =>
                  change({ type: "model", model: e.target.value })
                }
              >
                <option value="">选择模型</option>
                {c?.models.map((m) => (
                  <option key={m.id} value={m.id}>
                    {businessText(m.name)}
                  </option>
                ))}
              </select>
            </label>
            <label>
              <span>查看方式</span>
              <select
                aria-label="查看方式"
                value={s.mode}
                onChange={(e) =>
                  change({
                    type: "view",
                    mode: e.target.value as Selection["mode"],
                    until: s.until,
                  })
                }
              >
                <option value="post">历史复盘</option>
                <option value="live">查看已到数据</option>
                <option value="replay">按时点查看</option>
              </select>
            </label>
            {s.mode === "replay" && (
              <label>
                <span>截至</span>
                <input
                  aria-label="查看截止时间"
                  type="time"
                  value={s.until}
                  onChange={(e) =>
                    e.target.value &&
                    change({
                      type: "view",
                      mode: s.mode,
                      until: e.target.value,
                    })
                  }
                />
              </label>
            )}
          </div>
        )}
        <div className="energy-scroll">
          {s.tab === "settings" ? (
            <ModelSettings />
          ) : (
            <>
              <Status
                loading={context.loading || catalog.loading}
                error={context.error || catalog.error}
              />
              {c && (
                <>
                  <p className="unified-scope-notice">
                    {c.source.notice}{" "}
                    <span>
                      当前任务：{c.source.task_name} · {c.source.unit}
                    </span>
                  </p>
                  {error && (
                    <p className="inline-error" role="alert">
                      {error}
                    </p>
                  )}
                  {message && (
                    <p className="inline-success" role="status">
                      {message}
                    </p>
                  )}
                  {busy && <p role="status">正在处理，请稍候…</p>}
                  {!c.source.available ? (
                    <Panel title="该范围尚无可用数据">
                      <p>
                        当前来源没有已接入记录。请选择其他范围，或在完成真实数据接入后继续。
                      </p>
                    </Panel>
                  ) : (
                    <>
                      {s.tab === "overview" && (
                        <>
                          <div className="research-metrics">
                            <div>
                              <span>所选日期有效实际值</span>
                              <strong>
                                {
                                  c.points.filter((p) => p.actual !== null)
                                    .length
                                }
                                <small>
                                  /{c.source.target_points || 96} 时段
                                </small>
                              </strong>
                            </div>
                            <div>
                              <span>配对平均绝对误差</span>
                              <strong>
                                {fmt(c.metrics.mae, 2)}
                                <small>{c.source.unit}</small>
                              </strong>
                              <p>{c.metrics.n} 个配对时段</p>
                            </div>
                            <div>
                              <span>所选模型</span>
                              <strong className="unified-model-title">
                                {businessText(
                                  selectedModel?.name || "尚未选择",
                                )}
                              </strong>
                              <p>
                                {selectedModel?.trained
                                  ? "真实训练记录"
                                  : "参考或历史拟合，未经生产验收"}
                              </p>
                            </div>
                            <div>
                              <span>当前日期复核</span>
                              <strong>
                                {c.cases.filter((x) => x.feedback_id).length}
                                <small>条</small>
                              </strong>
                            </div>
                          </div>
                          <div className="research-two-grid unified-overview">
                            <div>
                              <Panel
                                title="预测与实际值"
                                action={
                                  <button
                                    onClick={() =>
                                      change({ type: "tab", tab: "forecast" })
                                    }
                                  >
                                    预测分析
                                    <ArrowRight size={14} />
                                  </button>
                                }
                              >
                                {chart()}
                              </Panel>
                              <Panel title="同一范围的电价观察">
                                {chart("price")}
                              </Panel>
                              <div className="research-filters">
                                <button
                                  onClick={() =>
                                    change({ type: "tab", tab: "compare" })
                                  }
                                >
                                  查看同口径版本比较 <ArrowRight size={14} />
                                </button>
                                <button
                                  onClick={() =>
                                    change({ type: "tab", tab: "flow" })
                                  }
                                >
                                  核对数据链路 <ArrowRight size={14} />
                                </button>
                              </div>
                            </div>
                            <div className="unified-overview-evidence">
                            <IntervalDetails
                              points={c.points}
                              slot={s.slot}
                              unit={c.source.unit}
                              sourceName={c.source.name}
                              modelName={selectedModel?.name || ""}
                              recordName={c.records.find((r) => r.id === s.record)?.name || ""}
                              basis={s.basis}
                              select={(slot) => change({ type: "slot", slot })}
                              navigate={(tab) => change({ type: "tab", tab })}
                              analyze={(point) => {
                                setQuestion(`请分析 ${c.date} ${time(point.start)} 这一时段的${c.source.task_name}，说明预测与实际的差异、已有证据和需要人工核对的事项。`);
                                change({ type: "tab", tab: "agent" });
                              }}
                            />
                            <Panel title="业务进展">
                              {c.flow.map((x) => (
                                <div className="unified-flow-step" key={x.name}>
                                  <strong>{x.name}</strong>
                                  <span
                                    className={`badge ${["succeeded", "archived", "matched", "confirmed"].includes(x.state) ? "success" : "warning"}`}
                                  >
                                    {x.state === "pending"
                                      ? "待完成"
                                      : stateLabel(x.state)}
                                  </span>
                                  <p>{x.detail}</p>
                                </div>
                              ))}
                            </Panel>
                            </div>
                          </div>
                        </>
                      )}
                      {s.tab === "raw" && (
                        <>
                        <DataOverview
                          key={s.source + ":" + s.task}
                          source={c.source}
                          metadata={c.metadata}
                          points={c.points}
                          date={c.date}
                          model={s.model}
                          record={s.record}
                          basis={s.basis}
                          revision={`${revision}:${c.context_version}`}
                        />
                        <Panel
                          title="当前范围的分时数据"
                          subtitle="数据范围、日期和模型均使用上方同一选择。选择时段后可继续预测分析或复核。"
                        >
                          <DataTable
                            points={c.points}
                            unit={c.source.unit}
                            slot={s.slot}
                            choose={(slot) => change({ type: "slot", slot })}
                          />
                          <button
                            onClick={() => change({ type: "tab", tab: "rsi" })}
                          >
                            复核所选时段
                            <ArrowRight size={14} />
                          </button>
                        </Panel>
                        </>
                      )}
                      {s.tab === "forecast" && (
                        <>
                          <Panel title="运行与查看预测">
                            <div className="research-filters">
                              <label>
                                已保存预测
                                <select
                                  aria-label="预测记录"
                                  value={s.record}
                                  onChange={(e) => {
                                    const r = c.records.find(
                                      (r) => r.id === e.target.value,
                                    );
                                    if (r)
                                      change({
                                        type: "record",
                                        record: r.id,
                                        model: r.model_id,
                                        date: r.date,
                                      });
                                  }}
                                >
                                  <option value="">
                                    选择记录，或运行当前模型
                                  </option>
                                  {c.records.map((r) => (
                                    <option key={r.id} value={r.id}>
                                      {businessText(r.name)}
                                    </option>
                                  ))}
                                </select>
                              </label>
                              <label>
                                实际值来源
                                <select
                                  value={s.basis}
                                  onChange={(e) =>
                                    change({
                                      type: "basis",
                                      basis: e.target
                                        .value as Selection["basis"],
                                    })
                                  }
                                >
                                  <option value="latest">最新已核对观测</option>
                                  {c.capabilities?.snapshot_actual && (
                                    <option value="snapshot">
                                      预测保存快照
                                    </option>
                                  )}
                                </select>
                              </label>
                              <label>
                                操作人
                                <input
                                  value={actor}
                                  onChange={(e) => setActor(e.target.value)}
                                  placeholder="填写姓名"
                                />
                              </label>
                              <button
                                className="primary-button"
                                disabled={
                                  !!busy ||
                                  !selectedModel?.can_predict ||
                                  !actor.trim()
                                }
                                onClick={() =>
                                  void act(
                                    "predict",
                                    {},
                                    "当前范围的预测已保存",
                                  )
                                }
                              >
                                运行所选模型
                              </button>
                            </div>
                            {!selectedModel?.can_predict && (
                              <p className="research-help">
                                {businessText(
                                  selectedModel?.scope_label ||
                                    "当前任务尚无可运行模型，请先完成训练并选择版本。",
                                )}
                              </p>
                            )}
                          </Panel>
                          <Panel
                            title="预测与实际值"
                            subtitle={`${c.date} · ${businessText(selectedModel?.name || "未选模型")} · ${c.metrics.n} 个配对时段`}
                          >
                            {chart()}
                            <div className="research-filters">
                              <label>
                                选中时段
                                <select
                                  aria-label="选中时段"
                                  value={s.slot ?? ""}
                                  onChange={(e) =>
                                    change({
                                      type: "slot",
                                      slot: Number(e.target.value),
                                    })
                                  }
                                >
                                  <option value="">选择时段</option>
                                  {c.points.map((p) => (
                                    <option key={p.slot} value={p.slot}>
                                      {time(p.start)}
                                    </option>
                                  ))}
                                </select>
                              </label>
                              <button
                                onClick={() =>
                                  change({ type: "tab", tab: "raw" })
                                }
                              >
                                查看原始数据
                              </button>
                              <button
                                onClick={() =>
                                  change({ type: "tab", tab: "rsi" })
                                }
                              >
                                继续复核
                              </button>
                              {c.record_id && (
                                <a
                                  className="button"
                                  href={
                                    "/api/v1/workspace/export?" +
                                    new URLSearchParams({
                                      source_key: s.source,
                                      task_id: s.task,
                                      trading_date: s.date,
                                      model_id: s.model,
                                      record_id: s.record,
                                      mode: s.mode,
                                      until: s.until,
                                      basis: s.basis,
                                      expected_version: c.context_version,
                                    })
                                  }
                                >
                                  导出当前预测与实际值
                                </a>
                              )}
                            </div>
                          </Panel>
                          <Panel title="同一范围的电价观察">
                            {chart("price")}
                          </Panel>
                          {c.record_id && (
                            <PredictionDetails
                              source={s.source}
                              task={s.task}
                              date={s.date}
                              model={s.model}
                              record={s.record}
                              revision={revision}
                            />
                          )}
                        </>
                      )}
                      {s.tab === "learning" && (
                        <>
                          <Panel title="发起训练">
                            {note("训练依据")}
                            <div className="research-filters">
                              <label>
                                正则强度
                                <select
                                  value={alpha}
                                  onChange={(e) =>
                                    setAlpha(Number(e.target.value))
                                  }
                                >
                                  {[0.1, 1, 10, 100].map((v) => (
                                    <option key={v}>{v}</option>
                                  ))}
                                </select>
                              </label>
                              <button
                                className="primary-button"
                                disabled={
                                  !!busy ||
                                  !c.source.can_train ||
                                  !actor.trim() ||
                                  !reason.trim()
                                }
                                onClick={() =>
                                  void act(
                                    "train",
                                    { alpha, key: crypto.randomUUID() },
                                    "训练已提交，可在运行监测查看实际进展",
                                  )
                                }
                              >
                                提交当前范围训练
                              </button>
                            </div>
                            {!c.source.can_train && (
                              <p className="research-help">
                                当前数据范围没有已批准的正式训练协议。可以核对既有模型与预测记录，不使用其他来源的训练流程代替。
                              </p>
                            )}
                          </Panel>
                          {c.source.domain === "market" && <OptimizationTraining
                            key={s.task}
                            task={s.task}
                            revision={revision}
                            canSubmit={!busy && !!actor.trim() && !!reason.trim() && c.source.can_train}
                            submit={(parameters) => void act("train", parameters, "优化候选训练已提交，请在运行监测核对实际完成情况")}
                            monitor={() => change({ type: "tab", tab: "monitor" })}
                          />}
                          {c.source.task.startsWith("pv_") && (
                            <Panel
                              title="训练期出力约束修正"
                              subtitle="复用所选线性模型的真实权重，只用训练期分布估计输出边界；源标签保持不变，不记作新权重训练。"
                            >
                              {note("修正依据")}
                              <button
                                disabled={
                                  !!busy ||
                                  !canGuardPower ||
                                  !actor.trim() ||
                                  !reason.trim()
                                }
                                onClick={() =>
                                  void act(
                                    "guard_power",
                                    {},
                                    "约束修正版本已保存，请运行该版本生成新的预测记录",
                                  )
                                }
                              >
                                为所选版本建立出力约束
                              </button>
                              {selectedModel?.trained && !canGuardPower && <p className="research-help">所选模型不适用线性模型出力约束，请使用它自己的受控训练方案生成新版本。</p>}
                            </Panel>
                          )}
                          <Panel title="当前范围的模型">
                            <ModelTable
                              models={c.models}
                              select={(model) => {
                                change({ type: "model", model });
                                change({ type: "tab", tab: "forecast" });
                              }}
                            />
                          </Panel>
                        </>
                      )}
                      {s.tab === "compare" && (
                        <>
                          <Panel title="同口径评估">
                            <div className="research-filters">
                              {c.source.domain === "market" && (
                                <label>
                                  评估范围
                                  <select
                                    aria-label="评估范围"
                                    value={s.window}
                                    onChange={(e) =>
                                      change({
                                        type: "window",
                                        window: e.target
                                          .value as Selection["window"],
                                      })
                                    }
                                  >
                                    <option value="tune">调参窗口</option>
                                    <option value="promotion">
                                      提升评估窗口
                                    </option>
                                    <option value="final_audit">
                                      已完成的最终评估
                                    </option>
                                  </select>
                                </label>
                              )}
                            </div>
                            <p className="research-help">
                              {businessText(
                                c.comparison_notice || "尚无可比记录",
                              )}
                            </p>
                            <div className="table-wrap">
                              <table>
                                <thead>
                                  <tr>
                                    <th>模型或记录</th>
                                    <th>平均绝对误差</th>
                                    <th>均方根误差</th>
                                    <th>平均偏差</th>
                                    <th>共同样本</th>
                                    {c.source.task.includes("spread") && (
                                      <>
                                        <th>方向命中率</th>
                                        <th>各方向平均命中率</th>
                                      </>
                                    )}
                                    {c.source.task.startsWith("pv_") && (
                                      <th>正出力时段误差 / MW</th>
                                    )}
                                  </tr>
                                </thead>
                                <tbody>
                                  {c.comparison.map((r) => (
                                    <tr key={r.id}>
                                      <td>{businessText(r.name)}</td>
                                      <td>
                                        {fmt(r.score.mae, 3)} {c.source.unit}
                                      </td>
                                      <td>
                                        {fmt(r.score.rmse, 3)} {c.source.unit}
                                      </td>
                                      <td>
                                        {fmt(r.score.mbe, 3)} {c.source.unit}
                                      </td>
                                      <td>{r.n}</td>
                                      {c.source.task.includes("spread") && (
                                        <>
                                          <td>
                                            {r.score.direction_accuracy ===
                                            undefined
                                              ? "—"
                                              : fmt(
                                                  r.score.direction_accuracy *
                                                    100,
                                                  1,
                                                ) + "%"}
                                          </td>
                                          <td>
                                            {r.score
                                              .balanced_direction_accuracy ===
                                            undefined
                                              ? "—"
                                              : fmt(
                                                  r.score
                                                    .balanced_direction_accuracy *
                                                    100,
                                                  1,
                                                ) + "%"}
                                          </td>
                                        </>
                                      )}
                                      {c.source.task.startsWith("pv_") && (
                                        <td>
                                          {fmt(r.score.positive_output?.mae, 3)}{" "}
                                          · {r.score.positive_output?.n ?? 0}{" "}
                                          时段
                                        </td>
                                      )}
                                    </tr>
                                  ))}
                                </tbody>
                              </table>
                            </div>
                          </Panel>
                        </>
                      )}
                      {s.tab === "compare" && c.source.domain === "market" && (
                        <OptimizationEvidence
                          key={s.task}
                          task={s.task}
                          date={s.date}
                          revision={revision}
                          theme={theme}
                        />
                      )}
                      {s.tab === "analytics" && (
                        <HistoryAnalysis
                          selection={s}
                          revision={`${revision}:${c.context_version}`}
                          contextVersion={c.context_version}
                          theme={theme}
                        />
                      )}
                      {s.tab === "rsi" && (
                        <>
                          <div className="research-two-grid">
                            <Panel
                              title="选择需要复核的时段"
                              subtitle="偏差统一为预测减实际。没有实际值的时段不能保存复核。"
                            >
                              <div className="unified-case-list">
                                {c.cases
                                  .slice(casePage * 6, casePage * 6 + 6)
                                  .map((x) => (
                                    <button
                                      key={x.id}
                                      aria-pressed={selectedCase?.id === x.id}
                                      className={
                                        selectedCase?.id === x.id
                                          ? "is-selected"
                                          : ""
                                      }
                                      onClick={() =>
                                        change({ type: "slot", slot: x.slot })
                                      }
                                    >
                                      <strong>
                                        {time(x.start)} · {fmt(x.error, 2)}{" "}
                                        {c.source.unit}
                                      </strong>
                                      <span>
                                        {x.feedback_id
                                          ? "已保存复核"
                                          : "待复核"}
                                      </span>
                                    </button>
                                  ))}
                              </div>
                              <div className="research-filters">
                                <button
                                  disabled={!casePage}
                                  onClick={() => setCasePage((v) => v - 1)}
                                >
                                  上一页
                                </button>
                                <span>{c.cases.length} 个可核对时段</span>
                                <button
                                  disabled={
                                    (casePage + 1) * 6 >= c.cases.length
                                  }
                                  onClick={() => setCasePage((v) => v + 1)}
                                >
                                  下一页
                                </button>
                              </div>
                            </Panel>
                            <Panel title="填写复核意见">
                              {selectedCase ? (
                                <>
                                  <p>
                                    {c.date} {time(selectedCase.start)} · 预测{" "}
                                    {fmt(selectedCase.predicted, 3)} / 实际{" "}
                                    {fmt(selectedCase.actual, 3)}{" "}
                                    {c.source.unit}
                                  </p>
                                  {note("复核依据")}
                                  <label className="unified-confirm">
                                    <input
                                      type="checkbox"
                                      checked={hasConfirmed}
                                      onChange={(e) =>
                                        setConfirmedKey(
                                          e.target.checked
                                            ? reasonKey + ":" + actor
                                            : "",
                                        )
                                      }
                                    />
                                    已核对所选来源、日期、模型和时段的实际值
                                  </label>
                                  <button
                                    className="primary-button"
                                    disabled={
                                      !!busy ||
                                      !actor.trim() ||
                                      !reason.trim() ||
                                      !hasConfirmed
                                    }
                                    onClick={() =>
                                      void act(
                                        "feedback",
                                        {
                                          confirmed: true,
                                          case_id: selectedCase.id,
                                          slot: selectedCase.slot,
                                        },
                                        "复核意见已保存并绑定当前来源、日期和预测",
                                      )
                                    }
                                  >
                                    确认并保存复核
                                  </button>
                                  {selectedCase.feedback_id && selectedCase.state === "confirmed" && <div className="research-filters">
                                    <button
                                      disabled={!!busy || !hasConfirmed || !actor.trim() || !reason.trim()}
                                      onClick={() => void act("ingest_case", { confirmed: true, feedback_id: selectedCase.feedback_id, case_id: selectedCase.id, slot: selectedCase.slot }, "已将确认复核沉淀为当前来源与任务的业务案例")}
                                    >沉淀为业务案例</button>
                                    <p className="research-help">新确认意见会自动沉淀；已有意见可补充收录，需与当前观测一致。</p>
                                  </div>}
                                  {c.source.domain === "market" &&
                                    selectedCase.feedback_id && (
                                      <div className="research-filters">
                                        <button
                                          disabled={
                                            !!busy ||
                                            selectedCase.state !== "submitted"
                                          }
                                          onClick={() =>
                                            void act(
                                              "confirm",
                                              {
                                                feedback_id:
                                                  selectedCase.feedback_id,
                                              },
                                              "复核已确认",
                                            )
                                          }
                                        >
                                          确认复核
                                        </button>
                                        {usesOptimizationRecipe ? <p className="research-help">所选候选沿用已冻结的优化流程重训，不使用线性模型正则参数，也不会把意见改成新标签。</p> : <label>
                                          重训正则强度
                                          <select
                                            aria-label="重训正则强度"
                                            value={selectedRetrainAlpha}
                                            onChange={(e) =>
                                              setRetrainAlpha(
                                                Number(e.target.value),
                                              )
                                            }
                                          >
                                            {[0.1, 1, 10, 100]
                                              .filter(
                                                (v) =>
                                                  v !== selectedModel?.alpha,
                                              )
                                              .map((v) => (
                                                <option key={v} value={v}>
                                                  {v}
                                                </option>
                                              ))}
                                          </select>
                                        </label>}
                                        <button
                                          disabled={
                                            !!busy ||
                                            selectedCase.state !== "confirmed"
                                          }
                                          onClick={() =>
                                            void act(
                                              "proposal",
                                              {
                                                feedback_id:
                                                  selectedCase.feedback_id,
                                                alpha: usesOptimizationRecipe ? 1 : selectedRetrainAlpha,
                                                key: crypto.randomUUID(),
                                              },
                                              "已按复核提案提交重训",
                                            )
                                          }
                                        >
                                          提交受控重训
                                        </button>
                                      </div>
                                    )}
                                </>
                              ) : (
                                <p className="research-empty">
                                  请选择一个有实际值的时段。所选时段没有可复核记录时，不自动替换为其他时段。
                                </p>
                              )}
                            </Panel>
                          </div>
                          <ReviewHistory
                            key={
                              s.source +
                              ":" +
                              s.date +
                              ":" +
                              s.mode +
                              ":" +
                              s.until
                            }
                            source={s.source}
                            task={s.task}
                            date={s.date}
                            mode={s.mode}
                            until={s.until}
                            revision={revision}
                          />
                          <Panel
                            title="模型审批与回滚"
                            subtitle={
                              c.source.source_mode === "synthetic"
                                ? "当前为演示注册状态变更，不代表生产效果验收。"
                                : "审批依照固定评估规则执行，研究版本不等于生产发布。"
                            }
                          >
                            {note("审批依据", true)}
                            {c.source.domain === "market" && (
                              <button
                                disabled={
                                  !!busy ||
                                  !selectedModel?.trained ||
                                  !actor.trim() ||
                                  !approvalReason.trim()
                                }
                                onClick={() =>
                                  void act(
                                    "shadow",
                                    {},
                                    "已保留为研究观察版本，未替换研究主版本",
                                  )
                                }
                              >
                                保留为观察版本
                              </button>
                            )}
                            <div className="research-filters">
                              <button
                                disabled={
                                  !!busy ||
                                  !selectedModel?.can_approve ||
                                  !actor.trim() ||
                                  !approvalReason.trim()
                                }
                                className="primary-button"
                                onClick={() =>
                                  void act("approve", {}, "审批结果已保存")
                                }
                              >
                                审核所选模型
                              </button>
                              <button
                                disabled={
                                  !!busy ||
                                  !selectedModel?.can_rollback ||
                                  !actor.trim() ||
                                  !approvalReason.trim()
                                }
                                onClick={() =>
                                  void act("rollback", {}, "回滚结果已保存")
                                }
                              >
                                回滚所选版本
                              </button>
                              {c.source.domain === "market" && (
                                <button
                                  disabled={
                                    !!busy ||
                                    !selectedModel ||
                                    !actor.trim() ||
                                    !approvalReason.trim()
                                  }
                                  onClick={() =>
                                    void act("reject", {}, "所选研究候选已拒绝")
                                  }
                                >
                                  拒绝所选候选
                                </button>
                              )}
                            </div>
                            {c.source.domain === "market" && (
                              <div className="research-final-review">
                                <h3>一次性最终评估</h3>
                                <p className="research-help">
                                  冻结一个研究候选后才可使用最终窗口；启封失败也会消耗资格，更换数据文件不能重置。已完成的结果可在评估对比查看。
                                </p>
                                <label className="unified-confirm">
                                  <input
                                    type="checkbox"
                                    checked={auditConfirmedKey === scopeKey}
                                    onChange={(e) =>
                                      setAuditConfirmedKey(
                                        e.target.checked ? scopeKey : "",
                                      )
                                    }
                                  />
                                  已确认冻结所选版本并使用一次性最终评估资格
                                </label>
                                <button
                                  disabled={
                                    !!busy ||
                                    !selectedModel?.can_final_audit ||
                                    auditConfirmedKey !== scopeKey ||
                                    !actor.trim() ||
                                    !approvalReason.trim()
                                  }
                                  onClick={() =>
                                    void act(
                                      "final_audit",
                                      { confirmed: true },
                                      "最终评估结果已保存",
                                    )
                                  }
                                >
                                  冻结所选版本并执行最终评估
                                </button>
                              </div>
                            )}
                            <ModelTable
                              models={c.models}
                              select={(model) =>
                                change({ type: "model", model })
                              }
                            />
                          </Panel>
                        </>
                      )}
                      {s.tab === "monitor" && (
                        <>
                          <Panel title="当前范围的任务">
                            {c.jobs.length > 0 && note("任务操作依据")}
                            <div className="table-wrap">
                              <table>
                                <thead>
                                  <tr>
                                    <th>任务</th>
                                    <th>状态</th>
                                    <th>说明</th>
                                    <th>提交时间</th>
                                    <th>操作</th>
                                  </tr>
                                </thead>
                                <tbody>
                                  {c.jobs.map((j) => (
                                    <tr key={j.id}>
                                      <td>{j.display_name}</td>
                                      <td>{stateLabel(j.state)}</td>
                                      <td>
                                        {businessText(
                                          j.detail.stage ||
                                            j.detail.error ||
                                            "结果已保存",
                                        )}
                                      </td>
                                      <td>{stamp(j.created_at)}</td>
                                      <td>
                                        {[
                                          "queued",
                                          "running",
                                          "cancel_requested",
                                        ].includes(j.state) ? (
                                          <button
                                            disabled={
                                              !!busy ||
                                              j.state === "cancel_requested" ||
                                              !actor.trim() ||
                                              !reason.trim()
                                            }
                                            onClick={() =>
                                              void act(
                                                "cancel",
                                                { job_id: j.id },
                                                "已提交取消请求，请以任务实际退出状态为准",
                                              )
                                            }
                                          >
                                            取消任务
                                          </button>
                                        ) : [
                                            "failed",
                                            "cancelled",
                                            "interrupted",
                                            "unknown_exit",
                                          ].includes(j.state) ? (
                                          <button
                                            disabled={
                                              !!busy ||
                                              !actor.trim() ||
                                              !reason.trim()
                                            }
                                            onClick={() =>
                                              void act(
                                                "retry",
                                                {
                                                  job_id: j.id,
                                                  key: crypto.randomUUID(),
                                                },
                                                "已创建重试任务",
                                              )
                                            }
                                          >
                                            重试任务
                                          </button>
                                        ) : (
                                          "已完成"
                                        )}
                                      </td>
                                    </tr>
                                  ))}
                                </tbody>
                              </table>
                            </div>
                            {!c.jobs.length && (
                              <p className="research-help">
                                当前范围暂无后台训练任务；预测与人工操作记录在下方显示。
                              </p>
                            )}
                          </Panel>
                          <Panel title="当前范围的业务记录">{activity}</Panel>
                        </>
                      )}
                      {s.tab === "flow" && (
                        <>
                          <Panel title="当前范围的数据链路">
                            <div className="unified-flow">
                              {c.flow.map((x, i) => (
                                <div className="unified-flow-step" key={x.name}>
                                  <strong>{x.name}</strong>
                                  <span className="badge info">
                                    {stateLabel(x.state)}
                                  </span>
                                  <p>{x.detail}</p>
                                  {i < c.flow.length - 1 && (
                                    <ArrowRight size={16} />
                                  )}
                                </div>
                              ))}
                            </div>
                          </Panel>
                          <Panel title="来源、模型与记录归属">
                            {c.related?.map((x) => (
                              <button
                                key={x.name}
                                onClick={() => {
                                  change({
                                    type: "record",
                                    record: x.record,
                                    model: x.model,
                                    date: x.date,
                                  });
                                  change({ type: "slot", slot: x.slot });
                                  change({ type: "tab", tab: x.tab });
                                }}
                              >
                                {x.name} · {x.date}
                              </button>
                            ))}
                            <dl className="research-facts">
                              <div>
                                <dt>数据范围</dt>
                                <dd>{c.source.name}</dd>
                              </div>
                              <div>
                                <dt>业务任务</dt>
                                <dd>{c.source.task_name}</dd>
                              </div>
                              <div>
                                <dt>目标日期</dt>
                                <dd>{c.date}</dd>
                              </div>
                              <div>
                                <dt>所选模型</dt>
                                <dd>
                                  {businessText(
                                    selectedModel?.name || "未选择",
                                  )}
                                </dd>
                              </div>
                              <div>
                                <dt>当前预测</dt>
                                <dd>
                                  {businessText(
                                    c.records.find((r) => r.id === s.record)
                                      ?.name || "当前选择尚无保存预测",
                                  )}
                                </dd>
                              </div>
                            </dl>
                            <p className="research-help">
                              模型和预测必须属于所选来源与任务。切换范围会清除不适用的选择，旧结果保留在原范围中。
                            </p>
                          </Panel>
                        </>
                      )}
                      {s.tab === "trading" && (
                        <Panel title="当前范围交易测算">
                          <p>
                            此页沿用现有数据范围。市场电价只能用于价差情景，场站收益还需要合约与规则；两者不互相替代。
                          </p>
                          {note("测算保存依据")}
                          <Scenario
                            key={s.source}
                            selection={s}
                            revision={`${revision}:${c.context_version}`}
                            contextVersion={c.context_version}
                            canSave={!!actor.trim() && !!reason.trim() && !busy}
                            save={(parameters) =>
                              void act(
                                "scenario",
                                parameters,
                                "量价测算已保存并关联所选预测、观测与规则",
                              )
                            }
                          />
                        </Panel>
                      )}
                      {s.tab === "agent" && (
                        <>
                        <Panel
                          title="分析当前范围"
                          subtitle={analysisLabel(
                            c.capabilities?.analysis_mode,
                          )}
                        >
                          <p>
                            {c.source.name} · {c.date} · {c.source.task_name}
                          </p>
                          <p className="research-help">{s.slot !== null ? `重点时段：${c.points.find((p) => p.slot === s.slot) ? time(c.points.find((p) => p.slot === s.slot)!.start) : "当前范围无此时段"}。分析同时保留当日背景。` : "当前分析当日范围；可在首页选择一个时段后继续。"}</p>
                          <label className="unified-question">
                            业务问题
                            <textarea
                              value={question}
                              maxLength={2000}
                              onChange={(e) => setQuestion(e.target.value)}
                              rows={3}
                            />
                          </label>
                          <label>
                            操作人
                            <input
                              value={actor}
                              onChange={(e) => setActor(e.target.value)}
                            />
                          </label>
                          <button
                            className="primary-button"
                            disabled={
                              !!busy || !question.trim() || !actor.trim()
                            }
                            onClick={() =>
                              void act("analyze", s.slot === null ? {} : { slot: s.slot }, "分析结果已保存")
                            }
                          >
                            分析当前来源的数据
                          </button>
                          {answer && (
                            <p className="learning-answer">
                              {answerVersion === c.context_version
                                ? answer
                                : "当前数据已更新，请重新分析；原分析记录已保留。"}
                            </p>
                          )}
                        </Panel>
                        <AgentEvidence
                          key={[s.source, s.task, s.date, s.mode, s.until, s.basis].join(":")}
                          selection={s}
                          revision={`${revision}:${c.context_version}`}
                          citations={analysisEvidence.citations}
                          tools={analysisEvidence.tools}
                          notice={analysisEvidence.notice}
                          showAnalysis={!!answer && answerVersion === c.context_version}
                        />
                        </>
                      )}
                    </>
                  )}
                  <footer className="energy-footer">
                    当前范围：{c.source.name} · {c.date} · {c.source.task_name}{" "}
                    · 检查时间 {stamp(c.checked_at)}
                  </footer>
                </>
              )}
            </>
          )}
        </div>
      </main>
    </div>
  );
}
function DataTable({
  points,
  unit,
  slot,
  choose,
}: {
  points: Point[];
  unit: string;
  slot: number | null;
  choose: (slot: number) => void;
}) {
  return (
    <div className="table-wrap">
      <table>
        <thead>
          <tr>
            <th>时段</th>
            <th>实际值 / {unit}</th>
            <th>模型预测 / {unit}</th>
            <th>日前电价 / 元/MWh</th>
            <th>实时电价 / 元/MWh</th>
            <th>状态</th>
          </tr>
        </thead>
        <tbody>
          {points.map((p) => (
            <tr key={p.slot} className={slot === p.slot ? "selected-row" : ""}>
              <td>
                <button onClick={() => choose(p.slot)}>{time(p.start)}</button>
              </td>
              <td>{fmt(p.actual, 3)}</td>
              <td>{fmt(p.predicted, 3)}</td>
              <td>{fmt(p.da_price, 2)}</td>
              <td>{fmt(p.rt_price, 2)}</td>
              <td>{stateLabel(p.quality)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
function ModelTable({
  models,
  select,
}: {
  models: Model[];
  select: (id: string) => void;
}) {
  return (
    <div className="table-wrap">
      <table>
        <thead>
          <tr>
            <th>模型版本</th>
            <th>状态</th>
            <th>能力说明</th>
            <th>操作</th>
          </tr>
        </thead>
        <tbody>
          {models.map((m) => (
            <tr key={m.id}>
              <td>{businessText(m.name)}</td>
              <td>{stateLabel(m.state)}</td>
              <td>
                {m.trained ? "已有真实训练记录" : businessText(m.scope_label)} ·{" "}
                {m.can_predict ? "可运行预测" : "已有参考记录"}
              </td>
              <td>
                <button onClick={() => select(m.id)}>选择此模型</button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
function Scenario({
  selection: s,
  revision,
  contextVersion,
  canSave,
  save,
}: {
  selection: Selection;
  revision: string;
  contextVersion: string;
  canSave: boolean;
  save: (parameters: Record<string, unknown>) => void;
}) {
  const [quantity, setQuantity] = useState(1);
  const [fee, setFee] = useState(0);
  const [bidRatio, setBidRatio] = useState(1);
  const p = new URLSearchParams({
    source_key: s.source,
    task_id: s.task,
    trading_date: s.date,
    mode: s.mode,
    until: s.until,
    basis: s.basis,
    expected_version: contextVersion,
    quantity: String(quantity),
    fee: String(fee),
    bid_ratio: String(bidRatio),
  });
  if (s.model) p.set("model_id", s.model);
  if (s.record) p.set("record_id", s.record);
  const r = useResource<{
    settlement?: {
      value: number | null;
      reference: number | null;
      delta: number | null;
      settled_intervals: number;
      excluded_intervals: number;
      negative_intervals: number;
      rule: string;
      notice: string;
      hours: {
        hour: number;
        bid_mwh: number;
        actual_mwh: number;
        value: number;
        reference: number;
      }[];
    } | null;
    history?: {
      name: string;
      model_name: string;
      created_at: string;
      value: number;
      delta: number;
      intervals: number;
      bid_ratio: number;
      fee: number;
      current_observation: boolean;
    }[];
    available: boolean;
    notice: string;
    quantity: number;
    value: number | null;
    points: number;
    plans: { name: string; value: number | null; settled: number }[];
  }>("/api/v1/workspace/scenario?" + p, revision, 10000);
  return (
    <>
      <div className="research-filters">
        <label>
          假设电量 / MWh
          <input
            type="number"
            min={0}
            max={1000000}
            value={quantity}
            onChange={(e) => setQuantity(Number(e.target.value))}
          />
        </label>
        <label>
          单位费用 / 元/MWh
          <input
            type="number"
            min={0}
            max={1000000}
            value={fee}
            onChange={(e) => setFee(Number(e.target.value))}
          />
        </label>
      </div>
      <Status loading={r.loading} error={r.error} />
      {r.data && (
        <>
          {r.data.settlement && (
            <section>
              <h3>所选日前出力预测的历史结算</h3>
              <label>
                预测申报系数
                <input
                  aria-label="预测申报系数"
                  type="number"
                  min={0}
                  max={1.5}
                  step={0.05}
                  value={bidRatio}
                  onChange={(e) => setBidRatio(Number(e.target.value))}
                />
              </label>
              <p>{r.data.settlement.rule}</p>
              <p className="research-help">{r.data.settlement.notice}</p>
              <div className="research-metrics">
                <div>
                  <span>预测申报情景 / 元</span>
                  <strong>{fmt(r.data.settlement.value, 2)}</strong>
                </div>
                <div>
                  <span>全实时对照 / 元</span>
                  <strong>{fmt(r.data.settlement.reference, 2)}</strong>
                </div>
                <div>
                  <span>同范围差额 / 元</span>
                  <strong>{fmt(r.data.settlement.delta, 2)}</strong>
                </div>
                <div>
                  <span>完整结算时段</span>
                  <strong>{r.data.settlement.settled_intervals}/96</strong>
                </div>
              </div>
              <p className="research-help">
                未结算 {r.data.settlement.excluded_intervals} 个时段；保留{" "}
                {r.data.settlement.negative_intervals} 个源负出力观测。
              </p>
              <button
                disabled={
                  !canSave ||
                  !r.data.settlement.settled_intervals ||
                  r.refreshing
                }
                onClick={() => save({ bid_ratio: bidRatio, fee })}
              >
                保存当前量价测算
              </button>
              <div className="table-wrap">
                <table>
                  <thead>
                    <tr>
                      <th>小时</th>
                      <th>预测申报 / MWh</th>
                      <th>源实绩 / MWh</th>
                      <th>测算净额 / 元</th>
                      <th>全实时对照 / 元</th>
                    </tr>
                  </thead>
                  <tbody>
                    {r.data.settlement.hours.map((h) => (
                      <tr key={h.hour}>
                        <td>
                          {String(h.hour).padStart(2, "0")}:00–
                          {String(h.hour + 1).padStart(2, "0")}:00
                        </td>
                        <td>{fmt(h.bid_mwh, 3)}</td>
                        <td>{fmt(h.actual_mwh, 3)}</td>
                        <td>{fmt(h.value, 2)}</td>
                        <td>{fmt(h.reference, 2)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </section>
          )}
          {!!r.data.history?.length && (
            <section>
              <h3>已保存的量价测算</h3>
              {r.data.history.map((h, i) => (
                <article className="unified-review-history" key={i}>
                  <strong>
                    {h.name} · {businessText(h.model_name)}
                  </strong>
                  <p>
                    {stamp(h.created_at)} · 系数 {h.bid_ratio} · 费用 {h.fee}{" "}
                    元/MWh · {h.intervals} 个时段
                  </p>
                  <p>
                    净额 {fmt(h.value, 2)} 元 · 与全实时对照差额{" "}
                    {fmt(h.delta, 2)} 元 ·{" "}
                    {h.current_observation
                      ? "与当前观测版本相同"
                      : "保存时的历史观测版本"}
                  </p>
                </article>
              ))}
            </section>
          )}
          <h3>假设电量的价差敞口</h3>
          <p>{r.data.notice}</p>
          <p>
            所选范围的假设价差敞口：{fmt(r.data.value, 2)} 元 · {r.data.points}{" "}
            个有效时段
          </p>
          {r.data.plans?.length > 0 && (
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>已登记方案</th>
                    <th>结算净额 / 元</th>
                    <th>已结算时段</th>
                  </tr>
                </thead>
                <tbody>
                  {r.data.plans.map((p, i) => (
                    <tr key={i}>
                      <td>{businessText(p.name)}</td>
                      <td>{fmt(p.value, 2)}</td>
                      <td>{p.settled}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </>
      )}
    </>
  );
}

function HistoryAnalysis({
  selection: s,
  revision,
  theme,
  contextVersion,
}: {
  selection: Selection;
  revision: string;
  theme: Theme;
  contextVersion: string;
}) {
  const [days, setDays] = useState(14);
  const q = new URLSearchParams({
    source_key: s.source,
    task_id: s.task,
    trading_date: s.date,
    days: String(days),
    mode: s.mode,
    until: s.until,
    basis: s.basis,
    expected_version: contextVersion,
  });
  if (s.model) q.set("model_id", s.model);
  if (s.record) q.set("record_id", s.record);
  const r = useResource<{
    unit: string;
    notice: string;
    decomposition_available: boolean;
    points: {
      start: string;
      actual: number | null;
      trend: number | null;
      seasonal: number | null;
      residual: number | null;
    }[];
  }>("/api/v1/workspace/history?" + q, revision, 10000);
  const d = r.data;
  return (
    <>
      <Panel title="历史观察与分解">
        <label>
          历史范围
          <select
            value={days}
            onChange={(e) => setDays(Number(e.target.value))}
          >
            {[7, 14, 28].map((n) => (
              <option key={n} value={n}>
                最近 {n} 个交易日
              </option>
            ))}
          </select>
        </label>
        <Status loading={r.loading} error={r.error} />
        {d && (
          <>
            <p className="research-help">{d.notice}</p>
            <div className="research-two-grid">
              {(
                [
                  { key: "actual", name: "历史实际值" },
                  { key: "trend", name: "日均趋势" },
                  ...(d.decomposition_available
                    ? [
                        { key: "seasonal", name: "同时段周期" },
                        { key: "residual", name: "剩余波动" },
                      ]
                    : []),
                ] as {
                  key: "actual" | "trend" | "seasonal" | "residual";
                  name: string;
                }[]
              ).map((f) => (
                <section key={f.key}>
                  <h3>{f.name}</h3>
                  <Chart
                    theme={theme}
                    compact
                    label={f.name}
                    group="unified-history"
                    option={() => ({
                      ...baseOption(),
                      xAxis: {
                        ...baseOption().xAxis,
                        data: d.points.map((p) => stamp(p.start)),
                      },
                      yAxis: {
                        ...baseOption().yAxis,
                        name: d.unit,
                        scale: true,
                      },
                      dataZoom: [{ type: "inside" }],
                      series: [
                        {
                          name: f.name,
                          type: "line",
                          symbol: "none",
                          connectNulls: false,
                          data: d.points.map((p) => p[f.key]),
                        },
                      ],
                    })}
                  />
                </section>
              ))}
            </div>
          </>
        )}
      </Panel>
    </>
  );
}
