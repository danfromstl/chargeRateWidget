# chargeRateWidget

A tiny Windows CLI that prints your laptop’s **charging / discharging rate** (mW) using WMI.

## What it does
Every N seconds, prints a line like:

[2026-02-17 09:12:33] Charging | Rate: 45000 mW | Remaining: 52000 mWh | Voltage: 12200 mV

Under the hood it queries WMI (`root\wmi` → `BatteryStatus`) and prints fields like:
- `ChargeRate` / `DischargeRate` (mW)
- `RemainingCapacity` (mWh)
- `Voltage` (mV)
- `Charging`, `PowerOnline` (booleans)

## Requirements
- Windows 10/11
- Python 3.x
- Python packages:
  - `wmi` (wrapper over `pywin32`) :contentReference[oaicite:3]{index=3}

## Setup
```bash
python -m venv .venv
.\.venv\Scripts\activate
pip install wmi pywin32
