import { useState } from "react";
import { fmt, request, stamp, useResource } from "./api";
import { Panel, Status } from "./components";
import { businessText } from "./presentation";
import type { BusinessPlan, BusinessPrediction, BusinessSettlement } from "./businessTypes";

type Issue = { id: string; name: string; plan_id: string; settlement_id: string | null; slot: number | null; category: string; category_name: string; reason: string; actor: string; owner: string; state: string; state_name: string; evidence: string; verification: { notice?: string; outcome?: string; delta?: number; unit?: string; before?: number; after?: number; improved?: boolean } | null; history: { name?: string; state_name?: string; actor?: string; reason?: string; created_at?: string }[] };
export default function BusinessReview({ source, date, plan, predictions, settlements, comparisonSettlements, actor, reason, revision, analyze, modelReview }: {
  source: string; date: string; plan: BusinessPlan; predictions: BusinessPrediction[]; settlements: BusinessSettlement[]; comparisonSettlements: BusinessSettlement[]; actor: string; reason: string; revision: string; analyze: (issue: Issue) => void; modelReview: () => void;
}) {
  const [localRevision, setLocalRevision] = useState(0);
  const [selected, setSelected] = useState("");
  const [settlement, setSettlement] = useState("");
  const [category, setCategory] = useState("unknown");
  const [owner, setOwner] = useState("");
  const [evidence, setEvidence] = useState("");
  const [comparison, setComparison] = useState("");
  const [verificationKind, setVerificationKind] = useState("settlement_comparison");
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  const scope = new URLSearchParams({ source_key: source, trading_date: date, plan_id: plan.id });
  const resource = useResource<{ records: Issue[]; categories: { key: string; name: string }[] }>("/api/v1/business/reviews?" + scope, `${revision}:${localRevision}`, 10000);
  const current = resource.data?.records.find((i) => i.id === selected);
  const canWrite = actor.trim() && reason.trim() && !busy;
  const comparisons = comparisonSettlements.filter((s) => s.id !== current?.settlement_id);
  async function act(action: string) {
    setBusy(true); setMessage(""); setError("");
    try {
      const saved = await request<Issue>("/api/v1/business/review-commands", { action, source_key: source, date, plan_id: plan.id, issue_id: action === "create" ? undefined : current?.id, settlement_id: action === "create" ? settlement || null : current?.settlement_id, category, actor: actor.trim(), reason: reason.trim(), owner: owner.trim(), evidence: evidence.trim(), ...(action === "verify" ? { verification: { kind: verificationKind, comparison_object_id: comparison } } : {}) });
      setSelected(saved.id);
      if (action === "create") { setVerificationKind(saved.category === "model" ? "prediction_comparison" : "settlement_comparison"); setComparison(""); }
      setMessage("处理记录已保存，请以更新后的处理状态与验证结果为准。");
      setLocalRevision((v) => v + 1);
    } catch (e) { setError(businessText((e as Error).message)); }
    finally { setBusy(false); }
  }
  return <>
    <Panel title="新增偏差处理项" subtitle="先区分数据、事件、模型或申报策略问题，再记录负责人和处理依据；人工意见不会自动成为训练标签。">
      <div className="business-form-grid">
        <label>关联本次结算<select value={settlement} onChange={(e) => setSettlement(e.target.value)}><option value="">暂不关联结算</option>{settlements.map((s) => <option key={s.id} value={s.id}>{businessText(s.name)}</option>)}</select></label>
        <label>问题分类<select value={category} onChange={(e) => setCategory(e.target.value)}>{(resource.data?.categories || []).map((c) => <option key={c.key} value={c.key}>{c.name}</option>)}</select></label>
        <label>处理负责人<input value={owner} onChange={(e) => setOwner(e.target.value)} placeholder="填写负责人" /></label>
      </div>
      <button className="primary-button" disabled={!canWrite} onClick={() => void act("create")}>保存新的处理项</button>
      <p className="research-help">使用本页上方的操作人与依据。需要通过金额对照验证的问题，请先绑定原结算版本。</p>
    </Panel>
    <Panel title="处理、证据与验证">
      <Status loading={resource.loading} error={resource.error} />
      {error && <p className="state error" role="alert">操作未完成：{businessText(error)}。处理证据保留，请核对后重试。</p>}
      {message && <p className="inline-success" role="status">{message}</p>}
      <div className="research-filters"><label>选择处理项<select aria-label="选择偏差处理项" value={current?.id || ""} onChange={(e) => { setSelected(e.target.value); setEvidence(""); setComparison(""); setVerificationKind(resource.data?.records.find((i) => i.id === e.target.value)?.category === "model" ? "prediction_comparison" : "settlement_comparison"); }}><option value="">请选择处理项</option>{resource.data?.records.map((i) => <option key={i.id} value={i.id}>{businessText(i.name)} · {i.category_name} · {i.state_name}</option>)}</select></label></div>
      {!resource.loading && !resource.error && !resource.data?.records.length && <p className="research-empty">当前方案暂无偏差处理项。</p>}
      {current && <>
        <dl className="unified-source-facts"><div><dt>当前状态</dt><dd>{current.state_name}</dd></div><div><dt>分类</dt><dd>{current.category_name}</dd></div><div><dt>负责人</dt><dd>{businessText(current.owner || "尚未指定")}</dd></div><div><dt>发现依据</dt><dd>{businessText(current.reason)}</dd></div></dl>
        <div className="business-form-grid"><label className="business-form-wide">本次处理证据<textarea rows={3} value={evidence} onChange={(e) => setEvidence(e.target.value)} placeholder="记录检查结果、实际处理和可核对的证据" /></label>
          {current.category === "model" && <label>验证口径<select value={verificationKind} onChange={(e) => { setVerificationKind(e.target.value); setComparison(""); }}><option value="prediction_comparison">比较同日预测误差</option><option value="settlement_comparison">比较同日结算净额</option></select></label>}
          {verificationKind === "prediction_comparison" ? <label className="business-form-wide">用于验证的新预测<select aria-label="用于验证的新预测" value={comparison} onChange={(e) => setComparison(e.target.value)}><option value="">请选择同日同任务的新保存预测</option>{predictions.filter((p) => p.task === plan.task && p.record_id !== plan.record_id).map((p) => <option key={p.id} value={p.record_id}>{businessText(p.name)}</option>)}</select></label> : <label className="business-form-wide">用于验证的其他结算<select aria-label="用于验证的其他结算" value={comparison} onChange={(e) => setComparison(e.target.value)}><option value="">请选择同日结算作为处理后对照</option>{comparisons.map((s) => <option key={s.id} value={s.id}>{businessText(s.name)} · {stamp(s.created_at)}</option>)}</select></label>}
        </div>
        <div className="research-filters">
          <button disabled={!canWrite || current.state !== "pending"} onClick={() => void act("start")}>开始处理</button>
          <button disabled={!canWrite || current.state !== "in_progress" || !evidence.trim()} onClick={() => void act("resolve")}>保存处理证据</button>
          <button disabled={!canWrite || current.state !== "resolved" || (verificationKind === "settlement_comparison" && !current.settlement_id) || !comparison} onClick={() => void act("verify")}>按所选对照验证效果</button>
          <button disabled={!canWrite || !["resolved", "verified"].includes(current.state)} onClick={() => void act("reopen")}>重新打开处理</button>
          <button onClick={() => analyze(current)}>请智能体分析这个处理项</button>
          {current.category === "model" && <button onClick={modelReview}>转模型复核与真实重训</button>}
        </div>
        <p className="research-help">验证会检查是否为同一实际观测、同一小时和同一规则；可比性不足将拒绝。无改善也会如实记录，不因保存证据自动宣称问题已解决。</p>
        {current.evidence && <p>已保存处理证据：{businessText(current.evidence)}</p>}
        {current.verification && <div className="business-verification"><p>验证结果：{current.verification.improved ? "对照结果有改善" : "对照结果未改善"} · 原结果 {fmt(current.verification.before, 2)} / 对照结果 {fmt(current.verification.after, 2)} {current.verification.unit || "元"}</p><p>对照差额 {fmt(current.verification.delta, 2)} {current.verification.unit || "元"}。{businessText(current.verification.notice || "")}</p></div>}
        {!!current.history.length && <div className="business-history">{current.history.map((h, i) => <article className="unified-review-history" key={i}><h3>{businessText(h.state_name || h.name || "处理记录")}</h3><p>{businessText(h.reason || "")}</p><small>{businessText(h.actor || "")}{h.created_at ? " · " + stamp(h.created_at) : ""}</small></article>)}</div>}
      </>}
    </Panel>
  </>;
}
