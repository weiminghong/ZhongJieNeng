/* 中文显示层。只替换页面文字与辅助标签，保留 Evidently 的原始数据和计算。 */
(function () {
  "use strict";

  const messages = {
    "Report": "评估报告",
    "Dataset Summary": "数据集概况",
    "Dataset Drift": "数据集分布变化",
    "Dataset Drift is detected. Dataset drift detection threshold is 0.5": "已检出数据集分布变化，触发条件为至少 50% 的监测字段发生变化",
    "Data Drift Summary": "各因素分布变化汇总",
    "Data Drift": "分布变化",
    "DATA DRIFT": "分布变化",
    "DATA DISTRIBUTION": "数据分布",
    "Column": "字段",
    "Columns": "字段总数",
    "Type": "类型",
    "Reference Distribution": "参考期分布",
    "Current Distribution": "当前期分布",
    "Drifted Columns": "发生变化的字段数",
    "Share of Drifted Columns": "发生变化的字段比例",
    "Drift Score": "检验统计量（本报告为 p 值）",
    "Stat Test": "统计检验方法",
    "Detected": "已检出变化",
    "Not Detected": "未检出显著变化",
    "K-S p_value": "双样本 K-S 检验 p 值",
    "chi-square p_value": "卡方检验 p 值",
    "Search": "搜索字段",
    "Clear Search": "清空搜索",
    "Rows per page:": "每页行数：",
    "Rows per page": "每页行数",
    "First Page": "首页",
    "Previous Page": "上一页",
    "Next Page": "下一页",
    "Last Page": "末页",
    "Detail panel visibility toggle": "展开或收起字段详情",
    "Sort": "排序",
    "Sort ascending": "升序",
    "Sort descending": "降序",
    "Close": "关闭",
    "Expand": "展开",
    "Collapse": "收起",
    "Download plot as a PNG": "下载图表为 PNG 图片",
    "Download plot as a png": "下载图表为 PNG 图片",
    "Zoom": "框选缩放",
    "Pan": "平移",
    "Box Select": "框选数据",
    "Lasso Select": "套索选择",
    "Zoom in": "放大",
    "Zoom out": "缩小",
    "Autoscale": "自动缩放",
    "Reset axes": "重置坐标轴",
    "Toggle Spike Lines": "切换辅助线",
    "Show closest data on hover": "悬停显示最近数据",
    "Compare data on hover": "悬停对比数据",
    "Double-click to zoom back out": "双击恢复缩放",
    "Metrics": "评价指标",
    "Tests": "检验结果",
    "Metric": "指标",
    "Value": "数值",
    "Count": "数量",
    "Percent": "百分比",
    "Mean": "均值",
    "Std": "标准差",
    "None": "无",
    "Actual": "实际值",
    "Predicted": "预测值",
    "Predicted - Actual": "预测值减实际值",
    "Predicted vs Actual in Time": "预测与实际的时间走势",
    "Error": "预测误差",
    "Error Distribution": "预测误差分布",
    "Error (Predicted - Actual)": "预测误差（预测值减实际值，MWh）",
    "Absolute Percentage Error": "绝对百分比误差",
    "Current": "当前期",
    "Reference": "参考期",
    "current": "当前期",
    "reference": "参考期",
    "Current: Model Quality (+/- std)": "当前期预测表现（均值及标准差）",
    "Reference: Model Quality (+/- std)": "参考期预测表现（均值及标准差）",
    "current (mean)": "当前期均值",
    "reference (mean)": "参考期均值",
    "reference (+/- 1std)": "参考期均值上下一个标准差",
    "Mean Absolute Percentage Error: Current": "当前期平均绝对百分比误差",
    "Mean Absolute Percentage Error: Reference": "参考期平均绝对百分比误差",
    "Absolute Max Error (current)": "当前期最大绝对误差（MWh）",
    "Absolute Max Error (reference)": "参考期最大绝对误差（MWh）",
    "R2 Score (current)": "当前期决定系数（R²）",
    "R2 Score (reference)": "参考期决定系数（R²）",
    "MAE": "平均绝对误差（MAE，MWh）",
    "RMSE": "均方根误差（RMSE，MWh）",
    "MAPE": "平均绝对百分比误差（MAPE，%）",
    "ME": "平均误差（ME，MWh）",
    "Number Of Objects": "样本数",
    "number of rows": "样本行数",
    "number of columns": "字段数量",
    "missing values": "缺失值",
    "missing": "缺失",
    "empty columns": "全空字段",
    "constant columns": "常量字段",
    "duplicated columns": "重复字段",
    "almost constant features": "近似常量因素",
    "almost duplicated features": "高度重复因素",
    "numeric columns": "数值字段",
    "categorical columns": "类别字段",
    "datetime columns": "日期时间字段",
    "text columns": "文本字段",
    "target column": "实际目标字段",
    "prediction column": "预测结果字段",
    "date column": "日期字段",
    "id column": "标识字段",
    "num": "数值",
    "cat": "类别",
    "min": "最小值",
    "max": "最大值",
    "mean": "均值",
    "std": "标准差",
    "count": "数量",
    "abs": "绝对误差",
    "perc": "百分比误差",
    "Sunny": "晴天",
    "Cloudy": "多云",
    "Rainy": "雨天",
    "date": "日期",
    "date (day)": "日期（天）",
    "ghi_kwh_m2": "日累计辐照量（kWh/m²）",
    "temperature_c": "气温（℃）",
    "cloud_cover_pct": "云量（%）",
    "wind_speed_ms": "风速（m/s）",
    "availability_pct": "设备可用率（%）",
    "weather_type": "天气类型",
    "actual_energy_mwh": "实际日发电量（MWh）",
    "forecast_energy_mwh": "预测日发电量（MWh）",
  };

  function translate(value) {
    const trimmed = value.trim();
    let translated = messages[trimmed];
    if (!translated) {
      translated = trimmed
        .replace(/^Drift is detected for ([\d.]+)% of columns \((\d+) out of (\d+)\)\.$/, "有 $1% 的字段检出分布变化（$3 个中有 $2 个）")
        .replace(/^Dataset Drift is not detected\..*$/, "未达到数据集分布变化的触发条件")
        .replace(/^Regression Model Performance\. Target: ['’](.+)['’]$/, (_, target) => `预测模型表现，实际目标为${messages[target] || target}`)
        .replace(/\b(\d+) rows\b/g, "$1 行")
        .replace(/^(\d+)-(\d+) of (\d+)$/, "第 $1—$2 条，共 $3 条")
        .replace(/^(\d+)–(\d+) of (\d+)$/, "第 $1—$2 条，共 $3 条");
      for (const field of ["ghi_kwh_m2", "temperature_c", "cloud_cover_pct", "wind_speed_ms", "availability_pct", "weather_type", "actual_energy_mwh", "forecast_energy_mwh"]) {
        translated = translated.replaceAll(field, messages[field]);
      }
      translated = translated.replaceAll("(mean +/- std)", "（均值上下一个标准差）");
    }
    return translated === trimmed ? value : value.replace(trimmed, translated);
  }

  function localize(root) {
    const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
    let node;
    while ((node = walker.nextNode())) {
      if (["SCRIPT", "STYLE", "NOSCRIPT"].includes(node.parentElement?.tagName)) continue;
      const text = translate(node.nodeValue);
      if (text !== node.nodeValue) node.nodeValue = text;
    }
    for (const element of root.querySelectorAll("[title],[aria-label],[placeholder]")) {
      for (const attribute of ["title", "aria-label", "placeholder"]) {
        const value = element.getAttribute(attribute);
        if (value !== null) {
          const text = translate(value);
          if (text !== value) element.setAttribute(attribute, text);
        }
      }
    }
  }

  document.documentElement.lang = "zh-CN";
  let scheduled = false;
  const observer = new MutationObserver(() => {
    if (scheduled) return;
    scheduled = true;
    requestAnimationFrame(() => {
      observer.disconnect();
      localize(document.body);
      scheduled = false;
      watch();
    });
  });
  function watch() {
    observer.observe(document.body, { childList: true, subtree: true, characterData: true, attributes: true, attributeFilter: ["title", "aria-label", "placeholder"] });
  }
  localize(document.body);
  watch();
})();
