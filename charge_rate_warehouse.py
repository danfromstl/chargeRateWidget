import gzip
import json
import os
from datetime import datetime
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent
LOG_DIR = REPO_ROOT / "logs"
SCHEMA_PATH = REPO_ROOT / "warehouse_schema.sql"
TIMESTAMP_FORMAT = "%Y-%m-%d %H:%M:%S"
CHUNK_SCHEMA_VERSION = 1
JSON_GZIP_ENCODING = "json+gzip"


class WarehouseDependencyError(RuntimeError):
    pass


def require_psycopg():
    try:
        import psycopg
        from psycopg.rows import dict_row
        from psycopg.types.json import Jsonb
    except ModuleNotFoundError as error:
        raise WarehouseDependencyError(
            "Postgres support requires psycopg. Install it with: pip install \"psycopg[binary]\""
        ) from error
    return psycopg, dict_row, Jsonb


def database_url(cli_value=None):
    url = cli_value or os.environ.get("CHARGE_RATE_DATABASE_URL") or os.environ.get("DATABASE_URL")
    if not url:
        raise ValueError(
            "Set CHARGE_RATE_DATABASE_URL or pass --database-url, for example "
            "postgresql://postgres:postgres@localhost:5432/charge_rate"
        )
    return url


def connect_database(cli_value=None):
    psycopg, dict_row, _jsonb = require_psycopg()
    return psycopg.connect(database_url(cli_value), row_factory=dict_row)


def initialize_database(conn):
    with SCHEMA_PATH.open("r", encoding="utf-8") as file:
        conn.execute(file.read())
    conn.commit()


def parse_timestamp(value):
    if not value:
        return None

    for parser in (
        lambda t: datetime.strptime(t, TIMESTAMP_FORMAT),
        datetime.fromisoformat,
    ):
        try:
            return parser(value)
        except (TypeError, ValueError):
            continue
    return None


def normalize_source_path(path):
    resolved = Path(path).resolve()
    try:
        return resolved.relative_to(REPO_ROOT).as_posix()
    except ValueError:
        return str(resolved)


def log_date_from_data(data):
    parsed = parse_timestamp(data.get("date"))
    if parsed is not None:
        return parsed.date()

    value = data.get("date")
    if isinstance(value, str):
        try:
            return datetime.strptime(value, "%Y-%m-%d").date()
        except ValueError:
            return None
    return None


def iter_log_paths(log_path=None):
    if log_path is not None:
        yield Path(log_path)
        return

    if not LOG_DIR.exists():
        return

    for path in sorted(LOG_DIR.glob("*_charge_rates.json")):
        if path.name.startswith("_") or ".tmp" in path.name:
            continue
        yield path


def load_log_file(path):
    with Path(path).open("r", encoding="utf-8") as file:
        data = json.load(file)

    sessions = data.get("sessions")
    if not isinstance(sessions, list):
        raise ValueError(f"{path} does not contain a sessions list.")
    return data


def session_metadata(session):
    metadata = {
        key: value
        for key, value in session.items()
        if key != "measurements"
    }
    return metadata


def decode_chunk_payload(encoding, payload_bytes):
    if encoding == JSON_GZIP_ENCODING:
        raw_bytes = gzip.decompress(bytes(payload_bytes))
        return json.loads(raw_bytes.decode("utf-8"))
    if encoding == "json":
        return json.loads(bytes(payload_bytes).decode("utf-8"))
    raise ValueError(f"Unsupported payload encoding: {encoding}")


def int_or_none(value):
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def bool_or_none(value):
    if value is None:
        return None
    return bool(value)
