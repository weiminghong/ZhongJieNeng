-- SQLite 3.35+; all instants are fixed-width UTC; synthetic evidence is opt-in.

CREATE TABLE data_source (
  "source_id" TEXT PRIMARY KEY NOT NULL,
  "source_name" TEXT NOT NULL,
  "source_type" TEXT NOT NULL,
  "provider_name" TEXT NOT NULL,
  "data_scope" TEXT,
  "default_timezone" TEXT,
  "expected_update_interval" TEXT,
  "access_method" TEXT,
  "owner_contact" TEXT,
  "enabled" INTEGER NOT NULL CHECK (enabled IN (0,1)),
  "created_at" TEXT NOT NULL CHECK (created_at IS NULL OR (length(created_at)=27 AND substr(created_at,11,1)='T' AND substr(created_at,27,1)='Z' AND julianday(created_at) IS NOT NULL)),
  UNIQUE (source_name)
);

CREATE TRIGGER immutable_data_source_update BEFORE UPDATE ON data_source BEGIN SELECT RAISE(ABORT,'append-only: data_source'); END;

CREATE TRIGGER immutable_data_source_delete BEFORE DELETE ON data_source BEGIN SELECT RAISE(ABORT,'append-only: data_source'); END;

CREATE TABLE ingestion_batch (
  "batch_id" TEXT PRIMARY KEY NOT NULL,
  "source_id" TEXT NOT NULL,
  "dataset_name" TEXT NOT NULL,
  "requested_start" TEXT CHECK (requested_start IS NULL OR (length(requested_start)=27 AND substr(requested_start,11,1)='T' AND substr(requested_start,27,1)='Z' AND julianday(requested_start) IS NOT NULL)),
  "requested_end" TEXT CHECK (requested_end IS NULL OR (length(requested_end)=27 AND substr(requested_end,11,1)='T' AND substr(requested_end,27,1)='Z' AND julianday(requested_end) IS NOT NULL)),
  "started_at" TEXT NOT NULL CHECK (started_at IS NULL OR (length(started_at)=27 AND substr(started_at,11,1)='T' AND substr(started_at,27,1)='Z' AND julianday(started_at) IS NOT NULL)),
  "finished_at" TEXT CHECK (finished_at IS NULL OR (length(finished_at)=27 AND substr(finished_at,11,1)='T' AND substr(finished_at,27,1)='Z' AND julianday(finished_at) IS NOT NULL)),
  "status" TEXT NOT NULL,
  "record_count" INTEGER,
  "raw_file_uri" TEXT,
  "file_hash" TEXT NOT NULL,
  "parser_version" TEXT NOT NULL,
  "error_summary" TEXT,
  FOREIGN KEY (source_id) REFERENCES data_source(source_id),
  UNIQUE (batch_id, source_id),
  UNIQUE (source_id, dataset_name, file_hash)
);

CREATE TABLE station (
  "station_id" TEXT PRIMARY KEY NOT NULL,
  "station_code" TEXT NOT NULL,
  "station_name" TEXT NOT NULL,
  "station_type" TEXT NOT NULL,
  "province_code" TEXT NOT NULL,
  "latitude" REAL NOT NULL,
  "longitude" REAL NOT NULL,
  "altitude_m" REAL,
  "timezone" TEXT NOT NULL,
  "commissioned_at" TEXT CHECK (commissioned_at IS NULL OR (length(commissioned_at)=27 AND substr(commissioned_at,11,1)='T' AND substr(commissioned_at,27,1)='Z' AND julianday(commissioned_at) IS NOT NULL)),
  "status" TEXT NOT NULL,
  "created_at" TEXT NOT NULL CHECK (created_at IS NULL OR (length(created_at)=27 AND substr(created_at,11,1)='T' AND substr(created_at,27,1)='Z' AND julianday(created_at) IS NOT NULL)),
  "available_at" TEXT NOT NULL CHECK (available_at IS NULL OR (length(available_at)=27 AND substr(available_at,11,1)='T' AND substr(available_at,27,1)='Z' AND julianday(available_at) IS NOT NULL)),
  "availability_basis" TEXT NOT NULL CHECK (availability_basis IN ('verified_arrival','verified_publication','synthetic','unknown')),
  "revision_no" INTEGER NOT NULL CHECK (revision_no>=0),
  UNIQUE (station_code, revision_no)
);

CREATE INDEX idx_station_pit ON station(station_code,available_at);

CREATE TRIGGER immutable_station_update BEFORE UPDATE ON station BEGIN SELECT RAISE(ABORT,'append-only: station'); END;

CREATE TRIGGER immutable_station_delete BEFORE DELETE ON station BEGIN SELECT RAISE(ABORT,'append-only: station'); END;

CREATE TABLE station_config_version (
  "config_version_id" TEXT PRIMARY KEY NOT NULL,
  "station_id" TEXT NOT NULL,
  "effective_from" TEXT NOT NULL CHECK (effective_from IS NULL OR (length(effective_from)=27 AND substr(effective_from,11,1)='T' AND substr(effective_from,27,1)='Z' AND julianday(effective_from) IS NOT NULL)),
  "effective_to" TEXT CHECK (effective_to IS NULL OR (length(effective_to)=27 AND substr(effective_to,11,1)='T' AND substr(effective_to,27,1)='Z' AND julianday(effective_to) IS NOT NULL)),
  "capacity_dc_mwp" REAL,
  "capacity_ac_mw" REAL NOT NULL,
  "connection_limit_mw" REAL,
  "tilt_deg" REAL,
  "azimuth_deg" REAL,
  "tracking_type" TEXT,
  "module_temp_coeff_per_c" REAL,
  "array_layout_ref" TEXT,
  "source_id" TEXT NOT NULL,
  "published_at" TEXT CHECK (published_at IS NULL OR (length(published_at)=27 AND substr(published_at,11,1)='T' AND substr(published_at,27,1)='Z' AND julianday(published_at) IS NOT NULL)),
  "first_seen_at" TEXT NOT NULL CHECK (first_seen_at IS NULL OR (length(first_seen_at)=27 AND substr(first_seen_at,11,1)='T' AND substr(first_seen_at,27,1)='Z' AND julianday(first_seen_at) IS NOT NULL)),
  "available_at" TEXT NOT NULL CHECK (available_at IS NULL OR (length(available_at)=27 AND substr(available_at,11,1)='T' AND substr(available_at,27,1)='Z' AND julianday(available_at) IS NOT NULL)),
  "revision_no" INTEGER NOT NULL CHECK (revision_no>=0),
  "availability_basis" TEXT NOT NULL CHECK (availability_basis IN ('verified_arrival','verified_publication','synthetic','unknown')),
  FOREIGN KEY (station_id) REFERENCES station(station_id),
  FOREIGN KEY (source_id) REFERENCES data_source(source_id),
  UNIQUE (station_id, effective_from, revision_no),
  CHECK (effective_to IS NULL OR effective_to>effective_from),
  CHECK (published_at IS NULL OR published_at<=available_at),
  CHECK (first_seen_at IS NULL OR first_seen_at<=available_at)
);

CREATE INDEX idx_station_config_version_pit ON station_config_version(station_id,effective_from,available_at);

CREATE TRIGGER immutable_station_config_version_update BEFORE UPDATE ON station_config_version BEGIN SELECT RAISE(ABORT,'append-only: station_config_version'); END;

CREATE TRIGGER immutable_station_config_version_delete BEFORE DELETE ON station_config_version BEGIN SELECT RAISE(ABORT,'append-only: station_config_version'); END;

CREATE TABLE market_location (
  "market_location_id" TEXT PRIMARY KEY NOT NULL,
  "location_code" TEXT NOT NULL,
  "location_name" TEXT NOT NULL,
  "location_type" TEXT NOT NULL,
  "market_code" TEXT NOT NULL,
  "parent_location_id" TEXT,
  "timezone" TEXT NOT NULL,
  "effective_from" TEXT NOT NULL CHECK (effective_from IS NULL OR (length(effective_from)=27 AND substr(effective_from,11,1)='T' AND substr(effective_from,27,1)='Z' AND julianday(effective_from) IS NOT NULL)),
  "effective_to" TEXT CHECK (effective_to IS NULL OR (length(effective_to)=27 AND substr(effective_to,11,1)='T' AND substr(effective_to,27,1)='Z' AND julianday(effective_to) IS NOT NULL)),
  "available_at" TEXT NOT NULL CHECK (available_at IS NULL OR (length(available_at)=27 AND substr(available_at,11,1)='T' AND substr(available_at,27,1)='Z' AND julianday(available_at) IS NOT NULL)),
  "availability_basis" TEXT NOT NULL CHECK (availability_basis IN ('verified_arrival','verified_publication','synthetic','unknown')),
  "revision_no" INTEGER NOT NULL CHECK (revision_no>=0),
  FOREIGN KEY (parent_location_id) REFERENCES market_location(market_location_id),
  UNIQUE (market_code, location_type, location_code, revision_no),
  CHECK (effective_to IS NULL OR effective_to>effective_from)
);

CREATE INDEX idx_market_location_pit ON market_location(market_code,location_type,location_code,available_at);

CREATE TRIGGER immutable_market_location_update BEFORE UPDATE ON market_location BEGIN SELECT RAISE(ABORT,'append-only: market_location'); END;

CREATE TRIGGER immutable_market_location_delete BEFORE DELETE ON market_location BEGIN SELECT RAISE(ABORT,'append-only: market_location'); END;

CREATE TABLE station_market_binding (
  "binding_id" TEXT PRIMARY KEY NOT NULL,
  "station_id" TEXT NOT NULL,
  "market_location_id" TEXT NOT NULL,
  "binding_role" TEXT NOT NULL,
  "effective_from" TEXT NOT NULL CHECK (effective_from IS NULL OR (length(effective_from)=27 AND substr(effective_from,11,1)='T' AND substr(effective_from,27,1)='Z' AND julianday(effective_from) IS NOT NULL)),
  "effective_to" TEXT CHECK (effective_to IS NULL OR (length(effective_to)=27 AND substr(effective_to,11,1)='T' AND substr(effective_to,27,1)='Z' AND julianday(effective_to) IS NOT NULL)),
  "mapping_basis" TEXT,
  "confirmed_status" TEXT NOT NULL,
  "recorded_at" TEXT NOT NULL CHECK (recorded_at IS NULL OR (length(recorded_at)=27 AND substr(recorded_at,11,1)='T' AND substr(recorded_at,27,1)='Z' AND julianday(recorded_at) IS NOT NULL)),
  "available_at" TEXT NOT NULL CHECK (available_at IS NULL OR (length(available_at)=27 AND substr(available_at,11,1)='T' AND substr(available_at,27,1)='Z' AND julianday(available_at) IS NOT NULL)),
  "availability_basis" TEXT NOT NULL CHECK (availability_basis IN ('verified_arrival','verified_publication','synthetic','unknown')),
  "revision_no" INTEGER NOT NULL CHECK (revision_no>=0),
  FOREIGN KEY (station_id) REFERENCES station(station_id),
  FOREIGN KEY (market_location_id) REFERENCES market_location(market_location_id),
  UNIQUE (station_id, binding_role, effective_from, revision_no),
  CHECK (effective_to IS NULL OR effective_to>effective_from)
);

CREATE INDEX idx_station_market_binding_pit ON station_market_binding(station_id,binding_role,effective_from,available_at);

CREATE TRIGGER immutable_station_market_binding_update BEFORE UPDATE ON station_market_binding BEGIN SELECT RAISE(ABORT,'append-only: station_market_binding'); END;

CREATE TRIGGER immutable_station_market_binding_delete BEFORE DELETE ON station_market_binding BEGIN SELECT RAISE(ABORT,'append-only: station_market_binding'); END;

CREATE TABLE weather_location (
  "weather_location_id" TEXT PRIMARY KEY NOT NULL,
  "source_id" TEXT NOT NULL,
  "location_code" TEXT NOT NULL,
  "location_name" TEXT NOT NULL,
  "location_type" TEXT NOT NULL,
  "latitude" REAL NOT NULL,
  "longitude" REAL NOT NULL,
  "altitude_m" REAL,
  "sensor_or_grid_ref" TEXT,
  "measurement_plane" TEXT NOT NULL,
  "timezone" TEXT NOT NULL,
  "status" TEXT NOT NULL,
  "available_at" TEXT NOT NULL CHECK (available_at IS NULL OR (length(available_at)=27 AND substr(available_at,11,1)='T' AND substr(available_at,27,1)='Z' AND julianday(available_at) IS NOT NULL)),
  "availability_basis" TEXT NOT NULL CHECK (availability_basis IN ('verified_arrival','verified_publication','synthetic','unknown')),
  "revision_no" INTEGER NOT NULL CHECK (revision_no>=0),
  FOREIGN KEY (source_id) REFERENCES data_source(source_id),
  UNIQUE (source_id, location_code, revision_no)
);

CREATE INDEX idx_weather_location_pit ON weather_location(source_id,location_code,available_at);

CREATE TRIGGER immutable_weather_location_update BEFORE UPDATE ON weather_location BEGIN SELECT RAISE(ABORT,'append-only: weather_location'); END;

CREATE TRIGGER immutable_weather_location_delete BEFORE DELETE ON weather_location BEGIN SELECT RAISE(ABORT,'append-only: weather_location'); END;

CREATE TABLE station_weather_binding (
  "binding_id" TEXT PRIMARY KEY NOT NULL,
  "station_id" TEXT NOT NULL,
  "weather_location_id" TEXT NOT NULL,
  "binding_role" TEXT NOT NULL,
  "distance_km" REAL,
  "selection_method" TEXT NOT NULL,
  "effective_from" TEXT NOT NULL CHECK (effective_from IS NULL OR (length(effective_from)=27 AND substr(effective_from,11,1)='T' AND substr(effective_from,27,1)='Z' AND julianday(effective_from) IS NOT NULL)),
  "effective_to" TEXT CHECK (effective_to IS NULL OR (length(effective_to)=27 AND substr(effective_to,11,1)='T' AND substr(effective_to,27,1)='Z' AND julianday(effective_to) IS NOT NULL)),
  "confirmed_status" TEXT NOT NULL,
  "recorded_at" TEXT NOT NULL CHECK (recorded_at IS NULL OR (length(recorded_at)=27 AND substr(recorded_at,11,1)='T' AND substr(recorded_at,27,1)='Z' AND julianday(recorded_at) IS NOT NULL)),
  "available_at" TEXT NOT NULL CHECK (available_at IS NULL OR (length(available_at)=27 AND substr(available_at,11,1)='T' AND substr(available_at,27,1)='Z' AND julianday(available_at) IS NOT NULL)),
  "availability_basis" TEXT NOT NULL CHECK (availability_basis IN ('verified_arrival','verified_publication','synthetic','unknown')),
  "revision_no" INTEGER NOT NULL CHECK (revision_no>=0),
  FOREIGN KEY (station_id) REFERENCES station(station_id),
  FOREIGN KEY (weather_location_id) REFERENCES weather_location(weather_location_id),
  UNIQUE (station_id, weather_location_id, binding_role, effective_from, revision_no),
  CHECK (effective_to IS NULL OR effective_to>effective_from)
);

CREATE INDEX idx_station_weather_binding_pit ON station_weather_binding(station_id,weather_location_id,binding_role,effective_from,available_at);

CREATE TRIGGER immutable_station_weather_binding_update BEFORE UPDATE ON station_weather_binding BEGIN SELECT RAISE(ABORT,'append-only: station_weather_binding'); END;

CREATE TRIGGER immutable_station_weather_binding_delete BEFORE DELETE ON station_weather_binding BEGIN SELECT RAISE(ABORT,'append-only: station_weather_binding'); END;

CREATE TABLE station_actual (
  "actual_id" TEXT PRIMARY KEY NOT NULL,
  "station_id" TEXT NOT NULL,
  "measurement_point_code" TEXT NOT NULL,
  "measurement_boundary" TEXT NOT NULL,
  "interval_start" TEXT NOT NULL CHECK (interval_start IS NULL OR (length(interval_start)=27 AND substr(interval_start,11,1)='T' AND substr(interval_start,27,1)='Z' AND julianday(interval_start) IS NOT NULL)),
  "interval_end" TEXT NOT NULL CHECK (interval_end IS NULL OR (length(interval_end)=27 AND substr(interval_end,11,1)='T' AND substr(interval_end,27,1)='Z' AND julianday(interval_end) IS NOT NULL)),
  "sampling_method" TEXT NOT NULL,
  "power_mw" REAL,
  "generated_energy_mwh" REAL,
  "export_energy_mwh" REAL,
  "available_capacity_mw" REAL,
  "source_id" TEXT NOT NULL,
  "batch_id" TEXT NOT NULL,
  "source_record_id" TEXT NOT NULL,
  "published_at" TEXT CHECK (published_at IS NULL OR (length(published_at)=27 AND substr(published_at,11,1)='T' AND substr(published_at,27,1)='Z' AND julianday(published_at) IS NOT NULL)),
  "first_seen_at" TEXT NOT NULL CHECK (first_seen_at IS NULL OR (length(first_seen_at)=27 AND substr(first_seen_at,11,1)='T' AND substr(first_seen_at,27,1)='Z' AND julianday(first_seen_at) IS NOT NULL)),
  "available_at" TEXT NOT NULL CHECK (available_at IS NULL OR (length(available_at)=27 AND substr(available_at,11,1)='T' AND substr(available_at,27,1)='Z' AND julianday(available_at) IS NOT NULL)),
  "availability_basis" TEXT NOT NULL CHECK (availability_basis IN ('verified_arrival','verified_publication','synthetic','unknown')),
  "source_version" TEXT NOT NULL,
  "revision_no" INTEGER NOT NULL CHECK (revision_no>=0),
  "quality_flag" TEXT NOT NULL,
  "raw_record_ref" TEXT,
  "created_at" TEXT NOT NULL CHECK (created_at IS NULL OR (length(created_at)=27 AND substr(created_at,11,1)='T' AND substr(created_at,27,1)='Z' AND julianday(created_at) IS NOT NULL)),
  FOREIGN KEY (station_id) REFERENCES station(station_id),
  FOREIGN KEY (source_id) REFERENCES data_source(source_id),
  FOREIGN KEY (batch_id) REFERENCES ingestion_batch(batch_id),
  FOREIGN KEY (batch_id, source_id) REFERENCES ingestion_batch(batch_id, source_id),
  UNIQUE (source_id, station_id, measurement_point_code, measurement_boundary, interval_start, interval_end, sampling_method, revision_no),
  CHECK (interval_end IS NULL OR interval_end>interval_start),
  CHECK (published_at IS NULL OR published_at<=available_at),
  CHECK (first_seen_at IS NULL OR first_seen_at<=available_at),
  CHECK (interval_end<=available_at)
);

CREATE INDEX idx_station_actual_pit ON station_actual(source_id,station_id,measurement_point_code,measurement_boundary,interval_start,interval_end,sampling_method,available_at);

CREATE TRIGGER immutable_station_actual_update BEFORE UPDATE ON station_actual BEGIN SELECT RAISE(ABORT,'append-only: station_actual'); END;

CREATE TRIGGER immutable_station_actual_delete BEFORE DELETE ON station_actual BEGIN SELECT RAISE(ABORT,'append-only: station_actual'); END;

CREATE TABLE station_forecast_snapshot (
  "forecast_snapshot_id" TEXT PRIMARY KEY NOT NULL,
  "station_id" TEXT NOT NULL,
  "measurement_boundary" TEXT NOT NULL,
  "forecast_type" TEXT NOT NULL,
  "issued_at" TEXT NOT NULL CHECK (issued_at IS NULL OR (length(issued_at)=27 AND substr(issued_at,11,1)='T' AND substr(issued_at,27,1)='Z' AND julianday(issued_at) IS NOT NULL)),
  "target_start" TEXT NOT NULL CHECK (target_start IS NULL OR (length(target_start)=27 AND substr(target_start,11,1)='T' AND substr(target_start,27,1)='Z' AND julianday(target_start) IS NOT NULL)),
  "target_end" TEXT NOT NULL CHECK (target_end IS NULL OR (length(target_end)=27 AND substr(target_end,11,1)='T' AND substr(target_end,27,1)='Z' AND julianday(target_end) IS NOT NULL)),
  "forecast_power_mw" REAL,
  "forecast_energy_mwh" REAL,
  "provider_model_name" TEXT,
  "provider_model_version" TEXT,
  "scenario_code" TEXT NOT NULL,
  "source_id" TEXT NOT NULL,
  "batch_id" TEXT NOT NULL,
  "source_record_id" TEXT NOT NULL,
  "published_at" TEXT CHECK (published_at IS NULL OR (length(published_at)=27 AND substr(published_at,11,1)='T' AND substr(published_at,27,1)='Z' AND julianday(published_at) IS NOT NULL)),
  "first_seen_at" TEXT NOT NULL CHECK (first_seen_at IS NULL OR (length(first_seen_at)=27 AND substr(first_seen_at,11,1)='T' AND substr(first_seen_at,27,1)='Z' AND julianday(first_seen_at) IS NOT NULL)),
  "available_at" TEXT NOT NULL CHECK (available_at IS NULL OR (length(available_at)=27 AND substr(available_at,11,1)='T' AND substr(available_at,27,1)='Z' AND julianday(available_at) IS NOT NULL)),
  "availability_basis" TEXT NOT NULL CHECK (availability_basis IN ('verified_arrival','verified_publication','synthetic','unknown')),
  "source_version" TEXT NOT NULL,
  "revision_no" INTEGER NOT NULL CHECK (revision_no>=0),
  "quality_flag" TEXT NOT NULL,
  "raw_record_ref" TEXT,
  "created_at" TEXT NOT NULL CHECK (created_at IS NULL OR (length(created_at)=27 AND substr(created_at,11,1)='T' AND substr(created_at,27,1)='Z' AND julianday(created_at) IS NOT NULL)),
  FOREIGN KEY (station_id) REFERENCES station(station_id),
  FOREIGN KEY (source_id) REFERENCES data_source(source_id),
  FOREIGN KEY (batch_id) REFERENCES ingestion_batch(batch_id),
  FOREIGN KEY (batch_id, source_id) REFERENCES ingestion_batch(batch_id, source_id),
  UNIQUE (source_id, station_id, measurement_boundary, forecast_type, target_start, target_end, scenario_code, issued_at, revision_no),
  CHECK (target_end IS NULL OR target_end>target_start),
  CHECK (published_at IS NULL OR published_at<=available_at),
  CHECK (first_seen_at IS NULL OR first_seen_at<=available_at),
  CHECK (issued_at IS NULL OR issued_at<=available_at)
);

CREATE INDEX idx_station_forecast_snapshot_pit ON station_forecast_snapshot(source_id,station_id,measurement_boundary,forecast_type,target_start,target_end,scenario_code,available_at);

CREATE TRIGGER immutable_station_forecast_snapshot_update BEFORE UPDATE ON station_forecast_snapshot BEGIN SELECT RAISE(ABORT,'append-only: station_forecast_snapshot'); END;

CREATE TRIGGER immutable_station_forecast_snapshot_delete BEFORE DELETE ON station_forecast_snapshot BEGIN SELECT RAISE(ABORT,'append-only: station_forecast_snapshot'); END;

CREATE TABLE weather_observation (
  "observation_id" TEXT PRIMARY KEY NOT NULL,
  "weather_location_id" TEXT NOT NULL,
  "interval_start" TEXT NOT NULL CHECK (interval_start IS NULL OR (length(interval_start)=27 AND substr(interval_start,11,1)='T' AND substr(interval_start,27,1)='Z' AND julianday(interval_start) IS NOT NULL)),
  "interval_end" TEXT NOT NULL CHECK (interval_end IS NULL OR (length(interval_end)=27 AND substr(interval_end,11,1)='T' AND substr(interval_end,27,1)='Z' AND julianday(interval_end) IS NOT NULL)),
  "sampling_method" TEXT NOT NULL,
  "ghi_wm2" REAL,
  "dni_wm2" REAL,
  "dhi_wm2" REAL,
  "poa_wm2" REAL,
  "air_temperature_c" REAL,
  "module_temperature_c" REAL,
  "relative_humidity_pct" REAL,
  "wind_speed_ms" REAL,
  "wind_direction_deg" REAL,
  "pressure_hpa" REAL,
  "cloud_cover_pct" REAL,
  "precipitation_mm" REAL,
  "calibration_version" TEXT,
  "source_id" TEXT NOT NULL,
  "batch_id" TEXT NOT NULL,
  "source_record_id" TEXT NOT NULL,
  "published_at" TEXT CHECK (published_at IS NULL OR (length(published_at)=27 AND substr(published_at,11,1)='T' AND substr(published_at,27,1)='Z' AND julianday(published_at) IS NOT NULL)),
  "first_seen_at" TEXT NOT NULL CHECK (first_seen_at IS NULL OR (length(first_seen_at)=27 AND substr(first_seen_at,11,1)='T' AND substr(first_seen_at,27,1)='Z' AND julianday(first_seen_at) IS NOT NULL)),
  "available_at" TEXT NOT NULL CHECK (available_at IS NULL OR (length(available_at)=27 AND substr(available_at,11,1)='T' AND substr(available_at,27,1)='Z' AND julianday(available_at) IS NOT NULL)),
  "availability_basis" TEXT NOT NULL CHECK (availability_basis IN ('verified_arrival','verified_publication','synthetic','unknown')),
  "source_version" TEXT NOT NULL,
  "revision_no" INTEGER NOT NULL CHECK (revision_no>=0),
  "quality_flag" TEXT NOT NULL,
  "raw_record_ref" TEXT,
  "created_at" TEXT NOT NULL CHECK (created_at IS NULL OR (length(created_at)=27 AND substr(created_at,11,1)='T' AND substr(created_at,27,1)='Z' AND julianday(created_at) IS NOT NULL)),
  FOREIGN KEY (weather_location_id) REFERENCES weather_location(weather_location_id),
  FOREIGN KEY (source_id) REFERENCES data_source(source_id),
  FOREIGN KEY (batch_id) REFERENCES ingestion_batch(batch_id),
  FOREIGN KEY (batch_id, source_id) REFERENCES ingestion_batch(batch_id, source_id),
  UNIQUE (source_id, weather_location_id, interval_start, interval_end, sampling_method, revision_no),
  CHECK (interval_end IS NULL OR interval_end>interval_start),
  CHECK (published_at IS NULL OR published_at<=available_at),
  CHECK (first_seen_at IS NULL OR first_seen_at<=available_at),
  CHECK (interval_end<=available_at)
);

CREATE INDEX idx_weather_observation_pit ON weather_observation(source_id,weather_location_id,interval_start,interval_end,sampling_method,available_at);

CREATE TRIGGER immutable_weather_observation_update BEFORE UPDATE ON weather_observation BEGIN SELECT RAISE(ABORT,'append-only: weather_observation'); END;

CREATE TRIGGER immutable_weather_observation_delete BEFORE DELETE ON weather_observation BEGIN SELECT RAISE(ABORT,'append-only: weather_observation'); END;

CREATE TABLE weather_forecast (
  "weather_forecast_id" TEXT PRIMARY KEY NOT NULL,
  "weather_location_id" TEXT NOT NULL,
  "forecast_product" TEXT NOT NULL,
  "issued_at" TEXT NOT NULL CHECK (issued_at IS NULL OR (length(issued_at)=27 AND substr(issued_at,11,1)='T' AND substr(issued_at,27,1)='Z' AND julianday(issued_at) IS NOT NULL)),
  "target_start" TEXT NOT NULL CHECK (target_start IS NULL OR (length(target_start)=27 AND substr(target_start,11,1)='T' AND substr(target_start,27,1)='Z' AND julianday(target_start) IS NOT NULL)),
  "target_end" TEXT NOT NULL CHECK (target_end IS NULL OR (length(target_end)=27 AND substr(target_end,11,1)='T' AND substr(target_end,27,1)='Z' AND julianday(target_end) IS NOT NULL)),
  "forecast_method" TEXT NOT NULL,
  "ghi_wm2" REAL,
  "dni_wm2" REAL,
  "dhi_wm2" REAL,
  "poa_wm2" REAL,
  "air_temperature_c" REAL,
  "relative_humidity_pct" REAL,
  "wind_speed_ms" REAL,
  "wind_direction_deg" REAL,
  "cloud_cover_pct" REAL,
  "low_cloud_pct" REAL,
  "mid_cloud_pct" REAL,
  "high_cloud_pct" REAL,
  "precipitation_mm" REAL,
  "source_id" TEXT NOT NULL,
  "batch_id" TEXT NOT NULL,
  "source_record_id" TEXT NOT NULL,
  "published_at" TEXT CHECK (published_at IS NULL OR (length(published_at)=27 AND substr(published_at,11,1)='T' AND substr(published_at,27,1)='Z' AND julianday(published_at) IS NOT NULL)),
  "first_seen_at" TEXT NOT NULL CHECK (first_seen_at IS NULL OR (length(first_seen_at)=27 AND substr(first_seen_at,11,1)='T' AND substr(first_seen_at,27,1)='Z' AND julianday(first_seen_at) IS NOT NULL)),
  "available_at" TEXT NOT NULL CHECK (available_at IS NULL OR (length(available_at)=27 AND substr(available_at,11,1)='T' AND substr(available_at,27,1)='Z' AND julianday(available_at) IS NOT NULL)),
  "availability_basis" TEXT NOT NULL CHECK (availability_basis IN ('verified_arrival','verified_publication','synthetic','unknown')),
  "source_version" TEXT NOT NULL,
  "revision_no" INTEGER NOT NULL CHECK (revision_no>=0),
  "quality_flag" TEXT NOT NULL,
  "raw_record_ref" TEXT,
  "created_at" TEXT NOT NULL CHECK (created_at IS NULL OR (length(created_at)=27 AND substr(created_at,11,1)='T' AND substr(created_at,27,1)='Z' AND julianday(created_at) IS NOT NULL)),
  FOREIGN KEY (weather_location_id) REFERENCES weather_location(weather_location_id),
  FOREIGN KEY (source_id) REFERENCES data_source(source_id),
  FOREIGN KEY (batch_id) REFERENCES ingestion_batch(batch_id),
  FOREIGN KEY (batch_id, source_id) REFERENCES ingestion_batch(batch_id, source_id),
  UNIQUE (source_id, weather_location_id, forecast_product, forecast_method, target_start, target_end, issued_at, revision_no),
  CHECK (target_end IS NULL OR target_end>target_start),
  CHECK (published_at IS NULL OR published_at<=available_at),
  CHECK (first_seen_at IS NULL OR first_seen_at<=available_at),
  CHECK (issued_at IS NULL OR issued_at<=available_at)
);

CREATE INDEX idx_weather_forecast_pit ON weather_forecast(source_id,weather_location_id,forecast_product,forecast_method,target_start,target_end,available_at);

CREATE TRIGGER immutable_weather_forecast_update BEFORE UPDATE ON weather_forecast BEGIN SELECT RAISE(ABORT,'append-only: weather_forecast'); END;

CREATE TRIGGER immutable_weather_forecast_delete BEFORE DELETE ON weather_forecast BEGIN SELECT RAISE(ABORT,'append-only: weather_forecast'); END;

CREATE TABLE station_operation_event (
  "event_revision_id" TEXT PRIMARY KEY NOT NULL,
  "station_id" TEXT NOT NULL,
  "event_code" TEXT NOT NULL,
  "equipment_code" TEXT,
  "event_type" TEXT NOT NULL,
  "event_status" TEXT NOT NULL,
  "effective_start" TEXT NOT NULL CHECK (effective_start IS NULL OR (length(effective_start)=27 AND substr(effective_start,11,1)='T' AND substr(effective_start,27,1)='Z' AND julianday(effective_start) IS NOT NULL)),
  "effective_end" TEXT NOT NULL CHECK (effective_end IS NULL OR (length(effective_end)=27 AND substr(effective_end,11,1)='T' AND substr(effective_end,27,1)='Z' AND julianday(effective_end) IS NOT NULL)),
  "affected_capacity_mw" REAL,
  "power_limit_mw" REAL,
  "limit_semantics" TEXT,
  "reason_code" TEXT,
  "description" TEXT,
  "source_id" TEXT NOT NULL,
  "batch_id" TEXT NOT NULL,
  "source_record_id" TEXT NOT NULL,
  "published_at" TEXT CHECK (published_at IS NULL OR (length(published_at)=27 AND substr(published_at,11,1)='T' AND substr(published_at,27,1)='Z' AND julianday(published_at) IS NOT NULL)),
  "first_seen_at" TEXT NOT NULL CHECK (first_seen_at IS NULL OR (length(first_seen_at)=27 AND substr(first_seen_at,11,1)='T' AND substr(first_seen_at,27,1)='Z' AND julianday(first_seen_at) IS NOT NULL)),
  "available_at" TEXT NOT NULL CHECK (available_at IS NULL OR (length(available_at)=27 AND substr(available_at,11,1)='T' AND substr(available_at,27,1)='Z' AND julianday(available_at) IS NOT NULL)),
  "availability_basis" TEXT NOT NULL CHECK (availability_basis IN ('verified_arrival','verified_publication','synthetic','unknown')),
  "source_version" TEXT NOT NULL,
  "revision_no" INTEGER NOT NULL CHECK (revision_no>=0),
  "quality_flag" TEXT NOT NULL,
  "raw_record_ref" TEXT,
  "created_at" TEXT NOT NULL CHECK (created_at IS NULL OR (length(created_at)=27 AND substr(created_at,11,1)='T' AND substr(created_at,27,1)='Z' AND julianday(created_at) IS NOT NULL)),
  FOREIGN KEY (station_id) REFERENCES station(station_id),
  FOREIGN KEY (source_id) REFERENCES data_source(source_id),
  FOREIGN KEY (batch_id) REFERENCES ingestion_batch(batch_id),
  FOREIGN KEY (batch_id, source_id) REFERENCES ingestion_batch(batch_id, source_id),
  UNIQUE (source_id, station_id, event_code, revision_no),
  CHECK (effective_end IS NULL OR effective_end>effective_start),
  CHECK (published_at IS NULL OR published_at<=available_at),
  CHECK (first_seen_at IS NULL OR first_seen_at<=available_at)
);

CREATE INDEX idx_station_operation_event_pit ON station_operation_event(source_id,station_id,event_code,available_at);

CREATE TRIGGER immutable_station_operation_event_update BEFORE UPDATE ON station_operation_event BEGIN SELECT RAISE(ABORT,'append-only: station_operation_event'); END;

CREATE TRIGGER immutable_station_operation_event_delete BEFORE DELETE ON station_operation_event BEGIN SELECT RAISE(ABORT,'append-only: station_operation_event'); END;

CREATE TABLE market_supply_actual (
  "supply_actual_id" TEXT PRIMARY KEY NOT NULL,
  "market_location_id" TEXT NOT NULL,
  "interval_start" TEXT NOT NULL CHECK (interval_start IS NULL OR (length(interval_start)=27 AND substr(interval_start,11,1)='T' AND substr(interval_start,27,1)='Z' AND julianday(interval_start) IS NOT NULL)),
  "interval_end" TEXT NOT NULL CHECK (interval_end IS NULL OR (length(interval_end)=27 AND substr(interval_end,11,1)='T' AND substr(interval_end,27,1)='Z' AND julianday(interval_end) IS NOT NULL)),
  "system_load_mw" REAL,
  "solar_generation_mw" REAL,
  "wind_generation_mw" REAL,
  "conventional_generation_mw" REAL,
  "import_power_mw" REAL,
  "export_power_mw" REAL,
  "pumped_storage_power_mw" REAL,
  "storage_power_mw" REAL,
  "aggregation_scope" TEXT NOT NULL,
  "source_id" TEXT NOT NULL,
  "batch_id" TEXT NOT NULL,
  "source_record_id" TEXT NOT NULL,
  "published_at" TEXT CHECK (published_at IS NULL OR (length(published_at)=27 AND substr(published_at,11,1)='T' AND substr(published_at,27,1)='Z' AND julianday(published_at) IS NOT NULL)),
  "first_seen_at" TEXT NOT NULL CHECK (first_seen_at IS NULL OR (length(first_seen_at)=27 AND substr(first_seen_at,11,1)='T' AND substr(first_seen_at,27,1)='Z' AND julianday(first_seen_at) IS NOT NULL)),
  "available_at" TEXT NOT NULL CHECK (available_at IS NULL OR (length(available_at)=27 AND substr(available_at,11,1)='T' AND substr(available_at,27,1)='Z' AND julianday(available_at) IS NOT NULL)),
  "availability_basis" TEXT NOT NULL CHECK (availability_basis IN ('verified_arrival','verified_publication','synthetic','unknown')),
  "source_version" TEXT NOT NULL,
  "revision_no" INTEGER NOT NULL CHECK (revision_no>=0),
  "quality_flag" TEXT NOT NULL,
  "raw_record_ref" TEXT,
  "created_at" TEXT NOT NULL CHECK (created_at IS NULL OR (length(created_at)=27 AND substr(created_at,11,1)='T' AND substr(created_at,27,1)='Z' AND julianday(created_at) IS NOT NULL)),
  FOREIGN KEY (market_location_id) REFERENCES market_location(market_location_id),
  FOREIGN KEY (source_id) REFERENCES data_source(source_id),
  FOREIGN KEY (batch_id) REFERENCES ingestion_batch(batch_id),
  FOREIGN KEY (batch_id, source_id) REFERENCES ingestion_batch(batch_id, source_id),
  UNIQUE (source_id, market_location_id, aggregation_scope, interval_start, interval_end, revision_no),
  CHECK (interval_end IS NULL OR interval_end>interval_start),
  CHECK (published_at IS NULL OR published_at<=available_at),
  CHECK (first_seen_at IS NULL OR first_seen_at<=available_at),
  CHECK (interval_end<=available_at)
);

CREATE INDEX idx_market_supply_actual_pit ON market_supply_actual(source_id,market_location_id,aggregation_scope,interval_start,interval_end,available_at);

CREATE TRIGGER immutable_market_supply_actual_update BEFORE UPDATE ON market_supply_actual BEGIN SELECT RAISE(ABORT,'append-only: market_supply_actual'); END;

CREATE TRIGGER immutable_market_supply_actual_delete BEFORE DELETE ON market_supply_actual BEGIN SELECT RAISE(ABORT,'append-only: market_supply_actual'); END;

CREATE TABLE market_supply_forecast (
  "supply_forecast_id" TEXT PRIMARY KEY NOT NULL,
  "market_location_id" TEXT NOT NULL,
  "product_type" TEXT NOT NULL,
  "issued_at" TEXT NOT NULL CHECK (issued_at IS NULL OR (length(issued_at)=27 AND substr(issued_at,11,1)='T' AND substr(issued_at,27,1)='Z' AND julianday(issued_at) IS NOT NULL)),
  "target_start" TEXT NOT NULL CHECK (target_start IS NULL OR (length(target_start)=27 AND substr(target_start,11,1)='T' AND substr(target_start,27,1)='Z' AND julianday(target_start) IS NOT NULL)),
  "target_end" TEXT NOT NULL CHECK (target_end IS NULL OR (length(target_end)=27 AND substr(target_end,11,1)='T' AND substr(target_end,27,1)='Z' AND julianday(target_end) IS NOT NULL)),
  "load_forecast_mw" REAL,
  "solar_forecast_mw" REAL,
  "wind_forecast_mw" REAL,
  "import_plan_mw" REAL,
  "export_plan_mw" REAL,
  "conventional_available_capacity_mw" REAL,
  "maintenance_capacity_mw" REAL,
  "pumped_storage_plan_mw" REAL,
  "storage_plan_mw" REAL,
  "aggregation_scope" TEXT NOT NULL,
  "source_id" TEXT NOT NULL,
  "batch_id" TEXT NOT NULL,
  "source_record_id" TEXT NOT NULL,
  "published_at" TEXT CHECK (published_at IS NULL OR (length(published_at)=27 AND substr(published_at,11,1)='T' AND substr(published_at,27,1)='Z' AND julianday(published_at) IS NOT NULL)),
  "first_seen_at" TEXT NOT NULL CHECK (first_seen_at IS NULL OR (length(first_seen_at)=27 AND substr(first_seen_at,11,1)='T' AND substr(first_seen_at,27,1)='Z' AND julianday(first_seen_at) IS NOT NULL)),
  "available_at" TEXT NOT NULL CHECK (available_at IS NULL OR (length(available_at)=27 AND substr(available_at,11,1)='T' AND substr(available_at,27,1)='Z' AND julianday(available_at) IS NOT NULL)),
  "availability_basis" TEXT NOT NULL CHECK (availability_basis IN ('verified_arrival','verified_publication','synthetic','unknown')),
  "source_version" TEXT NOT NULL,
  "revision_no" INTEGER NOT NULL CHECK (revision_no>=0),
  "quality_flag" TEXT NOT NULL,
  "raw_record_ref" TEXT,
  "created_at" TEXT NOT NULL CHECK (created_at IS NULL OR (length(created_at)=27 AND substr(created_at,11,1)='T' AND substr(created_at,27,1)='Z' AND julianday(created_at) IS NOT NULL)),
  FOREIGN KEY (market_location_id) REFERENCES market_location(market_location_id),
  FOREIGN KEY (source_id) REFERENCES data_source(source_id),
  FOREIGN KEY (batch_id) REFERENCES ingestion_batch(batch_id),
  FOREIGN KEY (batch_id, source_id) REFERENCES ingestion_batch(batch_id, source_id),
  UNIQUE (source_id, market_location_id, aggregation_scope, product_type, target_start, target_end, issued_at, revision_no),
  CHECK (target_end IS NULL OR target_end>target_start),
  CHECK (published_at IS NULL OR published_at<=available_at),
  CHECK (first_seen_at IS NULL OR first_seen_at<=available_at),
  CHECK (issued_at IS NULL OR issued_at<=available_at)
);

CREATE INDEX idx_market_supply_forecast_pit ON market_supply_forecast(source_id,market_location_id,aggregation_scope,product_type,target_start,target_end,available_at);

CREATE TRIGGER immutable_market_supply_forecast_update BEFORE UPDATE ON market_supply_forecast BEGIN SELECT RAISE(ABORT,'append-only: market_supply_forecast'); END;

CREATE TRIGGER immutable_market_supply_forecast_delete BEFORE DELETE ON market_supply_forecast BEGIN SELECT RAISE(ABORT,'append-only: market_supply_forecast'); END;

CREATE TABLE market_price (
  "price_id" TEXT PRIMARY KEY NOT NULL,
  "market_location_id" TEXT NOT NULL,
  "interval_start" TEXT NOT NULL CHECK (interval_start IS NULL OR (length(interval_start)=27 AND substr(interval_start,11,1)='T' AND substr(interval_start,27,1)='Z' AND julianday(interval_start) IS NOT NULL)),
  "interval_end" TEXT NOT NULL CHECK (interval_end IS NULL OR (length(interval_end)=27 AND substr(interval_end,11,1)='T' AND substr(interval_end,27,1)='Z' AND julianday(interval_end) IS NOT NULL)),
  "market_stage" TEXT NOT NULL,
  "price_type" TEXT NOT NULL,
  "price_component" TEXT NOT NULL,
  "price_yuan_mwh" REAL NOT NULL,
  "currency" TEXT NOT NULL,
  "is_final" INTEGER NOT NULL CHECK (is_final IN (0,1)),
  "source_id" TEXT NOT NULL,
  "batch_id" TEXT NOT NULL,
  "source_record_id" TEXT NOT NULL,
  "published_at" TEXT CHECK (published_at IS NULL OR (length(published_at)=27 AND substr(published_at,11,1)='T' AND substr(published_at,27,1)='Z' AND julianday(published_at) IS NOT NULL)),
  "first_seen_at" TEXT NOT NULL CHECK (first_seen_at IS NULL OR (length(first_seen_at)=27 AND substr(first_seen_at,11,1)='T' AND substr(first_seen_at,27,1)='Z' AND julianday(first_seen_at) IS NOT NULL)),
  "available_at" TEXT NOT NULL CHECK (available_at IS NULL OR (length(available_at)=27 AND substr(available_at,11,1)='T' AND substr(available_at,27,1)='Z' AND julianday(available_at) IS NOT NULL)),
  "availability_basis" TEXT NOT NULL CHECK (availability_basis IN ('verified_arrival','verified_publication','synthetic','unknown')),
  "source_version" TEXT NOT NULL,
  "revision_no" INTEGER NOT NULL CHECK (revision_no>=0),
  "quality_flag" TEXT NOT NULL,
  "raw_record_ref" TEXT,
  "created_at" TEXT NOT NULL CHECK (created_at IS NULL OR (length(created_at)=27 AND substr(created_at,11,1)='T' AND substr(created_at,27,1)='Z' AND julianday(created_at) IS NOT NULL)),
  FOREIGN KEY (market_location_id) REFERENCES market_location(market_location_id),
  FOREIGN KEY (source_id) REFERENCES data_source(source_id),
  FOREIGN KEY (batch_id) REFERENCES ingestion_batch(batch_id),
  FOREIGN KEY (batch_id, source_id) REFERENCES ingestion_batch(batch_id, source_id),
  UNIQUE (source_id, market_location_id, interval_start, interval_end, market_stage, price_type, price_component, revision_no),
  CHECK (interval_end IS NULL OR interval_end>interval_start),
  CHECK (published_at IS NULL OR published_at<=available_at),
  CHECK (first_seen_at IS NULL OR first_seen_at<=available_at)
);

CREATE INDEX idx_market_price_pit ON market_price(source_id,market_location_id,interval_start,interval_end,market_stage,price_type,price_component,available_at);

CREATE TRIGGER immutable_market_price_update BEFORE UPDATE ON market_price BEGIN SELECT RAISE(ABORT,'append-only: market_price'); END;

CREATE TRIGGER immutable_market_price_delete BEFORE DELETE ON market_price BEGIN SELECT RAISE(ABORT,'append-only: market_price'); END;

CREATE TABLE market_operation_event (
  "event_revision_id" TEXT PRIMARY KEY NOT NULL,
  "market_location_id" TEXT NOT NULL,
  "event_code" TEXT NOT NULL,
  "asset_code" TEXT,
  "event_type" TEXT NOT NULL,
  "effective_start" TEXT NOT NULL CHECK (effective_start IS NULL OR (length(effective_start)=27 AND substr(effective_start,11,1)='T' AND substr(effective_start,27,1)='Z' AND julianday(effective_start) IS NOT NULL)),
  "effective_end" TEXT NOT NULL CHECK (effective_end IS NULL OR (length(effective_end)=27 AND substr(effective_end,11,1)='T' AND substr(effective_end,27,1)='Z' AND julianday(effective_end) IS NOT NULL)),
  "affected_capacity_mw" REAL,
  "constraint_value" REAL,
  "constraint_unit" TEXT,
  "event_status" TEXT NOT NULL,
  "description" TEXT,
  "source_id" TEXT NOT NULL,
  "batch_id" TEXT NOT NULL,
  "source_record_id" TEXT NOT NULL,
  "published_at" TEXT CHECK (published_at IS NULL OR (length(published_at)=27 AND substr(published_at,11,1)='T' AND substr(published_at,27,1)='Z' AND julianday(published_at) IS NOT NULL)),
  "first_seen_at" TEXT NOT NULL CHECK (first_seen_at IS NULL OR (length(first_seen_at)=27 AND substr(first_seen_at,11,1)='T' AND substr(first_seen_at,27,1)='Z' AND julianday(first_seen_at) IS NOT NULL)),
  "available_at" TEXT NOT NULL CHECK (available_at IS NULL OR (length(available_at)=27 AND substr(available_at,11,1)='T' AND substr(available_at,27,1)='Z' AND julianday(available_at) IS NOT NULL)),
  "availability_basis" TEXT NOT NULL CHECK (availability_basis IN ('verified_arrival','verified_publication','synthetic','unknown')),
  "source_version" TEXT NOT NULL,
  "revision_no" INTEGER NOT NULL CHECK (revision_no>=0),
  "quality_flag" TEXT NOT NULL,
  "raw_record_ref" TEXT,
  "created_at" TEXT NOT NULL CHECK (created_at IS NULL OR (length(created_at)=27 AND substr(created_at,11,1)='T' AND substr(created_at,27,1)='Z' AND julianday(created_at) IS NOT NULL)),
  FOREIGN KEY (market_location_id) REFERENCES market_location(market_location_id),
  FOREIGN KEY (source_id) REFERENCES data_source(source_id),
  FOREIGN KEY (batch_id) REFERENCES ingestion_batch(batch_id),
  FOREIGN KEY (batch_id, source_id) REFERENCES ingestion_batch(batch_id, source_id),
  UNIQUE (source_id, market_location_id, event_code, revision_no),
  CHECK (effective_end IS NULL OR effective_end>effective_start),
  CHECK (published_at IS NULL OR published_at<=available_at),
  CHECK (first_seen_at IS NULL OR first_seen_at<=available_at)
);

CREATE INDEX idx_market_operation_event_pit ON market_operation_event(source_id,market_location_id,event_code,available_at);

CREATE TRIGGER immutable_market_operation_event_update BEFORE UPDATE ON market_operation_event BEGIN SELECT RAISE(ABORT,'append-only: market_operation_event'); END;

CREATE TRIGGER immutable_market_operation_event_delete BEFORE DELETE ON market_operation_event BEGIN SELECT RAISE(ABORT,'append-only: market_operation_event'); END;

CREATE TABLE weather_image (
  "image_id" TEXT PRIMARY KEY NOT NULL,
  "weather_location_id" TEXT NOT NULL,
  "image_type" TEXT NOT NULL,
  "captured_at" TEXT NOT NULL CHECK (captured_at IS NULL OR (length(captured_at)=27 AND substr(captured_at,11,1)='T' AND substr(captured_at,27,1)='Z' AND julianday(captured_at) IS NOT NULL)),
  "object_uri" TEXT NOT NULL,
  "file_hash" TEXT NOT NULL,
  "image_width" INTEGER NOT NULL,
  "image_height" INTEGER NOT NULL,
  "calibration_version" TEXT,
  "source_id" TEXT NOT NULL,
  "batch_id" TEXT NOT NULL,
  "source_record_id" TEXT NOT NULL,
  "published_at" TEXT CHECK (published_at IS NULL OR (length(published_at)=27 AND substr(published_at,11,1)='T' AND substr(published_at,27,1)='Z' AND julianday(published_at) IS NOT NULL)),
  "first_seen_at" TEXT NOT NULL CHECK (first_seen_at IS NULL OR (length(first_seen_at)=27 AND substr(first_seen_at,11,1)='T' AND substr(first_seen_at,27,1)='Z' AND julianday(first_seen_at) IS NOT NULL)),
  "available_at" TEXT NOT NULL CHECK (available_at IS NULL OR (length(available_at)=27 AND substr(available_at,11,1)='T' AND substr(available_at,27,1)='Z' AND julianday(available_at) IS NOT NULL)),
  "availability_basis" TEXT NOT NULL CHECK (availability_basis IN ('verified_arrival','verified_publication','synthetic','unknown')),
  "source_version" TEXT NOT NULL,
  "revision_no" INTEGER NOT NULL CHECK (revision_no>=0),
  "quality_flag" TEXT NOT NULL,
  "raw_record_ref" TEXT,
  "created_at" TEXT NOT NULL CHECK (created_at IS NULL OR (length(created_at)=27 AND substr(created_at,11,1)='T' AND substr(created_at,27,1)='Z' AND julianday(created_at) IS NOT NULL)),
  FOREIGN KEY (weather_location_id) REFERENCES weather_location(weather_location_id),
  FOREIGN KEY (source_id) REFERENCES data_source(source_id),
  FOREIGN KEY (batch_id) REFERENCES ingestion_batch(batch_id),
  FOREIGN KEY (batch_id, source_id) REFERENCES ingestion_batch(batch_id, source_id),
  UNIQUE (source_id, weather_location_id, image_type, captured_at, revision_no),
  CHECK (published_at IS NULL OR published_at<=available_at),
  CHECK (first_seen_at IS NULL OR first_seen_at<=available_at)
);

CREATE INDEX idx_weather_image_pit ON weather_image(source_id,weather_location_id,image_type,captured_at,available_at);

CREATE TRIGGER immutable_weather_image_update BEFORE UPDATE ON weather_image BEGIN SELECT RAISE(ABORT,'append-only: weather_image'); END;

CREATE TRIGGER immutable_weather_image_delete BEFORE DELETE ON weather_image BEGIN SELECT RAISE(ABORT,'append-only: weather_image'); END;

CREATE TABLE rule_version (
  "rule_version_id" TEXT PRIMARY KEY NOT NULL,
  "market_code" TEXT NOT NULL,
  "rule_code" TEXT NOT NULL,
  "title" TEXT NOT NULL,
  "version" TEXT NOT NULL,
  "effective_from" TEXT NOT NULL CHECK (effective_from IS NULL OR (length(effective_from)=27 AND substr(effective_from,11,1)='T' AND substr(effective_from,27,1)='Z' AND julianday(effective_from) IS NOT NULL)),
  "effective_to" TEXT CHECK (effective_to IS NULL OR (length(effective_to)=27 AND substr(effective_to,11,1)='T' AND substr(effective_to,27,1)='Z' AND julianday(effective_to) IS NOT NULL)),
  "published_at" TEXT CHECK (published_at IS NULL OR (length(published_at)=27 AND substr(published_at,11,1)='T' AND substr(published_at,27,1)='Z' AND julianday(published_at) IS NOT NULL)),
  "available_at" TEXT NOT NULL CHECK (available_at IS NULL OR (length(available_at)=27 AND substr(available_at,11,1)='T' AND substr(available_at,27,1)='Z' AND julianday(available_at) IS NOT NULL)),
  "availability_basis" TEXT NOT NULL CHECK (availability_basis IN ('verified_arrival','verified_publication','synthetic','unknown')),
  "source_id" TEXT NOT NULL,
  "document_uri" TEXT NOT NULL,
  "content_hash" TEXT NOT NULL,
  "parameters_json" TEXT NOT NULL CHECK (parameters_json IS NULL OR json_valid(parameters_json)),
  "review_status" TEXT NOT NULL,
  "revision_no" INTEGER NOT NULL CHECK (revision_no>=0),
  FOREIGN KEY (source_id) REFERENCES data_source(source_id),
  UNIQUE (market_code, rule_code, effective_from, revision_no),
  CHECK (effective_to IS NULL OR effective_to>effective_from),
  CHECK (published_at IS NULL OR published_at<=available_at)
);

CREATE INDEX idx_rule_version_pit ON rule_version(market_code,rule_code,effective_from,available_at);

CREATE TRIGGER immutable_rule_version_update BEFORE UPDATE ON rule_version BEGIN SELECT RAISE(ABORT,'append-only: rule_version'); END;

CREATE TRIGGER immutable_rule_version_delete BEFORE DELETE ON rule_version BEGIN SELECT RAISE(ABORT,'append-only: rule_version'); END;

CREATE TABLE calendar_day (
  "calendar_id" TEXT PRIMARY KEY NOT NULL,
  "market_code" TEXT NOT NULL,
  "calendar_date" TEXT NOT NULL,
  "day_type" TEXT NOT NULL,
  "calendar_version" TEXT NOT NULL,
  "source_id" TEXT NOT NULL,
  "published_at" TEXT CHECK (published_at IS NULL OR (length(published_at)=27 AND substr(published_at,11,1)='T' AND substr(published_at,27,1)='Z' AND julianday(published_at) IS NOT NULL)),
  "available_at" TEXT NOT NULL CHECK (available_at IS NULL OR (length(available_at)=27 AND substr(available_at,11,1)='T' AND substr(available_at,27,1)='Z' AND julianday(available_at) IS NOT NULL)),
  "availability_basis" TEXT NOT NULL CHECK (availability_basis IN ('verified_arrival','verified_publication','synthetic','unknown')),
  "revision_no" INTEGER NOT NULL CHECK (revision_no>=0),
  FOREIGN KEY (source_id) REFERENCES data_source(source_id),
  UNIQUE (market_code, calendar_date, revision_no),
  CHECK (published_at IS NULL OR published_at<=available_at)
);

CREATE INDEX idx_calendar_day_pit ON calendar_day(market_code,calendar_date,available_at);

CREATE TRIGGER immutable_calendar_day_update BEFORE UPDATE ON calendar_day BEGIN SELECT RAISE(ABORT,'append-only: calendar_day'); END;

CREATE TRIGGER immutable_calendar_day_delete BEFORE DELETE ON calendar_day BEGIN SELECT RAISE(ABORT,'append-only: calendar_day'); END;

CREATE TABLE feature_snapshot (
  "snapshot_id" TEXT PRIMARY KEY NOT NULL,
  "task" TEXT NOT NULL,
  "station_id" TEXT NOT NULL,
  "target_start" TEXT NOT NULL CHECK (target_start IS NULL OR (length(target_start)=27 AND substr(target_start,11,1)='T' AND substr(target_start,27,1)='Z' AND julianday(target_start) IS NOT NULL)),
  "target_end" TEXT NOT NULL CHECK (target_end IS NULL OR (length(target_end)=27 AND substr(target_end,11,1)='T' AND substr(target_end,27,1)='Z' AND julianday(target_end) IS NOT NULL)),
  "cutoff_at" TEXT NOT NULL CHECK (cutoff_at IS NULL OR (length(cutoff_at)=27 AND substr(cutoff_at,11,1)='T' AND substr(cutoff_at,27,1)='Z' AND julianday(cutoff_at) IS NOT NULL)),
  "created_at" TEXT NOT NULL CHECK (created_at IS NULL OR (length(created_at)=27 AND substr(created_at,11,1)='T' AND substr(created_at,27,1)='Z' AND julianday(created_at) IS NOT NULL)),
  "feature_version" TEXT NOT NULL,
  "source_mode" TEXT NOT NULL CHECK (source_mode IN ('synthetic','production')),
  "payload_json" TEXT NOT NULL CHECK (payload_json IS NULL OR json_valid(payload_json)),
  "content_hash" TEXT NOT NULL,
  FOREIGN KEY (station_id) REFERENCES station(station_id),
  CHECK (target_end IS NULL OR target_end>target_start)
);

CREATE TRIGGER immutable_feature_snapshot_update BEFORE UPDATE ON feature_snapshot BEGIN SELECT RAISE(ABORT,'append-only: feature_snapshot'); END;

CREATE TRIGGER immutable_feature_snapshot_delete BEFORE DELETE ON feature_snapshot BEGIN SELECT RAISE(ABORT,'append-only: feature_snapshot'); END;

CREATE TABLE feature_input (
  "input_id" TEXT PRIMARY KEY NOT NULL,
  "snapshot_id" TEXT NOT NULL,
  "table_name" TEXT NOT NULL,
  "record_id" TEXT NOT NULL,
  "available_at" TEXT NOT NULL CHECK (available_at IS NULL OR (length(available_at)=27 AND substr(available_at,11,1)='T' AND substr(available_at,27,1)='Z' AND julianday(available_at) IS NOT NULL)),
  "record_hash" TEXT NOT NULL,
  "payload_json" TEXT NOT NULL CHECK (payload_json IS NULL OR json_valid(payload_json)),
  FOREIGN KEY (snapshot_id) REFERENCES feature_snapshot(snapshot_id),
  UNIQUE (snapshot_id,table_name,record_id)
);

CREATE INDEX idx_feature_input_pit ON feature_input(input_id,available_at);

CREATE TRIGGER immutable_feature_input_update BEFORE UPDATE ON feature_input BEGIN SELECT RAISE(ABORT,'append-only: feature_input'); END;

CREATE TRIGGER immutable_feature_input_delete BEFORE DELETE ON feature_input BEGIN SELECT RAISE(ABORT,'append-only: feature_input'); END;

CREATE TABLE model_version (
  "model_version_id" TEXT PRIMARY KEY NOT NULL,
  "model_name" TEXT NOT NULL,
  "version" TEXT NOT NULL,
  "task" TEXT NOT NULL,
  "artifact_uri" TEXT,
  "artifact_hash" TEXT,
  "training_start" TEXT CHECK (training_start IS NULL OR (length(training_start)=27 AND substr(training_start,11,1)='T' AND substr(training_start,27,1)='Z' AND julianday(training_start) IS NOT NULL)),
  "training_end" TEXT CHECK (training_end IS NULL OR (length(training_end)=27 AND substr(training_end,11,1)='T' AND substr(training_end,27,1)='Z' AND julianday(training_end) IS NOT NULL)),
  "trained_at" TEXT CHECK (trained_at IS NULL OR (length(trained_at)=27 AND substr(trained_at,11,1)='T' AND substr(trained_at,27,1)='Z' AND julianday(trained_at) IS NOT NULL)),
  "feature_version" TEXT NOT NULL,
  "label_version" TEXT NOT NULL,
  "parameters_json" TEXT NOT NULL CHECK (parameters_json IS NULL OR json_valid(parameters_json)),
  "metrics_json" TEXT NOT NULL CHECK (metrics_json IS NULL OR json_valid(metrics_json)),
  "status" TEXT NOT NULL,
  "source_mode" TEXT NOT NULL CHECK (source_mode IN ('synthetic','production')),
  "created_at" TEXT NOT NULL CHECK (created_at IS NULL OR (length(created_at)=27 AND substr(created_at,11,1)='T' AND substr(created_at,27,1)='Z' AND julianday(created_at) IS NOT NULL)),
  UNIQUE (model_name,version,task)
);

CREATE TRIGGER immutable_model_version_update BEFORE UPDATE ON model_version BEGIN SELECT RAISE(ABORT,'append-only: model_version'); END;

CREATE TRIGGER immutable_model_version_delete BEFORE DELETE ON model_version BEGIN SELECT RAISE(ABORT,'append-only: model_version'); END;

CREATE TABLE prediction_run (
  "run_id" TEXT PRIMARY KEY NOT NULL,
  "model_version_id" TEXT NOT NULL,
  "snapshot_id" TEXT NOT NULL,
  "task" TEXT NOT NULL,
  "station_id" TEXT NOT NULL,
  "market_location_id" TEXT,
  "cutoff_at" TEXT NOT NULL CHECK (cutoff_at IS NULL OR (length(cutoff_at)=27 AND substr(cutoff_at,11,1)='T' AND substr(cutoff_at,27,1)='Z' AND julianday(cutoff_at) IS NOT NULL)),
  "issued_at" TEXT NOT NULL CHECK (issued_at IS NULL OR (length(issued_at)=27 AND substr(issued_at,11,1)='T' AND substr(issued_at,27,1)='Z' AND julianday(issued_at) IS NOT NULL)),
  "available_at" TEXT NOT NULL CHECK (available_at IS NULL OR (length(available_at)=27 AND substr(available_at,11,1)='T' AND substr(available_at,27,1)='Z' AND julianday(available_at) IS NOT NULL)),
  "target_start" TEXT NOT NULL CHECK (target_start IS NULL OR (length(target_start)=27 AND substr(target_start,11,1)='T' AND substr(target_start,27,1)='Z' AND julianday(target_start) IS NOT NULL)),
  "target_end" TEXT NOT NULL CHECK (target_end IS NULL OR (length(target_end)=27 AND substr(target_end,11,1)='T' AND substr(target_end,27,1)='Z' AND julianday(target_end) IS NOT NULL)),
  "baseline_run_id" TEXT,
  "status" TEXT NOT NULL,
  "source_mode" TEXT NOT NULL CHECK (source_mode IN ('synthetic','production')),
  "created_at" TEXT NOT NULL CHECK (created_at IS NULL OR (length(created_at)=27 AND substr(created_at,11,1)='T' AND substr(created_at,27,1)='Z' AND julianday(created_at) IS NOT NULL)),
  FOREIGN KEY (model_version_id) REFERENCES model_version(model_version_id),
  FOREIGN KEY (snapshot_id) REFERENCES feature_snapshot(snapshot_id),
  FOREIGN KEY (station_id) REFERENCES station(station_id),
  FOREIGN KEY (market_location_id) REFERENCES market_location(market_location_id),
  FOREIGN KEY (baseline_run_id) REFERENCES prediction_run(run_id),
  CHECK (target_end IS NULL OR target_end>target_start),
  CHECK (issued_at IS NULL OR issued_at<=available_at),
  CHECK (cutoff_at<=issued_at AND issued_at<=available_at)
);

CREATE INDEX idx_prediction_run_pit ON prediction_run(run_id,available_at);

CREATE TRIGGER immutable_prediction_run_update BEFORE UPDATE ON prediction_run BEGIN SELECT RAISE(ABORT,'append-only: prediction_run'); END;

CREATE TRIGGER immutable_prediction_run_delete BEFORE DELETE ON prediction_run BEGIN SELECT RAISE(ABORT,'append-only: prediction_run'); END;

CREATE TABLE prediction_value (
  "prediction_id" TEXT PRIMARY KEY NOT NULL,
  "run_id" TEXT NOT NULL,
  "target_start" TEXT NOT NULL CHECK (target_start IS NULL OR (length(target_start)=27 AND substr(target_start,11,1)='T' AND substr(target_start,27,1)='Z' AND julianday(target_start) IS NOT NULL)),
  "target_end" TEXT NOT NULL CHECK (target_end IS NULL OR (length(target_end)=27 AND substr(target_end,11,1)='T' AND substr(target_end,27,1)='Z' AND julianday(target_end) IS NOT NULL)),
  "value" REAL NOT NULL,
  "lower_value" REAL,
  "upper_value" REAL,
  "unit" TEXT NOT NULL,
  "quality_flag" TEXT NOT NULL,
  FOREIGN KEY (run_id) REFERENCES prediction_run(run_id),
  CHECK (target_end IS NULL OR target_end>target_start),
  UNIQUE (run_id,target_start,target_end),
  CHECK (lower_value IS NULL OR lower_value<=value),
  CHECK (upper_value IS NULL OR upper_value>=value),
  CHECK (unit IN ('MW','yuan/MWh','direction','MWh'))
);

CREATE TRIGGER immutable_prediction_value_update BEFORE UPDATE ON prediction_value BEGIN SELECT RAISE(ABORT,'append-only: prediction_value'); END;

CREATE TRIGGER immutable_prediction_value_delete BEFORE DELETE ON prediction_value BEGIN SELECT RAISE(ABORT,'append-only: prediction_value'); END;

CREATE TABLE evaluation_run (
  "evaluation_id" TEXT PRIMARY KEY NOT NULL,
  "run_id" TEXT NOT NULL,
  "label_cutoff_at" TEXT NOT NULL CHECK (label_cutoff_at IS NULL OR (length(label_cutoff_at)=27 AND substr(label_cutoff_at,11,1)='T' AND substr(label_cutoff_at,27,1)='Z' AND julianday(label_cutoff_at) IS NOT NULL)),
  "measurement_boundary" TEXT,
  "price_type" TEXT,
  "price_component" TEXT,
  "scorer_version" TEXT NOT NULL,
  "sample_count" INTEGER NOT NULL,
  "status" TEXT NOT NULL,
  "source_mode" TEXT NOT NULL CHECK (source_mode IN ('synthetic','production')),
  "created_at" TEXT NOT NULL CHECK (created_at IS NULL OR (length(created_at)=27 AND substr(created_at,11,1)='T' AND substr(created_at,27,1)='Z' AND julianday(created_at) IS NOT NULL)),
  FOREIGN KEY (run_id) REFERENCES prediction_run(run_id)
);

CREATE TRIGGER immutable_evaluation_run_update BEFORE UPDATE ON evaluation_run BEGIN SELECT RAISE(ABORT,'append-only: evaluation_run'); END;

CREATE TRIGGER immutable_evaluation_run_delete BEFORE DELETE ON evaluation_run BEGIN SELECT RAISE(ABORT,'append-only: evaluation_run'); END;

CREATE TABLE evaluation_metric (
  "metric_id" TEXT PRIMARY KEY NOT NULL,
  "evaluation_id" TEXT NOT NULL,
  "metric_name" TEXT NOT NULL,
  "metric_value" REAL NOT NULL,
  "unit" TEXT NOT NULL,
  "sample_count" INTEGER NOT NULL,
  FOREIGN KEY (evaluation_id) REFERENCES evaluation_run(evaluation_id),
  UNIQUE (evaluation_id,metric_name)
);

CREATE TRIGGER immutable_evaluation_metric_update BEFORE UPDATE ON evaluation_metric BEGIN SELECT RAISE(ABORT,'append-only: evaluation_metric'); END;

CREATE TRIGGER immutable_evaluation_metric_delete BEFORE DELETE ON evaluation_metric BEGIN SELECT RAISE(ABORT,'append-only: evaluation_metric'); END;

CREATE TABLE revenue_run (
  "revenue_run_id" TEXT PRIMARY KEY NOT NULL,
  "station_id" TEXT NOT NULL,
  "rule_version_id" TEXT NOT NULL,
  "snapshot_id" TEXT NOT NULL,
  "period_start" TEXT NOT NULL CHECK (period_start IS NULL OR (length(period_start)=27 AND substr(period_start,11,1)='T' AND substr(period_start,27,1)='Z' AND julianday(period_start) IS NOT NULL)),
  "period_end" TEXT NOT NULL CHECK (period_end IS NULL OR (length(period_end)=27 AND substr(period_end,11,1)='T' AND substr(period_end,27,1)='Z' AND julianday(period_end) IS NOT NULL)),
  "scenario_name" TEXT NOT NULL,
  "status" TEXT NOT NULL,
  "source_mode" TEXT NOT NULL CHECK (source_mode IN ('synthetic','production')),
  "created_at" TEXT NOT NULL CHECK (created_at IS NULL OR (length(created_at)=27 AND substr(created_at,11,1)='T' AND substr(created_at,27,1)='Z' AND julianday(created_at) IS NOT NULL)),
  FOREIGN KEY (station_id) REFERENCES station(station_id),
  FOREIGN KEY (rule_version_id) REFERENCES rule_version(rule_version_id),
  FOREIGN KEY (snapshot_id) REFERENCES feature_snapshot(snapshot_id),
  CHECK (period_end IS NULL OR period_end>period_start)
);

CREATE TRIGGER immutable_revenue_run_update BEFORE UPDATE ON revenue_run BEGIN SELECT RAISE(ABORT,'append-only: revenue_run'); END;

CREATE TRIGGER immutable_revenue_run_delete BEFORE DELETE ON revenue_run BEGIN SELECT RAISE(ABORT,'append-only: revenue_run'); END;

CREATE TABLE revenue_item (
  "revenue_item_id" TEXT PRIMARY KEY NOT NULL,
  "revenue_run_id" TEXT NOT NULL,
  "interval_start" TEXT NOT NULL CHECK (interval_start IS NULL OR (length(interval_start)=27 AND substr(interval_start,11,1)='T' AND substr(interval_start,27,1)='Z' AND julianday(interval_start) IS NOT NULL)),
  "interval_end" TEXT NOT NULL CHECK (interval_end IS NULL OR (length(interval_end)=27 AND substr(interval_end,11,1)='T' AND substr(interval_end,27,1)='Z' AND julianday(interval_end) IS NOT NULL)),
  "component" TEXT NOT NULL,
  "energy_mwh" REAL NOT NULL,
  "price_yuan_mwh" REAL NOT NULL,
  "amount_yuan" REAL NOT NULL,
  "calculation_json" TEXT NOT NULL CHECK (calculation_json IS NULL OR json_valid(calculation_json)),
  FOREIGN KEY (revenue_run_id) REFERENCES revenue_run(revenue_run_id),
  CHECK (interval_end IS NULL OR interval_end>interval_start)
);

CREATE TRIGGER immutable_revenue_item_update BEFORE UPDATE ON revenue_item BEGIN SELECT RAISE(ABORT,'append-only: revenue_item'); END;

CREATE TRIGGER immutable_revenue_item_delete BEFORE DELETE ON revenue_item BEGIN SELECT RAISE(ABORT,'append-only: revenue_item'); END;

CREATE TABLE agent_run (
  "agent_run_id" TEXT PRIMARY KEY NOT NULL,
  "station_id" TEXT NOT NULL,
  "snapshot_id" TEXT NOT NULL,
  "model_name" TEXT NOT NULL,
  "prompt_version" TEXT NOT NULL,
  "question" TEXT NOT NULL,
  "status" TEXT NOT NULL,
  "started_at" TEXT NOT NULL CHECK (started_at IS NULL OR (length(started_at)=27 AND substr(started_at,11,1)='T' AND substr(started_at,27,1)='Z' AND julianday(started_at) IS NOT NULL)),
  "finished_at" TEXT CHECK (finished_at IS NULL OR (length(finished_at)=27 AND substr(finished_at,11,1)='T' AND substr(finished_at,27,1)='Z' AND julianday(finished_at) IS NOT NULL)),
  "source_mode" TEXT NOT NULL CHECK (source_mode IN ('synthetic','production')),
  FOREIGN KEY (station_id) REFERENCES station(station_id),
  FOREIGN KEY (snapshot_id) REFERENCES feature_snapshot(snapshot_id)
);

CREATE TRIGGER immutable_agent_run_update BEFORE UPDATE ON agent_run BEGIN SELECT RAISE(ABORT,'append-only: agent_run'); END;

CREATE TRIGGER immutable_agent_run_delete BEFORE DELETE ON agent_run BEGIN SELECT RAISE(ABORT,'append-only: agent_run'); END;

CREATE TABLE agent_tool_call (
  "tool_call_id" TEXT PRIMARY KEY NOT NULL,
  "agent_run_id" TEXT NOT NULL,
  "tool_name" TEXT NOT NULL,
  "tool_version" TEXT NOT NULL,
  "input_json" TEXT NOT NULL CHECK (input_json IS NULL OR json_valid(input_json)),
  "output_json" TEXT NOT NULL CHECK (output_json IS NULL OR json_valid(output_json)),
  "status" TEXT NOT NULL,
  "started_at" TEXT NOT NULL CHECK (started_at IS NULL OR (length(started_at)=27 AND substr(started_at,11,1)='T' AND substr(started_at,27,1)='Z' AND julianday(started_at) IS NOT NULL)),
  "finished_at" TEXT CHECK (finished_at IS NULL OR (length(finished_at)=27 AND substr(finished_at,11,1)='T' AND substr(finished_at,27,1)='Z' AND julianday(finished_at) IS NOT NULL)),
  FOREIGN KEY (agent_run_id) REFERENCES agent_run(agent_run_id)
);

CREATE TRIGGER immutable_agent_tool_call_update BEFORE UPDATE ON agent_tool_call BEGIN SELECT RAISE(ABORT,'append-only: agent_tool_call'); END;

CREATE TRIGGER immutable_agent_tool_call_delete BEFORE DELETE ON agent_tool_call BEGIN SELECT RAISE(ABORT,'append-only: agent_tool_call'); END;

CREATE TABLE review_feedback (
  "feedback_id" TEXT PRIMARY KEY NOT NULL,
  "prediction_id" TEXT,
  "agent_run_id" TEXT,
  "reviewer_id" TEXT NOT NULL,
  "feedback_type" TEXT NOT NULL,
  "reason" TEXT NOT NULL,
  "training_eligible" INTEGER NOT NULL CHECK (training_eligible IN (0,1)),
  "status" TEXT NOT NULL,
  "created_at" TEXT NOT NULL CHECK (created_at IS NULL OR (length(created_at)=27 AND substr(created_at,11,1)='T' AND substr(created_at,27,1)='Z' AND julianday(created_at) IS NOT NULL)),
  FOREIGN KEY (prediction_id) REFERENCES prediction_value(prediction_id),
  FOREIGN KEY (agent_run_id) REFERENCES agent_run(agent_run_id),
  CHECK (prediction_id IS NOT NULL OR agent_run_id IS NOT NULL)
);

CREATE TRIGGER immutable_review_feedback_update BEFORE UPDATE ON review_feedback BEGIN SELECT RAISE(ABORT,'append-only: review_feedback'); END;

CREATE TRIGGER immutable_review_feedback_delete BEFORE DELETE ON review_feedback BEGIN SELECT RAISE(ABORT,'append-only: review_feedback'); END;

CREATE TABLE iteration_candidate (
  "candidate_id" TEXT PRIMARY KEY NOT NULL,
  "base_model_version_id" TEXT NOT NULL,
  "candidate_model_version_id" TEXT,
  "feedback_ids_json" TEXT NOT NULL CHECK (feedback_ids_json IS NULL OR json_valid(feedback_ids_json)),
  "hypothesis" TEXT NOT NULL,
  "evaluation_id" TEXT,
  "status" TEXT NOT NULL,
  "created_at" TEXT NOT NULL CHECK (created_at IS NULL OR (length(created_at)=27 AND substr(created_at,11,1)='T' AND substr(created_at,27,1)='Z' AND julianday(created_at) IS NOT NULL)),
  FOREIGN KEY (base_model_version_id) REFERENCES model_version(model_version_id),
  FOREIGN KEY (candidate_model_version_id) REFERENCES model_version(model_version_id),
  FOREIGN KEY (evaluation_id) REFERENCES evaluation_run(evaluation_id)
);

CREATE TRIGGER immutable_iteration_candidate_update BEFORE UPDATE ON iteration_candidate BEGIN SELECT RAISE(ABORT,'append-only: iteration_candidate'); END;

CREATE TRIGGER immutable_iteration_candidate_delete BEFORE DELETE ON iteration_candidate BEGIN SELECT RAISE(ABORT,'append-only: iteration_candidate'); END;

CREATE TABLE approval_decision (
  "decision_id" TEXT PRIMARY KEY NOT NULL,
  "candidate_id" TEXT NOT NULL,
  "reviewer_id" TEXT NOT NULL,
  "decision" TEXT NOT NULL,
  "reason" TEXT NOT NULL,
  "created_at" TEXT NOT NULL CHECK (created_at IS NULL OR (length(created_at)=27 AND substr(created_at,11,1)='T' AND substr(created_at,27,1)='Z' AND julianday(created_at) IS NOT NULL)),
  FOREIGN KEY (candidate_id) REFERENCES iteration_candidate(candidate_id)
);

CREATE TRIGGER immutable_approval_decision_update BEFORE UPDATE ON approval_decision BEGIN SELECT RAISE(ABORT,'append-only: approval_decision'); END;

CREATE TRIGGER immutable_approval_decision_delete BEFORE DELETE ON approval_decision BEGIN SELECT RAISE(ABORT,'append-only: approval_decision'); END;

CREATE TRIGGER prediction_snapshot_contract BEFORE INSERT ON prediction_run BEGIN
 SELECT CASE WHEN NOT EXISTS (SELECT 1 FROM feature_snapshot f JOIN model_version m ON m.model_version_id=NEW.model_version_id WHERE f.snapshot_id=NEW.snapshot_id AND f.cutoff_at=NEW.cutoff_at AND f.task=NEW.task AND m.task=NEW.task AND f.station_id=NEW.station_id AND f.source_mode=NEW.source_mode AND m.source_mode=NEW.source_mode AND f.target_start=NEW.target_start AND f.target_end=NEW.target_end) THEN RAISE(ABORT,'prediction snapshot mismatch') END;
END;

CREATE TRIGGER prediction_interval_contract BEFORE INSERT ON prediction_value BEGIN
 SELECT CASE WHEN NOT EXISTS (SELECT 1 FROM prediction_run r WHERE r.run_id=NEW.run_id AND NEW.target_start>=r.target_start AND NEW.target_end<=r.target_end) THEN RAISE(ABORT,'prediction interval outside run') END;
END;

CREATE TRIGGER feature_cutoff_contract BEFORE INSERT ON feature_input BEGIN
 SELECT CASE WHEN NOT EXISTS (SELECT 1 FROM feature_snapshot f WHERE f.snapshot_id=NEW.snapshot_id AND NEW.available_at<=f.cutoff_at) THEN RAISE(ABORT,'feature arrives after cutoff') END;
END;
