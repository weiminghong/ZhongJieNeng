-- Incremental upper layers; original L1 tables and immutable triggers stay intact.
CREATE TABLE training_dataset_version (
 dataset_version_id TEXT PRIMARY KEY, task TEXT NOT NULL, station_id TEXT NOT NULL REFERENCES station(station_id),
 train_start TEXT, train_end TEXT, val_start TEXT, val_end TEXT, test_start TEXT, test_end TEXT,
 cutoff_policy_json TEXT NOT NULL CHECK(json_valid(cutoff_policy_json)), feature_spec_version TEXT NOT NULL,
 excluded_feedback_ids_json TEXT NOT NULL CHECK(json_valid(excluded_feedback_ids_json)), parquet_uri TEXT NOT NULL,
 content_hash TEXT NOT NULL, row_count INTEGER NOT NULL CHECK(row_count>=0), source_mode TEXT NOT NULL CHECK(source_mode IN ('synthetic','production')), created_at TEXT NOT NULL
);
CREATE TABLE drift_check_run (
 drift_run_id TEXT PRIMARY KEY, station_id TEXT NOT NULL REFERENCES station(station_id), task TEXT NOT NULL,
 reference_start TEXT, reference_end TEXT, current_start TEXT, current_end TEXT,
 drifted_feature_count INTEGER NOT NULL, total_feature_count INTEGER NOT NULL, summary_json TEXT NOT NULL CHECK(json_valid(summary_json)),
 report_uri TEXT, triggered_rsi INTEGER NOT NULL CHECK(triggered_rsi IN (0,1)), source_mode TEXT NOT NULL CHECK(source_mode IN ('synthetic','production')), created_at TEXT NOT NULL
);
CREATE TABLE model_lifecycle_event (
 lifecycle_event_id TEXT PRIMARY KEY, model_version_id TEXT NOT NULL REFERENCES model_version(model_version_id),
 from_status TEXT NOT NULL, to_status TEXT NOT NULL CHECK(to_status IN ('candidate','shadow','production','archived','rolled_back')),
 decision_id TEXT NOT NULL REFERENCES approval_decision(decision_id), operator_id TEXT NOT NULL, reason TEXT NOT NULL, created_at TEXT NOT NULL
);
CREATE TABLE contract_position (
 contract_id TEXT PRIMARY KEY, station_id TEXT NOT NULL REFERENCES station(station_id), market_location_id TEXT NOT NULL REFERENCES market_location(market_location_id),
 contract_type TEXT NOT NULL, interval_start TEXT NOT NULL, interval_end TEXT NOT NULL, contract_energy_mwh REAL NOT NULL CHECK(contract_energy_mwh>=0),
 contract_price_yuan_mwh REAL NOT NULL, effective_from TEXT NOT NULL, effective_to TEXT, available_at TEXT NOT NULL,
 source_id TEXT NOT NULL REFERENCES data_source(source_id), revision_no INTEGER NOT NULL, source_mode TEXT NOT NULL CHECK(source_mode IN ('synthetic','production'))
);
CREATE TABLE bidding_plan (
 plan_id TEXT PRIMARY KEY, station_id TEXT NOT NULL REFERENCES station(station_id), market_location_id TEXT NOT NULL REFERENCES market_location(market_location_id),
 trading_date TEXT NOT NULL, plan_name TEXT NOT NULL, power_run_id TEXT NOT NULL REFERENCES prediction_run(run_id), price_run_id TEXT REFERENCES prediction_run(run_id),
 rule_version_id TEXT NOT NULL REFERENCES rule_version(rule_version_id), status TEXT NOT NULL, created_by TEXT NOT NULL, source_mode TEXT NOT NULL CHECK(source_mode IN ('synthetic','production')), created_at TEXT NOT NULL
);
CREATE TABLE bidding_plan_item (
 plan_item_id TEXT PRIMARY KEY, plan_id TEXT NOT NULL REFERENCES bidding_plan(plan_id), interval_start TEXT NOT NULL, interval_end TEXT NOT NULL,
 bid_power_mw REAL NOT NULL CHECK(bid_power_mw>=0), bid_energy_mwh REAL NOT NULL CHECK(bid_energy_mwh>=0), bid_price_yuan_mwh REAL,
 strategy_tag TEXT NOT NULL, rationale_json TEXT NOT NULL CHECK(json_valid(rationale_json)), UNIQUE(plan_id,interval_start)
);
CREATE TABLE rag_document (
 doc_id TEXT PRIMARY KEY, collection TEXT NOT NULL CHECK(collection IN ('market_rule','domain_manual','dispatch_notice','rsi_case')),
 title TEXT NOT NULL, market_code TEXT, station_id TEXT REFERENCES station(station_id), effective_from TEXT NOT NULL, effective_to TEXT,
 source_uri TEXT NOT NULL, content_hash TEXT NOT NULL, version TEXT NOT NULL, status TEXT NOT NULL, source_mode TEXT NOT NULL CHECK(source_mode IN ('synthetic','production')), created_at TEXT NOT NULL
);
CREATE TABLE rag_chunk (
 chunk_id TEXT PRIMARY KEY, doc_id TEXT NOT NULL REFERENCES rag_document(doc_id), chunk_index INTEGER NOT NULL,
 heading_path TEXT NOT NULL, content_text TEXT NOT NULL, metadata_json TEXT NOT NULL CHECK(json_valid(metadata_json)), token_count INTEGER NOT NULL,
 embedding_model TEXT, created_at TEXT NOT NULL, UNIQUE(doc_id,chunk_index)
);
CREATE VIRTUAL TABLE rag_chunk_fts USING fts5(chunk_id UNINDEXED, content_text, heading_path, tokenize='unicode61');
CREATE TRIGGER rag_chunk_insert AFTER INSERT ON rag_chunk BEGIN
 INSERT INTO rag_chunk_fts(chunk_id,content_text,heading_path) VALUES(new.chunk_id,new.content_text,new.heading_path);
END;
CREATE TRIGGER rag_chunk_update AFTER UPDATE ON rag_chunk BEGIN
 DELETE FROM rag_chunk_fts WHERE chunk_id=old.chunk_id;
 INSERT INTO rag_chunk_fts(chunk_id,content_text,heading_path) VALUES(new.chunk_id,new.content_text,new.heading_path);
END;
CREATE TRIGGER rag_chunk_delete AFTER DELETE ON rag_chunk BEGIN
 DELETE FROM rag_chunk_fts WHERE chunk_id=old.chunk_id;
END;
CREATE TABLE agent_session (
 session_id TEXT PRIMARY KEY, user_id TEXT NOT NULL, scope_json TEXT NOT NULL CHECK(json_valid(scope_json)), created_at TEXT NOT NULL
);
CREATE TABLE agent_response (
 response_id TEXT PRIMARY KEY, agent_run_id TEXT NOT NULL REFERENCES agent_run(agent_run_id), session_id TEXT NOT NULL REFERENCES agent_session(session_id),
 answer_markdown TEXT NOT NULL, citations_json TEXT NOT NULL CHECK(json_valid(citations_json)), grounded_check_passed INTEGER NOT NULL CHECK(grounded_check_passed IN (0,1)),
 llm_mode TEXT NOT NULL, latency_ms REAL NOT NULL, created_at TEXT NOT NULL
);
CREATE TABLE deviation_case (
 case_id TEXT PRIMARY KEY, station_id TEXT NOT NULL REFERENCES station(station_id), prediction_run_id TEXT NOT NULL REFERENCES prediction_run(run_id),
 interval_start TEXT NOT NULL, interval_end TEXT NOT NULL, actual_value REAL NOT NULL, predicted_value REAL NOT NULL, error_value REAL NOT NULL,
 severity TEXT NOT NULL, auto_clues_json TEXT NOT NULL CHECK(json_valid(auto_clues_json)), status TEXT NOT NULL,
 source_mode TEXT NOT NULL CHECK(source_mode IN ('synthetic','production')), created_at TEXT NOT NULL
);
CREATE TABLE serving_interval_wide (
 station_id TEXT NOT NULL REFERENCES station(station_id), interval_start TEXT NOT NULL, source_mode TEXT NOT NULL,
 trading_date TEXT NOT NULL, interval_end TEXT NOT NULL, actual_mw REAL, physical_clear_sky_mw REAL, da_forecast_mw REAL,
 compare_forecast_mw REAL, id_corrected_mw REAL, lower_mw REAL, upper_mw REAL, da_pred_price REAL, da_price REAL, rt_pred_price REAL, rt_price REAL,
 spread_yuan_mwh REAL, ghi_wm2 REAL, air_temp_c REAL, cloud_cover_pct REAL, active_event_flag INTEGER NOT NULL, quality_flag TEXT NOT NULL,
 lineage_refs_json TEXT NOT NULL CHECK(json_valid(lineage_refs_json)), refreshed_at TEXT NOT NULL, PRIMARY KEY(station_id,interval_start,source_mode)
);
CREATE INDEX serving_interval_day ON serving_interval_wide(station_id,trading_date,source_mode);
CREATE TABLE serving_daily_kpi (
 station_id TEXT NOT NULL REFERENCES station(station_id), trading_date TEXT NOT NULL, scope TEXT NOT NULL, source_mode TEXT NOT NULL,
 energy_actual_mwh REAL, energy_forecast_matched_mwh REAL, power_mae_mw REAL, power_rmse_mw REAL, price_mae REAL,
 avg_spread REAL, max_abs_spread REAL, observed_count INTEGER NOT NULL, due_count INTEGER NOT NULL, missing_count INTEGER NOT NULL,
 worst_interval_json TEXT NOT NULL, estimated_net_revenue_yuan REAL, estimated_penalty_yuan REAL, refreshed_at TEXT NOT NULL,
 PRIMARY KEY(station_id,trading_date,scope,source_mode)
);
CREATE TABLE serving_version_compare (
 compare_key TEXT PRIMARY KEY, task TEXT NOT NULL, station_id TEXT NOT NULL REFERENCES station(station_id), date_start TEXT NOT NULL, date_end TEXT NOT NULL,
 run_a_id TEXT NOT NULL REFERENCES prediction_run(run_id), run_b_id TEXT NOT NULL REFERENCES prediction_run(run_id), scope TEXT NOT NULL,
 matched_sample_count INTEGER NOT NULL, metrics_a_json TEXT NOT NULL, metrics_b_json TEXT NOT NULL, delta_json TEXT NOT NULL,
 top_diff_intervals_json TEXT NOT NULL, source_mode TEXT NOT NULL, refreshed_at TEXT NOT NULL
);
CREATE INDEX lifecycle_model ON model_lifecycle_event(model_version_id,created_at);
CREATE INDEX deviation_scope ON deviation_case(station_id,interval_start);
CREATE INDEX agent_response_session ON agent_response(session_id,created_at);
CREATE TRIGGER training_dataset_version_immutable_update BEFORE UPDATE ON training_dataset_version BEGIN SELECT RAISE(ABORT, 'append-only: training_dataset_version'); END;
CREATE TRIGGER training_dataset_version_immutable_delete BEFORE DELETE ON training_dataset_version BEGIN SELECT RAISE(ABORT, 'append-only: training_dataset_version'); END;
CREATE TRIGGER drift_check_run_immutable_update BEFORE UPDATE ON drift_check_run BEGIN SELECT RAISE(ABORT, 'append-only: drift_check_run'); END;
CREATE TRIGGER drift_check_run_immutable_delete BEFORE DELETE ON drift_check_run BEGIN SELECT RAISE(ABORT, 'append-only: drift_check_run'); END;
CREATE TRIGGER model_lifecycle_event_immutable_update BEFORE UPDATE ON model_lifecycle_event BEGIN SELECT RAISE(ABORT, 'append-only: model_lifecycle_event'); END;
CREATE TRIGGER model_lifecycle_event_immutable_delete BEFORE DELETE ON model_lifecycle_event BEGIN SELECT RAISE(ABORT, 'append-only: model_lifecycle_event'); END;
CREATE TRIGGER contract_position_immutable_update BEFORE UPDATE ON contract_position BEGIN SELECT RAISE(ABORT, 'append-only: contract_position'); END;
CREATE TRIGGER contract_position_immutable_delete BEFORE DELETE ON contract_position BEGIN SELECT RAISE(ABORT, 'append-only: contract_position'); END;
CREATE TRIGGER bidding_plan_immutable_update BEFORE UPDATE ON bidding_plan BEGIN SELECT RAISE(ABORT, 'append-only: bidding_plan'); END;
CREATE TRIGGER bidding_plan_immutable_delete BEFORE DELETE ON bidding_plan BEGIN SELECT RAISE(ABORT, 'append-only: bidding_plan'); END;
CREATE TRIGGER bidding_plan_item_immutable_update BEFORE UPDATE ON bidding_plan_item BEGIN SELECT RAISE(ABORT, 'append-only: bidding_plan_item'); END;
CREATE TRIGGER bidding_plan_item_immutable_delete BEFORE DELETE ON bidding_plan_item BEGIN SELECT RAISE(ABORT, 'append-only: bidding_plan_item'); END;
CREATE TRIGGER rag_document_immutable_update BEFORE UPDATE ON rag_document BEGIN SELECT RAISE(ABORT, 'append-only: rag_document'); END;
CREATE TRIGGER rag_document_immutable_delete BEFORE DELETE ON rag_document BEGIN SELECT RAISE(ABORT, 'append-only: rag_document'); END;
CREATE TRIGGER rag_chunk_immutable_update BEFORE UPDATE ON rag_chunk BEGIN SELECT RAISE(ABORT, 'append-only: rag_chunk'); END;
CREATE TRIGGER rag_chunk_immutable_delete BEFORE DELETE ON rag_chunk BEGIN SELECT RAISE(ABORT, 'append-only: rag_chunk'); END;
CREATE TRIGGER agent_session_immutable_update BEFORE UPDATE ON agent_session BEGIN SELECT RAISE(ABORT, 'append-only: agent_session'); END;
CREATE TRIGGER agent_session_immutable_delete BEFORE DELETE ON agent_session BEGIN SELECT RAISE(ABORT, 'append-only: agent_session'); END;
CREATE TRIGGER agent_response_immutable_update BEFORE UPDATE ON agent_response BEGIN SELECT RAISE(ABORT, 'append-only: agent_response'); END;
CREATE TRIGGER agent_response_immutable_delete BEFORE DELETE ON agent_response BEGIN SELECT RAISE(ABORT, 'append-only: agent_response'); END;
CREATE TRIGGER deviation_case_immutable_update BEFORE UPDATE ON deviation_case BEGIN SELECT RAISE(ABORT, 'append-only: deviation_case'); END;
CREATE TRIGGER deviation_case_immutable_delete BEFORE DELETE ON deviation_case BEGIN SELECT RAISE(ABORT, 'append-only: deviation_case'); END;
