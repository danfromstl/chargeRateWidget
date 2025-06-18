import re
import csv
from datetime import datetime

# Paste your raw log data into this variable as a triple-quoted string
raw_data = """Monitoring battery. Press Ctrl+C to stop.

[2025-06-17 08:49:15] Discharging | Rate: 0 mW | Remaining: 18058 mWh | Voltage: 11112 mV
[2025-06-17 08:49:20] Discharging | Rate: 0 mW | Remaining: 18058 mWh | Voltage: 11112 mV
[2025-06-17 08:49:25] Discharging | Rate: 0 mW | Remaining: 18058 mWh | Voltage: 11112 mV
[2025-06-17 08:49:31] Discharging | Rate: 0 mW | Remaining: 18058 mWh | Voltage: 11112 mV
[2025-06-17 08:49:36] Discharging | Rate: 0 mW | Remaining: 18058 mWh | Voltage: 11112 mV
[2025-06-17 08:49:41] Discharging | Rate: 0 mW | Remaining: 18058 mWh | Voltage: 11112 mV
[2025-06-17 08:49:46] Charging | Rate: 11 mW | Remaining: 17955 mWh | Voltage: 11314 mV
[2025-06-17 08:49:51] Charging | Rate: 11 mW | Remaining: 17955 mWh | Voltage: 11317 mV
[2025-06-17 08:49:56] Charging | Rate: 11 mW | Remaining: 17955 mWh | Voltage: 11317 mV
[2025-06-17 08:50:01] Charging | Rate: 11 mW | Remaining: 17955 mWh | Voltage: 11317 mV
[2025-06-17 08:50:06] Charging | Rate: 20987 mW | Remaining: 18001 mWh | Voltage: 11709 mV
[2025-06-17 08:50:11] Charging | Rate: 20987 mW | Remaining: 18001 mWh | Voltage: 11709 mV
[2025-06-17 08:50:16] Charging | Rate: 28831 mW | Remaining: 18092 mWh | Voltage: 11746 mV
[2025-06-17 08:50:21] Charging | Rate: 28831 mW | Remaining: 18092 mWh | Voltage: 11746 mV
[2025-06-17 08:50:26] Charging | Rate: 28831 mW | Remaining: 18092 mWh | Voltage: 11746 mV
[2025-06-17 08:50:31] Charging | Rate: 28831 mW | Remaining: 18092 mWh | Voltage: 11746 mV
[2025-06-17 08:50:36] Charging | Rate: 28831 mW | Remaining: 18092 mWh | Voltage: 11746 mV
[2025-06-17 08:50:41] Charging | Rate: 28831 mW | Remaining: 18092 mWh | Voltage: 11746 mV
[2025-06-17 08:50:46] Charging | Rate: 28831 mW | Remaining: 18092 mWh | Voltage: 11746 mV
[2025-06-17 08:50:51] Charging | Rate: 28945 mW | Remaining: 18388 mWh | Voltage: 11779 mV
[2025-06-17 08:50:56] Charging | Rate: 28945 mW | Remaining: 18388 mWh | Voltage: 11779 mV
[2025-06-17 08:51:01] Charging | Rate: 28945 mW | Remaining: 18388 mWh | Voltage: 11779 mV
[2025-06-17 08:51:06] Charging | Rate: 28945 mW | Remaining: 18388 mWh | Voltage: 11779 mV
[2025-06-17 08:51:11] Charging | Rate: 28945 mW | Remaining: 18388 mWh | Voltage: 11779 mV
[2025-06-17 08:51:16] Charging | Rate: 28910 mW | Remaining: 18559 mWh | Voltage: 11815 mV
[2025-06-17 08:51:21] Charging | Rate: 28910 mW | Remaining: 18559 mWh | Voltage: 11815 mV
[2025-06-17 08:51:26] Charging | Rate: 28967 mW | Remaining: 18673 mWh | Voltage: 11823 mV
[2025-06-17 08:51:31] Charging | Rate: 28967 mW | Remaining: 18673 mWh | Voltage: 11823 mV
[2025-06-17 08:51:36] Charging | Rate: 28967 mW | Remaining: 18673 mWh | Voltage: 11823 mV
[2025-06-17 08:51:42] Charging | Rate: 28967 mW | Remaining: 18673 mWh | Voltage: 11823 mV
[2025-06-17 08:51:47] Charging | Rate: 28967 mW | Remaining: 18673 mWh | Voltage: 11823 mV
[2025-06-17 08:51:52] Charging | Rate: 28796 mW | Remaining: 18856 mWh | Voltage: 11835 mV
[2025-06-17 08:51:57] Charging | Rate: 28956 mW | Remaining: 18890 mWh | Voltage: 11839 mV
[2025-06-17 08:52:02] Charging | Rate: 28899 mW | Remaining: 18958 mWh | Voltage: 11843 mV
[2025-06-17 08:52:07] Charging | Rate: 28888 mW | Remaining: 18981 mWh | Voltage: 11842 mV
[2025-06-17 08:52:12] Charging | Rate: 28888 mW | Remaining: 18981 mWh | Voltage: 11842 mV
[2025-06-17 08:52:17] Charging | Rate: 28888 mW | Remaining: 18981 mWh | Voltage: 11842 mV
[2025-06-17 08:52:22] Charging | Rate: 28888 mW | Remaining: 18981 mWh | Voltage: 11842 mV
[2025-06-17 08:52:27] Charging | Rate: 28945 mW | Remaining: 19152 mWh | Voltage: 11850 mV
[2025-06-17 08:52:32] Charging | Rate: 28945 mW | Remaining: 19152 mWh | Voltage: 11850 mV
[2025-06-17 08:52:37] Charging | Rate: 28979 mW | Remaining: 19255 mWh | Voltage: 11854 mV
[2025-06-17 08:52:42] Charging | Rate: 28979 mW | Remaining: 19255 mWh | Voltage: 11854 mV
[2025-06-17 08:52:47] Charging | Rate: 28979 mW | Remaining: 19255 mWh | Voltage: 11854 mV
[2025-06-17 08:52:52] Charging | Rate: 28979 mW | Remaining: 19255 mWh | Voltage: 11854 mV
[2025-06-17 08:52:57] Charging | Rate: 28979 mW | Remaining: 19255 mWh | Voltage: 11854 mV
[2025-06-17 08:53:02] Charging | Rate: 28979 mW | Remaining: 19255 mWh | Voltage: 11854 mV
[2025-06-17 08:53:07] Charging | Rate: 28979 mW | Remaining: 19255 mWh | Voltage: 11854 mV
[2025-06-17 08:53:13] Charging | Rate: 28751 mW | Remaining: 19551 mWh | Voltage: 11866 mV
[2025-06-17 08:53:18] Charging | Rate: 28751 mW | Remaining: 19551 mWh | Voltage: 11866 mV
[2025-06-17 08:53:23] Charging | Rate: 28751 mW | Remaining: 19551 mWh | Voltage: 11866 mV
[2025-06-17 08:53:28] Charging | Rate: 28751 mW | Remaining: 19551 mWh | Voltage: 11866 mV
[2025-06-17 08:53:33] Charging | Rate: 28967 mW | Remaining: 19711 mWh | Voltage: 11868 mV
[2025-06-17 08:53:38] Charging | Rate: 28967 mW | Remaining: 19711 mWh | Voltage: 11868 mV
[2025-06-17 08:53:43] Charging | Rate: 27964 mW | Remaining: 19790 mWh | Voltage: 11866 mV
[2025-06-17 08:53:48] Charging | Rate: 28922 mW | Remaining: 19825 mWh | Voltage: 11869 mV
[2025-06-17 08:53:53] Charging | Rate: 28979 mW | Remaining: 19859 mWh | Voltage: 11872 mV
[2025-06-17 08:53:58] Charging | Rate: 28979 mW | Remaining: 19859 mWh | Voltage: 11872 mV
[2025-06-17 08:54:03] Charging | Rate: 28922 mW | Remaining: 19950 mWh | Voltage: 11876 mV
[2025-06-17 08:54:08] Charging | Rate: 28511 mW | Remaining: 19961 mWh | Voltage: 11876 mV
[2025-06-17 08:54:13] Charging | Rate: 28511 mW | Remaining: 19961 mWh | Voltage: 11876 mV
[2025-06-17 08:54:18] Charging | Rate: 28511 mW | Remaining: 19961 mWh | Voltage: 11876 mV
[2025-06-17 08:54:23] Charging | Rate: 28511 mW | Remaining: 19961 mWh | Voltage: 11876 mV
[2025-06-17 08:54:28] Charging | Rate: 28511 mW | Remaining: 19961 mWh | Voltage: 11876 mV
[2025-06-17 08:54:33] Charging | Rate: 28865 mW | Remaining: 20201 mWh | Voltage: 11881 mV
[2025-06-17 08:54:38] Charging | Rate: 28865 mW | Remaining: 20201 mWh | Voltage: 11881 mV
[2025-06-17 08:54:43] Charging | Rate: 28865 mW | Remaining: 20201 mWh | Voltage: 11881 mV
[2025-06-17 08:54:48] Charging | Rate: 28865 mW | Remaining: 20201 mWh | Voltage: 11881 mV
[2025-06-17 08:54:53] Charging | Rate: 28956 mW | Remaining: 20349 mWh | Voltage: 11885 mV
[2025-06-17 08:54:59] Charging | Rate: 28956 mW | Remaining: 20349 mWh | Voltage: 11885 mV
[2025-06-17 08:55:04] Charging | Rate: 28420 mW | Remaining: 20406 mWh | Voltage: 11890 mV
[2025-06-17 08:55:09] Charging | Rate: 28420 mW | Remaining: 20406 mWh | Voltage: 11890 mV
[2025-06-17 08:55:14] Discharging | Rate: 0 mW | Remaining: 20520 mWh | Voltage: 11440 mV
[2025-06-17 08:55:19] Discharging | Rate: 0 mW | Remaining: 20520 mWh | Voltage: 11440 mV
[2025-06-17 08:55:24] Discharging | Rate: 0 mW | Remaining: 20520 mWh | Voltage: 11440 mV
[2025-06-17 08:55:29] Discharging | Rate: 0 mW | Remaining: 20520 mWh | Voltage: 11440 mV
[2025-06-17 08:55:34] Discharging | Rate: 0 mW | Remaining: 20372 mWh | Voltage: 11179 mV
[2025-06-17 08:55:39] Discharging | Rate: 0 mW | Remaining: 20372 mWh | Voltage: 11179 mV
[2025-06-17 08:55:44] Discharging | Rate: 0 mW | Remaining: 20303 mWh | Voltage: 11157 mV
[2025-06-17 08:55:49] Discharging | Rate: 0 mW | Remaining: 20303 mWh | Voltage: 11157 mV
[2025-06-17 08:55:54] Discharging | Rate: 0 mW | Remaining: 20269 mWh | Voltage: 11195 mV
[2025-06-17 08:55:59] Discharging | Rate: 0 mW | Remaining: 20269 mWh | Voltage: 11195 mV
[2025-06-17 08:56:04] Discharging | Rate: 0 mW | Remaining: 20201 mWh | Voltage: 11139 mV
[2025-06-17 08:56:09] Discharging | Rate: 0 mW | Remaining: 20201 mWh | Voltage: 11139 mV
[2025-06-17 08:56:14] Discharging | Rate: 0 mW | Remaining: 20201 mWh | Voltage: 11139 mV
[2025-06-17 08:56:19] Discharging | Rate: 0 mW | Remaining: 20201 mWh | Voltage: 11139 mV
[2025-06-17 08:56:24] Discharging | Rate: 0 mW | Remaining: 20201 mWh | Voltage: 11139 mV
[2025-06-17 08:56:29] Discharging | Rate: 0 mW | Remaining: 20201 mWh | Voltage: 11139 mV
[2025-06-17 08:56:34] Discharging | Rate: 0 mW | Remaining: 20201 mWh | Voltage: 11139 mV
[2025-06-17 08:56:39] Discharging | Rate: 0 mW | Remaining: 19996 mWh | Voltage: 11170 mV
[2025-06-17 08:56:44] Discharging | Rate: 0 mW | Remaining: 19996 mWh | Voltage: 11170 mV
[2025-06-17 08:56:50] Discharging | Rate: 0 mW | Remaining: 19996 mWh | Voltage: 11170 mV
[2025-06-17 08:56:55] Discharging | Rate: 0 mW | Remaining: 19996 mWh | Voltage: 11170 mV
[2025-06-17 08:57:00] Discharging | Rate: 0 mW | Remaining: 19882 mWh | Voltage: 11134 mV
[2025-06-17 08:57:05] Discharging | Rate: 0 mW | Remaining: 19882 mWh | Voltage: 11134 mV
[2025-06-17 08:57:10] Discharging | Rate: 0 mW | Remaining: 19882 mWh | Voltage: 11134 mV
[2025-06-17 08:57:15] Discharging | Rate: 0 mW | Remaining: 19790 mWh | Voltage: 11099 mV
[2025-06-17 08:57:20] Discharging | Rate: 0 mW | Remaining: 19790 mWh | Voltage: 11099 mV
[2025-06-17 08:57:25] Discharging | Rate: 0 mW | Remaining: 19790 mWh | Voltage: 11099 mV
[2025-06-17 08:57:30] Discharging | Rate: 0 mW | Remaining: 19790 mWh | Voltage: 11099 mV
[2025-06-17 08:57:35] Discharging | Rate: 0 mW | Remaining: 19790 mWh | Voltage: 11099 mV
[2025-06-17 08:57:40] Discharging | Rate: 0 mW | Remaining: 19790 mWh | Voltage: 11099 mV
[2025-06-17 08:57:45] Discharging | Rate: 0 mW | Remaining: 19790 mWh | Voltage: 11099 mV
[2025-06-17 08:57:50] Discharging | Rate: 0 mW | Remaining: 19790 mWh | Voltage: 11099 mV
[2025-06-17 08:57:55] Discharging | Rate: 0 mW | Remaining: 19551 mWh | Voltage: 11133 mV
[2025-06-17 08:58:00] Discharging | Rate: 0 mW | Remaining: 19551 mWh | Voltage: 11133 mV
[2025-06-17 08:58:05] Discharging | Rate: 0 mW | Remaining: 19494 mWh | Voltage: 11143 mV
[2025-06-17 08:58:10] Discharging | Rate: 0 mW | Remaining: 19494 mWh | Voltage: 11143 mV
[2025-06-17 08:58:15] Discharging | Rate: 0 mW | Remaining: 19494 mWh | Voltage: 11143 mV
[2025-06-17 08:58:20] Discharging | Rate: 0 mW | Remaining: 19494 mWh | Voltage: 11143 mV
[2025-06-17 08:58:25] Discharging | Rate: 0 mW | Remaining: 19494 mWh | Voltage: 11143 mV
[2025-06-17 08:58:30] Discharging | Rate: 0 mW | Remaining: 19494 mWh | Voltage: 11143 mV
[2025-06-17 08:58:35] Discharging | Rate: 0 mW | Remaining: 19403 mWh | Voltage: 11208 mV
Traceback (most recent call last):
KeyboardInterrupt"""

# Regex pattern to extract relevant fields
pattern = re.compile(
    r"\[(.*?)\] (Charging|Discharging) \| Rate: (\d+) mW \| Remaining: (\d+) mWh \| Voltage: (\d+) mV"
)

# Extract all matches
matches = pattern.findall(raw_data)

# Optional: print a few matches for inspection
# print(matches[:5])

# Prepare CSV rows
csv_rows = [("timestamp", "status", "rate_mw", "remaining_mwh", "voltage_mv")]
for match in matches:
    timestamp_str, status, rate, remaining, voltage = match
    timestamp = datetime.strptime(timestamp_str, "%Y-%m-%d %H:%M:%S")
    csv_rows.append((timestamp.isoformat(), status, int(rate), int(remaining), int(voltage)))

# Save to CSV
output_file = "laptop_charge_log_v1.csv"
with open(output_file, mode="w", newline="") as f:
    writer = csv.writer(f)
    writer.writerows(csv_rows)

print(f"✅ CSV saved as: {output_file}")
