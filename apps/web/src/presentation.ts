export const taskLabel = (value: string) =>
  ({
    day_ahead_power: "日前功率预测",
    intraday_power: "日内功率修正",
    day_ahead_price: "日前电价预测",
    prebid_spread: "申报前价差",
    intraday_spread: "日内价差",
    rt_price_day_ahead_reference: "实时电价预测",
  })[value] || "预测研究";
export const stateLabel = (value?: string) =>
  ({
    production: "使用中",
    rolled_back: "已回滚",
    started: "任务已开始",
    claimed: "准备中",
    child_complete: "结果已保存，等待确认",
    cancel_requested: "正在取消",
    registered: "已登记",
    consumed: "已完成评估",
    candidate: "待审核",
    archived: "已归档",
    retired: "已停用",
    research_active: "研究主版本",
    evaluated: "已评估",
    shadow: "观察中",
    rejected: "未通过",
    confirmed: "已确认",
    submitted: "待确认",
    completed: "已完成",
    succeeded: "已完成",
    failed: "未完成",
    cancelled: "已取消",
    queued: "排队中",
    training: "训练中",
    preparing: "准备数据",
    evaluating: "评估中",
    unknown_exit: "完成情况待核验",
    interrupted: "已中断",
    ready: "可用",
    valid: "有效",
    missing: "缺测",
    pending: "待到达",
    provider_failed: "摘要服务暂不可用",
    matched: "已核对",
    frozen: "已固定",
  })[value || ""] || "待核验";
export const sourceLabel = (value?: string) =>
  value === "synthetic"
    ? "合成演示"
    : value === "public_reference"
      ? "公开历史数据"
      : value === "production"
        ? "生产输入"
        : "待核验来源";
export const analysisLabel = (value?: string) =>
  value === "deterministic_tools_only" ? "规则工具分析" : "摘要辅助分析";
export const stationLabel = (value: string) =>
  ({ lanneng: "岚能场站", lingguang: "凌光场站" })[value] || "所选场站";
export const adapterLabel = (value: string) =>
  ({
    builtin_pit_ridge: "历史功率拟合",
    local_joblib: "已登记预测模型",
    local_torchscript: "已登记预测模型",
    local_onnx: "已登记预测模型",
    http: "外部预测服务",
  })[value] || "已登记预测服务";
export const fieldLabel = (value: string) =>
  ({
    power_mw: "实测功率（MW）",
    generated_energy_mwh: "发电量（MWh）",
    export_energy_mwh: "上网电量（MWh）",
    available_capacity_mw: "可用容量（MW）",
    forecast_power_mw: "预测功率（MW）",
    forecast_energy_mwh: "预测电量（MWh）",
    price_yuan_mwh: "电价（元/MWh）",
    target_start: "目标时段开始",
    target_end: "目标时段结束",
    air_temperature_c: "气温（℃）",
    module_temperature_c: "组件温度（℃）",
    station_actual: "场站实测",
    station_forecast_snapshot: "场站预测",
    weather_observation: "气象实测",
    weather_forecast: "天气预报",
    market_price: "市场电价",
    prediction_run: "已保存预测",
    feature_snapshot: "预测输入",
    station_operation_event: "场站事件",
    market_operation_event: "市场事件",
    interval_start: "时段开始",
    interval_end: "时段结束",
    actual_mw: "实测功率",
    predicted_mw: "预测功率",
    da_forecast_mw: "日前预测功率",
    id_corrected_mw: "日内修正功率",
    da_price: "日前电价",
    rt_price: "实时电价",
    spread_yuan_mwh: "实时与日前价差",
    ghi_wm2: "总辐照度",
    cloud_cover_pct: "云量",
    air_temp_c: "气温",
    quality_flag: "数据状态",
    capacity_mw: "装机容量",
    available_at: "本系统可用时间",
    forecast_issued_at: "预报发布时间",
    issued_at: "发布时间",
    wind_speed_ms: "风速",
    pressure_hpa: "气压",
    relative_humidity_pct: "相对湿度",
    humidity_pct: "湿度",
    value: "数值",
    unit: "单位",
    task: "预测任务",
    status: "状态",
  })[value] || "业务记录";
export const toolLabel = (value?: string) =>
  ({
    data_overview: "数据概况",
    forecast_metrics: "预测表现",
    trading_revenue: "收益测算",
    deviation_review: "偏差复核",
    knowledge_search: "知识检索",
    registered_numpy_price_inference: "电价模型预测",
    run_model_inference: "模型预测",
    compare_revenue: "收益对比",
    deviation_top: "重点偏差",
  })[value || ""] || "业务计算";

/** Display only. The stored evidence and machine identifiers remain unchanged. */
export function businessText(value: unknown): string {
  let text = String(value ?? "");
  text = text
    .replace(/intraday-corr-demo/g, "日内修正参考模型")
    .replace(/lgbm-demo/g, "光伏功率参考模型")
    .replace(/demo-scenario/g, "演示参考模型")
    .replace(/(\d+(?:\.\d+)?)-cand\b/g, "$1候选");
  if (/constraint failed|FOREIGN KEY|sqlite|ml_\w+registry/i.test(text))
    return "记录关联校验未通过，请刷新后重试。问题仍存在时请联系维护人员。";
  text = text.replace(
    /(?:权重\s*)?SHA-?256\s*[:：]?\s*[a-f0-9]{64}/gi,
    "数据版本已校验",
  );
  text = text.replace(
    /\b(model|dataset|prediction|job|feedback|proposal|observation|analysis|audit|source)_[a-f0-9]{12,64}\b/gi,
    (_, kind: string) =>
      ({
        model: "所选模型",
        dataset: "所选数据",
        prediction: "本次预测",
        job: "训练任务",
        feedback: "复核记录",
        proposal: "重训提案",
        observation: "观测记录",
        analysis: "分析记录",
        audit: "审核记录",
        source: "数据版本",
      })[kind.toLowerCase()] || "业务记录",
  );
  text = text
    .replace(
      /\b[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}\b/gi,
      "已保存记录",
    )
    .replace(/\b[a-f0-9]{32,64}\b/gi, "已校验版本");
  const words: Record<string, string> = {
    pit_synthetic_demo: "合成历史拟合，未经生产验证",
    pit_production: "使用查询时点可见的历史数据",
    physical_only_no_pit_pairs: "物理参考结果，暂无有效历史配对",
    external_artifact_unverified_training: "外部模型的训练过程尚未核验",
    historical_assumed: "历史研究口径",
    deterministic_tools_only: "规则工具分析",
    openai_compatible_evidence_summary: "摘要辅助分析",
    synthetic: "合成演示",
    production: "生产输入",
    public_reference: "公开历史数据",
    PIT: "指定时点",
    RSI: "人工复核",
    serving: "页面数据",
    NumPy: "",
    Ridge: "线性模型",
    SQL: "",
    JSON: "",
    SHA256: "版本校验",
    SHA: "版本校验",
    CNY: "元",
    cutoff: "查询截止时点",
  };
  text = text.replace(
    /\b[a-zA-Z][a-zA-Z0-9_]*\b/g,
    (word) => words[word] ?? (word.includes("_") ? fieldLabel(word) : word),
  );
  return text;
}

export function recordLabel(
  record?: { display_name?: string; created_at?: string } | null,
  fallback = "研究记录",
) {
  return record?.display_name || fallback;
}
