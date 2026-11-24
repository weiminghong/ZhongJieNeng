CREATE TABLE ml_object (
 object_id TEXT PRIMARY KEY, kind TEXT NOT NULL,
 parent_id TEXT REFERENCES ml_object(object_id), source_hash TEXT NOT NULL,
 payload_json TEXT NOT NULL CHECK(json_valid(payload_json)), created_at TEXT NOT NULL
);
CREATE TABLE ml_job (
 job_id TEXT PRIMARY KEY, dataset_id TEXT NOT NULL REFERENCES ml_object(object_id),
 parent_job_id TEXT REFERENCES ml_job(job_id), idempotency_key TEXT NOT NULL UNIQUE,
 config_json TEXT NOT NULL CHECK(json_valid(config_json)), created_at TEXT NOT NULL
);
CREATE TABLE ml_event (
 event_id TEXT PRIMARY KEY, subject_id TEXT NOT NULL, state TEXT NOT NULL,
 payload_json TEXT NOT NULL CHECK(json_valid(payload_json)), created_at TEXT NOT NULL
);
CREATE INDEX ml_event_subject ON ml_event(subject_id,created_at);
CREATE TRIGGER ml_object_no_update BEFORE UPDATE ON ml_object BEGIN SELECT RAISE(ABORT,'append-only: ml_object'); END;
CREATE TRIGGER ml_object_no_delete BEFORE DELETE ON ml_object BEGIN SELECT RAISE(ABORT,'append-only: ml_object'); END;
CREATE TRIGGER ml_job_no_update BEFORE UPDATE ON ml_job BEGIN SELECT RAISE(ABORT,'append-only: ml_job'); END;
CREATE TRIGGER ml_job_no_delete BEFORE DELETE ON ml_job BEGIN SELECT RAISE(ABORT,'append-only: ml_job'); END;
CREATE TRIGGER ml_event_no_update BEFORE UPDATE ON ml_event BEGIN SELECT RAISE(ABORT,'append-only: ml_event'); END;
CREATE TRIGGER ml_event_no_delete BEFORE DELETE ON ml_event BEGIN SELECT RAISE(ABORT,'append-only: ml_event'); END;
