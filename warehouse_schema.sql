CREATE SCHEMA IF NOT EXISTS charge_rate;

CREATE TABLE IF NOT EXISTS charge_rate.shipper_offsets (
  source_log_path text NOT NULL,
  session_id integer NOT NULL,
  next_measurement_index integer NOT NULL DEFAULT 0,
  updated_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (source_log_path, session_id)
);

CREATE TABLE IF NOT EXISTS charge_rate.raw_event_chunks (
  id bigserial PRIMARY KEY,
  created_at timestamptz NOT NULL DEFAULT now(),
  source_log_path text NOT NULL,
  session_id integer NOT NULL,
  first_measurement_index integer NOT NULL,
  last_measurement_index integer NOT NULL,
  chunk_started_at timestamp,
  chunk_ended_at timestamp,
  schema_version integer NOT NULL,
  encoding text NOT NULL,
  payload_sha256 text NOT NULL,
  payload_bytes bytea NOT NULL,
  payload_uncompressed_bytes integer NOT NULL,
  payload_compressed_bytes integer NOT NULL,
  measurement_count integer NOT NULL,
  decoded_at timestamptz,
  decode_error text,
  UNIQUE (source_log_path, session_id, first_measurement_index, last_measurement_index),
  UNIQUE (payload_sha256)
);

CREATE TABLE IF NOT EXISTS charge_rate.battery_sessions (
  source_log_path text NOT NULL,
  session_id integer NOT NULL,
  log_date date,
  started_at timestamp,
  ended_at timestamp,
  start_reason text,
  end_reason text,
  interval_seconds numeric,
  previous_gap jsonb,
  events jsonb,
  session_metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
  first_seen_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (source_log_path, session_id)
);

CREATE TABLE IF NOT EXISTS charge_rate.battery_measurements (
  source_log_path text NOT NULL,
  session_id integer NOT NULL,
  measurement_index integer NOT NULL,
  raw_event_chunk_id bigint NOT NULL REFERENCES charge_rate.raw_event_chunks(id) ON DELETE CASCADE,
  measured_at timestamp,
  status_available boolean,
  charge_rate_mw integer,
  discharge_rate_mw integer,
  effective_charge_rate_mw integer,
  effective_discharge_rate_mw integer,
  rate_source text,
  rate_confidence text,
  rate_window_seconds integer,
  remaining_capacity_mwh integer,
  full_charged_capacity_mwh integer,
  voltage_mv integer,
  charging boolean,
  power_online boolean,
  read_error text,
  raw_measurement jsonb NOT NULL,
  inserted_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (source_log_path, session_id, measurement_index)
);

CREATE INDEX IF NOT EXISTS idx_raw_event_chunks_pending
  ON charge_rate.raw_event_chunks (id)
  WHERE decoded_at IS NULL AND decode_error IS NULL;

CREATE INDEX IF NOT EXISTS idx_battery_measurements_measured_at
  ON charge_rate.battery_measurements (measured_at);

CREATE INDEX IF NOT EXISTS idx_battery_measurements_power_state
  ON charge_rate.battery_measurements (power_online, charging, measured_at);

CREATE INDEX IF NOT EXISTS idx_battery_measurements_rate_source
  ON charge_rate.battery_measurements (rate_source, measured_at);
