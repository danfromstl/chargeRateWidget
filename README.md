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

The overlay shows:

- charging or discharging state
- estimated time to target in the header
- timestamp in 12-hour time with seconds and AM/PM
- charge rate
- discharge rate
- remaining capacity
- voltage
- power source

ETA behavior:

- Charging: up arrow, estimated time to 100%
- Discharging: down arrow, estimated time to 10%
- If the rate or full capacity is unavailable, ETA displays `null`

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

Each run appends a new session to the current day's JSON:

```json
{
  "date": "2026-05-20",
  "sessions": [
    {
      "session_id": 1,
      "started_at": "2026-05-20 12:31:33",
      "ended_at": null,
      "interval_seconds": 2,
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
  "remaining_capacity_mWh": null,
  "full_charged_capacity_mWh": null,
  "voltage_mV": null,
  "charging": null,
  "power_online": null,
  "read_error": "x_wmi: ..."
}
```

The Windows battery API can report an unknown rate as `-2147483648`. The widget normalizes that sentinel to Python `None`, which becomes `null` in JSON.

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

## Notes

- The monitor writes every interval measurement to JSON.
- Console output is change-based to avoid repeated identical lines.
- JSON writes use a per-process temp file and retries to reduce Windows file-lock crashes.
- Existing running processes do not pick up code changes until restarted.
