import { useState } from "react";
import { Download, ExternalLink, Search, Database } from "lucide-react";
import type { Scope, Overview, Lineage } from "./types";
import { query, useResource, fmt, time, stamp } from "./api";
import { Drawer, Panel, Status } from "./components";

function LineagePanel({
  scope,
  interval,
  onClose,
}: {
  scope: Scope;
  interval: string;
  onClose: () => void;
}) {
  const result = useResource<Lineage>(
    "/api/v1/workbench/lineage?" +
      query(scope) +
      "&interval_start=" +
      encodeURIComponent(interval),
  );
  return (
    <Drawer title={`${time(interval)} · L1 数据血缘`} onClose={onClose}>
      <div className="drawer-body">
        <Status loading={result.loading} error={result.error} />
        {result.data && (
          <>
            <p className="muted">截止时点：{stamp(result.data.cutoff_at)}</p>
            {result.data.evidence.map((e, i) => (
              <details key={i} className="evidence" open={i === 0}>
                <summary>
                  <Database size={14} />
                  <strong>{e.reference.table}</strong>
                  <span
                    className={`badge ${e.available_before_cutoff ? "success" : "error"}`}
                  >
                    {e.available_before_cutoff ? "时点可见" : "晚于 cutoff"}
                  </span>
                </summary>
                <dl>
                  <dt>record_id</dt>
                  <dd>{e.reference.record_id}</dd>
                  <dt>source_id</dt>
                  <dd>
                    {String(
                      e.record?.source_id ??
                        "见 prediction_run / feature_inputs",
                    )}
                  </dd>
                  <dt>batch_id</dt>
                  <dd>{String(e.record?.batch_id ?? "见输入快照")}</dd>
                  <dt>available_at ≤ cutoff_at</dt>
                  <dd>{stamp(e.reference.available_at)}</dd>
                </dl>
                <pre>{JSON.stringify(e.record, null, 2)}</pre>
                {e.feature_inputs && (
                  <details>
                    <summary>
                      输入快照血缘 · {e.feature_inputs.length} 条
                    </summary>
                    <pre>{JSON.stringify(e.feature_inputs, null, 2)}</pre>
                  </details>
                )}
              </details>
            ))}
          </>
        )}
      </div>
    </Drawer>
  );
}

export default function Raw({
  scope,
  selected,
  onSelect,
  reportUrl,
  revision,
}: {
  scope: Scope;
  selected?: string;
  onSelect: (s: string) => void;
  reportUrl: string;
  revision: number;
}) {
  const [search, setSearch] = useState("");
  const [quality, setQuality] = useState("all");
  const [lineage, setLineage] = useState<string | null>(null);
  const result = useResource<Overview>(
    "/api/v1/workbench/raw?" + query(scope),
    revision,
  );
  const filtered = (result.data?.intervals || []).filter(
    (r) =>
      (quality === "all" || r.quality_flag === quality) &&
      (!search ||
        [
          time(r.interval_start),
          r.quality_flag,
          r.actual_mw,
          r.da_forecast_mw,
          r.cloud_cover_pct,
        ]
          .join(" ")
          .toLowerCase()
          .includes(search.toLowerCase())),
  );
  function exportCsv() {
    const fields = [
      "interval_start",
      "actual_mw",
      "da_forecast_mw",
      "id_corrected_mw",
      "da_price",
      "rt_price",
      "spread_yuan_mwh",
      "ghi_wm2",
      "cloud_cover_pct",
      "quality_flag",
      "lineage_refs_json",
    ] as const;
    const escape = (v: unknown) =>
      '"' + String(v ?? "").replaceAll('"', '""') + '"';
    const blob = new Blob(
      [
        "\ufeff" +
          fields.join(",") +
          "\r\n" +
          filtered
            .map((r) => fields.map((f) => escape(r[f])).join(","))
            .join("\r\n"),
      ],
      { type: "text/csv;charset=utf-8;" },
    );
    const url = URL.createObjectURL(blob),
      a = document.createElement("a");
    a.href = url;
    a.download = `${scope.station_id}-${scope.date}-filtered.csv`;
    a.click();
    URL.revokeObjectURL(url);
  }
  return (
    <>
      <div className="quality-strip">
        <div>
          <strong>{result.data?.kpi?.missing_count ?? "—"}</strong>
          <span>实测缺失时段</span>
        </div>
        <div>
          <strong>
            {result.data?.drift?.[0]?.drifted_feature_count ?? "—"} /{" "}
            {result.data?.drift?.[0]?.total_feature_count ?? "—"}
          </strong>
          <span>合成漂移特征示例</span>
        </div>
        <div>
          <strong>PIT</strong>
          <span>按可用时间追溯输入</span>
        </div>
        <a className="button" href={reportUrl} target="_blank" rel="noreferrer">
          <ExternalLink size={15} />
          中文 Evidently 报告
        </a>
      </div>
      <Panel
        title="原始分时数据与证据"
        subtitle="实测缺失、未来待到达、真实零值分开显示。点击任意行查阅来源、批次与气象关联。"
        action={
          <button onClick={exportCsv} disabled={!filtered.length}>
            <Download size={15} />
            导出筛选 CSV
          </button>
        }
      >
        <div className="table-toolbar">
          <label className="search-field">
            <Search size={16} />
            <input
              aria-label="搜索原始数据"
              placeholder="搜索时间、数值或质量标记"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
            />
          </label>
          <select
            aria-label="质量筛选"
            value={quality}
            onChange={(e) => setQuality(e.target.value)}
          >
            <option value="all">全部质量</option>
            <option value="valid">有效实测</option>
            <option value="missing">应到缺测</option>
            <option value="pending">未来待到达</option>
          </select>
          <span className="muted">
            {filtered.length} / {result.data?.intervals.length ?? 0} 条
          </span>
        </div>
        <Status
          loading={result.loading}
          error={result.error}
          empty={!result.loading && !result.error && !filtered.length}
        />
        {!!filtered.length && (
          <div className="table-wrap raw-table">
            <table>
              <thead>
                <tr>
                  <th>时段 / 北京时间</th>
                  <th>实测 MW</th>
                  <th>日前 MW</th>
                  <th>日内 MW</th>
                  <th>日前价</th>
                  <th>实时价</th>
                  <th>Δ 元/MWh</th>
                  <th>辐照 W/m²</th>
                  <th>云量 %</th>
                  <th>状态</th>
                  <th>血缘</th>
                </tr>
              </thead>
              <tbody>
                {filtered.map((r) => (
                  <tr
                    key={r.interval_start}
                    className={
                      selected === r.interval_start ? "selected-row" : ""
                    }
                    onClick={() => {
                      onSelect(r.interval_start);
                      setLineage(r.interval_start);
                    }}
                  >
                    <td>
                      <button
                        className="link-button"
                        onClick={(e) => {
                          e.stopPropagation();
                          onSelect(r.interval_start);
                          setLineage(r.interval_start);
                        }}
                      >
                        {time(r.interval_start)}—{time(r.interval_end)}
                      </button>
                    </td>
                    <td>{fmt(r.actual_mw)}</td>
                    <td>{fmt(r.da_forecast_mw)}</td>
                    <td>{fmt(r.id_corrected_mw)}</td>
                    <td>{fmt(r.da_price)}</td>
                    <td>{fmt(r.rt_price)}</td>
                    <td>{fmt(r.spread_yuan_mwh)}</td>
                    <td>{fmt(r.ghi_wm2, 1)}</td>
                    <td>{fmt(r.cloud_cover_pct, 0)}</td>
                    <td>
                      <span
                        className={`badge ${r.quality_flag === "valid" ? "success" : r.quality_flag === "missing" ? "warning" : ""}`}
                      >
                        {r.quality_flag === "valid"
                          ? "有效"
                          : r.quality_flag === "missing"
                            ? "应到缺测"
                            : "待到达"}
                      </span>
                    </td>
                    <td>{JSON.parse(r.lineage_refs_json).length} 条</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Panel>
      {lineage && (
        <LineagePanel
          scope={scope}
          interval={lineage}
          onClose={() => setLineage(null)}
        />
      )}
    </>
  );
}
