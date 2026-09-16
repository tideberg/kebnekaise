"""Read-only readiness inventory; also works on the development Mac."""

import json
import platform
import shutil
import sqlite3
import sys
from pathlib import Path
from zoneinfo import ZoneInfo

model = Path("/proc/device-tree/model")
print(json.dumps({
    "model": model.read_text().strip("\0") if model.exists() else platform.machine(),
    "os": platform.platform(), "python": platform.python_version(),
    "python_supported": sys.version_info >= (3, 11), "sqlite": sqlite3.sqlite_version,
    "timezone_available": str(ZoneInfo("Europe/Stockholm")),
    "free_disk_gb": round(shutil.disk_usage(".").free / 1e9, 1),
    "systemd_available": shutil.which("systemctl") is not None,
    "note": "Kontrollera dessutom strömförsörjning, NTP-synk och lagringshälsa på Pi:n."
}, ensure_ascii=False, indent=2))
