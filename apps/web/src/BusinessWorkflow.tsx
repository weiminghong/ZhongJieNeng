import { requestKey } from "./requestKey";
import { useEffect, useRef, useState } from "react";
import { fmt, request, stamp, useResource } from "./api";
import { Panel, Status } from "./components";
import { businessText } from "./presentation";
import BusinessPlanForm, { defaultPlanParameters } from "./BusinessPlanForm";
import BusinessSettlementView from "./BusinessSettlementView";
import BusinessReview from "./BusinessReview";
import BusinessSeriesChart from "./BusinessSeriesChart";
import type { Theme } from "./types";
import type { BusinessCatalog, BusinessPlan, BusinessPrediction, BusinessSettlement, PlanParameters } from "./businessTypes";
import type { Selection } from "./workspaceState";

type Stage = "plan" | "settlement" | "review";
export default function BusinessWorkflow({ selection: s, stage, revision, theme, bindPrediction, navigate, analyze }: {
  selection: Selection; stage: Stage; revision: string; theme: Theme;
  bindPrediction: (prediction: Pick<BusinessPrediction, "record_id" | "model_id" | "date" | "task">) => void;
  navigate: (stage: string) => void;
  analyze: (id: string, title: string, plan: BusinessPlan) => void;
}) {
  const storageKey = `cecep-business-plan:${s.source}:${s.date}`;
  const [chosen, setChosen] = useState(() => { try { return sessionStorage.getItem(storageKey) || ""; } catch { return ""; } });
  const [record, setRecord] = useState(s.task === "pv_day_ahead_reference" ? s.record : "");
  const [parameters, setParameters] = useState<PlanParameters>(defaultPlanParameters);
  const [prices, setPrices] = useState<Record<string, string>>({});
  const [loadedParent, setLoadedParent] = useState("");
  const [actor, setActor] = useState(() => localStorage.getItem("cecep-research-actor") || "");
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [localRevision, setLocalRevision] = useState(0);
  const mounted = useRef(true);
  useEffect(() => { mounted.current = true; return () => { mounted.current = false; }; }, []);
  const base = new URLSearchParams({ source_key: s.source, trading_date: s.date });
  const catalogParams = new URLSearchParams(base);
  if (record) catalogParams.set("record_id", record);
  const catalog = useResource<BusinessCatalog>("/api/v1/business/catalog?" + catalogParams, `${revision}:${localRevision}`, 10000);
  const selected = catalog.data?.plans.find((p) => p.id === chosen) || catalog.data?.plans[0];
  const detail = useResource<{ plan: BusinessPlan; settlements: BusinessSettlement[]; notice: string }>(selected ? `/api/v1/business/plans/${encodeURIComponent(selected.id)}?` + base : null, `${revision}:${localRevision}`, 10000);
  const plan = detail.data?.plan;
  const snapshotParams = new URLSearchParams(base);
  if (plan) snapshotParams.set("record_id", plan.record_id);
  const snapshotCatalog = useResource<BusinessCatalog>(plan ? "/api/v1/business/catalog?" + snapshotParams : null, `${revision}:${localRevision}`, 10000);
  const settlements = detail.data?.settlements || [];
  const inputReady = !!catalog.data && !catalog.loading && !catalog.error && !catalog.refreshing;
  const snapshotReady = !!snapshotCatalog.data && !snapshotCatalog.loading && !snapshotCatalog.error && !snapshotCatalog.refreshing;
  const canWrite = !!actor.trim() && !!reason.trim() && !busy;
  useEffect(() => { if (chosen) sessionStorage.setItem(storageKey, chosen); }, [chosen, storageKey]);
  function choosePlan(id: string) {
    setChosen(id); setMessage(""); setError("");
    const found = catalog.data?.plans.find((p) => p.id === id);
    if (found) bindPrediction(found);
  }
  async function command(action: "create_plan" | "derive_plan" | "settle", observation?: string) {
    if (!canWrite || !(action === "settle" ? snapshotReady : inputReady) || (action === "derive_plan" && loadedParent !== plan?.id)) return;
    setBusy(true); setError(""); setMessage("");
    const prediction = catalog.data?.predictions.find((p) => p.record_id === record);
    try {
      const result = await request<{ plan: BusinessPlan; settlement?: BusinessSettlement }>("/api/v1/business/commands", {
        action, source_key: s.source, trading_date: s.date, record_id: action === "settle" ? plan?.record_id : record,
        model_id: action === "settle" ? plan?.model_id : prediction?.model_id,
        plan_id: action === "create_plan" ? undefined : plan?.id, actor: actor.trim(), reason: reason.trim(), key: requestKey(),
        ...(action === "settle" ? {} : { parameters, ...prices }), observation_id: observation, context_version: action === "settle" ? snapshotCatalog.data?.context_version : catalog.data?.context_version,
      });
      if (!mounted.current) return;
      setChosen(result.plan.id); bindPrediction(result.plan);
      localStorage.setItem("cecep-research-actor", actor.trim());
      setMessage(action === "settle" ? "已保存新的实绩结算版本；旧结算保留。" : "方案已保存并绑定预测与参数；不会覆盖已有方案。");
      setLocalRevision((v) => v + 1);
    } catch (e) { setError(businessText((e as Error).message)); }
    finally { setBusy(false); }
  }
  const comparisonSettlements = [...new Map([...(catalog.data?.plans.flatMap((p) => p.latest_settlement ? [p.latest_settlement] : []) || []), ...settlements].map((x) => [x.id, x])).values()];
  return <div className="business-workflow">
    <div className="business-stage-nav" aria-label="方案业务步骤">{[{ key: "plan", name: "形成申报方案" }, { key: "settlement", name: "核对实绩结算" }, { key: "review", name: "处理与验证偏差" }].map((item, i) => <button key={item.key} aria-current={stage === item.key ? "step" : undefined} onClick={() => navigate(item.key)}><span>{i + 1}</span>{item.name}</button>)}</div>
    <Status loading={catalog.loading} error={catalog.error} />
    {error && <p className="state error" role="alert">操作未完成：{businessText(error)}。已填写的内容保留，请核对后重试。</p>}
    {message && <p className="inline-success" role="status">{message}</p>}
    <p className="business-object-notice">保存对象快照 · 历史研究。本页展示完整已保存方案与实绩版本，查看方式固定为历史复盘，不按回放时间重新筛选或结算。</p>
    <p className="research-help">{businessText(catalog.data?.notice || "正在读取当前来源与日期的业务记录。")}</p>
    <Panel title="业务范围与已保存方案" subtitle="预测、方案和结算各自保存；选择方案后使用它绑定的预测继续操作。">
      <div className="research-filters"><label>当前方案<select aria-label="当前申报方案" value={selected?.id || ""} onChange={(e) => choosePlan(e.target.value)}><option value="">尚无保存方案</option>{catalog.data?.plans.map((p) => <option key={p.id} value={p.id}>{businessText(p.name)} · 第{p.version}版</option>)}</select></label></div>
      <div className="business-form-grid"><label>操作人<input value={actor} onChange={(e) => setActor(e.target.value)} placeholder="填写姓名" /></label><label className="business-form-wide">操作与复盘依据<textarea rows={2} value={reason} onChange={(e) => setReason(e.target.value)} placeholder="说明本次方案、结算或处理依据" /></label></div>
      <p className="research-help">操作身份为内网声明，所有保存动作需填写依据。当前为历史研究，不向交易平台发送申报。</p>
      {plan && <dl className="unified-source-facts"><div><dt>方案版本</dt><dd>{businessText(plan.name)} · 第{plan.version}版{plan.parent_name ? ` · 派生自${businessText(plan.parent_name)}` : ""}</dd></div><div><dt>绑定的功率预测</dt><dd>{businessText(catalog.data?.predictions.find((p) => p.record_id === plan.record_id)?.name || "方案保存的光伏日前预测")}</dd></div><div><dt>预测决策时点</dt><dd>{plan.cutoff_at ? stamp(plan.cutoff_at) : "保存对象中未列出"}</dd></div><div><dt>预测日期</dt><dd>{plan.date}</dd></div><div><dt>保存时间</dt><dd>{stamp(plan.created_at)}</dd></div><div><dt>保存依据</dt><dd>{businessText(plan.reason)}</dd></div>{Object.entries(plan.price_records || {}).map(([key, value]) => <div key={key}><dt>{key === "da" ? "日前价格依据" : key === "rt" ? "实时价格依据" : "价差依据"}</dt><dd>{businessText(value?.name || "未绑定")}</dd></div>)}</dl>}
    </Panel>
    {stage === "plan" && <>
      <Panel title="形成新方案或派生调整版本" subtitle="只绑定已保存的光伏日前预测；调整参数后保存新版本，原方案和原预测均保留。">
        <BusinessPlanForm predictions={catalog.data?.predictions || []} record={record} setRecord={(value) => { setRecord(value); setPrices({ da_record_id: "", rt_record_id: "", spread_record_id: "" }); }} parameters={parameters} setParameters={setParameters} priceRecords={prices} setPriceRecords={setPrices} />
        <div className="research-filters"><button className="primary-button" disabled={!canWrite || !inputReady || !record} onClick={() => void command("create_plan")}>保存新的申报方案</button><button disabled={!canWrite || !inputReady || !record || !plan || loadedParent !== plan.id} onClick={() => void command("derive_plan")}>由当前方案派生新版本</button>{plan && <button onClick={() => { setLoadedParent(plan.id); setRecord(plan.record_id); setParameters({ ...plan.parameters }); setPrices({ da_record_id: plan.price_records?.da?.record_id || "", rt_record_id: plan.price_records?.rt?.record_id || "", spread_record_id: plan.price_records?.spread?.record_id || "" }); }}>带入当前方案参数与价格依据</button>}<button onClick={() => navigate("forecast")}>前往补充保存预测</button></div>
        <p className="research-help">下方结果属于已经保存的方案，上方表单是待保存的新输入。派生前先带入当前方案参数与价格依据；上方模型切换不会修改已有方案。</p>
      </Panel>
      {plan && <>
        <Status loading={detail.loading} error={detail.error} />
        <Panel title="所选方案的预计结果与风险">
          <div className="research-metrics"><div><span>预测发电量 / MWh</span><strong>{fmt(plan.estimated.forecast_mwh, 3)}</strong></div><div><span>方案申报电量 / MWh</span><strong>{fmt(plan.estimated.bid_mwh, 3)}</strong></div><div><span>预计净额 / 元</span><strong>{fmt(plan.estimated.expected_value, 2)}</strong></div><div><span>具备预计价格的小时</span><strong>{plan.estimated.priced_hours}<small> / {plan.estimated.total_hours}</small></strong></div></div>
          <p className="research-help">{businessText(plan.estimated.notice)}</p><p className="research-help">{businessText(plan.risk.notice)}</p>
          {plan.risk.available && <dl className="unified-source-facts"><div><dt>训练残差样本</dt><dd>{plan.risk.sample_hours} 小时</dd></div><div><dt>每小时误差参考范围</dt><dd>{fmt(plan.risk.lower_error_mwh, 3)} 至 {fmt(plan.risk.upper_error_mwh, 3)} MWh</dd></div></dl>}
          <div className="research-filters"><button onClick={() => navigate("settlement")}>继续核对实绩结算</button><button onClick={() => analyze(plan.id, plan.name, plan)}>请智能体分析这个方案</button></div>
          <BusinessSeriesChart hours={plan.hours || []} mode="quantity" theme={theme} />
        </Panel>
        <Panel title="逐小时申报与预计净额"><div className="table-wrap"><table><thead><tr><th>小时</th><th>预测 / MWh</th><th>申报系数</th><th>申报 / MWh</th><th>日前预测价</th><th>实时预测价</th><th>预计净额 / 元</th><th>数据说明</th></tr></thead><tbody>{plan.hours?.map((h) => <tr key={h.hour}><td>{h.time}</td><td>{fmt(h.forecast_mwh, 3)}</td><td>{fmt(h.bid_ratio, 2)}</td><td>{fmt(h.bid_mwh, 3)}</td><td>{fmt(h.da_forecast, 2)}</td><td>{fmt(h.rt_forecast, 2)}</td><td>{fmt(h.expected_value, 2)}</td><td>{businessText(h.missing_reason || "已保存方案参数")}</td></tr>)}</tbody></table></div></Panel>
      </>}
    </>}
    {stage !== "plan" && <Status loading={detail.loading} error={detail.error} />}
    {stage !== "plan" && !selected && !catalog.loading && <Panel title="先形成并选择申报方案"><p className="research-empty">当前来源和日期还没有保存的申报方案。</p><button onClick={() => navigate("plan")}>前往形成申报方案</button></Panel>}
    {stage === "settlement" && plan && <><Status loading={snapshotCatalog.loading} error={snapshotCatalog.error} /><BusinessSettlementView key={plan.id} plan={plan} settlements={settlements} observations={snapshotCatalog.data?.observations || []} busy={busy} canSubmit={canWrite && snapshotReady} theme={theme} settle={(observation) => void command("settle", observation)} review={() => navigate("review")} analyze={(settlement) => analyze(settlement.id, settlement.name, plan)} /></>}
    {stage === "review" && plan && <BusinessReview key={plan.id} source={s.source} date={s.date} plan={plan} predictions={catalog.data?.predictions || []} settlements={settlements} comparisonSettlements={comparisonSettlements} actor={actor} reason={reason} revision={`${revision}:${localRevision}`} analyze={(issue) => analyze(issue.id, issue.name, plan)} modelReview={() => { bindPrediction(plan); navigate("rsi"); }} />}
  </div>;
}
