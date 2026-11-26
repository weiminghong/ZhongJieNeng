import { useEffect, useState } from "react";
import {
  Activity,
  ArrowRight,
  BrainCircuit,
  Database,
  FileSearch,
  RefreshCw,
  Terminal,
} from "lucide-react";
import { fmt, stamp, useResource } from "./api";
import { Panel, Status } from "./components";
import Chart, { baseOption, color } from "./Chart";
import { names, states } from "./LearningLoop";
import type {
  Entity,
  Model,
  Overview,
  Prediction,
  Report,
  Score,
} from "./LearningLoop";
import type { PublicCatalog, PublicMetadata } from "./publicTypes";
import type { Theme } from "./types";
import "./styles/research.css";
import { recordLabel, businessText, stateLabel } from "./presentation";

export type NavigateResearch = (
  tab: string,
  context?: Record<string, string>,
) => void;
type Event = Overview["events"][number];
type Summary = {
  catalog: PublicCatalog;
  active_model: Entity<Model> | null;
  latest_prediction: Entity<Prediction> | null;
  model_count: number;
  prediction_count: number;
  worker: Overview["worker"];
  monitor: Overview["monitor"];
  jobs: Overview["jobs"];
  events: Event[];
  checked_at: string;
};
type Quality = {
  metadata: PublicMetadata;
  fields: {
    key: string;
    column: string;
    unit: string;
    valid: number;
    missing: number;
    missing_percent: number;
    negative: number;
    minimum: number | null;
    maximum: number | null;
  }[];
  expected_records: number;
  missing_intervals: number;
  incomplete_days: number;
  checked_at: string;
  original_preview: Record<string, string>[];
};
type Comparison = {
  model_id: string;
  dataset_id: string;
  source_hash: string;
  partition: string;
  start: string;
  end: string;
  rows: {
    model_id: string;
    algorithm: string;
    alpha: number | null;
    state: string;
    scores: Score & { negative: Score; spike: Score };
    aliases: string[];
  }[];
  daily: { date: string; n: number; mae: Record<string, number> }[];
  report: Report;
  expected: number;
  label_coverage: number;
  notice: string;
};
const clock = (s: number) =>
  `${String(Math.floor(s / 4)).padStart(2, "0")}:${String((s % 4) * 15).padStart(2, "0")}`;
const fresh = (worker?: Overview["worker"]) =>
  !!worker?.updated_at &&
  Date.now() - Date.parse(worker.updated_at) < 45000 &&
  ["ready", "busy"].includes(worker.state);
const eventName: Record<string, string> = {
  activate: "申请审批",
  predict: "执行预测",
  feedback: "提交复核",
  confirm: "确认复核",
  proposal: "创建重训提案",
  train_proposal: "提交重训",
  train: "提交训练",
  analyze: "分析预测证据",
  research_active: "研究主版本生效",
  retired: "原版本退役",
  succeeded: "执行完成",
  submitted: "复核待确认",
  confirmed: "复核已确认",
  evaluated: "模型评估完成",
  child_complete: "产物已生成，等待退出确认",
  unknown_exit: "退出未确认",
  queued: "进入队列",
  preparing: "准备样本",
  training: "拟合权重",
  evaluating: "计算评估",
  cancelled: "任务已取消",
};
function eventRoute(e: Event): string {
  return e.subject_id.startsWith("job_")
    ? "monitor"
    : e.subject_id.startsWith("prediction_")
      ? "forecast"
      : e.subject_id.startsWith("model_")
        ? "learning"
        : "rsi";
}
function EventList({
  events,
  navigate,
}: {
  events: Event[];
  navigate: NavigateResearch;
}) {
  return (
    <div className="research-events">
      {events.length ? (
        events.map((e, i) => (
          <button
            key={`${e.subject_id}:${e.created_at}:${i}`}
            onClick={() =>
              navigate(
                eventRoute(e),
                e.subject_id.startsWith("prediction_")
                  ? { ml_prediction: e.subject_id }
                  : e.subject_id.startsWith("model_")
                    ? { ml_model: e.subject_id }
                    : e.subject_id.startsWith("job_")
                      ? { job: e.subject_id }
                      : {},
              )
            }
          >
            <Activity size={16} />
            <span>
              <strong>
                {eventName[e.state] || states[e.state] || stateLabel(e.state)}
              </strong>
              <small>
                {e.display_name || "业务操作"}
                {typeof e.detail.reason === "string"
                  ? ` · ${businessText(e.detail.reason)}`
                  : ""}
              </small>
            </span>
            <time>{stamp(e.created_at)}</time>
            <ArrowRight size={14} />
          </button>
        ))
      ) : (
        <p className="research-empty">尚无业务操作记录。</p>
      )}
    </div>
  );
}

export function ResearchOverview({
  theme,
  revision,
  navigate,
}: {
  theme: Theme;
  revision: number;
  navigate: NavigateResearch;
}) {
  const resource = useResource<Summary>(
    "/api/v1/research/summary",
    revision,
    5000,
  );
  const d = resource.data;
  const prediction = d?.latest_prediction;
  const model = d?.active_model;
  const scores = prediction?.payload.scores;
  return (
    <div className="research-page">
      <div className="research-intro">
        <div>
          <h2>预测研究总览</h2>
          <p>先看数据与模型是否就绪，再进入一次可追溯的预测。</p>
        </div>
        <button
          className="primary-button"
          onClick={() =>
            navigate(
              "forecast",
              prediction
                ? {
                    ml_model: prediction.payload.model_id,
                    ml_date: prediction.payload.date,
                    ml_prediction: prediction.id,
                  }
                : {},
            )
          }
        >
          进入预测分析
          <ArrowRight size={16} />
        </button>
      </div>
      <Status loading={resource.loading} error={resource.error} />
      {d && (
        <>
          <div className="research-context">
            <Activity size={22} />
            <div>
              <strong>
                {model ? "研究主版本已就绪" : "等待批准研究主版本"}
              </strong>
              <span>
                {model
                  ? names[model.payload.algorithm]
                  : "先核对数据并完成一次训练"}{" "}
                · {d.catalog.metadata?.name || "数据源未配置"}
              </span>
            </div>
            <span className="badge warning">历史公开数据 · 非场站生产</span>
            <div className="research-context-end">
              <small>源文件覆盖至</small>
              <strong>{d.catalog.metadata?.date_end || "—"}</strong>
            </div>
          </div>
          <div className="research-metrics">
            <div>
              <span>已有原始记录</span>
              <strong>
                {fmt(d.catalog.metadata?.row_count, 0)}
                <small>条</small>
              </strong>
              <p>
                {d.catalog.metadata?.date_start} 至{" "}
                {d.catalog.metadata?.date_end}
              </p>
            </div>
            <div>
              <span>最近预测日 · 预测均价</span>
              <strong>
                {prediction
                  ? fmt(
                      prediction.payload.points.reduce(
                        (n, p) => n + p.predicted,
                        0,
                      ) / 96,
                      2,
                    )
                  : "—"}
                <small>元/MWh</small>
              </strong>
              <p>
                {prediction?.payload.date || "尚无推理记录"} ·
                独立保存的模型输出
              </p>
            </div>
            <div>
              <span>该次预测配对 MAE</span>
              <strong>
                {fmt(scores?.mae, 2)}
                <small>元/MWh</small>
              </strong>
              <p>
                {scores?.n || 0}/96 条实际标签 ·{" "}
                {prediction?.payload.validation_only ? "调参验证" : "研究推理"}
              </p>
            </div>
            <div>
              <span>实际训练任务</span>
              <strong>
                {d.jobs.filter((j) => j.state === "succeeded").length}
                <small>次成功</small>
              </strong>
              <p>
                {d.model_count} 个模型版本 · 执行器
                {fresh(d.worker) ? "在线" : "等待心跳"}
              </p>
            </div>
          </div>
          <div className="research-wide-grid">
            <Panel
              title="模型预测与原始价格"
              subtitle={
                prediction
                  ? `${prediction.payload.date} · 此图取自已保存预测，不自动启动新任务。`
                  : "预测完成后，曲线会与原始标签一同显示。"
              }
              action={
                <button
                  onClick={() =>
                    navigate(
                      "forecast",
                      prediction
                        ? {
                            ml_prediction: prediction.id,
                            ml_model: prediction.payload.model_id,
                            ml_date: prediction.payload.date,
                          }
                        : {},
                    )
                  }
                >
                  查看详细分析
                  <ArrowRight size={14} />
                </button>
              }
            >
              {prediction ? (
                <Chart
                  theme={theme}
                  label="已保存真实电价预测与实际价格"
                  option={() => ({
                    ...baseOption(),
                    xAxis: {
                      ...baseOption().xAxis,
                      data: prediction.payload.points.map((p) => clock(p.slot)),
                    },
                    yAxis: {
                      ...baseOption().yAxis,
                      name: "元/MWh",
                      scale: true,
                    },
                    series: [
                      {
                        name: "本站模型预测",
                        type: "line",
                        symbol: "none",
                        data: prediction.payload.points.map((p) => p.predicted),
                      },
                      {
                        name: "原始实际价格",
                        type: "line",
                        symbol: "none",
                        lineStyle: { type: "dashed" },
                        data: prediction.payload.points.map((p) => p.actual),
                      },
                    ],
                  })}
                />
              ) : (
                <div className="research-empty">
                  <Activity size={28} />
                  <strong>还没有可显示的预测记录</strong>
                  <p>选择训练完成的模型运行预测；不会用示例曲线替代。</p>
                  <button onClick={() => navigate("forecast")}>
                    开始一次预测
                  </button>
                </div>
              )}
            </Panel>
            <Panel
              title="这次研究如何接续"
              subtitle="每一步指向同一套数据和模型记录。"
            >
              <div className="research-next-steps">
                {[
                  {
                    tab: "raw",
                    name: "核对数据",
                    detail: `${d.catalog.metadata?.row_count.toLocaleString() || 0} 条源记录与缺失情况`,
                  },
                  {
                    tab: "learning",
                    name: "训练与模型",
                    detail: model
                      ? recordLabel(model, "当前模型")
                      : "创建真实训练任务",
                  },
                  {
                    tab: "compare",
                    name: "同口径评估",
                    detail: "训练候选与三个基线共用标签掩码",
                  },
                  {
                    tab: "rsi",
                    name: "复核与审批",
                    detail: "核对预测 → 提议重训 → 规则审批",
                  },
                ].map((s) => (
                  <button
                    key={s.tab}
                    onClick={() =>
                      navigate(s.tab, model ? { ml_model: model.id } : {})
                    }
                  >
                    <span>
                      <strong>{s.name}</strong>
                      <small>{s.detail}</small>
                    </span>
                    <ArrowRight size={16} />
                  </button>
                ))}
              </div>
              <p className="research-help">
                历史到达时间未经核验。本页面的系统时间、数据覆盖时间与预测目标日分别显示。
              </p>
            </Panel>
          </div>
          <div className="research-two-grid">
            <Panel
              title="当前研究主版本"
              action={
                <button onClick={() => navigate("learning")}>
                  模型中心
                  <ArrowRight size={14} />
                </button>
              }
            >
              {model ? (
                <>
                  <div className="research-model-lead">
                    <BrainCircuit size={28} />
                    <div>
                      <strong>{names[model.payload.algorithm]}</strong>
                      <p>{recordLabel(model, "研究模型")} · 真实权重已校验</p>
                    </div>
                    <span className="badge success">研究使用</span>
                  </div>
                  <dl className="research-facts">
                    <div>
                      <dt>训练集</dt>
                      <dd>{model.payload.splits.train.join(" 至 ")}</dd>
                    </div>
                    <div>
                      <dt>提升窗口 MAE</dt>
                      <dd>
                        {fmt(
                          model.payload.report.promotion.scores[
                            model.payload.algorithm
                          ]?.mae,
                          3,
                        )}{" "}
                        元/MWh
                      </dd>
                    </div>
                    <div>
                      <dt>数据版本</dt>
                      <dd>项目既有历史数据</dd>
                    </div>
                  </dl>
                  <button
                    onClick={() => navigate("compare", { ml_model: model.id })}
                  >
                    查看完整对比
                  </button>
                </>
              ) : (
                <p className="research-empty">
                  尚未批准研究主版本，已训练候选可在模型页查看。
                </p>
              )}
            </Panel>
            <Panel
              title="最近业务动态"
              action={
                <button onClick={() => navigate("monitor")}>
                  全部记录
                  <ArrowRight size={14} />
                </button>
              }
            >
              <EventList events={d.events.slice(0, 5)} navigate={navigate} />
            </Panel>
          </div>
        </>
      )}
    </div>
  );
}

export function ResearchDataSummary({
  revision,
  navigate,
}: {
  revision: number;
  navigate: NavigateResearch;
}) {
  const data = useResource<Quality>(
    "/api/v1/research/data-quality",
    revision,
    30000,
  );
  const [expanded, setExpanded] = useState(false);
  const q = data.data;
  return (
    <div className="research-data-summary">
      <Status loading={data.loading} error={data.error} />
      {q && (
        <Panel
          title="已有数据源与质量"
          subtitle="参考系统的数据管理方式，逐项核对覆盖、缺失与单位。已有原文件只读，登记版本不会修改原始记录。"
          action={
            <button onClick={() => navigate("learning")}>
              用于训练
              <ArrowRight size={15} />
            </button>
          }
        >
          <div className="research-data-strip">
            <Database size={24} />
            <div>
              <strong>{q.metadata.name}</strong>
              <p>
                {q.metadata.date_start} 至 {q.metadata.date_end} ·{" "}
                {q.metadata.row_count.toLocaleString()} 条 · 15分钟
              </p>
            </div>
            <span className="badge warning">公开省级数据</span>
            <button
              onClick={() => setExpanded((v) => !v)}
              aria-expanded={expanded}
            >
              {expanded ? "收起质量明细" : "查看质量明细"}
            </button>
          </div>
          <div className="research-quality-counts">
            <span>
              时段缺口 <strong>{q.missing_intervals}</strong>
            </span>
            <span>
              不完整交易日 <strong>{q.incomplete_days}</strong>
            </span>
            <span>
              存在缺失的数据项{" "}
              <strong>{q.fields.filter((f) => f.missing > 0).length}</strong>
            </span>
            <span>数据已保留版本</span>
          </div>
          {expanded && (
            <div className="table-scroll">
              <table>
                <thead>
                  <tr>
                    <th>数据项</th>
                    <th>单位</th>
                    <th>有效 / 缺失</th>
                    <th>缺失率</th>
                    <th>原始负值</th>
                    <th>最小 / 最大</th>
                  </tr>
                </thead>
                <tbody>
                  {q.fields.map((f) => (
                    <tr key={f.key}>
                      <td>{f.column}</td>
                      <td>{f.unit}</td>
                      <td>
                        {f.valid.toLocaleString()} /{" "}
                        {f.missing.toLocaleString()}
                      </td>
                      <td>{fmt(f.missing_percent, 2)}%</td>
                      <td>{f.negative}</td>
                      <td>
                        {fmt(f.minimum, 2)} / {fmt(f.maximum, 2)}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          <p className="research-help">
            下方原始行、回放窗口与训练版本分别保留来源。缺失值保持为空，负值原样保留，不直接采用参考系统的负荷清洗规则。
          </p>
        </Panel>
      )}
    </div>
  );
}

export function ResearchComparison({
  theme,
  revision,
  navigate,
}: {
  theme: Theme;
  revision: number;
  navigate: NavigateResearch;
}) {
  const overview = useResource<Overview>("/api/v1/ml/overview", revision, 5000);
  const [modelId, setModelId] = useState(
    () => new URLSearchParams(location.search).get("ml_model") || "",
  );
  const [partition, setPartition] = useState("promotion");
  useEffect(() => {
    if (!modelId && overview.data)
      setModelId(
        overview.data.active.detail.model_id ||
          overview.data.models.find((m) => m.payload.algorithm === "ridge")
            ?.id ||
          "",
      );
  }, [overview.data, modelId]);
  const resource = useResource<Comparison>(
    modelId
      ? `/api/v1/research/comparison?model_id=${encodeURIComponent(modelId)}&partition=${partition}`
      : null,
    revision,
  );
  const d = resource.data;
  useEffect(() => {
    if (modelId) {
      const u = new URL(location.href);
      if (
        u.searchParams.get("ml_model") &&
        u.searchParams.get("ml_model") !== modelId
      )
        u.searchParams.delete("ml_prediction");
      u.searchParams.set("ml_model", modelId);
      history.replaceState(null, "", u);
    }
  }, [modelId]);
  const modelOptions = overview.data?.models || [];
  const rowName = (r: Comparison["rows"][number]) =>
    names[r.algorithm] + (r.alpha !== null ? ` · 训练参数 ${r.alpha}` : "");
  return (
    <div className="research-page">
      <div className="research-intro">
        <div>
          <h2>评估对比</h2>
          <p>
            在相同日期、标签和数据版本上比较，避免把不同实验的数字拼在一起。
          </p>
        </div>
        <button onClick={() => navigate("learning")}>
          训练对照版本
          <ArrowRight size={15} />
        </button>
      </div>
      <Panel title="选择比较范围">
        <div className="research-filters">
          <label>
            参考模型
            <select
              value={modelId}
              onChange={(e) => setModelId(e.target.value)}
            >
              <option value="">选择已训练模型</option>
              {modelOptions.map((m) => (
                <option key={m.id} value={m.id}>
                  {names[m.payload.algorithm]}
                  {m.payload.alpha !== null
                    ? ` · 训练参数 ${m.payload.alpha}`
                    : ""}{" "}
                  · {recordLabel(m, "研究模型")} · {states[m.state]}
                </option>
              ))}
            </select>
          </label>
          <label>
            评估窗口
            <select
              value={partition}
              onChange={(e) => setPartition(e.target.value)}
            >
              <option value="tune">调参窗口（非独立测试）</option>
              <option value="promotion">提升评估窗口</option>
              <option value="final_audit">已启封的最终审计</option>
            </select>
          </label>
        </div>
        <p className="research-help">
          最终审计只读取既有封存结果，不因查看页面重新启封或评估其他候选。相同输出的重复任务折叠显示，原版本记录继续保留。
        </p>
      </Panel>
      <Status
        loading={resource.loading || overview.loading}
        error={resource.error || overview.error}
      />
      {!modelId && !overview.loading && (
        <p className="research-empty">尚无已训练模型，先从训练与模型页开始。</p>
      )}
      {d && (
        <>
          <div className="research-context">
            <FileSearch size={22} />
            <div>
              <strong>
                {d.start} 至 {d.end}
              </strong>
              <span>
                {d.report.rows.toLocaleString()} 条共同标签 /{" "}
                {d.expected.toLocaleString()} 个预期时段 · 标签覆盖{" "}
                {fmt(d.label_coverage * 100, 2)}%
              </span>
            </div>
            <span className="badge info">同一标签掩码</span>
          </div>
          <Panel
            title="点预测误差"
            subtitle="数值越低表示该窗口的平均误差越小；单位均为元/MWh。"
          >
            <Chart
              theme={theme}
              label="同掩码模型MAE与RMSE比较"
              option={() => ({
                ...baseOption(),
                xAxis: {
                  ...baseOption().xAxis,
                  data: d.rows.map(rowName),
                  axisLabel: {
                    color: color("on-surface-variant"),
                    width: 100,
                    overflow: "truncate",
                    interval: 0,
                    rotate: 12,
                  },
                },
                yAxis: { ...baseOption().yAxis, name: "元/MWh" },
                series: [
                  {
                    name: "MAE",
                    type: "bar",
                    data: d.rows.map((r) => r.scores.mae),
                    barMaxWidth: 32,
                  },
                  {
                    name: "RMSE",
                    type: "bar",
                    data: d.rows.map((r) => r.scores.rmse),
                    barMaxWidth: 32,
                  },
                ],
              })}
            />
            <div className="table-scroll">
              <table>
                <thead>
                  <tr>
                    <th>模型</th>
                    <th>MAE</th>
                    <th>RMSE</th>
                    <th>平均偏差 MBE</th>
                    <th>负价 MAE / 条数</th>
                    <th>高价 MAE / 条数</th>
                    <th>版本</th>
                  </tr>
                </thead>
                <tbody>
                  {d.rows.map((r, i) => (
                    <tr key={r.model_id + ":" + r.algorithm + ":" + i}>
                      <td>
                        {rowName(r)}
                        <small>{states[r.state] || r.state}</small>
                      </td>
                      <td>{fmt(r.scores.mae, 3)}</td>
                      <td>{fmt(r.scores.rmse, 3)}</td>
                      <td>{fmt(r.scores.mbe, 3)}</td>
                      <td>
                        {fmt(r.scores.negative.mae, 3)} / {r.scores.negative.n}
                      </td>
                      <td>
                        {fmt(r.scores.spike.mae, 3)} / {r.scores.spike.n}
                      </td>
                      <td>
                        <button
                          onClick={() =>
                            navigate("learning", {
                              ml_model: r.model_id,
                              ml_date: d.end,
                            })
                          }
                        >
                          查看版本
                        </button>
                        <small>合并 {r.aliases.length} 条等价记录</small>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Panel>
          <div className="research-two-grid">
            <Panel
              title="按交易日查看误差"
              subtitle="每条线对应同一窗口内一个实际方法输出。"
            >
              <Chart
                theme={theme}
                label="各模型逐日配对MAE"
                option={() => ({
                  ...baseOption(),
                  xAxis: {
                    ...baseOption().xAxis,
                    data: d.daily.map((x) => x.date),
                  },
                  yAxis: { ...baseOption().yAxis, name: "MAE 元/MWh" },
                  series: d.rows.map((r, i) => ({
                    name: rowName(r) + ` #${i + 1}`,
                    type: "line" as const,
                    symbol: "none",
                    data: d.daily.map(
                      (x) =>
                        x.mae[
                          partition === "final_audit" ? r.algorithm : r.model_id
                        ],
                    ),
                  })),
                })}
              />
            </Panel>
            <Panel
              title="差异是否足够明确"
              subtitle="Ridge相对各基线的日配对MAE差；7天移动块、2000次，95%区间。"
            >
              <div className="research-interval-list">
                {Object.entries(d.report.comparisons).map(([name, c]) => (
                  <div key={name}>
                    <strong>{names[name]}</strong>
                    <p>
                      {fmt(c.delta_mae, 3)} [{fmt(c.lower95, 3)},{" "}
                      {fmt(c.upper95, 3)}] 元/MWh
                    </p>
                    <span
                      className={`badge ${c.conclusion === "improved" ? "success" : "warning"}`}
                    >
                      {c.conclusion === "improved"
                        ? "此窗口支持误差改善"
                        : c.conclusion === "worse"
                          ? "此窗口支持误差更大"
                          : "差异证据不确定"}
                    </span>
                  </div>
                ))}
              </div>
              <p className="research-help">
                区间跨过0表示证据不足，不能写成“一样好”。价格可能为零或负数，因此不照搬负荷系统的百分比误差排名。
              </p>
            </Panel>
          </div>
        </>
      )}
    </div>
  );
}

export function ResearchDecomposition({
  theme,
  revision,
}: {
  theme: Theme;
  revision: number;
}) {
  const catalog = useResource<PublicCatalog>(
    "/api/v1/public-data/catalog",
    revision,
  );
  const [day, setDay] = useState(
    () => new URLSearchParams(location.search).get("date") || "",
  );
  const [field, setField] = useState("rt_price");
  const [windowDays, setWindowDays] = useState(14);
  const [cursor, setCursor] = useState(() => {
    const n = Number(new URLSearchParams(location.search).get("cursor") ?? 96);
    return Number.isInteger(n) && n >= 0 && n <= 96 ? n : 96;
  });
  useEffect(() => {
    if (!day) return;
    const u = new URL(location.href);
    if (u.searchParams.get("ml_date") && u.searchParams.get("ml_date") !== day)
      u.searchParams.delete("ml_prediction");
    u.searchParams.set("date", day);
    u.searchParams.set("ml_date", day);
    u.searchParams.set("cursor", String(cursor));
    history.replaceState(null, "", u);
  }, [day, cursor]);
  useEffect(() => {
    if (!day && catalog.data?.default_date) setDay(catalog.data.default_date);
  }, [day, catalog.data]);
  const resource = useResource<{
    points: {
      timestamp: string;
      actual: number | null;
      trend: number | null;
      seasonal: number | null;
      residual: number | null;
    }[];
    unit: string;
    method: string;
    notice: string;
    scope: { start: string; end: string };
  }>(
    day && catalog.data?.metadata
      ? `/api/v1/research/decomposition?trading_date=${day}&field=${field}&days=${windowDays}&cursor=${cursor}&source_hash=${catalog.data.metadata.source_hash}`
      : null,
    revision,
  );
  const d = resource.data;
  const fields = [
    { key: "actual", title: "原始观测", token: "data" },
    { key: "trend", title: "日均趋势", token: "primary" },
    { key: "seasonal", title: "同时段周期", token: "success" },
    { key: "residual", title: "剩余波动", token: "warning" },
  ] as const;
  return (
    <div className="research-page">
      <div className="research-intro">
        <div>
          <h2>时序分解</h2>
          <p>把历史变化拆开看，帮助发现周期与异常，再回到原始行核对。</p>
        </div>
      </div>
      <Panel title="选择历史范围">
        <div className="research-filters">
          <label>
            截止交易日
            <input
              type="date"
              value={day}
              min={catalog.data?.metadata?.date_start}
              max={catalog.data?.metadata?.date_end}
              onChange={(e) => setDay(e.target.value)}
            />
          </label>
          <label>
            分析指标
            <select value={field} onChange={(e) => setField(e.target.value)}>
              <option value="rt_price">实时电价 · 元/MWh</option>
              <option value="pv_actual_mw">区域光伏实际 · MW</option>
              <option value="load_actual_mw">区域负荷实际 · MW</option>
            </select>
          </label>
          <label>
            历史窗口
            <select
              value={windowDays}
              onChange={(e) => setWindowDays(Number(e.target.value))}
            >
              {[7, 14, 28].map((n) => (
                <option key={n} value={n}>
                  最近 {n} 天
                </option>
              ))}
            </select>
          </label>
          <label>
            末日已展示时段
            <input
              type="number"
              min={0}
              max={96}
              value={cursor}
              onChange={(e) => setCursor(Number(e.target.value))}
            />
          </label>
        </div>
        <p className="research-help">
          这是历史描述，不是因果解释，也不会把分解后的未来值送进模型。缺失实测不补成0。末日只分析已展示的{" "}
          {cursor}/96 个时段。
        </p>
      </Panel>
      <Status
        loading={resource.loading || catalog.loading}
        error={resource.error || catalog.error}
      />
      {d && (
        <>
          <p className="research-help">
            {d.method} · {d.scope.start.slice(0, 10)} 至{" "}
            {d.scope.end.slice(0, 10)}
          </p>
          <div className="research-two-grid">
            {fields.map((f) => (
              <Panel key={f.key} title={f.title}>
                <Chart
                  theme={theme}
                  compact
                  group="research-decomposition"
                  label={f.title}
                  option={() => ({
                    ...baseOption(),
                    color: [color(f.token)],
                    xAxis: {
                      ...baseOption().xAxis,
                      data: d.points.map((p) =>
                        p.timestamp.slice(5, 16).replace("T", " "),
                      ),
                    },
                    yAxis: { ...baseOption().yAxis, name: d.unit, scale: true },
                    dataZoom: [{ type: "inside" }],
                    series: [
                      {
                        name: f.title,
                        type: "line",
                        symbol: "none",
                        data: d.points.map((p) => p[f.key]),
                      },
                    ],
                  })}
                />
              </Panel>
            ))}
          </div>
          <p className="research-help">{d.notice}</p>
        </>
      )}
    </div>
  );
}

export function ResearchMonitor({
  revision,
  navigate,
}: {
  revision: number;
  navigate: NavigateResearch;
}) {
  const [rev, setRev] = useState(0);
  const resource = useResource<Overview>(
    "/api/v1/ml/overview",
    `${revision}:${rev}`,
    5000,
  );
  const events = useResource<{ events: Event[] }>(
    "/api/v1/research/events",
    `${revision}:${rev}`,
    5000,
  );
  const [jobId, setJobId] = useState(
    () => new URLSearchParams(location.search).get("job") || "",
  );
  const logs = useResource<
    Overview["jobs"][number] & {
      events: {
        state: string;
        detail: Record<string, unknown>;
        created_at: string;
      }[];
    }
  >(jobId ? `/api/v1/ml/jobs/${encodeURIComponent(jobId)}` : null, rev, 3000);
  const d = resource.data;
  return (
    <div className="research-page">
      <div className="research-intro">
        <div>
          <h2>运行监测</h2>
          <p>区分数据到了、任务正在跑，以及结果已经成功保存。</p>
        </div>
        <button onClick={() => setRev((v) => v + 1)}>
          <RefreshCw size={16} />
          检查最新状态
        </button>
      </div>
      <Status loading={resource.loading} error={resource.error} />
      {d && (
        <>
          <div className="research-context">
            <Activity size={22} />
            <div>
              <strong>
                {fresh(d.worker) ? "CPU 执行器在线" : "执行器心跳未就绪"}
              </strong>
              <span>心跳 {stamp(d.worker.updated_at || "")} · 页面5秒检查</span>
            </div>
            <span className="badge info">单训练槽位</span>
          </div>
          <div className="research-two-grid">
            <Panel title="数据更新与研究策略">
              <dl className="research-facts">
                <div>
                  <dt>数据版本检查</dt>
                  <dd>每30秒 · {stamp(d.monitor.updated_at || "")}</dd>
                </div>
                <div>
                  <dt>最新覆盖日</dt>
                  <dd>{d.monitor.detail.date_end || "—"}</dd>
                </div>
                <div>
                  <dt>自动处理</dt>
                  <dd>版本变化 → 质量检查 → 尝试已批准主模型推理</dd>
                </div>
                <div>
                  <dt>训练预算</dt>
                  <dd>CPU · 最多4线程 · 每次30分钟上限</dd>
                </div>
                <div>
                  <dt>自动训练</dt>
                  <dd>关闭；需确认复核并提交具体重训提案</dd>
                </div>
                <div>
                  <dt>发布规则</dt>
                  <dd>研究使用；MAE差置信上界低于0且RMSE不劣于现任版本</dd>
                </div>
              </dl>
              <p className="research-help">
                本轮取长补短保留受控训练合同，不照搬参考系统的WAPE阈值、自动上线或模拟进度。源文件没有变化时，只更新检查时间。
              </p>
              <button onClick={() => navigate("raw")}>
                查看数据版本
                <ArrowRight size={15} />
              </button>
            </Panel>
            <Panel title="状态说明">
              <div className="research-status-legend">
                {[
                  [
                    "排队 / 准备 / 训练 / 评估",
                    "实际工作阶段，不换算成猜测的百分比。",
                  ],
                  ["成功", "控制器实际确认完成并保存了有效结果。"],
                  [
                    "退出未确认",
                    "旧控制器没有观测到完成情况；保留结果，不能冒称成功。",
                  ],
                  ["失败 / 取消", "保留原尝试；重试会创建独立任务。"],
                ].map(([a, b]) => (
                  <div key={a}>
                    <strong>{a}</strong>
                    <p>{b}</p>
                  </div>
                ))}
              </div>
            </Panel>
          </div>
          <Panel
            title="实际计算任务"
            subtitle="选择日志后查看该任务的完整追加事件。运行任务的取消和重试仍通过训练页记录操作依据。"
          >
            <div className="table-scroll">
              <table>
                <thead>
                  <tr>
                    <th>任务</th>
                    <th>状态</th>
                    <th>运行证据</th>
                    <th>提交时间</th>
                    <th>操作</th>
                  </tr>
                </thead>
                <tbody>
                  {d.jobs.map((j) => (
                    <tr key={j.id}>
                      <td>
                        {recordLabel(j, "训练任务")}
                        <small>训练参数 {j.config.alpha}</small>
                      </td>
                      <td>
                        {states[j.state] || stateLabel(j.state)}
                        <small>
                          {businessText(j.detail.stage || j.detail.error)}
                        </small>
                      </td>
                      <td>
                        {j.detail.measured_seconds !== undefined
                          ? `${fmt(j.detail.measured_seconds, 2)} 秒`
                          : "—"}
                        <small>
                          {j.state === "succeeded"
                            ? "结果已核验"
                            : "完成情况见任务进展"}
                        </small>
                      </td>
                      <td>{stamp(j.created_at)}</td>
                      <td>
                        <button
                          onClick={() => {
                            setJobId(j.id);
                            const u = new URL(location.href);
                            u.searchParams.set("job", j.id);
                            history.replaceState(null, "", u);
                          }}
                        >
                          <Terminal size={14} />
                          日志
                        </button>
                        <button onClick={() => navigate("learning")}>
                          训练操作
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            {!d.jobs.length && <p className="research-empty">尚无计算任务。</p>}
          </Panel>
          {jobId && (
            <Panel title={recordLabel(logs.data, "任务进展")}>
              <Status loading={logs.loading} error={logs.error} />
              <div className="research-log" role="log">
                {logs.data?.events.map((e, i) => (
                  <div key={i}>
                    <time>{stamp(e.created_at)}</time>
                    <strong>{states[e.state] || stateLabel(e.state)}</strong>
                    <p>
                      {businessText(
                        e.detail.error ||
                          e.detail.stage ||
                          (e.state === "succeeded"
                            ? "训练与评估已经完成，结果已保存。"
                            : e.state === "unknown_exit"
                              ? "执行结果暂未完成核验，历史结果已保留。"
                              : "进展已记录。"),
                      )}
                    </p>
                  </div>
                ))}
              </div>
            </Panel>
          )}
          <Panel
            title="业务操作历程"
            subtitle="过滤例行心跳，保留训练、预测、复核和版本切换的实际事件。"
          >
            <Status error={events.error} />
            <EventList events={events.data?.events || []} navigate={navigate} />
          </Panel>
        </>
      )}
    </div>
  );
}
