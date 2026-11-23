export type Mode = "live" | "post" | "replay";
export type SourceMode = "synthetic" | "production";
export type Theme = "standard-light" | "high-contrast-light";
export interface Scope {
  station_id: string;
  date: string;
  mode: Mode;
  source_mode: SourceMode;
  cutoff_at?: string;
  selected_interval?: string;
}
export interface Station {
  station_id: string;
  station_name: string;
  capacity_ac_mw: number;
}
export interface Model {
  model_version_id: string;
  model_name: string;
  version: string;
  task: string;
  effective_status: string;
  source_mode: string;
  trained: boolean;
}
export interface Bootstrap {
  stations: Station[];
  dates: string[];
  default_date: string;
  data_clock: string;
  source_modes: SourceMode[];
  models: Model[];
  llm_mode: string;
  evidently: { report_url: string; status: string; notice: string };
}
export interface Interval {
  station_id: string;
  interval_start: string;
  interval_end: string;
  actual_mw: number | null;
  physical_clear_sky_mw: number | null;
  da_forecast_mw: number | null;
  compare_forecast_mw: number | null;
  id_corrected_mw: number | null;
  lower_mw: number | null;
  upper_mw: number | null;
  da_price: number | null;
  da_pred_price: number | null;
  rt_price: number | null;
  rt_pred_price: number | null;
  spread_yuan_mwh: number | null;
  ghi_wm2: number | null;
  air_temp_c: number | null;
  cloud_cover_pct: number | null;
  active_event_flag: number;
  quality_flag: string;
  lineage_refs_json: string;
}
export interface Kpi {
  energy_actual_mwh: number | null;
  energy_forecast_matched_mwh: number | null;
  power_mae_mw: number | null;
  power_rmse_mw: number | null;
  avg_spread: number | null;
  observed_count: number;
  due_count: number;
  missing_count: number;
  estimated_net_revenue_yuan: number | null;
  estimated_penalty_yuan: number | null;
}
export interface Overview {
  intervals: Interval[];
  kpi: Kpi | null;
  query_path: string;
  cutoff_at: string;
  source_mode: SourceMode;
  drift?: {
    summary_json: string;
    drifted_feature_count: number;
    total_feature_count: number;
    report_uri: string;
  }[];
}
export interface Version {
  run_id: string;
  model_version_id: string;
  model_name: string;
  version: string;
  cutoff_at: string;
  mae: number | null;
  rmse: number | null;
  sample_count: number;
  comparison_basis: string;
  values: { interval_start: string; value: number }[];
}
export interface Comparison {
  versions: Version[];
  query_path: string;
  intraday: {
    comparison_basis: string;
    day_ahead: { mae: number | null; sample_count: number };
    corrected: { mae: number | null; sample_count: number };
  };
}
export interface Plan {
  plan_id: string;
  plan_name: string;
  net_revenue_yuan: number | null;
  settled_count: number;
  unsettled_count: number;
  components: Record<string, number>;
  items: { interval_start: string; bid_power_mw: number }[];
  rule: {
    description: string;
    exempt_fraction: number;
    penalty_yuan_mwh: number;
  };
  warning: string;
  scope: string;
}
export interface Trading {
  plans: Plan[];
  engine: string;
}
export interface ToolCall {
  tool_name: string;
  input: unknown;
  output: unknown;
}
export interface Citation {
  citation_id: string;
  kind: string;
  tool_name?: string;
  title?: string;
  chunk_id?: string;
}
export interface AgentAnswer {
  response_id: string;
  session_id: string;
  agent_run_id: string;
  question?: string;
  answer_markdown: string;
  citations: Citation[];
  tool_calls: ToolCall[];
  llm_mode: string;
  grounded_check_passed: boolean;
  latency_ms: number;
}
export interface Feedback {
  feedback_id: string;
  reason: string;
  training_eligible: number;
}
export interface Case {
  case_id: string;
  station_id: string;
  interval_start: string;
  actual_value: number;
  predicted_value: number;
  error_value: number;
  severity: string;
  auto_clues_json: string;
  effective_status: string;
  feedback: Feedback | null;
  rag_doc_id: string | null;
}
export interface Candidate {
  candidate_id: string;
  base_model_version_id: string;
  candidate_model_version_id: string;
  hypothesis: string;
  evaluation_id: string | null;
}
export interface Rsi {
  cases: Case[];
  models: Model[];
  candidates: Candidate[];
  lifecycle: {
    lifecycle_event_id: string;
    model_version_id: string;
    from_status: string;
    to_status: string;
    reason: string;
    created_at: string;
  }[];
}
export interface Lineage {
  cutoff_at: string;
  evidence: {
    reference: { table: string; record_id: string; available_at: string };
    record: Record<string, unknown> | null;
    available_before_cutoff: boolean;
    feature_inputs?: unknown[];
  }[];
}
