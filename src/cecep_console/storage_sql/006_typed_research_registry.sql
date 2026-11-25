-- Typed, append-only relational links over immutable ML evidence.

-- Existing objects and migrations are preserved; missing legacy archives remain NULL.

CREATE TABLE ml_source_registry (
 source_version_id TEXT PRIMARY KEY REFERENCES ml_object(object_id),
 source_hash TEXT NOT NULL UNIQUE CHECK(length(source_hash)=64),
 source_mode TEXT NOT NULL CHECK(source_mode IN ('synthetic','public_reference')),
 archive_path TEXT NOT NULL,
 archive_sha256 TEXT NOT NULL CHECK(archive_sha256=source_hash),
 record_count INTEGER NOT NULL CHECK(record_count>0),
 ingested_at TEXT NOT NULL
);

CREATE TABLE ml_dataset_registry (
 dataset_id TEXT PRIMARY KEY REFERENCES ml_object(object_id),
 source_version_id TEXT REFERENCES ml_source_registry(source_version_id),
 source_hash TEXT NOT NULL CHECK(length(source_hash)=64),
 task TEXT NOT NULL,
 split_json TEXT NOT NULL CHECK(json_valid(split_json)),
 feature_schema_json TEXT NOT NULL CHECK(json_valid(feature_schema_json)),
 created_at TEXT NOT NULL
);

CREATE TABLE ml_model_registry (
 model_version_id TEXT PRIMARY KEY REFERENCES ml_object(object_id),
 dataset_id TEXT NOT NULL REFERENCES ml_dataset_registry(dataset_id),
 job_id TEXT NOT NULL REFERENCES ml_job(job_id),
 algorithm TEXT NOT NULL CHECK(algorithm IN ('ridge','seasonal_naive_d2','seasonal_naive_d7','train_weekday_slot_median')),
 task TEXT NOT NULL,
 unit TEXT NOT NULL CHECK(unit='CNY/MWh'),
 artifact_path TEXT NOT NULL,
 artifact_sha256 TEXT NOT NULL CHECK(length(artifact_sha256)=64),
 training_end TEXT NOT NULL,
 selection_end TEXT NOT NULL,
 final_start TEXT NOT NULL,
 final_end TEXT NOT NULL,
 created_at TEXT NOT NULL
);

CREATE TABLE ml_prediction_registry (
 prediction_id TEXT PRIMARY KEY REFERENCES ml_object(object_id),
 model_version_id TEXT NOT NULL REFERENCES ml_model_registry(model_version_id),
 input_source_id TEXT REFERENCES ml_source_registry(source_version_id),
 input_source_hash TEXT NOT NULL CHECK(length(input_source_hash)=64),
 trading_date TEXT NOT NULL,
 cutoff_at TEXT NOT NULL,
 unit TEXT NOT NULL CHECK(unit='CNY/MWh'),
 point_count INTEGER NOT NULL CHECK(point_count=96),
 validation_only INTEGER NOT NULL CHECK(validation_only IN (0,1)),
 created_at TEXT NOT NULL
);

CREATE TABLE ml_observation_registry (
 observation_id TEXT PRIMARY KEY REFERENCES ml_object(object_id),
 prediction_id TEXT NOT NULL REFERENCES ml_prediction_registry(prediction_id),
 source_version_id TEXT NOT NULL REFERENCES ml_source_registry(source_version_id),
 source_hash TEXT NOT NULL,
 observed_points INTEGER NOT NULL CHECK(observed_points BETWEEN 0 AND 96),
 changed_points INTEGER NOT NULL CHECK(changed_points BETWEEN 0 AND 96),
 checked_at TEXT NOT NULL,
 created_at TEXT NOT NULL,
 UNIQUE(prediction_id,source_version_id)
);

CREATE TABLE ml_feedback_registry (
 feedback_id TEXT PRIMARY KEY REFERENCES ml_object(object_id),
 prediction_id TEXT NOT NULL REFERENCES ml_prediction_registry(prediction_id),
 observation_id TEXT REFERENCES ml_observation_registry(observation_id),
 slot INTEGER NOT NULL CHECK(slot BETWEEN 0 AND 95),
 reviewer_id TEXT NOT NULL,
 training_eligible INTEGER NOT NULL CHECK(training_eligible=0),
 created_at TEXT NOT NULL
);

CREATE TABLE ml_retrain_registry (
 proposal_id TEXT PRIMARY KEY REFERENCES ml_object(object_id),
 feedback_id TEXT NOT NULL REFERENCES ml_feedback_registry(feedback_id),
 dataset_id TEXT NOT NULL REFERENCES ml_dataset_registry(dataset_id),
 parent_model_id TEXT NOT NULL REFERENCES ml_model_registry(model_version_id),
 alpha REAL NOT NULL CHECK(alpha IN (0.1,1,10,100)),
 incorporates_labels INTEGER NOT NULL CHECK(incorporates_labels=0),
 created_at TEXT NOT NULL
);

CREATE TABLE ml_audit_registry (
 audit_id TEXT PRIMARY KEY REFERENCES ml_object(object_id),
 model_version_id TEXT NOT NULL REFERENCES ml_model_registry(model_version_id),
 task TEXT NOT NULL,
 window_start TEXT NOT NULL,
 window_end TEXT NOT NULL,
 created_at TEXT NOT NULL,
 UNIQUE(task,window_start,window_end)
);

INSERT INTO ml_source_registry (source_version_id,source_hash,source_mode,archive_path,archive_sha256,record_count,ingested_at) SELECT o.object_id,o.source_hash,json_extract(o.payload_json,'$.source_mode'),json_extract(o.payload_json,'$.archive.path'),json_extract(o.payload_json,'$.archive.sha256'),json_extract(o.payload_json,'$.metadata.row_count'),json_extract(o.payload_json,'$.ingested_at') FROM ml_object o WHERE o.kind='source_revision' ORDER BY o.rowid;

CREATE TRIGGER ml_source_registry_insert AFTER INSERT ON ml_object WHEN NEW.kind='source_revision' BEGIN INSERT INTO ml_source_registry (source_version_id,source_hash,source_mode,archive_path,archive_sha256,record_count,ingested_at) SELECT o.object_id,o.source_hash,json_extract(o.payload_json,'$.source_mode'),json_extract(o.payload_json,'$.archive.path'),json_extract(o.payload_json,'$.archive.sha256'),json_extract(o.payload_json,'$.metadata.row_count'),json_extract(o.payload_json,'$.ingested_at') FROM ml_object o WHERE o.object_id=NEW.object_id; END;

CREATE TRIGGER ml_source_registry_kind BEFORE INSERT ON ml_source_registry WHEN (SELECT kind FROM ml_object WHERE object_id=NEW.source_version_id) IS NOT 'source_revision' BEGIN SELECT RAISE(ABORT,'typed object kind mismatch: ml_source_registry'); END;

CREATE TRIGGER ml_source_registry_no_update BEFORE UPDATE ON ml_source_registry BEGIN SELECT RAISE(ABORT,'append-only: ml_source_registry'); END;

CREATE TRIGGER ml_source_registry_no_delete BEFORE DELETE ON ml_source_registry BEGIN SELECT RAISE(ABORT,'append-only: ml_source_registry'); END;

INSERT INTO ml_dataset_registry (dataset_id,source_version_id,source_hash,task,split_json,feature_schema_json,created_at) SELECT o.object_id,(SELECT source_version_id FROM ml_source_registry WHERE source_hash=o.source_hash),o.source_hash,json_extract(o.payload_json,'$.policy.task'),json_extract(o.payload_json,'$.splits'),json_extract(o.payload_json,'$.policy.features'),o.created_at FROM ml_object o WHERE o.kind='dataset' ORDER BY o.rowid;

CREATE TRIGGER ml_dataset_registry_insert AFTER INSERT ON ml_object WHEN NEW.kind='dataset' BEGIN INSERT INTO ml_dataset_registry (dataset_id,source_version_id,source_hash,task,split_json,feature_schema_json,created_at) SELECT o.object_id,(SELECT source_version_id FROM ml_source_registry WHERE source_hash=o.source_hash),o.source_hash,json_extract(o.payload_json,'$.policy.task'),json_extract(o.payload_json,'$.splits'),json_extract(o.payload_json,'$.policy.features'),o.created_at FROM ml_object o WHERE o.object_id=NEW.object_id; END;

CREATE TRIGGER ml_dataset_registry_kind BEFORE INSERT ON ml_dataset_registry WHEN (SELECT kind FROM ml_object WHERE object_id=NEW.dataset_id) IS NOT 'dataset' BEGIN SELECT RAISE(ABORT,'typed object kind mismatch: ml_dataset_registry'); END;

CREATE TRIGGER ml_dataset_registry_no_update BEFORE UPDATE ON ml_dataset_registry BEGIN SELECT RAISE(ABORT,'append-only: ml_dataset_registry'); END;

CREATE TRIGGER ml_dataset_registry_no_delete BEFORE DELETE ON ml_dataset_registry BEGIN SELECT RAISE(ABORT,'append-only: ml_dataset_registry'); END;

INSERT INTO ml_model_registry (model_version_id,dataset_id,job_id,algorithm,task,unit,artifact_path,artifact_sha256,training_end,selection_end,final_start,final_end,created_at) SELECT o.object_id,json_extract(o.payload_json,'$.dataset_id'),json_extract(o.payload_json,'$.job_id'),json_extract(o.payload_json,'$.algorithm'),json_extract(o.payload_json,'$.task'),json_extract(o.payload_json,'$.unit'),json_extract(o.payload_json,'$.weights.path'),json_extract(o.payload_json,'$.weights.sha256'),json_extract(o.payload_json,'$.training_label_end'),json_extract(o.payload_json,'$.selection_end'),json_extract(o.payload_json,'$.splits.final_audit[0]'),json_extract(o.payload_json,'$.splits.final_audit[1]'),o.created_at FROM ml_object o WHERE o.kind='model' ORDER BY o.rowid;

CREATE TRIGGER ml_model_registry_insert AFTER INSERT ON ml_object WHEN NEW.kind='model' BEGIN INSERT INTO ml_model_registry (model_version_id,dataset_id,job_id,algorithm,task,unit,artifact_path,artifact_sha256,training_end,selection_end,final_start,final_end,created_at) SELECT o.object_id,json_extract(o.payload_json,'$.dataset_id'),json_extract(o.payload_json,'$.job_id'),json_extract(o.payload_json,'$.algorithm'),json_extract(o.payload_json,'$.task'),json_extract(o.payload_json,'$.unit'),json_extract(o.payload_json,'$.weights.path'),json_extract(o.payload_json,'$.weights.sha256'),json_extract(o.payload_json,'$.training_label_end'),json_extract(o.payload_json,'$.selection_end'),json_extract(o.payload_json,'$.splits.final_audit[0]'),json_extract(o.payload_json,'$.splits.final_audit[1]'),o.created_at FROM ml_object o WHERE o.object_id=NEW.object_id; END;

CREATE TRIGGER ml_model_registry_kind BEFORE INSERT ON ml_model_registry WHEN (SELECT kind FROM ml_object WHERE object_id=NEW.model_version_id) IS NOT 'model' BEGIN SELECT RAISE(ABORT,'typed object kind mismatch: ml_model_registry'); END;

CREATE TRIGGER ml_model_registry_no_update BEFORE UPDATE ON ml_model_registry BEGIN SELECT RAISE(ABORT,'append-only: ml_model_registry'); END;

CREATE TRIGGER ml_model_registry_no_delete BEFORE DELETE ON ml_model_registry BEGIN SELECT RAISE(ABORT,'append-only: ml_model_registry'); END;

INSERT INTO ml_prediction_registry (prediction_id,model_version_id,input_source_id,input_source_hash,trading_date,cutoff_at,unit,point_count,validation_only,created_at) SELECT o.object_id,json_extract(o.payload_json,'$.model_id'),(SELECT source_version_id FROM ml_source_registry WHERE source_hash=o.source_hash),o.source_hash,json_extract(o.payload_json,'$.date'),(strftime('%Y-%m-%dT%H:%M:%S',json_extract(o.payload_json,'$.logical_cutoff'))||'.000000Z'),json_extract(o.payload_json,'$.unit'),json_array_length(o.payload_json,'$.points'),json_extract(o.payload_json,'$.validation_only'),o.created_at FROM ml_object o WHERE o.kind='prediction' ORDER BY o.rowid;

CREATE TRIGGER ml_prediction_registry_insert AFTER INSERT ON ml_object WHEN NEW.kind='prediction' BEGIN INSERT INTO ml_prediction_registry (prediction_id,model_version_id,input_source_id,input_source_hash,trading_date,cutoff_at,unit,point_count,validation_only,created_at) SELECT o.object_id,json_extract(o.payload_json,'$.model_id'),(SELECT source_version_id FROM ml_source_registry WHERE source_hash=o.source_hash),o.source_hash,json_extract(o.payload_json,'$.date'),(strftime('%Y-%m-%dT%H:%M:%S',json_extract(o.payload_json,'$.logical_cutoff'))||'.000000Z'),json_extract(o.payload_json,'$.unit'),json_array_length(o.payload_json,'$.points'),json_extract(o.payload_json,'$.validation_only'),o.created_at FROM ml_object o WHERE o.object_id=NEW.object_id; END;

CREATE TRIGGER ml_prediction_registry_kind BEFORE INSERT ON ml_prediction_registry WHEN (SELECT kind FROM ml_object WHERE object_id=NEW.prediction_id) IS NOT 'prediction' BEGIN SELECT RAISE(ABORT,'typed object kind mismatch: ml_prediction_registry'); END;

CREATE TRIGGER ml_prediction_registry_no_update BEFORE UPDATE ON ml_prediction_registry BEGIN SELECT RAISE(ABORT,'append-only: ml_prediction_registry'); END;

CREATE TRIGGER ml_prediction_registry_no_delete BEFORE DELETE ON ml_prediction_registry BEGIN SELECT RAISE(ABORT,'append-only: ml_prediction_registry'); END;

INSERT INTO ml_observation_registry (observation_id,prediction_id,source_version_id,source_hash,observed_points,changed_points,checked_at,created_at) SELECT o.object_id,json_extract(o.payload_json,'$.prediction_id'),json_extract(o.payload_json,'$.source_revision_id'),o.source_hash,json_extract(o.payload_json,'$.observed_points'),json_extract(o.payload_json,'$.changed_from_snapshot'),json_extract(o.payload_json,'$.checked_at'),o.created_at FROM ml_object o WHERE o.kind='observation_match' ORDER BY o.rowid;

CREATE TRIGGER ml_observation_registry_insert AFTER INSERT ON ml_object WHEN NEW.kind='observation_match' BEGIN INSERT INTO ml_observation_registry (observation_id,prediction_id,source_version_id,source_hash,observed_points,changed_points,checked_at,created_at) SELECT o.object_id,json_extract(o.payload_json,'$.prediction_id'),json_extract(o.payload_json,'$.source_revision_id'),o.source_hash,json_extract(o.payload_json,'$.observed_points'),json_extract(o.payload_json,'$.changed_from_snapshot'),json_extract(o.payload_json,'$.checked_at'),o.created_at FROM ml_object o WHERE o.object_id=NEW.object_id; END;

CREATE TRIGGER ml_observation_registry_kind BEFORE INSERT ON ml_observation_registry WHEN (SELECT kind FROM ml_object WHERE object_id=NEW.observation_id) IS NOT 'observation_match' BEGIN SELECT RAISE(ABORT,'typed object kind mismatch: ml_observation_registry'); END;

CREATE TRIGGER ml_observation_registry_no_update BEFORE UPDATE ON ml_observation_registry BEGIN SELECT RAISE(ABORT,'append-only: ml_observation_registry'); END;

CREATE TRIGGER ml_observation_registry_no_delete BEFORE DELETE ON ml_observation_registry BEGIN SELECT RAISE(ABORT,'append-only: ml_observation_registry'); END;

INSERT INTO ml_feedback_registry (feedback_id,prediction_id,observation_id,slot,reviewer_id,training_eligible,created_at) SELECT o.object_id,json_extract(o.payload_json,'$.prediction_id'),json_extract(o.payload_json,'$.observation_id'),json_extract(o.payload_json,'$.slot'),json_extract(o.payload_json,'$.actor'),json_extract(o.payload_json,'$.training_eligible'),o.created_at FROM ml_object o WHERE o.kind='feedback' ORDER BY o.rowid;

CREATE TRIGGER ml_feedback_registry_insert AFTER INSERT ON ml_object WHEN NEW.kind='feedback' BEGIN INSERT INTO ml_feedback_registry (feedback_id,prediction_id,observation_id,slot,reviewer_id,training_eligible,created_at) SELECT o.object_id,json_extract(o.payload_json,'$.prediction_id'),json_extract(o.payload_json,'$.observation_id'),json_extract(o.payload_json,'$.slot'),json_extract(o.payload_json,'$.actor'),json_extract(o.payload_json,'$.training_eligible'),o.created_at FROM ml_object o WHERE o.object_id=NEW.object_id; END;

CREATE TRIGGER ml_feedback_registry_kind BEFORE INSERT ON ml_feedback_registry WHEN (SELECT kind FROM ml_object WHERE object_id=NEW.feedback_id) IS NOT 'feedback' BEGIN SELECT RAISE(ABORT,'typed object kind mismatch: ml_feedback_registry'); END;

CREATE TRIGGER ml_feedback_registry_no_update BEFORE UPDATE ON ml_feedback_registry BEGIN SELECT RAISE(ABORT,'append-only: ml_feedback_registry'); END;

CREATE TRIGGER ml_feedback_registry_no_delete BEFORE DELETE ON ml_feedback_registry BEGIN SELECT RAISE(ABORT,'append-only: ml_feedback_registry'); END;

INSERT INTO ml_retrain_registry (proposal_id,feedback_id,dataset_id,parent_model_id,alpha,incorporates_labels,created_at) SELECT o.object_id,json_extract(o.payload_json,'$.feedback_id'),json_extract(o.payload_json,'$.dataset_id'),json_extract(o.payload_json,'$.model_id'),json_extract(o.payload_json,'$.alpha'),json_extract(o.payload_json,'$.incorporates_labels'),o.created_at FROM ml_object o WHERE o.kind='proposal' ORDER BY o.rowid;

CREATE TRIGGER ml_retrain_registry_insert AFTER INSERT ON ml_object WHEN NEW.kind='proposal' BEGIN INSERT INTO ml_retrain_registry (proposal_id,feedback_id,dataset_id,parent_model_id,alpha,incorporates_labels,created_at) SELECT o.object_id,json_extract(o.payload_json,'$.feedback_id'),json_extract(o.payload_json,'$.dataset_id'),json_extract(o.payload_json,'$.model_id'),json_extract(o.payload_json,'$.alpha'),json_extract(o.payload_json,'$.incorporates_labels'),o.created_at FROM ml_object o WHERE o.object_id=NEW.object_id; END;

CREATE TRIGGER ml_retrain_registry_kind BEFORE INSERT ON ml_retrain_registry WHEN (SELECT kind FROM ml_object WHERE object_id=NEW.proposal_id) IS NOT 'proposal' BEGIN SELECT RAISE(ABORT,'typed object kind mismatch: ml_retrain_registry'); END;

CREATE TRIGGER ml_retrain_registry_no_update BEFORE UPDATE ON ml_retrain_registry BEGIN SELECT RAISE(ABORT,'append-only: ml_retrain_registry'); END;

CREATE TRIGGER ml_retrain_registry_no_delete BEFORE DELETE ON ml_retrain_registry BEGIN SELECT RAISE(ABORT,'append-only: ml_retrain_registry'); END;

INSERT INTO ml_audit_registry (audit_id,model_version_id,task,window_start,window_end,created_at) SELECT o.object_id,json_extract(o.payload_json,'$.model_id'),(SELECT task FROM ml_model_registry WHERE model_version_id=json_extract(o.payload_json,'$.model_id')),(SELECT final_start FROM ml_model_registry WHERE model_version_id=json_extract(o.payload_json,'$.model_id')),(SELECT final_end FROM ml_model_registry WHERE model_version_id=json_extract(o.payload_json,'$.model_id')),o.created_at FROM ml_object o WHERE o.kind='audit' ORDER BY o.rowid;

CREATE TRIGGER ml_audit_registry_insert AFTER INSERT ON ml_object WHEN NEW.kind='audit' BEGIN INSERT INTO ml_audit_registry (audit_id,model_version_id,task,window_start,window_end,created_at) SELECT o.object_id,json_extract(o.payload_json,'$.model_id'),(SELECT task FROM ml_model_registry WHERE model_version_id=json_extract(o.payload_json,'$.model_id')),(SELECT final_start FROM ml_model_registry WHERE model_version_id=json_extract(o.payload_json,'$.model_id')),(SELECT final_end FROM ml_model_registry WHERE model_version_id=json_extract(o.payload_json,'$.model_id')),o.created_at FROM ml_object o WHERE o.object_id=NEW.object_id; END;

CREATE TRIGGER ml_audit_registry_kind BEFORE INSERT ON ml_audit_registry WHEN (SELECT kind FROM ml_object WHERE object_id=NEW.audit_id) IS NOT 'audit' BEGIN SELECT RAISE(ABORT,'typed object kind mismatch: ml_audit_registry'); END;

CREATE TRIGGER ml_audit_registry_no_update BEFORE UPDATE ON ml_audit_registry BEGIN SELECT RAISE(ABORT,'append-only: ml_audit_registry'); END;

CREATE TRIGGER ml_audit_registry_no_delete BEFORE DELETE ON ml_audit_registry BEGIN SELECT RAISE(ABORT,'append-only: ml_audit_registry'); END;

CREATE INDEX ml_object_kind ON ml_object(kind);

CREATE INDEX ml_object_kind_source ON ml_object(kind,source_hash);

CREATE INDEX ml_object_parent_kind ON ml_object(parent_id,kind);

CREATE INDEX ml_event_latest ON ml_event(subject_id);

CREATE INDEX ml_prediction_scope ON ml_prediction_registry(model_version_id,trading_date);

CREATE INDEX ml_prediction_day ON ml_prediction_registry(trading_date);

CREATE INDEX ml_observation_prediction ON ml_observation_registry(prediction_id);

CREATE INDEX ml_dataset_source ON ml_dataset_registry(source_hash);

CREATE INDEX ml_model_dataset ON ml_model_registry(dataset_id);

CREATE INDEX ml_feedback_prediction ON ml_feedback_registry(prediction_id);

CREATE TRIGGER ml_job_dataset_kind BEFORE INSERT ON ml_job WHEN NOT EXISTS(SELECT 1 FROM ml_dataset_registry WHERE dataset_id=NEW.dataset_id) BEGIN SELECT RAISE(ABORT,'training job requires typed dataset'); END;

CREATE TRIGGER ml_model_job_dataset BEFORE INSERT ON ml_model_registry WHEN (SELECT dataset_id FROM ml_job WHERE job_id=NEW.job_id) IS NOT NEW.dataset_id BEGIN SELECT RAISE(ABORT,'model and job dataset mismatch'); END;

CREATE TRIGGER ml_feedback_observation BEFORE INSERT ON ml_feedback_registry WHEN NEW.observation_id IS NOT NULL AND (SELECT prediction_id FROM ml_observation_registry WHERE observation_id=NEW.observation_id) IS NOT NEW.prediction_id BEGIN SELECT RAISE(ABORT,'feedback observation belongs to another prediction'); END;

CREATE TRIGGER ml_observation_source BEFORE INSERT ON ml_observation_registry WHEN (SELECT source_hash FROM ml_source_registry WHERE source_version_id=NEW.source_version_id) IS NOT NEW.source_hash BEGIN SELECT RAISE(ABORT,'observation source mismatch'); END;

CREATE TRIGGER ml_prediction_source BEFORE INSERT ON ml_prediction_registry WHEN NEW.input_source_id IS NOT NULL AND (SELECT source_hash FROM ml_source_registry WHERE source_version_id=NEW.input_source_id) IS NOT NEW.input_source_hash BEGIN SELECT RAISE(ABORT,'prediction input source mismatch'); END;

CREATE TRIGGER ml_retrain_dataset BEFORE INSERT ON ml_retrain_registry WHEN (SELECT dataset_id FROM ml_model_registry WHERE model_version_id=NEW.parent_model_id) IS NOT NEW.dataset_id BEGIN SELECT RAISE(ABORT,'parameter-only proposal must preserve dataset'); END;

CREATE TRIGGER ml_model_source_guard BEFORE INSERT ON ml_model_registry WHEN (SELECT source_hash FROM ml_object WHERE object_id=NEW.model_version_id) IS NOT (SELECT source_hash FROM ml_dataset_registry WHERE dataset_id=NEW.dataset_id) BEGIN SELECT RAISE(ABORT,'model source does not match frozen dataset'); END;

CREATE TRIGGER ml_prediction_weights_guard BEFORE INSERT ON ml_prediction_registry WHEN (SELECT json_extract(payload_json,'$.weights_hash') FROM ml_object WHERE object_id=NEW.prediction_id) IS NOT (SELECT artifact_sha256 FROM ml_model_registry WHERE model_version_id=NEW.model_version_id) BEGIN SELECT RAISE(ABORT,'prediction weights do not match model version'); END;
