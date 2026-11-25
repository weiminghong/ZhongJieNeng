import { useState } from "react";
import { ArrowRight, Database, RefreshCw, FileCheck2 } from "lucide-react";
import { useResource, fmt, stamp } from "./api";
import { Panel, Status } from "./components";
import { names, states } from "./LearningLoop";
import type {
  Entity,
  Model,
  Prediction,
  Overview,
  Score,
} from "./LearningLoop";
import type { PublicCatalog } from "./publicTypes";
import type { NavigateResearch } from "./ResearchPages";

type Match = {
  prediction_id: string;
  date: string;
  input_source_hash: string;
  observation_source_hash: string;
  observed_points: number;
  changed_from_snapshot: number;
  scores: Score;
  checked_at: string;
  notice: string;
  points: {
    slot: number;
    actual: number | null;
    predicted: number;
    source_line: number | null;
  }[];
};
type Flow = {
  current_source: PublicCatalog;
  monitor: Overview["monitor"];
  model: Entity<Model> | null;
  dataset: Entity<{ source_rows: number }> | null;
  job: Overview["jobs"][number] | null;
  archive: Entity<{
    archive: { sha256: string; bytes: number };
    ingested_at: string;
  }> | null;
  prediction: Entity<Prediction> | null;
  observation: Entity<Match> | null;
  feedback: { id: string; state: string }[];
  proposals: { id: string; state: string }[];
  versions: {
    id: string;
    source_hash: string;
    rows: number;
    date_start: string;
    date_end: string;
    bytes: number;
    ingested_at: string;
  }[];
  checked_at: string;
  source_policy: string;
};
const short = (v?: string) => (v ? v.slice(0, 16) : "—");
export default function DataFlow({
  revision,
  navigate,
}: {
  revision: number;
  navigate: NavigateResearch;
}) {
  const params = new URLSearchParams(location.search);
  const query = new URLSearchParams();
  if (params.get("ml_prediction"))
    query.set("prediction_id", params.get("ml_prediction")!);
  else if (params.get("ml_model"))
    query.set("model_id", params.get("ml_model")!);
  const [rev, setRev] = useState(0);
  const resource = useResource<Flow>(
    "/api/v1/research/flow?" + query,
    `${revision}:${rev}`,
    5000,
  );
  const f = resource.data;
  const schema = useResource<{
    version: number;
    tables: {
      name: string;
      role: string;
      rows: number;
      foreign_keys: { from: string; table: string; to: string }[];
      columns: { name: string; type: string }[];
    }[];
    foreign_key_errors: unknown[];
    storage_policy: string;
  }>("/api/v1/research/schema", `${revision}:${rev}`);
  const context: Record<string, string> = f?.prediction
    ? {
        ml_prediction: f.prediction.id,
        ml_model: f.prediction.payload.model_id,
        ml_date: f.prediction.payload.date,
      }
    : f?.model
      ? { ml_model: f.model.id }
      : {};
  const stages = f
    ? [
        {
          title: "原始数据归档",
          value: f.archive
            ? `${fmt(f.archive.payload.archive.bytes / 1024 / 1024, 2)} MB 已固定`
            : "等待首次归档",
          id: f.archive?.id,
          detail: `源 ${short(f.model?.source_hash || f.current_source.metadata?.source_hash)}`,
          tab: "raw",
          state: !!f.archive,
        },
        {
          title: "冻结训练切片",
          value: f.dataset
            ? `${fmt(f.model?.payload.counts.train.included, 0)} 条训练标签`
            : "尚未登记",
          id: f.dataset?.id,
          detail: "原始行清单、排除原因与划分随版本保存",
          tab: "learning",
          state: !!f.dataset,
        },
        {
          title: "真实训练任务",
          value: f.job ? states[f.job.state] || f.job.state : "尚无任务",
          id: f.job?.id,
          detail:
            f.job?.detail.observed_exit_code !== undefined
              ? `观测退出码 ${f.job.detail.observed_exit_code}`
              : "没有观测到退出时，不标为成功",
          tab: "monitor",
          state: f.job?.state === "succeeded",
        },
        {
          title: "已保存模型权重",
          value: f.model
            ? names[f.model.payload.algorithm] || f.model.payload.algorithm
            : "尚无模型",
          id: f.model?.id,
          detail: f.model?.payload.artifact_load_verified
            ? "加载与推理已校验"
            : "等待产物校验",
          tab: "learning",
          state: !!f.model?.payload.artifact_load_verified,
        },
      ]
    : [];
  return (
    <div className="research-page">
      <div className="research-intro">
        <div>
          <h2>数据流与版本</h2>
          <p>从我们自己的原始记录，追到训练、预测，再核对后续实际值。</p>
        </div>
        <button onClick={() => setRev((v) => v + 1)}>
          <RefreshCw size={16} />
          检查数据链
        </button>
      </div>
      <Status loading={resource.loading} error={resource.error} />
      {f && (
        <>
          <div className="research-context">
            <Database size={22} />
            <div>
              <strong>
                {f.current_source.metadata?.name || "已有数据源未配置"}
              </strong>
              <span>
                {f.current_source.metadata?.date_start} 至{" "}
                {f.current_source.metadata?.date_end} ·{" "}
                {fmt(f.current_source.metadata?.row_count, 0)} 条原始数据
              </span>
            </div>
            <span className="badge info">本项目既有数据</span>
            <span>系统检查 {stamp(f.monitor.updated_at || f.checked_at)}</span>
          </div>
          <p className="research-help">
            {f.source_policy}{" "}
            文件覆盖时间与系统归档时间分开；历史发布时间未经核验，仍采用
            historical_assumed。
          </p>
          <Panel
            title="训练链路"
            subtitle="每个节点读取真实记录。点击节点查看对应数据、任务或模型；查看页面不会启动训练。"
          >
            <div className="data-flow-stages">
              {stages.map((s, i) => (
                <div className="data-flow-stage-wrap" key={s.title}>
                  <button
                    className="data-flow-stage"
                    onClick={() =>
                      navigate(s.tab, {
                        ...context,
                        ...(s.tab === "raw" && f.archive
                          ? { view_source: f.archive.source_hash }
                          : {}),
                        ...(s.tab === "monitor" && f.job
                          ? { job: f.job.id }
                          : {}),
                      })
                    }
                  >
                    <span
                      className={`badge ${s.state ? "success" : "warning"}`}
                    >
                      {s.state ? "有证据" : "待完成"}
                    </span>
                    <strong>{s.title}</strong>
                    <span>{s.value}</span>
                    <code>{short(s.id)}</code>
                    <small>{s.detail}</small>
                  </button>
                  {i < stages.length - 1 && (
                    <ArrowRight size={18} aria-hidden="true" />
                  )}
                </div>
              ))}
            </div>
            <details className="data-flow-proof">
              <summary>输入与权重的完整版本凭据</summary>
              <p>训练源 SHA256：{f.model?.source_hash || "—"}</p>
              <p>权重 SHA256：{f.model?.payload.weights.sha256 || "—"}</p>
              <p>
                训练归档时间：
                {f.archive ? stamp(f.archive.payload.ingested_at) : "未归档"}
              </p>
              <p>归档不会重写旧记录的历史到达时间。</p>
            </details>
          </Panel>
          <div className="research-two-grid">
            <Panel
              title="预测与实际值核对"
              subtitle="旧预测固定保存；实际值来自哪个新版本，另外追加记录。"
            >
              {f.prediction ? (
                <>
                  <dl className="research-facts">
                    <div>
                      <dt>所选预测</dt>
                      <dd>
                        {f.prediction.payload.date} · {f.prediction.id}
                      </dd>
                    </div>
                    <div>
                      <dt>预测输入版本</dt>
                      <dd>{f.prediction.source_hash}</dd>
                    </div>
                    <div>
                      <dt>原快照 MAE</dt>
                      <dd>
                        {fmt(f.prediction.payload.scores.mae, 3)} 元/MWh ·{" "}
                        {f.prediction.payload.scores.n}/96 条标签
                      </dd>
                    </div>
                    <div>
                      <dt>最新观测版本</dt>
                      <dd>
                        {f.observation?.payload.observation_source_hash ||
                          "等待后台核对"}
                      </dd>
                    </div>
                    <div>
                      <dt>最新核对 MAE</dt>
                      <dd>
                        {f.observation
                          ? `${fmt(f.observation.payload.scores.mae, 3)} 元/MWh · ${f.observation.payload.observed_points}/96 条标签`
                          : "尚无追加核对结果"}
                      </dd>
                    </div>
                    <div>
                      <dt>相对快照变化</dt>
                      <dd>
                        {f.observation
                          ? `${f.observation.payload.changed_from_snapshot} 个实际值变化`
                          : "未核对"}
                      </dd>
                    </div>
                  </dl>
                  <p className="research-help">
                    {f.observation?.payload.notice ||
                      "已有历史数据先做版本核对；只有真实文件变化，才会出现新的观测版本。不会凭空生成实时数据。"}
                  </p>
                  <button
                    className="primary-button"
                    onClick={() =>
                      navigate("forecast", {
                        ...context,
                        actual_basis: "latest",
                      })
                    }
                  >
                    在图表上核对
                    <ArrowRight size={15} />
                  </button>
                </>
              ) : (
                <p className="research-empty">
                  该模型尚无保存的预测。完成推理后，这里才显示预测与实测的对应关系。
                </p>
              )}
            </Panel>
            <Panel
              title="复核到重训"
              subtitle="人工意见与真实预测绑定；不把备注自动变成训练标签。"
            >
              <div className="data-flow-review">
                <FileCheck2 size={28} />
                <strong>{f.feedback.length} 条关联复核</strong>
                <span>{f.proposals.length} 条关联重训提案</span>
              </div>
              <p className="research-help">
                复核确认 → 明确变更提案 → 独立训练任务 → 同口径评估 →
                人工审批。原始标签不改写，旧评估不被新结果覆盖。
              </p>
              {f.feedback.map((x) => (
                <button
                  key={x.id}
                  onClick={() =>
                    navigate("rsi", { ...context, ml_feedback: x.id })
                  }
                >
                  {short(x.id)} · {states[x.state] || x.state}
                </button>
              ))}
              {f.prediction && (
                <button onClick={() => navigate("rsi", context)}>
                  继续复核或审批
                  <ArrowRight size={15} />
                </button>
              )}
            </Panel>
          </div>
          <Panel
            title="已保留的原始数据版本"
            subtitle="归档在GB10，按实际文件哈希保存；没有新文件时，版本数不增加。"
          >
            <div className="table-scroll">
              <table>
                <thead>
                  <tr>
                    <th>数据版本</th>
                    <th>记录数</th>
                    <th>源文件覆盖</th>
                    <th>大小</th>
                    <th>本系统归档时间</th>
                  </tr>
                </thead>
                <tbody>
                  {f.versions.map((v) => (
                    <tr key={v.id}>
                      <td>
                        <code>{v.source_hash}</code>
                      </td>
                      <td>{fmt(v.rows, 0)}</td>
                      <td>
                        {v.date_start} 至 {v.date_end}
                      </td>
                      <td>{fmt(v.bytes / 1024 / 1024, 2)} MB</td>
                      <td>{stamp(v.ingested_at)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            {!f.versions.length && (
              <p className="research-empty">
                后台尚未归档。旧文件无法追溯时会明确显示缺口，不用当前文件替代。
              </p>
            )}
          </Panel>
        </>
      )}
      <Panel
        title="数据库表与关联"
        subtitle="直接读取数据库当前结构和行数。每条记录通过外键指向所属版本，不仅在界面上连线。"
      >
        <Status loading={schema.loading} error={schema.error} />
        {schema.data && (
          <>
            <p className="research-help">
              库版本 {schema.data.version} · 外键检查{" "}
              {schema.data.foreign_key_errors.length === 0
                ? "通过"
                : "存在异常"}
              。{schema.data.storage_policy}
            </p>
            <div className="table-scroll">
              <table>
                <thead>
                  <tr>
                    <th>业务内容</th>
                    <th>实际表名</th>
                    <th>记录数</th>
                    <th>关系与字段</th>
                  </tr>
                </thead>
                <tbody>
                  {schema.data.tables.map((t) => (
                    <tr key={t.name}>
                      <td>{t.role}</td>
                      <td>
                        <code>{t.name}</code>
                      </td>
                      <td>{t.rows}</td>
                      <td>
                        <details>
                          <summary>
                            {t.foreign_keys.length} 个外键 · {t.columns.length}{" "}
                            个字段
                          </summary>
                          {t.foreign_keys.map((fk, i) => (
                            <p key={i}>
                              {fk.from} → {fk.table}.{fk.to}
                            </p>
                          ))}
                          <p>
                            {t.columns
                              .map((c) => `${c.name} (${c.type})`)
                              .join(" · ")}
                          </p>
                        </details>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </>
        )}
      </Panel>
    </div>
  );
}
