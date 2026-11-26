import { useEffect, useRef, useState } from "react";
import { Download, Printer } from "lucide-react";
import type { LineSeriesOption } from "echarts";
import type { Entity, Prediction, Score } from "./LearningLoop";
import type { Theme } from "./types";
import { fmt, stamp, useResource } from "./api";
import { Status } from "./components";
import Chart, { baseOption, color } from "./Chart";
import { recordLabel, businessText } from "./presentation";

export type Observation = {
  prediction_id: string;
  points: Prediction["points"];
  scores: Score;
  changed_from_snapshot: number;
  checked_at: string;
  observation_source_hash: string;
};
type Details = {
  model_name?: string;
  input_name?: string;
  observation: Entity<Observation> | null;
  notice: string;
  range: null | {
    points: (Prediction["points"][number] & { lower: number; upper: number })[];
    mean_width: number;
    calibration_points: number;
    observed_points: number;
    observed_coverage: number | null;
    calibration_end: string;
  };
  range_unavailable?: string;
  explanation: null | {
    items: { name: string; value: number }[];
    reconstruction_verified: boolean;
    prediction_mean: number;
    method: string;
  };
  explanation_unavailable?: string;
};
const clock = (s: number) =>
  `${String(Math.floor(s / 4)).padStart(2, "0")}:${String((s % 4) * 15).padStart(2, "0")}`;
export default function PredictionInsights({
  record,
  theme,
  onPoint,
  onObservationChange,
}: {
  record: Entity<Prediction>;
  theme: Theme;
  onPoint: (slot: number) => void;
  onObservationChange?: (observation: Entity<Observation> | null) => void;
}) {
  const [confidence, setConfidence] = useState(0.95);
  const [actualBasis, setActualBasis] = useState(() =>
    new URLSearchParams(location.search).get("actual_basis") === "snapshot"
      ? "snapshot"
      : "latest",
  );
  useEffect(() => {
    const u = new URL(location.href);
    u.searchParams.set("actual_basis", actualBasis);
    history.replaceState(null, "", u);
  }, [actualBasis, record.id]);
  const details = useResource<Details>(
    `/api/v1/research/prediction-details/${record.id}?confidence=${confidence}`,
    0,
    10000,
  );
  const d = details.data;
  const retainedObservation = useRef<Entity<Observation> | null>(null);
  if (d) retainedObservation.current = d.observation;
  const observation =
    actualBasis === "latest"
      ? d?.observation ||
        (retainedObservation.current?.payload.prediction_id === record.id
          ? retainedObservation.current
          : null)
      : null;
  const points = observation?.payload.points || record.payload.points;
  const scores = observation?.payload.scores || record.payload.scores;
  useEffect(() => {
    onObservationChange?.(observation || null);
  }, [observation?.id, actualBasis, record.id]);
  const rangeObserved = points.filter((p) => p.actual !== null);
  const rangeCoverage =
    d?.range && rangeObserved.length
      ? rangeObserved.filter(
          (p) =>
            p.actual! >= p.predicted - d.range!.mean_width / 2 &&
            p.actual! <= p.predicted + d.range!.mean_width / 2,
        ).length / rangeObserved.length
      : null;
  const peak = points.reduce((a, b) => (b.predicted > a.predicted ? b : a));
  const contributions = d?.explanation?.items || [];
  const maximum = Math.max(1, ...contributions.map((c) => Math.abs(c.value)));
  return (
    <div className="prediction-insights">
      <div className="research-filters">
        <label>
          图表实际值来源
          <select
            aria-label="图表实际值来源"
            value={actualBasis}
            onChange={(e) => {
              setActualBasis(e.target.value);
              onObservationChange?.(
                e.target.value === "latest" ? d?.observation || null : null,
              );
            }}
          >
            <option value="latest">最新已核对观测</option>
            <option value="snapshot">原预测保存快照</option>
          </select>
        </label>
        <label>
          历史误差范围
          <select
            aria-label="历史误差范围"
            value={confidence}
            onChange={(e) => setConfidence(Number(e.target.value))}
          >
            <option value={0.8}>80%经验分位</option>
            <option value={0.9}>90%经验分位</option>
            <option value={0.95}>95%经验分位</option>
          </select>
        </label>
        <a
          className="button"
          href={`/api/v1/research/predictions/${record.id}/export${observation ? `?observation_id=${observation.id}` : ""}`}
        >
          <Download size={15} />
          导出所选来源CSV
        </a>
        <button onClick={() => window.print()}>
          <Printer size={15} />
          打印结果
        </button>
      </div>
      <Status loading={details.loading} error={details.error} />
      <p className="research-help">
        {observation
          ? `正在显示 ${stamp(observation.payload.checked_at)} 核对的实际值，相对原快照 ${observation.payload.changed_from_snapshot} 个实际值变化。`
          : "正在显示原预测保存的实际值快照；旧记录不被新数据覆盖。"}{" "}
        预测曲线始终使用原来保存的模型输出。
      </p>
      <div className="research-metrics">
        <div>
          <span>预测最高价格</span>
          <strong>
            {fmt(peak.predicted, 2)}
            <small>元/MWh</small>
          </strong>
          <p>{clock(peak.slot)} · 保留负价格</p>
        </div>
        <div>
          <span>预测平均价格</span>
          <strong>
            {fmt(points.reduce((sum, p) => sum + p.predicted, 0) / 96, 2)}
            <small>元/MWh</small>
          </strong>
          <p>96个15分钟区间</p>
        </div>
        <div>
          <span>经验范围平均宽度</span>
          <strong>
            {fmt(d?.range?.mean_width, 2)}
            <small>元/MWh</small>
          </strong>
          <p>
            {d?.range
              ? `来自 ${d.range.calibration_points} 条既有调参误差`
              : "当前记录不提供同窗误差范围"}
          </p>
        </div>
        <div>
          <span>{observation ? "最新观测核对 MAE" : "原快照 MAE"}</span>
          <strong>
            {fmt(scores.mae, 2)}
            <small>元/MWh</small>
          </strong>
          <p>{scores.n}/96 条标签 · 与所选观测来源一致</p>
        </div>
      </div>
      <Chart
        label="真实模型96点电价推理与原始价格"
        theme={theme}
        onPoint={onPoint}
        option={() => {
          const series: LineSeriesOption[] = [
            {
              name: "本站模型预测",
              type: "line",
              symbol: "none",
              data: points.map((p) => p.predicted),
              lineStyle: { color: color("primary"), width: 2 },
            },
            {
              name: observation ? "最新核对实际价格" : "原快照实际价格",
              type: "line",
              symbol: "none",
              data: points.map((p) => p.actual),
              lineStyle: { color: color("success"), type: "dashed" },
            },
          ];
          if (d?.range) {
            series.push(
              {
                name: "经验下界",
                type: "line",
                symbol: "none",
                data: d.range.points.map((p) => p.lower),
                lineStyle: { color: color("data"), type: "dotted", width: 1 },
              },
              {
                name: "经验上界",
                type: "line",
                symbol: "none",
                data: d.range.points.map((p) => p.upper),
                lineStyle: { color: color("data"), type: "dotted", width: 1 },
              },
            );
          }
          return {
            ...baseOption(),
            xAxis: {
              ...baseOption().xAxis,
              data: points.map((p) => clock(p.slot)),
            },
            yAxis: { ...baseOption().yAxis, name: "元/MWh", scale: true },
            series,
          };
        }}
      />
      <p className="research-help">
        {d?.range
          ? `经验范围使用截至 ${d.range.calibration_end} 的误差。所选来源的 ${rangeObserved.length} 条实际标签中，${fmt(rangeCoverage === null ? null : rangeCoverage * 100, 1)}% 落在范围内；这不是未来覆盖保证。`
          : d?.range_unavailable}
      </p>
      <div className="research-two-grid">
        <section className="research-insight-section">
          <h3>模型为何得到这个数值</h3>
          {d?.explanation ? (
            <>
              <div className="research-contributions">
                {contributions.map((c) => (
                  <div key={c.name}>
                    <span>{c.name}</span>
                    <strong>
                      {c.value > 0 ? "+" : ""}
                      {fmt(c.value, 2)} 元/MWh
                    </strong>
                    <div>
                      <i
                        style={{
                          width: `${(Math.abs(c.value) / maximum) * 100}%`,
                        }}
                      />
                    </div>
                  </div>
                ))}
              </div>
              <p className="research-help">
                {d.explanation.method}。各项和为{" "}
                {fmt(d.explanation.prediction_mean, 3)}{" "}
                元/MWh，已与真实预测重构核对；不是因果结论。
              </p>
            </>
          ) : (
            <p className="research-help">
              {businessText(d?.explanation_unavailable || "正在核对预测依据…")}
            </p>
          )}
        </section>
        <section className="research-insight-section">
          <h3>可追溯的预测记录</h3>
          <dl className="research-facts">
            <div>
              <dt>预测记录</dt>
              <dd>{recordLabel(record, "已保存预测")}</dd>
            </div>
            <div>
              <dt>预测模型</dt>
              <dd>{d?.model_name || "所选预测模型"}</dd>
            </div>
            <div>
              <dt>输入数据</dt>
              <dd>{d?.input_name || "已保存的历史数据"}</dd>
            </div>
            <div>
              <dt>预测日期</dt>
              <dd>{record.payload.date}</dd>
            </div>
            <div>
              <dt>数据范围</dt>
              <dd>当日96个15分钟时段</dd>
            </div>
            <div>
              <dt>原始实际值</dt>
              <dd>{record.payload.scores.n} 个有效时段</dd>
            </div>
          </dl>
          <p className="research-help">
            点预测保持不变，历史误差范围仅作研究参考。
          </p>
        </section>
      </div>
    </div>
  );
}
