import { useCallback, useEffect, useRef, useState } from "react";
import {
  Play,
  Pause,
  SkipBack,
  SkipForward,
  FileSearch,
  Sparkles,
  ClipboardCheck,
  ArrowRight,
  Database,
  Download,
} from "lucide-react";
import type { EChartsOption } from "echarts";
import type { Theme } from "./types";
import type {
  PublicCatalog,
  PublicSeries,
  PublicAnalysis,
  PublicScenario,
  PublicRun,
  PublicTab,
} from "./publicTypes";
import { fmt, request, stamp, time, useResource } from "./api";
import { Panel, Status } from "./components";
import Chart, { baseOption, color } from "./Chart";

const steps: { tab: PublicTab; title: string; task: string }[] = [
  { tab: "raw", title: "核对数据", task: "查看原始行、空值和来源" },
  { tab: "forecast", title: "观察量价", task: "定位预测与实际的差异" },
  { tab: "trading", title: "测算情景", task: "调整电量与费用查看价差敞口" },
  { tab: "agent", title: "分析证据", task: "按当前窗口调用计算与摘要工具" },
  { tab: "rsi", title: "保存复核", task: "把人工结论与原始行绑定" },
];
const explanations: Record<PublicTab, string> = {
  forecast:
    "先选交易日，再播放或拖动时间条。曲线、指标与右侧记录使用同一窗口；点击图表可定位时段。",
  raw: "核对当前已展示范围的源文件记录。选中一行后，可继续分析或保存人工复核。",
  trading:
    "用已展示时段的真实价差计算假设敞口。参数由你设定，不代替场站合约或正式结算。",
  agent:
    "分析绑定当前日期、回放范围和文件版本；数值由工具计算，摘要保留证据行号。",
  rsi: "核对选中原始记录并保存人工结论。这里只记录复核，不自动纳入训练或发布模型。",
  connections: "查看数据覆盖、原始字段、更新方式及尚缺的业务要素。",
};

export default function PublicWorkspace({
  tab,
  onNavigate,
  theme,
  revision,
}: {
  tab: PublicTab;
  onNavigate: (tab: PublicTab) => void;
  theme: Theme;
  revision: number;
}) {
  const [autoCheck, setAutoCheck] = useState(true);
  const [viewSource, setViewSource] = useState(
    () => new URLSearchParams(location.search).get("view_source") || "",
  );
  const catalog = useResource<PublicCatalog>(
    viewSource
      ? `/api/v1/research/source-catalog?source_hash=${encodeURIComponent(viewSource)}`
      : "/api/v1/public-data/catalog",
    revision,
    autoCheck ? 30000 : 0,
  );
  const [day, setDay] = useState(
    () =>
      new URLSearchParams(location.search).get("date") ||
      new URLSearchParams(location.search).get("ml_date") ||
      "",
  );
  const [cursor, setCursor] = useState(() => {
    const raw = new URLSearchParams(location.search).get("cursor");
    const value = Number(raw);
    return raw !== null && Number.isInteger(value) && value >= 0 && value <= 96
      ? value
      : 48;
  });
  const [playing, setPlaying] = useState(false);
  const [speed, setSpeed] = useState(2000);
  const [follow, setFollow] = useState(
    () => !new URLSearchParams(location.search).has("slot"),
  );
  const [slot, setSlot] = useState(() => {
    const value = Number(new URLSearchParams(location.search).get("slot"));
    return Number.isInteger(value) && value >= 0 && value <= 95 ? value : 47;
  });
  const [localRevision, setLocalRevision] = useState(0);
  const [includeHistorical, setIncludeHistorical] = useState(true);
  const [snapshot, setSnapshot] = useState<PublicRun | null>(null);
  const [failure, setFailure] = useState("");
  const [message, setMessage] = useState("");
  const meta = catalog.data?.metadata;
  const previousHash = useRef<string | undefined>(undefined);
  const [versionNote, setVersionNote] = useState("");
  useEffect(() => {
    if (meta?.source_hash) {
      if (previousHash.current && previousHash.current !== meta.source_hash)
        setVersionNote(
          "检测到源文件更新，已重读当前范围；交易日和回放位置保持不变。",
        );
      previousHash.current = meta.source_hash;
    }
  }, [meta?.source_hash]);
  const valid = !!catalog.data?.dates.includes(day);
  const scopeKey = `${meta?.source_hash || ""}:${day}:${cursor}`;
  const current = useRef(scopeKey);
  current.current = scopeKey;
  const data = useResource<PublicSeries>(
    valid && meta
      ? viewSource
        ? `/api/v1/research/source-series?trading_date=${day}&cursor=${cursor}&source_hash=${meta.source_hash}`
        : `/api/v1/public-data/series?date=${day}&cursor=${cursor}&source_hash=${meta.source_hash}`
      : null,
    `${revision}:${meta?.source_hash}`,
  );
  const history = useResource<{ runs: PublicRun[] }>(
    valid && meta
      ? `/api/v1/public-data/history?date=${day}&source_hash=${meta.source_hash}&all_versions=${includeHistorical}`
      : null,
    `${localRevision}:${revision}`,
  );
  const [question, setQuestion] = useState(
    "分析当前范围的光伏预测偏差、电价变化及需要复核的时段",
  );
  const [answer, setAnswer] = useState<{
    key: string;
    value: PublicAnalysis;
  } | null>(null);
  const [busy, setBusy] = useState(false);
  const [quantity, setQuantity] = useState(1);
  const [fee, setFee] = useState(0);
  const [calculation, setCalculation] = useState<{
    key: string;
    value: PublicScenario;
  } | null>(null);
  const [calculating, setCalculating] = useState(false);
  const [reason, setReason] = useState("");
  const [draftScope, setDraftScope] = useState<{
    date: string;
    cursor: number;
    slot: number;
    source_hash: string;
  } | null>(null);
  const calculationKey = `${scopeKey}:${quantity}:${fee}`;
  const activeCalculation = useRef(calculationKey);
  activeCalculation.current = calculationKey;
  const retained = useRef<PublicSeries | null>(null);
  if (data.data) retained.current = data.data;
  const series =
    data.data ||
    (retained.current?.scope.date === day &&
    retained.current.metadata.source_hash === meta?.source_hash
      ? retained.current
      : null);
  const displayedCursor = series?.scope.cursor ?? cursor;
  const points = series?.points || [];
  const selectedSlot = follow ? Math.max(0, displayedCursor - 1) : slot;
  const selected = points[selectedSlot];
  const ready = !!data.data && !data.error && !data.loading;
  const showData = !!series && !data.error;
  const payload = {
    date: day,
    cursor,
    source_hash: meta?.source_hash,
    archived: !!viewSource,
  };

  useEffect(() => {
    if (catalog.data?.available && !catalog.data.dates.includes(day))
      setDay(catalog.data.default_date || catalog.data.dates.at(-1) || "");
  }, [catalog.data, day]);
  useEffect(() => {
    if (!valid) return;
    const url = new URL(location.href);
    if (
      url.searchParams.get("ml_date") &&
      url.searchParams.get("ml_date") !== day
    ) {
      url.searchParams.delete("ml_prediction");
      url.searchParams.delete("ml_feedback");
      url.searchParams.delete("ml_proposal");
    }
    url.searchParams.set("date", day);
    url.searchParams.set("ml_date", day);
    url.searchParams.set("cursor", String(cursor));
    if (follow) url.searchParams.delete("slot");
    else url.searchParams.set("slot", String(slot));
    window.history.replaceState(null, "", url);
  }, [valid, day, cursor, slot, follow]);
  useEffect(() => {
    setPlaying(false);
    setFailure("");
    setMessage("");
  }, [day, meta?.source_hash]);
  useEffect(() => {
    setFailure("");
    setMessage("");
  }, [scopeKey]);
  useEffect(() => {
    if (!playing) return;
    const timer = window.setInterval(
      () => setCursor((value) => Math.min(96, value + 1)),
      speed,
    );
    return () => window.clearInterval(timer);
  }, [playing, speed]);
  useEffect(() => {
    if (cursor >= 96) setPlaying(false);
  }, [cursor]);

  useEffect(() => {
    if (tab !== "trading" || !valid || !meta) return;
    const controller = new AbortController();
    setCalculating(true);
    setFailure("");
    const captured = calculationKey;
    const timer = window.setTimeout(() => {
      request<PublicScenario>(
        "/api/v1/public-data/scenario",
        {
          date: day,
          cursor,
          source_hash: meta.source_hash,
          quantity_mwh: quantity,
          fee_yuan_mwh: fee,
        },
        controller.signal,
      )
        .then((value) => {
          if (
            !controller.signal.aborted &&
            activeCalculation.current === captured
          )
            setCalculation({ key: captured, value });
        })
        .catch((error) => {
          if (!controller.signal.aborted) setFailure((error as Error).message);
        })
        .finally(() => {
          if (!controller.signal.aborted) setCalculating(false);
        });
    }, 300);
    return () => {
      controller.abort();
      window.clearTimeout(timer);
    };
  }, [tab, calculationKey, valid, meta, day, cursor, quantity, fee]);

  const locate = useCallback((index: number) => {
    if (index < 0 || index > 95) return;
    setPlaying(false);
    setFollow(false);
    setSlot(index);
    setCursor((value) => Math.max(value, index + 1));
  }, []);
  const power = useCallback((): EChartsOption => {
    const base = baseOption();
    return {
      ...base,
      grid: { left: 72, right: 28, top: 48, bottom: 42 },
      xAxis: { ...base.xAxis, data: points.map((p) => time(p.interval_start)) },
      yAxis: { ...base.yAxis, name: "区域总出力 / MW" },
      series: [
        {
          name: "源文件光伏预测",
          type: "line",
          showSymbol: false,
          connectNulls: false,
          data: points.map((p) => p.pv_forecast_mw),
          itemStyle: { color: color("primary") },
          lineStyle: { type: "dashed", width: 2 },
        },
        {
          name: "源文件光伏实际",
          type: "line",
          showSymbol: false,
          connectNulls: false,
          data: points.map((p) => p.pv_actual_mw),
          itemStyle: { color: color("success") },
          lineStyle: { width: 2 },
          markLine: {
            symbol: "none",
            label: { formatter: "回放位置" },
            lineStyle: { color: color("warning") },
            data: displayedCursor
              ? [{ xAxis: Math.max(0, displayedCursor - 1) }]
              : [],
          },
        },
      ],
    };
  }, [points, displayedCursor]);
  const prices = useCallback((): EChartsOption => {
    const base = baseOption();
    return {
      ...base,
      grid: { left: 60, right: 60, top: 48, bottom: 36 },
      xAxis: { ...base.xAxis, data: points.map((p) => time(p.interval_start)) },
      yAxis: [
        { ...base.yAxis, name: "价格 / 元/MWh" },
        { ...base.yAxis, name: "RT−DA", splitLine: { show: false } },
      ],
      series: [
        {
          name: "日前价格",
          type: "line",
          showSymbol: false,
          connectNulls: false,
          data: points.map((p) => p.da_price),
          itemStyle: { color: color("primary") },
        },
        {
          name: "实时价格",
          type: "line",
          showSymbol: false,
          connectNulls: false,
          data: points.map((p) => p.rt_price),
          itemStyle: { color: color("success") },
        },
        {
          name: "RT−DA 价差（右轴）",
          type: "bar",
          yAxisIndex: 1,
          data: points.map((p) => p.spread_yuan_mwh),
          itemStyle: { color: color("warning-container") },
        },
      ],
    };
  }, [points]);

  async function analyze() {
    if (!ready || !question.trim()) return;
    setPlaying(false);
    setBusy(true);
    setFailure("");
    setMessage("");
    const captured = scopeKey;
    try {
      const value = await request<PublicAnalysis>(
        "/api/v1/public-data/analyze",
        { ...payload, question },
      );
      if (current.current === captured) setAnswer({ key: captured, value });
      setLocalRevision((v) => v + 1);
    } catch (error) {
      if (current.current === captured) setFailure((error as Error).message);
    } finally {
      setBusy(false);
    }
  }
  async function saveReview() {
    if (!ready || !draftScope || !reason.trim()) return;
    setBusy(true);
    setFailure("");
    setMessage("");
    try {
      const result = await request<{ run_id: string }>(
        "/api/v1/public-data/review",
        {
          date: draftScope.date,
          cursor: draftScope.cursor,
          selected_slot: draftScope.slot,
          source_hash: draftScope.source_hash,
          reason,
        },
      );
      setMessage(`复核已保存，记录 ${result.run_id.slice(0, 8)}；未触发训练。`);
      setReason("");
      setDraftScope(null);
      setLocalRevision((v) => v + 1);
    } catch (error) {
      setFailure((error as Error).message);
    } finally {
      setBusy(false);
    }
  }
  async function saveScenario() {
    if (!ready) return;
    setPlaying(false);
    setBusy(true);
    setFailure("");
    setMessage("");
    try {
      const result = await request<PublicScenario>(
        "/api/v1/public-data/scenario",
        {
          ...payload,
          quantity_mwh: quantity,
          fee_yuan_mwh: fee,
          persist: true,
        },
      );
      setMessage(
        `情景计算已保存，记录 ${result.saved?.run_id.slice(0, 8)}；没有提交交易。`,
      );
      setLocalRevision((v) => v + 1);
    } catch (error) {
      setFailure((error as Error).message);
    } finally {
      setBusy(false);
    }
  }
  function exportVisible() {
    if (!series) return;
    const columns = series.metadata.source_columns;
    const cell = (v: unknown) =>
      '"' + String(v ?? "").replaceAll('"', '""') + '"';
    const csv = [
      columns.map(cell).join(","),
      ...points
        .filter((p) => p.visible && p.source_values)
        .map((p) => columns.map((c) => cell(p.source_values![c])).join(",")),
    ].join("\r\n");
    const url = URL.createObjectURL(
      new Blob(["\ufeff", csv], { type: "text/csv;charset=utf-8" }),
    );
    const a = document.createElement("a");
    a.href = url;
    a.download = `山东公开市场-${day}-前${cursor}时段.csv`;
    a.click();
    URL.revokeObjectURL(url);
  }

  const k = series?.summary;
  const shownAnswer = answer?.key === scopeKey ? answer.value : null;
  const shownCalculation =
    calculation?.key === calculationKey ? calculation.value : null;
  const currentDraft =
    !draftScope ||
    (draftScope.date === day &&
      draftScope.cursor === cursor &&
      draftScope.slot === selectedSlot &&
      draftScope.source_hash === meta?.source_hash);
  const selectedLabel = selected
    ? `${time(selected.interval_start)}–${time(selected.interval_end)}`
    : "未选记录";
  const contextPanel = (
    <Panel title="当前记录与下一步" action={<FileSearch size={17} />}>
      <div className="public-record-context">
        <strong>
          {day} · {selectedLabel}
        </strong>
        <small>
          山东区域市场 ·{" "}
          {selected?.source_line
            ? `源文件第 ${selected.source_line} 行`
            : "该位置没有已展示的原始记录"}
        </small>
      </div>
      <dl className="interval-facts">
        <div>
          <dt>光伏实际</dt>
          <dd>
            {fmt(selected?.pv_actual_mw)} <small>MW</small>
          </dd>
        </div>
        <div>
          <dt>源文件光伏预测</dt>
          <dd>
            {fmt(selected?.pv_forecast_mw)} <small>MW</small>
          </dd>
        </div>
        <div>
          <dt>实际直调负荷</dt>
          <dd>
            {fmt(selected?.load_actual_mw)} <small>MW</small>
          </dd>
        </div>
        <div>
          <dt>日前 / 实时价</dt>
          <dd>
            {fmt(selected?.da_price)} / {fmt(selected?.rt_price)}
          </dd>
        </div>
        <div>
          <dt>RT−DA</dt>
          <dd>
            {fmt(selected?.spread_yuan_mwh)} <small>元/MWh</small>
          </dd>
        </div>
      </dl>
      <div className="public-next-actions">
        <button onClick={() => onNavigate("raw")}>
          <FileSearch size={15} />
          查看这行原始数据
        </button>
        <button onClick={() => onNavigate("agent")}>
          <Sparkles size={15} />
          分析当前回放范围
        </button>
        <button
          onClick={() => {
            setPlaying(false);
            onNavigate("rsi");
          }}
        >
          <ClipboardCheck size={15} />
          记录人工复核
        </button>
      </div>
    </Panel>
  );

  return (
    <div className="public-workspace">
      {viewSource && (
        <div className="research-context">
          <Database size={20} />
          <div>
            <strong>正在按输入版本查看原始数据</strong>
            <span>{viewSource.slice(0, 16)} · 图表和原始行均绑定此版本</span>
          </div>
          <button
            onClick={() => {
              setViewSource("");
              const u = new URL(location.href);
              u.searchParams.delete("view_source");
              window.history.replaceState(null, "", u);
            }}
          >
            切回当前源文件
          </button>
        </div>
      )}
      <Status loading={catalog.loading} error={catalog.error} />
      {catalog.data && !catalog.data.available && (
        <section className="connection-empty">
          <Database size={30} />
          <h2>公开市场数据尚未就绪</h2>
          <p>{catalog.data.notice}</p>
          <p>请选择其他已配置工作区，或由管理员检查现有服务器数据路径。</p>
        </section>
      )}
      {meta && (
        <>
          <div className="public-source-status">
            <div>
              <strong>山东公开市场历史记录</strong>
              <span>
                {meta.row_count.toLocaleString()} 条 · {meta.day_count} 天 ·{" "}
                {meta.date_start}—{meta.date_end}
              </span>
            </div>
            <label>
              <input
                type="checkbox"
                checked={autoCheck}
                onChange={(e) => setAutoCheck(e.target.checked)}
              />
              每30秒检查源文件变化
            </label>
            <small>
              {catalog.refreshing
                ? "正在检查源文件…"
                : `最近检查 ${time(catalog.data!.checked_at)}`}
            </small>
          </div>
          {versionNote && (
            <p className="public-pending" role="status">
              {versionNote}
            </p>
          )}
          <div className="public-time-controls">
            <label>
              交易日
              <input
                aria-label="公开数据交易日"
                type="date"
                min={meta.date_start}
                max={meta.date_end}
                value={day}
                onChange={(e) => {
                  if (catalog.data?.dates.includes(e.target.value)) {
                    setDay(e.target.value);
                    setPlaying(false);
                  } else
                    setFailure("该日期没有原始记录，请选择数据覆盖内的日期。");
                }}
              />
            </label>
            <button
              onClick={() => {
                setFollow(true);
                if (cursor >= 96) setCursor(0);
                setPlaying((v) => !v);
              }}
              disabled={!valid}
            >
              {playing ? <Pause size={16} /> : <Play size={16} />}
              {playing ? "暂停回放" : "播放历史记录"}
            </button>
            <button
              aria-label="上一个回放时段"
              disabled={cursor <= 0}
              onClick={() => {
                setPlaying(false);
                setFollow(true);
                setCursor((v) => Math.max(0, v - 1));
              }}
            >
              <SkipBack size={15} />
            </button>
            <button
              aria-label="下一个回放时段"
              disabled={cursor >= 96}
              onClick={() => {
                setPlaying(false);
                setFollow(true);
                setCursor((v) => Math.min(96, v + 1));
              }}
            >
              <SkipForward size={15} />
            </button>
            <label className="public-playback-range">
              已展示 {cursor}/96 时段
              <input
                aria-label="历史记录回放位置"
                type="range"
                min="0"
                max="96"
                step="1"
                value={cursor}
                onChange={(e) => {
                  setPlaying(false);
                  setFollow(true);
                  setCursor(Number(e.target.value));
                }}
              />
            </label>
            <label>
              速度
              <select
                aria-label="历史记录回放速度"
                value={speed}
                onChange={(e) => setSpeed(Number(e.target.value))}
              >
                <option value="1000">1秒 / 时段</option>
                <option value="2000">2秒 / 时段</option>
                <option value="5000">5秒 / 时段</option>
              </select>
            </label>
          </div>
          <div className="public-scope-strip">
            <span>
              同一分析范围：{day} · 回放至{" "}
              {series
                ? time(series.scope.replay_until)
                : `${Math.floor(cursor / 4)
                    .toString()
                    .padStart(
                      2,
                      "0",
                    )}:${((cursor % 4) * 15).toString().padStart(2, "0")}`}{" "}
              · 每时段15分钟
            </span>
            <span>历史记录顺序播放，非当前实时行情</span>
          </div>
          <nav className="public-flow" aria-label="业务操作路径">
            {steps.map((step, index) => (
              <div key={step.tab}>
                <button
                  aria-current={step.tab === tab ? "step" : undefined}
                  onClick={() => onNavigate(step.tab)}
                  title={step.task}
                >
                  {step.title}
                  <small>{step.task}</small>
                </button>
                {index < steps.length - 1 && (
                  <ArrowRight size={14} aria-hidden="true" />
                )}
              </div>
            ))}
          </nav>
          <p className="public-page-purpose">{explanations[tab]}</p>
          {failure && (
            <p className="inline-error" role="alert">
              {failure}
            </p>
          )}
          {message && (
            <p className="inline-success" role="status">
              {message}
            </p>
          )}
          <Status loading={data.loading && !series} error={data.error} />
          {series && (
            <p className="public-pending" role="status">
              {data.loading
                ? "正在读取回放目标位置；当前图表与指标仍对应 "
                : "图表、指标和证据已同步至 "}
              {time(series.scope.replay_until)}。
            </p>
          )}
          {showData && (
            <>
              <div className="presentation-metrics public-metrics">
                <div>
                  <span>回放末端 · 区域光伏实际</span>
                  <strong>
                    {fmt(series.latest?.pv_actual_mw)} <small>MW</small>
                  </strong>
                  <small>
                    {series.latest
                      ? time(series.latest.interval_start)
                      : "尚未展示原始记录"}
                  </small>
                </div>
                <div>
                  <span>已展示范围 · 光伏列配对 MAE</span>
                  <strong>
                    {fmt(k?.pv_mae_mw)} <small>MW</small>
                  </strong>
                  <small>{k?.power_pair_count} 条配对 · 不是本站模型效果</small>
                </div>
                <div>
                  <span>回放末端 · 实时价格</span>
                  <strong>
                    {fmt(series.latest?.rt_price)} <small>元/MWh</small>
                  </strong>
                  <small>原始缺失保留为空</small>
                </div>
                <div>
                  <span>已展示范围 · 平均 RT−DA</span>
                  <strong>
                    {fmt(k?.mean_spread_yuan_mwh)} <small>元/MWh</small>
                  </strong>
                  <small>
                    {k?.price_pair_count} 条价格配对 · {k?.negative_price_count}{" "}
                    个负价时段
                  </small>
                </div>
              </div>
              {(tab === "forecast" ||
                tab === "raw" ||
                tab === "trading" ||
                tab === "rsi") && (
                <div className="public-analysis-grid">
                  <div className="public-primary">
                    {tab === "forecast" && (
                      <>
                        <div className="public-quick-locate">
                          <button
                            disabled={!k?.worst_pv_error}
                            onClick={() =>
                              k?.worst_pv_error && locate(k.worst_pv_error.slot)
                            }
                          >
                            定位最大光伏列偏差
                          </button>
                          <button
                            disabled={!k?.max_abs_spread}
                            onClick={() =>
                              k?.max_abs_spread && locate(k.max_abs_spread.slot)
                            }
                          >
                            定位最大价差
                          </button>
                        </div>
                        <Panel
                          title="区域光伏预测与实绩"
                          subtitle="直接读取源文件预测/实际列；区间起点标时，原始负值保留。"
                        >
                          <Chart
                            label="已展示历史范围的区域光伏预测与实际出力"
                            option={power}
                            theme={theme}
                            group="public-timeline"
                            onPoint={locate}
                          />
                        </Panel>
                        <Panel
                          title="日前价、实时价与价差"
                          subtitle="点击曲线定位记录；未播放时段不提前展示。"
                        >
                          <Chart
                            label="历史价格与RT减DA价差"
                            option={prices}
                            theme={theme}
                            group="public-timeline"
                            onPoint={locate}
                            compact
                          />
                        </Panel>
                      </>
                    )}
                    {tab === "raw" && (
                      <>
                        <Panel
                          title="已展示的原始记录"
                          subtitle={`已展示 ${k?.visible_records} 条 · 点击一行绑定右侧证据与复核`}
                          action={
                            <button onClick={exportVisible}>
                              <Download size={14} />
                              导出已展示范围
                            </button>
                          }
                        >
                          <div className="table-wrap public-raw-table">
                            <table className="presentation-table">
                              <thead>
                                <tr>
                                  <th>时段</th>
                                  <th>光伏预测 / MW</th>
                                  <th>光伏实际 / MW</th>
                                  <th>日前价</th>
                                  <th>实时价</th>
                                  <th>源行号</th>
                                </tr>
                              </thead>
                              <tbody>
                                {points
                                  .filter((p) => p.visible)
                                  .map((p) => (
                                    <tr
                                      key={p.slot}
                                      tabIndex={0}
                                      aria-selected={p.slot === selectedSlot}
                                      className={
                                        p.slot === selectedSlot
                                          ? "selected-row"
                                          : ""
                                      }
                                      onClick={() => locate(p.slot)}
                                      onKeyDown={(e) => {
                                        if (
                                          e.key === "Enter" ||
                                          e.key === " "
                                        ) {
                                          e.preventDefault();
                                          locate(p.slot);
                                        }
                                      }}
                                    >
                                      <td>
                                        {time(p.interval_start)}–
                                        {time(p.interval_end)}
                                      </td>
                                      <td>{fmt(p.pv_forecast_mw)}</td>
                                      <td>{fmt(p.pv_actual_mw)}</td>
                                      <td>{fmt(p.da_price)}</td>
                                      <td>{fmt(p.rt_price)}</td>
                                      <td>{p.source_line ?? "缺失记录"}</td>
                                    </tr>
                                  ))}
                              </tbody>
                            </table>
                          </div>
                        </Panel>
                        <Panel
                          title="选中记录的完整原始字段"
                          subtitle="不把字段缺失补为零，也不把山东聚合出力转换为岚能场站实测。"
                        >
                          <dl className="public-source-values">
                            {meta.source_columns.map((column) => (
                              <div key={column}>
                                <dt>{column}</dt>
                                <dd>
                                  {selected?.source_values?.[column] === ""
                                    ? "空值"
                                    : (selected?.source_values?.[column] ??
                                      "—")}
                                </dd>
                              </div>
                            ))}
                          </dl>
                        </Panel>
                      </>
                    )}
                    {tab === "trading" && (
                      <>
                        <Panel
                          title="价差敞口情景"
                          subtitle="假设每个配对时段有同等电量暴露，计算事后 RT−DA 差额；不是可执行策略或场站结算。"
                        >
                          <div className="public-scenario-inputs">
                            <label>
                              每时段假设电量 / MWh
                              <input
                                aria-label="价差情景电量"
                                type="number"
                                min="0"
                                max="1000000"
                                step="0.25"
                                value={quantity}
                                onChange={(e) =>
                                  setQuantity(Number(e.target.value))
                                }
                              />
                            </label>
                            <label>
                              每 MWh 假设费用 / 元
                              <input
                                aria-label="价差情景费用"
                                type="number"
                                min="0"
                                max="1000000"
                                step="1"
                                value={fee}
                                onChange={(e) => setFee(Number(e.target.value))}
                              />
                            </label>
                          </div>
                          <p className="public-calculation-state" role="status">
                            {calculating
                              ? "正在按当前范围重算…"
                              : "参数修改后自动重算；只有点击保存才会入库。"}
                          </p>
                          {shownCalculation && (
                            <div className="public-scenario-result">
                              <span>已展示范围的假设净价差敞口</span>
                              <strong>
                                {fmt(shownCalculation.net_spread_yuan)}{" "}
                                <small>元</small>
                              </strong>
                              <p>
                                {shownCalculation.paired_intervals} 个配对时段 ·
                                暴露电量{" "}
                                {fmt(shownCalculation.total_exposure_mwh)} MWh ·
                                缺少价格 {shownCalculation.unsettled_intervals}{" "}
                                段
                              </p>
                              <p>
                                价差差额{" "}
                                {fmt(shownCalculation.gross_spread_yuan)} 元 −
                                假设费用 {fmt(shownCalculation.fees_yuan)} 元
                              </p>
                              <code>{shownCalculation.formula}</code>
                              <button
                                onClick={() => void saveScenario()}
                                disabled={!ready || busy || calculating}
                              >
                                保存当前测算记录
                              </button>
                            </div>
                          )}
                        </Panel>
                        <Panel
                          title="情景采用的原始电价"
                          subtitle="复核当前窗口中的真实价格，再解释测算差额。"
                        >
                          <Chart
                            label="情景依据的历史电价曲线"
                            option={prices}
                            theme={theme}
                            onPoint={locate}
                            compact
                          />
                        </Panel>
                      </>
                    )}
                    {tab === "rsi" && (
                      <Panel
                        title="人工复核当前记录"
                        subtitle={`${day} · ${selectedLabel} · 源文件第 ${selected?.source_line ?? "—"} 行`}
                      >
                        <div className="public-review-form">
                          <p>
                            结合原始负荷、光伏和价格列记录判断。未知原因可写为待核验，不自动认定天气或设备故障。
                          </p>
                          <label htmlFor="public-review-reason">
                            人工结论
                            <textarea
                              id="public-review-reason"
                              disabled={!ready || busy}
                              rows={5}
                              maxLength={4000}
                              value={reason}
                              onChange={(e) => {
                                if (!reason && meta) {
                                  setDraftScope({
                                    date: day,
                                    cursor,
                                    slot: selectedSlot,
                                    source_hash: meta.source_hash,
                                  });
                                  setPlaying(false);
                                }
                                setReason(e.target.value);
                                if (!e.target.value) setDraftScope(null);
                              }}
                              placeholder="记录观察到的变化、依据和仍需核验的信息"
                            />
                          </label>
                          {!currentDraft && (
                            <div className="notice">
                              <span>
                                草稿绑定此前的范围或版本；请返回原范围，或核对当前记录后明确重新绑定。
                              </span>
                              <button
                                onClick={() => {
                                  if (draftScope) {
                                    setDay(draftScope.date);
                                    setCursor(draftScope.cursor);
                                    setSlot(draftScope.slot);
                                    setFollow(false);
                                    setPlaying(false);
                                  }
                                }}
                              >
                                返回草稿范围
                              </button>
                              <button
                                disabled={!ready || !selected?.source_line}
                                onClick={() => {
                                  if (meta)
                                    setDraftScope({
                                      date: day,
                                      cursor,
                                      slot: selectedSlot,
                                      source_hash: meta.source_hash,
                                    });
                                }}
                              >
                                重新绑定当前记录
                              </button>
                              <button
                                onClick={() => {
                                  setReason("");
                                  setDraftScope(null);
                                }}
                              >
                                清空草稿
                              </button>
                            </div>
                          )}
                          <button
                            className="primary-button"
                            disabled={
                              !ready ||
                              busy ||
                              !reason.trim() ||
                              !selected?.source_line ||
                              !currentDraft
                            }
                            onClick={() => void saveReview()}
                          >
                            保存复核与证据
                          </button>
                          <small>
                            保存会追加记录；不修改源文件，不自动纳入训练。
                          </small>
                        </div>
                      </Panel>
                    )}
                  </div>
                  <aside className="context-rail">{contextPanel}</aside>
                </div>
              )}
              {tab === "agent" && (
                <div className="public-analysis-grid">
                  <div className="public-primary">
                    <Panel
                      title="分析当前量价数据"
                      subtitle={`${day} · 前 ${cursor} 个时段 · 同一文件版本`}
                    >
                      <form
                        className="public-question-form"
                        onSubmit={(e) => {
                          e.preventDefault();
                          void analyze();
                        }}
                      >
                        <label htmlFor="public-question">
                          业务问题
                          <textarea
                            id="public-question"
                            rows={3}
                            maxLength={4000}
                            value={question}
                            onChange={(e) => setQuestion(e.target.value)}
                          />
                        </label>
                        <button
                          className="primary-button"
                          disabled={
                            !ready || busy || !question.trim() || cursor === 0
                          }
                        >
                          {busy
                            ? "正在调用工具与摘要器…"
                            : "分析当前范围并保存"}
                        </button>
                        <small>
                          点击后暂停回放，避免分析范围在请求过程中移动。
                        </small>
                      </form>
                      {shownAnswer && (
                        <div className="public-answer">
                          <p>{shownAnswer.answer_markdown}</p>
                          <small>
                            {shownAnswer.llm_mode} ·{" "}
                            {shownAnswer.evidence.source_lines.length}{" "}
                            条来源记录 · 分析已保存
                          </small>
                          <details>
                            <summary>查看计算事实与来源</summary>
                            <pre>
                              {JSON.stringify(
                                {
                                  facts: shownAnswer.facts,
                                  evidence: shownAnswer.evidence,
                                },
                                null,
                                2,
                              )}
                            </pre>
                          </details>
                          <button
                            onClick={() => {
                              setPlaying(false);
                              onNavigate("rsi");
                            }}
                          >
                            去复核选中记录
                          </button>
                        </div>
                      )}
                    </Panel>
                  </div>
                  <aside className="context-rail">{contextPanel}</aside>
                </div>
              )}
              {tab === "connections" && (
                <div className="connection-status">
                  <Panel
                    title="当前接入的公开数据"
                    subtitle="资产已在 GB10，页面通过后端读取，未复制到工作站。"
                  >
                    <dl className="public-source-values">
                      <div>
                        <dt>原始数据集</dt>
                        <dd>{meta.source_file}</dd>
                      </div>
                      <div>
                        <dt>空间范围</dt>
                        <dd>{meta.region}</dd>
                      </div>
                      <div>
                        <dt>覆盖</dt>
                        <dd>
                          {meta.day_count} 天 /{" "}
                          {meta.row_count.toLocaleString()} 条
                        </dd>
                      </div>
                      <div>
                        <dt>时间语义</dt>
                        <dd>源时刻为区间终点；图表按区间起点显示</dd>
                      </div>
                      <div>
                        <dt>文件版本</dt>
                        <dd className="public-hash">{meta.source_hash}</dd>
                      </div>
                      <div>
                        <dt>更新方式</dt>
                        <dd>{meta.update_policy}</dd>
                      </div>
                    </dl>
                    <div className="panel-note">
                      <a
                        href={meta.source_url}
                        target="_blank"
                        rel="noreferrer"
                      >
                        查看源仓库与数据说明
                      </a>
                    </div>
                  </Panel>
                  <Panel
                    title="数据如何流动"
                    subtitle="每个动作的范围与结果都能回到原始记录。"
                  >
                    <ol className="public-dataflow">
                      <li>
                        读取现有 CSV，校验列名、时段、重复记录并计算文件版本。
                      </li>
                      <li>选择交易日和回放位置，仅展示该位置之前的记录。</li>
                      <li>根据已展示记录计算光伏列误差、价差及情景差额。</li>
                      <li>
                        显式点击分析或保存，把范围、文件版本、原始行号与结果追加入库。
                      </li>
                      <li>
                        检测到文件版本改变后重新加载；历史分析仍保留原版本证据。
                      </li>
                    </ol>
                  </Panel>
                  <Panel title="适用范围与仍缺的要素">
                    <div className="public-boundaries">
                      <p>
                        可用于公开市场历史数据研究、源字段预测与实绩对照、事后价差敞口和人工复核。
                      </p>
                      <p>
                        该文件不是浙江场站数据；当前{meta.source_columns.length}
                        列没有场站气象实测，也缺少原始预报发布时间、到达时间、场站合同、设备状态及正式结算规则。
                      </p>
                      <p>{meta.basis}</p>
                      <p>
                        本站实时推理、训练和交易执行状态不会由这份文件的存在自动变为已完成。
                      </p>
                    </div>
                  </Panel>
                </div>
              )}
              {(tab === "agent" || tab === "rsi" || tab === "trading") && (
                <Panel
                  title="当前交易日的分析与复核记录"
                  subtitle="记录绑定原始文件版本；切换回放位置不会改写已保存结果。"
                  action={
                    <label className="public-history-toggle">
                      <input
                        type="checkbox"
                        checked={includeHistorical}
                        onChange={(e) => setIncludeHistorical(e.target.checked)}
                      />
                      包含历史文件版本
                    </label>
                  }
                >
                  <Status loading={history.loading} error={history.error} />
                  <div className="public-history">
                    {history.data?.runs.length ? (
                      history.data.runs.map((run) => (
                        <article key={run.run_id}>
                          <header>
                            <strong>
                              {run.kind === "review"
                                ? "人工复核"
                                : run.kind === "analysis"
                                  ? "工具分析"
                                  : "情景计算"}
                            </strong>
                            <small>
                              {stamp(run.created_at)} · 前 {run.scope.cursor}{" "}
                              时段 ·{" "}
                              {run.source_hash === meta.source_hash
                                ? "当前文件版本"
                                : "历史文件版本"}
                            </small>
                            <button
                              onClick={() => {
                                if (run.source_hash !== meta.source_hash) {
                                  setSnapshot(run);
                                  return;
                                }
                                setCursor(run.scope.cursor);
                                if (
                                  run.scope.selected_slot !== undefined &&
                                  run.scope.selected_slot !== null
                                ) {
                                  setSlot(run.scope.selected_slot);
                                  setFollow(false);
                                }
                                setPlaying(false);
                              }}
                            >
                              {run.source_hash === meta.source_hash
                                ? "定位原范围"
                                : "查看保存快照"}
                            </button>
                          </header>
                          <p>{run.answer_text}</p>
                          <small>
                            记录 {run.run_id.slice(0, 8)} ·{" "}
                            {run.status === "provider_failed"
                              ? "摘要调用失败，已留存工具证据"
                              : "已保存"}
                          </small>
                        </article>
                      ))
                    ) : (
                      <p className="empty-inline">
                        该日尚无保存记录。先完成分析、情景计算或人工复核，再点击保存。
                      </p>
                    )}
                  </div>
                </Panel>
              )}
              {snapshot && (
                <Panel
                  title="保存时的证据快照"
                  subtitle={`${snapshot.scope.date} · 前 ${snapshot.scope.cursor} 时段 · 文件版本 ${snapshot.source_hash.slice(0, 12)}；不随当前回放变化。`}
                  action={
                    <button onClick={() => setSnapshot(null)}>关闭快照</button>
                  }
                >
                  <div className="table-wrap">
                    <table className="presentation-table">
                      <thead>
                        <tr>
                          <th>原始行号</th>
                          <th>区间</th>
                          <th>光伏实际 / MW</th>
                          <th>日前价</th>
                          <th>实时价</th>
                        </tr>
                      </thead>
                      <tbody>
                        {snapshot.evidence.source_records.map((r) => (
                          <tr key={r.slot}>
                            <td>{r.source_line}</td>
                            <td>
                              {time(r.interval_start)}–{time(r.interval_end)}
                            </td>
                            <td>{fmt(r.pv_actual_mw)}</td>
                            <td>{fmt(r.da_price)}</td>
                            <td>{fmt(r.rt_price)}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </Panel>
              )}
            </>
          )}
          <p className="public-basis-note">{meta.basis}</p>
        </>
      )}
    </div>
  );
}
