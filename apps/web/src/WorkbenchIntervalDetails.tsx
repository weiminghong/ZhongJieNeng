import { fmt, time } from "./api";
import { Panel } from "./components";
import { businessText, stateLabel } from "./presentation";

type Point = { slot: number; start: string; actual: number | null; predicted: number | null; da_price: number | null; rt_price: number | null; quality: string };
export default function IntervalDetails({ points, slot, unit, sourceName, modelName, recordName, basis, select, navigate, analyze }: {
  points: Point[];
  slot: number | null;
  unit: string;
  sourceName: string;
  modelName: string;
  recordName: string;
  basis: "latest" | "snapshot";
  select: (slot: number) => void;
  navigate: (tab: string) => void;
  analyze: (point: Point) => void;
}) {
  const point = points.find((p) => p.slot === slot);
  return (
    <Panel title="当前时段与证据" subtitle="点击曲线或选择时段，后续数据核对、复核与分析沿用这一范围。">
      <label className="unified-interval-select">查看时段<select aria-label="首页查看时段" value={slot ?? ""} onChange={(e) => e.target.value !== "" && select(Number(e.target.value))}><option value="">请选择一个时段</option>{points.map((p) => <option key={p.slot} value={p.slot}>{time(p.start)}</option>)}</select></label>
      {point ? <>
        <dl className="unified-source-facts unified-interval-facts">
          <div><dt>时段</dt><dd>{time(point.start)} · {stateLabel(point.quality)}</dd></div>
          <div><dt>模型预测</dt><dd>{fmt(point.predicted, 3)} {unit}</dd></div>
          <div><dt>实际值</dt><dd>{fmt(point.actual, 3)} {unit}</dd></div>
          <div><dt>预测减实际</dt><dd>{point.predicted !== null && point.actual !== null ? fmt(point.predicted - point.actual, 3) : "—"} {unit}</dd></div>
          <div><dt>日前电价</dt><dd>{fmt(point.da_price, 2)} 元/MWh</dd></div>
          <div><dt>实时电价</dt><dd>{fmt(point.rt_price, 2)} 元/MWh</dd></div>
        </dl>
        {point.actual === null && <p className="research-help">当前时点没有有效实际值，暂不能确认偏差或保存复核。</p>}
      </> : <p className="research-empty">尚未选择时段。先点击左侧曲线，即可核对这一时段的预测和实际值。</p>}
      <dl className="unified-source-facts unified-interval-facts">
        <div><dt>来源</dt><dd>{sourceName}</dd></div>
        <div><dt>所选模型</dt><dd>{businessText(modelName || "未选择模型")}</dd></div>
        <div><dt>预测依据</dt><dd>{businessText(recordName || "当前尚无已保存预测")}</dd></div>
        <div><dt>实际值口径</dt><dd>{basis === "snapshot" ? "预测保存快照" : "最新已核对观测"}</dd></div>
      </dl>
      <div className="unified-detail-actions">
        <button onClick={() => navigate("raw")}>核对来源与分时数据</button>
        <button disabled={!point || point.actual === null || point.predicted === null} onClick={() => navigate("rsi")}>复核这个时段</button>
        <button className="primary-button" disabled={!point} onClick={() => point && analyze(point)}>让智能体分析这个时段</button>
      </div>
    </Panel>
  );
}
