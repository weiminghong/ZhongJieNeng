import { useState } from "react";
import { ArrowRight, Database, RefreshCw, FileCheck2 } from "lucide-react";
import { useResource, fmt, stamp } from "./api";
import { Panel, Status } from "./components";
import { states } from "./LearningLoop";
import { recordLabel, stateLabel } from "./presentation";
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
  feedback: { id: string; state: string; display_name?: string }[];
  proposals: { id: string; state: string }[];
  versions: {
    id: string;
    display_name?: string;
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
  const context: Record<string, string> = f?.prediction
    ? {
        ml_prediction: f.prediction.id,
        ml_model: f.prediction.payload.model_id,
        ml_date: f.prediction.payload.date,
      }
    : f?.model
      ? { ml_model: f.model.id }
      : {};
  const versionName = (hash?: string) =>
    recordLabel(
      f?.versions.find((v) => v.source_hash === hash),
      "所选历史数据",
    );
  const stages = f
    ? [
        {
          title: "原始数据",
          value: recordLabel(f.archive, "等待收录"),
          detail: "保留每次使用的数据版本",
          tab: "raw",
          ready: !!f.archive,
        },
        {
          title: "训练数据",
          value: f.dataset
            ? `${fmt(f.model?.payload.counts.train.included, 0)} 条训练样本`
            : "尚未准备",
          detail: "训练与评估日期分别保留",
          tab: "learning",
          ready: !!f.dataset,
        },
        {
          title: "模型训练",
          value: f.job ? stateLabel(f.job.state) : "尚无任务",
          detail: recordLabel(f.job, "等待训练"),
          tab: "monitor",
          ready: f.job?.state === "succeeded",
        },
        {
          title: "预测模型",
          value: recordLabel(f.model, "尚无模型"),
          detail: f.model?.payload.artifact_load_verified
            ? "已完成加载与预测检查"
            : "等待模型检查",
          tab: "learning",
          ready: !!f.model?.payload.artifact_load_verified,
        },
      ]
    : [];
  return (
    <div className="research-page">
      <div className="research-intro">
        <div>
          <h2>数据流与版本</h2>
          <p>查看数据如何用于训练、预测、实际值核对和人工复核。</p>
        </div>
        <button onClick={() => setRev((v) => v + 1)}>
          <RefreshCw size={16} />
          检查最新进展
        </button>
      </div>
      <Status loading={resource.loading} error={resource.error} />
      {f && (
        <>
          <div className="research-context">
            <Database size={22} />
            <div>
              <strong>
                {f.current_source.metadata?.name || "尚未接入数据"}
              </strong>
              <span>
                {f.current_source.metadata?.date_start} 至{" "}
                {f.current_source.metadata?.date_end} ·{" "}
                {fmt(f.current_source.metadata?.row_count, 0)} 条历史记录
              </span>
            </div>
            <span className="badge info">项目已有数据</span>
            <span>最近检查 {stamp(f.monitor.updated_at || f.checked_at)}</span>
          </div>
          <p className="research-help">
            原始发布时间尚未核验，当前用于历史研究。数据文件真正变化后才增加版本，不生成模拟行情。
          </p>
          <Panel
            title="从数据到模型"
            subtitle="点击相应步骤，继续查看数据、训练任务或模型。"
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
                      className={`badge ${s.ready ? "success" : "warning"}`}
                    >
                      {s.ready ? "已就绪" : "待完成"}
                    </span>
                    <strong>{s.title}</strong>
                    <span>{s.value}</span>
                    <small>{s.detail}</small>
                  </button>
                  {i < stages.length - 1 && (
                    <ArrowRight size={18} aria-hidden="true" />
                  )}
                </div>
              ))}
            </div>
          </Panel>
          <div className="research-two-grid">
            <Panel
              title="预测与实际值核对"
              subtitle="预测结果保留不变，新的实际值另行核对。"
            >
              {f.prediction ? (
                <>
                  <dl className="research-facts">
                    <div>
                      <dt>所选预测</dt>
                      <dd>
                        {f.prediction.payload.date} ·{" "}
                        {recordLabel(f.prediction, "已保存预测")}
                      </dd>
                    </div>
                    <div>
                      <dt>预测使用数据</dt>
                      <dd>{versionName(f.prediction.source_hash)}</dd>
                    </div>
                    <div>
                      <dt>保存时的平均误差</dt>
                      <dd>
                        {fmt(f.prediction.payload.scores.mae, 3)} 元/MWh ·{" "}
                        {f.prediction.payload.scores.n}/96 条实际值
                      </dd>
                    </div>
                    <div>
                      <dt>最新核对数据</dt>
                      <dd>
                        {f.observation
                          ? versionName(
                              f.observation.payload.observation_source_hash,
                            )
                          : "等待核对"}
                      </dd>
                    </div>
                    <div>
                      <dt>最新核对平均误差</dt>
                      <dd>
                        {f.observation
                          ? `${fmt(f.observation.payload.scores.mae, 3)} 元/MWh · ${f.observation.payload.observed_points}/96 条实际值`
                          : "尚无核对结果"}
                      </dd>
                    </div>
                    <div>
                      <dt>实际值变化</dt>
                      <dd>
                        {f.observation
                          ? `${f.observation.payload.changed_from_snapshot} 个时段发生变化`
                          : "等待核对"}
                      </dd>
                    </div>
                  </dl>
                  <p className="research-help">
                    新实际值与原来预测逐时段匹配，原结果和原评估保持不变。
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
                  完成一次预测后，这里显示预测与实际值的对应关系。
                </p>
              )}
            </Panel>
            <Panel
              title="复核与模型更新"
              subtitle="人工意见绑定具体预测，更新模型需经过审核。"
            >
              <div className="data-flow-review">
                <FileCheck2 size={28} />
                <strong>{f.feedback.length} 条复核记录</strong>
                <span>{f.proposals.length} 条重训提案</span>
              </div>
              <p className="research-help">
                确认复核意见后，可提出重训，再比较新旧模型。原始实际值不因人工意见而改写。
              </p>
              {f.feedback.map((x) => (
                <button
                  key={x.id}
                  onClick={() =>
                    navigate("rsi", { ...context, ml_feedback: x.id })
                  }
                >
                  {recordLabel(x, "已保存复核")} ·{" "}
                  {states[x.state] || stateLabel(x.state)}
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
            title="已保留的数据版本"
            subtitle="每个版本分别保存，便于查看和复现历史结果。"
          >
            <div className="table-scroll">
              <table>
                <thead>
                  <tr>
                    <th>数据版本</th>
                    <th>记录数</th>
                    <th>覆盖日期</th>
                    <th>文件大小</th>
                    <th>收录时间</th>
                  </tr>
                </thead>
                <tbody>
                  {f.versions.map((v) => (
                    <tr key={v.id}>
                      <td>{recordLabel(v, "历史数据")}</td>
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
              <p className="research-empty">尚未收录数据版本。</p>
            )}
          </Panel>
        </>
      )}
    </div>
  );
}
