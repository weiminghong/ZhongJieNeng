"use strict";

const state = { page: "overview", data: null, context: null, request: 0, chat: [] };
const pages = {
  overview: ["运行总览", "先了解场站出力与预测表现，再定位需要关注的时段。"],
  raw: ["原始数据", "逐时段查看原始记录，检查缺失、到数范围与数据口径。"],
  generation: ["发电预测", "在同一时间轴上对比日前功率、日内修正与实际出力。"],
  price: ["电价与价差", "分别查看日前预测、日前出清价格，以及实时价格与价差。"],
  analysis: ["偏差分析", "按相同实测时段评估预测，结合天气与运行信息查找线索。"],
  agent: ["Agent 分析", "基于当前场站和日期调用数据工具，查询指标、时段与业务依据。"],
  training: ["模型训练", "查看训练能力的接入范围和前置条件。"],
  rsi: ["RSI 迭代", "查看反馈、候选改进和验证发布的建设范围。"],
};
const colors = { actual: "#007e78", forecast: "#3174c4", corrected: "#d49b32", muted: "#a5b5c3", negative: "#c9634d" };
const $ = (selector) => document.querySelector(selector);
const escapeHTML = (value) => String(value).replace(/[&<>"']/g, (char) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[char]));
const number = (value, digits = 2) => value == null ? "—" : Number(value).toLocaleString("zh-CN", { minimumFractionDigits: digits, maximumFractionDigits: digits });

function filterParams() {
  return new URLSearchParams({ station: $("#station").value, date: $("#date").value, daylight: $("#daylight").checked ? "1" : "0" });
}

async function fetchJSON(url, options) {
  const response = await fetch(url, options);
  const value = await response.json();
  if (!response.ok) throw new Error(value.error || "数据请求失败");
  return value;
}

function stat(label, value, unit, note) {
  return `<div class="stat"><div class="stat-label">${label}</div><div class="stat-value">${value}<small>${unit}</small></div><div class="stat-note">${note}</div></div>`;
}

function panel(title, caption, body, action = "") {
  return `<section class="panel"><div class="panel-heading"><h2>${title}</h2>${action}</div>${caption ? `<p class="panel-caption">${caption}</p>` : ""}${body}</section>`;
}

function chart(id, short = false) {
  return `<div id="${id}" class="chart${short ? " short" : ""}" role="img" aria-label="${id}"></div>`;
}

function table(headers, rows, className = "") {
  return `<div class="table-scroll"><table class="${className}"><thead><tr>${headers.map((item) => `<th scope="col">${item}</th>`).join("")}</tr></thead><tbody>${rows.length ? rows.map((row) => `<tr>${row.map((item) => `<td>${item}</td>`).join("")}</tr>`).join("") : `<tr><td colspan="${headers.length}">当前筛选范围没有可用记录</td></tr>`}</tbody></table></div>`;
}

function trace(name, key, color, dash = "solid", rows = state.data.rows) {
  return { x: rows.map((row) => row.time), y: rows.map((row) => row[key]), type: "scatter", mode: "lines", name, connectgaps: false, line: { color, width: 2.5, dash }, hovertemplate: "%{x}<br>%{y:.2f}<extra>%{fullData.name}</extra>" };
}

function plot(id, traces, unit, options = {}) {
  const element = document.getElementById(id);
  if (!element) return;
  Plotly.newPlot(element, traces, {
    font: { family: "Microsoft YaHei, sans-serif", color: "#607386", size: 11 },
    paper_bgcolor: "#fff", plot_bgcolor: "#fff", hovermode: "x unified",
    margin: { l: 60, r: 24, t: 50, b: 48 },
    legend: { orientation: "h", x: 0, y: 1.16, font: { size: 11 } },
    xaxis: { showgrid: false, tickmode: "auto", nticks: 9, zeroline: false, title: { text: "北京时间" } },
    yaxis: { title: { text: unit, standoff: 12 }, gridcolor: "#edf1f5", zerolinecolor: "#dae3ea", rangemode: "tozero" },
    ...options,
  }, { responsive: true, displaylogo: false, modeBarButtonsToRemove: ["lasso2d", "select2d", "autoScale2d"] });
}

function generationTraces(includeCorrected = true) {
  const traces = [trace("实际出力", "actual", colors.actual), trace("日前预测", "forecast", colors.forecast, "dash")];
  if (includeCorrected) traces.push(trace("日内修正", "corrected", colors.corrected, "dot"));
  return traces;
}

function sortedErrors() {
  return state.data.rows.filter((row) => row.actual !== null).sort((a, b) => Math.abs(b.forecast - b.actual) - Math.abs(a.forecast - a.actual));
}

function completenessText() {
  const metrics = state.data.metrics;
  return `${metrics.observed_count} / ${metrics.due_count} 个到期时段`;
}

function renderOverview() {
  const { metrics, rows } = state.data;
  const worst = sortedErrors().slice(0, 3);
  $("#content").innerHTML = `<div class="stats">${stat("已实测发电量", number(metrics.energy_actual), "MWh", "仅累计已到达且有效的实发")}${stat("同期日前预测", number(metrics.energy_forecast_matched), "MWh", "与实测使用相同时段")}${stat("功率预测 MAE", number(metrics.generation.mae), "MW", `${metrics.generation.n} 个有效配对时段`)}${stat("实发到数", completenessText(), "", "未来时段不计为缺失")}</div>
  <div class="grid-main"><div>${panel("发电预测与实际出力", "15 分钟粒度 · 实线为实测，虚线为预测，实测缺失时保留断点", chart("generation-chart"), '<a class="text-link" href="#generation">查看预测详情 ↗</a>')}
  ${panel("日前与实时电价", "元/MWh · 日前出清价格与实时价格采用相同业务时段", chart("overview-price", true), '<a class="text-link" href="#price">查看价差 ↗</a>')}</div>
  <aside>${panel("重点偏差时段", "基于已实测时段的事后分析", worst.length ? worst.map((row) => `<div class="event"><time>${row.time} · 功率偏差</time><strong>日前预测偏${row.forecast > row.actual ? "高" : "低"} ${number(Math.abs(row.forecast - row.actual))} MW</strong><p>实际 ${number(row.actual)} MW · 云量 ${number(row.cloud * 100, 0)}%</p></div>`).join("") : '<div class="panel-body">实际结果尚未到达，待到数后生成分析。</div>')}
  ${panel("数据与业务口径", "", `<div class="panel-body"><div class="definition"><strong>${escapeHTML(state.data.station.name)}</strong><span>装机容量 ${state.data.station.capacity} MW</span></div><div class="definition"><strong>预测、实测分开记录</strong><span>未来实测保持空值。日内修正曲线从其发布时点起展示。</span></div><a href="#agent" class="text-link">向 Agent 查询本日表现 ↗</a></div>`)}</aside></div>`;
  plot("generation-chart", generationTraces(), "MW");
  plot("overview-price", [trace("日前出清价格", "da_price", colors.forecast), trace("实时价格", "rt_price", colors.actual)], "元/MWh");
}

function qualityTag(value) {
  const kind = value.includes("缺失") ? "warning" : value === "待实测" ? "pending" : "";
  return `<span class="tag ${kind}">${escapeHTML(value)}</span>`;
}

function rawRows(rows) {
  return rows.map((row) => [row.time, number(row.actual), number(row.forecast), number(row.irradiance, 1), number(row.temperature, 1), `${number(row.cloud * 100, 0)}%`, number(row.da_price), number(row.rt_price), qualityTag(row.quality)]);
}

function renderRaw() {
  const { metrics, rows } = state.data;
  $("#content").innerHTML = `<div class="note">每行代表区间起点标注的 15 分钟时段。实发和实时电价按演示时钟到数，缺失值以“—”显示。天气列属于演示场景变量。</div>
    <div class="stats">${stat("当前记录", rows.length, "条", state.data.scope)}${stat("到期时段", metrics.due_count, "个", "按演示时钟判断")}${stat("实发有效记录", metrics.observed_count, "条", "已到期且非空")}${stat("字段缺失记录", metrics.quality_count, "条", "实发或辐照度缺失")}</div>
    ${panel("分时原始记录", "实发 MW · 辐照度 W/m² · 温度 ℃ · 电价 元/MWh", '<input class="search" id="raw-search" placeholder="搜索时刻或质量状态，如 12: 或缺失" aria-label="搜索原始记录"><div id="raw-table"></div>')}`;
  const renderTable = (query = "") => {
    const selected = rows.filter((row) => `${row.time} ${row.quality}`.includes(query));
    $("#raw-table").innerHTML = table(["时刻", "实发 MW", "日前预测 MW", "实测辐照度", "温度", "云量", "日前出清价", "实时价", "数据状态"], rawRows(selected));
  };
  renderTable();
  $("#raw-search").addEventListener("input", (event) => renderTable(event.target.value.trim()));
}

function renderGeneration() {
  const { metrics, rows } = state.data;
  const firstCorrection = rows.find((row) => row.correction_issued_at)?.correction_issued_at;
  const issued = rows[0]?.forecast_issued_at.replace("T", " ").slice(0, 16);
  $("#content").innerHTML = `<div class="stats">${stat("目标时段预测电量", number(metrics.energy_forecast), "MWh", "功率 × 0.25 小时后累加")}${stat("日前 MAE", number(metrics.generation.mae), "MW", `${metrics.generation.n} 个有效配对`)}${stat("日前 RMSE", number(metrics.generation.rmse), "MW", "保留误差原单位")}${stat("可比较修正时段", metrics.correction_matched.n, "个", "已实测且存在日内修正")}</div>
    ${panel("分时功率预测", "点击图例可隐藏或显示曲线，拖动图表可放大时段", `<div class="metadata"><span>版本 ${state.data.model}</span><span>日前发布 ${issued || "—"}</span><span>日内发布 ${firstCorrection ? "当日 10:00" : "暂无"}</span><span>时区 Asia/Shanghai</span></div>${chart("forecast-chart")}`)}
    <div class="grid-two">${panel("日内修正前后对比", "只统计修正已发布、且实发已到达的同一批时段", table(["预测版本", "样本数", "MAE / MW", "RMSE / MW"], [["日前基线", metrics.baseline_matched.n, number(metrics.baseline_matched.mae), number(metrics.baseline_matched.rmse)], ["日内修正", metrics.correction_matched.n, number(metrics.correction_matched.mae), number(metrics.correction_matched.rmse)]]))}
    ${panel("读图说明", "", '<div class="panel-body"><div class="definition"><strong>MW 表示瞬时功率</strong><span>区间电量按 15 分钟功率乘 0.25 小时计算，单位 MWh。</span></div><div class="definition"><strong>合成预测场景</strong><span>当前曲线展示业务语义，模型训练尚未接入。修正前后对比是演示场景结果。</span></div></div>')}</div>`;
  plot("forecast-chart", [...generationTraces(), trace("晴空物理基线", "physical", colors.muted, "dashdot")], "MW");
}

function renderPrice() {
  const { rows, metrics } = state.data;
  const arrived = rows.filter((row) => row.rt_price !== null);
  const mean = (key) => rows.reduce((total, row) => total + row[key], 0) / rows.length;
  const spread = rows.map((row) => ({ ...row, spread_actual: row.rt_price === null ? null : row.rt_price - row.da_price, spread_pred: row.rt_pred - row.da_price }));
  $("#content").innerHTML = `<div class="stats">${stat("日前出清均价", number(mean("da_price")), "元/MWh", "演示公布价格")}${stat("日前预测 MAE", number(metrics.price.mae), "元/MWh", "日前预测与日前出清配对")}${stat("实时预测 MAE", number(metrics.rt_price.mae), "元/MWh", `${arrived.length} 个已到达时段`)}${stat("实时到数", arrived.length, "时段", "价差 = 实时价格 − 日前出清价")}</div>
    ${panel("日前价格预测与出清", "蓝色虚线为日前预测，实线为日前出清价格", chart("da-price"))}
    <div class="grid-two">${panel("实时价格预测与实绩", "历史已到达价格与预测走势对比", chart("rt-price", true))}${panel("实时与日前价差", "正值表示实时价高于日前价，零线用于区分方向", chart("spread-chart", true))}</div>
    <div class="note">价格以元/MWh 展示。当前数据未接入浙江实际结算节点、交易合同与考核规则，界面仅呈现价格与价差分析。</div>`;
  plot("da-price", [trace("日前预测", "da_pred", colors.forecast, "dash"), trace("日前出清价", "da_price", colors.actual)], "元/MWh");
  plot("rt-price", [trace("实时预测", "rt_pred", colors.forecast, "dash"), trace("实时价格", "rt_price", colors.actual)], "元/MWh");
  plot("spread-chart", [trace("预测价差", "spread_pred", colors.forecast, "dash", spread), trace("实际价差", "spread_actual", colors.actual, "solid", spread)], "元/MWh");
}

function renderAnalysis() {
  const worst = sortedErrors();
  $("#content").innerHTML = `<div class="note">偏差按“日前预测 − 实际功率”计算。气象散点图用于寻找相关线索，结论需结合设备、限电和运行记录复核。</div>
    <div class="grid-two">${panel("功率偏差分布", "正值为预测偏高，负值为预测偏低", chart("error-chart"))}${panel("云量与绝对误差", "仅使用实际出力已到达的时段", chart("factor-chart"))}</div>
    ${panel("重点时段及关联因素", "按绝对偏差排序，可导出数据后进行业务复核", table(["时刻", "预测 MW", "实际 MW", "偏差 MW", "云量", "温度 ℃", "设备可用率"], worst.slice(0, 12).map((row) => [row.time, number(row.forecast), number(row.actual), number(row.forecast - row.actual), `${number(row.cloud * 100, 0)}%`, number(row.temperature, 1), "100%"])))}`;
  plot("error-chart", [{ x: worst.map((row) => row.time).sort(), y: state.data.rows.filter((row) => row.actual !== null).map((row) => row.forecast - row.actual), type: "bar", name: "预测偏差", marker: { color: colors.forecast } }], "MW");
  plot("factor-chart", [{ x: worst.map((row) => row.cloud * 100), y: worst.map((row) => Math.abs(row.forecast - row.actual)), text: worst.map((row) => row.time), type: "scatter", mode: "markers", name: "时段样本", marker: { color: colors.actual, size: 7, opacity: 0.7 }, hovertemplate: "%{text}<br>云量 %{x:.0f}%<br>绝对误差 %{y:.2f} MW<extra></extra>" }], "绝对误差 MW", { hovermode: "closest", xaxis: { title: { text: "云量 %" }, gridcolor: "#edf1f5" }, showlegend: false });
}

function renderAgent() {
  $("#content").innerHTML = `<div class="chat-layout"><section class="panel"><div class="panel-heading"><h2>业务数据助手</h2><span class="tag">本地工具分析</span></div><p class="panel-caption">按当前场站与日期查询。此入口尚未接入大语言模型。</p><div class="chat-body" id="messages"></div>
    <form class="chat-form" id="chat-form"><input id="question" placeholder="查询发电偏差、电价或数据质量…" maxlength="1000" aria-label="输入业务问题" required><button class="button" type="submit">分析</button></form></section>
    <aside>${panel("当前分析范围", "", `<div class="panel-body"><div class="definition"><strong>${escapeHTML(state.data.station.name)}</strong><span>${state.data.date} · ${state.data.scope}</span></div><div class="definition"><strong>合成演示数据</strong><span>原始数据、图表和回答使用同一份时段记录。</span></div><div class="definition"><strong>工具能力</strong><span>数据查询、配对评估、价差分析、缺失检查。</span></div></div>`)}</aside></div>`;
  displayMessages();
  $("#chat-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const question = $("#question").value.trim();
    if (!question) return;
    await ask(question);
  });
}

function displayMessages() {
  const target = $("#messages");
  if (!target) return;
  if (!state.chat.length) {
    target.innerHTML = '<div class="assistant-message">可以帮你查询当前场站的预测与实发差异、实时价差，以及缺失数据。</div><div class="suggestions"><button type="button">今天发电预测偏差怎么样？</button><button type="button">哪个时段实时价差最大？</button><button type="button">原始数据有没有缺失？</button></div>';
    target.querySelectorAll(".suggestions button").forEach((button) => button.addEventListener("click", () => ask(button.textContent)));
    return;
  }
  target.innerHTML = state.chat.map((message) => message.role === "user"
    ? `<div class="user-message">${escapeHTML(message.text)}</div>`
    : `<div class="assistant-message">${escapeHTML(message.text)}${message.tools ? `<div class="tools">调用工具 ${message.tools.map(escapeHTML).join(" / ")} · ${escapeHTML(message.context)}</div><a class="text-link" href="#${message.link}">查看对应数据 ↗</a>` : ""}</div>`).join("");
}

async function ask(question) {
  const form = $("#chat-form");
  if (form.querySelector("button").disabled) return;
  state.chat.push({ role: "user", text: question });
  displayMessages();
  form.querySelector("button").disabled = true;
  $("#question").value = "";
  const requestContext = filterParams().toString();
  try {
    const result = await fetchJSON("/api/analyze", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ question, ...Object.fromEntries(filterParams()) }) });
    if (requestContext === filterParams().toString()) state.chat.push({ role: "assistant", ...result });
  } catch (error) {
    state.chat.push({ role: "assistant", text: error.message });
  } finally {
    if (document.contains(form)) form.querySelector("button").disabled = false;
    displayMessages();
  }
}

function renderReadiness() {
  const training = state.page === "training";
  const rows = training ? [
    ["四项预测模型", "10 号服务器材料记录了四项离线结果，源码与模型包尚待访问核验。", "待迁移"],
    ["场站训练数据", "本页当前使用合成场景，正式训练需历史实发、天气预报版本和市场输入。", "待交付"],
    ["训练与评估入口", "接入后记录训练区间、特征版本、模型产物和同样本测试指标。", "待建设"],
  ] : [
    ["反馈数据", "保存预测快照、真实结果和业务人员审核记录。", "待接入"],
    ["候选改进", "根据误差和审核意见生成可验证的特征、模型或工具调用改进。", "待建设"],
    ["验证与发布", "固定数据和预算验证候选改进，审批后启用，保留版本回退。", "待建设"],
  ];
  $("#content").innerHTML = `<div class="note notice">当前交付聚焦业务展示与数据分析。这部分页面用于明确后续接入内容，尚无训练或自进化任务在运行。</div>${panel(training ? "模型训练接入清单" : "RSI 能力接入清单", "", table(["能力", "所需内容", "状态"], rows.map(([name, description, status]) => [name, description, `<span class="tag pending">${status}</span>`]), "status-table"))}`;
}

function render() {
  document.querySelectorAll(".js-plotly-plot").forEach((element) => Plotly.purge(element));
  const [title, description] = pages[state.page];
  $("#page-title").textContent = title;
  $("#page-description").textContent = description;
  $("#crumb").textContent = title;
  document.title = `${title} · 中节能光伏交易工作台`;
  document.querySelectorAll("nav a").forEach((link) => {
    link.classList.toggle("active", link.dataset.page === state.page);
    if (link.dataset.page === state.page) link.setAttribute("aria-current", "page");
    else link.removeAttribute("aria-current");
  });
  const renderers = { overview: renderOverview, raw: renderRaw, generation: renderGeneration, price: renderPrice, analysis: renderAnalysis, agent: renderAgent, training: renderReadiness, rsi: renderReadiness };
  renderers[state.page]();
  $("#content").setAttribute("aria-busy", "false");
}

async function loadData() {
  const requestId = ++state.request;
  $("#global-error").hidden = true;
  $("#refresh-button").disabled = true;
  $("#export-button").disabled = true;
  $("#content").setAttribute("aria-busy", "true");
  try {
    const data = await fetchJSON(`/api/data?${filterParams()}`);
    if (requestId !== state.request) return;
    state.data = data;
    state.chat = [];
    $("#context-label").textContent = `${data.station.capacity} MW · 15 分钟 · ${data.scope}`;
    render();
  } catch (error) {
    if (requestId === state.request) {
      $("#global-error").textContent = `${error.message}。可点击“刷新数据”重试。`;
      $("#global-error").hidden = false;
      $("#content").innerHTML = '<div class="loading">当前筛选数据尚未加载，请刷新重试。</div>';
    }
  } finally {
    if (requestId === state.request) {
      $("#refresh-button").disabled = false;
      $("#export-button").disabled = !$("#global-error").hidden;
      $("#content").setAttribute("aria-busy", "false");
    }
  }
}

function exportCSV() {
  if (!state.data) return;
  const keys = Object.keys(state.data.rows[0]);
  const csvValue = (value) => `"${String(value ?? "").replace(/"/g, '""')}"`;
  const csv = "\ufeff" + [keys.join(","), ...state.data.rows.map((row) => keys.map((key) => csvValue(row[key])).join(","))].join("\r\n");
  const url = URL.createObjectURL(new Blob([csv], { type: "text/csv;charset=utf-8" }));
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = `演示_${state.data.station.name}_${state.data.date}.csv`;
  anchor.click();
  URL.revokeObjectURL(url);
}

async function initialize() {
  try {
    state.context = await fetchJSON("/api/context");
    $("#asof").textContent = `演示时钟 ${state.context.as_of.slice(5, 10)} ${state.context.as_of.slice(11, 16)}`;
    $("#station").innerHTML = state.context.stations.map((station) => `<option value="${station.id}">${station.name}</option>`).join("");
    $("#date").innerHTML = state.context.dates.map((date) => `<option value="${date}">${date}</option>`).join("");
    $("#date").value = state.context.default_date;
    state.page = location.hash.slice(1) in pages ? location.hash.slice(1) : "overview";
    await loadData();
  } catch (error) {
    $("#global-error").textContent = `${error.message}。请检查网络后刷新页面。`;
    $("#global-error").hidden = false;
    $("#content").innerHTML = '<div class="loading">服务暂不可用，请刷新页面重试。</div>';
  }
}

window.addEventListener("hashchange", () => {
  state.page = location.hash.slice(1) in pages ? location.hash.slice(1) : "overview";
  if (state.data) render();
});
$("#filters").addEventListener("submit", (event) => { event.preventDefault(); loadData(); });
["#station", "#date", "#daylight"].forEach((selector) => $(selector).addEventListener("change", loadData));
$("#export-button").addEventListener("click", exportCSV);
$("#about-button").addEventListener("click", () => $("#about-dialog").showModal());
$("#close-dialog").addEventListener("click", () => $("#about-dialog").close());
initialize();
