# 第三方组件

## PriceForecast 公开市场参考数据

- 来源 https://github.com/ronaldowzy/price_forecast
- GB10 已有副本提交 `96ddcf9b020e98be35c9b8eb1c0f8b6e1fb8dc6f`。
- MIT License，Copyright (c) 2026 ronaldowzy；原许可保留在服务器已有仓库中。
- 读取其 `data/价格预测数据集.csv`；数据公开与隐私说明见上游 `docs/data_privacy.md`。
- 数据为山东省级聚合市场参考，不能表示中节能浙江场站实测或本站模型训练效果。
- 不修改该副本或重新下载数据；仅通过主工作台自有适配层读取，在追加式记录中保留源文件哈希、行号和分析快照。

## solar-forecast

- 来源 https://github.com/tusharbeckham/solar-forecast
- 固定提交 `14ac74888b3d967b0a0ff61a5af58be1417ad217`
- MIT License，Copyright (c) 2026 Tushar
- 许可正文随子模块 `vendor/solar-forecast/LICENSE` 保留。
- 本项目调用物理计算函数，未使用该项目的代理目标作为中节能实测值。

## AI Energy Trading Platform

- 来源 https://github.com/yaoyaojiahan/ai-energy-trading-platform
- 固定提交 `4c7391606c47272dd50582640cc8e7b4f6a78209`
- 作者 Yao Jiahan，README 声明 MIT License。
- 本项目调用 `src/forecast/evaluate.py` 中的 `ModelEvaluator`，保留上游源码和作者署名。
- 仓库未提供独立 LICENSE 正文，正式对外分发前应向上游确认许可文本。

## Plotly

- 来源 https://github.com/plotly/plotly.js 与 https://github.com/plotly/plotly.py
- MIT License，运行环境中随依赖保留许可证与 JavaScript 文件中的版权说明。
- 图表资源从 Python 包本地读取并提供服务，浏览器无需连接外部 CDN。

NumPy、Pandas 及其他传递依赖遵循各自随包提供的许可证。
