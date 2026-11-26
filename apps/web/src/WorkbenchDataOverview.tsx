import { useState } from "react";
import { fmt, stamp, useResource } from "./api";
import { Panel, Status } from "./components";
import { businessText, sourceLabel } from "./presentation";

export type SourceMetadata = {
  name?: string;
  source_file?: string;
  source_hash?: string;
  row_count?: number;
  day_count?: number;
  date_start?: string;
  date_end?: string;
  interval_minutes?: number;
  cutoff_at?: string;
};
type Version = {
  id: string;
  display_name?: string;
  source_hash: string;
  rows: number;
  date_start: string;
  date_end: string;
  ingested_at: string;
};
type Flow = { versions: Version[]; checked_at: string; source_policy: string };
export default function DataOverview({
  source, metadata, points, date, model, record, revision, basis,
}: {
  source: { key: string; name: string; domain: string; source_mode: string; target_points?: number };
  metadata?: SourceMetadata;
  points: { actual: number | null; predicted: number | null; quality: string }[];
  date: string;
  model: string;
  record: string;
  revision: string;
  basis: "latest" | "snapshot";
}) {
  const params = new URLSearchParams();
  if (model) params.set("model_id", model);
  if (record) params.set("prediction_id", record);
  const versions = useResource<Flow>(
    source.domain === "market" ? "/api/v1/research/flow?" + params : null,
    revision,
  );
  const [selected, setSelected] = useState("");
  const list = versions.data?.versions || [];
  const current = list.find((v) => v.source_hash === metadata?.source_hash);
  const chosen = list.find((v) => v.id === selected) || current || list[0];
  const pending = points.filter((p) => p.quality === "pending").length;
  const missing = points.filter((p) => p.actual === null && p.quality !== "pending").length;
  const observed = points.filter((p) => p.actual !== null).length;
  const paired = points.filter((p) => p.actual !== null && p.predicted !== null).length;
  const negative = points.filter((p) => p.actual !== null && p.actual < 0).length;
  return (
    <>
      <Panel title="来源与当前观测口径" subtitle="先核对使用什么数据，再查看当日记录；归档版本不会因浏览而被改写。">
        <dl className="unified-source-facts">
          <div><dt>业务来源</dt><dd>{source.name} · {sourceLabel(source.source_mode)}</dd></div>
          <div><dt>观测口径</dt><dd>{basis === "snapshot" ? "预测保存时的实际值快照" : "当前已核对的实际观测"}</dd></div>
          <div><dt>当前观测版本</dt><dd>{current ? businessText(current.display_name || "已归档历史数据") : source.domain === "market" ? versions.loading ? "正在核对归档资料" : "当前观测尚未匹配到可用归档资料" : "按业务记录与查询时点读取"}</dd></div>
          {metadata?.source_file && <div><dt>源文件</dt><dd>{businessText(metadata.source_file)}</dd></div>}
          {metadata?.date_start && <div><dt>文件覆盖日期</dt><dd>{metadata.date_start} 至 {metadata.date_end}</dd></div>}
          {metadata?.row_count !== undefined && <div><dt>文件记录</dt><dd>{fmt(metadata.row_count, 0)} 行 · {fmt(metadata.day_count, 0)} 个日期</dd></div>}
          {metadata?.interval_minutes && <div><dt>原始采样间隔</dt><dd>{metadata.interval_minutes} 分钟；预测任务另按所选业务粒度组织</dd></div>}
          {metadata?.cutoff_at && <div><dt>本次查询截止</dt><dd>{stamp(metadata.cutoff_at)}</dd></div>}
        </dl>
        <p className="research-help">{source.domain === "market" ? "公开历史文件未提供已核验的原始发布时间；归档时间是本系统收录时间。省级数据不代表场站实绩。" : "场站记录按当前查看时点核对；合成演示与生产输入分别保存。此页不把业务记录伪装成外部文件归档。"}</p>
      </Panel>
      <Panel title={`${date} 的数据质量概况`} subtitle="统计范围仅为当前任务、日期及可见时点，不代表整份源文件的质量结论。">
        <div className="research-metrics">
          <div><span>已有实际值</span><strong>{observed}<small> / {source.target_points || points.length} 时段</small></strong></div>
          <div><span>待到达实际值</span><strong>{pending}<small> 时段</small></strong></div>
          <div><span>已发生缺测</span><strong>{missing}<small> 时段</small></strong></div>
          <div><span>可比较预测与实际</span><strong>{paired}<small> 时段</small></strong></div>
        </div>
        <p className="research-help">原始负值保留：{negative} 个时段。缺测与未来尚未到达均不作为真实零值；指标只使用实际与预测均有效的配对时段。</p>
      </Panel>
      {source.domain === "market" && (
        <Panel title="已保留的源文件版本" subtitle="选择后查看该归档的覆盖与收录资料；不会切换当前预测或实际值口径。">
          <Status loading={versions.loading} error={versions.error} />
          {!versions.loading && !versions.error && !list.length && <p className="research-empty">当前尚无已收录的源文件版本。</p>}
          {chosen && <>
            <div className="research-filters"><label>查看归档版本<select aria-label="查看归档版本" value={chosen.id} onChange={(e) => setSelected(e.target.value)}>{list.map((v) => <option key={v.id} value={v.id}>{businessText(v.display_name || "历史数据归档")} · {v.date_start} 至 {v.date_end}</option>)}</select></label></div>
            <dl className="unified-source-facts">
              <div><dt>归档名称</dt><dd>{businessText(chosen.display_name || "历史数据归档")}</dd></div>
              <div><dt>覆盖日期</dt><dd>{chosen.date_start} 至 {chosen.date_end}</dd></div>
              <div><dt>原始记录</dt><dd>{fmt(chosen.rows, 0)} 行</dd></div>
              <div><dt>本系统收录时间</dt><dd>{stamp(chosen.ingested_at)}</dd></div>
              <div><dt>与当前观测的关系</dt><dd>{chosen.source_hash === metadata?.source_hash ? "当前页面正在使用的观测版本" : "仅查看归档资料，当前观测不变"}</dd></div>
            </dl>
            <p className="research-help">{businessText(versions.data?.source_policy)}</p>
          </>}
        </Panel>
      )}
    </>
  );
}
