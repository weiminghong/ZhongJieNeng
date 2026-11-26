import { useCallback } from "react";
import type { EChartsOption } from "echarts";
import Chart, { baseOption, color } from "./Chart";
import type { Theme } from "./types";

type Hour = { hour: number; forecast_mwh?: number | null; bid_mwh?: number | null; actual_mwh?: number | null; expected_value?: number | null; value?: number | null };
export default function BusinessSeriesChart({ hours, mode, theme = "standard-light" }: { hours: Hour[]; mode: "quantity" | "money"; theme?: Theme }) {
  const option = useCallback((): EChartsOption => {
    const b = baseOption();
    const fields = mode === "quantity"
      ? [["forecast_mwh", "预测电量", "primary"], ["bid_mwh", "方案申报电量", "warning"], ["actual_mwh", "实际电量", "success"]]
      : [["expected_value", "保存的预计净额", "primary"], ["value", "实际净额", "success"]];
    return { ...b, xAxis: { type: "category", data: hours.map(h => `${String(h.hour).padStart(2, "0")}:00`) },
      yAxis: { ...b.yAxis, name: mode === "quantity" ? "MWh" : "元" },
      dataZoom: [{ type: "inside" }, { type: "slider", bottom: 4, height: 16 }],
      series: fields.filter(([key]) => hours.some(h => h[key as keyof Hour] != null)).map(([key, name, token]) => ({
        name, type: "line" as const, showSymbol: true, symbolSize: 4, connectNulls: false,
        data: hours.map(h => h[key as keyof Hour] ?? null), lineStyle: { color: color(token) }, itemStyle: { color: color(token) },
      })) };
  }, [hours, mode]);
  return <Chart option={option} theme={theme} label={mode === "quantity" ? "逐小时预测、申报与实际电量" : "同一方案预计与实际净额"} />;
}
