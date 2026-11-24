# 中节能光储交易工作台设计系统

面向调度员、交易分析师和模型审核人的分析工作台。浅色侧栏以深绿品牌和选中态承载导航，浅灰绿主区承载筛选、图表、表格和证据操作；预测、数据、交易、智能体与审核共享场站、日期、模式和选中时段。以 BirdCurve 的市场分析组织为参考，根据本项目数据和业务流程实现，不引入其数据或模型。

## 颜色唯一事实源

以下 JSON 是可执行 Token 合同。`scripts/generate_design_tokens.mjs` 从此生成 CSS，不手改生成物。

```json design-tokens
{
  "standard-light": {
    "background": "#f2f5f3",
    "surface": "#ffffff",
    "surface-container": "#f6f8f6",
    "on-surface": "#173a2e",
    "on-surface-variant": "#53665d",
    "outline": "#d8e1db",
    "primary": "#176447",
    "primary-container": "#e7f1e9",
    "on-primary": "#ffffff",
    "success": "#13796a",
    "success-container": "#e0f2ec",
    "warning": "#9a5b08",
    "warning-container": "#fff2d9",
    "error": "#b42318",
    "error-container": "#fee4e2",
    "data": "#6d7e74",
    "scrim": "#173a2e66"
  },
  "high-contrast-light": {
    "background": "#e9eeea",
    "surface": "#ffffff",
    "surface-container": "#f0f5f1",
    "on-surface": "#092318",
    "on-surface-variant": "#344d3f",
    "outline": "#879c8d",
    "primary": "#0a4c30",
    "primary-container": "#dcece0",
    "on-primary": "#ffffff",
    "success": "#065b52",
    "success-container": "#d5f2e9",
    "warning": "#854000",
    "warning-container": "#ffedc8",
    "error": "#971b12",
    "error-container": "#ffdedb",
    "data": "#445d50",
    "scrim": "#09231888"
  }
}
```

## 工程约束

- 中文调度字体栈：`"Microsoft YaHei", "PingFang SC", "Noto Sans CJK SC", "Segoe UI", sans-serif`；所有读数 `font-variant-numeric: tabular-nums`。
- 深绿表示日前主版本/主要动作，青绿表示实测，琥珀表示日内修正/警告，赤红表示超阈偏差；同时配文字、线型与图例。
- 4px 间距单位，卡片圆角 8px，按钮 6px，1px 细框。正文 14px，表格 12px，标题 22px；投屏主题增强边框与文字对比。
- 全局：桌面侧栏贯穿屏幕左侧，品牌与上下文栏分区，内容独立滚动；窄屏改为横向业务导航与可换行的筛选栏。各模块采用一致的标题、分段切换、操作栏、表格、状态和详情面板。
- 首屏：四项 KPI、功率主图、电价联动图与同口径版本对比；原始数据优先展示筛选和记录表，交易优先展示方案与结算范围，智能体突出上下文、提问与证据，审核采用列表和详情双栏。
- 加载、空数据、错误必须可见；写操作等待成功后刷新。抽屉支持 Escape、遮罩关闭、焦点回到触发按钮。
- 图表颜色从 CSS 变量读取；主题改变重绘。联动缩放共享时间轴。演示与 LLM 模式标识始终可见。

## 光伏双栏工作区

- 首页保留紧凑指标带、功率与电价联动图、下方同口径版本表；右侧常驻时段详情、来源摘要和智能体提问。
- 桌面侧栏宽 184px，右侧详情宽 304px；窄屏依次呈现分析区与详情，筛选器可换行。
- Image 2 概念稿只确定布局与视觉；曲线、时段和模型结果始终从 API 读取，不从生成图片转录。
- 接入状态从后端统计，明确区分推理适配器、真实输入和训练调度；禁止以演示状态代替生产验收。
