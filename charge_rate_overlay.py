import argparse
import json
from datetime import datetime
from pathlib import Path
import tkinter as tk


REPO_ROOT = Path(__file__).resolve().parent
LOG_DIR = REPO_ROOT / "logs"
CURRENT_SESSION_PATH = LOG_DIR / "_current_session.json"
TIMESTAMP_FORMAT = "%Y-%m-%d %H:%M:%S"
STALE_AFTER_SECONDS = 10

MONITORED_VALUE_KEYS = (
    "status_available",
    "charge_rate_mW",
    "discharge_rate_mW",
    "effective_charge_rate_mW",
    "effective_discharge_rate_mW",
    "rate_source",
    "rate_confidence",
    "rate_window_seconds",
    "remaining_capacity_mWh",
    "full_charged_capacity_mWh",
    "voltage_mV",
    "charging",
    "power_online",
)
NO_DATA = ("no-data",)
CHARGING_ETA_LABEL = "⬆"
DISCHARGING_ETA_LABEL = "⬇"

_BG = "#101820"
_BORDER = "#5eead4"
_CHARGE_LINE = "#86efac"
_CHARGE_FILL = "#14532d"
_DISCHARGE_LINE = "#fb923c"
_DISCHARGE_FILL = "#431407"
_GRID = "#1e3a4a"
_AXIS = "#334155"
_DIM = "#64748b"

GRAPH_MAX_SAMPLES = 120


def today_log_path():
    now = datetime.now()
    filename = f"{now.month}-{now.day}-{now.strftime('%y')}_charge_rates.json"
    return LOG_DIR / filename


def parse_args():
    parser = argparse.ArgumentParser(description="Small live overlay for charge rate readings.")
    parser.add_argument("--log-path", type=Path)
    parser.add_argument("--session-id", type=int)
    parser.add_argument(
        "--follow-current",
        action="store_true",
        help="Follow logs/_current_session.json. This is the default when --log-path is omitted.",
    )
    parser.add_argument("--poll-ms", type=int, default=500)
    return parser.parse_args()


def load_current_session_target():
    try:
        with CURRENT_SESSION_PATH.open("r", encoding="utf-8") as f:
            data = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return None

    log_path = data.get("log_path")
    if not log_path:
        return None

    path = Path(log_path)
    if not path.is_absolute():
        path = REPO_ROOT / path
    return path, data.get("session_id")


def _load_session(log_path, session_id):
    try:
        with log_path.open("r", encoding="utf-8") as f:
            data = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return None

    sessions = data.get("sessions")
    if not isinstance(sessions, list) or not sessions:
        return None

    if session_id is None:
        return sessions[-1] if isinstance(sessions[-1], dict) else None

    for candidate in reversed(sessions):
        if isinstance(candidate, dict) and candidate.get("session_id") == session_id:
            return candidate
    return None


def read_latest_measurement(log_path, session_id=None):
    session = _load_session(log_path, session_id)
    if session is None:
        return None
    measurements = session.get("measurements")
    if not isinstance(measurements, list) or not measurements:
        return None
    latest = measurements[-1]
    return latest if isinstance(latest, dict) else None


def read_session_measurements(log_path, session_id=None):
    session = _load_session(log_path, session_id)
    if session is None:
        return []
    measurements = session.get("measurements")
    if not isinstance(measurements, list):
        return []
    return [m for m in measurements if isinstance(m, dict)]


def read_all_sessions(log_path):
    """Returns list of all session dicts from the daily log."""
    try:
        with log_path.open("r", encoding="utf-8") as f:
            data = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return []
    sessions = data.get("sessions")
    return [s for s in sessions if isinstance(s, dict)] if isinstance(sessions, list) else []


def value_fingerprint(measurement):
    if measurement is None:
        return NO_DATA
    return tuple(measurement.get(key) for key in MONITORED_VALUE_KEYS)


def format_value(value, suffix):
    if value is None:
        return "null"
    return f"{value} {suffix}"


def format_timestamp(value):
    if not value:
        return ""

    for parser in (
        lambda t: datetime.strptime(t, TIMESTAMP_FORMAT),
        datetime.fromisoformat,
    ):
        try:
            dt = parser(value)
            return f"{dt.strftime('%Y-%m-%d')} {dt.strftime('%I:%M:%S %p').lstrip('0')}"
        except (TypeError, ValueError):
            continue

    return value


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


def measurement_age_seconds(measurement):
    if measurement is None:
        return None
    timestamp = parse_timestamp(measurement.get("timestamp"))
    if timestamp is None:
        return None
    return max(0, (datetime.now() - timestamp).total_seconds())


def format_age(seconds):
    if seconds is None:
        return ""
    seconds = int(seconds)
    if seconds < 60:
        return f"{seconds}s"
    minutes, sec = divmod(seconds, 60)
    if minutes < 60:
        return f"{minutes}m {sec}s" if sec else f"{minutes}m"
    hours, minutes = divmod(minutes, 60)
    return f"{hours}h {minutes}m" if minutes else f"{hours}h"


def stale_bucket(measurement):
    age = measurement_age_seconds(measurement)
    if age is None or age < STALE_AFTER_SECONDS:
        return 0
    return int(age // 5)


def number_or_none(value):
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def format_duration(hours):
    if hours <= 0:
        return "now"

    total_minutes = max(1, round(hours * 60))
    days, day_minutes = divmod(total_minutes, 24 * 60)
    hours_part, minutes_part = divmod(day_minutes, 60)

    if days:
        return f"{days}d {hours_part}h"
    if hours_part:
        return f"{hours_part}h {minutes_part}m" if minutes_part else f"{hours_part}h"
    return f"{minutes_part}m"


def active_rate_direction(measurement):
    charge_rate = number_or_none(measurement.get("charge_rate_mW")) or 0
    discharge_rate = number_or_none(measurement.get("discharge_rate_mW")) or 0
    effective_charge = number_or_none(measurement.get("effective_charge_rate_mW")) or 0
    effective_discharge = number_or_none(measurement.get("effective_discharge_rate_mW")) or 0

    if measurement.get("charging"):
        return "charge"
    if measurement.get("power_online") is False:
        return "discharge"
    if charge_rate > 0 or effective_charge > 0:
        return "charge"
    if discharge_rate > 0 or effective_discharge > 0:
        return "discharge"
    return None


def rate_for_direction(measurement, direction):
    raw_key = "charge_rate_mW" if direction == "charge" else "discharge_rate_mW"
    effective_key = (
        "effective_charge_rate_mW"
        if direction == "charge"
        else "effective_discharge_rate_mW"
    )
    raw = number_or_none(measurement.get(raw_key))
    effective = number_or_none(measurement.get(effective_key))
    if raw is not None and raw > 0:
        return raw, False
    if effective is not None and effective > 0:
        return effective, measurement.get("rate_source") != "reported"
    return raw, False


def format_rate_field(measurement, raw_key, effective_key):
    raw = number_or_none(measurement.get(raw_key))
    effective = number_or_none(measurement.get(effective_key))
    if raw is not None and raw > 0:
        return format_value(int(raw), "mW")
    if (
        effective is not None
        and effective > 0
        and measurement.get("rate_source") == "estimated_capacity_delta"
    ):
        return f"~{int(effective)} mW"
    return format_value(measurement.get(raw_key), "mW")


def format_measurement_timestamp(measurement):
    timestamp = format_timestamp(measurement.get("timestamp"))
    age = measurement_age_seconds(measurement)
    if age is not None and age >= STALE_AFTER_SECONDS:
        return f"{timestamp} ({format_age(age)} old)"
    return timestamp


def calculate_eta(measurement):
    if measurement is None or not measurement.get("status_available"):
        return "--"

    direction = active_rate_direction(measurement)
    if direction is None:
        return "--"

    charging = direction == "charge"
    label = CHARGING_ETA_LABEL if charging else DISCHARGING_ETA_LABEL
    remaining = number_or_none(measurement.get("remaining_capacity_mWh"))
    full_capacity = number_or_none(measurement.get("full_charged_capacity_mWh"))
    rate, estimated = rate_for_direction(measurement, direction)

    if remaining is None or full_capacity is None or full_capacity <= 0:
        return f"{label} null"
    if rate is None or rate <= 0:
        return f"{label} null"

    target_capacity = full_capacity if charging else full_capacity * 0.10
    capacity_delta = target_capacity - remaining if charging else remaining - target_capacity
    prefix = "~" if estimated else ""
    return f"{label} {prefix}{format_duration(capacity_delta / rate)}"


def _nice_y_axis(max_val_mw):
    """Return (axis_max_mw, tick_step_mw) rounded to clean W boundaries."""
    if max_val_mw <= 0:
        return 5000, 1000
    max_w = max_val_mw / 1000
    if max_w <= 5:
        step_w = 1
    elif max_w <= 20:
        step_w = 5
    elif max_w <= 60:
        step_w = 10
    else:
        step_w = 25
    axis_max_w = (int(max_w / step_w) + 1) * step_w
    return axis_max_w * 1000, step_w * 1000


def _cap_y_axis(min_cap, max_cap):
    """Return (y_min, y_max, tick_step) in mWh for a mWh capacity range."""
    if max_cap <= min_cap:
        min_cap, max_cap = min_cap - 500, min_cap + 500
    raw_step = (max_cap - min_cap) / 4
    for step_wh in (0.5, 1, 2, 5, 10, 20, 50, 100, 200):
        if raw_step <= step_wh * 1000:
            step = int(step_wh * 1000)
            break
    else:
        step = 200000
    y_min = (min_cap // step) * step
    y_max = (max_cap // step + 1) * step
    return y_min, y_max, step


class ChargeRateGraph:
    CW = 370    # canvas width
    CH = 158    # canvas height
    PL = 46     # left pad (Y labels)
    PR = 12     # right pad
    PT = 12     # top pad
    PB = 26     # bottom pad (X labels)

    def __init__(self, parent_root, log_path, session_id, poll_ms):
        self.log_path = log_path
        self.session_id = session_id
        self.poll_ms = poll_ms
        self._destroyed = False
        self.drag_offset_x = 0
        self.drag_offset_y = 0

        self.window = tk.Toplevel(parent_root)
        self.window.title("Charge Rate Graph")
        self.window.overrideredirect(True)
        self.window.configure(bg=_BG)
        self.window.bind("<Escape>", lambda _e: self.destroy())
        self.window.bind("<Button-3>", lambda _e: self.destroy())
        self.window.protocol("WM_DELETE_WINDOW", self.destroy)

        for attr, val in (("-topmost", True), ("-alpha", 0.76)):
            try:
                self.window.attributes(attr, val)
            except tk.TclError:
                pass

        frame = tk.Frame(
            self.window, bg=_BG,
            highlightbackground=_BORDER, highlightthickness=1,
        )
        frame.pack(fill="both", expand=True)

        header = tk.Frame(frame, bg=_BG, padx=10, pady=6)
        header.pack(fill="x")

        close_btn = tk.Label(
            header, text="x", bg=_BG, fg="#94a3b8",
            font=("Segoe UI", 9, "bold"), padx=4, cursor="hand2",
        )
        close_btn.pack(side="right")
        close_btn.bind("<Button-1>", lambda _e: self.destroy())

        tk.Label(
            header, text="Rate History", bg=_BG, fg="#f8fafc",
            font=("Segoe UI", 9, "bold"), anchor="w",
        ).pack(side="left")
        tk.Label(
            header, text="● charge", bg=_BG, fg=_CHARGE_LINE,
            font=("Segoe UI", 8),
        ).pack(side="left", padx=(10, 0))
        tk.Label(
            header, text="● discharge", bg=_BG, fg=_DISCHARGE_LINE,
            font=("Segoe UI", 8),
        ).pack(side="left", padx=(6, 0))

        self.canvas = tk.Canvas(
            frame, width=self.CW, height=self.CH,
            bg=_BG, highlightthickness=0,
        )
        self.canvas.pack(pady=(0, 6))

        for widget in (self.window, frame, header, self.canvas):
            self._bind_drag(widget)
        for child in header.winfo_children():
            self._bind_drag(child)

        self.window.update_idletasks()
        self._place_beside_overlay()

    def _bind_drag(self, widget):
        widget.bind("<ButtonPress-1>", self._start_drag, add="+")
        widget.bind("<B1-Motion>", self._do_drag, add="+")

    def _start_drag(self, event):
        self.drag_offset_x = event.x_root - self.window.winfo_x()
        self.drag_offset_y = event.y_root - self.window.winfo_y()

    def _do_drag(self, event):
        self.window.geometry(
            f"+{event.x_root - self.drag_offset_x}+{event.y_root - self.drag_offset_y}"
        )

    def _place_beside_overlay(self):
        x = 18 + 260 + 10
        screen_height = self.window.winfo_screenheight()
        win_h = self.window.winfo_reqheight() or 220
        y = max(18, screen_height - win_h - 72)
        self.window.geometry(f"+{x}+{y}")

    def is_alive(self):
        if self._destroyed:
            return False
        try:
            return bool(self.window.winfo_exists())
        except tk.TclError:
            return False

    def destroy(self):
        self._destroyed = True
        try:
            self.window.destroy()
        except tk.TclError:
            pass

    def refresh(self):
        if not self.is_alive():
            return
        measurements = read_session_measurements(self.log_path, self.session_id)
        self._draw(measurements)

    def _draw(self, measurements):
        c = self.canvas
        c.delete("all")

        pw = self.CW - self.PL - self.PR
        ph = self.CH - self.PT - self.PB

        valid = [
            m for m in measurements
            if isinstance(m, dict) and m.get("status_available")
        ][-GRAPH_MAX_SAMPLES:]

        if len(valid) < 2:
            c.create_text(
                self.CW // 2, self.CH // 2,
                text="Collecting data…",
                fill="#94a3b8", font=("Segoe UI", 9),
            )
            return

        charges = [rate_for_direction(m, "charge")[0] or 0 for m in valid]
        discharges = [rate_for_direction(m, "discharge")[0] or 0 for m in valid]
        timestamps = [m.get("timestamp", "") for m in valid]
        n = len(valid)

        axis_max, tick_step = _nice_y_axis(max(max(charges), max(discharges)))

        def xp(i):
            return self.PL + (i / (n - 1)) * pw

        def yp(rate):
            return self.PT + ph * (1.0 - rate / axis_max)

        # Horizontal grid lines + Y labels
        tick = 0
        while tick <= axis_max:
            y = yp(tick)
            c.create_line(self.PL, y, self.PL + pw, y, fill=_GRID, width=1)
            label = f"{tick // 1000}W" if tick >= 1000 else f"{tick}mW"
            c.create_text(self.PL - 4, y, text=label, fill=_DIM,
                          font=("Segoe UI", 7), anchor="e")
            tick += tick_step

        # X time ticks (up to 5 evenly spaced)
        tick_count = min(5, n)
        for k in range(tick_count):
            i = round(k * (n - 1) / max(tick_count - 1, 1))
            x = xp(i)
            ts = timestamps[i]
            try:
                label = datetime.strptime(ts, "%Y-%m-%d %H:%M:%S").strftime("%H:%M")
            except (ValueError, TypeError):
                label = ""
            c.create_line(x, self.PT + ph, x, self.PT + ph + 3, fill=_DIM, width=1)
            c.create_text(x, self.PT + ph + 13, text=label, fill=_DIM,
                          font=("Segoe UI", 7), anchor="center")

        # Area fill + line for each series
        for series, fill_color, line_color in (
            (charges, _CHARGE_FILL, _CHARGE_LINE),
            (discharges, _DISCHARGE_FILL, _DISCHARGE_LINE),
        ):
            if not any(r > 0 for r in series):
                continue
            base_y = self.PT + ph
            fill_pts = (
                [(xp(0), base_y)]
                + [(xp(i), yp(r)) for i, r in enumerate(series)]
                + [(xp(n - 1), base_y)]
            )
            c.create_polygon(
                [coord for pt in fill_pts for coord in pt],
                fill=fill_color, outline="",
            )
            line_pts = [coord for i, r in enumerate(series) for coord in (xp(i), yp(r))]
            c.create_line(line_pts, fill=line_color, width=1, joinstyle="round")

        # Axis lines
        c.create_line(self.PL, self.PT, self.PL, self.PT + ph, fill=_AXIS, width=1)
        c.create_line(self.PL, self.PT + ph, self.PL + pw, self.PT + ph, fill=_AXIS, width=1)

        # Current-value dots at the right edge
        for rate, color in ((charges[-1], _CHARGE_LINE), (discharges[-1], _DISCHARGE_LINE)):
            if rate > 0:
                cx, cy = xp(n - 1), yp(rate)
                c.create_oval(cx - 3, cy - 3, cx + 3, cy + 3, fill=color, outline="")


class ChargeDayView:
    CW = 468
    CHART_H = 148
    PL = 52
    PR = 12
    PT = 12
    PB = 28
    ROW_H = 21
    MAX_ROWS = 6

    def __init__(self, parent_root, log_path, current_session_id, poll_ms):
        self.log_path = log_path
        self.current_session_id = current_session_id
        self.poll_ms = poll_ms
        self._destroyed = False
        self.drag_offset_x = 0
        self.drag_offset_y = 0

        canvas_h = self.CHART_H + 14 + self.MAX_ROWS * self.ROW_H + 6

        self.window = tk.Toplevel(parent_root)
        self.window.title("Day View")
        self.window.overrideredirect(True)
        self.window.configure(bg=_BG)
        self.window.bind("<Escape>", lambda _e: self.destroy())
        self.window.bind("<Button-3>", lambda _e: self.destroy())
        self.window.protocol("WM_DELETE_WINDOW", self.destroy)

        for attr, val in (("-topmost", True), ("-alpha", 0.76)):
            try:
                self.window.attributes(attr, val)
            except tk.TclError:
                pass

        frame = tk.Frame(
            self.window, bg=_BG,
            highlightbackground=_BORDER, highlightthickness=1,
        )
        frame.pack(fill="both", expand=True)

        header = tk.Frame(frame, bg=_BG, padx=10, pady=6)
        header.pack(fill="x")

        close_btn = tk.Label(
            header, text="x", bg=_BG, fg="#94a3b8",
            font=("Segoe UI", 9, "bold"), padx=4, cursor="hand2",
        )
        close_btn.pack(side="right")
        close_btn.bind("<Button-1>", lambda _e: self.destroy())

        try:
            today = datetime.now().strftime("%b %#d")  # Windows: no leading zero
        except ValueError:
            today = datetime.now().strftime("%b %d")

        tk.Label(
            header, text=f"Day View — {today}", bg=_BG, fg="#f8fafc",
            font=("Segoe UI", 9, "bold"), anchor="w",
        ).pack(side="left")
        tk.Label(
            header, text="● charge", bg=_BG, fg=_CHARGE_LINE,
            font=("Segoe UI", 8),
        ).pack(side="left", padx=(10, 0))
        tk.Label(
            header, text="● discharge", bg=_BG, fg=_DISCHARGE_LINE,
            font=("Segoe UI", 8),
        ).pack(side="left", padx=(6, 0))

        self.canvas = tk.Canvas(
            frame, width=self.CW, height=canvas_h,
            bg=_BG, highlightthickness=0,
        )
        self.canvas.pack(pady=(0, 6))

        for widget in (self.window, frame, header, self.canvas):
            self._bind_drag(widget)
        for child in header.winfo_children():
            self._bind_drag(child)

        self.window.update_idletasks()
        self._place_above_overlay()

    def _bind_drag(self, widget):
        widget.bind("<ButtonPress-1>", self._start_drag, add="+")
        widget.bind("<B1-Motion>", self._do_drag, add="+")

    def _start_drag(self, event):
        self.drag_offset_x = event.x_root - self.window.winfo_x()
        self.drag_offset_y = event.y_root - self.window.winfo_y()

    def _do_drag(self, event):
        self.window.geometry(
            f"+{event.x_root - self.drag_offset_x}+{event.y_root - self.drag_offset_y}"
        )

    def _place_above_overlay(self):
        x = 18
        sh = self.window.winfo_screenheight()
        overlay_y = max(18, sh - 158 - 72)
        win_h = self.window.winfo_reqheight() or 320
        y = max(18, overlay_y - win_h - 10)
        self.window.geometry(f"+{x}+{y}")

    def is_alive(self):
        if self._destroyed:
            return False
        try:
            return bool(self.window.winfo_exists())
        except tk.TclError:
            return False

    def destroy(self):
        self._destroyed = True
        try:
            self.window.destroy()
        except tk.TclError:
            pass

    def refresh(self):
        if not self.is_alive():
            return
        self._draw(read_all_sessions(self.log_path))

    def _draw(self, sessions):
        c = self.canvas
        c.delete("all")

        # Build (session, [valid_measurements]) pairs
        session_data = []
        for s in sessions:
            ms = [
                m for m in s.get("measurements", [])
                if isinstance(m, dict)
                and m.get("status_available")
                and m.get("timestamp")
                and m.get("remaining_capacity_mWh") is not None
            ]
            if ms:
                session_data.append((s, ms))

        if not session_data:
            c.create_text(self.CW // 2, self.CHART_H // 2,
                         text="No data yet", fill="#94a3b8", font=("Segoe UI", 9))
            return

        pl, pr, pt, pb = self.PL, self.PR, self.PT, self.PB
        pw = self.CW - pl - pr
        ph = self.CHART_H - pt - pb

        # Time and capacity bounds across all sessions
        try:
            first_dt = datetime.strptime(
                session_data[0][1][0]["timestamp"], "%Y-%m-%d %H:%M:%S"
            )
            last_dt = datetime.strptime(
                session_data[-1][1][-1]["timestamp"], "%Y-%m-%d %H:%M:%S"
            )
        except (ValueError, KeyError):
            return

        total_secs = max((last_dt - first_dt).total_seconds(), 60)

        all_caps = [m["remaining_capacity_mWh"] for _, ms in session_data for m in ms]
        y_min, y_max, tick_step = _cap_y_axis(min(all_caps), max(all_caps))

        def xp(dt):
            return pl + (dt - first_dt).total_seconds() / total_secs * pw

        def yp(cap):
            return pt + ph * (1.0 - (cap - y_min) / max(y_max - y_min, 1))

        # Horizontal grid + Y labels
        tick = y_min
        while tick <= y_max:
            y = yp(tick)
            if pt - 1 <= y <= pt + ph + 1:
                c.create_line(pl, y, pl + pw, y, fill=_GRID, width=1)
                wh = tick / 1000
                if tick_step >= 1000:
                    label = f"{int(wh)}Wh"
                elif tick_step == 500:
                    label = f"{wh:.1f}Wh"
                else:
                    label = f"{tick}mWh"
                c.create_text(pl - 4, y, text=label, fill=_DIM,
                              font=("Segoe UI", 7), anchor="e")
            tick += tick_step

        # X time labels (up to 5)
        n_ticks = min(5, max(2, len(session_data)))
        for k in range(n_ticks):
            frac = k / max(n_ticks - 1, 1)
            secs = frac * total_secs
            tick_dt = datetime.fromtimestamp(first_dt.timestamp() + secs)
            x = pl + frac * pw
            c.create_line(x, pt + ph, x, pt + ph + 3, fill=_DIM, width=1)
            c.create_text(x, pt + ph + 13, text=tick_dt.strftime("%H:%M"),
                         fill=_DIM, font=("Segoe UI", 7), anchor="center")

        # Draw capacity line per session (color by charging state)
        for _session, ms in session_data:
            stride = max(1, len(ms) // 300)
            sampled = ms[::stride]
            if sampled[-1] is not ms[-1]:
                sampled = sampled + [ms[-1]]

            prev_x = prev_y = None
            batch_pts = []
            batch_color = None

            for m in sampled:
                try:
                    dt = datetime.strptime(m["timestamp"], "%Y-%m-%d %H:%M:%S")
                except ValueError:
                    continue
                cap = m.get("remaining_capacity_mWh")
                if cap is None:
                    continue
                color = _CHARGE_LINE if m.get("charging") else _DISCHARGE_LINE
                x, y = xp(dt), yp(cap)

                if prev_x is None:
                    batch_pts = [x, y]
                    batch_color = color
                elif color != batch_color:
                    if len(batch_pts) >= 4:
                        c.create_line(batch_pts, fill=batch_color, width=1.5)
                    batch_pts = [prev_x, prev_y, x, y]
                    batch_color = color
                else:
                    batch_pts.extend([x, y])
                prev_x, prev_y = x, y

            if len(batch_pts) >= 4:
                c.create_line(batch_pts, fill=batch_color, width=1.5)

            # Session start tick
            try:
                sx = xp(datetime.strptime(ms[0]["timestamp"], "%Y-%m-%d %H:%M:%S"))
                c.create_line(sx, pt, sx, pt + ph, fill=_AXIS, width=1, dash=(2, 4))
            except (ValueError, KeyError):
                pass

        # Axes
        c.create_line(pl, pt, pl, pt + ph, fill=_AXIS, width=1)
        c.create_line(pl, pt + ph, pl + pw, pt + ph, fill=_AXIS, width=1)

        # ── Session rows ──────────────────────────────────────────────
        sep_y = self.CHART_H + 6
        c.create_line(pl, sep_y, pl + pw, sep_y, fill=_AXIS, width=1)

        if len(session_data) > self.MAX_ROWS:
            extra = len(session_data) - self.MAX_ROWS
            c.create_text(pl + pw, sep_y - 3, text=f"({extra} older not shown)",
                         fill=_DIM, font=("Segoe UI", 7), anchor="e")

        row_y = self.CHART_H + 14
        for session, ms in session_data[-self.MAX_ROWS:][::-1]:
            sid = session.get("session_id", "?")
            is_current = (sid == self.current_session_id and not session.get("ended_at"))

            start_cap = ms[0].get("remaining_capacity_mWh")
            end_cap = ms[-1].get("remaining_capacity_mWh")
            net_mwh = (end_cap - start_cap) if (start_cap and end_cap) else None

            charging_count = sum(1 for m in ms if m.get("charging"))
            is_mostly_charging = charging_count > len(ms) / 2
            dot_color = _CHARGE_LINE if is_mostly_charging else _DISCHARGE_LINE

            started_at = session.get("started_at", "")
            ended_at = session.get("ended_at")
            try:
                start_str = datetime.strptime(started_at, "%Y-%m-%d %H:%M:%S").strftime("%H:%M")
            except (ValueError, TypeError):
                start_str = "?"
            if ended_at:
                try:
                    end_str = datetime.strptime(ended_at, "%Y-%m-%d %H:%M:%S").strftime("%H:%M")
                except (ValueError, TypeError):
                    end_str = "?"
                time_range = f"{start_str}–{end_str}"
            else:
                time_range = f"{start_str}–now"

            n_samples = len(ms)
            interval = session.get("interval_seconds", 5)
            dur_mins = max(1, n_samples * interval // 60)
            dur_str = f"{dur_mins}m" if dur_mins < 60 else f"{dur_mins // 60}h {dur_mins % 60}m"

            cy = row_y + self.ROW_H // 2
            text_color = "#f8fafc" if is_current else "#94a3b8"
            bold = "bold" if is_current else "normal"

            c.create_oval(pl + 1, cy - 3, pl + 7, cy + 3, fill=dot_color, outline="")
            c.create_text(pl + 13, cy, anchor="w", text=f"#{sid}",
                         fill=text_color, font=("Segoe UI", 8, bold))
            c.create_text(pl + 36, cy, anchor="w", text=time_range,
                         fill=text_color, font=("Segoe UI", 8))
            c.create_text(pl + 132, cy, anchor="w", text=dur_str,
                         fill=_DIM, font=("Segoe UI", 8))

            if net_mwh is not None:
                wh = net_mwh / 1000
                net_color = _CHARGE_LINE if net_mwh >= 0 else _DISCHARGE_LINE
                c.create_text(pl + 172, cy, anchor="w", text=f"{wh:+.1f}Wh",
                             fill=net_color, font=("Segoe UI", 8, "bold"))

            relevant = [m for m in ms if bool(m.get("charging")) == is_mostly_charging]
            if relevant:
                direction = "charge" if is_mostly_charging else "discharge"
                avg_w = (
                    sum(rate_for_direction(m, direction)[0] or 0 for m in relevant)
                    / len(relevant)
                    / 1000
                )
                c.create_text(pl + 232, cy, anchor="w", text=f"~{avg_w:.1f}W",
                             fill=_DIM, font=("Segoe UI", 8))

            if is_current:
                c.create_text(pl + 290, cy, anchor="w", text="● live",
                             fill=dot_color, font=("Segoe UI", 7, "bold"))

            row_y += self.ROW_H


class ChargeRateOverlay:
    def __init__(self, log_path, session_id, poll_ms, follow_current=False):
        self.fixed_log_path = log_path or today_log_path()
        self.fixed_session_id = session_id
        self.follow_current = follow_current
        self.log_path = self.fixed_log_path
        self.session_id = self.fixed_session_id
        self.poll_ms = poll_ms
        self.previous_values = None
        self.drag_offset_x = 0
        self.drag_offset_y = 0
        self.graph_window = None
        self.day_view = None

        self.root = tk.Tk()
        self.root.title("Charge Rate")
        self.root.overrideredirect(True)
        self.root.configure(bg="#101820")
        self.root.bind("<Escape>", lambda _event: self.root.destroy())
        self.root.bind("<Button-3>", lambda _event: self.root.destroy())
        self.root.protocol("WM_DELETE_WINDOW", self.root.destroy)

        for attribute, value in (("-topmost", True), ("-alpha", 0.76)):
            try:
                self.root.attributes(attribute, value)
            except tk.TclError:
                pass

        self.panel = tk.Frame(
            self.root,
            bg="#101820",
            highlightbackground="#5eead4",
            highlightthickness=1,
            padx=12,
            pady=10,
        )
        self.panel.pack(fill="both", expand=True)

        header = tk.Frame(self.panel, bg="#101820")
        header.pack(fill="x")

        self.state_label = tk.Label(
            header,
            text="Waiting",
            bg="#101820",
            fg="#f8fafc",
            font=("Segoe UI", 10, "bold"),
            anchor="w",
        )
        self.state_label.pack(side="left")

        # Right-side buttons (pack order: rightmost first)
        close_button = tk.Label(
            header,
            text="x",
            bg="#101820",
            fg="#94a3b8",
            font=("Segoe UI", 9, "bold"),
            padx=4,
            cursor="hand2",
        )
        close_button.pack(side="right")
        close_button.bind("<Button-1>", lambda _event: self.root.destroy())

        self.graph_button = tk.Label(
            header,
            text="≋",
            bg="#101820",
            fg="#5eead4",
            font=("Segoe UI", 10, "bold"),
            padx=4,
            cursor="hand2",
        )
        self.graph_button.pack(side="right")
        self.graph_button.bind("<Button-1>", lambda _event: self._toggle_graph())

        self.day_button = tk.Label(
            header,
            text="≡",
            bg="#101820",
            fg="#5eead4",
            font=("Segoe UI", 10, "bold"),
            padx=4,
            cursor="hand2",
        )
        self.day_button.pack(side="right")
        self.day_button.bind("<Button-1>", lambda _event: self._toggle_day_view())

        self.eta_label = tk.Label(
            header,
            text="--",
            bg="#101820",
            fg="#f8fafc",
            font=("Segoe UI Emoji", 9, "bold"),
            anchor="e",
        )
        self.eta_label.pack(side="left", fill="x", expand=True, padx=(8, 4))

        self.timestamp_label = tk.Label(
            self.panel,
            text="",
            bg="#101820",
            fg="#94a3b8",
            font=("Segoe UI", 8),
            anchor="w",
        )
        self.timestamp_label.pack(fill="x", pady=(2, 6))

        self.fields = {}
        for key, label in (
            ("charge_rate_mW", "Charge"),
            ("discharge_rate_mW", "Discharge"),
            ("remaining_capacity_mWh", "Remaining"),
            ("voltage_mV", "Voltage"),
            ("power_online", "Power"),
        ):
            row = tk.Frame(self.panel, bg="#101820")
            row.pack(fill="x", pady=1)

            name = tk.Label(
                row,
                text=label,
                bg="#101820",
                fg="#cbd5e1",
                font=("Segoe UI", 9),
                anchor="w",
                width=10,
            )
            name.pack(side="left")

            value = tk.Label(
                row,
                text="--",
                bg="#101820",
                fg="#f8fafc",
                font=("Segoe UI", 9, "bold"),
                anchor="e",
            )
            value.pack(side="right", fill="x", expand=True)
            self.fields[key] = value

        self._bind_drag(self.root)
        self._bind_drag(self.panel)
        self._bind_drag(header)
        self._bind_drag(self.state_label)
        self._bind_drag(self.timestamp_label)
        for child in self.panel.winfo_children():
            self._bind_drag(child)
            for grandchild in child.winfo_children():
                self._bind_drag(grandchild)

        self.root.update_idletasks()
        self._place_bottom_left()

    def _bind_drag(self, widget):
        widget.bind("<ButtonPress-1>", self._start_drag, add="+")
        widget.bind("<B1-Motion>", self._drag, add="+")

    def _start_drag(self, event):
        self.drag_offset_x = event.x_root - self.root.winfo_x()
        self.drag_offset_y = event.y_root - self.root.winfo_y()

    def _drag(self, event):
        x = event.x_root - self.drag_offset_x
        y = event.y_root - self.drag_offset_y
        self.root.geometry(f"+{x}+{y}")

    def _place_bottom_left(self):
        width = 260
        height = 158
        margin_x = 18
        margin_bottom = 72
        screen_height = self.root.winfo_screenheight()
        y = max(18, screen_height - height - margin_bottom)
        self.root.geometry(f"{width}x{height}+{margin_x}+{y}")

    def _resolve_target(self):
        if self.follow_current:
            target = load_current_session_target()
            if target is not None:
                return target
        return self.fixed_log_path, self.fixed_session_id

    def _set_target(self, log_path, session_id):
        if log_path == self.log_path and session_id == self.session_id:
            return

        self.log_path = log_path
        self.session_id = session_id
        self.previous_values = None

        if self.graph_window is not None and self.graph_window.is_alive():
            self.graph_window.log_path = log_path
            self.graph_window.session_id = session_id

        if self.day_view is not None and self.day_view.is_alive():
            self.day_view.log_path = log_path
            self.day_view.current_session_id = session_id

    def _toggle_graph(self):
        if self.graph_window is not None and self.graph_window.is_alive():
            self.graph_window.destroy()
            self.graph_window = None
            self.graph_button.config(fg="#5eead4")
        else:
            self.graph_window = ChargeRateGraph(
                self.root, self.log_path, self.session_id, self.poll_ms
            )
            self.graph_button.config(fg="#f8fafc")

    def _toggle_day_view(self):
        if self.day_view is not None and self.day_view.is_alive():
            self.day_view.destroy()
            self.day_view = None
            self.day_button.config(fg="#5eead4")
        else:
            self.day_view = ChargeDayView(
                self.root, self.log_path, self.session_id, self.poll_ms
            )
            self.day_button.config(fg="#f8fafc")

    def _set_waiting(self):
        self.state_label.config(text="Waiting for data", fg="#f8fafc")
        self.timestamp_label.config(text="No samples yet")
        self.eta_label.config(text="--", fg="#f8fafc")
        for field in self.fields.values():
            field.config(text="--")

    def _render(self, measurement):
        if measurement is None:
            self._set_waiting()
            return

        if not measurement.get("status_available"):
            self.state_label.config(text="Unavailable", fg="#fca5a5")
            self.timestamp_label.config(text=format_measurement_timestamp(measurement))
            self.eta_label.config(text="--", fg="#fca5a5")
            for field in self.fields.values():
                field.config(text="--")
            return

        direction = active_rate_direction(measurement)
        is_charging = direction == "charge"
        is_stale = (measurement_age_seconds(measurement) or 0) >= STALE_AFTER_SECONDS
        if direction == "charge":
            state_text = "Charging"
            state_color = "#86efac"
        elif direction == "discharge":
            state_text = "Discharging"
            state_color = "#fbbf24"
        elif measurement.get("power_online"):
            state_text = "Plugged in"
            state_color = "#f8fafc"
        else:
            state_text = "Idle"
            state_color = "#f8fafc"
        if is_stale:
            state_text = f"Last: {state_text}"

        self.state_label.config(
            text=state_text,
            fg=state_color,
        )
        self.timestamp_label.config(text=format_measurement_timestamp(measurement))
        self.eta_label.config(
            text=calculate_eta(measurement),
            fg="#86efac" if is_charging else "#fca5a5",
        )
        self.fields["charge_rate_mW"].config(
            text=format_rate_field(
                measurement,
                "charge_rate_mW",
                "effective_charge_rate_mW",
            )
        )
        self.fields["discharge_rate_mW"].config(
            text=format_rate_field(
                measurement,
                "discharge_rate_mW",
                "effective_discharge_rate_mW",
            )
        )
        self.fields["remaining_capacity_mWh"].config(
            text=format_value(measurement.get("remaining_capacity_mWh"), "mWh")
        )
        self.fields["voltage_mV"].config(
            text=format_value(measurement.get("voltage_mV"), "mV")
        )
        self.fields["power_online"].config(
            text="Online" if measurement.get("power_online") else "Battery"
        )

    def _refresh(self):
        self._set_target(*self._resolve_target())
        measurement = read_latest_measurement(self.log_path, self.session_id)
        current_values = (
            str(self.log_path),
            self.session_id,
            value_fingerprint(measurement),
            stale_bucket(measurement),
        )
        if current_values != self.previous_values:
            self._render(measurement)
            self.previous_values = current_values

        if self.graph_window is not None:
            if self.graph_window.is_alive():
                self.graph_window.refresh()
            else:
                self.graph_window = None
                self.graph_button.config(fg="#5eead4")

        if self.day_view is not None:
            if self.day_view.is_alive():
                self.day_view.refresh()
            else:
                self.day_view = None
                self.day_button.config(fg="#5eead4")

        self.root.after(self.poll_ms, self._refresh)

    def run(self):
        self._refresh()
        self.root.mainloop()


def main():
    args = parse_args()
    follow_current = args.follow_current or args.log_path is None
    overlay = ChargeRateOverlay(
        args.log_path,
        args.session_id,
        args.poll_ms,
        follow_current=follow_current,
    )
    overlay.run()


if __name__ == "__main__":
    main()
