import { useState } from "react";
import { Download, ExternalLink, Search } from "lucide-react";
import type { Scope, Overview, Lineage } from "./types";
import { query, useResource, fmt, time, stamp } from "./api";
import { Drawer, Panel, Status } from "./components";
import BusinessFacts from "./BusinessFacts";
import { fieldLabel, stateLabel } from "./presentation";

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
    <Drawer title={`${time(interval)} · 原始数据来源`} onClose={onClose}>
      <div className="drawer-body">
        <Status loading={result.loading} error={result.error} />
        {result.data && (
          <>
            <p className="muted">截止时点：{stamp(result.data.cutoff_at)}</p>
            {result.data.evidence.map((e, i) => (
              <section key={i} className="evidence">
                <h3>{fieldLabel(e.reference.table)}</h3>
                <p
                  className={`badge ${e.available_before_cutoff ? "success" : "warning"}`}
                >
                  {e.available_before_cutoff ? "查询时已可用" : "晚于查询时点"}
                </p>
                <p>数据可用时间：{stamp(e.reference.available_at)}</p>
                <BusinessFacts value={e.record} />
                {e.feature_inputs && (
                  <p>本次使用 {e.feature_inputs.length} 项已保存输入。</p>
                )}
              </section>
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
  capacity,
}: {
  scope: Scope;
  selected?: string;
  onSelect: (s: string) => void;
  reportUrl: string;
  revision: number;
  capacity: number;
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
      (quality === "all" ||
        (quality === "exceeded"
          ? r.actual_mw !== null &&
            r.da_forecast_mw !== null &&
            Math.abs(r.actual_mw - r.da_forecast_mw) > capacity * 0.05
          : r.quality_flag === quality)) &&
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
    ] as const;
    const escape = (v: unknown) =>
      '"' + String(v ?? "").replaceAll('"', '""') + '"';
    const blob = new Blob(
      [
        "\ufeff" +
          fields.map(fieldLabel).join(",") +
          "\r\n" +
          filtered
            .map((r) =>
              fields
                .map((f) =>
                  escape(f === "quality_flag" ? stateLabel(r[f]) : r[f]),
                )
                .join(","),
            )
            .join("\r\n"),
      ],
      { type: "text/csv;charset=utf-8;" },
    );
    const url = URL.createObjectURL(blob),
      a = document.createElement("a");
    a.href = url;
    a.download = `场站数据-${scope.date}.csv`;
    a.click();
    URL.revokeObjectURL(url);
  }
  return (
    <>
      <div className="presentation-metrics">
        <div>
          <span>有效实测率</span>
          <strong>
            {result.data?.kpi?.observed_count ?? "—"} /{" "}
            {result.data?.kpi?.due_count ?? "—"}
          </strong>
          <small>有效实测 / 应到时段</small>
        </div>
        <div>
          <span>应到缺测时段</span>
          <strong className="text-warning">
            {result.data?.kpi?.missing_count ?? "—"}
          </strong>
          <small>未来待到达单独标记</small>
        </div>
        <div>
          <span>漂移预警特征</span>
          <strong>
            {result.data?.drift?.[0]?.drifted_feature_count ?? "—"} /{" "}
            {result.data?.drift?.[0]?.total_feature_count ?? "—"}
          </strong>
          <small>合成漂移场景示例</small>
        </div>
        <div>
          <span>按查询时点溯源</span>
          <strong>输入可追溯</strong>
          <a href={reportUrl} target="_blank" rel="noreferrer">
            中文 Evidently 报告 <ExternalLink size={12} />
          </a>
        </div>
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
          <div
            className="teaching-analytics-tabs"
            role="group"
            aria-label="质量筛选"
          >
            {[
              ["all", "全部"],
              ["valid", "有效"],
              ["missing", "缺测"],
              ["pending", "待到达"],
              ["exceeded", "超阈"],
            ].map(([value, label]) => (
              <button
                key={value}
                aria-pressed={quality === value}
                onClick={() => setQuality(value)}
              >
                {label}
              </button>
            ))}
          </div>
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
            <table className="presentation-table">
              <thead>
                <tr>
                  <th>时段 / 北京时间</th>
                  <th>实测 MW</th>
                  <th>日前 MW</th>
                  <th>日内 MW</th>
                  <th>日前价</th>
                  <th>实时价</th>
                  <th>价差 元/MWh</th>
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
