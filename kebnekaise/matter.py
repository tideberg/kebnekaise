"""Fresh Matter reads via the local server; never relabel cached state as fresh.

Node 24 provides the WebSocket transport. Python validates units, ranges and
the receipt time before the existing collector can write anything to SQLite.
"""

from __future__ import annotations

import json
import math
import subprocess
import time
from pathlib import Path

from .config import METRICS

HELPER = Path(__file__).with_name("matter_read.mjs")


def attribute_paths(sensor):
    endpoints = sensor["endpoints"]
    return {"temperature": f"{endpoints['temperature']}/1026/0",
            "co2": f"{endpoints['co2']}/1037/0",
            "co2_unit": f"{endpoints['co2']}/1037/8"}


def read_nodes(config, sensors):
    settings = config["matter"]
    grouped = {}
    for sensor in sensors:
        grouped.setdefault(sensor["node_id"], set()).update(attribute_paths(sensor).values())
    timeout = settings.get("timeout_seconds", 15)
    request = {"url": settings["url"], "timeout_ms": int(timeout * 1000),
               "reads": [{"node_id": key, "attributes": sorted(paths)} for key, paths in grouped.items()]}
    try:
        result = subprocess.run([settings["node_path"], str(HELPER)], input=json.dumps(request),
                                text=True, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                timeout=timeout + 5, check=True)
        if len(result.stdout) > 1_000_000:
            raise ValueError("Matter-svaret är för stort")
        nodes = json.loads(result.stdout)
        if not isinstance(nodes, dict):
            raise ValueError("Ogiltigt Matter-svar")
        return nodes
    except (OSError, subprocess.SubprocessError, ValueError):
        # Do not leak server payloads or environment into dashboard health/logs.
        raise OSError("Matter ej tillgänglig; kontrollera tjänsten och Node.js") from None


def decode_sensor(sensor, result, started_at, received_at):
    if not isinstance(result, dict) or result.get("error"):
        return [], ["Matter-avläsning misslyckades; inga nya värden"]
    ts = result.get("received_at")
    attrs = result.get("attributes")
    if (type(ts) is not int or not started_at <= ts <= received_at
            or not isinstance(attrs, dict)):
        return [], ["Matter-svaret saknar giltig avläsningstid eller attribut"]
    paths = attribute_paths(sensor)
    rows, errors = [], []
    for metric, (unit, low, high) in METRICS.items():
        raw = attrs.get(paths[metric])
        if (isinstance(raw, bool) or not isinstance(raw, (int, float)) or not math.isfinite(raw)
                or (metric == "temperature" and not isinstance(raw, int))):
            errors.append(f"{metric}: saknat eller ogiltigt värde")
            continue
        if metric == "co2":
            measurement_unit = attrs.get(paths["co2_unit"])
            if type(measurement_unit) is not int or measurement_unit != 0:
                errors.append("co2: ppm-enhet kunde inte verifieras")
                continue
        value = raw / 100 if metric == "temperature" else raw
        if not low <= value <= high:
            errors.append(f"{metric}: värdet ligger utanför tillåtet intervall")
            continue
        rows.append((sensor["id"], metric, "matter", ts, value, "matter_read_received"))
    return rows, errors


def collect(config, sensors):
    started = int(time.time())
    try:
        nodes = read_nodes(config, sensors)
    except OSError:
        nodes = {}
    finished = int(time.time())
    rows, health = [], []
    for sensor in sensors:
        readings, errors = decode_sensor(sensor, nodes.get(str(sensor["node_id"])), started, finished)
        rows.extend(readings)
        detail = "; ".join(errors) if errors else "Sensorn avläst via Matter; tid = mottaget lässvar"
        health.append((sensor["id"], finished, not errors, detail))
    return rows, health
