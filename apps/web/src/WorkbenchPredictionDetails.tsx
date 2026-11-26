import { useState } from "react";
import { fmt, useResource } from "./api";
import { Panel, Status } from "./components";
import { businessText } from "./presentation";

type Details = {
  unit: string;
  explanation: {
    items: { name: string; value: number }[];
    prediction_mean: number;
    output_constrained?: boolean;
    postprocessed_prediction_mean?: number;
    method: string;
  } | null;
  range?: {
    mean_width: number;
    calibration_points: number;
    calibration_end: string;
  } | null;
  notice: string;
  explanation_unavailable?: string;
  range_unavailable?: string;
};
export default function PredictionDetails({
  source,
  task,
  date,
  model,
  record,
  revision,
}: {
  source: string;
  task: string;
  date: string;
  model: string;
  record: string;
  revision: number;
}) {
  const [confidence, setConfidence] = useState("0.95");
  const q = new URLSearchParams({
    source_key: source,
    task_id: task,
    trading_date: date,
    model_id: model,
    record_id: record,
    confidence,
  });
  const r = useResource<Details>(
    "/api/v1/workspace/prediction-details?" + q,
    revision,
  );
  return (
    <Panel title="预测说明与经验误差范围">
      <Status loading={r.loading} error={r.error} />
      {r.data && (
        <>
          <p className="research-help">{businessText(r.data.notice)}</p>
          {r.data.explanation ? (
            <>
              <p>
                {r.data.explanation.method} ·{" "}
                {r.data.explanation.output_constrained
                  ? "约束前日均估计"
                  : "日均预测"}{" "}
                {fmt(r.data.explanation.prediction_mean, 3)} {r.data.unit}
              </p>
              {r.data.explanation.output_constrained && (
                <p>
                  约束后保存预测的均值：
                  {fmt(r.data.explanation.postprocessed_prediction_mean, 3)}{" "}
                  {r.data.unit}
                </p>
              )}
              <div className="table-wrap">
                <table>
                  <thead>
                    <tr>
                      <th>模型项</th>
                      <th>日均贡献 / {r.data.unit}</th>
                    </tr>
                  </thead>
                  <tbody>
                    {r.data.explanation.items.map((x) => (
                      <tr key={x.name}>
                        <td>{x.name}</td>
                        <td>{fmt(x.value, 3)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </>
          ) : (
            <p className="research-help">
              {businessText(
                r.data.explanation_unavailable || "暂无已核验的模型项解释。",
              )}
            </p>
          )}
          {(r.data.range || r.data.range_unavailable) && (
            <>
              <div className="research-filters">
                <label>
                  调参误差分位数
                  <select
                    value={confidence}
                    onChange={(e) => setConfidence(e.target.value)}
                  >
                    <option value="0.8">80%</option>
                    <option value="0.9">90%</option>
                    <option value="0.95">95%</option>
                  </select>
                </label>
              </div>
              {r.data.range ? (
                <p>
                  经验范围宽度 {fmt(r.data.range.mean_width, 3)} {r.data.unit} ·
                  来自 {r.data.range.calibration_points} 个调参样本，截止{" "}
                  {r.data.range.calibration_end}。这不是未来结果的概率保证。
                </p>
              ) : (
                <p className="research-help">
                  {businessText(r.data.range_unavailable)}
                </p>
              )}
            </>
          )}
        </>
      )}
    </Panel>
  );
}
