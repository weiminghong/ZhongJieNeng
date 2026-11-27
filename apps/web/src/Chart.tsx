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
    color: [
      color("primary"),
      color("success"),
      color("warning"),
      color("data"),
      color("error"),
    ],
    textStyle: {
      color: color("on-surface-variant"),
      fontFamily: "Microsoft YaHei, sans-serif",
      fontSize: 11,
    },
    tooltip: {
      trigger: "axis",
      confine: true,
      axisPointer: { type: "line", lineStyle: { color: color("primary") } },
      backgroundColor: color("surface"),
      borderColor: color("outline"),
      textStyle: { color: color("on-surface") },
      valueFormatter: (value) => typeof value === "number"
        ? value.toLocaleString("zh-CN", { maximumFractionDigits: 3 })
        : value == null ? "—" : String(value),
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
  linked = false,
  onPoint,
  compact = false,
  label,
}: {
  option: () => EChartsOption;
  theme: Theme;
  group?: string;
  linked?: boolean;
  onPoint?: (index: number) => void;
  compact?: boolean;
  label: string;
}) {
  const ref = useRef<HTMLDivElement>(null);
  const instance = useRef<ReturnType<typeof echarts.init> | null>(null);
  const selectPoint = useRef(onPoint);
  selectPoint.current = onPoint;
  const latestOption = useRef(option);
  latestOption.current = option;
  useEffect(() => {
    const chart = echarts.init(ref.current!);
    instance.current = chart;
    chart.setOption(latestOption.current());
    if (group && linked) {
      chart.group = group;
      echarts.connect(group);
    }
    chart.getZr().on("click", (event) => {
        if (!selectPoint.current) return;
        const point = [event.offsetX, event.offsetY];
        if (chart.containPixel("grid", point)) {
          const coordinates = chart.convertFromPixel({ gridIndex: 0 }, point);
          const index = Math.round(coordinates[0]);
          if (Number.isFinite(index) && index >= 0) selectPoint.current(index);
        }
      });
    const observer = new ResizeObserver(() => chart.resize());
    observer.observe(ref.current!);
    return () => {
      observer.disconnect();
      if (group && linked) echarts.disconnect(group);
      chart.dispose();
      instance.current = null;
    };
  }, [theme, group, linked]);
  useEffect(() => {
    instance.current?.setOption(option(), { replaceMerge: ["series"] });
  }, [option, theme, group, linked]);
  return (
    <div
      role="img"
      aria-label={label}
      data-chart-interaction={linked ? "linked" : "independent"}
      ref={ref}
      className={compact ? "chart compact-chart" : "chart"}
    />
  );
}
