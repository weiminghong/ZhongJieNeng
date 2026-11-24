import { useCallback, useEffect, useState } from "react";
import {
  Activity,
  Database,
  ChartNoAxesCombined,
  Sparkles,
  ClipboardCheck,
  Sun,
  RefreshCw,
  Settings2,
  ChevronRight,
  ExternalLink,
  X,
  PanelRightOpen,
  Cable,
} from "lucide-react";
import type {
  Bootstrap,
  Scope,
  Theme,
  Overview,
  Mode,
  SourceMode,
  Inference,
  Readiness,
} from "./types";
import { query, useResource, time, stamp } from "./api";
import { Drawer, Status } from "./components";
import Forecast from "./Forecast";
import Raw from "./Raw";
import Trading from "./Trading";
import Agent from "./Agent";
import Rsi from "./Rsi";
import ContextRail from "./ContextRail";
import ConnectionStatus from "./ConnectionStatus";
import PublicWorkspace from "./PublicWorkspace";

const tabs = [
  {
    id: "forecast",
    title: "预测分析",
    icon: Activity,
    description: "光伏预测与版本对比",
  },
  {
    id: "raw",
    title: "数据与血缘",
    icon: Database,
    description: "原始记录与来源追溯",
  },
  {
    id: "trading",
    title: "交易策略",
    icon: ChartNoAxesCombined,
    description: "申报方案与收益沙盘",
  },
  {
    id: "agent",
    title: "智能体助手",
    icon: Sparkles,
    description: "业务分析与工具证据",
  },
  {
    id: "rsi",
    title: "模型与审核",
    icon: ClipboardCheck,
    description: "偏差复核与模型审批",
  },
  {
    id: "connections",
    title: "接入状态",
    icon: Cable,
    description: "数据、模型与业务能力",
  },
] as const;
type Tab = (typeof tabs)[number]["id"];
const publicTitles: Record<Tab, string> = {
  forecast: "量价分析",
  raw: "原始数据",
  trading: "价差情景",
  agent: "数据分析",
  rsi: "人工复核",
  connections: "来源与流程",
};

export default function App() {
  const [workspace, setWorkspace] = useState(() =>
    new URLSearchParams(location.search).get("workspace") === "site" ||
    (!new URLSearchParams(location.search).has("workspace") &&
      localStorage.getItem("cecep-data-workspace") === "site")
      ? "site"
      : "public",
  );
  const publicActive = workspace === "public";
  const [scope, setScope] = useState<Scope>({
    station_id: "lanneng",
    date: "",
    mode: "live",
    source_mode: "synthetic",
  });
  const [revision, setRevision] = useState(0);
  const bootstrap = useResource<Bootstrap>(
    `/api/v1/workbench/bootstrap?station_id=${encodeURIComponent(scope.station_id)}&source_mode=${scope.source_mode}`,
    revision,
    !publicActive && scope.mode === "live" && scope.source_mode === "production"
      ? 30000
      : 0,
  );
  const readiness = useResource<Readiness>(
    `/api/v1/workbench/readiness?station_id=${encodeURIComponent(scope.station_id)}&source_mode=${scope.source_mode}`,
    revision,
  );
  const [tab, setTab] = useState<Tab>(() => {
    const value = new URLSearchParams(location.search).get("tab");
    return tabs.some((t) => t.id === value) ? (value as Tab) : "forecast";
  });
  const [theme, setTheme] = useState<Theme>(() =>
    localStorage.getItem("cecep-theme") === "high-contrast-light"
      ? "high-contrast-light"
      : "standard-light",
  );
  const [drawer, setDrawer] = useState(false);
  const [draft, setDraft] = useState("");
  const [overlay, setOverlay] = useState<Inference | null>(null);
  const [cutoffTime, setCutoffTime] = useState("12:00");
  const validDate = !!bootstrap.data?.dates.includes(scope.date);
  const overview = useResource<Overview>(
    validDate && !publicActive
      ? "/api/v1/workbench/overview?" + query(scope)
      : null,
    revision,
    !publicActive && scope.mode === "live" && scope.source_mode === "production"
      ? 30000
      : 0,
  );
  useEffect(
    () => setOverlay(null),
    [
      scope.station_id,
      scope.date,
      scope.mode,
      scope.cutoff_at,
      scope.source_mode,
    ],
  );
  useEffect(() => {
    localStorage.setItem("cecep-data-workspace", workspace);
    setDrawer(false);
  }, [workspace]);
  useEffect(() => {
    const url = new URL(location.href);
    url.searchParams.set("workspace", workspace);
    url.searchParams.set("tab", tab);
    window.history.replaceState(null, "", url);
  }, [workspace, tab]);
  useEffect(() => {
    const b = bootstrap.data;
    if (b && !b.dates.includes(scope.date)) {
      const date = b.dates.includes(b.default_date)
        ? b.default_date
        : b.dates[0] || "";
      setScope((s) => ({
        ...s,
        date,
        selected_interval: undefined,
        cutoff_at:
          s.mode === "replay" && date
            ? `${date}T${cutoffTime}:00+08:00`
            : undefined,
      }));
    }
  }, [bootstrap.data, scope.date, cutoffTime]);
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
  const showOverlay = useCallback((value: Inference) => {
    setOverlay(value);
    setTab("forecast");
    setDrawer(false);
  }, []);
  function updateContext(update: Partial<Scope>) {
    setScope((s) => ({
      ...s,
      ...update,
      ...(update.date && s.mode === "replay"
        ? { cutoff_at: `${update.date}T${cutoffTime}:00+08:00` }
        : {}),
      selected_interval: undefined,
    }));
    setDraft("");
  }
  function changeMode(mode: Mode) {
    updateContext({
      mode,
      cutoff_at:
        mode === "replay" ? `${scope.date}T${cutoffTime}:00+08:00` : undefined,
    });
  }
  const station = bootstrap.data?.stations.find(
    (s) => s.station_id === scope.station_id,
  );
  const current = tabs.find((t) => t.id === tab)!;
  const llmMode = bootstrap.data?.llm_mode || "deterministic_tools_only";
  const noData = !!bootstrap.data && !bootstrap.data.dates.length;
  return (
    <div className="energy-shell">
      <aside className="energy-sidebar" aria-label="业务导航">
        <a
          className="energy-brand"
          href="#forecast"
          onClick={() => setTab("forecast")}
        >
          <Sun size={26} aria-hidden="true" />
          <strong>
            中节能<span>光伏交易工作台</span>
          </strong>
        </a>
        <nav>
          {tabs.map((t) => (
            <button
              key={t.id}
              className={tab === t.id ? "is-active" : ""}
              aria-current={tab === t.id ? "page" : undefined}
              onClick={() => setTab(t.id)}
            >
              <t.icon size={19} />
              <span>{publicActive ? publicTitles[t.id] : t.title}</span>
              <ChevronRight size={14} />
            </button>
          ))}
        </nav>
        <div className="energy-sidebar-bottom">
          <div className="solar-sign" aria-hidden="true">
            <Sun size={28} />
            <span />
            <span />
            <span />
          </div>
          <p>光伏量价 · 证据相随</p>
          <a href="/settings">
            <Settings2 size={15} /> 模型与连接设置
          </a>
          {bootstrap.data?.evidently.report_url && (
            <a
              href={bootstrap.data.evidently.report_url}
              target="_blank"
              rel="noreferrer"
            >
              <ExternalLink size={14} /> 外部监测报告
            </a>
          )}
          <small>报告内容需独立核验</small>
        </div>
      </aside>
      <main className="energy-main">
        <header className="energy-heading">
          <div className="energy-page-title">
            <current.icon size={21} />
            <h1>
              {publicActive
                ? `公开市场研究 · ${publicTitles[current.id]}`
                : current.description}
            </h1>
            <span
              className={`badge ${publicActive ? "info" : scope.source_mode === "synthetic" ? "warning" : "info"}`}
            >
              {publicActive
                ? "山东公开历史数据"
                : scope.source_mode === "synthetic"
                  ? "合成演示"
                  : "生产口径"}
            </span>
          </div>
          <div className="energy-actions">
            <button
              onClick={refresh}
              aria-label="检查数据更新"
              title="重新读取源文件或数据库的当前状态"
            >
              <RefreshCw size={16} />
            </button>
            <button
              onClick={() =>
                setTheme(
                  theme === "standard-light"
                    ? "high-contrast-light"
                    : "standard-light",
                )
              }
            >
              {theme === "standard-light" ? "高对比" : "标准显示"}
            </button>
            <button
              onClick={() => (publicActive ? setTab("agent") : setDrawer(true))}
              disabled={!publicActive && !validDate}
            >
              <PanelRightOpen size={16} />
              {publicActive ? "打开数据分析" : "随行智能体"}
            </button>
          </div>
        </header>
        <div className="energy-filters" aria-label="分析范围">
          <label>
            <span>数据工作区</span>
            <select
              aria-label="数据工作区"
              value={workspace}
              onChange={(e) => setWorkspace(e.target.value)}
            >
              <option value="public">公开市场研究（山东）</option>
              <option value="site">场站工作台（镇海）</option>
            </select>
          </label>
          {publicActive ? (
            <p className="workspace-scope-help">
              使用已有公开数据完成历史研究；场站生产、合成演示和公开市场数据分别标识。
            </p>
          ) : (
            <>
              <label>
                <span>光伏场站</span>
                <select
                  aria-label="场站"
                  value={scope.station_id}
                  onChange={(e) =>
                    updateContext({ station_id: e.target.value })
                  }
                >
                  {bootstrap.data?.stations.map((s) => (
                    <option key={s.station_id} value={s.station_id}>
                      {s.station_name} · {s.capacity_ac_mw} MW
                    </option>
                  ))}
                  {!bootstrap.data && (
                    <option value={scope.station_id}>{scope.station_id}</option>
                  )}
                </select>
              </label>
              <label>
                <span>交易日期</span>
                <select
                  aria-label="交易日期"
                  value={scope.date}
                  onChange={(e) => updateContext({ date: e.target.value })}
                  disabled={!bootstrap.data?.dates.length}
                >
                  {!bootstrap.data?.dates.length && (
                    <option value="">暂无可用日期</option>
                  )}
                  {bootstrap.data?.dates.map((d) => (
                    <option key={d} value={d}>
                      {d}
                    </option>
                  ))}
                </select>
              </label>
              <label>
                <span>查看方式</span>
                <select
                  aria-label="工作模式"
                  value={scope.mode}
                  onChange={(e) => changeMode(e.target.value as Mode)}
                >
                  <option value="live">监测已到达数据</option>
                  <option value="post">事后复盘</option>
                  <option value="replay">时点回放</option>
                </select>
              </label>
              {scope.mode === "replay" && (
                <label>
                  <span>截止时间</span>
                  <input
                    aria-label="回放截止时间"
                    type="time"
                    step="900"
                    value={cutoffTime}
                    onChange={(e) => {
                      if (!e.target.value) return;
                      setCutoffTime(e.target.value);
                      updateContext({
                        cutoff_at: `${scope.date}T${e.target.value}:00+08:00`,
                      });
                    }}
                  />
                </label>
              )}
              <label>
                <span>数据口径</span>
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
              <div className="energy-clock">
                <span className="status-dot" />
                {overview.data
                  ? `数据截止 ${stamp(overview.data.cutoff_at)}`
                  : "按所选范围读取"}
                <small>北京时间 · 15 分钟</small>
              </div>
            </>
          )}
        </div>
        <div className="energy-scroll">
          {publicActive ? (
            <PublicWorkspace
              tab={tab}
              onNavigate={setTab}
              theme={theme}
              revision={revision}
            />
          ) : (
            <>
              <div className="energy-source-notice">
                <span>
                  {scope.source_mode === "synthetic"
                    ? "当前为合成演示，预测、参考规则与收益均不代表生产效果。"
                    : "生产口径仅显示真实到达记录，缺失输入不补造。"}
                </span>
                <button onClick={() => setTab("connections")}>
                  查看接入状态
                  <ChevronRight size={13} />
                </button>
              </div>
              <Status loading={bootstrap.loading} error={bootstrap.error} />
              {!bootstrap.loading && !bootstrap.error && (
                <>
                  {tab === "connections" ? (
                    <ConnectionStatus resource={readiness} />
                  ) : noData ? (
                    <section className="connection-empty">
                      <Database size={32} />
                      <h2>
                        当前场站尚无
                        {scope.source_mode === "production" ? "生产" : "合成"}
                        记录
                      </h2>
                      <p>
                        接入状态按数据库实时核验；现有演示数据不会混入生产口径。
                      </p>
                      <button
                        className="primary-button"
                        onClick={() => setTab("connections")}
                      >
                        查看数据与模型接入
                      </button>
                    </section>
                  ) : (
                    <div
                      className={`energy-workspace ${tab === "forecast" ? "with-context" : ""}`}
                    >
                      <div className={`workspace-page workspace-page--${tab}`}>
                        {scope.selected_interval && tab !== "forecast" && (
                          <div className="selection-bar">
                            <span>
                              已选 {time(scope.selected_interval)} ·
                              上下文跨模块保留
                            </span>
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
                        )}
                        {tab === "forecast" && validDate && (
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
                        {tab === "raw" && validDate && (
                          <Raw
                            scope={scope}
                            capacity={station?.capacity_ac_mw || 0}
                            selected={scope.selected_interval}
                            onSelect={selectInterval}
                            reportUrl={
                              bootstrap.data?.evidently.report_url || ""
                            }
                            revision={revision}
                          />
                        )}
                        {tab === "trading" && validDate && (
                          <Trading
                            scope={scope}
                            theme={theme}
                            revision={revision}
                            onRefresh={refresh}
                            onDateChange={(d) => updateContext({ date: d })}
                          />
                        )}
                        {tab === "agent" && validDate && (
                          <section className="panel agent-page">
                            <Agent
                              scope={scope}
                              theme={theme}
                              onOverlay={showOverlay}
                              llmMode={llmMode}
                              onDraft={toDraft}
                            />
                          </section>
                        )}
                        {tab === "rsi" && validDate && (
                          <Rsi
                            scope={scope}
                            revision={revision}
                            onRefresh={refresh}
                            draft={draft}
                            onSelect={selectInterval}
                          />
                        )}
                      </div>
                      {tab === "forecast" && (
                        <ContextRail
                          scope={scope}
                          data={overview.data}
                          loading={overview.loading}
                          error={overview.error}
                          llmMode={llmMode}
                          onSelect={selectInterval}
                          onRaw={() => setTab("raw")}
                          onDraft={toDraft}
                          onFullAgent={() => setTab("agent")}
                        />
                      )}
                    </div>
                  )}
                  <footer className="energy-footer">
                    <span>中节能光伏交易工作台 · 口径可核验，证据可追溯</span>
                    <span>
                      {llmMode === "deterministic_tools_only"
                        ? "确定性工具模式"
                        : "外部证据摘要器已配置 · 调用结果以记录为准"}
                    </span>
                  </footer>
                </>
              )}
            </>
          )}
        </div>
      </main>
      {drawer && (
        <Drawer title="随行智能体" onClose={() => setDrawer(false)}>
          <Agent
            scope={scope}
            theme={theme}
            onOverlay={showOverlay}
            llmMode={llmMode}
            onDraft={toDraft}
          />
        </Drawer>
      )}
    </div>
  );
}
