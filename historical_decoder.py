import argparse
import time

from charge_rate_warehouse import (
    WarehouseDependencyError,
    bool_or_none,
    connect_database,
    decode_chunk_payload,
    initialize_database,
    int_or_none,
    parse_timestamp,
    require_psycopg,
)


def parse_args():
    parser = argparse.ArgumentParser(
        description="Decode compressed charge-rate chunk events into queryable Postgres rows."
    )
    parser.add_argument("--database-url", help="Postgres connection URL. Defaults to CHARGE_RATE_DATABASE_URL.")
    parser.add_argument("--init-db", action="store_true", help="Create/update the warehouse schema before running.")
    parser.add_argument("--batch-size", type=int, default=25, help="Pending chunks to decode per pass.")
    parser.add_argument("--poll-seconds", type=float, default=5, help="Seconds between polling passes.")
    parser.add_argument("--quiet", action="store_true", help="Only print final summary output.")
    parser.add_argument("--once", action="store_true", help="Decode pending chunks once and exit.")
    return parser.parse_args()


def fetch_pending_chunk(conn):
    return conn.execute(
        """
        SELECT id, encoding, payload_bytes
        FROM charge_rate.raw_event_chunks
        WHERE decoded_at IS NULL AND decode_error IS NULL
        ORDER BY id
        LIMIT 1
        FOR UPDATE SKIP LOCKED
        """
    ).fetchone()


def upsert_session(conn, payload):
    _psycopg, _dict_row, Jsonb = require_psycopg()
    source_log_path = payload["source_log_path"]
    session = payload.get("session") or {}
    session_id = session.get("session_id")

    conn.execute(
        """
        INSERT INTO charge_rate.battery_sessions (
          source_log_path,
          session_id,
          log_date,
          started_at,
          ended_at,
          start_reason,
          end_reason,
          interval_seconds,
          previous_gap,
          events,
          session_metadata,
          updated_at
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, now())
        ON CONFLICT (source_log_path, session_id) DO UPDATE
        SET log_date = EXCLUDED.log_date,
            started_at = EXCLUDED.started_at,
            ended_at = EXCLUDED.ended_at,
            start_reason = EXCLUDED.start_reason,
            end_reason = EXCLUDED.end_reason,
            interval_seconds = EXCLUDED.interval_seconds,
            previous_gap = EXCLUDED.previous_gap,
            events = EXCLUDED.events,
            session_metadata = EXCLUDED.session_metadata,
            updated_at = now()
        """,
        (
            source_log_path,
            session_id,
            payload.get("log_date"),
            parse_timestamp(session.get("started_at")),
            parse_timestamp(session.get("ended_at")),
            session.get("start_reason"),
            session.get("end_reason"),
            session.get("interval_seconds"),
            Jsonb(session.get("previous_gap")) if session.get("previous_gap") is not None else None,
            Jsonb(session.get("events") or []),
            Jsonb(session),
        ),
    )


def insert_measurement(conn, chunk_id, payload, item):
    _psycopg, _dict_row, Jsonb = require_psycopg()
    source_log_path = payload["source_log_path"]
    session_id = payload["session"]["session_id"]
    measurement_index = item["measurement_index"]
    measurement = item["measurement"]

    conn.execute(
        """
        INSERT INTO charge_rate.battery_measurements (
          source_log_path,
          session_id,
          measurement_index,
          raw_event_chunk_id,
          measured_at,
          status_available,
          charge_rate_mw,
          discharge_rate_mw,
          effective_charge_rate_mw,
          effective_discharge_rate_mw,
          rate_source,
          rate_confidence,
          rate_window_seconds,
          remaining_capacity_mwh,
          full_charged_capacity_mwh,
          voltage_mv,
          charging,
          power_online,
          read_error,
          raw_measurement,
          updated_at
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, now())
        ON CONFLICT (source_log_path, session_id, measurement_index) DO UPDATE
        SET raw_event_chunk_id = EXCLUDED.raw_event_chunk_id,
            measured_at = EXCLUDED.measured_at,
            status_available = EXCLUDED.status_available,
            charge_rate_mw = EXCLUDED.charge_rate_mw,
            discharge_rate_mw = EXCLUDED.discharge_rate_mw,
            effective_charge_rate_mw = EXCLUDED.effective_charge_rate_mw,
            effective_discharge_rate_mw = EXCLUDED.effective_discharge_rate_mw,
            rate_source = EXCLUDED.rate_source,
            rate_confidence = EXCLUDED.rate_confidence,
            rate_window_seconds = EXCLUDED.rate_window_seconds,
            remaining_capacity_mwh = EXCLUDED.remaining_capacity_mwh,
            full_charged_capacity_mwh = EXCLUDED.full_charged_capacity_mwh,
            voltage_mv = EXCLUDED.voltage_mv,
            charging = EXCLUDED.charging,
            power_online = EXCLUDED.power_online,
            read_error = EXCLUDED.read_error,
            raw_measurement = EXCLUDED.raw_measurement,
            updated_at = now()
        """,
        (
            source_log_path,
            session_id,
            measurement_index,
            chunk_id,
            parse_timestamp(measurement.get("timestamp")),
            bool_or_none(measurement.get("status_available")),
            int_or_none(measurement.get("charge_rate_mW")),
            int_or_none(measurement.get("discharge_rate_mW")),
            int_or_none(measurement.get("effective_charge_rate_mW")),
            int_or_none(measurement.get("effective_discharge_rate_mW")),
            measurement.get("rate_source"),
            measurement.get("rate_confidence"),
            int_or_none(measurement.get("rate_window_seconds")),
            int_or_none(measurement.get("remaining_capacity_mWh")),
            int_or_none(measurement.get("full_charged_capacity_mWh")),
            int_or_none(measurement.get("voltage_mV")),
            bool_or_none(measurement.get("charging")),
            bool_or_none(measurement.get("power_online")),
            measurement.get("read_error"),
            Jsonb(measurement),
        ),
    )


def mark_decoded(conn, chunk_id):
    conn.execute(
        """
        UPDATE charge_rate.raw_event_chunks
        SET decoded_at = now(), decode_error = NULL
        WHERE id = %s
        """,
        (chunk_id,),
    )


def mark_decode_error(conn, chunk_id, error):
    conn.execute(
        """
        UPDATE charge_rate.raw_event_chunks
        SET decode_error = %s
        WHERE id = %s
        """,
        (f"{type(error).__name__}: {error}"[:1000], chunk_id),
    )


def decode_chunk(conn, chunk):
    payload = decode_chunk_payload(chunk["encoding"], chunk["payload_bytes"])
    upsert_session(conn, payload)

    for item in payload.get("measurements", []):
        if not isinstance(item, dict) or not isinstance(item.get("measurement"), dict):
            continue
        insert_measurement(conn, chunk["id"], payload, item)

    mark_decoded(conn, chunk["id"])
    return len(payload.get("measurements", []))


def decode_pending_once(conn, args):
    decoded = 0

    for _ in range(args.batch_size):
        try:
            with conn.transaction():
                chunk = fetch_pending_chunk(conn)
                if chunk is None:
                    break
                measurement_count = decode_chunk(conn, chunk)
            decoded += 1
            if not args.quiet:
                print(f"Decoded chunk #{chunk['id']} ({measurement_count} measurement(s)).")
        except Exception as error:
            conn.rollback()
            with conn.transaction():
                mark_decode_error(conn, chunk["id"], error)
            print(f"Decode failed for chunk #{chunk['id']}: {type(error).__name__}: {error}")

    return decoded


def run(args):
    with connect_database(args.database_url) as conn:
        if args.init_db:
            initialize_database(conn)

        total_decoded = 0
        while True:
            decoded = decode_pending_once(conn, args)
            total_decoded += decoded
            if args.once:
                return total_decoded
            if decoded == 0:
                time.sleep(args.poll_seconds)


def main():
    args = parse_args()
    try:
        decoded = run(args)
    except WarehouseDependencyError as error:
        raise SystemExit(str(error)) from error
    if args.once:
        print(f"Decoded {decoded} chunk(s).")


if __name__ == "__main__":
    main()
