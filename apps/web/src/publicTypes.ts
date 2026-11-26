export interface PublicMetadata {
  display_name?:string;
  dataset_id: string;
  name: string;
  source_url: string;
  source_file: string;
  source_hash: string;
  row_count: number;
  day_count: number;
  date_start: string;
  date_end: string;
  interval_minutes: number;
  source_kind: string;
  region: string;
  basis: string;
  update_policy: string;
  source_columns: string[];
  fields: { key: string; source_column: string; unit: string }[];
}
export interface PublicCatalog {
  available: boolean;
  metadata: PublicMetadata | null;
  dates: string[];
  default_date?: string;
  checked_at: string;
  notice?: string;
}
export interface PublicPoint {
  slot: number;
  source_line: number | null;
  interval_start: string;
  interval_end: string;
  visible: boolean;
  quality: string;
  pv_forecast_mw: number | null;
  pv_actual_mw: number | null;
  load_forecast_mw: number | null;
  load_actual_mw: number | null;
  wind_forecast_mw: number | null;
  wind_actual_mw: number | null;
  da_price: number | null;
  rt_price: number | null;
  spread_yuan_mwh: number | null;
  source_values: Record<string, string> | null;
}
export interface PublicSeries {
  metadata: PublicMetadata;
  scope: {
    dataset_id: string;
    source_hash: string;
    date: string;
    cursor: number;
    replay_until: string;
  };
  scope_hash: string;
  points: PublicPoint[];
  latest: PublicPoint | null;
  summary: {
    visible_records: number;
    revealed_slots: number;
    total_day_records: number;
    pv_mae_mw: number | null;
    pv_rmse_mw: number | null;
    power_pair_count: number;
    pv_actual_mwh: number | null;
    mean_spread_yuan_mwh: number | null;
    price_pair_count: number;
    negative_price_count: number;
    missing_records: number;
    max_abs_spread: PublicPoint | null;
    worst_pv_error: PublicPoint | null;
  };
}
export interface PublicAnalysis {
  run_id: string;
  scope: PublicSeries["scope"];
  answer_markdown: string;
  llm_mode: string;
  facts: string[];
  evidence: { source_hash: string; source_lines: number[] };
  provider_error: string | null;
}
export interface PublicScenario {
  scope: PublicSeries["scope"];
  quantity_mwh: number;
  fee_yuan_mwh: number;
  paired_intervals: number;
  unsettled_intervals: number;
  total_exposure_mwh: number;
  gross_spread_yuan: number | null;
  fees_yuan: number | null;
  net_spread_yuan: number | null;
  formula: string;
  basis: string;
  saved?: { run_id: string };
}
export interface PublicRun {
  source_hash: string;
  evidence: {
    source_hash: string;
    source_records: PublicPoint[];
    source_lines: number[];
  };
  run_id: string;
  kind: "analysis" | "review" | "scenario";
  answer_text: string;
  created_at: string;
  scope: PublicSeries["scope"] & { selected_slot?: number };
  status: string;
}
export type PublicTab =
  "forecast" | "raw" | "trading" | "agent" | "rsi" | "connections";
