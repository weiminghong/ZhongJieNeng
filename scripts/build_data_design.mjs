/** 生成 18 张底层表 ER 图与预测取数映射。修改表定义后运行 node scripts/build_data_design.mjs。 */
import fs from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const output = path.join(root, 'design');
const tables = [];
function table(name, title, pk, fields, references = [], fact = false) {
  tables.push({ name, title, pk, fields: fields.split(' '), references, fact });
}
table('data_source', '数据来源', 'source_id', 'source_name source_type provider_name data_scope default_timezone expected_update_interval access_method owner_contact enabled created_at');
table('ingestion_batch', '采集批次', 'batch_id', 'source_id dataset_name requested_start requested_end started_at finished_at status record_count raw_file_uri file_hash parser_version error_summary', [['source_id', 'data_source']]);
table('station', '场站', 'station_id', 'station_code station_name station_type province_code latitude longitude altitude_m timezone commissioned_at status created_at');
table('station_config_version', '场站配置版本', 'config_version_id', 'station_id effective_from effective_to capacity_dc_mwp capacity_ac_mw connection_limit_mw tilt_deg azimuth_deg tracking_type module_temp_coeff_per_c array_layout_ref source_id published_at first_seen_at available_at revision_no', [['station_id', 'station'], ['source_id', 'data_source']]);
table('market_location', '市场位置', 'market_location_id', 'location_code location_name location_type market_code parent_location_id timezone effective_from effective_to', [['parent_location_id', 'market_location']]);
table('station_market_binding', '场站市场关系', 'binding_id', 'station_id market_location_id binding_role effective_from effective_to mapping_basis confirmed_status recorded_at available_at', [['station_id', 'station'], ['market_location_id', 'market_location']]);
table('weather_location', '气象点位', 'weather_location_id', 'source_id location_code location_name location_type latitude longitude altitude_m sensor_or_grid_ref measurement_plane timezone status', [['source_id', 'data_source']]);
table('station_weather_binding', '场站气象关系', 'binding_id', 'station_id weather_location_id binding_role distance_km selection_method effective_from effective_to confirmed_status recorded_at available_at', [['station_id', 'station'], ['weather_location_id', 'weather_location']]);
table('station_actual', '场站实际出力', 'actual_id', 'station_id measurement_point_code measurement_boundary interval_start interval_end sampling_method power_mw generated_energy_mwh export_energy_mwh available_capacity_mw', [['station_id', 'station']], true);
table('station_forecast_snapshot', '历史功率预测快照', 'forecast_snapshot_id', 'station_id measurement_boundary forecast_type issued_at target_start target_end forecast_power_mw forecast_energy_mwh provider_model_name provider_model_version scenario_code', [['station_id', 'station']], true);
table('weather_observation', '气象实测', 'observation_id', 'weather_location_id interval_start interval_end sampling_method ghi_wm2 dni_wm2 dhi_wm2 poa_wm2 air_temperature_c module_temperature_c relative_humidity_pct wind_speed_ms wind_direction_deg pressure_hpa cloud_cover_pct precipitation_mm calibration_version', [['weather_location_id', 'weather_location']], true);
table('weather_forecast', '气象预报', 'weather_forecast_id', 'weather_location_id forecast_product issued_at target_start target_end forecast_method ghi_wm2 dni_wm2 dhi_wm2 poa_wm2 air_temperature_c relative_humidity_pct wind_speed_ms wind_direction_deg cloud_cover_pct low_cloud_pct mid_cloud_pct high_cloud_pct precipitation_mm', [['weather_location_id', 'weather_location']], true);
table('station_operation_event', '场站运行事件', 'event_revision_id', 'station_id event_code equipment_code event_type event_status effective_start effective_end affected_capacity_mw power_limit_mw limit_semantics reason_code description', [['station_id', 'station']], true);
table('market_supply_actual', '实际供需', 'supply_actual_id', 'market_location_id interval_start interval_end system_load_mw solar_generation_mw wind_generation_mw conventional_generation_mw import_power_mw export_power_mw pumped_storage_power_mw storage_power_mw aggregation_scope', [['market_location_id', 'market_location']], true);
table('market_supply_forecast', '供需预测与计划', 'supply_forecast_id', 'market_location_id product_type issued_at target_start target_end load_forecast_mw solar_forecast_mw wind_forecast_mw import_plan_mw export_plan_mw conventional_available_capacity_mw maintenance_capacity_mw pumped_storage_plan_mw storage_plan_mw aggregation_scope', [['market_location_id', 'market_location']], true);
table('market_price', '市场价格', 'price_id', 'market_location_id interval_start interval_end market_stage price_type price_component price_yuan_mwh currency is_final', [['market_location_id', 'market_location']], true);
table('market_operation_event', '市场运行事件（选建）', 'event_revision_id', 'market_location_id event_code asset_code event_type effective_start effective_end affected_capacity_mw constraint_value constraint_unit event_status description', [['market_location_id', 'market_location']], true);
table('weather_image', '气象图像（选建）', 'image_id', 'weather_location_id image_type captured_at object_uri file_hash image_width image_height calibration_version', [['weather_location_id', 'weather_location']], true);

const common = 'source_id batch_id source_record_id published_at first_seen_at available_at availability_basis source_version revision_no quality_flag raw_record_ref created_at'.split(' ');
for (const entry of tables.filter(t => t.fact)) {
  entry.fields.push(...common);
  entry.references.push(['source_id', 'data_source'], ['batch_id', 'ingestion_batch']);
}

const positions = {
  data_source: [80, 150], ingestion_batch: [660, 150],
  station: [1240, 150], market_location: [2400, 150], weather_location: [3560, 150],
  station_config_version: [80, 880], station_actual: [660, 880], station_forecast_snapshot: [1240, 880],
  station_operation_event: [1820, 880], station_market_binding: [2400, 880], station_weather_binding: [3560, 880],
  market_supply_actual: [80, 1680], market_supply_forecast: [660, 1680], market_price: [1240, 1680],
  market_operation_event: [1820, 1680], weather_observation: [2400, 1680], weather_forecast: [2980, 1680], weather_image: [3560, 1680],
};
const width = 500;
function escape(value) {
  return String(value).replaceAll('&', '&amp;').replaceAll('<', '&lt;').replaceAll('>', '&gt;').replaceAll('"', '&quot;');
}
function vertex(id, value, x, y, w, h, style, parent = 'business') {
  return `<mxCell id="${id}" value="${escape(value)}" style="${style}" vertex="1" parent="${parent}"><mxGeometry x="${x}" y="${y}" width="${w}" height="${h}" as="geometry"/></mxCell>`;
}
const normalText = 'text;html=1;whiteSpace=wrap;align=left;verticalAlign=top;fillColor=none;strokeColor=none;fontFamily=Times New Roman;fontSize=20;';
const cells = [
  '<mxCell id="0"/>',
  '<mxCell id="business" value="业务实体与外键（实线）" parent="0"/>',
  '<mxCell id="lineage" value="来源与采集血缘（虚线，按需显示）" visible="0" parent="0"/>',
  vertex('heading', '<b style="font-size:38px">预测底层数据模型 · 18 张表</b><br>PK 主键　FK 外键　父表 1 对子表 0..N；每条事实记录对应一个来源与采集批次。', 80, 24, 3950, 100, normalText),
];

const heightByName = {};
for (const entry of tables) {
  const [x, y] = positions[entry.name];
  const height = 88 + entry.fields.length * 22 + 30;
  heightByName[entry.name] = height;
  const isOptional = entry.title.includes('选建');
  const primary = `PK　${entry.pk}`;
  const attributes = entry.fields.map(field => {
    const reference = entry.references.find(([key]) => key === field);
    return reference ? `<span style="color:#006D77"><b>FK　${field} → ${reference[1]}</b></span>` : `　　${field}`;
  });
  const value = `<b style="font-size:24px">${entry.title}</b><br><span style="font-size:20px">${entry.name}</span><br><br><b style="color:#0B674E">${primary}</b><br>${attributes.join('<br>')}`;
  cells.push(vertex(entry.name, value, x, y, width, height,
    `rounded=0;whiteSpace=wrap;html=1;align=left;verticalAlign=top;spacing=16;fillColor=${isOptional ? '#FFF8E9' : '#FFFFFF'};strokeColor=${isOptional ? '#BB7B27' : '#8EA8BC'};strokeWidth=1.5;fontFamily=Times New Roman;fontSize=17;`));
}

let number = 0;
for (const child of tables) {
  for (const [field, parent] of child.references) {
    const isLineage = parent === 'data_source' || parent === 'ingestion_batch';
    const layer = isLineage ? 'lineage' : 'business';
    const [px, py] = positions[parent];
    const [cx, cy] = positions[child.name];
    const sourceX = px + width / 2;
    const targetX = cx + width / 2;
    const corridor = cy - 42 - (number % 4) * 16;
    const lane = px + width + 30;
    const parentBottom = py + heightByName[parent] + 26;
    const points = parent === child.name
      ? `<mxPoint x="${px + width + 30}" y="${py + 60}"/><mxPoint x="${px + width + 30}" y="${py - 35}"/>`
      : `<mxPoint x="${sourceX}" y="${parentBottom}"/><mxPoint x="${lane}" y="${parentBottom}"/><mxPoint x="${lane}" y="${corridor}"/><mxPoint x="${targetX}" y="${corridor}"/>`;
    const label = parent === child.name ? '父位置 0..1 / 子位置 0..N' : `1 → 0..N · ${field}`;
    cells.push(`<mxCell id="relation-${number++}" value="${escape(label)}" style="edgeStyle=orthogonalEdgeStyle;rounded=0;html=1;startArrow=ERone;endArrow=ERmany;startFill=0;endFill=0;strokeWidth=${isLineage ? '1' : '1.8'};strokeColor=${isLineage ? '#B0BCC7' : '#54768D'};dashed=${isLineage ? '1' : '0'};fontSize=14;fontFamily=Times New Roman;labelBackgroundColor=#FFFFFF;exitX=${parent === child.name ? '1' : '0.5'};exitY=${parent === child.name ? '0.15' : '1'};entryX=0.5;entryY=0;" edge="1" parent="${layer}" source="${parent}" target="${child.name}"><mxGeometry relative="1" as="geometry"><Array as="points">${points}</Array></mxGeometry></mxCell>`);
  }
}
cells.push(vertex('reading', '<b>阅读方式</b><br>实体内标出全部 PK、FK 和属性。默认显示业务外键连线。来源与批次的公共外键位于独立血缘图层，可在 draw.io 图层面板开启。<br><br><b>版本与时间</b><br>有效时间回答“对应哪个业务时段”；available_at 回答“预测当时能否使用”。修订采用追加版本保存。<br><br><b>需冻结的口径</b><br>计量边界、市场位置、统计范围、采样方式、版本及可用时间依据。增强表按实际数据接入。', 2980, 150, 500, 530, normalText));

const xml = `<?xml version="1.0" encoding="UTF-8"?>\n<mxfile host="app.diagrams.net" type="device"><diagram id="prediction-data-er" name="18 张底层表 ER 图"><mxGraphModel dx="4180" dy="2920" grid="1" gridSize="10" page="1" pageWidth="4180" pageHeight="2920"><root>${cells.join('')}</root></mxGraphModel></diagram></mxfile>\n`;

const mapping = `# 预测任务与底层表字段映射

本设计为逻辑需求模型，尚未执行建库。16 张核心表及 2 张选建增强表覆盖预测底层输入与标签。真实源字段及权限尚待核验。ER 图为同目录“18张预测底层表ER图.drawio”。

## 公共取数约束

- 所有输入必须在预测截止时点已可获得，即 available_at ≤ 本次预测截止时间。无法证明可用时间的历史记录需标记 availability_basis，不能默认满足正式回测条件。
- 未来目标时段的预报或计划可作为输入；未来实测用于事后标签。发布时间、起报时间、目标时间与实际到达时间分别保留。
- 配置及关系按目标时段的 effective_from / effective_to 匹配，且该版本在预测时点已可见。第 4、6、8 张表补充 available_at，修复仅按生效期关联造成的信息泄漏风险。
- 仅采用已确认的场站—市场、场站—气象关系。多个点位保留原始记录，按明确选择或融合方法生成模型特征。
- 实发、历史预测及标签必须匹配 measurement_boundary；市场数据必须匹配 market_location_id、aggregation_scope、market_stage、price_type 和 price_component。
- 各序列保留原始间隔。整点预测、瞬时功率、区间平均功率、累计电量不直接混用。小时数据不能通过插值冒充真实的 15 分钟标签。
- source_version、revision_no 和 available_at 共同用于选择当时可见版本；采集到的后续修订不会覆盖此前版本。
- 空值与零值区分；缺失处理、单位换算与聚合保留处理记录。

## 日前光伏功率预测

| 用途 | 表 | 使用字段 | 时间与口径 |
| --- | --- | --- | --- |
| 场站定义 | station | station_id, latitude, longitude, altitude_m, timezone | 使用对应场站 |
| 物理配置 | station_config_version | capacity_dc_mwp, capacity_ac_mw, connection_limit_mw, tilt_deg, azimuth_deg, tracking_type, module_temp_coeff_per_c | 目标时段生效且预测时已知 |
| 气象选点 | station_weather_binding + weather_location | weather_location_id, binding_role, selection_method, measurement_plane | 按预报角色选点，避免把不同测量平面混用 |
| 目标日气象预报 | weather_forecast | issued_at, target_start, target_end, forecast_product, forecast_method, ghi_wm2, dni_wm2, dhi_wm2, poa_wm2, air_temperature_c, relative_humidity_pct, wind_speed_ms, wind_direction_deg, cloud_cover_pct, precipitation_mm | 取预测时已获得的版本。只提供部分辐射分量时保留缺失状态 |
| 历史出力 | station_actual | power_mw, generated_energy_mwh, export_energy_mwh, available_capacity_mw, interval_start, interval_end, sampling_method, measurement_boundary | 仅历史已到达记录 |
| 运行计划与异常 | station_operation_event | event_type, event_status, effective_start, effective_end, affected_capacity_mw, power_limit_mw, limit_semantics | 已知计划可作输入；历史受限事件用于样本标记 |
| 外部基准 | station_forecast_snapshot | forecast_type, issued_at, target_start, target_end, forecast_power_mw, provider_model_version | 候选输入或评价基准，角色在实验前固定 |
| 训练和评价标签 | station_actual | power_mw；计量点、边界与时段 | 标签按目标区间匹配。是否预测站内或并网出力待确认 |

衍生特征包括太阳位置、时间周期、历史出力滞后、物理晴空基线及可用容量比例。衍生电量需要区间平均功率与时长，不能直接使用瞬时功率替代。

## 日内光伏功率修正

| 用途 | 表 | 使用字段 | 时间与口径 |
| --- | --- | --- | --- |
| 此前预测 | station_forecast_snapshot | forecast_type, issued_at, target_start, target_end, forecast_power_mw, provider_model_version | 固定日前基线快照；本系统自有输出另接输出层 |
| 最新实发 | station_actual | power_mw, available_capacity_mw, interval_start, interval_end, first_seen_at, available_at | 只使用滚动截止前已到达数据 |
| 当前实测天气 | weather_observation | ghi_wm2, dni_wm2, dhi_wm2, poa_wm2, air_temperature_c, module_temperature_c, wind_speed_ms, relative_humidity_pct, cloud_cover_pct | 实测时段与实际到达时间同时受约束 |
| 最新短临预报 | weather_forecast | forecast_method, forecast_product, issued_at, target_start, target_end, 各气象字段 | 短临与更新数值预报按产品区分 |
| 当前运行变化 | station_operation_event | event_type, event_status, effective_start, effective_end, affected_capacity_mw, power_limit_mw | 已知故障、降额、恢复与限电约束 |
| 配置和选点 | station_config_version + station_weather_binding + weather_location | 与日前功率任务相同的配置与映射字段 | 使用当时已知版本 |
| 可选云图 | weather_image | captured_at, available_at, image_type, object_uri, quality_flag | 先经可追溯的特征提取；图像特征输出不混入原始表 |
| 训练和评价标签 | station_actual + 固定日前预测快照 | actual.power_mw − baseline.forecast_power_mw | 实发在事后形成残差标签；计量边界及目标区间一致 |

衍生特征包括最近已发生的实发减对应历史预测、功率爬坡、天气修订量及当前容量约束。预测的残差加回基线后生成更新功率。时距和刷新频率待确认。

## 日前电价预测

| 用途 | 表 | 使用字段 | 时间与口径 |
| --- | --- | --- | --- |
| 市场归属 | station_market_binding + market_location | binding_role, market_location_id, location_type, parent_location_id, market_code | 价格位置、负荷区域和风光区域可不同，按关系角色关联 |
| 已公布历史价格 | market_price | price_yuan_mwh, market_stage, price_type, price_component, interval_start, interval_end | 仅截止前已公布、可取得的价格 |
| 目标日供需预报 | market_supply_forecast | load_forecast_mw, solar_forecast_mw, wind_forecast_mw, import_plan_mw, export_plan_mw, conventional_available_capacity_mw, maintenance_capacity_mw, issued_at, product_type, aggregation_scope | 同一目标区间，使用申报／预测截止前可见版本 |
| 历史实际供需 | market_supply_actual | system_load_mw, solar_generation_mw, wind_generation_mw, conventional_generation_mw, import_power_mw, export_power_mw | 历史滞后与误差规律，无法使用目标日未来实际值 |
| 可选补充供给 | market_supply_forecast / actual | pumped_storage_plan_mw, storage_plan_mw / pumped_storage_power_mw, storage_power_mw | 按数据可得性使用，固定充放电与净出力正负方向 |
| 可选运行边界 | market_operation_event | asset_code, event_type, effective_start, effective_end, affected_capacity_mw, constraint_value, constraint_unit, event_status | 仅当时已公布的事件 |
| 训练和评价标签 | market_price | price_yuan_mwh，market_stage=日前，确认的 price_type / price_component | 目标日实际日前价格，使用确定的最终评价版本 |

衍生特征包括净负荷、供需紧张程度、价格滞后与波动、工作日与节假日。单站光伏预测不自动替代区域光伏预测，聚合边界需核验。

## 日内实时电价与价差预测

| 用途 | 表 | 使用字段 | 时间与口径 |
| --- | --- | --- | --- |
| 已知日前基线 | market_price | price_yuan_mwh, market_stage=日前, published_at, available_at, 位置与区间字段 | 目标日日前价已经公布，且滚动时可见 |
| 新旧供需预测 | market_supply_forecast | issued_at, target_start, target_end, load_forecast_mw, solar_forecast_mw, wind_forecast_mw, import_plan_mw, export_plan_mw | 对同一目标时段比较已可见的新旧版本 |
| 最近实际供需 | market_supply_actual | 实际负荷、区域风光、常规出力、受入送出和可选储能字段 | 当前已到达的历史时段 |
| 最近实时价格 | market_price | price_yuan_mwh, market_stage=实时, published_at, available_at | 使用已公布实时价，不采用目标时段未来实时价 |
| 可选事件 | market_operation_event | event_type, effective_start, effective_end, constraint_value, affected_capacity_mw | 已知运行扰动 |
| 市场映射 | station_market_binding + market_location | market_location_id, binding_role, 生效区间 | 同位置价格配对，系统供需按对应区域读取 |
| 训练和评价标签 | market_price 的日前、实时两组记录 | Δ = P_RT − P_DA | 匹配相同位置、价格类型、分项、区间。不能盲目拼接不同时间粒度 |

衍生特征包括供需预报修订量、已发生的新能源和负荷偏差、近期实时价差。更新实时价格为已知日前价加预测价差。若既有代码使用预测日前价作基线，必须单独标记该执行口径。

## 日前申报前价差方向判断

| 用途 | 表 | 使用字段 | 时间与口径 |
| --- | --- | --- | --- |
| 申报前历史价格 | market_price | 日前与实时 price_yuan_mwh、位置、区间、published_at、available_at | 仅截止前已可见的历史价格 |
| 目标日供需预期 | market_supply_forecast | 目标日负荷、区域光伏、风电、外来电、机组可用容量与检修字段；issued_at | 必须冻结在申报前实际截止时点 |
| 历史供需与偏差 | market_supply_actual + 对应历史预测版本 | 负荷、区域风光、外来电及相应预测字段 | 由已发生样本学习误差规律 |
| 已知运行边界 | market_operation_event（可选） | 事件类型、有效期、公布时间、容量和约束字段 | 当时可见的公告或事件 |
| 市场归属 | station_market_binding + market_location | 位置、角色和生效区间 | 先确认场站适用价差口径 |
| 可选模型组合 | 后续预测输出层 | 同一截止时点的日前价格预测、申报前实时价格预测及版本 | 非原始数据。不能直接使用日内价差预测代替此任务 |
| 训练和评价标签 | market_price | sign(P_RT − P_DA)，可选差值幅度 | 两种目标日实际价格在事后用于标签；零差阈值待确认 |

本场景在申报前无法取得目标日实际日前出清价。是否纳入首期、预测截止时间、方向定义与零差阈值需确认。

## 原始表、衍生特征和本系统产物的边界

1. station_forecast_snapshot 用于保存接收的历史功率预测快照。现有系统、外部模型的已发布结果是可追溯上游产物。
2. 本系统 model_version、prediction_run、prediction_value 属于后续输出层。日内调用本系统日前结果及新旧模型比较需连接该层，本图的 18 张原始表不覆盖其实现。
3. 太阳位置、净负荷、价差、修订量、滞后和窗口特征在可重现的特征流程中生成，记录源记录 ID、截止时点、窗口、单位及算法版本。
4. 结构化价格限值、规则参数和节假日日历需有经业务确认的版本来源。它们属于规则／日历支撑，本图未将未经核验的规则数值硬编码进原始事实。
5. 18 张表是预测范围的底层逻辑模型，不覆盖合同、申报、结算、Agent 日志、RSI 反馈等完整业务系统存储。

## 主键、外键和唯一约束

- 每表使用图内明确的单列主键；事实及版本记录追加保存。
- 图内所有 FK 均具有对应父表，主键侧 1 对子记录 0..N。market_location.parent_location_id 可空，自关联为父位置 0..1 对子位置 0..N。
- 所有外键在适用时要求非空。气象变量和可选供需属性按源数据可空，不填假零值。
- 数据来源与批次除独立 FK 外，建议以 ingestion_batch 的 UNIQUE(batch_id, source_id) 配合事实表的复合外键，保证批次与来源匹配。
- station.station_code 唯一。weather_location 的 (source_id, location_code) 唯一。市场位置的编码应在 market_code、location_type 的范围内确定唯一性。
- 事实防重复键至少包括来源、对象、业务区间、数据类型和修订号。预报额外包括 issued_at、产品与情景；价格额外包括 market_stage、price_type 和 price_component。
- 配置及场站映射记录的有效期和修订语义需校验，避免出现同一角色的含糊归属。多气象点是允许的，必须指定融合或选择方式。

## 当前设计状态

已确定：18 张表的逻辑职责、主外键目标、各预测任务的取数角色和时间边界。

待确认：甲方真实字段、功率计量边界、价格位置与类型、源数据版本标识、发布时间与可用时间证据、粒度和统计范围。字段存在于逻辑模型不表示甲方已交付该数据。
`;

await fs.mkdir(output, { recursive: true });
await fs.writeFile(path.join(output, '18张预测底层表ER图.drawio'), xml);
const schemaIndex = [
  '\n## ER 图实体索引\n',
  '| 表 | 主键 | 外键 |',
  '| --- | --- | --- |',
  ...tables.map(entry => `| ${entry.title} \\(${entry.name}\\) | ${entry.pk} | ${entry.references.map(([field, parent]) => `${field} → ${parent}`).join('<br>') || '无'} |`),
  '\n实体内包含全部属性。业务图层默认可见，来源与批次血缘图层默认隐藏，可在 draw.io 图层面板开启。图中的 1 对 0..N 表示基数，字段是否可空仍按业务语义约束。\n',
].join('\n');
await fs.writeFile(path.join(output, '预测任务与底层数据映射.md'), mapping + schemaIndex);
const names = new Set(tables.map(t => t.name));
for (const entry of tables) {
  if (new Set(entry.fields).size !== entry.fields.length) throw new Error(`字段重复 ${entry.name}`);
  for (const [field, parent] of entry.references) {
    if (!names.has(parent) || !entry.fields.includes(field)) throw new Error(`无效外键 ${entry.name}.${field}`);
  }
}
console.log(`Generated ${tables.length} tables, ${number} FK relationships, 5 prediction task mappings.`);
