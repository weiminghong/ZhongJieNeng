-- Public-market research evidence is distinct from site production and training.
CREATE TABLE public_reference_run (
 run_id TEXT PRIMARY KEY,
 dataset_id TEXT NOT NULL,
 source_hash TEXT NOT NULL,
 kind TEXT NOT NULL CHECK(kind IN ('analysis','review','scenario')),
 scope_json TEXT NOT NULL CHECK(json_valid(scope_json)),
 evidence_json TEXT NOT NULL CHECK(json_valid(evidence_json)),
 output_json TEXT NOT NULL CHECK(json_valid(output_json)),
 answer_text TEXT NOT NULL,
 status TEXT NOT NULL CHECK(status IN ('completed','provider_failed')),
 created_at TEXT NOT NULL
);
CREATE INDEX public_reference_run_scope ON public_reference_run(source_hash,created_at);
CREATE TRIGGER public_reference_run_immutable_update BEFORE UPDATE ON public_reference_run BEGIN SELECT RAISE(ABORT,'append-only: public_reference_run'); END;
CREATE TRIGGER public_reference_run_immutable_delete BEFORE DELETE ON public_reference_run BEGIN SELECT RAISE(ABORT,'append-only: public_reference_run'); END;
