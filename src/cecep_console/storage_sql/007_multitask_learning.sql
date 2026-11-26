-- Append-only task extensions; legacy constraints, rows and checksums remain intact.

CREATE TABLE ml_model_registry_v2 (
 model_version_id TEXT PRIMARY KEY REFERENCES ml_object(object_id),
 dataset_id TEXT NOT NULL REFERENCES ml_dataset_registry(dataset_id),
 job_id TEXT NOT NULL REFERENCES ml_job(job_id),
 algorithm TEXT NOT NULL CHECK(algorithm IN ('ridge','seasonal_naive_d2','seasonal_naive_d7','train_weekday_slot_median','recent_observation','zero_spread')),
 task TEXT NOT NULL,
 unit TEXT NOT NULL CHECK(unit IN ('CNY/MWh','MW')),
 artifact_path TEXT NOT NULL,
 artifact_sha256 TEXT NOT NULL CHECK(length(artifact_sha256)=64),
 training_end TEXT NOT NULL,
 selection_end TEXT NOT NULL,
 final_start TEXT NOT NULL,
 final_end TEXT NOT NULL,
 created_at TEXT NOT NULL
);

CREATE TABLE ml_prediction_registry_v2 (
 prediction_id TEXT PRIMARY KEY REFERENCES ml_object(object_id),
 model_version_id TEXT NOT NULL REFERENCES ml_model_registry_v2(model_version_id),
 input_source_id TEXT REFERENCES ml_source_registry(source_version_id),
 input_source_hash TEXT NOT NULL CHECK(length(input_source_hash)=64),
 trading_date TEXT NOT NULL,
 cutoff_at TEXT NOT NULL,
 unit TEXT NOT NULL CHECK(unit IN ('CNY/MWh','MW')),
 point_count INTEGER NOT NULL CHECK(point_count IN (24,96)),
 validation_only INTEGER NOT NULL CHECK(validation_only IN (0,1)),
 created_at TEXT NOT NULL
);

CREATE TABLE ml_observation_registry_v2 (
 observation_id TEXT PRIMARY KEY REFERENCES ml_object(object_id),
 prediction_id TEXT NOT NULL REFERENCES ml_prediction_registry_v2(prediction_id),
 source_version_id TEXT NOT NULL REFERENCES ml_source_registry(source_version_id),
 source_hash TEXT NOT NULL,
 observed_points INTEGER NOT NULL CHECK(observed_points BETWEEN 0 AND 96),
 changed_points INTEGER NOT NULL CHECK(changed_points BETWEEN 0 AND 96),
 checked_at TEXT NOT NULL,
 created_at TEXT NOT NULL,
 UNIQUE(prediction_id,source_version_id)
);

CREATE TABLE ml_feedback_registry_v2 (
 feedback_id TEXT PRIMARY KEY REFERENCES ml_object(object_id),
 prediction_id TEXT NOT NULL REFERENCES ml_prediction_registry_v2(prediction_id),
 observation_id TEXT REFERENCES ml_observation_registry_v2(observation_id),
 slot INTEGER NOT NULL CHECK(slot BETWEEN 0 AND 95),
 reviewer_id TEXT NOT NULL,
 training_eligible INTEGER NOT NULL CHECK(training_eligible=0),
 created_at TEXT NOT NULL
);

CREATE TABLE ml_retrain_registry_v2 (
 proposal_id TEXT PRIMARY KEY REFERENCES ml_object(object_id),
 feedback_id TEXT NOT NULL REFERENCES ml_feedback_registry_v2(feedback_id),
 dataset_id TEXT NOT NULL REFERENCES ml_dataset_registry(dataset_id),
 parent_model_id TEXT NOT NULL REFERENCES ml_model_registry_v2(model_version_id),
 alpha REAL NOT NULL CHECK(alpha IN (0.1,1,10,100)),
 incorporates_labels INTEGER NOT NULL CHECK(incorporates_labels=0),
 created_at TEXT NOT NULL
);

CREATE TABLE ml_audit_registry_v2 (
 audit_id TEXT PRIMARY KEY REFERENCES ml_object(object_id),
 model_version_id TEXT NOT NULL REFERENCES ml_model_registry_v2(model_version_id),
 task TEXT NOT NULL,
 window_start TEXT NOT NULL,
 window_end TEXT NOT NULL,
 created_at TEXT NOT NULL,
 UNIQUE(task,window_start,window_end)
);

DROP TRIGGER ml_model_registry_insert;

CREATE TRIGGER ml_model_registry_insert AFTER INSERT ON ml_object WHEN NEW.kind='model' AND json_extract(NEW.payload_json,'$.task')='rt_price_day_ahead_reference' BEGIN INSERT INTO ml_model_registry (model_version_id,dataset_id,job_id,algorithm,task,unit,artifact_path,artifact_sha256,training_end,selection_end,final_start,final_end,created_at) SELECT o.object_id,json_extract(o.payload_json,'$.dataset_id'),json_extract(o.payload_json,'$.job_id'),json_extract(o.payload_json,'$.algorithm'),json_extract(o.payload_json,'$.task'),json_extract(o.payload_json,'$.unit'),json_extract(o.payload_json,'$.weights.path'),json_extract(o.payload_json,'$.weights.sha256'),json_extract(o.payload_json,'$.training_label_end'),json_extract(o.payload_json,'$.selection_end'),json_extract(o.payload_json,'$.splits.final_audit[0]'),json_extract(o.payload_json,'$.splits.final_audit[1]'),o.created_at FROM ml_object o WHERE o.object_id=NEW.object_id; END;

CREATE TRIGGER ml_model_registry_insert_v2 AFTER INSERT ON ml_object WHEN NEW.kind='model' AND json_extract(NEW.payload_json,'$.task')<>'rt_price_day_ahead_reference' BEGIN INSERT INTO ml_model_registry_v2 (model_version_id,dataset_id,job_id,algorithm,task,unit,artifact_path,artifact_sha256,training_end,selection_end,final_start,final_end,created_at) SELECT o.object_id,json_extract(o.payload_json,'$.dataset_id'),json_extract(o.payload_json,'$.job_id'),json_extract(o.payload_json,'$.algorithm'),json_extract(o.payload_json,'$.task'),json_extract(o.payload_json,'$.unit'),json_extract(o.payload_json,'$.weights.path'),json_extract(o.payload_json,'$.weights.sha256'),json_extract(o.payload_json,'$.training_label_end'),json_extract(o.payload_json,'$.selection_end'),json_extract(o.payload_json,'$.splits.final_audit[0]'),json_extract(o.payload_json,'$.splits.final_audit[1]'),o.created_at FROM ml_object o WHERE o.object_id=NEW.object_id; END;

CREATE TRIGGER ml_model_registry_kind_v2 BEFORE INSERT ON ml_model_registry_v2 WHEN (SELECT kind FROM ml_object WHERE object_id=NEW.model_version_id) IS NOT 'model' BEGIN SELECT RAISE(ABORT,'typed object kind mismatch: ml_model_registry_v2'); END;

CREATE TRIGGER ml_model_registry_no_update_v2 BEFORE UPDATE ON ml_model_registry_v2 BEGIN SELECT RAISE(ABORT,'append-only: ml_model_registry_v2'); END;

CREATE TRIGGER ml_model_registry_no_delete_v2 BEFORE DELETE ON ml_model_registry_v2 BEGIN SELECT RAISE(ABORT,'append-only: ml_model_registry_v2'); END;

DROP TRIGGER ml_prediction_registry_insert;

CREATE TRIGGER ml_prediction_registry_insert AFTER INSERT ON ml_object WHEN NEW.kind='prediction' AND EXISTS(SELECT 1 FROM ml_model_registry WHERE model_version_id=json_extract(NEW.payload_json,'$.model_id')) BEGIN INSERT INTO ml_prediction_registry (prediction_id,model_version_id,input_source_id,input_source_hash,trading_date,cutoff_at,unit,point_count,validation_only,created_at) SELECT o.object_id,json_extract(o.payload_json,'$.model_id'),(SELECT source_version_id FROM ml_source_registry WHERE source_hash=o.source_hash),o.source_hash,json_extract(o.payload_json,'$.date'),(strftime('%Y-%m-%dT%H:%M:%S',json_extract(o.payload_json,'$.logical_cutoff'))||'.000000Z'),json_extract(o.payload_json,'$.unit'),json_array_length(o.payload_json,'$.points'),json_extract(o.payload_json,'$.validation_only'),o.created_at FROM ml_object o WHERE o.object_id=NEW.object_id; END;

CREATE TRIGGER ml_prediction_registry_insert_v2 AFTER INSERT ON ml_object WHEN NEW.kind='prediction' AND EXISTS(SELECT 1 FROM ml_model_registry_v2 WHERE model_version_id=json_extract(NEW.payload_json,'$.model_id')) BEGIN INSERT INTO ml_prediction_registry_v2 (prediction_id,model_version_id,input_source_id,input_source_hash,trading_date,cutoff_at,unit,point_count,validation_only,created_at) SELECT o.object_id,json_extract(o.payload_json,'$.model_id'),(SELECT source_version_id FROM ml_source_registry WHERE source_hash=o.source_hash),o.source_hash,json_extract(o.payload_json,'$.date'),(strftime('%Y-%m-%dT%H:%M:%S',json_extract(o.payload_json,'$.logical_cutoff'))||'.000000Z'),json_extract(o.payload_json,'$.unit'),json_array_length(o.payload_json,'$.points'),json_extract(o.payload_json,'$.validation_only'),o.created_at FROM ml_object o WHERE o.object_id=NEW.object_id; END;

CREATE TRIGGER ml_prediction_registry_kind_v2 BEFORE INSERT ON ml_prediction_registry_v2 WHEN (SELECT kind FROM ml_object WHERE object_id=NEW.prediction_id) IS NOT 'prediction' BEGIN SELECT RAISE(ABORT,'typed object kind mismatch: ml_prediction_registry_v2'); END;

CREATE TRIGGER ml_prediction_registry_no_update_v2 BEFORE UPDATE ON ml_prediction_registry_v2 BEGIN SELECT RAISE(ABORT,'append-only: ml_prediction_registry_v2'); END;

CREATE TRIGGER ml_prediction_registry_no_delete_v2 BEFORE DELETE ON ml_prediction_registry_v2 BEGIN SELECT RAISE(ABORT,'append-only: ml_prediction_registry_v2'); END;

DROP TRIGGER ml_observation_registry_insert;

CREATE TRIGGER ml_observation_registry_insert AFTER INSERT ON ml_object WHEN NEW.kind='observation_match' AND EXISTS(SELECT 1 FROM ml_model_registry WHERE model_version_id=json_extract(NEW.payload_json,'$.model_id')) BEGIN INSERT INTO ml_observation_registry (observation_id,prediction_id,source_version_id,source_hash,observed_points,changed_points,checked_at,created_at) SELECT o.object_id,json_extract(o.payload_json,'$.prediction_id'),json_extract(o.payload_json,'$.source_revision_id'),o.source_hash,json_extract(o.payload_json,'$.observed_points'),json_extract(o.payload_json,'$.changed_from_snapshot'),json_extract(o.payload_json,'$.checked_at'),o.created_at FROM ml_object o WHERE o.object_id=NEW.object_id; END;

CREATE TRIGGER ml_observation_registry_insert_v2 AFTER INSERT ON ml_object WHEN NEW.kind='observation_match' AND EXISTS(SELECT 1 FROM ml_model_registry_v2 WHERE model_version_id=json_extract(NEW.payload_json,'$.model_id')) BEGIN INSERT INTO ml_observation_registry_v2 (observation_id,prediction_id,source_version_id,source_hash,observed_points,changed_points,checked_at,created_at) SELECT o.object_id,json_extract(o.payload_json,'$.prediction_id'),json_extract(o.payload_json,'$.source_revision_id'),o.source_hash,json_extract(o.payload_json,'$.observed_points'),json_extract(o.payload_json,'$.changed_from_snapshot'),json_extract(o.payload_json,'$.checked_at'),o.created_at FROM ml_object o WHERE o.object_id=NEW.object_id; END;

CREATE TRIGGER ml_observation_registry_kind_v2 BEFORE INSERT ON ml_observation_registry_v2 WHEN (SELECT kind FROM ml_object WHERE object_id=NEW.observation_id) IS NOT 'observation_match' BEGIN SELECT RAISE(ABORT,'typed object kind mismatch: ml_observation_registry_v2'); END;

CREATE TRIGGER ml_observation_registry_no_update_v2 BEFORE UPDATE ON ml_observation_registry_v2 BEGIN SELECT RAISE(ABORT,'append-only: ml_observation_registry_v2'); END;

CREATE TRIGGER ml_observation_registry_no_delete_v2 BEFORE DELETE ON ml_observation_registry_v2 BEGIN SELECT RAISE(ABORT,'append-only: ml_observation_registry_v2'); END;

DROP TRIGGER ml_feedback_registry_insert;

CREATE TRIGGER ml_feedback_registry_insert AFTER INSERT ON ml_object WHEN NEW.kind='feedback' AND EXISTS(SELECT 1 FROM ml_model_registry WHERE model_version_id=json_extract(NEW.payload_json,'$.model_id')) BEGIN INSERT INTO ml_feedback_registry (feedback_id,prediction_id,observation_id,slot,reviewer_id,training_eligible,created_at) SELECT o.object_id,json_extract(o.payload_json,'$.prediction_id'),json_extract(o.payload_json,'$.observation_id'),json_extract(o.payload_json,'$.slot'),json_extract(o.payload_json,'$.actor'),json_extract(o.payload_json,'$.training_eligible'),o.created_at FROM ml_object o WHERE o.object_id=NEW.object_id; END;

CREATE TRIGGER ml_feedback_registry_insert_v2 AFTER INSERT ON ml_object WHEN NEW.kind='feedback' AND EXISTS(SELECT 1 FROM ml_model_registry_v2 WHERE model_version_id=json_extract(NEW.payload_json,'$.model_id')) BEGIN INSERT INTO ml_feedback_registry_v2 (feedback_id,prediction_id,observation_id,slot,reviewer_id,training_eligible,created_at) SELECT o.object_id,json_extract(o.payload_json,'$.prediction_id'),json_extract(o.payload_json,'$.observation_id'),json_extract(o.payload_json,'$.slot'),json_extract(o.payload_json,'$.actor'),json_extract(o.payload_json,'$.training_eligible'),o.created_at FROM ml_object o WHERE o.object_id=NEW.object_id; END;

CREATE TRIGGER ml_feedback_registry_kind_v2 BEFORE INSERT ON ml_feedback_registry_v2 WHEN (SELECT kind FROM ml_object WHERE object_id=NEW.feedback_id) IS NOT 'feedback' BEGIN SELECT RAISE(ABORT,'typed object kind mismatch: ml_feedback_registry_v2'); END;

CREATE TRIGGER ml_feedback_registry_no_update_v2 BEFORE UPDATE ON ml_feedback_registry_v2 BEGIN SELECT RAISE(ABORT,'append-only: ml_feedback_registry_v2'); END;

CREATE TRIGGER ml_feedback_registry_no_delete_v2 BEFORE DELETE ON ml_feedback_registry_v2 BEGIN SELECT RAISE(ABORT,'append-only: ml_feedback_registry_v2'); END;

DROP TRIGGER ml_retrain_registry_insert;

CREATE TRIGGER ml_retrain_registry_insert AFTER INSERT ON ml_object WHEN NEW.kind='proposal' AND EXISTS(SELECT 1 FROM ml_model_registry WHERE model_version_id=json_extract(NEW.payload_json,'$.model_id')) BEGIN INSERT INTO ml_retrain_registry (proposal_id,feedback_id,dataset_id,parent_model_id,alpha,incorporates_labels,created_at) SELECT o.object_id,json_extract(o.payload_json,'$.feedback_id'),json_extract(o.payload_json,'$.dataset_id'),json_extract(o.payload_json,'$.model_id'),json_extract(o.payload_json,'$.alpha'),json_extract(o.payload_json,'$.incorporates_labels'),o.created_at FROM ml_object o WHERE o.object_id=NEW.object_id; END;

CREATE TRIGGER ml_retrain_registry_insert_v2 AFTER INSERT ON ml_object WHEN NEW.kind='proposal' AND EXISTS(SELECT 1 FROM ml_model_registry_v2 WHERE model_version_id=json_extract(NEW.payload_json,'$.model_id')) BEGIN INSERT INTO ml_retrain_registry_v2 (proposal_id,feedback_id,dataset_id,parent_model_id,alpha,incorporates_labels,created_at) SELECT o.object_id,json_extract(o.payload_json,'$.feedback_id'),json_extract(o.payload_json,'$.dataset_id'),json_extract(o.payload_json,'$.model_id'),json_extract(o.payload_json,'$.alpha'),json_extract(o.payload_json,'$.incorporates_labels'),o.created_at FROM ml_object o WHERE o.object_id=NEW.object_id; END;

CREATE TRIGGER ml_retrain_registry_kind_v2 BEFORE INSERT ON ml_retrain_registry_v2 WHEN (SELECT kind FROM ml_object WHERE object_id=NEW.proposal_id) IS NOT 'proposal' BEGIN SELECT RAISE(ABORT,'typed object kind mismatch: ml_retrain_registry_v2'); END;

CREATE TRIGGER ml_retrain_registry_no_update_v2 BEFORE UPDATE ON ml_retrain_registry_v2 BEGIN SELECT RAISE(ABORT,'append-only: ml_retrain_registry_v2'); END;

CREATE TRIGGER ml_retrain_registry_no_delete_v2 BEFORE DELETE ON ml_retrain_registry_v2 BEGIN SELECT RAISE(ABORT,'append-only: ml_retrain_registry_v2'); END;

DROP TRIGGER ml_audit_registry_insert;

CREATE TRIGGER ml_audit_registry_insert AFTER INSERT ON ml_object WHEN NEW.kind='audit' AND EXISTS(SELECT 1 FROM ml_model_registry WHERE model_version_id=json_extract(NEW.payload_json,'$.model_id')) BEGIN INSERT INTO ml_audit_registry (audit_id,model_version_id,task,window_start,window_end,created_at) SELECT o.object_id,json_extract(o.payload_json,'$.model_id'),(SELECT task FROM ml_model_registry WHERE model_version_id=json_extract(o.payload_json,'$.model_id')),(SELECT final_start FROM ml_model_registry WHERE model_version_id=json_extract(o.payload_json,'$.model_id')),(SELECT final_end FROM ml_model_registry WHERE model_version_id=json_extract(o.payload_json,'$.model_id')),o.created_at FROM ml_object o WHERE o.object_id=NEW.object_id; END;

CREATE TRIGGER ml_audit_registry_insert_v2 AFTER INSERT ON ml_object WHEN NEW.kind='audit' AND EXISTS(SELECT 1 FROM ml_model_registry_v2 WHERE model_version_id=json_extract(NEW.payload_json,'$.model_id')) BEGIN INSERT INTO ml_audit_registry_v2 (audit_id,model_version_id,task,window_start,window_end,created_at) SELECT o.object_id,json_extract(o.payload_json,'$.model_id'),(SELECT task FROM ml_model_registry_v2 WHERE model_version_id=json_extract(o.payload_json,'$.model_id')),(SELECT final_start FROM ml_model_registry_v2 WHERE model_version_id=json_extract(o.payload_json,'$.model_id')),(SELECT final_end FROM ml_model_registry_v2 WHERE model_version_id=json_extract(o.payload_json,'$.model_id')),o.created_at FROM ml_object o WHERE o.object_id=NEW.object_id; END;

CREATE TRIGGER ml_audit_registry_kind_v2 BEFORE INSERT ON ml_audit_registry_v2 WHEN (SELECT kind FROM ml_object WHERE object_id=NEW.audit_id) IS NOT 'audit' BEGIN SELECT RAISE(ABORT,'typed object kind mismatch: ml_audit_registry_v2'); END;

CREATE TRIGGER ml_audit_registry_no_update_v2 BEFORE UPDATE ON ml_audit_registry_v2 BEGIN SELECT RAISE(ABORT,'append-only: ml_audit_registry_v2'); END;

CREATE TRIGGER ml_audit_registry_no_delete_v2 BEFORE DELETE ON ml_audit_registry_v2 BEGIN SELECT RAISE(ABORT,'append-only: ml_audit_registry_v2'); END;

CREATE TRIGGER ml_model_job_dataset_v2 BEFORE INSERT ON ml_model_registry_v2 WHEN (SELECT dataset_id FROM ml_job WHERE job_id=NEW.job_id) IS NOT NEW.dataset_id BEGIN SELECT RAISE(ABORT,'model and job dataset mismatch'); END;

CREATE TRIGGER ml_feedback_observation_v2 BEFORE INSERT ON ml_feedback_registry_v2 WHEN NEW.observation_id IS NOT NULL AND (SELECT prediction_id FROM ml_observation_registry_v2 WHERE observation_id=NEW.observation_id) IS NOT NEW.prediction_id BEGIN SELECT RAISE(ABORT,'feedback observation belongs to another prediction'); END;

CREATE TRIGGER ml_observation_source_v2 BEFORE INSERT ON ml_observation_registry_v2 WHEN (SELECT source_hash FROM ml_source_registry WHERE source_version_id=NEW.source_version_id) IS NOT NEW.source_hash BEGIN SELECT RAISE(ABORT,'observation source mismatch'); END;

CREATE TRIGGER ml_prediction_source_v2 BEFORE INSERT ON ml_prediction_registry_v2 WHEN NEW.input_source_id IS NOT NULL AND (SELECT source_hash FROM ml_source_registry WHERE source_version_id=NEW.input_source_id) IS NOT NEW.input_source_hash BEGIN SELECT RAISE(ABORT,'prediction input source mismatch'); END;

CREATE TRIGGER ml_retrain_dataset_v2 BEFORE INSERT ON ml_retrain_registry_v2 WHEN (SELECT dataset_id FROM ml_model_registry_v2 WHERE model_version_id=NEW.parent_model_id) IS NOT NEW.dataset_id BEGIN SELECT RAISE(ABORT,'parameter-only proposal must preserve dataset'); END;

CREATE TRIGGER ml_model_source_guard_v2 BEFORE INSERT ON ml_model_registry_v2 WHEN (SELECT source_hash FROM ml_object WHERE object_id=NEW.model_version_id) IS NOT (SELECT source_hash FROM ml_dataset_registry WHERE dataset_id=NEW.dataset_id) BEGIN SELECT RAISE(ABORT,'model source does not match frozen dataset'); END;

CREATE TRIGGER ml_prediction_weights_guard_v2 BEFORE INSERT ON ml_prediction_registry_v2 WHEN (SELECT json_extract(payload_json,'$.weights_hash') FROM ml_object WHERE object_id=NEW.prediction_id) IS NOT (SELECT artifact_sha256 FROM ml_model_registry_v2 WHERE model_version_id=NEW.model_version_id) BEGIN SELECT RAISE(ABORT,'prediction weights do not match model version'); END;

CREATE INDEX ml_prediction_scope_v2 ON ml_prediction_registry_v2(model_version_id,trading_date);

CREATE INDEX ml_prediction_day_v2 ON ml_prediction_registry_v2(trading_date);

CREATE INDEX ml_observation_prediction_v2 ON ml_observation_registry_v2(prediction_id);

CREATE INDEX ml_model_dataset_v2 ON ml_model_registry_v2(dataset_id);

CREATE INDEX ml_feedback_prediction_v2 ON ml_feedback_registry_v2(prediction_id);

CREATE VIEW ml_models AS SELECT * FROM ml_model_registry UNION ALL SELECT * FROM ml_model_registry_v2;

CREATE VIEW ml_predictions AS SELECT * FROM ml_prediction_registry UNION ALL SELECT * FROM ml_prediction_registry_v2;

CREATE VIEW ml_observations AS SELECT * FROM ml_observation_registry UNION ALL SELECT * FROM ml_observation_registry_v2;

CREATE VIEW ml_feedbacks AS SELECT * FROM ml_feedback_registry UNION ALL SELECT * FROM ml_feedback_registry_v2;

CREATE VIEW ml_retrains AS SELECT * FROM ml_retrain_registry UNION ALL SELECT * FROM ml_retrain_registry_v2;

CREATE VIEW ml_audits AS SELECT * FROM ml_audit_registry UNION ALL SELECT * FROM ml_audit_registry_v2;

CREATE TRIGGER ml_task_model_contract BEFORE INSERT ON ml_model_registry_v2 WHEN
 NEW.task NOT IN ('pv_day_ahead_reference','pv_intraday_reference','da_price_reference','prebid_spread_reference','intraday_spread_reference') OR
 NEW.task IS NOT (SELECT task FROM ml_dataset_registry WHERE dataset_id=NEW.dataset_id) OR
 NEW.unit IS NOT (CASE WHEN NEW.task IN ('pv_day_ahead_reference','pv_intraday_reference') THEN 'MW' ELSE 'CNY/MWh' END)
 BEGIN SELECT RAISE(ABORT,'task, dataset and unit mismatch'); END;

CREATE TRIGGER ml_task_prediction_contract BEFORE INSERT ON ml_prediction_registry_v2 WHEN
 NEW.unit IS NOT (SELECT unit FROM ml_model_registry_v2 WHERE model_version_id=NEW.model_version_id) OR
 NEW.point_count IS NOT (SELECT CASE WHEN task IN ('pv_day_ahead_reference','pv_intraday_reference') THEN 96 ELSE 24 END FROM ml_model_registry_v2 WHERE model_version_id=NEW.model_version_id) OR
 (SELECT json_extract(payload_json,'$.task') FROM ml_object WHERE object_id=NEW.prediction_id) IS NOT (SELECT task FROM ml_model_registry_v2 WHERE model_version_id=NEW.model_version_id)
 BEGIN SELECT RAISE(ABORT,'prediction task, unit or grid mismatch'); END;

CREATE TRIGGER ml_task_object_owner BEFORE INSERT ON ml_object WHEN
 (NEW.kind='model' AND COALESCE(json_extract(NEW.payload_json,'$.task'),'') NOT IN ('rt_price_day_ahead_reference','pv_day_ahead_reference','pv_intraday_reference','da_price_reference','prebid_spread_reference','intraday_spread_reference')) OR
 (NEW.kind IN ('prediction','observation_match','feedback','proposal','audit') AND NOT EXISTS(SELECT 1 FROM ml_models WHERE model_version_id=json_extract(NEW.payload_json,'$.model_id')))
 BEGIN SELECT RAISE(ABORT,'unregistered learning task or model owner'); END;

CREATE TABLE ml_business_scenario (
 scenario_id TEXT PRIMARY KEY REFERENCES ml_object(object_id),
 prediction_id TEXT NOT NULL REFERENCES ml_prediction_registry_v2(prediction_id),
 model_id TEXT NOT NULL REFERENCES ml_model_registry_v2(model_version_id),
 source_version_id TEXT NOT NULL REFERENCES ml_source_registry(source_version_id),
 bid_ratio REAL NOT NULL CHECK(bid_ratio BETWEEN 0 AND 1.5),
 fee REAL NOT NULL CHECK(fee>=0),
 settled_intervals INTEGER NOT NULL CHECK(settled_intervals BETWEEN 4 AND 96 AND settled_intervals%4=0),
 value REAL NOT NULL,reference_value REAL NOT NULL,created_at TEXT NOT NULL
);
CREATE TRIGGER ml_business_scenario_insert AFTER INSERT ON ml_object WHEN NEW.kind='scenario' BEGIN
 INSERT INTO ml_business_scenario VALUES(NEW.object_id,json_extract(NEW.payload_json,'$.record_id'),json_extract(NEW.payload_json,'$.model_id'),json_extract(NEW.payload_json,'$.source_revision_id'),json_extract(NEW.payload_json,'$.bid_ratio'),json_extract(NEW.payload_json,'$.fee'),json_extract(NEW.payload_json,'$.result.settled_intervals'),json_extract(NEW.payload_json,'$.result.value'),json_extract(NEW.payload_json,'$.result.reference'),NEW.created_at);
END;
CREATE TRIGGER ml_business_scenario_owner BEFORE INSERT ON ml_business_scenario WHEN
 (SELECT model_version_id FROM ml_prediction_registry_v2 WHERE prediction_id=NEW.prediction_id) IS NOT NEW.model_id OR
 (SELECT task FROM ml_model_registry_v2 WHERE model_version_id=NEW.model_id) IS NOT 'pv_day_ahead_reference' OR
 (SELECT source_hash FROM ml_object WHERE object_id=NEW.scenario_id) IS NOT (SELECT source_hash FROM ml_source_registry WHERE source_version_id=NEW.source_version_id)
 BEGIN SELECT RAISE(ABORT,'scenario prediction, task or observation mismatch'); END;
CREATE TRIGGER ml_business_scenario_no_update BEFORE UPDATE ON ml_business_scenario BEGIN SELECT RAISE(ABORT,'append-only: ml_business_scenario'); END;
CREATE TRIGGER ml_business_scenario_no_delete BEFORE DELETE ON ml_business_scenario BEGIN SELECT RAISE(ABORT,'append-only: ml_business_scenario'); END;
CREATE INDEX ml_business_scenario_prediction ON ml_business_scenario(prediction_id,created_at);

CREATE TRIGGER ml_task_parent_binding BEFORE INSERT ON ml_object WHEN
 (NEW.kind='model' AND NEW.parent_id IS NOT json_extract(NEW.payload_json,'$.dataset_id')) OR
 (NEW.kind IN ('prediction','audit') AND NEW.parent_id IS NOT json_extract(NEW.payload_json,'$.model_id')) OR
 (NEW.kind IN ('observation_match','feedback') AND (NEW.parent_id IS NOT json_extract(NEW.payload_json,'$.prediction_id') OR json_extract(NEW.payload_json,'$.model_id') IS NOT (SELECT model_version_id FROM ml_predictions WHERE prediction_id=NEW.parent_id))) OR
 (NEW.kind='proposal' AND NEW.parent_id IS NOT json_extract(NEW.payload_json,'$.feedback_id')) OR
 (NEW.kind='scenario' AND NEW.parent_id IS NOT json_extract(NEW.payload_json,'$.record_id'))
 BEGIN SELECT RAISE(ABORT,'learning object parent binding mismatch'); END;
CREATE TRIGGER ml_task_prediction_grid BEFORE INSERT ON ml_prediction_registry_v2 WHEN
 (SELECT count(DISTINCT json_extract(value,'$.slot')) FROM json_each((SELECT payload_json FROM ml_object WHERE object_id=NEW.prediction_id),'$.points')) IS NOT NEW.point_count OR
 EXISTS(SELECT 1 FROM json_each((SELECT payload_json FROM ml_object WHERE object_id=NEW.prediction_id),'$.points') WHERE json_extract(value,'$.slot') NOT BETWEEN 0 AND 95 OR (NEW.point_count=24 AND json_extract(value,'$.slot')%4<>3))
 BEGIN SELECT RAISE(ABORT,'prediction grid must contain unique task intervals'); END;
