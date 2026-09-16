"""Validated, versioned configuration. A placement is distinct from its source."""

from __future__ import annotations

import hashlib
import json
import math
import re
from urllib.parse import urlsplit
from pathlib import Path
from zoneinfo import ZoneInfo

METRICS = {"temperature": ("°C", -40, 85), "co2": ("ppm", 250, 40000)}
SOURCES = {"simulation", "ha", "matter", "mock", "replay"}
ID = re.compile(r"^[a-z][a-z0-9_-]{0,47}$")


def number(value, low, high, name):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name}: ett tal krävs")
    if not math.isfinite(value) or not low <= value <= high:
        raise ValueError(f"{name}: tillåtet intervall {low}–{high}")
    return value


def validate(config):
    if config.get("version") != 1:
        raise ValueError("Konfigurationsversion måste vara 1")
    if config.get("mode") not in {"demo", "pilot", "production"}:
        raise ValueError("mode måste vara demo, pilot eller production")
    ZoneInfo(config["timezone"])
    number(config["interval_seconds"], 10, 3600, "interval_seconds")
    number(config["max_hold_seconds"], 10, 3600, "max_hold_seconds")
    if config["max_hold_seconds"] < config["interval_seconds"]:
        raise ValueError("max_hold_seconds måste vara minst interval_seconds")
    hours = config["work_hours"]
    if len(hours) != 2 or not (0 <= hours[0] < hours[1] <= 24):
        raise ValueError("work_hours måste innehålla två klockslag i stigande ordning")
    thresholds = config["thresholds"]
    number(thresholds["co2"], 300, 10000, "CO₂-referens")
    for key in ("temperature_low", "temperature_high"):
        number(thresholds[key], 10, 35, key)
    if thresholds["temperature_low"] >= thresholds["temperature_high"]:
        raise ValueError("Temperaturreferenserna är omvända")
    rooms = config["rooms"]
    model_rooms = {s["room"] for s in config["sensors"] if s["provider"] in {"simulation", "mock"}}
    for room in rooms:
        if not ID.fullmatch(room["id"]):
            raise ValueError("Ogiltigt rums-id")
        for key, low, high in (("volume_m3", 10, 10000), ("people", 0, 500),
                               ("ach", .05, 20), ("setpoint_c", 10, 35),
                               ("solar_c", 0, 10)):
            if room["id"] in model_rooms or key in room:
                number(room[key], low, high, key)
        if room["id"] in model_rooms and room.get("aspect") not in {"NE", "SW"}:
            raise ValueError("Simulerade rum kräver aspect NE eller SW")
    room_ids = [r["id"] for r in rooms]
    if len(room_ids) != len(set(room_ids)):
        raise ValueError("Dubbla rums-id")
    sensors = config["sensors"]
    if not 1 <= len(sensors) <= 100:
        raise ValueError("1–100 mätpunkter krävs")
    ids = []
    entities = []
    matter_attributes = []
    for sensor in sensors:
        sid = sensor["id"]
        if not ID.fullmatch(sid) or sensor["room"] not in room_ids:
            raise ValueError(f"Ogiltig mätpunkt: {sid}")
        if not isinstance(sensor["name"], str) or not 1 <= len(sensor["name"]) <= 80:
            raise ValueError("Mätpunktens namn måste innehålla 1–80 tecken")
        provider = sensor["provider"]
        if provider not in SOURCES | {"disabled"}:
            raise ValueError(f"Okänd provider: {provider}")
        if not isinstance(sensor.get("zone"), str) or not 1 <= len(sensor["zone"]) <= 80:
            raise ValueError("Mätpunktens zon måste innehålla 1–80 tecken")
        if config["mode"] == "production" and provider not in {"ha", "matter", "disabled"}:
            raise ValueError("Production tillåter bara verklig HA, Matter eller disabled")
        if provider in {"ha", "mock"}:
            for metric in METRICS:
                entity = sensor.get("entities", {}).get(metric, "")
                if not re.fullmatch(r"sensor\.[a-z0-9_]+", entity):
                    raise ValueError(f"{sid}: ange HA-entity för {metric}")
                entities.append(entity)
        if provider == "matter":
            node_id = sensor.get("node_id")
            number(node_id, 1, 2**53-1, "node_id")
            if not isinstance(node_id, int):
                raise ValueError("Matter node_id måste vara ett heltal")
            for metric in METRICS:
                endpoint = sensor.get("endpoints", {}).get(metric)
                number(endpoint, 1, 65534, f"{metric} endpoint")
                if not isinstance(endpoint, int):
                    raise ValueError("Matter endpoint måste vara ett heltal")
                matter_attributes.append((node_id, endpoint, metric))
        number(sensor.get("temperature_offset", 0), -5, 5, "temperature_offset")
        ids.append(sid)
    if len(ids) != len(set(ids)) or len(entities) != len(set(entities)):
        raise ValueError("Dubbla mätpunkter eller HA-entiteter")
    if len(matter_attributes) != len(set(matter_attributes)):
        raise ValueError("Samma Matter-attribut används av flera mätpunkter")
    if matter_attributes:
        settings = config.get("matter", {})
        url = urlsplit(settings.get("url", ""))
        if (url.scheme != "ws" or url.hostname != "127.0.0.1" or not url.port
                or url.path != "/ws" or url.username is not None or url.password is not None
                or url.query or url.fragment):
            raise ValueError("Matter kräver ws://127.0.0.1:PORT/ws på samma dator")
        if not isinstance(settings.get("node_path"), str) or not Path(settings["node_path"]).is_absolute():
            raise ValueError("Ange absolut sökväg till Node.js 24 för Matter")
        number(settings.get("timeout_seconds", 15), 1, 20, "Matter timeout_seconds")
    if "site_name" in config and (not isinstance(config["site_name"], str) or not 1 <= len(config["site_name"]) <= 80):
        raise ValueError("site_name måste innehålla 1–80 tecken")
    return config


def load(path):
    return validate(json.loads(Path(path).read_text(encoding="utf-8")))


def fingerprint(config):
    return hashlib.sha256(json.dumps(config, sort_keys=True).encode()).hexdigest()
