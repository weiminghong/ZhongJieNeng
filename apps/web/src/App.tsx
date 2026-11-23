import { useCallback, useEffect, useState } from "react";
import {
  Activity,
  Database,
  ChartNoAxesCombined,
  Sparkles,
  ClipboardCheck,
  ChevronRight,
  CalendarDays,
  Building2,
  Clock3,
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
  Inference,
} from "./types";
import { query, useResource, time, stamp } from "./api";
import { Drawer, Status } from "./components";
import Forecast from "./Forecast";
import Raw from "./Raw";
import Trading from "./Trading";
import Agent from "./Agent";
import Rsi from "./Rsi";
import ProactiveBriefs from "./ProactiveBriefs";

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
    title: "智能体助手",
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
    date: "",
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
  const [overlay, setOverlay] = useState<Inference | null>(null);
  useEffect(() => setOverlay(null), [scope.station_id, scope.date, scope.mode, scope.cutoff_at, scope.source_mode]);
  const showOverlay = useCallback((data: Inference) => {
    setOverlay(data); setTab("forecast"); setDrawer(false);
  }, []);
  const [cutoffTime, setCutoffTime] = useState("12:00");
  const validDate = !!bootstrap.data?.dates.includes(scope.date);
  const overview = useResource<Overview>(
    validDate ? "/api/v1/workbench/overview?" + query(scope) : null,
    revision,
  );
  useEffect(() => {
    if (overlay && overview.data && overlay.cutoff_at !== overview.data.cutoff_at) setOverlay(null);
  }, [overlay, overview.data]);
  useEffect(() => {
    const b = bootstrap.data;
    if (b && !b.dates.includes(scope.date))
      setScope((s) => ({
        ...s,
        date: b.dates.includes(b.default_date)
          ? b.default_date
          : b.dates[0] || "",
      }));
  }, [bootstrap.data, scope.date]);
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
    if (update.date && !bootstrap.data?.dates.includes(update.date)) return;
    setScope((s) => ({
      ...s,
      ...update,
      ...(update.date && s.mode === "replay"
        ? { cutoff_at: update.date + "T" + cutoffTime + ":00+08:00" }
        : {}),
      selected_interval: undefined,
    }));
    setDraft("");
  }
  function setMode(mode: Mode) {
    updateContext({
      mode,
      cutoff_at:
        mode === "replay"
          ? scope.date + "T" + cutoffTime + ":00+08:00"
          : undefined,
    });
  }
  if (bootstrap.loading || bootstrap.error)
    return (
      <div className="startup">
        <h1>中节能 · 光储交易工作台</h1>
        <Status loading={bootstrap.loading} error={bootstrap.error} />
      </div>
    );
  const dates = bootstrap.data?.dates || [];
  return (
    <div className="app-shell bg-background text-on-surface">
      <header className="app-switcher">
        <a
          className="brand"
          href="#forecast"
          onClick={() => setTab("forecast")}
        >
          <span className="brand-icon">
            <Activity size={24} />
          </span>
          <strong>中节能</strong>
          <span className="brand-divider" />
          <span className="product-name">光储交易工作台</span>
        </a>
        <div className="banner-facts">
          <label className="start-banner-fact-card">
            <Building2 aria-hidden="true" />
            <span>
              <small>场站</small>
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
            </span>
          </label>
          <label className="start-banner-fact-card date-fact">
            <CalendarDays aria-hidden="true" />
            <span>
              <small>交易日 · 仅可用日期</small>
              <span className="available-date-control">
                {dates.length > 5 && (
                  <button
                    aria-label="上一个可用交易日"
                    disabled={dates.indexOf(scope.date) <= 0}
                    onClick={() =>
                      updateContext({
                        date: dates[dates.indexOf(scope.date) - 1],
                      })
                    }
                  >
                    ‹
                  </button>
                )}
                <select
                  aria-label="交易日期"
                  value={scope.date}
                  onChange={(e) => updateContext({ date: e.target.value })}
                  disabled={!dates.length}
                >
                  {!dates.length && <option value="">暂无可用日期</option>}
                  {dates.map((d) => (
                    <option key={d} value={d}>
                      {d.slice(5)}{" "}
                      {d < bootstrap.data!.default_date
                        ? "历史"
                        : d === bootstrap.data!.default_date
                          ? `日内 ${time(bootstrap.data!.data_clock)}`
                          : "日前"}
                    </option>
                  ))}
                </select>
                {dates.length > 5 && (
                  <button
                    aria-label="下一个可用交易日"
                    disabled={dates.indexOf(scope.date) >= dates.length - 1}
                    onClick={() =>
                      updateContext({
                        date: dates[dates.indexOf(scope.date) + 1],
                      })
                    }
                  >
                    ›
                  </button>
                )}
              </span>
            </span>
          </label>
          <label className="start-banner-fact-card">
            <Radio aria-hidden="true" />
            <span>
              <small>工作模式</small>
              <select
                aria-label="工作模式"
                value={scope.mode}
                onChange={(e) => setMode(e.target.value as Mode)}
              >
                <option value="live">日内实时</option>
                <option value="replay">时点回放</option>
                <option value="post">事后复盘</option>
              </select>
            </span>
          </label>
          {scope.mode === "replay" && (
            <label className="start-banner-fact-card cutoff-fact">
              <Clock3 aria-hidden="true" />
              <span>
                <small>截止时间 · 北京时间</small>
                <input
                  aria-label="回放截止时间"
                  type="time"
                  value={cutoffTime}
                  onChange={(e) => {
                    if (!e.target.value) return;
                    setCutoffTime(e.target.value);
                    updateContext({
                      cutoff_at:
                        scope.date + "T" + e.target.value + ":00+08:00",
                    });
                  }}
                />
              </span>
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
            aria-label="切换标准浅色与高对比"
          >
            <Sun size={16} />
            <span>{theme === "standard-light" ? "标准浅色" : "高对比"}</span>
          </button>
          <button className="primary-button" onClick={() => setDrawer(true)}>
            <Sparkles size={16} />
            智能体助手
            <PanelRightOpen size={15} />
          </button>
        </div>
      </header>
      <aside className="admin-center-sidebar">
        <div className="workspace-label">
          <Radio size={16} />
          业务工作区<span>v1.0</span>
        </div>
        <nav className="admin-center-navigation" aria-label="业务模块">
          {(
            [
              { id: "business", title: "业务分析", items: tabs.slice(0, 3) },
              { id: "governance", title: "智能与治理", items: tabs.slice(3) },
            ] as const
          ).map((group) => (
            <section className="admin-center-nav-group" key={group.id}>
              <div className="admin-center-section-toggle">{group.title}</div>
              <div
                className="admin-center-subsection-list"
                id={`nav-${group.id}`}
              >
                {group.items.map((t) => (
                  <button
                    key={t.id}
                    className={tab === t.id ? "is-active" : ""}
                    aria-current={tab === t.id ? "page" : undefined}
                    onClick={() => setTab(t.id)}
                  >
                    <span className="admin-center-nav-icon">
                      <t.icon size={22} />
                    </span>
                    <span className="admin-center-nav-copy">
                      <strong>{t.title}</strong>
                      <small>{t.description}</small>
                    </span>
                    <ChevronRight size={14} />
                  </button>
                ))}
              </div>
            </section>
          ))}
        </nav>
        <div className="sidebar-footer">
          <div className="source-indicator">
            <span className="status-dot" />
            数据库已连接
          </div>
          <p>SQLite WAL · PIT 时点引擎</p>
          <a
            href={bootstrap.data?.evidently.report_url}
            target="_blank"
            rel="noreferrer"
          >
            Evidently 中文报告
            <ExternalLink size={13} />
          </a>
          <small>{bootstrap.data?.evidently.status}</small>
          <div className="source-note">
            {scope.source_mode === "synthetic"
              ? "合成演示 · 未训练模型"
              : "生产数据模式"}
          </div>
        </div>
      </aside>
      <main className="admin-center-main">
        <header className="admin-center-header">
          <div className="page-heading">
            <span className="admin-center-page-icon">
              <current.icon size={24} />
            </span>
            <div>
              <h1>{current.title}</h1>
              <p>
                {station?.station_name || scope.station_id} · {scope.date} ·{" "}
                {current.description}
              </p>
            </div>
          </div>
          <div className="workspace-evidence">
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
              <button onClick={refresh} aria-label="刷新数据库数据">
                <RefreshCw size={14} />
                刷新
              </button>
            </div>
            <span className="read-path" title={overview.data?.query_path}>
              <GitBranch size={13} />
              {scope.mode === "replay" ? "实时 PIT 引擎" : "预聚合宽表"} ·{" "}
              {scope.source_mode === "synthetic" ? "合成演示" : "生产"}
            </span>
            <small>
              数据时钟{" "}
              {overview.data ? stamp(overview.data.cutoff_at) : "读取中"} ·
              北京时间
            </small>
          </div>
        </header>
        <div className="admin-center-content presentation-polished">
          {validDate && <ProactiveBriefs scope={scope} compact onEnter={() => setTab("agent")} onDraft={(text, interval) => { if (interval) selectInterval(interval); toDraft(text); }} />}
          {scope.source_mode === "production" ? (
            <section className="production-readiness panel" role="status">
              <div className="readiness-heading">
                <Database size={28} />
                <div>
                  <h2>生产数据接入就绪状态</h2>
                  <p>当前暂无生产记录，等待真实数据源接入后开始业务分析。</p>
                </div>
              </div>
              <div className="presentation-metrics">
                <div>
                  <span>源端数据库</span>
                  <strong>等待接入</strong>
                  <small>10 号服务器 · energy_poc</small>
                </div>
                <div>
                  <span>真实数据适配器</span>
                  <strong>待配置</strong>
                  <small>实测、气象、价格与合同</small>
                </div>
                <div>
                  <span>时点与质量校验</span>
                  <strong>等待数据</strong>
                  <small>available_at 与批次血缘核验</small>
                </div>
                <div>
                  <span>当前口径</span>
                  <strong>production</strong>
                  <small>真实数据尚未提供</small>
                </div>
              </div>
              <button
                className="primary-button"
                onClick={() => updateContext({ source_mode: "synthetic" })}
              >
                切回合成演示
              </button>
            </section>
          ) : !validDate ? (
            <Status empty />
          ) : (
            <>
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
                        setScope((s) => ({
                          ...s,
                          selected_interval: undefined,
                        }))
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
                  onDateChange={(d) => updateContext({ date: d })}
                  revision={revision}
                  overlay={overlay}
                  onOverlay={showOverlay}
                  onClearOverlay={() => setOverlay(null)}
                />
              )}
              {tab === "raw" && (
                <Raw
                  scope={scope}
                  capacity={station?.capacity_ac_mw || 0}
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
                  onDateChange={(d) => updateContext({ date: d })}
                />
              )}
              {tab === "agent" && (
                <section className="panel agent-page">
                  <Agent
                    scope={scope}
                    theme={theme}
                    onOverlay={showOverlay}
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
            </>
          )}
          <footer className="page-footer">
            <span>中节能光储交易工作台 · 证据可追溯，口径可核验</span>
            <span>{bootstrap.data?.llm_mode} · 工具计算与知识证据可追溯</span>
          </footer>
        </div>
      </main>
      {drawer && (
        <Drawer title="随行智能体" onClose={() => setDrawer(false)}>
          <Agent
            scope={scope}
            theme={theme}
            onOverlay={showOverlay}
            llmMode={bootstrap.data!.llm_mode}
            onDraft={toDraft}
          />
        </Drawer>
      )}
    </div>
  );
}
