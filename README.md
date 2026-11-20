# 中节能光伏交易 Agent 工作台

项目分为模型训练、Agent 业务展示、RSI 迭代三个建设方向。当前版本完成业务展示和本地数据分析入口，训练与 RSI 页列出待接入内容。

## 当前入口

默认入口直接复用 `vendor/ai-energy-trading-platform` 的 7 页 HTML 驾驶舱和 22 个 Plotly 图表。自有 `src/cecep_console` 页面保留作为真实场站数据接入后的扩展入口，当前不会作为默认服务。

启动脚本先运行上游项目的 `main.py --export`，再把上游项目目录作为静态资源提供服务。这样甲方先看到现成驾驶舱中的预测、价格、收入、偏差、风险和发电页面。

## 上游驾驶舱内容

- 执行概览：KPI、日发电量、收入走势
- 市场分析：价格热力图、峰谷价差、电价趋势
- 电站表现：容量因子、限电影响、天气辐照
- 收入分析：瀑布图、构成、月度对比
- 预测精度：准确率、预测与实际散点、天气分组
- 偏差分析：偏差散点、考核率、偏差分布
- AI 助手：上游预留入口

这些页面使用上游仓库自带的 90 天模拟数据，不代表中节能真实数据。

## 自有扩展页面

| 页面 | 业务内容 |
| --- | --- |
| 运行总览 | 已实测电量、同期预测、配对误差、重点时段 |
| 原始数据 | 分时实发、预测、天气、市场价格、缺失状态、搜索与 CSV 导出 |
| 发电预测 | 日前功率、日内修正、实发和晴空物理基线，同样本修正对比 |
| 电价与价差 | 日前预测与出清、实时预测与实绩、实时减日前价差 |
| 偏差分析 | 预测残差、气象关联和重点时段 |
| Agent 分析 | 调用本地数据与评估工具回答业务问题，显示分析范围和工具链 |

Agent 当前是本地工具路由，尚未连接大语言模型。页面中的预测为合成场景，模型名称 `demo-scenario-v1` 是场景版本。10 号服务器 `energy_poc` 的读取权限尚未开放，真实数据和模型尚未迁移。

## 数据口径

- 两个演示场站的容量参考项目材料，时序值全部为合成数据。
- 固定演示时钟为北京时间 2026-11-20 14:00。提供 11 月 19 日历史、20 日日内、21 日未来三种状态。
- 15 分钟时段以区间起点标注，区间结束后才出现实际功率和实时价格。未来实际值保持空值。
- 功率单位 MW，电量按有效时段功率乘 0.25 小时累加，单位 MWh。
- 预测误差只统计实测已到达的配对时段。日内修正对比只统计原预测、修正值和实发均存在的同一批时段。
- 电价单位元/MWh，价差定义为实时价格减日前出清价格。
- 天气关联用于人工分析线索，未进行因果判定。

## 开源集成

上游代码固定为 Git 子模块，无需复制修改。

| 项目 | 调用位置 | 用途 |
| --- | --- | --- |
| solar-forecast | `adapters.solar_components`、`data.records` | 计算采用上海时区的场站晴空物理功率基线 |
| AI Energy Trading Platform | `adapters.evaluate_predictions` | 使用上游 `ModelEvaluator` 计算配对 MAE/RMSE |
| Plotly.js | 服务器 `/plotly.js` | 本地加载可交互曲线、柱图和散点图 |

界面结构重新设计，借鉴上游的预测、市场与偏差分析分类。许可与使用说明见 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。

## 本地开发

```bash
git submodule update --init
python -m venv .venv
# Windows 使用 .venv/Scripts/python；Linux 使用 .venv/bin/python
.venv/bin/python -m pip install -e .
.venv/bin/python -m cecep_console.server --host 127.0.0.1 --port 8501
```

打开 `http://127.0.0.1:8501`。页面资源全部由本地服务提供。

```bash
.venv/bin/python -m unittest discover -s tests -v
node --check src/cecep_console/static/app.js
```

## 部署到 GB10

从 GitHub 拉取已验证的提交，在服务器项目专用环境安装依赖并运行 `scripts/start.sh`。部署前确认端口空闲，不修改其他任务。

```bash
git clone --branch codex/agent-workbench https://github.com/weiminghong/ZhongJieNeng.git
cd ZhongJieNeng
git submodule update --init
python3 -m venv .venv
.venv/bin/python -m pip install -e .
./scripts/start.sh
```

`runtime/` 保存项目日志和临时缓存，已排除在 Git 之外。凭据通过既有 SSH 认证提供，不保存在代码中。
