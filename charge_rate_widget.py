import time
import wmi
from datetime import datetime

# Connect to the WMI namespace
w = wmi.WMI(namespace="root\\wmi")

def get_battery_status():
    try:
        battery = w.BatteryStatus()[0]
        return {
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "charge_rate_mW": battery.ChargeRate,
            "discharge_rate_mW": battery.DischargeRate,
            "remaining_capacity_mWh": battery.RemainingCapacity,
            "voltage_mV": battery.Voltage,
            "charging": battery.Charging,
            "power_online": battery.PowerOnline
        }
    except IndexError:
        return None

def log_battery_status(interval=5):
    print("Monitoring battery. Press Ctrl+C to stop.\n")
    while True:
        status = get_battery_status()
        if status:
            print(f"[{status['timestamp']}] "
                  f"{'Charging' if status['charging'] else 'Discharging'} | "
                  f"Rate: {status['charge_rate_mW']} mW | "
                  f"Remaining: {status['remaining_capacity_mWh']} mWh | "
                  f"Voltage: {status['voltage_mV']} mV")
        else:
            print("Battery status not available.")
        time.sleep(interval)

if __name__ == "__main__":
    log_battery_status(interval=5)  # You can change this to 1 if you want faster updates
