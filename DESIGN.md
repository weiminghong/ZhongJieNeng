# 中节能光储交易工作台设计系统

面向调度员、交易分析师和模型审核人。蓝白雾灰的浅色工程工作台，采用紧凑表格、连续时间轴与证据下钻。五个模块共享全局场站、日期、模式、异常时段和 Agent 上下文。禁止教学业务与装饰性营销页面。

## 颜色唯一事实源

以下 JSON 是可执行 Token 合同。`scripts/generate_design_tokens.mjs` 从此生成 CSS，不手改生成物。

```json design-tokens
{
  "standard-light": {
    "background": "#eef2f7", "surface": "#ffffff", "surface-container": "#f7f9fc",
    "on-surface": "#172033", "on-surface-variant": "#52627a", "outline": "#d7dfeb",
    "primary": "#1e5eff", "primary-container": "#e8efff", "on-primary": "#ffffff",
    "success": "#0f766e", "success-container": "#d9f6f1",
    "warning": "#b45309", "warning-container": "#fff4de",
    "error": "#b42318", "error-container": "#fee4e2", "data": "#657991", "scrim": "#17203366"
  },
  "high-contrast-light": {
    "background": "#e5eaf1", "surface": "#ffffff", "surface-container": "#f1f4f8",
    "on-surface": "#080f1c", "on-surface-variant": "#344054", "outline": "#8996a8",
    "primary": "#1043c7", "primary-container": "#e1e9ff", "on-primary": "#ffffff",
    "success": "#065b52", "success-container": "#d5f2e9",
    "warning": "#854000", "warning-container": "#ffedc8",
    "error": "#971b12", "error-container": "#ffdedb", "data": "#44556c", "scrim": "#080f1c88"
  }
}
```

## 工程约束

- 中文调度字体栈：`"Microsoft YaHei", "PingFang SC", "Noto Sans CJK SC", "Segoe UI", sans-serif`；所有读数 `font-variant-numeric: tabular-nums`。
- 主蓝表示日前主版本/主要动作，青绿表示实测，琥珀表示日内修正/警告，赤红表示超阈偏差；同时配文字、线型与图例。
- 4px 间距单位，卡片圆角 8px，按钮 6px，1px 细框。正文 14px，表格 12px，标题 22px；投屏主题增强边框与文字对比。
- 首屏：固定上下文栏、左侧模块导航、四项 KPI、功率主图、电价联动图与同口径版本对比。桌面最大化使用有效宽度；窄屏导航横滚、卡片重排、表格内部滚动。
- 加载、空数据、错误必须可见；写操作等待成功后刷新。抽屉支持 Escape、遮罩关闭、焦点回到触发按钮。
- 图表颜色从 CSS 变量读取；主题改变重绘。联动缩放共享时间轴。演示与 LLM 模式标识始终可见。
