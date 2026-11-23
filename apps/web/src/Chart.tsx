import { useEffect, useRef } from "react";
import * as echarts from "echarts/core";
import {
  LineChart,
  BarChart,
  ScatterChart,
  HeatmapChart,
  CustomChart,
} from "echarts/charts";
import {
  TooltipComponent,
  GridComponent,
  LegendComponent,
  DataZoomComponent,
  MarkLineComponent,
  MarkAreaComponent,
  VisualMapComponent,
} from "echarts/components";
import { CanvasRenderer } from "echarts/renderers";
import type { EChartsOption } from "echarts";
import type { Theme } from "./types";
echarts.use([
  LineChart,
  BarChart,
  ScatterChart,
  HeatmapChart,
  CustomChart,
  TooltipComponent,
  GridComponent,
  LegendComponent,
  DataZoomComponent,
  MarkLineComponent,
  MarkAreaComponent,
  VisualMapComponent,
  CanvasRenderer,
]);
export function color(name: string) {
  return getComputedStyle(document.documentElement)
    .getPropertyValue(`--ce-color-${name}`)
    .trim();
}
export function baseOption(): EChartsOption {
  return {
    animation: false,
    textStyle: {
      color: color("on-surface-variant"),
      fontFamily: "Microsoft YaHei, sans-serif",
      fontSize: 11,
    },
    tooltip: {
      trigger: "axis",
      confine: true,
      backgroundColor: color("surface"),
      borderColor: color("outline"),
      textStyle: { color: color("on-surface") },
    },
    grid: { left: 56, right: 30, top: 50, bottom: 60 },
    legend: {
      top: 4,
      type: "scroll",
      textStyle: { color: color("on-surface-variant"), fontSize: 11 },
    },
    xAxis: {
      type: "category",
      boundaryGap: false,
      axisLine: { lineStyle: { color: color("outline") } },
      axisTick: { show: false },
      axisLabel: { color: color("on-surface-variant") },
    },
    yAxis: {
      type: "value",
      splitLine: { lineStyle: { color: color("outline"), type: "dashed" } },
    },
  };
}
export default function Chart({
  option,
  theme,
  group,
  onPoint,
  compact = false,
  label,
}: {
  option: () => EChartsOption;
  theme: Theme;
  group?: string;
  onPoint?: (index: number) => void;
  compact?: boolean;
  label: string;
}) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const chart = echarts.init(ref.current!);
    chart.setOption(option());
    if (group) {
      chart.group = group;
      echarts.connect(group);
    }
    if (onPoint)
      chart.on("click", (p) => {
        if (typeof p.dataIndex === "number") onPoint(p.dataIndex);
      });
    const observer = new ResizeObserver(() => chart.resize());
    observer.observe(ref.current!);
    return () => {
      observer.disconnect();
      chart.dispose();
    };
  }, [option, theme, group, onPoint]);
  return (
    <div
      role="img"
      aria-label={label}
      ref={ref}
      className={compact ? "chart compact-chart" : "chart"}
    />
  );
}
