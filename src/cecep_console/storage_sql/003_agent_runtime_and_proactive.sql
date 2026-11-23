CREATE TABLE agent_proactive_brief (
 brief_id TEXT PRIMARY KEY,
 station_id TEXT NOT NULL REFERENCES station(station_id),
 trading_date TEXT NOT NULL, cutoff_at TEXT NOT NULL,
 source_mode TEXT NOT NULL CHECK(source_mode IN ('synthetic','production')),
 trigger_type TEXT NOT NULL,
 severity TEXT NOT NULL CHECK(severity IN ('info','warning','critical')),
 headline TEXT NOT NULL, summary_markdown TEXT NOT NULL,
 signals_json TEXT NOT NULL CHECK(json_valid(signals_json)),
 model_inference_json TEXT CHECK(model_inference_json IS NULL OR json_valid(model_inference_json)),
 recommended_action_json TEXT NOT NULL CHECK(json_valid(recommended_action_json)),
 citations_json TEXT NOT NULL CHECK(json_valid(citations_json)), created_at TEXT NOT NULL
);
CREATE INDEX idx_proactive_scope ON agent_proactive_brief(station_id,trading_date,source_mode,created_at);
CREATE TRIGGER immutable_agent_proactive_brief_update BEFORE UPDATE ON agent_proactive_brief BEGIN SELECT RAISE(ABORT,'append-only: agent_proactive_brief'); END;
CREATE TRIGGER immutable_agent_proactive_brief_delete BEFORE DELETE ON agent_proactive_brief BEGIN SELECT RAISE(ABORT,'append-only: agent_proactive_brief'); END;
