-- Business snapshots reuse immutable objects and events; no alternate numerical store.
CREATE TRIGGER business_plan_owner BEFORE INSERT ON ml_object WHEN NEW.kind='business_plan' AND (
 NEW.parent_id IS NOT COALESCE(json_extract(NEW.payload_json,'$.parent_plan_id'),json_extract(NEW.payload_json,'$.record_id')) OR
 json_extract(NEW.payload_json,'$.source_key') IS NOT 'market:shandong' OR
 json_extract(NEW.payload_json,'$.task') IS NOT 'pv_day_ahead_reference' OR
 json_extract(NEW.payload_json,'$.production_eligible') IS NOT 0 OR
 json_extract(NEW.payload_json,'$.input_source_hash') IS NOT NEW.source_hash OR
 NOT EXISTS(SELECT 1 FROM ml_object p JOIN ml_models m ON m.model_version_id=json_extract(p.payload_json,'$.model_id') WHERE
  p.object_id=json_extract(NEW.payload_json,'$.record_id') AND p.kind='prediction' AND p.source_hash=NEW.source_hash AND
  m.task='pv_day_ahead_reference' AND m.model_version_id=json_extract(NEW.payload_json,'$.model_id') AND
  json_extract(p.payload_json,'$.date')=json_extract(NEW.payload_json,'$.date') AND
  json_extract(p.payload_json,'$.logical_cutoff')=json_extract(NEW.payload_json,'$.cutoff_at')) OR
 (json_extract(NEW.payload_json,'$.parent_plan_id') IS NOT NULL AND NOT EXISTS(SELECT 1 FROM ml_object p WHERE p.kind='business_plan' AND p.object_id=json_extract(NEW.payload_json,'$.parent_plan_id') AND json_extract(p.payload_json,'$.source_key')=json_extract(NEW.payload_json,'$.source_key') AND json_extract(p.payload_json,'$.date')=json_extract(NEW.payload_json,'$.date'))) OR
 json_array_length(NEW.payload_json,'$.hours') IS NOT 24 OR
 (SELECT count(DISTINCT json_extract(value,'$.hour')) FROM json_each(NEW.payload_json,'$.hours')) IS NOT 24 OR
 EXISTS(SELECT 1 FROM json_each(NEW.payload_json,'$.hours') WHERE json_extract(value,'$.hour') NOT BETWEEN 0 AND 23)
) BEGIN SELECT RAISE(ABORT,'business plan prediction or scope mismatch'); END;

CREATE TRIGGER business_plan_prices BEFORE INSERT ON ml_object WHEN NEW.kind='business_plan' AND EXISTS(
 SELECT 1 FROM json_each(NEW.payload_json,'$.price_records') r WHERE r.key NOT IN ('da','rt','spread') OR NOT EXISTS(
  SELECT 1 FROM ml_object p JOIN ml_models m ON m.model_version_id=json_extract(p.payload_json,'$.model_id') JOIN ml_object mo ON mo.object_id=m.model_version_id WHERE
  p.object_id=json_extract(r.value,'$.record_id') AND p.kind='prediction' AND p.source_hash=NEW.source_hash AND
  m.task=(CASE r.key WHEN 'da' THEN 'da_price_reference' WHEN 'rt' THEN 'rt_price_day_ahead_reference' WHEN 'spread' THEN 'prebid_spread_reference' END) AND
  json_extract(p.payload_json,'$.date')=json_extract(NEW.payload_json,'$.date') AND
  json_extract(p.payload_json,'$.logical_cutoff')=json_extract(NEW.payload_json,'$.cutoff_at') AND
  COALESCE(json_extract(mo.payload_json,'$.policy.information_budget'),'d2_history')=json_extract(NEW.payload_json,'$.information_budget')
 )) BEGIN SELECT RAISE(ABORT,'business price forecast scope mismatch'); END;

CREATE TRIGGER business_settlement_owner BEFORE INSERT ON ml_object WHEN NEW.kind='business_settlement' AND (
 NEW.parent_id IS NOT json_extract(NEW.payload_json,'$.plan_id') OR
 json_extract(NEW.payload_json,'$.production_eligible') IS NOT 0 OR
 json_extract(NEW.payload_json,'$.observation_source_hash') IS NOT NEW.source_hash OR
 NOT EXISTS(SELECT 1 FROM ml_object p JOIN ml_object o ON o.object_id=json_extract(NEW.payload_json,'$.observation_id') WHERE
  p.object_id=NEW.parent_id AND p.kind='business_plan' AND o.kind='observation_match' AND
  o.source_hash=NEW.source_hash AND o.parent_id=json_extract(p.payload_json,'$.record_id') AND
  json_extract(NEW.payload_json,'$.source_key')=json_extract(p.payload_json,'$.source_key') AND
  json_extract(NEW.payload_json,'$.date')=json_extract(p.payload_json,'$.date') AND
  json_extract(NEW.payload_json,'$.record_id')=json_extract(p.payload_json,'$.record_id') AND
  json_extract(NEW.payload_json,'$.source_revision_id')=json_extract(o.payload_json,'$.source_revision_id'))
) BEGIN SELECT RAISE(ABORT,'business settlement plan or observation mismatch'); END;

CREATE INDEX business_plan_scope ON ml_object(json_extract(payload_json,'$.source_key'),json_extract(payload_json,'$.date'),created_at) WHERE kind='business_plan';
CREATE INDEX business_settlement_plan ON ml_object(parent_id,created_at) WHERE kind='business_settlement';
