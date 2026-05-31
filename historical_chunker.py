import argparse
import gzip
import hashlib
import json
import time
from datetime import datetime, timedelta

from charge_rate_warehouse import (
    CHUNK_SCHEMA_VERSION,
    JSON_GZIP_ENCODING,
    WarehouseDependencyError,
    connect_database,
    initialize_database,
    iter_log_paths,
    load_log_file,
    log_date_from_data,
    normalize_source_path,
    parse_timestamp,
    session_metadata,
)


def parse_args():
    parser = argparse.ArgumentParser(
        description="Ship charge-rate JSON measurements as compressed chunk events into Postgres."
    )
    parser.add_argument("--database-url", help="Postgres connection URL. Defaults to CHARGE_RATE_DATABASE_URL.")
    parser.add_argument("--init-db", action="store_true", help="Create/update the warehouse schema before running.")
    parser.add_argument("--log-path", help="Ship one log file instead of scanning logs/*_charge_rates.json.")
    parser.add_argument("--chunk-seconds", type=int, default=30, help="Target event chunk width in seconds.")
    parser.add_argument(
        "--lag-seconds",
        type=int,
        default=30,
        help="Do not ship measurements newer than this many seconds. Use 0 for backfills.",
    )
    parser.add_argument("--poll-seconds", type=float, default=5, help="Seconds between scans.")
    parser.add_argument("--max-chunks", type=int, help="Maximum chunks to ship before exiting.")
    parser.add_argument("--quiet", action="store_true", help="Only print final summary output.")
    parser.add_argument("--once", action="store_true", help="Scan once and exit.")
    return parser.parse_args()


def get_next_measurement_index(conn, source_log_path, session_id):
    row = conn.execute(
        """
        SELECT next_measurement_index
        FROM charge_rate.shipper_offsets
        WHERE source_log_path = %s AND session_id = %s
        """,
        (source_log_path, session_id),
    ).fetchone()
    if row:
        return row["next_measurement_index"]

    conn.execute(
        """
        INSERT INTO charge_rate.shipper_offsets (source_log_path, session_id)
        VALUES (%s, %s)
        ON CONFLICT DO NOTHING
        """,
        (source_log_path, session_id),
    )
    return 0


def set_next_measurement_index(conn, source_log_path, session_id, next_index):
    conn.execute(
        """
        INSERT INTO charge_rate.shipper_offsets (
          source_log_path, session_id, next_measurement_index, updated_at
        )
        VALUES (%s, %s, %s, now())
        ON CONFLICT (source_log_path, session_id) DO UPDATE
        SET next_measurement_index = EXCLUDED.next_measurement_index,
            updated_at = now()
        """,
        (source_log_path, session_id, next_index),
    )


def build_next_chunk(measurements, start_index, chunk_seconds, cutoff_at):
    if start_index >= len(measurements):
        return None

    first_measurement = measurements[start_index]
    if not isinstance(first_measurement, dict):
        return {
            "first_index": start_index,
            "last_index": start_index,
            "chunk_started_at": None,
            "chunk_ended_at": None,
            "measurements": [
                {
                    "measurement_index": start_index,
                    "measurement": first_measurement,
                }
            ],
        }

    first_at = parse_timestamp(first_measurement.get("timestamp"))
    if cutoff_at is not None and first_at is not None and first_at > cutoff_at:
        return None

    window_ends_at = first_at + timedelta(seconds=chunk_seconds) if first_at else None
    chunk_measurements = []
    chunk_started_at = first_at
    chunk_ended_at = first_at
    index = start_index

    while index < len(measurements):
        measurement = measurements[index]
        measured_at = parse_timestamp(measurement.get("timestamp")) if isinstance(measurement, dict) else None

        if cutoff_at is not None and measured_at is not None and measured_at > cutoff_at:
            break
        if (
            window_ends_at is not None
            and measured_at is not None
            and measured_at > window_ends_at
            and chunk_measurements
        ):
            break

        chunk_measurements.append({
            "measurement_index": index,
            "measurement": measurement,
        })
        if measured_at is not None:
            chunk_started_at = min(chunk_started_at or measured_at, measured_at)
            chunk_ended_at = max(chunk_ended_at or measured_at, measured_at)
        index += 1

    if not chunk_measurements:
        return None

    return {
        "first_index": chunk_measurements[0]["measurement_index"],
        "last_index": chunk_measurements[-1]["measurement_index"],
        "chunk_started_at": chunk_started_at,
        "chunk_ended_at": chunk_ended_at,
        "measurements": chunk_measurements,
    }


def timestamp_value(value):
    return value if value is None else value.strftime("%Y-%m-%d %H:%M:%S")


def encode_payload(payload):
    raw_bytes = json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    compressed_bytes = gzip.compress(raw_bytes)
    return raw_bytes, compressed_bytes, hashlib.sha256(raw_bytes).hexdigest()


def insert_chunk(conn, source_log_path, session_id, log_date, session, chunk, chunk_seconds):
    metadata = session_metadata(session)
    payload = {
        "schema_version": CHUNK_SCHEMA_VERSION,
        "source_log_path": source_log_path,
        "log_date": log_date.isoformat() if log_date else None,
        "session": metadata,
        "chunk": {
            "chunk_seconds": chunk_seconds,
            "first_measurement_index": chunk["first_index"],
            "last_measurement_index": chunk["last_index"],
            "chunk_started_at": timestamp_value(chunk["chunk_started_at"]),
            "chunk_ended_at": timestamp_value(chunk["chunk_ended_at"]),
        },
        "measurements": chunk["measurements"],
    }
    raw_bytes, compressed_bytes, payload_hash = encode_payload(payload)

    row = conn.execute(
        """
        INSERT INTO charge_rate.raw_event_chunks (
          source_log_path,
          session_id,
          first_measurement_index,
          last_measurement_index,
          chunk_started_at,
          chunk_ended_at,
          schema_version,
          encoding,
          payload_sha256,
          payload_bytes,
          payload_uncompressed_bytes,
          payload_compressed_bytes,
          measurement_count
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT DO NOTHING
        RETURNING id
        """,
        (
            source_log_path,
            session_id,
            chunk["first_index"],
            chunk["last_index"],
            chunk["chunk_started_at"],
            chunk["chunk_ended_at"],
            CHUNK_SCHEMA_VERSION,
            JSON_GZIP_ENCODING,
            payload_hash,
            compressed_bytes,
            len(raw_bytes),
            len(compressed_bytes),
            len(chunk["measurements"]),
        ),
    ).fetchone()

    event_id = row["id"] if row else None
    set_next_measurement_index(conn, source_log_path, session_id, chunk["last_index"] + 1)

    if event_id is not None:
        conn.execute("SELECT pg_notify('charge_rate_chunks', %s)", (str(event_id),))
    return event_id, len(raw_bytes), len(compressed_bytes)


def ship_session_chunks(conn, source_log_path, log_date, session, args, cutoff_at):
    session_id = session.get("session_id")
    measurements = session.get("measurements")
    if not isinstance(session_id, int) or not isinstance(measurements, list):
        return 0

    shipped = 0
    while args.max_chunks is None or shipped < args.max_chunks:
        start_index = get_next_measurement_index(conn, source_log_path, session_id)
        chunk = build_next_chunk(measurements, start_index, args.chunk_seconds, cutoff_at)
        if chunk is None:
            break

        event_id, raw_size, compressed_size = insert_chunk(
            conn,
            source_log_path,
            session_id,
            log_date,
            session,
            chunk,
            args.chunk_seconds,
        )
        conn.commit()

        shipped += 1
        if args.quiet:
            pass
        elif event_id is None:
            print(
                f"Skipped existing chunk {source_log_path} session #{session_id} "
                f"[{chunk['first_index']}-{chunk['last_index']}]."
            )
        else:
            ratio = compressed_size / raw_size if raw_size else 0
            print(
                f"Shipped chunk event #{event_id}: {source_log_path} session #{session_id} "
                f"[{chunk['first_index']}-{chunk['last_index']}] "
                f"{raw_size}B -> {compressed_size}B ({ratio:.0%})."
            )

    return shipped


def ship_available_chunks(conn, args):
    cutoff_at = datetime.now() - timedelta(seconds=args.lag_seconds) if args.lag_seconds > 0 else None
    shipped = 0

    for path in iter_log_paths(args.log_path):
        try:
            data = load_log_file(path)
        except (FileNotFoundError, json.JSONDecodeError, OSError, ValueError) as error:
            print(f"Skipping {path}: {type(error).__name__}: {error}")
            continue

        source_log_path = normalize_source_path(path)
        log_date = log_date_from_data(data)
        for session in data.get("sessions", []):
            if not isinstance(session, dict):
                continue
            shipped += ship_session_chunks(conn, source_log_path, log_date, session, args, cutoff_at)
            if args.max_chunks is not None and shipped >= args.max_chunks:
                return shipped

    return shipped


def run(args):
    with connect_database(args.database_url) as conn:
        if args.init_db:
            initialize_database(conn)

        total_shipped = 0
        while True:
            shipped = ship_available_chunks(conn, args)
            total_shipped += shipped
            if args.once:
                return total_shipped
            if args.max_chunks is not None and total_shipped >= args.max_chunks:
                return total_shipped
            if shipped == 0:
                time.sleep(args.poll_seconds)


def main():
    args = parse_args()
    try:
        shipped = run(args)
    except WarehouseDependencyError as error:
        raise SystemExit(str(error)) from error
    if args.once:
        print(f"Shipped {shipped} chunk(s).")


if __name__ == "__main__":
    main()
