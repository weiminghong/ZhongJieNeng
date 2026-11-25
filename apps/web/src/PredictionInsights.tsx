import { useState } from "react";
import { Download, Printer } from "lucide-react";
import type { LineSeriesOption } from "echarts";
import type { Entity, Prediction } from "./LearningLoop";
import type { Theme } from "./types";
import { fmt, useResource } from "./api";
import { Status } from "./components";
import Chart, { baseOption, color } from "./Chart";

type Details = {
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
}: {
  record: Entity<Prediction>;
  theme: Theme;
  onPoint: (slot: number) => void;
}) {
  const [confidence, setConfidence] = useState(0.95);
  const details = useResource<Details>(
    `/api/v1/research/prediction-details/${record.id}?confidence=${confidence}`,
  );
  const d = details.data;
  const points = record.payload.points;
  const peak = points.reduce((a, b) => (b.predicted > a.predicted ? b : a));
  const contributions = d?.explanation?.items || [];
  const maximum = Math.max(1, ...contributions.map((c) => Math.abs(c.value)));
  return (
    <div className="prediction-insights">
      <div className="research-filters">
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
          href={`/api/v1/research/predictions/${record.id}/export`}
        >
          <Download size={15} />
          导出本次CSV
        </a>
        <button onClick={() => window.print()}>
          <Printer size={15} />
          打印结果
        </button>
      </div>
      <Status loading={details.loading} error={details.error} />
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
          <span>本次已观察 MAE</span>
          <strong>
            {fmt(record.payload.scores.mae, 2)}
            <small>元/MWh</small>
          </strong>
          <p>{record.payload.scores.n}/96 条标签 · 快照不随新记录改写</p>
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
              name: "原始实际价格",
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
          ? `经验范围使用截至 ${d.range.calibration_end} 的误差。本次 ${d.range.observed_points} 条已观察标签中，${fmt((d.range.observed_coverage ?? 0) * 100, 1)}% 落在范围内；这不是未来覆盖保证。`
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
              {d?.explanation_unavailable || "正在核对真实模型项…"}
            </p>
          )}
        </section>
        <section className="research-insight-section">
          <h3>可追溯的预测记录</h3>
          <dl className="research-facts">
            <div>
              <dt>预测ID</dt>
              <dd>{record.id}</dd>
            </div>
            <div>
              <dt>调用模型</dt>
              <dd>{record.payload.model_id}</dd>
            </div>
            <div>
              <dt>权重SHA256</dt>
              <dd>{record.payload.weights_hash}</dd>
            </div>
            <div>
              <dt>输入版本</dt>
              <dd>{record.source_hash}</dd>
            </div>
          </dl>
          <p className="research-help">{d?.notice}</p>
        </section>
      </div>
    </div>
  );
}
