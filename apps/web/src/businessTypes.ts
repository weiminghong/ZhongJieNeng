export type PlanParameters = {
  mode: "manual" | "spread_rule";
  bid_ratio: number;
  fee_yuan_mwh: number;
  min_ratio: number;
  max_ratio: number;
  spread_threshold: number;
  ratio_step: number;
  max_bid_mwh: number | null;
};
export type BusinessPrediction = { id: string; record_id: string; model_id: string; task: string; date: string; name: string; unit: string; information_budget?: string; input_source_hash?: string; cutoff_at?: string };
export type Observation = { id: string; prediction_id: string; name: string; source_name: string; checked_at: string };
export type PlanHour = { hour: number; time: string; forecast_mwh: number | null; bid_mwh: number | null; bid_ratio: number; da_forecast: number | null; rt_forecast: number | null; spread_forecast: number | null; expected_fee: number | null; expected_value: number | null; missing_reason?: string };
export type SettlementHour = { hour: number; time: string; complete: boolean; missing_reason?: string; bid_mwh: number | null; actual_mwh: number | null; da_price: number | null; rt_price: number | null; value: number | null; expected_value: number | null; variance: number | null };
export type BusinessSettlement = {
  id: string; name: string; version: number; plan_id: string; observation_id: string; observation_name: string; created_at: string;
  actual: { value: number | null; reference: number | null; delta: number | null; actual_mwh: number | null; bid_mwh: number | null; fee: number | null; settled_hours: number; excluded_hours: number };
  comparison: { expected_value: number | null; actual_value: number | null; delta: number | null; power_effect: number | null; price_effect: number | null; fee_effect: number | null; matched_hours: number; unmatched_hours: number };
  hours: SettlementHour[];
};
export type BusinessPlan = {
  id: string; name: string; version: number; parent_id?: string; source_key: string; date: string; task: string; model_id: string; record_id: string; status: string; parameters: PlanParameters; created_at: string; actor: string; reason: string;
  estimated: { forecast_mwh: number | null; bid_mwh: number | null; expected_fee: number | null; expected_value: number | null; priced_hours: number; total_hours: number; notice: string };
  risk: { available: boolean; sample_hours: number; lower_error_mwh: number | null; upper_error_mwh: number | null; mean_error_mwh: number | null; notice: string };
  hours?: PlanHour[];
  cutoff_at?: string;
  parent_name?: string;
  price_records?: { da?: { record_id: string; name: string }; rt?: { record_id: string; name: string }; spread?: { record_id: string; name: string } };
  latest_settlement?: BusinessSettlement;
};
export type BusinessCatalog = { source_key: string; date: string; context_version: string; predictions: BusinessPrediction[]; observations: Observation[]; plans: BusinessPlan[]; notice: string };
