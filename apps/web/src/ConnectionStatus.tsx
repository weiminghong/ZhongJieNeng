import { Cable, ArrowUpRight } from "lucide-react";
import type { Readiness } from "./types";
import { Panel, Status } from "./components";
import { stamp } from "./api";

export default function ConnectionStatus({
  resource,
}: {
  resource: { data: Readiness | null; loading: boolean; error: string };
}) {
  const data = resource.data;
  return (
    <div className="connection-status">
      <Status loading={resource.loading} error={resource.error} />
      {data && (
        <>
          <div className="connection-intro">
            <Cable size={26} />
            <div>
              <h2>数据与模型接入实况</h2>
              <p>
                {data.source_mode === "synthetic" ? "合成演示" : "生产数据"} ·
                当前场站 · 核验于 {stamp(data.checked_at)}
              </p>
            </div>
            <a className="button" href="/settings">
              配置模型连接
              <ArrowUpRight size={15} />
            </a>
          </div>
          <Panel
            title="数据就绪情况"
            subtitle="直接统计底层到达记录；未确认来源与合成来源不会计为真实输入。数量包含历史修订，不等同有效配对数。"
          >
            <div className="table-wrap">
              <table className="presentation-table">
                <thead>
                  <tr>
                    <th>业务输入</th>
                    <th>到达记录</th>
                    <th>最新到达时间</th>
                    <th>状态</th>
                  </tr>
                </thead>
                <tbody>
                  {data.inputs.map((row) => (
                    <tr key={row.key}>
                      <td>{row.label}</td>
                      <td>{row.record_count}</td>
                      <td>
                        {row.latest_available_at
                          ? stamp(row.latest_available_at)
                          : "—"}
                      </td>
                      <td>
                        <span
                          className={`badge ${row.record_count ? "success" : "warning"}`}
                        >
                          {row.record_count ? "有输入记录" : "等待接入"}
                        </span>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Panel>
          <Panel
            title="可执行能力与边界"
            subtitle="适配器可执行、权重训练记录、业务效果验证分别判断。"
          >
            <div className="capability-list">
              {data.capabilities.map((c) => (
                <div key={c.key}>
                  <span
                    className={`badge ${c.available ? "success" : "warning"}`}
                  >
                    {c.available ? "已实现" : "待接入"}
                  </span>
                  <div>
                    <h3>{c.label}</h3>
                    <p>{c.note}</p>
                  </div>
                </div>
              ))}
            </div>
          </Panel>
          <Panel
            title="当前推理适配器"
            subtitle="就绪表示协议或本地依赖可用；HTTP 服务在实际请求时验证，不等于预测精度已验收。"
          >
            <div className="table-wrap">
              <table className="presentation-table">
                <thead>
                  <tr>
                    <th>模型版本</th>
                    <th>适配器</th>
                    <th>可执行状态</th>
                    <th>说明</th>
                  </tr>
                </thead>
                <tbody>
                  {data.models.map((m) => (
                    <tr key={m.model_version_id}>
                      <td>
                        {m.model_name} v{m.version}
                      </td>
                      <td>{m.adapter_type}</td>
                      <td>{m.ready ? "适配器就绪" : "不可执行"}</td>
                      <td>{m.readiness_note}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Panel>
          <p className="connection-limits">{data.notice}</p>
        </>
      )}
    </div>
  );
}
