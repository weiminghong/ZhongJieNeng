import { useState } from "react";
import { fmt, stamp } from "./api";
import { Panel } from "./components";
import { businessText } from "./presentation";
import BusinessSeriesChart from "./BusinessSeriesChart";
import type { Theme } from "./types";
import type { BusinessPlan, BusinessSettlement, Observation } from "./businessTypes";

export default function BusinessSettlementView({ plan, settlements, observations, busy, canSubmit, theme, settle, review, analyze }: {
  plan: BusinessPlan; settlements: BusinessSettlement[]; observations: Observation[];
  busy: boolean; canSubmit: boolean; theme: Theme; settle: (observation: string) => void;
  review: () => void; analyze: (settlement: BusinessSettlement) => void;
}) {
  const [observed, setObserved] = useState("");
  const [chosen, setChosen] = useState("");
  const selected = settlements.find((s) => s.id === chosen) || settlements[0];
  const available = observations.filter((o) => o.prediction_id === plan.record_id);
  return <>
    <Panel title="选择实绩并保存结算" subtitle="申报方案固定不变；每次按所选实际观测形成新的结算版本，不覆盖旧结算。">
      <div className="research-filters"><label>已核对的实际观测<select aria-label="结算实际观测" value={observed} onChange={(e) => setObserved(e.target.value)}><option value="">请选择实际观测版本</option>{available.map((o) => <option key={o.id} value={o.id}>{businessText(o.name)} · {stamp(o.checked_at)}</option>)}</select></label>
        <button className="primary-button" disabled={busy || !canSubmit || !available.some((o) => o.id === observed)} onClick={() => settle(observed)}>保存本次实绩结算</button>
      </div>
      {!available.length && <p className="research-empty">所选预测尚无已核对的实际观测。可以保留方案，待观测齐备后再结算。</p>}
      <p className="research-help">只对实际出力、日前价和实时价同时齐备的小时结算；缺失小时单列，不用零补齐。规则为历史研究规则。</p>
    </Panel>
    {selected ? <>
      <Panel title="预计与实绩对照" subtitle="预计取方案保存时的预测与参数，实际取本次选择的观测，两者均保留原快照。">
        <div className="research-filters"><label>查看结算版本<select aria-label="查看结算版本" value={selected.id} onChange={(e) => setChosen(e.target.value)}>{settlements.map((s) => <option key={s.id} value={s.id}>{businessText(s.name)} · {stamp(s.created_at)}</option>)}</select></label></div>
        <p>{businessText(selected.observation_name)} · {stamp(selected.created_at)}</p>
        <div className="research-metrics">
          <div><span>匹配小时的预计净额 / 元</span><strong>{fmt(selected.comparison.expected_value, 2)}</strong></div>
          <div><span>匹配小时的实际净额 / 元</span><strong>{fmt(selected.comparison.actual_value, 2)}</strong></div>
          <div><span>实际减预计 / 元</span><strong>{fmt(selected.comparison.delta, 2)}</strong></div>
          <div><span>预计与实际可比小时</span><strong>{selected.comparison.matched_hours}<small> / 24</small></strong></div>
        </div>
        <dl className="unified-source-facts">
          <div><dt>已结算全部小时净额</dt><dd>{fmt(selected.actual.value, 2)} 元</dd></div>
          <div><dt>同范围全实时参考</dt><dd>{fmt(selected.actual.reference, 2)} 元</dd></div>
          <div><dt>与全实时参考差额</dt><dd>{fmt(selected.actual.delta, 2)} 元</dd></div>
          <div><dt>实际结算完整性</dt><dd>{selected.actual.settled_hours} 小时已结算 · {selected.actual.excluded_hours} 小时未结算</dd></div>
          <div><dt>出力差异对应金额</dt><dd>{fmt(selected.comparison.power_effect, 2)} 元</dd></div>
          <div><dt>价格差异对应金额</dt><dd>{fmt(selected.comparison.price_effect, 2)} 元</dd></div>
          <div><dt>费用差异对应金额</dt><dd>{fmt(selected.comparison.fee_effect, 2)} 元</dd></div>
        </dl>
        <p className="research-help">预计价格缺失时可有实际结算，但无法形成预计净额或金额差异分解。分解是固定公式的计算结果，不是异常原因认定。</p>
        <BusinessSeriesChart hours={selected.hours} mode="money" theme={theme} />
        <div className="research-filters"><button onClick={review}>继续偏差复盘</button><button onClick={() => analyze(selected)}>请智能体分析这次结算</button></div>
      </Panel>
      <Panel title="逐小时结算与待补数据">
        <div className="table-wrap"><table><thead><tr><th>小时</th><th>申报 / MWh</th><th>实际 / MWh</th><th>日前价</th><th>实时价</th><th>预计净额 / 元</th><th>实际净额 / 元</th><th>实际减预计 / 元</th><th>结算状态</th></tr></thead><tbody>{selected.hours.map((h) => <tr key={h.hour}><td>{h.time}</td><td>{fmt(h.bid_mwh, 3)}</td><td>{fmt(h.actual_mwh, 3)}</td><td>{fmt(h.da_price, 2)}</td><td>{fmt(h.rt_price, 2)}</td><td>{fmt(h.expected_value, 2)}</td><td>{fmt(h.value, 2)}</td><td>{fmt(h.variance, 2)}</td><td>{h.complete ? "已结算" : businessText(h.missing_reason || "数据待补齐")}</td></tr>)}</tbody></table></div>
      </Panel>
    </> : <Panel title="尚未形成实绩结算"><p className="research-empty">先选择已核对的实际观测，填写操作人与依据，再保存结算。已有申报方案会继续保留。</p></Panel>}
  </>;
}
