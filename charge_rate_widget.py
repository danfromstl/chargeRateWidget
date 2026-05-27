import argparse
import time
import json
import os
import subprocess
import sys
from pathlib import Path
import wmi
from datetime import datetime, timedelta

# Connect lazily so transient WMI failures become sampled hiccups instead of import-time crashes.
w = None

REPO_ROOT = Path(__file__).resolve().parent
LOG_DIR = REPO_ROOT / "logs"
CURRENT_SESSION_PATH = LOG_DIR / "_current_session.json"
OVERLAY_SCRIPT = REPO_ROOT / "charge_rate_overlay.py"
BATTERY_UNKNOWN_RATE = -2147483648
JSON_WRITE_ATTEMPTS = 8
JSON_WRITE_RETRY_SECONDS = 0.15
TIMESTAMP_FORMAT = "%Y-%m-%d %H:%M:%S"
DEFAULT_MIN_GAP_SECONDS = 60
GAP_THRESHOLD_INTERVAL_MULTIPLIER = 5
POWER_EVENT_QUERY_TIMEOUT_SECONDS = 5
POWER_EVENT_QUERY_PADDING_SECONDS = 30
RATE_ESTIMATE_MIN_WINDOW_SECONDS = 30
RATE_ESTIMATE_MAX_WINDOW_SECONDS = 15 * 60
RATE_ESTIMATE_MIN_DELTA_MWH = 10
MONITORED_VALUE_KEYS = (
    "status_available",
    "charge_rate_mW",
    "discharge_rate_mW",
    "effective_charge_rate_mW",
    "effective_discharge_rate_mW",
    "rate_source",
    "rate_confidence",
    "remaining_capacity_mWh",
    "full_charged_capacity_mWh",
    "voltage_mV",
    "charging",
    "power_online",
    "read_error",
)


def timestamp_now():
    return format_timestamp(datetime.now())


def format_timestamp(value):
    return value.strftime(TIMESTAMP_FORMAT)


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
        "effective_charge_rate_mW": None,
        "effective_discharge_rate_mW": None,
        "rate_source": "unavailable",
        "rate_confidence": "none",
        "rate_window_seconds": None,
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


def write_json_file(path, data):
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


def write_daily_log(path, data):
    write_json_file(path, data)


def write_current_session_pointer(path, session, updated_at=None):
    pointer = {
        "log_path": str(path),
        "session_id": session.get("session_id"),
        "date": path.stem.split("_", 1)[0],
        "started_at": session.get("started_at"),
        "updated_at": updated_at or timestamp_now(),
    }
    write_json_file(CURRENT_SESSION_PATH, pointer)


def next_session_id(data):
    session_ids = [
        session.get("session_id", 0)
        for session in data["sessions"]
        if isinstance(session, dict) and isinstance(session.get("session_id"), int)
    ]
    return max(session_ids, default=0) + 1


def session_gap_threshold(interval, configured_threshold=None):
    if configured_threshold is not None:
        return max(0, configured_threshold)
    return max(DEFAULT_MIN_GAP_SECONDS, interval * GAP_THRESHOLD_INTERVAL_MULTIPLIER)


def latest_session(data):
    sessions = data.get("sessions", [])
    for session in reversed(sessions):
        if isinstance(session, dict):
            return session
    return None


def latest_measurement(session):
    measurements = session.get("measurements", [])
    if not isinstance(measurements, list):
        return None

    for measurement in reversed(measurements):
        if isinstance(measurement, dict):
            return measurement
    return None


def session_last_activity(session):
    candidates = []

    for key in ("last_updated_at", "resumed_at", "ended_at", "started_at"):
        dt = parse_timestamp(session.get(key))
        if dt is not None:
            candidates.append(dt)

    measurement = latest_measurement(session)
    if measurement is not None:
        dt = parse_timestamp(measurement.get("timestamp"))
        if dt is not None:
            candidates.append(dt)

    return max(candidates) if candidates else None


def append_session_event(session, event):
    if not event:
        return
    events = session.setdefault("events", [])
    if isinstance(events, list):
        events.append(event)


def open_daily_log(now):
    path = daily_log_path(now)
    data = load_daily_log(path, now.strftime("%Y-%m-%d"))
    return path, data


def new_session(data, interval, started_at=None, start_reason="process_start", previous_gap=None):
    started_at = started_at or datetime.now()
    session = {
        "session_id": next_session_id(data),
        "started_at": format_timestamp(started_at),
        "ended_at": None,
        "start_reason": start_reason,
        "end_reason": None,
        "interval_seconds": interval,
        "events": [],
        "measurements": []
    }
    if previous_gap:
        session["previous_gap"] = previous_gap
    data["sessions"].append(session)
    return session


def start_json_session(interval, now=None, start_reason="process_start", previous_gap=None):
    now = now or datetime.now()
    path, data = open_daily_log(now)
    start_at = parse_timestamp(previous_gap.get("resume_event_at")) if previous_gap else None
    session = new_session(
        data,
        interval,
        started_at=start_at or now,
        start_reason=start_reason,
        previous_gap=previous_gap,
    )
    write_daily_log(path, data)
    write_current_session_pointer(path, session, updated_at=session["started_at"])
    return path, data, session


def close_json_session(path, data, session, ended_at=None, end_reason="process_stop", event=None):
    ended_at = ended_at or datetime.now()
    ended_at_text = format_timestamp(ended_at) if isinstance(ended_at, datetime) else ended_at
    session["ended_at"] = session.get("ended_at") or ended_at_text
    session["end_reason"] = session.get("end_reason") or end_reason
    append_session_event(session, event)
    write_daily_log(path, data)


def start_overlay(_log_path=None, _session_id=None):
    if not OVERLAY_SCRIPT.exists():
        print(f"Overlay script not found: {OVERLAY_SCRIPT}")
        return None

    command = [
        sys.executable,
        str(OVERLAY_SCRIPT),
    ]
    creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    return subprocess.Popen(
        command,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=creationflags,
    )


def log_date_from_path(path):
    raw_date = path.name.split("_", 1)[0]
    try:
        return datetime.strptime(raw_date, "%m-%d-%y").strftime("%Y-%m-%d")
    except ValueError:
        return datetime.now().strftime("%Y-%m-%d")


def daily_log_paths():
    if not LOG_DIR.exists():
        return []
    return sorted(LOG_DIR.glob("*_charge_rates.json"))


def compact_event_message(message):
    if not message:
        return None
    return " ".join(str(message).split())[:240]


def classify_windows_power_event(provider, event_id):
    if provider == "Microsoft-Windows-Power-Troubleshooter" and event_id == 1:
        return "wake"
    if provider == "Microsoft-Windows-Kernel-Power" and event_id in (42, 506):
        return "sleep"
    if provider == "Microsoft-Windows-Kernel-Power" and event_id in (107, 507):
        return "wake"
    return "power_event"


def query_windows_power_events(start_dt, end_dt):
    if os.name != "nt":
        return []

    padded_start = start_dt - timedelta(seconds=POWER_EVENT_QUERY_PADDING_SECONDS)
    padded_end = end_dt + timedelta(seconds=POWER_EVENT_QUERY_PADDING_SECONDS)
    script = r"""
$start = [datetime]::Parse($env:CHARGE_RATE_POWER_EVENT_START, [Globalization.CultureInfo]::InvariantCulture)
$end = [datetime]::Parse($env:CHARGE_RATE_POWER_EVENT_END, [Globalization.CultureInfo]::InvariantCulture)
$wanted = @{
  'Microsoft-Windows-Kernel-Power' = @(42, 107, 506, 507)
  'Microsoft-Windows-Power-Troubleshooter' = @(1)
}
Get-WinEvent -FilterHashtable @{ LogName = 'System'; StartTime = $start; EndTime = $end } -ErrorAction SilentlyContinue |
  Where-Object { $wanted.ContainsKey($_.ProviderName) -and $wanted[$_.ProviderName] -contains $_.Id } |
  Sort-Object TimeCreated |
  Select-Object `
    @{Name='time_created';Expression={$_.TimeCreated.ToString('yyyy-MM-dd HH:mm:ss')}}, `
    @{Name='provider';Expression={$_.ProviderName}}, `
    @{Name='event_id';Expression={$_.Id}}, `
    @{Name='message';Expression={$_.Message}} |
  ConvertTo-Json -Compress -Depth 3
"""
    env = os.environ.copy()
    env["CHARGE_RATE_POWER_EVENT_START"] = padded_start.isoformat(sep=" ")
    env["CHARGE_RATE_POWER_EVENT_END"] = padded_end.isoformat(sep=" ")
    try:
        result = subprocess.run(
            [
                "powershell",
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-Command",
                script,
            ],
            capture_output=True,
            text=True,
            env=env,
            timeout=POWER_EVENT_QUERY_TIMEOUT_SECONDS,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except (OSError, subprocess.SubprocessError):
        return []

    if result.returncode != 0 or not result.stdout.strip():
        return []

    try:
        raw_events = json.loads(result.stdout)
    except json.JSONDecodeError:
        return []

    if isinstance(raw_events, dict):
        raw_events = [raw_events]
    if not isinstance(raw_events, list):
        return []

    events = []
    for event in raw_events:
        if not isinstance(event, dict):
            continue
        provider = event.get("provider")
        event_id = event.get("event_id")
        if not isinstance(event_id, int):
            continue
        event_type = classify_windows_power_event(provider, event_id)
        events.append({
            "type": event_type,
            "timestamp": event.get("time_created"),
            "provider": provider,
            "event_id": event_id,
            "message": compact_event_message(event.get("message")),
        })
    return events


def describe_gap(start_dt, end_dt, classification="sampling_gap"):
    duration = max(0, (end_dt - start_dt).total_seconds())
    power_events = query_windows_power_events(start_dt, end_dt)
    sleep_events = [event for event in power_events if event.get("type") == "sleep"]
    wake_events = [event for event in power_events if event.get("type") == "wake"]
    sleep_event_at = sleep_events[0].get("timestamp") if sleep_events else None
    resume_event_at = wake_events[-1].get("timestamp") if wake_events else None

    if sleep_event_at or resume_event_at:
        classification = "sleep_wake"

    return {
        "type": "gap",
        "classification": classification,
        "started_at": format_timestamp(start_dt),
        "ended_at": format_timestamp(end_dt),
        "duration_seconds": round(duration, 3),
        "sleep_event_at": sleep_event_at,
        "resume_event_at": resume_event_at,
        "power_events": power_events,
    }


def gap_end_reason(gap):
    if gap.get("sleep_event_at"):
        return "sleep"
    return gap.get("classification") or "sampling_gap"


def gap_start_reason(gap):
    if gap.get("resume_event_at"):
        return "wake"
    if gap.get("sleep_event_at"):
        return "resume_after_sleep"
    return "resume_after_gap"


def recover_old_unclosed_sessions(now, interval, configured_gap_threshold=None, exclude_path=None):
    gap_threshold = session_gap_threshold(interval, configured_gap_threshold)

    for path in daily_log_paths():
        if exclude_path is not None and path.resolve() == exclude_path.resolve():
            continue

        data = load_daily_log(path, log_date_from_path(path))
        changed = False
        for session in data.get("sessions", []):
            if not isinstance(session, dict) or session.get("ended_at"):
                continue

            last_dt = session_last_activity(session) or now
            if (now - last_dt).total_seconds() >= gap_threshold:
                gap = describe_gap(last_dt, now, classification="app_downtime")
            else:
                gap = {
                    "type": "gap",
                    "classification": "app_downtime",
                    "started_at": format_timestamp(last_dt),
                    "ended_at": format_timestamp(now),
                    "duration_seconds": round(max(0, (now - last_dt).total_seconds()), 3),
                    "sleep_event_at": None,
                    "resume_event_at": None,
                    "power_events": [],
                }

            ended_at = parse_timestamp(gap.get("sleep_event_at")) or last_dt
            session["ended_at"] = format_timestamp(ended_at)
            session["end_reason"] = gap_end_reason(gap)
            append_session_event(session, gap)
            changed = True

        if changed:
            write_daily_log(path, data)


def resume_session(path, data, session, now, gap=None):
    session["ended_at"] = None
    session["end_reason"] = None
    session["resumed_at"] = format_timestamp(now)
    session["resume_count"] = int(session.get("resume_count") or 0) + 1
    if gap:
        append_session_event(session, gap)
    write_daily_log(path, data)
    write_current_session_pointer(path, session, updated_at=format_timestamp(now))
    return path, data, session


def start_or_resume_json_session(interval, configured_gap_threshold=None):
    now = datetime.now()
    path, data = open_daily_log(now)
    recover_old_unclosed_sessions(
        now,
        interval,
        configured_gap_threshold=configured_gap_threshold,
        exclude_path=path,
    )

    session = latest_session(data)
    if isinstance(session, dict) and not session.get("ended_at"):
        last_dt = session_last_activity(session)
        if last_dt is None:
            return resume_session(path, data, session, now)

        gap_seconds = max(0, (now - last_dt).total_seconds())
        if gap_seconds >= session_gap_threshold(interval, configured_gap_threshold):
            gap = describe_gap(last_dt, now, classification="app_downtime")
            if gap.get("sleep_event_at") or gap.get("resume_event_at"):
                ended_at = parse_timestamp(gap.get("sleep_event_at")) or last_dt
                close_json_session(path, data, session, ended_at, gap_end_reason(gap), gap)
                return start_json_session(
                    interval,
                    now=now,
                    start_reason=gap_start_reason(gap),
                    previous_gap=gap,
                )
            return resume_session(path, data, session, now, gap)

        return resume_session(path, data, session, now)

    return start_json_session(interval, now=now, start_reason="process_start")


def maybe_rotate_session(context, now, interval, configured_gap_threshold=None):
    path = context["path"]
    data = context["data"]
    session = context["session"]
    last_sample_at = context.get("last_sample_at")

    if last_sample_at is not None:
        gap_seconds = max(0, (now - last_sample_at).total_seconds())
        if gap_seconds >= session_gap_threshold(interval, configured_gap_threshold):
            gap = describe_gap(last_sample_at, now, classification="sampling_gap")
            ended_at = parse_timestamp(gap.get("sleep_event_at")) or last_sample_at
            close_json_session(path, data, session, ended_at, gap_end_reason(gap), gap)
            new_path, new_data, new_session = start_json_session(
                interval,
                now=now,
                start_reason=gap_start_reason(gap),
                previous_gap=gap,
            )
            return {
                "path": new_path,
                "data": new_data,
                "session": new_session,
                "last_sample_at": None,
            }

    expected_path = daily_log_path(now)
    if path != expected_path:
        rollover_at = datetime(now.year, now.month, now.day)
        event = {
            "type": "date_rollover",
            "timestamp": format_timestamp(rollover_at),
            "from_log_path": str(path),
            "to_log_path": str(expected_path),
        }
        close_json_session(path, data, session, rollover_at, "date_rollover", event)
        new_path, new_data, new_session = start_json_session(
            interval,
            now=rollover_at,
            start_reason="date_rollover",
        )
        return {
            "path": new_path,
            "data": new_data,
            "session": new_session,
            "last_sample_at": None,
        }

    return context


def number_or_none(value):
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def active_rate_direction(status):
    charge_rate = number_or_none(status.get("charge_rate_mW")) or 0
    discharge_rate = number_or_none(status.get("discharge_rate_mW")) or 0

    if status.get("charging"):
        return "charge"
    if status.get("power_online") is False:
        return "discharge"
    if charge_rate > 0:
        return "charge"
    if discharge_rate > 0:
        return "discharge"
    return None


def estimate_rate_from_capacity(status, session, direction):
    current_capacity = number_or_none(status.get("remaining_capacity_mWh"))
    current_dt = parse_timestamp(status.get("timestamp"))
    if current_capacity is None or current_dt is None:
        return None, None, None

    measurements = session.get("measurements", [])
    if not isinstance(measurements, list):
        return None, None, None

    for previous in reversed(measurements):
        if not isinstance(previous, dict) or not previous.get("status_available"):
            continue
        if active_rate_direction(previous) != direction:
            continue

        previous_capacity = number_or_none(previous.get("remaining_capacity_mWh"))
        previous_dt = parse_timestamp(previous.get("timestamp"))
        if previous_capacity is None or previous_dt is None:
            continue

        window_seconds = (current_dt - previous_dt).total_seconds()
        if window_seconds < RATE_ESTIMATE_MIN_WINDOW_SECONDS:
            continue
        if window_seconds > RATE_ESTIMATE_MAX_WINDOW_SECONDS:
            break

        capacity_delta = current_capacity - previous_capacity
        if direction == "discharge":
            capacity_delta = previous_capacity - current_capacity
        if capacity_delta < RATE_ESTIMATE_MIN_DELTA_MWH:
            continue

        rate_mw = capacity_delta / (window_seconds / 3600)
        confidence = "medium" if window_seconds <= 5 * 60 else "low"
        return int(round(rate_mw)), int(round(window_seconds)), confidence

    return None, None, None


def enrich_rate_information(status, session):
    status.setdefault("effective_charge_rate_mW", None)
    status.setdefault("effective_discharge_rate_mW", None)
    status.setdefault("rate_source", "unavailable")
    status.setdefault("rate_confidence", "none")
    status.setdefault("rate_window_seconds", None)

    if not status.get("status_available"):
        return status

    direction = active_rate_direction(status)
    charge_rate = number_or_none(status.get("charge_rate_mW"))
    discharge_rate = number_or_none(status.get("discharge_rate_mW"))

    if direction is None:
        status["effective_charge_rate_mW"] = 0 if charge_rate == 0 else charge_rate
        status["effective_discharge_rate_mW"] = 0 if discharge_rate == 0 else discharge_rate
        status["rate_source"] = "idle_or_full"
        status["rate_confidence"] = "none"
        return status

    raw_rate = charge_rate if direction == "charge" else discharge_rate
    if raw_rate is not None and raw_rate > 0:
        status["effective_charge_rate_mW"] = int(raw_rate) if direction == "charge" else 0
        status["effective_discharge_rate_mW"] = int(raw_rate) if direction == "discharge" else 0
        status["rate_source"] = "reported"
        status["rate_confidence"] = "high"
        status["rate_window_seconds"] = None
        return status

    estimate, window_seconds, confidence = estimate_rate_from_capacity(status, session, direction)
    if estimate is not None:
        status["effective_charge_rate_mW"] = estimate if direction == "charge" else 0
        status["effective_discharge_rate_mW"] = estimate if direction == "discharge" else 0
        status["rate_source"] = "estimated_capacity_delta"
        status["rate_confidence"] = confidence
        status["rate_window_seconds"] = window_seconds
        return status

    status["effective_charge_rate_mW"] = 0 if direction == "discharge" else charge_rate
    status["effective_discharge_rate_mW"] = 0 if direction == "charge" else discharge_rate
    status["rate_source"] = "missing_rate"
    status["rate_confidence"] = "none"
    return status


def record_measurement(path, data, session, status):
    session["measurements"].append(status)
    session["last_updated_at"] = status["timestamp"]
    session["last_write_error"] = None
    try:
        write_daily_log(path, data)
        write_current_session_pointer(path, session, updated_at=status["timestamp"])
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


def format_rate_for_console(status, raw_key, effective_key):
    raw = status.get(raw_key)
    effective = status.get(effective_key)
    if raw is not None and raw > 0:
        return format_value(raw, "mW")
    if (
        effective is not None
        and effective > 0
        and status.get("rate_source") == "estimated_capacity_delta"
    ):
        return f"~{effective} mW"
    return format_value(raw, "mW")


def format_power_state(status):
    if status.get("charging"):
        return "Charging"
    if status.get("power_online"):
        return "Plugged in"
    return "Discharging"


def format_status(status):
    if not status["status_available"]:
        return f"[{status['timestamp']}] Battery status unavailable: {status['read_error']}"

    return (f"[{status['timestamp']}] "
            f"{format_power_state(status)} | "
            f"Charge Rate: {format_rate_for_console(status, 'charge_rate_mW', 'effective_charge_rate_mW')} | "
            f"Discharge Rate: {format_rate_for_console(status, 'discharge_rate_mW', 'effective_discharge_rate_mW')} | "
            f"Remaining: {status['remaining_capacity_mWh']} mWh | "
            f"Voltage: {status['voltage_mV']} mV | "
            f"Rate Source: {status.get('rate_source')}")


def parse_args():
    parser = argparse.ArgumentParser(description="Monitor laptop charge and discharge rate.")
    parser.add_argument("--interval", type=float, default=2, help="Seconds between samples.")
    parser.add_argument(
        "--gap-threshold",
        type=float,
        help="Seconds without samples before starting a new wake/gap session. Defaults to max(60, interval * 5).",
    )
    parser.add_argument("--overlay", dest="show_overlay", action="store_true", default=True)
    parser.add_argument("--no-overlay", dest="show_overlay", action="store_false")
    return parser.parse_args()


def log_battery_status(interval=5, show_overlay=True, gap_threshold=None):
    log_path, data, session = start_or_resume_json_session(
        interval,
        configured_gap_threshold=gap_threshold,
    )
    context = {
        "path": log_path,
        "data": data,
        "session": session,
        "last_sample_at": session_last_activity(session),
    }
    overlay_process = start_overlay() if show_overlay else None

    print(f"Monitoring battery. Writing every {interval}s sample to {log_path}.")
    print(f"Active session #{session['session_id']} ({session.get('start_reason', 'process_start')}).")
    print("Console output appears only when a monitored value changes.")
    if overlay_process:
        print("Overlay started.")
    print("Press Ctrl+C to stop.\n")

    previous_values = None
    previous_write_error = None
    try:
        while True:
            previous_path = context["path"]
            previous_session_id = context["session"].get("session_id")
            context = maybe_rotate_session(
                context,
                datetime.now(),
                interval,
                configured_gap_threshold=gap_threshold,
            )
            if (
                context["path"] != previous_path
                or context["session"].get("session_id") != previous_session_id
            ):
                print(
                    f"[{timestamp_now()}] Started session "
                    f"#{context['session'].get('session_id')} in {context['path']} "
                    f"({context['session'].get('start_reason')})."
                )

            status = get_battery_status()
            status = enrich_rate_information(status, context["session"])
            write_error = record_measurement(
                context["path"],
                context["data"],
                context["session"],
                status,
            )
            context["last_sample_at"] = parse_timestamp(status.get("timestamp")) or datetime.now()
            if write_error and write_error != previous_write_error:
                print(f"[{status['timestamp']}] JSON write hiccup: {write_error}")
            previous_write_error = write_error

            current_values = value_fingerprint(status)
            if current_values != previous_values:
                print(format_status(status))
                previous_values = current_values

            time.sleep(interval)
    except KeyboardInterrupt:
        final_write_failed = False
        try:
            close_json_session(
                context["path"],
                context["data"],
                context["session"],
                datetime.now(),
                "process_stop",
            )
        except OSError as error:
            final_write_failed = True
            print(f"\nStopped, but final JSON write failed: {type(error).__name__}: {error}")
        if overlay_process and overlay_process.poll() is None:
            overlay_process.terminate()
        if not final_write_failed:
            print(f"\nStopped. Final JSON written to {context['path']}.")

if __name__ == "__main__":
    args = parse_args()
    log_battery_status(
        interval=args.interval,
        show_overlay=args.show_overlay,
        gap_threshold=args.gap_threshold,
    )
