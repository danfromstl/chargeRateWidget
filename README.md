# chargeRateWidget

A small Windows charge-rate monitor. It samples laptop battery data through WMI, writes every sample to daily JSON logs, and can show a lightweight desktop overlay controlled from a tray icon.

## What It Does

`charge_rate_widget.py` is the sampler. At the configured interval it reads `root\wmi` battery data and records:

- `ChargeRate` and `DischargeRate` in mW
- `RemainingCapacity` in mWh
- `BatteryFullChargedCapacity` in mWh when available
- `Voltage` in mV
- charging / power-online state
- WMI read hiccups as unavailable measurements instead of crashing

Every interval measurement is written to JSON, even when the console does not print anything. The console only prints a new line when one of the monitored values changes.

## Requirements

- Windows 10/11
- Python 3.x
- Python packages:
  - `wmi`
  - `pywin32`

Setup:

```powershell
python -m venv .venv
.\.venv\Scripts\activate
pip install wmi pywin32
```

## Quick Start

Run the monitor with the overlay:

```powershell
python .\charge_rate_widget.py
```

Run at a custom interval:

```powershell
python .\charge_rate_widget.py --interval 2
```

Run the monitor without starting the overlay:

```powershell
python .\charge_rate_widget.py --no-overlay
```

Show the overlay separately:

```powershell
pythonw .\charge_rate_overlay.py
```

Start the tray controller:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\charge_rate_tray.ps1
```

For normal use, install the Desktop shortcut and launch from there.

## Desktop Shortcuts

Install only the tray shortcut, which is the default:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\install_desktop_shortcuts.ps1
```

This creates:

- `Charge Rate Tray Widget.lnk`

Install or refresh all shortcuts:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\install_desktop_shortcuts.ps1 all_icons
```

This creates:

- `Charge Rate Tray Widget.lnk`
- `Charge Rate Widget.lnk`
- `Charge Rate Widget (Hidden Overlay).lnk`
- `Show Charge Rate Overlay.lnk`

The shortcut installer converts `icon.png` to `icon.ico` when needed and applies `icon.ico` to the shortcuts.

## Tray Controller

`charge_rate_tray.ps1` creates a Windows tray icon using PowerShell WinForms. It starts the monitor hidden with `--no-overlay`, then lets you manage the app from the tray menu.

Tray actions:

- `Start Monitor` / `Stop Monitor`
- `Show Overlay` / `Hide Overlay`
- `Open Logs Folder`
- `Exit`

Double-clicking the tray icon toggles the overlay.

`start_charge_rate_tray.vbs` launches the tray controller without leaving an empty PowerShell window open. The Desktop shortcut points to `wscript.exe` and runs this VBS launcher.

## Overlay

`charge_rate_overlay.py` is a small transparent Tkinter window. It reads the newest measurement from the active JSON log rather than querying WMI itself.

When started without `--log-path`, the overlay follows `logs/_current_session.json`. That lets it keep tracking the monitor when the sampler rolls into a new daily file or starts a new session after wake.

The overlay shows:

- charging, discharging, plugged-in, or idle state
- estimated time to target in the header
- timestamp in 12-hour time with seconds and AM/PM
- charge rate, using `~` when the value is estimated from capacity changes
- discharge rate, using `~` when the value is estimated from capacity changes
- remaining capacity
- voltage
- power source

ETA behavior:

- Charging: up arrow, estimated time to 100%
- Discharging: down arrow, estimated time to 10%
- If the rate or full capacity is unavailable, ETA displays `null`
- If the sampler stops writing, the overlay keeps showing the last sample and adds an age marker like `(45s old)`

Controls:

- Drag the overlay to move it
- Click `x`, press `Esc`, or right-click to close it

## JSON Logs

Logs are written to `logs/` using this filename pattern:

```text
M-D-YY_charge_rates.json
```

Example:

```text
logs/5-20-26_charge_rates.json
```

Each run starts or resumes a session in the current day's JSON:

```json
{
  "date": "2026-05-20",
  "sessions": [
    {
      "session_id": 1,
      "started_at": "2026-05-20 12:31:33",
      "ended_at": null,
      "start_reason": "process_start",
      "end_reason": null,
      "interval_seconds": 2,
      "events": [],
      "measurements": []
    }
  ]
}
```

Each measurement looks like:

```json
{
  "timestamp": "2026-05-20 12:31:33",
  "status_available": true,
  "charge_rate_mW": 30150,
  "discharge_rate_mW": 0,
  "effective_charge_rate_mW": 30150,
  "effective_discharge_rate_mW": 0,
  "rate_source": "reported",
  "rate_confidence": "high",
  "rate_window_seconds": null,
  "remaining_capacity_mWh": 44630,
  "full_charged_capacity_mWh": 58120,
  "voltage_mV": 16422,
  "charging": true,
  "power_online": true,
  "read_error": null
}
```

If WMI has a read/access hiccup, the script records an unavailable measurement instead of exiting:

```json
{
  "timestamp": "2026-05-20 12:31:33",
  "status_available": false,
  "charge_rate_mW": null,
  "discharge_rate_mW": null,
  "effective_charge_rate_mW": null,
  "effective_discharge_rate_mW": null,
  "rate_source": "unavailable",
  "rate_confidence": "none",
  "rate_window_seconds": null,
  "remaining_capacity_mWh": null,
  "full_charged_capacity_mWh": null,
  "voltage_mV": null,
  "charging": null,
  "power_online": null,
  "read_error": "x_wmi: ..."
}
```

The Windows battery API can report an unknown rate as `-2147483648`. The widget normalizes that sentinel to Python `None`, which becomes `null` in JSON.

When the reported charge/discharge rate is missing or zero, the sampler tries to estimate the active rate from recent capacity changes:

```text
mW = delta_mWh / delta_hours
```

Estimated values are written to `effective_charge_rate_mW` or `effective_discharge_rate_mW` with `rate_source: "estimated_capacity_delta"`.

## Session Boundaries

The sampler keeps the active log/session pointer in:

```text
logs/_current_session.json
```

The monitor checks for daily rollover inside the sampling loop. When the date changes, it closes the old session with `end_reason: "date_rollover"` and opens the next day's file with `start_reason: "date_rollover"`.

The monitor also checks for sampling gaps. By default, a gap is any missing-sample window longer than `max(60, interval * 5)` seconds. You can override that:

```powershell
python .\charge_rate_widget.py --gap-threshold 120
```

When a gap is detected, the sampler queries the Windows System event log for sleep/wake events from `Microsoft-Windows-Kernel-Power` and `Microsoft-Windows-Power-Troubleshooter`. If it finds sleep/wake events, the previous session is closed with `end_reason: "sleep"` and the next session starts with `start_reason: "wake"` or `resume_after_sleep`.

If the app was closed and restarted on the same day without a detected sleep/wake boundary, it resumes the previous open session and records an `app_downtime` event instead of incrementing the session number.

## Historical Logs

The old June 2025 CSV/TXT logs were converted into the current JSON shape:

- `logs/6-16-25_charge_rates.json`
- `logs/6-17-25_charge_rates.json`

Those historical entries only contain the fields that were tracked at the time. Fields that did not exist in the old data are stored as `null`.

## File Map

- `charge_rate_widget.py`: WMI sampler, console output, daily JSON writer, optional overlay launcher
- `charge_rate_overlay.py`: transparent draggable overlay that follows the latest JSON measurement
- `charge_rate_tray.ps1`: tray controller with monitor and overlay actions
- `start_charge_rate_tray.vbs`: no-console launcher for the tray controller
- `install_desktop_shortcuts.ps1`: Desktop shortcut installer
- `icon.png`: source icon
- `icon.ico`: Windows icon generated from `icon.png`
- `logs/`: daily JSON logs
- `logs/_current_session.json`: active log/session pointer written by the sampler

## Notes

- The monitor writes every interval measurement to JSON.
- Console output is change-based to avoid repeated identical lines.
- JSON writes use a per-process temp file and retries to reduce Windows file-lock crashes.
- The overlay follows `logs/_current_session.json` unless launched with an explicit `--log-path`.
- Existing running processes do not pick up code changes until restarted.


## Roadmap

- Done: date check to create a new daily log file while the monitor is still running
- Done: gap-based session boundaries with Windows sleep/wake event-log enrichment
- Done: same-day app restart can resume an open session and record `app_downtime`
- Done: best-guess effective charge/discharge rates when the reported rate field is unavailable


## Dan's Crazy Moonshot Ideas

- A postgres database to house the logs
- An Avro Schema (or equivalent tech) to compress the logs
- An event-driven system to ship the events to the database
- A simulated data warehouse to store... historical charging data?
- An AI app that monitors the Data Warehouse Data and recurrently issues reports
- Migrating most or all of these support services to AWS
- Standing up and loading all of those services on demand with Terraform
- Migrating to Snowflake to enable elastic storage AND elastic compute
- A blog that automatically posts uptime and running avearge stats

## Even Crazier Moonshots

- Rewrite everything in Rust
- Rewrite everything in Go?
- Rewrite everything in Zig
