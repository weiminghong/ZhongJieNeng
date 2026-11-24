import { useEffect, useState } from "react";
import { RefreshCw, Play, Undo2, FileCheck2 } from "lucide-react";
import type { Theme } from "./types";
import type { PublicCatalog } from "./publicTypes";
import { fmt, request, stamp, useResource } from "./api";
import { Panel, Status } from "./components";
import Chart, { baseOption, color } from "./Chart";
import "./styles/learning.css";

type Entity<P> = {
  id: string;
  state: string;
  source_hash: string;
  parent_id: string | null;
  created_at: string;
  payload: P;
};
type Score = {
  n: number;
  mae: number | null;
  rmse: number | null;
  mbe: number | null;
};
type Comparison = {
  days: number;
  delta_mae: number;
  lower95: number | null;
  upper95: number | null;
  conclusion: string;
};
type Report = {
  rows: number;
  days: number;
  scores: Record<string, Score & { negative: Score; spike: Score }>;
  comparisons: Record<string, Comparison>;
  row_mask_hash: string;
  fallback_counts: Record<string, number>;
};
type Splits = Record<
  "train" | "tune" | "promotion" | "final_audit",
  [string, string]
>;
type Model = {
  algorithm: string;
  alpha: number | null;
  job_id: string;
  dataset_id: string;
  report: Record<string, Report>;
  measured_seconds: number;
  peak_rss_kib: number | null;
  feature_value_hash: string;
  artifact_load_verified: boolean;
  weights: { sha256: string };
  counts: Record<string, { included: number; excluded: number; days: number }>;
  splits: Splits;
};
type Prediction = {
  model_id: string;
  date: string;
  logical_cutoff: string;
  latest_feature_day: string;
  validation_only: boolean;
  feature_value_hash: string;
  weights_hash: string;
  points: {
    slot: number;
    predicted: number;
    actual: number | null;
    source_line: number | null;
  }[];
  scores: Score;
};
type Feedback = {
  prediction_id: string;
  model_id: string;
  date: string;
  slot: number;
  reason: string;
  actor: string;
  training_eligible: boolean;
};
type Proposal = {
  feedback_id: string;
  model_id: string;
  dataset_id: string;
  alpha: number;
  incorporates_labels: boolean;
};
type Job = {
  id: string;
  state: string;
  dataset_id: string;
  parent_job_id: string | null;
  created_at: string;
  config: { alpha: number };
  detail: {
    stage?: string;
    error?: string;
    measured_seconds?: number;
    observed_exit_code?: number;
    models?: string[];
    completed_units?: number;
  };
};
type Event = {
  subject_id: string;
  state: string;
  created_at: string;
  detail: Record<string, unknown>;
};
type Overview = {
  splits: Splits;
  policy: { promotion_gate: string; actor_verification: string };
  active: {
    state: string;
    detail: { model_id?: string; previous_model_id?: string };
  };
  worker: { state: string; updated_at?: string; detail: { pid?: number } };
  monitor: {
    state: string;
    updated_at?: string;
    detail: { source_hash?: string; date_end?: string; error?: string };
  };
  datasets: Entity<{ splits: Splits; source_rows: number }>[];
  models: Entity<Model>[];
  jobs: Job[];
  feedback: Entity<Feedback>[];
  proposals: Entity<Proposal>[];
  predictions: Entity<Prediction>[];
  audits: Entity<{ model_id: string; report: Record<string, Report> }>[];
  events: Event[];
};
type Command = {
  action: string;
  object_id?: string;
  source_hash?: string;
  alpha?: number;
  date?: string;
  validation_only?: boolean;
  slot?: number;
  idempotency_key?: string;
};
const names: Record<string, string> = {
  ridge: "Ridge 训练模型",
  seasonal_naive_d2: "D−2 同时段基线",
  seasonal_naive_d7: "D−7 同时段基线",
  train_weekday_slot_median: "训练集星期 / 时段中位数",
};
const states: Record<string, string> = {
  queued: "排队",
  claimed: "已领取",
  started: "进程已启动",
  preparing: "准备样本",
  training: "拟合权重",
  evaluating: "评估",
  child_complete: "等待退出确认",
  succeeded: "成功",
  failed: "失败",
  cancelled: "已取消",
  cancel_requested: "正在取消",
  interrupted: "被中断",
  unknown_exit: "退出未确认",
  evaluated: "已评估",
  shadow: "影子验证",
  research_active: "研究主版本",
  retired: "已退役",
  rejected: "已拒绝",
  submitted: "待确认",
  confirmed: "已确认",
  registered: "已登记",
  ready: "可执行",
  consumed: "已完成",
};
const done = new Set([
  "succeeded",
  "failed",
  "cancelled",
  "interrupted",
  "unknown_exit",
]);
const short = (s?: string) => (s ? s.slice(0, 14) : "—");
const clock = (slot: number) =>
  `${String(Math.floor(slot / 4)).padStart(2, "0")}:${String((slot % 4) * 15).padStart(2, "0")}`;

export default function LearningLoop({
  theme,
  revision,
}: {
  theme: Theme;
  revision: number;
}) {
  const [rev, setRev] = useState(0);
  const resource = useResource<Overview>(
    "/api/v1/ml/overview",
    `${revision}:${rev}`,
    5000,
  );
  const catalog = useResource<PublicCatalog>(
    "/api/v1/public-data/catalog",
    revision,
    30000,
  );
  const data = resource.data;
  const [actor, setActor] = useState(
    () => localStorage.getItem("cecep-research-actor") || "",
  );
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [alpha, setAlpha] = useState(1);
  const [modelId, setModelId] = useState(
    () => new URLSearchParams(location.search).get("ml_model") || "",
  );
  const [day, setDay] = useState(
    () => new URLSearchParams(location.search).get("ml_date") || "",
  );
  const [validation, setValidation] = useState(true);
  const [prediction, setPrediction] = useState<Entity<Prediction> | null>(null);
  const [slot, setSlot] = useState(48);
  const [feedbackId, setFeedbackId] = useState("");
  const [proposalId, setProposalId] = useState("");
  const [auditReady, setAuditReady] = useState(false);
  const [analysis, setAnalysis] = useState<Entity<{
    answer: string;
    llm_mode: string;
  }> | null>(null);
  const tuneStart = data?.splits.tune[0];
  const tuneEnd = data?.splits.tune[1];
  const inTune = !!tuneStart && !!tuneEnd && day >= tuneStart && day <= tuneEnd;
  useEffect(() => {
    if (tuneStart && tuneEnd) setValidation(day >= tuneStart && day <= tuneEnd);
  }, [day, tuneStart, tuneEnd]);
  useEffect(() => {
    if (!data) return;
    if (!day) setDay(data.splits.tune[1]);
    if (!modelId)
      setModelId(
        data.active.detail.model_id ||
          data.models.find((m) => m.payload.algorithm === "ridge")?.id ||
          "",
      );
  }, [data, day, modelId]);
  useEffect(() => {
    const url = new URL(location.href);
    if (modelId) url.searchParams.set("ml_model", modelId);
    if (day) url.searchParams.set("ml_date", day);
    history.replaceState(null, "", url);
    setPrediction(null);
    setAnalysis(null);
    setFeedbackId("");
    setProposalId("");
    setAuditReady(false);
  }, [modelId, day]);
  const model = data?.models.find((m) => m.id === modelId);
  const currentFeedback = data?.feedback.find((f) => f.id === feedbackId);
  const workerFresh =
    !!data?.worker.updated_at &&
    Date.now() - Date.parse(data.worker.updated_at) < 45000 &&
    ["ready", "busy"].includes(data.worker.state);
  const dataset = data?.datasets.find(
    (d) => d.source_hash === catalog.data?.metadata?.source_hash,
  );
  const needsIdentity = !actor.trim() || !reason.trim();
  async function act<T = unknown>(
    command: Command,
    success: string,
  ): Promise<T | null> {
    if (busy || needsIdentity) return null;
    setBusy(command.action);
    setError("");
    setMessage("");
    localStorage.setItem("cecep-research-actor", actor.trim());
    try {
      const result = await request<T>("/api/v1/ml/commands", {
        ...command,
        actor: actor.trim(),
        reason: reason.trim(),
      });
      setRev((v) => v + 1);
      setMessage(success);
      return result;
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
      return null;
    } finally {
      setBusy("");
    }
  }
  const blocked = !!busy || needsIdentity;
  const selectedReport = model?.payload.report.promotion;
  const activeModel = data?.models.find(
    (m) => m.id === data.active.detail.model_id,
  );
  const activePrediction =
    prediction &&
    prediction.payload.model_id === modelId &&
    prediction.payload.date === day
      ? prediction
      : null;
  const point = activePrediction?.payload.points[slot];
  return (
    <div className="learning-workspace">
      <div className="learning-heading">
        <div>
          <h1>模型训练与迭代</h1>
          <p>已有山东市场历史数据 · 实时电价日前预测 · 元/MWh</p>
        </div>
        <button disabled={!!busy} onClick={() => setRev((v) => v + 1)}>
          <RefreshCw size={16} />
          检查状态
        </button>
      </div>
      <p className="learning-boundary">
        研究用途。历史发布时间未经核验，采用
        historical_assumed；不代表岚能、凌光的生产能力。本站训练权重与源文件预测列分开记录。
      </p>
      <Status
        loading={resource.loading}
        error={resource.error || catalog.error}
      />
      {data && (
        <>
          <div className="learning-control-strip">
            <span className={`badge ${workerFresh ? "info" : "warning"}`}>
              {workerFresh ? "CPU 执行器在线" : "执行器心跳未就绪"}
            </span>
            <span>单任务 · 最多4线程 · 30分钟上限</span>
            <span>
              主版本：
              {activeModel
                ? names[activeModel.payload.algorithm] +
                  " · " +
                  short(activeModel.id)
                : "尚未初始化"}
            </span>
            <span>状态检查 {stamp(resource.checkedAt || "")}</span>
          </div>
          <p className="learning-help">
            源文件自动检查：
            {data.monitor.updated_at
              ? stamp(data.monitor.updated_at)
              : "等待首次检查"}{" "}
            · 覆盖至 {data.monitor.detail.date_end || "—"}
            。仅在文件版本变化时检查新记录并尝试主模型推理，不生成行情、不自动训练。
            {data.monitor.detail.error}
          </p>
          <Panel
            title="操作记录"
            subtitle="填写本次操作的身份与依据；当前身份为内网声明，尚未接入企业身份认证。"
          >
            <div className="learning-form">
              <label>
                操作人
                <input
                  autoComplete="name"
                  value={actor}
                  onChange={(e) => setActor(e.target.value)}
                  placeholder="姓名或员工标识"
                  maxLength={100}
                />
              </label>
              <label className="learning-reason">
                操作 / 复核依据
                <textarea
                  value={reason}
                  onChange={(e) => setReason(e.target.value)}
                  placeholder="说明启动训练、复核偏差或审批版本的依据"
                  maxLength={4000}
                  rows={2}
                />
              </label>
            </div>
            {needsIdentity && (
              <p className="learning-help">
                填完操作人与依据后，执行按钮才会启用。
              </p>
            )}
            {busy && <p role="status">正在执行：{busy}…</p>}
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
          </Panel>
          <Panel
            title="数据版本与训练任务"
            subtitle="参数调整复用冻结的数据集；缺失标签剔除并保存逐行清单。"
          >
            <div className="learning-actions">
              <span>
                当前源：
                <code>{short(catalog.data?.metadata?.source_hash)}</code> ·{" "}
                {catalog.data?.metadata?.row_count.toLocaleString()} 行
              </span>
              <button
                disabled={blocked || !catalog.data?.available}
                onClick={() =>
                  act(
                    {
                      action: "dataset",
                      source_hash: catalog.data?.metadata?.source_hash,
                    },
                    "数据版本已登记；尚未启动训练。",
                  )
                }
              >
                {dataset ? "核对已登记版本" : "登记当前数据版本"}
              </button>
              <label>
                Ridge α
                <select
                  value={alpha}
                  onChange={(e) => setAlpha(Number(e.target.value))}
                >
                  {[0.1, 1, 10, 100].map((a) => (
                    <option key={a}>{a}</option>
                  ))}
                </select>
              </label>
              <button
                className="primary"
                disabled={blocked || !dataset || !workerFresh}
                onClick={() =>
                  act(
                    {
                      action: "train",
                      object_id: dataset?.id,
                      alpha,
                      idempotency_key: crypto.randomUUID(),
                    },
                    "训练任务已排队；下表显示实际阶段。",
                  )
                }
              >
                <Play size={15} />
                开始训练
              </button>
            </div>
            <div className="learning-splits">
              {Object.entries(data.splits).map(([key, range]) => (
                <div key={key}>
                  <strong>
                    {
                      {
                        train: "训练",
                        tune: "调参",
                        promotion: "提升评估",
                        final_audit: "最终审计 · 封存",
                      }[key]
                    }
                  </strong>
                  <span>{range.join(" 至 ")}</span>
                </div>
              ))}
            </div>
            {!data.jobs.length ? (
              <p className="learning-empty">
                还没有训练任务。先登记版本，再启动首个候选。
              </p>
            ) : (
              <div className="table-scroll">
                <table>
                  <thead>
                    <tr>
                      <th>任务 / 提交时间</th>
                      <th>参数</th>
                      <th>实际状态</th>
                      <th>运行证据</th>
                      <th>操作</th>
                    </tr>
                  </thead>
                  <tbody>
                    {data.jobs.map((j) => (
                      <tr key={j.id}>
                        <td>
                          <code>{short(j.id)}</code>
                          <small>{stamp(j.created_at)}</small>
                        </td>
                        <td>α {j.config.alpha}</td>
                        <td>
                          {states[j.state] || j.state}
                          <small>{j.detail.stage || j.detail.error}</small>
                        </td>
                        <td>
                          {j.detail.measured_seconds !== undefined
                            ? `${fmt(j.detail.measured_seconds, 2)} 秒`
                            : "—"}
                          <small>
                            {j.detail.observed_exit_code !== undefined
                              ? `观测退出码 ${j.detail.observed_exit_code}`
                              : "尚无退出确认"}
                          </small>
                        </td>
                        <td>
                          {!done.has(j.state) ? (
                            <button
                              disabled={
                                blocked || j.state === "cancel_requested"
                              }
                              onClick={() =>
                                act(
                                  { action: "cancel", object_id: j.id },
                                  "已提交取消请求；以任务最终状态为准。",
                                )
                              }
                            >
                              取消任务
                            </button>
                          ) : (
                            j.state !== "succeeded" && (
                              <button
                                disabled={blocked || !workerFresh}
                                onClick={() =>
                                  act(
                                    {
                                      action: "retry",
                                      object_id: j.id,
                                      idempotency_key: crypto.randomUUID(),
                                    },
                                    "已创建独立重试，保留原失败记录。",
                                  )
                                }
                              >
                                创建重试
                              </button>
                            )
                          )}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </Panel>
          <div className="learning-columns">
            <div className="learning-main">
              <Panel
                title="候选比较与真实推理"
                subtitle="所有方法使用同一原始标签掩码；负价格与负预测均保留。"
              >
                <div className="learning-actions">
                  <label>
                    模型版本
                    <select
                      value={modelId}
                      onChange={(e) => setModelId(e.target.value)}
                    >
                      <option value="">选择已完成模型</option>
                      {data.models.map((m) => (
                        <option key={m.id} value={m.id}>
                          {names[m.payload.algorithm]} · {short(m.id)} ·{" "}
                          {states[m.state]}
                        </option>
                      ))}
                    </select>
                  </label>
                  <label>
                    预测交易日
                    <input
                      type="date"
                      value={day}
                      onChange={(e) => setDay(e.target.value)}
                    />
                  </label>
                </div>
                {model && (
                  <>
                    <div className="learning-actions">
                      <button
                        onClick={() => {
                          setDay(data.splits.tune[1]);
                          setValidation(true);
                        }}
                      >
                        使用调参集末日
                      </button>
                      <button
                        onClick={() => {
                          setDay(data.splits.promotion[1]);
                          setValidation(false);
                        }}
                      >
                        使用提升集末日
                      </button>
                      <label>
                        <input
                          type="checkbox"
                          checked={validation}
                          disabled={!inTune}
                          onChange={(e) => setValidation(e.target.checked)}
                        />
                        调参验证（不宣称独立测试）
                      </label>
                      <button
                        className="primary"
                        disabled={blocked || !day}
                        onClick={async () => {
                          const result = await act<Entity<Prediction>>(
                            {
                              action: "predict",
                              object_id: modelId,
                              date: day,
                              validation_only: validation,
                            },
                            "已加载已校验权重，保存96点真实推理。",
                          );
                          if (result) {
                            setPrediction(result);
                            setAnalysis(null);
                          }
                        }}
                      >
                        <Play size={15} />
                        运行96点推理
                      </button>
                    </div>
                    <p className="learning-help">
                      训练 /
                      选择边界见下方证据。选择最终审计日期前，必须先在右侧冻结唯一候选。
                    </p>
                    {selectedReport && (
                      <>
                        <h3>
                          提升集比较 · {selectedReport.days} 天 /{" "}
                          {selectedReport.rows.toLocaleString()} 条
                        </h3>
                        <div className="table-scroll">
                          <table>
                            <thead>
                              <tr>
                                <th>方法</th>
                                <th>MAE</th>
                                <th>RMSE</th>
                                <th>MBE</th>
                                <th>负价 MAE / 条数</th>
                              </tr>
                            </thead>
                            <tbody>
                              {Object.entries(selectedReport.scores).map(
                                ([name, score]) => (
                                  <tr key={name}>
                                    <td>{names[name]}</td>
                                    <td>{fmt(score.mae, 3)}</td>
                                    <td>{fmt(score.rmse, 3)}</td>
                                    <td>{fmt(score.mbe, 3)}</td>
                                    <td>
                                      {fmt(score.negative.mae, 3)} /{" "}
                                      {score.negative.n}
                                    </td>
                                  </tr>
                                ),
                              )}
                            </tbody>
                          </table>
                        </div>
                        <p className="learning-help">
                          Ridge − 基线的日配对 MAE
                          差（95%区间；7天移动块、2000次）：
                          {Object.entries(selectedReport.comparisons).map(
                            ([name, c]) => (
                              <span className="learning-comparison" key={name}>
                                {names[name]}：{fmt(c.delta_mae, 3)} [
                                {fmt(c.lower95, 3)}, {fmt(c.upper95, 3)}] ·{" "}
                                {c.conclusion === "improved"
                                  ? "支持改善"
                                  : c.conclusion === "worse"
                                    ? "支持更差"
                                    : "证据未定"}
                              </span>
                            ),
                          )}
                        </p>
                      </>
                    )}
                    <details>
                      <summary>模型与样本证据</summary>
                      <dl className="learning-evidence">
                        <dt>模型权重 SHA256</dt>
                        <dd>{model.payload.weights.sha256}</dd>
                        <dt>特征值 SHA256</dt>
                        <dd>{model.payload.feature_value_hash}</dd>
                        <dt>数据集版本</dt>
                        <dd>{model.payload.dataset_id}</dd>
                        <dt>重载校验</dt>
                        <dd>
                          {model.payload.artifact_load_verified
                            ? "通过"
                            : "未通过"}{" "}
                          · {fmt(model.payload.measured_seconds, 2)} 秒 ·{" "}
                          {model.payload.peak_rss_kib !== null
                            ? `${fmt(model.payload.peak_rss_kib / 1024)} MiB 峰值进程内存`
                            : "内存未记录"}
                        </dd>
                        {Object.entries(model.payload.counts).map(
                          ([name, count]) => (
                            <div key={name}>
                              <dt>{name}</dt>
                              <dd>
                                纳入 {count.included} · 剔除 {count.excluded} ·{" "}
                                {count.days} 天
                              </dd>
                            </div>
                          ),
                        )}
                      </dl>
                    </details>
                  </>
                )}
                {!model && (
                  <p className="learning-empty">
                    任务成功后，真实权重、基线分数和模型版本会出现在这里。
                  </p>
                )}
                {activePrediction && (
                  <div className="learning-prediction">
                    <h3>
                      {activePrediction.payload.date} ·{" "}
                      {activePrediction.payload.validation_only
                        ? "调参验证推理"
                        : "研究推理"}
                    </h3>
                    <p>
                      逻辑预测截止{" "}
                      {stamp(activePrediction.payload.logical_cutoff)} ·
                      特征最晚 {activePrediction.payload.latest_feature_day} ·
                      MAE {fmt(activePrediction.payload.scores.mae, 3)} 元/MWh
                    </p>
                    <Chart
                      label="真实模型96点电价推理与原始价格"
                      theme={theme}
                      onPoint={setSlot}
                      option={() => ({
                        ...baseOption(),
                        xAxis: {
                          ...baseOption().xAxis,
                          data: activePrediction.payload.points.map((p) =>
                            clock(p.slot),
                          ),
                        },
                        yAxis: {
                          ...baseOption().yAxis,
                          name: "元/MWh",
                          scale: true,
                        },
                        series: [
                          {
                            name: "本站模型推理",
                            type: "line",
                            symbol: "none",
                            data: activePrediction.payload.points.map(
                              (p) => p.predicted,
                            ),
                            lineStyle: { color: color("primary") },
                          },
                          {
                            name: "原始实际价格",
                            type: "line",
                            symbol: "none",
                            data: activePrediction.payload.points.map(
                              (p) => p.actual,
                            ),
                            lineStyle: {
                              color: color("success"),
                              type: "dashed",
                            },
                          },
                        ],
                      })}
                    />
                    <label>
                      复核时段
                      <select
                        value={slot}
                        onChange={(e) => setSlot(Number(e.target.value))}
                      >
                        {activePrediction.payload.points.map((p) => (
                          <option key={p.slot} value={p.slot}>
                            {clock(p.slot)}
                          </option>
                        ))}
                      </select>
                    </label>
                    <p>
                      源行 {point?.source_line || "缺失"} · 预测{" "}
                      {fmt(point?.predicted, 3)} · 实际 {fmt(point?.actual, 3)}{" "}
                      元/MWh
                    </p>
                    <button
                      disabled={blocked}
                      onClick={async () => {
                        const r = await act<Entity<Feedback>>(
                          {
                            action: "feedback",
                            object_id: activePrediction.id,
                            slot,
                          },
                          "复核已保存；尚未确认，不自动用于训练。",
                        );
                        if (r) setFeedbackId(r.id);
                      }}
                    >
                      <FileCheck2 size={15} />
                      保存此时段复核
                    </button>
                    <button
                      disabled={blocked}
                      onClick={async () => {
                        const r = await act<
                          Entity<{ answer: string; llm_mode: string }>
                        >(
                          { action: "analyze", object_id: activePrediction.id },
                          "分析已保存，数值与引用来自此条真实推理。",
                        );
                        if (r) setAnalysis(r);
                      }}
                    >
                      分析当前推理证据
                    </button>
                    {analysis && (
                      <div className="learning-answer">
                        <p className="learning-help">
                          智能体工具：注册 NumPy 电价模型 ·{" "}
                          {analysis.payload.llm_mode} · {short(analysis.id)}
                        </p>
                        <p>{analysis.payload.answer}</p>
                      </div>
                    )}
                  </div>
                )}
              </Panel>
            </div>
            <aside className="learning-side">
              <Panel
                title="复核与重训"
                subtitle="选择复核 → 人工确认 → 参数变更提案 → 独立训练任务。"
              >
                <label>
                  复核记录
                  <select
                    value={feedbackId}
                    onChange={(e) => {
                      setFeedbackId(e.target.value);
                      setProposalId("");
                    }}
                  >
                    <option value="">选择已保存复核</option>
                    {data.feedback.map((f) => (
                      <option key={f.id} value={f.id}>
                        {f.payload.date} {clock(f.payload.slot)} ·{" "}
                        {states[f.state]} · {short(f.id)}
                      </option>
                    ))}
                  </select>
                </label>
                {currentFeedback && (
                  <>
                    <p>{currentFeedback.payload.reason}</p>
                    <p className="learning-help">
                      {currentFeedback.payload.actor} · 原始标签不改写 ·
                      训练标签资格：否
                    </p>
                    <button
                      disabled={
                        blocked || currentFeedback.state !== "submitted"
                      }
                      onClick={() =>
                        act(
                          { action: "confirm", object_id: feedbackId },
                          "复核已确认，标签仍不自动进入训练。",
                        )
                      }
                    >
                      确认人工复核
                    </button>
                    <button
                      disabled={
                        blocked || currentFeedback.state !== "confirmed"
                      }
                      onClick={async () => {
                        const r = await act<Entity<Proposal>>(
                          { action: "proposal", object_id: feedbackId, alpha },
                          "已创建参数重训提案；保留同一数据集与隔离的提升窗口。",
                        );
                        if (r) setProposalId(r.id);
                      }}
                    >
                      创建 α={alpha} 重训提案
                    </button>
                    <p className="learning-help">
                      只接受调参窗口的反馈作为选参依据。提升窗口之后的意见需新的未来评估合同。
                    </p>
                  </>
                )}
                <label>
                  重训提案
                  <select
                    value={proposalId}
                    onChange={(e) => setProposalId(e.target.value)}
                  >
                    <option value="">选择提案</option>
                    {data.proposals.map((p) => (
                      <option key={p.id} value={p.id}>
                        α {p.payload.alpha} · {short(p.id)}
                      </option>
                    ))}
                  </select>
                </label>
                <button
                  className="primary"
                  disabled={blocked || !proposalId || !workerFresh}
                  onClick={() =>
                    act(
                      {
                        action: "train_proposal",
                        object_id: proposalId,
                        idempotency_key: crypto.randomUUID(),
                      },
                      "重训已排队，可在任务表查看实际进度。",
                    )
                  }
                >
                  执行所选重训提案
                </button>
              </Panel>
              <Panel
                title="研究审批与回滚"
                subtitle="首次初始化 D−2 基线；后续升级需同时通过 MAE 置信区间与 RMSE 门槛。"
              >
                <p>
                  选中：{model ? names[model.payload.algorithm] : "尚无模型"}
                  <br />
                  {short(modelId)} · {model ? states[model.state] : "—"}
                </p>
                <p className="learning-help">
                  审批只变更研究主版本。此公共数据合同始终禁止生产发布。
                </p>
                <div className="learning-stacked">
                  <button
                    disabled={blocked || !model}
                    onClick={() =>
                      act(
                        { action: "shadow", object_id: modelId },
                        "已进入研究影子验证，未替换主版本。",
                      )
                    }
                  >
                    设为影子版本
                  </button>
                  <button
                    className="primary"
                    disabled={blocked || !model}
                    onClick={() =>
                      act(
                        { action: "activate", object_id: modelId },
                        "已通过规则并更新研究主版本。",
                      )
                    }
                  >
                    按固定门槛审批
                  </button>
                  <button
                    disabled={blocked || !model}
                    onClick={() =>
                      act(
                        { action: "reject", object_id: modelId },
                        "已保存拒绝记录，当前研究主版本未变。",
                      )
                    }
                  >
                    拒绝此候选
                  </button>
                  <button
                    disabled={blocked || !data.active.detail.previous_model_id}
                    onClick={() =>
                      act(
                        {
                          action: "rollback",
                          object_id: data.active.detail.previous_model_id,
                        },
                        "已回滚实际主版本指针；可选主版本再次推理核对。",
                      )
                    }
                  >
                    <Undo2 size={15} />
                    回滚到上一主版本
                  </button>
                  <button
                    disabled={!activeModel}
                    onClick={() => {
                      if (activeModel) setModelId(activeModel.id);
                    }}
                  >
                    选择当前主版本核验
                  </button>
                </div>
                <details>
                  <summary>一次性最终审计</summary>
                  <p>
                    冻结当前 Ridge
                    权重后启封最终窗口。每个源版本仅允许一次；失败也消耗启封资格，后续选参不能再声称独立检验。
                  </p>
                  <label>
                    <input
                      type="checkbox"
                      checked={auditReady}
                      onChange={(e) => setAuditReady(e.target.checked)}
                    />
                    确认冻结此候选并消耗审计资格
                  </label>
                  <button
                    disabled={
                      blocked ||
                      !auditReady ||
                      model?.payload.algorithm !== "ridge"
                    }
                    onClick={() =>
                      act(
                        { action: "final_audit", object_id: modelId },
                        "最终审计已完成；结果追加保存，窗口不再是未见测试集。",
                      )
                    }
                  >
                    冻结并执行最终审计
                  </button>
                  {data.audits.map((a) => (
                    <p key={a.id}>
                      {short(a.payload.model_id)} · 最终 Ridge MAE{" "}
                      {fmt(a.payload.report.final_audit.scores.ridge.mae, 3)} ·{" "}
                      {a.payload.report.final_audit.rows} 条
                    </p>
                  ))}
                </details>
              </Panel>
            </aside>
          </div>
          <Panel
            title="数据流与操作证据"
            subtitle="源文件 → 冻结切片 → 任务 → 权重 → 预测 → 复核 → 重训 → 规则审批 / 回滚。"
          >
            <details>
              <summary>查看最近100条追加式事件</summary>
              <div className="table-scroll">
                <table>
                  <thead>
                    <tr>
                      <th>时间</th>
                      <th>对象</th>
                      <th>实际事件</th>
                      <th>证据详情</th>
                    </tr>
                  </thead>
                  <tbody>
                    {data.events.map((e, i) => (
                      <tr key={i}>
                        <td>{stamp(e.created_at)}</td>
                        <td>
                          <code>{short(e.subject_id)}</code>
                        </td>
                        <td>{states[e.state] || e.state}</td>
                        <td>
                          <details>
                            <summary>展开</summary>
                            <pre>{JSON.stringify(e.detail, null, 2)}</pre>
                          </details>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </details>
          </Panel>
        </>
      )}
    </div>
  );
}
