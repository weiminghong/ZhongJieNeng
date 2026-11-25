# 中节能光储交易 Agent 工作台 v1

基于既有 SQLite PIT 底座的联库工作台：预测与版本对比、原始数据与血缘、申报策略与收益、双通道 Agent、偏差审核与 RSI。新版由 FastAPI + React 19 / TypeScript / Vite 6 / Tailwind 4 / ECharts 提供，GB10 入口为 **http://10.21.179.91:8503**。

场站演示工作区的时序、演示模型与参考规则为 **synthetic 合成演示**。另已接入 GB10 原项目保留的 **PriceForecast 山东公开市场历史数据**，作为独立研究工作区使用。公开市场数据不等于岚能、凌光的生产记录；模型名称也不代表本站已完成训练。配置外部摘要模型是可选项，未配置时明确使用 `deterministic_tools_only`。

## 结构与合同

- `src/cecep_console/storage_sql/001_initial.sql`：原 34 张表，不修改；`002_upper_layers.sql`：11 张上层业务表、3 张 serving 宽表与 FTS5。迁移顺序执行并校验历史 checksum。
- `serving.py`：L1/PIT 联合生成 96 点、日 KPI 和同 cutoff 版本比较。普通页面直读 serving，回放实时调用 `Store.as_of` / `Store.predictions`。训练禁止读取 serving 表。
- `trading.py`：确定性结算。合同 + 日前现货 + 实时偏差 − 超免考考核 = 净收益；只结算实测和价格齐备的时段。演示 ±5% 容量免考及 70% 锁价示例不代表浙江正式规则。
- `agent_service.py`：通道 1 包含五个数据库/计算工具；通道 2 为 FTS5 BM25 + 中文 bigram TF-IDF。问答、输入证据快照、工具调用和引用全部持久化。日内/复盘知识检索使用当前知识时点，回放知识也受 cutoff 限制。
- `rsi.py`：人工确认反馈、案例沉淀、审批与回滚均采用追加式记录。演示审批改变注册状态及展示主版本，不会触发真实训练。
- `api.py`：统一 `/api/v1/*` 与兼容 `/api/storage/*`；`apps/web/dist` 同源提供 SPA。`DESIGN.md` 为唯一颜色事实源。

定稿架构参考：[底层到上层全栈架构设计](design/全栈系统架构与底层到上层设计方案.md)。实现采用 Vite SPA；公开市场模型链路使用服务器上的 NumPy CPU 工作进程，不需要新增训练依赖。

## 本地构建与测试

```bash
python -m venv .venv
# Windows: .venv/Scripts/python.exe；Linux: .venv/bin/python
.venv/bin/python -m pip install -e ".[test]"
node scripts/generate_design_tokens.mjs
npm --prefix apps/web ci
npm --prefix apps/web run build
.venv/bin/python -m unittest discover -s tests -v
```

测试使用独立临时 SQLite 库，覆盖旧版 001 升级、checksum、PIT 防穿越、serving 路由、手算结算、RAG/RSI、审批回滚、完整 API 读写与 provider 失败审计。`apps/web/dist` 和 `node_modules` 不进入 Git。

## GB10 发布

唯一发布目录 `/home/priv/ZhongJieNeng`，分支 `codex/agent-workbench`。源码提交推送后，使用本机既有 paramiko：

```powershell
# CECEP_GB10_PASSWORD 通过会话环境或秘密输入提供，不写入文件
python scripts/sync_gb10.py
```

脚本验证远端工作树，fast-forward 到本地已验证 commit；在线备份旧 SQLite；安装依赖；校验每个 dist 文件的 SHA256 后切换；执行增量迁移与幂等 seed；仅重启 `cecep-storage.service`。随后进行真实 HTTP、Agent、审核入库、FTS5 命中、审批回滚与数据库完整性验收，结果写入被忽略的 `runtime/gb10-deploy-receipt.json`。`--verify-only` 跳过部署，仍执行包含合成反馈写入和审批回滚的完整验收。

服务入口仍为 `scripts/start_storage.sh`，默认监听 8503。原 8501 外部演示面板与 8502 中文 Evidently 报告服务保留，不修改其启动或代码。远端第三方子模块的既存改动不覆盖。

## 可选外部摘要器

打开 `/settings`，或从 Agent 页进入“模型配置”，设置 OpenAI 兼容 Base URL、模型 ID、API Key、启用状态与请求参数。默认模型 ID 为 `qwen3.8-27b`，地址需与密钥所属区域和服务控制台一致。保存后立即对后续 Agent 请求生效，无需重启。先保存，再使用“测试已保存的连接”发送一次最小真实请求；保存成功不等于连接已验证。

密钥只写入被忽略的 `runtime/private/llm-settings.json`（目录 0700、文件 0600）；可通过 `CECEP_LLM_SETTINGS_PATH` 指定私有位置。配置 GET 仅返回是否已保存，不返回密钥；页面留空保留原密钥，移除需要显式勾选。密钥不进入业务数据库、构建产物或部署收据。本站配置写接口检查同源 Origin 和专用请求头，沿用项目内网部署范围。

尚无私有配置文件时，可从服务环境读取 `CECEP_LLM_API_KEY`、`CECEP_LLM_BASE_URL` 和 `CECEP_LLM_MODEL`；私有文件保存后优先使用页面配置。不开启外部模型时保持 `deterministic_tools_only`。模型只返回既有证据句的选择顺序，数值由工具计算并约束；失败返回 502 与 `provider_failed`，失败记录仍保存。配置不下载模型、不训练权重，也不构成业务预测效果证明。

## 展示口径

北京时间（Asia/Shanghai），15 分钟区间起点标时；功率 MW、电量 MWh、电价元/MWh，价差为 RT−DA。合成数据时钟固定 2026-11-20 14:00。真实零值、应到缺测、未来待到达分开显示。日前版本比较固定同 cutoff 与共同实测样本；日内修正明确标为新增信息。漂移告警是演示 fixture，不能当成 Evidently 的实测结论；外部报告链接状态与漂移示例分别标识。

## 光伏双栏工作区

首页按光伏概念稿实现浅绿白底导航、紧凑指标带、上下联动的功率/电价图和同口径版本表，右侧常驻时段详情、原始证据入口及智能体提问。图表空白处点击、时段下拉和前后切换均更新同一分析范围；数据、交易、复核和智能体保留该范围。移动端把详情接在分析区下方。

概念稿为 `design/光伏交易工作台-Image2概念稿.png`，使用内置 ImageGen 参考原图重制；提示方向为“保持左导航、中央预测与电价、右侧证据与智能体，将风电全部替换为光伏，夜间功率归零，采用已核验合成快照的字段与量级，明确合成演示和未训练状态”。图片仅用于视觉参考，生成的曲线与文字不作为业务事实。页面全部从真实 API 读取数据。

`GET /api/v1/workbench/readiness?station_id=...&source_mode=...` 只读统计当前场站的实测、预测快照、天气和市场价格到达记录，并列出推理适配器及功能边界。`bootstrap` 的日期按场站和数据口径过滤，生产记录不会被写死的空状态挡住；原始证据已有、预聚合尚未生成时，概览使用 PIT 查询。只有合成数据时生产页显示空状态，不混用合成曲线。

现有内置光伏历史拟合和外部权重登记/推理可以执行；场站真实生产数据、正式规则和生产精度验收仍待接入。公开市场训练与场站演示审批分开，登记模型不代表已训练。

## 公开市场训练与迭代

入口 `/?workspace=public&tab=learning`。`learning.py` 从既有山东源文件的实时价格构造 D−2 及以前的13个历史/日历特征，训练集拟合填补、标准化和缺失指示后训练 NumPy Ridge。三个基线与候选使用共同标签掩码；负价不裁剪，标签缺失保留排除清单。冻结合同为 `design/闭环执行合同.json`，历史到达时间未经验证，始终 `historical_assumed`、`production_eligible=false`。

005迁移新增 `ml_object`、`ml_job`、`ml_event` 三张追加式表，保存数据、模型、预测、复核、提案、审计和审批事件。API为 `GET /api/v1/ml/{overview,capabilities}`、`GET /api/v1/ml/objects/{id}`、`GET /api/v1/ml/jobs/{id}`、`GET /api/v1/ml/lineage/{id}` 与 `POST /api/v1/ml/commands`。命令使用受限 `action`，不接受任意脚本或文件路径；每个写操作保存声明操作者和理由。当前身份为内网声明，尚未接入企业认证。

`start_storage.sh` 启用一个受服务管理的控制器，文件锁串行准入；每次训练运行独立CPU子进程，最多4线程、30分钟。API监测控制器实际退出后重启；遗留任务验证PID出生标识，未知旧退出保留 `unknown_exit`，重试创建新对象。取消只作用于控制器持有的该任务子进程。阶段、退出码、耗时、峰值RSS来自实际执行。NPZ使用 `allow_pickle=False`，保存哈希、完整原始行/排除清单、训练划分、代码commit、候选/基线原生预测和加载校验。实际资产全部留在 GB10 `runtime/ml/`。

页面支持登记版本、排队/取消/重试、96点权重推理、确定性工具及可选外部证据摘要、逐点复核、人工确认、参数重训提案、同掩码比较与审批回滚。参数调整复用原数据集；调参窗口反馈可支持重新选参，提升/终评窗口反馈不能继续复用同窗口选择候选。意见不修改原始标签，也不自动成为训练样本。初次只初始化 D−2 基线；后续升级需配对7天块bootstrap的 MAE 差95%上界小于0且RMSE不劣于现任版本。结果不达标可明确拒绝，不能修改门槛。

最终审计需冻结唯一Ridge权重并明确启封；每个源版本只允许一次，失败也消耗资格，后续调参不得重称独立检验。源文件每30秒检查版本，变化后保存质量快照并尝试已批准主模型的推理/证据分析；封存窗口和版本边界仍会拦截，未产生新记录不制造行情，不自动训练。

服务器实际训练与发布验收结果写入忽略的 `runtime/learning-loop-acceptance.json`。代码接口、功能测试、训练完成和模型业务增益分别验收；本链路不代表其余场站功率、浙江收益或五类任务全部完成。

知识检索在相关性同分时优先返回截止时点内较新的证据；文档与切片均受创建时点约束，历史回放不读取后来新增的切片。重复验收产生的旧案例不会再仅因随机 ID 顺序挤掉新案例。

## 已有公开数据与操作链路

默认进入“公开市场研究（山东）”。后端直接读取 GB10 已有 `/home/priv/cecep_rsi_demo/vendor/price_forecast/data/价格预测数据集.csv`，也可用服务环境变量 `CECEP_PUBLIC_MARKET_CSV` 指定同类已授权文件。数据集保留在服务器，不复制到工作站，不修改原 vendor 文件。

此次核验版本为 71,520 行、745 天、15 分钟粒度，覆盖 2024-01-01 至 2026-01-14，包含 21 个源字段；SHA-256 为 `5d00ffd26a75078c521ebecbd5aa8eba172d1eaf2816e8b64f05d08a8eee7954`。其中日前价格有 53,424 个空值、实时价格有 88 个空值，空值不补零。后端校验重复时段及数值格式，按文件版本变化更新内存缓存；页面可每30秒检查文件版本，历史文件不生成随机“实时”行情。

操作顺序为：**核对原始数据 → 选择日期与回放范围 → 观察量价与偏差 → 调整价差情景或调用分析 → 保存人工复核**。各页面共享交易日、回放位置、选中记录和源文件版本。播放每次推进一个15分钟时段；图表、配对指标和情景结果都从该范围重新计算。后台读取尚未完成时保留上次范围的画面并注明，禁止把旧结果冒充新范围。

源文件的 `时刻` 是区间终点，`24:00` 归入该交易日的最后一个区间；图表以区间起点标时。回放只展示游标前的记录及原始字段。源文件没有原始发布时间和实际到达时间，因此这是**记录顺序回放，不是严格 PIT 策略回测**；“光伏预测”曲线来自源字段，不代表本站模型新推理或训练效果。原始负值保留。

价差情景按 `Σ[(实时价−日前价−每MWh假设费用)×每时段假设电量]` 计算，属于事后敞口研究，不冒充场站合同结算或可执行套利策略。只在明确点击保存时追加分析、情景或复核记录；`004_public_reference_runs.sql` 保存文件哈希、范围、源行号和原始记录快照，旧迁移不变。

公开数据 API 位于 `/api/v1/public-data/{catalog,series,scenario,analyze,review,history}`。该工作区与“场站工作台（镇海）”隔离；后者保留已有生产接口和合成演示。场站容量按配置版本读取，合约电量/价格与规则参数按数据库记录展示，不再在前端写死70%或380元/MWh。


## 参考软件后的前端与业务交互

公开研究默认进入总览。参考用户提供的GridCast软件，按“取长补短”改进页面组织，不迁入另一项目的模型、负荷单位、用户口令或考核指标。保留原React与FastAPI、光伏场站工作区、既有数据、真实权重与追加式审批。

主要页面：`tab=overview` 总览、`raw` 数据管理、`learning` 训练与模型、`forecast` 预测分析、`compare` 同口径评估、`decompose` 历史分解、`monitor` 运行日志。`market` 保留原光伏量价观察；`source_review` 保留原始记录的复核历史；`rsi` 承接模型预测复核与研究审批。URL中的数据、模型、预测和复核ID跨页面接续。

新增 `/api/v1/research/*` 都是只读视图：`summary`、`data-quality`、`predictions`（日期筛选与分页）、`comparison`、`decomposition`、`prediction-details/{id}` 与 `predictions/{id}/export`。它们直接读取已有CSV和模型产物；查看页面不训练、不启封最终审计、不修改原始标签。最终审计页只读取已经冻结的候选和其既有基线结果，重复输出折叠但不删除版本。

预测解释校验真实权重与特征哈希，并将线性贡献与已保存预测核对。经验范围采用既有调参残差分位数，仅作为 `research-display-v1` 分析视图，不属于独立区间校准或新增模型效果证明。历史分解采用明确的均值/中位数描述，不冒称STL或因果分析。训练协议、生产资格和自动训练限制继续沿用冻结合同。

本轮验收写入忽略的 `runtime/reference-integration-audit.json`；引用压缩包只读，未执行其启动脚本，未将其中的说明当作新指令。界面未照搬CSV上传删除、用户权限和混合模型的假入口：既有源文件仍只读，企业鉴权、额外模型或数据接入需要相应后端能力。
