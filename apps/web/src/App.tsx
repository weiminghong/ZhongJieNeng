import { useCallback, useEffect, useState } from "react";
import {
  Activity,
  Database,
  ChartNoAxesCombined,
  Sparkles,
  ClipboardCheck,
  ChevronDown,
  Sun,
  PanelRightOpen,
  Radio,
  GitBranch,
  RefreshCw,
  X,
  ExternalLink,
} from "lucide-react";
import type {
  Bootstrap,
  Scope,
  Theme,
  Overview,
  Mode,
  SourceMode,
} from "./types";
import { query, useResource, time, stamp } from "./api";
import { Drawer, Status } from "./components";
import Forecast from "./Forecast";
import Raw from "./Raw";
import Trading from "./Trading";
import Agent from "./Agent";
import Rsi from "./Rsi";

const tabs = [
  {
    id: "forecast",
    title: "预测与版本对比",
    icon: Activity,
    description: "预测表现、置信区间与同口径评估",
  },
  {
    id: "raw",
    title: "原始数据与血缘",
    icon: Database,
    description: "分时数据、质量与底层证据",
  },
  {
    id: "trading",
    title: "申报策略与收益",
    icon: ChartNoAxesCombined,
    description: "确定性结算与三方案沙盘",
  },
  {
    id: "agent",
    title: "Agent 副驾驶",
    icon: Sparkles,
    description: "双通道工具分析与知识检索",
  },
  {
    id: "rsi",
    title: "偏差审核与 RSI",
    icon: ClipboardCheck,
    description: "人工复核、知识沉淀与生命周期",
  },
] as const;
type Tab = (typeof tabs)[number]["id"];

export default function App() {
  const bootstrap = useResource<Bootstrap>("/api/v1/workbench/bootstrap");
  const [scope, setScope] = useState<Scope>({
    station_id: "lanneng",
    date: "2026-11-20",
    mode: "live",
    source_mode: "synthetic",
  });
  const [tab, setTab] = useState<Tab>("forecast");
  const [theme, setTheme] = useState<Theme>(() =>
    localStorage.getItem("cecep-theme") === "high-contrast-light"
      ? "high-contrast-light"
      : "standard-light",
  );
  const [drawer, setDrawer] = useState(false);
  const [revision, setRevision] = useState(0);
  const [draft, setDraft] = useState("");
  const [cutoffInput, setCutoffInput] = useState("2026-11-20T12:00");
  const overview = useResource<Overview>(
    "/api/v1/workbench/overview?" + query(scope),
    revision,
  );
  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    localStorage.setItem("cecep-theme", theme);
  }, [theme]);
  const selectInterval = useCallback(
    (value: string) => setScope((s) => ({ ...s, selected_interval: value })),
    [],
  );
  const refresh = useCallback(() => setRevision((v) => v + 1), []);
  const toDraft = useCallback((text: string) => {
    setDraft(text);
    setTab("rsi");
    setDrawer(false);
  }, []);
  const station = bootstrap.data?.stations.find(
    (s) => s.station_id === scope.station_id,
  );
  const current = tabs.find((t) => t.id === tab)!;
  function updateContext(update: Partial<Scope>) {
    setScope((s) => ({ ...s, ...update, selected_interval: undefined }));
    setDraft("");
  }
  function setMode(mode: Mode) {
    updateContext({
      mode,
      cutoff_at: mode === "replay" ? cutoffInput + ":00+08:00" : undefined,
    });
  }
  if (bootstrap.loading || bootstrap.error)
    return (
      <div className="startup">
        <h1>中节能 · 光储交易工作台</h1>
        <Status loading={bootstrap.loading} error={bootstrap.error} />
      </div>
    );
  return (
    <div className="app-shell bg-background text-on-surface">
      <header className="global-header bg-surface border-outline">
        <a
          className="brand"
          href="#forecast"
          onClick={() => setTab("forecast")}
        >
          <div className="brand-icon">
            <Activity size={25} />
          </div>
          <div>
            <strong>中节能</strong>
            <span>光储交易工作台</span>
          </div>
        </a>
        <div className="context-fields">
          <label>
            场站
            <div className="select-wrap">
              <select
                aria-label="场站"
                value={scope.station_id}
                onChange={(e) => updateContext({ station_id: e.target.value })}
              >
                {bootstrap.data?.stations.map((s) => (
                  <option key={s.station_id} value={s.station_id}>
                    {s.station_name} · {s.capacity_ac_mw} MW
                  </option>
                ))}
              </select>
              <ChevronDown size={13} />
            </div>
          </label>
          <label>
            交易日
            <input
              type="date"
              aria-label="交易日期"
              value={scope.date}
              onChange={(e) => {
                if (e.target.value) updateContext({ date: e.target.value });
              }}
            />
          </label>
          <label>
            工作模式
            <select
              aria-label="工作模式"
              value={scope.mode}
              onChange={(e) => setMode(e.target.value as Mode)}
            >
              <option value="live">日内实时</option>
              <option value="replay">时点回放</option>
              <option value="post">事后复盘</option>
            </select>
          </label>
          {scope.mode === "replay" && (
            <label>
              cutoff · 北京时间
              <input
                aria-label="回放截止时间"
                type="datetime-local"
                value={cutoffInput}
                onChange={(e) => {
                  setCutoffInput(e.target.value);
                  if (e.target.value)
                    updateContext({ cutoff_at: e.target.value + ":00+08:00" });
                }}
              />
            </label>
          )}
        </div>
        <div className="header-actions">
          <button
            className="theme-button"
            onClick={() =>
              setTheme((v) =>
                v === "standard-light"
                  ? "high-contrast-light"
                  : "standard-light",
              )
            }
            title="切换标准调度浅色 / 高对比演示"
          >
            <Sun size={16} />
            <span>
              {theme === "standard-light" ? "标准调度浅色" : "高对比演示"}
            </span>
          </button>
          <button className="primary-button" onClick={() => setDrawer(true)}>
            <Sparkles size={16} />
            Agent 副驾驶
            <PanelRightOpen size={15} />
          </button>
        </div>
        <div className="header-evidence">
          <span className="read-path">
            <GitBranch size={13} />
            {overview.data?.query_path ||
              (scope.mode === "replay"
                ? "实时 PIT 引擎 · 查询中"
                : "预聚合 serving_* · 查询中")}
          </span>
          <span
            className={`badge ${scope.source_mode === "synthetic" ? "warning" : "success"}`}
          >
            {scope.source_mode === "synthetic"
              ? "合成演示 · 未训练模型"
              : "生产数据"}
          </span>
        </div>
      </header>
      <aside className="sidebar bg-surface">
        <div className="workspace-label">
          <Radio size={14} />
          业务工作区<span>v1.0</span>
        </div>
        <nav aria-label="业务模块">
          {tabs.map((t) => (
            <button
              key={t.id}
              className={`nav-item ${tab === t.id ? "active" : ""}`}
              onClick={() => setTab(t.id)}
              aria-current={tab === t.id ? "page" : undefined}
            >
              <t.icon size={18} />
              <span>{t.title}</span>
            </button>
          ))}
        </nav>
        <div className="sidebar-footer">
          <div className="source-indicator">
            <span className="status-dot" />
            数据库已连接
          </div>
          <p>SQLite WAL · PIT 引擎</p>
          <p>北京时间 · 15 min</p>
          <a
            href={bootstrap.data?.evidently.report_url}
            target="_blank"
            rel="noreferrer"
          >
            Evidently 中文报告
            <ExternalLink size={13} />
          </a>
          <div className="source-note">
            {scope.source_mode === "synthetic"
              ? "合成演示环境\n未接入真实生产数据"
              : "生产数据模式"}
          </div>
        </div>
      </aside>
      <main className="main-content">
        <div className="context-status">
          <span className="read-path">
            <GitBranch size={14} />
            {overview.data?.query_path ||
              (scope.mode === "replay"
                ? "实时 PIT 引擎 · 查询中"
                : "预聚合 serving_* · 查询中")}
          </span>
          <div className="context-badges">
            <label className="source-selector">
              数据口径
              <select
                aria-label="数据口径"
                value={scope.source_mode}
                onChange={(e) =>
                  updateContext({ source_mode: e.target.value as SourceMode })
                }
              >
                <option value="synthetic">合成演示</option>
                <option value="production">生产数据</option>
              </select>
            </label>
            <span
              className={`badge ${scope.source_mode === "synthetic" ? "warning" : "success"}`}
            >
              {scope.source_mode === "synthetic"
                ? "合成演示 · 未训练模型"
                : "生产数据"}
            </span>
          </div>
        </div>
        <div className="page-heading">
          <div>
            <h1>{current.title}</h1>
            <p>
              {station?.station_name || scope.station_id} <span> / </span>
              {scope.date}
              <span> / </span>
              {current.description}
            </p>
          </div>
          <button onClick={refresh} aria-label="刷新数据库数据">
            <RefreshCw size={15} />
            刷新数据
          </button>
        </div>
        <div className="clock-line">
          <span>
            数据时钟 {overview.data ? stamp(overview.data.cutoff_at) : "读取中"}
            （北京时间）
          </span>
          <span>功率 MW · 电量 MWh · 电价 元/MWh</span>
        </div>
        {scope.selected_interval && (
          <div className="selection-bar">
            <span>
              已选时段 <strong>{time(scope.selected_interval)}</strong> ·
              跨模块分析上下文
            </span>
            <div>
              <button onClick={() => setTab("raw")}>查看血缘</button>
              <button onClick={() => setDrawer(true)}>交给 Agent</button>
              <button
                aria-label="清除选中时段"
                onClick={() =>
                  setScope((s) => ({ ...s, selected_interval: undefined }))
                }
              >
                <X size={14} />
              </button>
            </div>
          </div>
        )}
        {tab === "forecast" && (
          <Forecast
            scope={scope}
            data={overview.data}
            loading={overview.loading}
            error={overview.error}
            theme={theme}
            capacity={station?.capacity_ac_mw || 0}
            onSelect={selectInterval}
            onRaw={() => setTab("raw")}
            revision={revision}
          />
        )}
        {tab === "raw" && (
          <Raw
            scope={scope}
            selected={scope.selected_interval}
            onSelect={selectInterval}
            reportUrl={bootstrap.data?.evidently.report_url || ""}
            revision={revision}
          />
        )}
        {tab === "trading" && (
          <Trading
            scope={scope}
            theme={theme}
            revision={revision}
            onRefresh={refresh}
          />
        )}
        {tab === "agent" && (
          <section className="panel agent-page">
            <Agent
              scope={scope}
              llmMode={bootstrap.data!.llm_mode}
              onDraft={toDraft}
            />
          </section>
        )}
        {tab === "rsi" && (
          <Rsi
            scope={scope}
            revision={revision}
            onRefresh={refresh}
            draft={draft}
            onSelect={selectInterval}
          />
        )}
        <footer className="page-footer">
          <span>中节能光储交易工作台 · 证据可追溯，口径可核验</span>
          <span>未连接外部大模型时，仅使用确定性工具与知识检索</span>
        </footer>
      </main>
      {drawer && (
        <Drawer title="随行 Agent 副驾驶" onClose={() => setDrawer(false)}>
          <Agent
            scope={scope}
            llmMode={bootstrap.data!.llm_mode}
            onDraft={toDraft}
          />
        </Drawer>
      )}
    </div>
  );
}
