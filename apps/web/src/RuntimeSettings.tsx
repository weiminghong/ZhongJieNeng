import { useState } from "react";
import { request, useResource, fmt } from "./api";
import type { Bootstrap, Inference, RuntimeModel } from "./types";
import { Status } from "./components";
import {
  businessText,
  taskLabel,
  stateLabel,
  sourceLabel,
} from "./presentation";
export default function RuntimeSettings() {
  const models = useResource<{ models: RuntimeModel[] }>(
    "/api/v1/models/runtime",
  );
  const bootstrap = useResource<Bootstrap>("/api/v1/workbench/bootstrap");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [result, setResult] = useState<Inference | null>(null);
  async function verify(model: RuntimeModel) {
    setBusy(true);
    setError("");
    setResult(null);
    try {
      const b = bootstrap.data;
      if (!b?.stations.length || !b.dates.length)
        throw new Error("暂无可用于检查的场站和交易日");
      setResult(
        await request<Inference>("/api/v1/models/predict", {
          station_id: b.stations[0].station_id,
          date: b.dates.includes(b.default_date)
            ? b.default_date
            : b.dates[b.dates.length - 1],
          source_mode: model.source_mode,
          mode: "live",
          model_version_id: model.model_version_id,
        }),
      );
    } catch (e) {
      setError(businessText((e as Error).message));
    } finally {
      setBusy(false);
    }
  }
  return (
    <section className="panel runtime-settings">
      <h2>已接入的预测能力</h2>
      <p className="muted">
        查看模型是否可执行。完成检查不代表生产精度已经验收。
      </p>
      <Status
        loading={models.loading}
        error={models.error || bootstrap.error || error}
      />
      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th>模型</th>
              <th>业务任务</th>
              <th>状态</th>
              <th>数据来源</th>
              <th>操作</th>
            </tr>
          </thead>
          <tbody>
            {models.data?.models.map((m) => (
              <tr key={m.model_version_id}>
                <td>
                  {businessText(m.model_name)} · {m.version}
                </td>
                <td>{taskLabel(m.task)}</td>
                <td>{stateLabel(m.effective_status)}</td>
                <td>{sourceLabel(m.source_mode)}</td>
                <td>
                  <button
                    disabled={!m.ready || busy}
                    onClick={() => void verify(m)}
                  >
                    {busy ? "正在检查…" : "检查预测能力"}
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {result && (
        <p className="notice">
          已返回 {result.points.length} 个时段的预测。平均绝对误差{" "}
          {fmt(result.metrics.mae)} MW，共 {result.metrics.sample_count}{" "}
          个有效时段。
        </p>
      )}
    </section>
  );
}
