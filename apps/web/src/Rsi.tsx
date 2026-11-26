import BusinessFacts from "./BusinessFacts";
import {
  businessText,
  taskLabel,
  stateLabel,
  sourceLabel,
} from "./presentation";
import { useEffect, useState } from "react";
import {
  Check,
  BookPlus,
  RotateCcw,
  Rocket,
  ClipboardCheck,
} from "lucide-react";
import type { Scope, Rsi as RsiData } from "./types";
import { query, useResource, request, fmt, time, stamp } from "./api";
import { Panel, Status, Segments } from "./components";

export default function Rsi({
  scope,
  revision,
  onRefresh,
  draft,
  onSelect,
}: {
  scope: Scope;
  revision: number;
  onRefresh: () => void;
  draft: string;
  onSelect: (s: string) => void;
}) {
  const result = useResource<RsiData>(
    "/api/v1/workbench/rsi?" + query(scope),
    revision,
  );
  const [view, setView] = useState("review");
  const [caseId, setCaseId] = useState("");
  const [reason, setReason] = useState("");
  const [training, setTraining] = useState(false);
  const [approvalReason, setApprovalReason] = useState(
    "人工核验同口径演示评估后更新演示注册状态",
  );
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);
  const [draftConsumed, setDraftConsumed] = useState(false);
  const cases = result.data?.cases || [];
  const selected =
    cases.find((c) => c.case_id === caseId) ||
    cases.find((c) => c.interval_start === scope.selected_interval) ||
    cases[0];
  useEffect(() => {
    setReason((!draftConsumed && draft) || selected?.feedback?.reason || "");
    setTraining(!!selected?.feedback?.training_eligible);
  }, [
    selected?.case_id,
    selected?.feedback?.feedback_id,
    draft,
    draftConsumed,
  ]);
  useEffect(() => {
    setCaseId("");
    setView("review");
  }, [scope.station_id, scope.date]);
  async function act(path: string, body: unknown, success: string) {
    setBusy(true);
    setError("");
    setMessage("");
    try {
      await request(path, body);
      if (path.endsWith("/feedback")) setDraftConsumed(true);
      setMessage(success);
      onRefresh();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  return (
    <>
      <div className="notice">
        <ClipboardCheck size={18} />
        <p>
          人工复核 → 追加反馈 →
          确认后沉淀案例；模型审批与回滚写入不可变生命周期事件。当前所有候选均为未训练演示场景。
        </p>
      </div>
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
      <Status loading={result.loading} error={result.error} />
      <div className="presentation-metrics">
        <div>
          <span>待复核偏差</span>
          <strong>
            {result.data
              ? cases.filter((c) => c.effective_status !== "confirmed").length
              : "—"}
          </strong>
          <small>自动关联线索待人工确认</small>
        </div>
        <div>
          <span>已确认案例</span>
          <strong>
            {result.data
              ? cases.filter((c) => c.effective_status === "confirmed").length
              : "—"}
          </strong>
          <small>人工结论追加保存</small>
        </div>
        <div>
          <span>候选模型</span>
          <strong>{result.data?.candidates.length ?? "—"}</strong>
          <small>未训练演示版本</small>
        </div>
        <div>
          <span>生命周期事件</span>
          <strong>{result.data?.lifecycle.length ?? "—"}</strong>
          <small>审批与回滚均可追溯</small>
        </div>
      </div>
      <Segments
        label="偏差审核视图"
        value={view}
        onChange={setView}
        options={[
          ["review", "偏差复核"],
          ["models", "候选模型与审批"],
          ["audit", "生命周期审计"],
        ]}
      />
      {view === "review" && (
        <Panel
          title="偏差归因与人工复核"
          subtitle="自动线索仅提供关联，根因必须由审核人确认；合成±5%容量参考阈值"
        >
          {!result.loading && !cases.length ? (
            <Status empty />
          ) : (
            <div className="review-grid">
              <div className="case-list">
                {cases.map((c) => (
                  <button
                    className={`case-item ${selected?.case_id === c.case_id ? "active" : ""}`}
                    key={c.case_id}
                    onClick={() => {
                      setCaseId(c.case_id);
                      onSelect(c.interval_start);
                    }}
                  >
                    <div>
                      <strong>
                        {time(c.interval_start)} · {fmt(c.error_value)} MW
                      </strong>
                      <span
                        className={`badge ${c.effective_status === "confirmed" ? "success" : "warning"}`}
                      >
                        {c.effective_status === "confirmed"
                          ? "已确认"
                          : "待复核"}
                      </span>
                    </div>
                    <p>
                      实测 {fmt(c.actual_value)} / 预测 {fmt(c.predicted_value)}
                    </p>
                  </button>
                ))}
              </div>
              {selected && (
                <div className="review-form">
                  <div className="review-values">
                    <span>
                      时段 <strong>{time(selected.interval_start)}</strong>
                    </span>
                    <span>
                      实测 − 预测{" "}
                      <strong className="text-error">
                        {fmt(selected.error_value)} MW
                      </strong>
                    </span>
                  </div>
                  <section className="evidence">
                    <h3>天气与事件线索</h3>
                    <BusinessFacts
                      value={JSON.parse(selected.auto_clues_json)}
                    />
                    <p className="research-help">
                      这些线索尚不能确认因果，请人工核对。
                    </p>
                  </section>
                  {draft && (
                    <p className="warning-copy">
                      Agent 草稿仅供复核，请编辑为人工确认根因后保存。
                    </p>
                  )}
                  <label htmlFor="review-reason">人工确认根因</label>
                  <textarea
                    id="review-reason"
                    rows={5}
                    placeholder="结合原始数据、天气与调度记录填写复核结论"
                    value={reason}
                    onChange={(e) => setReason(e.target.value)}
                    maxLength={4000}
                  />
                  <label className="checkbox-label">
                    <input
                      type="checkbox"
                      checked={training}
                      onChange={(e) => setTraining(e.target.checked)}
                    />
                    确认该时段可纳入后续训练样本
                  </label>
                  <div className="review-actions">
                    <button
                      className="primary-button"
                      disabled={busy || !reason.trim()}
                      onClick={() =>
                        void act(
                          "/api/v1/rsi/feedback",
                          {
                            case_id: selected.case_id,
                            reason,
                            training_eligible: training,
                          },
                          "人工反馈已写入数据库，刷新后仍保留。",
                        )
                      }
                    >
                      <Check size={15} />
                      确认并保存复核
                    </button>
                    <button
                      disabled={
                        busy || !selected.feedback || !!selected.rag_doc_id
                      }
                      onClick={() =>
                        void act(
                          "/api/v1/rsi/rag-ingest",
                          { feedback_id: selected.feedback?.feedback_id },
                          "已确认案例已加入业务知识，可用于后续查询。",
                        )
                      }
                    >
                      <BookPlus size={15} />
                      {selected.rag_doc_id ? "已沉淀案例" : "保存为业务案例"}
                    </button>
                  </div>
                  {selected.feedback && <p className="muted">复核意见已保存</p>}
                </div>
              )}
            </div>
          )}
        </Panel>
      )}
      {view === "models" && (
        <Panel
          title="候选模型与审批"
          subtitle="审批只更新演示模型注册状态与展示主版本，未执行真实模型训练；上线与回滚均追加审计事件"
        >
          <div className="approval-reason">
            <label htmlFor="approval-reason">审批 / 回滚理由</label>
            <input
              id="approval-reason"
              value={approvalReason}
              onChange={(e) => setApprovalReason(e.target.value)}
              maxLength={4000}
            />
          </div>
          {!result.data?.candidates.length ? (
            <Status empty />
          ) : (
            result.data.candidates.map((c) => {
              const model = result.data?.models.find(
                (m) => m.model_version_id === c.candidate_model_version_id,
              );
              return (
                <div key={c.candidate_id} className="candidate-row">
                  <div>
                    <strong>
                      {model
                        ? `${model.model_name} · 第${model.version}版`
                        : "待审核模型"}
                    </strong>
                    <p>{businessText(c.hypothesis)}</p>
                    <small>基线与评估记录已关联保存</small>
                  </div>
                  <span className="badge info">
                    {stateLabel(model?.effective_status)}
                  </span>
                  <div className="head-tools">
                    <button
                      className="primary-button"
                      disabled={
                        busy ||
                        model?.effective_status === "production" ||
                        !approvalReason.trim()
                      }
                      onClick={() =>
                        void act(
                          "/api/v1/rsi/approve",
                          {
                            candidate_id: c.candidate_id,
                            action: "approve",
                            reason: approvalReason,
                          },
                          "候选审批已持久化，主版本与页面结果已刷新。",
                        )
                      }
                    >
                      <Rocket size={15} />
                      审批上线
                    </button>
                    <button
                      disabled={
                        busy ||
                        model?.effective_status !== "production" ||
                        !approvalReason.trim()
                      }
                      onClick={() =>
                        void act(
                          "/api/v1/rsi/approve",
                          {
                            candidate_id: c.candidate_id,
                            action: "rollback",
                            reason: approvalReason,
                          },
                          "已回滚至基线模型，生命周期事件已追加。",
                        )
                      }
                    >
                      <RotateCcw size={15} />
                      一键回滚
                    </button>
                  </div>
                </div>
              );
            })
          )}
          <div className="table-wrap">
            <table className="presentation-table">
              <thead>
                <tr>
                  <th>模型注册版本</th>
                  <th>任务</th>
                  <th>有效状态</th>
                  <th>训练状态</th>
                  <th>数据来源</th>
                </tr>
              </thead>
              <tbody>
                {result.data?.models.map((m) => (
                  <tr key={m.model_version_id}>
                    <td>
                      {m.model_name} v{m.version}
                    </td>
                    <td>{taskLabel(m.task)}</td>
                    <td>
                      <span
                        className={`badge ${m.effective_status === "production" ? "success" : ""}`}
                      >
                        {stateLabel(m.effective_status)}
                      </span>
                    </td>
                    <td>{m.trained ? "已训练" : "未训练 · 场景版本"}</td>
                    <td>{sourceLabel(m.source_mode)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Panel>
      )}
      {view === "audit" && (
        <Panel
          title="模型生命周期审计"
          subtitle="保留原注册记录，通过追加事件追溯每次晋升与回滚"
        >
          {!result.data?.lifecycle.length ? (
            <div className="empty-inline">
              尚无审批事件。审批操作成功后将在此展示。
            </div>
          ) : (
            <div className="table-wrap">
              <table className="presentation-table">
                <thead>
                  <tr>
                    <th>时间</th>
                    <th>模型</th>
                    <th>状态流转</th>
                    <th>人工理由</th>
                  </tr>
                </thead>
                <tbody>
                  {result.data.lifecycle.map((e) => (
                    <tr key={e.lifecycle_event_id}>
                      <td>{stamp(e.created_at)}</td>
                      <td>
                        {result.data?.models.find(
                          (m) => m.model_version_id === e.model_version_id,
                        )?.model_name || "研究模型"}
                      </td>
                      <td>
                        {stateLabel(e.from_status)} → {stateLabel(e.to_status)}
                      </td>
                      <td>{businessText(e.reason)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </Panel>
      )}
    </>
  );
}
