import { useState } from "react";
import { fmt, stamp, time, useResource } from "./api";
import { Panel, Status } from "./components";
import Chart, { baseOption } from "./Chart";
import type { Theme } from "./types";

type Row = {
  name: string;
  n: number;
  mae?: number;
  rmse?: number;
  accuracy?: number;
  balanced_accuracy?: number;
};
type Report = {
  id: string;
  name: string;
  family: string;
  created_at: string;
  unit: string;
  rows: number;
  days: number;
  scores: Row[];
  evidence: string;
  old_evidence: string;
  input_notice: string;
  replay: { start: string; end: string; scores: Row[]; evidence: string };
  folds: {
    start: string;
    end: string;
    choice: string;
    candidate: Omit<Row, "name">;
    reference: Omit<Row, "name">;
  }[];
};
type Point = {
  start: string;
  actual: number;
  predicted: number;
  old?: number;
  reference?: number;
  positive?: number;
};
function Scores({
  rows,
  family,
  unit,
}: {
  rows: Row[];
  family: string;
  unit: string;
}) {
  const direction = family === "direction";
  return (
    <div className="table-wrap">
      <table>
        <thead>
          <tr>
            <th>方法</th>
            <th>{direction ? "方向命中率" : "平均绝对误差 / " + unit}</th>
            <th>{direction ? "各方向平均召回" : "均方根误差 / " + unit}</th>
            <th>同范围样本</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((x) => (
            <tr key={x.name}>
              <td>{x.name}</td>
              <td>
                {direction
                  ? fmt((x.accuracy ?? 0) * 100, 2) + "%"
                  : fmt(x.mae, 3)}
              </td>
              <td>
                {direction
                  ? fmt((x.balanced_accuracy ?? 0) * 100, 2) + "%"
                  : fmt(x.rmse, 3)}
              </td>
              <td>{x.n.toLocaleString()}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
const directionName = (x: number) =>
  x > 0 ? "实时偏高" : x < 0 ? "实时偏低" : "持平";
export default function OptimizationEvidence({
  task,
  date,
  revision,
  theme,
}: {
  task: string;
  date: string;
  revision: number;
  theme: Theme;
}) {
  const r = useResource<{ reports: Report[]; notice: string }>(
    "/api/v1/optimization/summary?" + new URLSearchParams({ task_id: task }),
    revision,
    10000,
  );
  const [chosen, setChosen] = useState("");
  const report =
    r.data?.reports.find((x) => x.id === chosen) || r.data?.reports[0];
  const points = useResource<{
    available: boolean;
    points: Point[];
    notice: string;
  }>(
    report
      ? "/api/v1/optimization/predictions?" +
          new URLSearchParams({
            result_id: report.id,
            trading_date: date,
            task_id: task,
          })
      : null,
    revision,
  );
  return (
    <Panel
      title="模型优化：真实历史滚动验证"
      subtitle="新旧方法均按相同截止日训练；优化验证与当前研究主版本分开呈现。"
    >
      <Status loading={r.loading} error={r.error} />
      {!r.loading && !r.error && !report && (
        <p className="research-empty">
          当前任务尚无已完成的优化验证结果。作业实际状态可在运行监测查看。
        </p>
      )}
      {report && (
        <>
          <div className="research-filters">
            <label>
              优化方案
              <select
                aria-label="优化方案"
                value={report.id}
                onChange={(e) => setChosen(e.target.value)}
              >
                {r.data?.reports.map((x) => (
                  <option key={x.id} value={x.id}>
                    {x.name} · {stamp(x.created_at)}
                  </option>
                ))}
              </select>
            </label>
          </div>
          <p className="research-help">{r.data?.notice}</p>
          <p>{report.input_notice}</p>
          <h3>五个跨季节窗口 · {report.days} 个验证日期</h3>
          <Scores
            rows={report.scores}
            family={report.family}
            unit={report.unit}
          />
          <p>{report.evidence}</p>
          <p className="research-help">相对原方法：{report.old_evidence}</p>
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>外层验证日期</th>
                  <th>优化结果</th>
                  <th>预设参考</th>
                  <th>内层决定</th>
                </tr>
              </thead>
              <tbody>
                {report.folds.map((f) => (
                  <tr key={f.start}>
                    <td>
                      {f.start} 至 {f.end}
                    </td>
                    <td>
                      {report.family === "direction"
                        ? fmt((f.candidate.accuracy ?? 0) * 100, 2) + "%"
                        : fmt(f.candidate.mae, 3) + " " + report.unit}
                    </td>
                    <td>
                      {report.family === "direction"
                        ? fmt((f.reference.accuracy ?? 0) * 100, 2) + "%"
                        : fmt(f.reference.mae, 3) + " " + report.unit}
                    </td>
                    <td>{f.choice}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <h3>
            旧最终窗口复盘 · {report.replay.start} 至 {report.replay.end}
          </h3>
          <p className="research-help">
            该窗口已用于旧版本审计，以下结果不作为新的独立终评。
          </p>
          <Scores
            rows={report.replay.scores}
            family={report.family}
            unit={report.unit}
          />
          <p>{report.replay.evidence}</p>
          <h3>当前日期 {date} 的保存预测</h3>
          <Status loading={points.loading} error={points.error} />
          <p className="research-help">{points.data?.notice}</p>
          {points.data?.available &&
            (report.family === "direction" ? (
              <div className="table-wrap">
                <table>
                  <thead>
                    <tr>
                      <th>小时开始</th>
                      <th>实际方向</th>
                      <th>优化判断</th>
                      <th>实时偏高概率</th>
                    </tr>
                  </thead>
                  <tbody>
                    {points.data.points.map((p) => (
                      <tr key={p.start}>
                        <td>{time(p.start)}</td>
                        <td>{directionName(p.actual)}</td>
                        <td>{directionName(p.predicted)}</td>
                        <td>{fmt((p.positive ?? 0) * 100, 1)}%</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : (
              <Chart
                theme={theme}
                label="优化验证的保存预测与同范围实际值"
                option={() => ({
                  ...baseOption(),
                  xAxis: {
                    ...baseOption().xAxis,
                    data: points.data?.points.map((p) => time(p.start)) || [],
                  },
                  yAxis: {
                    ...baseOption().yAxis,
                    name: report.unit,
                    scale: true,
                  },
                  series: [
                    {
                      name: "优化流程",
                      type: "line",
                      symbol: "none",
                      data: points.data?.points.map((p) => p.predicted),
                    },
                    {
                      name: "原方法（同截止日）",
                      type: "line",
                      symbol: "none",
                      lineStyle: { type: "dashed" },
                      data: points.data?.points.map((p) => p.old),
                    },
                    {
                      name: "实际值",
                      type: "line",
                      symbol: "none",
                      data: points.data?.points.map((p) => p.actual),
                    },
                  ],
                })}
              />
            ))}
        </>
      )}
    </Panel>
  );
}
