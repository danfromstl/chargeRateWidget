import argparse
import json
from datetime import datetime
from pathlib import Path
import tkinter as tk


MONITORED_VALUE_KEYS = (
    "status_available",
    "charge_rate_mW",
    "discharge_rate_mW",
    "remaining_capacity_mWh",
    "full_charged_capacity_mWh",
    "voltage_mV",
    "charging",
    "power_online",
)
NO_DATA = ("no-data",)
CHARGING_ETA_LABEL = "🟢⬆"
DISCHARGING_ETA_LABEL = "🔴⬇"


def today_log_path():
    now = datetime.now()
    filename = f"{now.month}-{now.day}-{now.strftime('%y')}_charge_rates.json"
    return Path(__file__).resolve().parent / "logs" / filename


def parse_args():
    parser = argparse.ArgumentParser(description="Small live overlay for charge rate readings.")
    parser.add_argument("--log-path", type=Path, default=today_log_path())
    parser.add_argument("--session-id", type=int)
    parser.add_argument("--poll-ms", type=int, default=500)
    return parser.parse_args()


def read_latest_measurement(log_path, session_id=None):
    try:
        with log_path.open("r", encoding="utf-8") as file:
            data = json.load(file)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return None

    sessions = data.get("sessions")
    if not isinstance(sessions, list) or not sessions:
        return None

    session = None
    if session_id is None:
        session = sessions[-1]
    else:
        for candidate in reversed(sessions):
            if isinstance(candidate, dict) and candidate.get("session_id") == session_id:
                session = candidate
                break

    if not isinstance(session, dict):
        return None

    measurements = session.get("measurements")
    if not isinstance(measurements, list) or not measurements:
        return None

    latest = measurements[-1]
    return latest if isinstance(latest, dict) else None


def value_fingerprint(measurement):
    if measurement is None:
        return NO_DATA
    return tuple(measurement.get(key) for key in MONITORED_VALUE_KEYS)


def format_value(value, suffix):
    if value is None:
        return "null"
    return f"{value} {suffix}"


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


def calculate_eta(measurement):
    if measurement is None or not measurement.get("status_available"):
        return "--"

    charging = bool(measurement.get("charging"))
    label = CHARGING_ETA_LABEL if charging else DISCHARGING_ETA_LABEL
    remaining = number_or_none(measurement.get("remaining_capacity_mWh"))
    full_capacity = number_or_none(measurement.get("full_charged_capacity_mWh"))
    rate_key = "charge_rate_mW" if charging else "discharge_rate_mW"
    rate = number_or_none(measurement.get(rate_key))

    if remaining is None or full_capacity is None or full_capacity <= 0:
        return f"{label} null"
    if rate is None or rate <= 0:
        return f"{label} null"

    target_capacity = full_capacity if charging else full_capacity * 0.10
    capacity_delta = target_capacity - remaining if charging else remaining - target_capacity
    return f"{label} {format_duration(capacity_delta / rate)}"


class ChargeRateOverlay:
    def __init__(self, log_path, session_id, poll_ms):
        self.log_path = log_path
        self.session_id = session_id
        self.poll_ms = poll_ms
        self.previous_values = None
        self.drag_offset_x = 0
        self.drag_offset_y = 0

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
        self.state_label.pack(side="left", fill="x", expand=True)

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

        self.timestamp_label = tk.Label(
            self.panel,
            text="",
            bg="#101820",
            fg="#94a3b8",
            font=("Segoe UI", 8),
            anchor="w",
        )
        self.timestamp_label.pack(fill="x", pady=(0, 6))

        eta_row = tk.Frame(self.panel, bg="#101820")
        eta_row.pack(fill="x", pady=(1, 5))

        eta_name = tk.Label(
            eta_row,
            text="ETA",
            bg="#101820",
            fg="#cbd5e1",
            font=("Segoe UI", 9),
            anchor="w",
            width=10,
        )
        eta_name.pack(side="left")

        self.eta_label = tk.Label(
            eta_row,
            text="--",
            bg="#101820",
            fg="#f8fafc",
            font=("Segoe UI Emoji", 9, "bold"),
            anchor="e",
        )
        self.eta_label.pack(side="right", fill="x", expand=True)

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
        height = 184
        margin_x = 18
        margin_bottom = 72
        screen_height = self.root.winfo_screenheight()
        y = max(18, screen_height - height - margin_bottom)
        self.root.geometry(f"{width}x{height}+{margin_x}+{y}")

    def _set_waiting(self):
        self.state_label.config(text="Waiting for data", fg="#f8fafc")
        self.timestamp_label.config(text="No samples yet")
        self.eta_label.config(text="--")
        for field in self.fields.values():
            field.config(text="--")

    def _render(self, measurement):
        if measurement is None:
            self._set_waiting()
            return

        if not measurement.get("status_available"):
            self.state_label.config(text="Unavailable", fg="#fca5a5")
            self.timestamp_label.config(text=measurement.get("timestamp", ""))
            self.eta_label.config(text="--")
            for field in self.fields.values():
                field.config(text="--")
            return

        is_charging = bool(measurement.get("charging"))
        self.state_label.config(
            text="Charging" if is_charging else "Discharging",
            fg="#86efac" if is_charging else "#fbbf24",
        )
        self.timestamp_label.config(text=measurement.get("timestamp", ""))
        self.eta_label.config(text=calculate_eta(measurement))
        self.fields["charge_rate_mW"].config(
            text=format_value(measurement.get("charge_rate_mW"), "mW")
        )
        self.fields["discharge_rate_mW"].config(
            text=format_value(measurement.get("discharge_rate_mW"), "mW")
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
        measurement = read_latest_measurement(self.log_path, self.session_id)
        current_values = value_fingerprint(measurement)
        if current_values != self.previous_values:
            self._render(measurement)
            self.previous_values = current_values
        self.root.after(self.poll_ms, self._refresh)

    def run(self):
        self._refresh()
        self.root.mainloop()


def main():
    args = parse_args()
    overlay = ChargeRateOverlay(args.log_path, args.session_id, args.poll_ms)
    overlay.run()


if __name__ == "__main__":
    main()
