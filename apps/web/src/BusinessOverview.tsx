import { useResource } from "./api";
import { Panel, Status } from "./components";
import { businessText } from "./presentation";
import type { BusinessCatalog } from "./businessTypes";

export default function BusinessOverview({ source, date, revision, navigate }: { source: string; date: string; revision: string; navigate: (tab: string) => void }) {
  const scope = new URLSearchParams({ source_key: source, trading_date: date });
  const catalog = useResource<BusinessCatalog>("/api/v1/business/catalog?" + scope, revision, 10000);
  const reviews = useResource<{ records: { state: string }[] }>(source === "market:shandong" ? "/api/v1/business/reviews?" + scope : null, revision, 10000);
  const data = catalog.data;
  const pv = data?.predictions.filter((p) => p.task === "pv_day_ahead_reference").length || 0;
  const settled = data?.plans.filter((p) => p.latest_settlement).length || 0;
  const pending = reviews.data?.records.filter((i) => i.state !== "verified").length || 0;
  return <Panel title="当前日期的业务待办" subtitle="按本来源、本日期实际保存的预测、方案、结算与处理事项统计。">
    <Status loading={catalog.loading || reviews.loading} error={catalog.error || reviews.error} />
    {data && <>
      <p className="research-help">{businessText(data.notice)}</p>
      {source === "market:shandong" ? <>
        <div className="research-metrics"><div><span>已保存光伏日前预测</span><strong>{pv}<small> 条</small></strong></div><div><span>已保存申报方案</span><strong>{data.plans.length}<small> 个</small></strong></div><div><span>已有实绩结算的方案</span><strong>{settled}<small> 个</small></strong></div><div><span>尚待验证的处理项</span><strong>{reviews.data ? pending : "—"}<small> 项</small></strong></div></div>
        <div className="research-filters"><button onClick={() => navigate(pv ? "plan" : "forecast")}>{pv ? "形成或调整申报方案" : "先保存光伏日前预测"}</button><button disabled={!data.plans.length} onClick={() => navigate("settlement")}>{data.plans.length - settled} 个方案待结算 · 查看实绩</button><button disabled={!data.plans.length} onClick={() => navigate("review")}>处理与验证 {reviews.data ? pending : "待检查"} 项偏差</button></div>
      </> : <p className="research-empty">此来源尚未接入真实申报与结算业务链；可继续查看已有预测与数据，不使用公开市场方案代替场站业务。</p>}
    </>}
  </Panel>;
}
