import csv
import json
from datetime import datetime
from pathlib import Path
from statistics import median


REPO_ROOT = Path(__file__).resolve().parent
LOG_DIR = REPO_ROOT / "logs"
LEGACY_CSVS = (
    LOG_DIR / "Monday_laptop_charge_log.csv",
    LOG_DIR / "Tuesday_laptop_charge_log.csv",
)


def parse_int(value):
    if value == "":
        return None
    return int(value)


def format_timestamp(value):
    return datetime.fromisoformat(value).strftime("%Y-%m-%d %H:%M:%S")


def infer_interval_seconds(rows):
    timestamps = [datetime.fromisoformat(row["timestamp"]) for row in rows]
    deltas = [
        int((later - earlier).total_seconds())
        for earlier, later in zip(timestamps, timestamps[1:])
        if later > earlier
    ]
    return int(median(deltas)) if deltas else None


def daily_log_path(timestamp):
    now = datetime.fromisoformat(timestamp)
    filename = f"{now.month}-{now.day}-{now.strftime('%y')}_charge_rates.json"
    return LOG_DIR / filename


def next_session_id(data):
    session_ids = [
        session.get("session_id", 0)
        for session in data["sessions"]
        if isinstance(session, dict) and isinstance(session.get("session_id"), int)
    ]
    return max(session_ids, default=0) + 1


def legacy_row_to_measurement(row):
    status = row["status"].strip().lower()
    charging = status == "charging"
    rate = parse_int(row["rate_mw"])

    return {
        "timestamp": format_timestamp(row["timestamp"]),
        "status_available": True,
        "charge_rate_mW": rate if charging else 0,
        "discharge_rate_mW": 0 if charging else rate,
        "remaining_capacity_mWh": parse_int(row["remaining_mwh"]),
        "full_charged_capacity_mWh": None,
        "voltage_mV": parse_int(row["voltage_mv"]),
        "charging": charging,
        "power_online": charging,
        "read_error": None,
    }


def load_daily_json(path, log_date):
    if not path.exists():
        return {"date": log_date, "sessions": []}

    with path.open("r", encoding="utf-8") as file:
        data = json.load(file)

    data.setdefault("date", log_date)
    data.setdefault("sessions", [])
    return data


def write_json(path, data):
    with path.open("w", encoding="utf-8") as file:
        json.dump(data, file, indent=2)
        file.write("\n")


def convert_csv(path):
    with path.open("r", encoding="utf-8", newline="") as file:
        rows = list(csv.DictReader(file))

    if not rows:
        return None

    first_timestamp = datetime.fromisoformat(rows[0]["timestamp"])
    output_path = daily_log_path(rows[0]["timestamp"])
    data = load_daily_json(output_path, first_timestamp.strftime("%Y-%m-%d"))
    data["sessions"] = [
        session
        for session in data["sessions"]
        if session.get("source_file") != path.name
    ]

    measurements = [legacy_row_to_measurement(row) for row in rows]
    session = {
        "session_id": next_session_id(data),
        "started_at": measurements[0]["timestamp"],
        "ended_at": measurements[-1]["timestamp"],
        "interval_seconds": infer_interval_seconds(rows),
        "source_file": path.name,
        "measurements": measurements,
    }
    data["sessions"].append(session)
    write_json(output_path, data)
    return output_path, len(measurements)


def main():
    for csv_path in LEGACY_CSVS:
        if not csv_path.exists():
            print(f"Skipped missing CSV: {csv_path}")
            continue

        result = convert_csv(csv_path)
        if result is None:
            print(f"Skipped empty CSV: {csv_path}")
            continue

        output_path, count = result
        print(f"Wrote {count} measurements to {output_path}")


if __name__ == "__main__":
    main()
