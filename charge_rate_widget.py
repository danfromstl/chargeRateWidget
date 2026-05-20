import argparse
import time
import json
import os
import subprocess
import sys
from pathlib import Path
import wmi
from datetime import datetime

# Connect lazily so transient WMI failures become sampled hiccups instead of import-time crashes.
w = None

LOG_DIR = Path(__file__).resolve().parent / "logs"
OVERLAY_SCRIPT = Path(__file__).resolve().parent / "charge_rate_overlay.py"
BATTERY_UNKNOWN_RATE = -2147483648
JSON_WRITE_ATTEMPTS = 8
JSON_WRITE_RETRY_SECONDS = 0.15
MONITORED_VALUE_KEYS = (
    "status_available",
    "charge_rate_mW",
    "discharge_rate_mW",
    "remaining_capacity_mWh",
    "full_charged_capacity_mWh",
    "voltage_mV",
    "charging",
    "power_online",
    "read_error",
)


def timestamp_now():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def get_wmi_connection():
    global w
    if w is None:
        w = wmi.WMI(namespace="root\\wmi")
    return w


def normalize_rate(rate):
    return None if rate == BATTERY_UNKNOWN_RATE else rate


def unavailable_status(timestamp, read_error):
    return {
        "timestamp": timestamp,
        "status_available": False,
        "charge_rate_mW": None,
        "discharge_rate_mW": None,
        "remaining_capacity_mWh": None,
        "full_charged_capacity_mWh": None,
        "voltage_mV": None,
        "charging": None,
        "power_online": None,
        "read_error": read_error,
    }


def get_full_charged_capacity():
    try:
        capacity = get_wmi_connection().BatteryFullChargedCapacity()[0]
        return capacity.FullChargedCapacity
    except Exception:
        return None


def get_battery_status():
    timestamp = timestamp_now()
    try:
        battery = get_wmi_connection().BatteryStatus()[0]
        return {
            "timestamp": timestamp,
            "status_available": True,
            "charge_rate_mW": normalize_rate(battery.ChargeRate),
            "discharge_rate_mW": normalize_rate(battery.DischargeRate),
            "remaining_capacity_mWh": battery.RemainingCapacity,
            "full_charged_capacity_mWh": get_full_charged_capacity(),
            "voltage_mV": battery.Voltage,
            "charging": battery.Charging,
            "power_online": battery.PowerOnline,
            "read_error": None,
        }
    except IndexError:
        return unavailable_status(timestamp, "Battery status not available.")
    except Exception as error:
        return unavailable_status(timestamp, f"{type(error).__name__}: {error}")


def daily_log_path(now=None):
    now = now or datetime.now()
    filename = f"{now.month}-{now.day}-{now.strftime('%y')}_charge_rates.json"
    return LOG_DIR / filename


def load_daily_log(path, log_date):
    if not path.exists():
        return {
            "date": log_date,
            "sessions": []
        }

    with path.open("r", encoding="utf-8") as file:
        data = json.load(file)

    if not isinstance(data, dict):
        raise ValueError(f"{path} must contain a JSON object.")

    sessions = data.setdefault("sessions", [])
    if not isinstance(sessions, list):
        raise ValueError(f"{path} must contain a 'sessions' list.")

    data.setdefault("date", log_date)
    return data


def write_daily_log(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    last_error = None

    for _attempt in range(JSON_WRITE_ATTEMPTS):
        try:
            with temp_path.open("w", encoding="utf-8") as file:
                json.dump(data, file, indent=2)
                file.write("\n")
            temp_path.replace(path)
            return
        except OSError as error:
            last_error = error
            time.sleep(JSON_WRITE_RETRY_SECONDS)

    raise last_error


def next_session_id(data):
    session_ids = [
        session.get("session_id", 0)
        for session in data["sessions"]
        if isinstance(session, dict) and isinstance(session.get("session_id"), int)
    ]
    return max(session_ids, default=0) + 1


def start_json_session(interval):
    now = datetime.now()
    path = daily_log_path(now)
    data = load_daily_log(path, now.strftime("%Y-%m-%d"))
    session = {
        "session_id": next_session_id(data),
        "started_at": timestamp_now(),
        "ended_at": None,
        "interval_seconds": interval,
        "measurements": []
    }
    data["sessions"].append(session)
    write_daily_log(path, data)
    return path, data, session


def start_overlay(log_path, session_id):
    if not OVERLAY_SCRIPT.exists():
        print(f"Overlay script not found: {OVERLAY_SCRIPT}")
        return None

    command = [
        sys.executable,
        str(OVERLAY_SCRIPT),
        "--log-path",
        str(log_path),
        "--session-id",
        str(session_id),
    ]
    creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    return subprocess.Popen(
        command,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=creationflags,
    )


def record_measurement(path, data, session, status):
    session["measurements"].append(status)
    session["last_updated_at"] = status["timestamp"]
    session["last_write_error"] = None
    try:
        write_daily_log(path, data)
        return None
    except OSError as error:
        session["last_write_error"] = f"{type(error).__name__}: {error}"
        return session["last_write_error"]


def value_fingerprint(status):
    return tuple(status.get(key) for key in MONITORED_VALUE_KEYS)


def format_value(value, suffix):
    if value is None:
        return "null"
    return f"{value} {suffix}"


def format_status(status):
    if not status["status_available"]:
        return f"[{status['timestamp']}] Battery status unavailable: {status['read_error']}"

    return (f"[{status['timestamp']}] "
            f"{'Charging' if status['charging'] else 'Discharging'} | "
            f"Charge Rate: {format_value(status['charge_rate_mW'], 'mW')} | "
            f"Discharge Rate: {format_value(status['discharge_rate_mW'], 'mW')} | "
            f"Remaining: {status['remaining_capacity_mWh']} mWh | "
            f"Voltage: {status['voltage_mV']} mV")


def parse_args():
    parser = argparse.ArgumentParser(description="Monitor laptop charge and discharge rate.")
    parser.add_argument("--interval", type=float, default=2, help="Seconds between samples.")
    parser.add_argument("--overlay", dest="show_overlay", action="store_true", default=True)
    parser.add_argument("--no-overlay", dest="show_overlay", action="store_false")
    return parser.parse_args()


def log_battery_status(interval=5, show_overlay=True):
    log_path, data, session = start_json_session(interval)
    overlay_process = start_overlay(log_path, session["session_id"]) if show_overlay else None

    print(f"Monitoring battery. Writing every {interval}s sample to {log_path}.")
    print("Console output appears only when a monitored value changes.")
    if overlay_process:
        print("Overlay started.")
    print("Press Ctrl+C to stop.\n")

    previous_values = None
    previous_write_error = None
    try:
        while True:
            status = get_battery_status()
            write_error = record_measurement(log_path, data, session, status)
            if write_error and write_error != previous_write_error:
                print(f"[{status['timestamp']}] JSON write hiccup: {write_error}")
            previous_write_error = write_error

            current_values = value_fingerprint(status)
            if current_values != previous_values:
                print(format_status(status))
                previous_values = current_values

            time.sleep(interval)
    except KeyboardInterrupt:
        session["ended_at"] = timestamp_now()
        final_write_failed = False
        try:
            write_daily_log(log_path, data)
        except OSError as error:
            final_write_failed = True
            print(f"\nStopped, but final JSON write failed: {type(error).__name__}: {error}")
        if overlay_process and overlay_process.poll() is None:
            overlay_process.terminate()
        if not final_write_failed:
            print(f"\nStopped. Final JSON written to {log_path}.")

if __name__ == "__main__":
    args = parse_args()
    log_battery_status(interval=args.interval, show_overlay=args.show_overlay)
