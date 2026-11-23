# 中节能项目 Harness

- 唯一本地工作区：`C:\Users\wmh\Documents\ChatGPT\中节能项目`；唯一发布工作区：GB10 `priv@10.21.179.91:/home/priv/ZhongJieNeng`。普通产品源码在本地开发、测试、构建、提交后发布；服务器实验与大资产只在服务器处理。
- 当前发布分支为 `codex/agent-workbench`。不得修改 `short-drama-production/`、`vendor/` 子模块内部代码或夹带其他任务资产。
- `src/cecep_console/storage_sql/001_initial.sql` 不可修改。迁移按序号追加，校验旧迁移 checksum，必须保留旧库数据。L1、预测、审计采用追加式记录；只有 `serving_*` 允许重建。
- `DESIGN.md` 是颜色唯一事实源。运行 `node scripts/generate_design_tokens.mjs` 生成 CSS；组件和图表只读语义 Token，禁止硬编码颜色。
- 前后端使用真实 `/api/v1/*`；失败显示错误、空数据显示空状态，禁止静默 mock、假成功或虚构证据。所有合成输入及演示模型显式标记 `source_mode=synthetic`。未配置 LLM 必须标记 `deterministic_tools_only`；演示模型没有真实训练与生产能力证明。
- 收益由确定性规则引擎计算；演示 ±5% 免考只作沙盘参考，不声称为真实市场规则。PIT 回放按 `available_at <= cutoff_at`；训练不得使用 serving 宽表。
- 完成逻辑批次：运行完整 Python 测试、Token 生成与 Web build → 精确 stage 本批次文件 → 中文 `[codex]` commit → push `origin/codex/agent-workbench` → GB10 fast-forward、迁移、同步已验证 dist、只重启 `cecep-storage.service` → HTTP 与 DB 验收。不得影响 8501/8502 服务。
- 凭据仅从环境或交互秘密输入获取，不进入仓库、日志和验收收据。运行产物置于忽略的 `runtime/`。

- 永久用词规范：所有前端界面文案、代码注释、CSS 类名、API 文案、文档及提交信息，禁止使用车辆操控相关称谓及其英文座舱称谓；统一使用 `智能体助手`、`随行智能体`、`双栏工作区`、`外部演示面板`、`.forecast-workspace`。
