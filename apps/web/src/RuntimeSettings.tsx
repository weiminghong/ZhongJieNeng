import { useState, type FormEvent } from "react";
import { request, useResource, fmt } from "./api";
import type { Bootstrap, Inference, RuntimeModel } from "./types";
import { Status } from "./components";

export default function RuntimeSettings() {
  const [revision, setRevision] = useState(0);
  const models = useResource<{ models: RuntimeModel[] }>("/api/v1/models/runtime", revision);
  const bootstrap = useResource<Bootstrap>("/api/v1/workbench/bootstrap");
  const [name, setName] = useState("");
  const [version, setVersion] = useState("");
  const [uri, setUri] = useState("");
  const [hash, setHash] = useState("");
  const [source, setSource] = useState("synthetic");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [result, setResult] = useState<Inference | null>(null);
  async function predict(model: RuntimeModel) {
    const b = bootstrap.data;
    if (!b?.stations.length || !b.dates.length) throw new Error("当前没有可用于推理校验的场站与交易日");
    const prediction = await request<Inference>("/api/v1/models/predict", { station_id: b.stations[0].station_id,
      date: b.dates.includes(b.default_date) ? b.default_date : b.dates[b.dates.length - 1],
      source_mode: model.source_mode, mode: "live", model_version_id: model.model_version_id });
    setResult(prediction);
  }
  async function register(e: FormEvent) {
    e.preventDefault(); setBusy(true); setError(""); setMessage(""); setResult(null);
    try {
      const response = await fetch("/api/v1/models/register", { method: "POST", headers: { "Content-Type": "application/json", "X-CECEP-Settings": "1" },
        body: JSON.stringify({ model_name: name, version, artifact_uri: uri, artifact_hash: hash || null, source_mode: source }) });
      const data = await response.json();
      if (!response.ok) throw new Error(data.error || JSON.stringify(data.detail));
      setMessage("模型已追加登记为 candidate；正在执行真实96点推理校验。");
      setRevision(v => v + 1);
      await predict(data); setMessage("登记成功，真实推理协议校验通过；尚未验证生产精度。");
    } catch (e) { setError((e as Error).message); }
    finally { setBusy(false); }
  }
  return <section className="panel runtime-settings">
    <h2>预测小模型运行时与热注册</h2>
    <p className="muted">内置残差模型按 PIT 可见历史现场拟合。外部模型仅验证文件或接口协议；登记不会自动上线，也不证明生产精度。</p>
    <Status loading={models.loading} error={models.error || bootstrap.error} />
    <div className="table-wrap"><table><thead><tr><th>模型 / 版本</th><th>任务 / 适配器</th><th>状态 / 数据模式</th><th>就绪说明</th><th>验证</th></tr></thead><tbody>{models.data?.models.map(m => <tr key={m.model_version_id}><td>{m.model_name} v{m.version}</td><td>{m.task}<br />{m.adapter_type}</td><td>{m.effective_status} · {m.source_mode}</td><td>{m.readiness_note}</td><td><button disabled={!m.ready || busy} onClick={async () => { setBusy(true); setError(""); setResult(null); try { await predict(m); } catch(e) { setError((e as Error).message); } finally { setBusy(false); } }}>真实预测校验</button></td></tr>)}</tbody></table></div>
    <form onSubmit={register} className="runtime-registration"><fieldset disabled={busy}>
      <label className="model-settings-field">模型名称<input required maxLength={100} value={name} onChange={e => setName(e.target.value)} /></label>
      <label className="model-settings-field">版本<input required maxLength={100} value={version} onChange={e => setVersion(e.target.value)} /></label>
      <label className="model-settings-field">权重 URI 或 HTTP 推理地址<input required value={uri} onChange={e => setUri(e.target.value)} placeholder="local_joblib://runtime/models/model.joblib 或 https://模型服务/predict" /><small>支持 joblib、TorchScript、ONNX；本地文件须先由管理员放入服务器 models 或 runtime/models。仅加载可信来源权重。</small></label>
      <label className="model-settings-field">本地文件 SHA-256<input value={hash} onChange={e => setHash(e.target.value)} pattern="[0-9a-f]{64}" maxLength={64} required={uri.startsWith("local_")} /></label>
      <label className="model-settings-field">数据模式<select value={source} onChange={e => setSource(e.target.value)}><option value="synthetic">synthetic · 合成演示</option><option value="production">production · 真实输入</option></select></label>
      <p className="muted">特征协议：baseline_mw、cloud_cover_pct、air_temp_c，矩阵形状96×3；HTTP POST 返回 predictions 数组，GET 用于注册连通探测。</p>
      <button className="primary-button" disabled={busy || !bootstrap.data}>{busy ? "正在校验…" : "登记并执行真实预测"}</button>
    </fieldset></form>
    <Status error={error} />{message && <p role="status">{message}</p>}
    {result && <div className="notice"><p>真实推理已返回 {result.points.length} 点 · {result.model_name} · {fmt(result.latency_ms, 0)} ms<br />{result.source_mode} · {result.trained_scope} · 配对 MAE {fmt(result.metrics.mae)} MW（{result.metrics.sample_count} 个时段）</p></div>}
  </section>;
}
