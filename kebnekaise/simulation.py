"""Explicitly synthetic, deterministic single-zone mass balances (not sensor data)."""

from __future__ import annotations

import hashlib
import math
from datetime import datetime
from zoneinfo import ZoneInfo


def noise(seed, key, ts):
    raw = hashlib.sha256(f"{seed}/{key}/{ts}".encode()).digest()
    return int.from_bytes(raw[:4], "big") / (2**32 - 1) * 2 - 1


def conditions(room, local):
    hour = local.hour + local.minute / 60
    weekday = local.weekday() < 5
    occupied = weekday and 8 <= hour < 17
    lunch = 11.5 <= hour < 13
    coffee = 9.5 <= hour < 10 or 14.5 <= hour < 15
    presentation = weekday and local.weekday() == 2 and 14 <= hour < 15
    if room["id"] == "lunch":
        fraction = 1.0 if presentation else .85 if lunch else .45 if coffee else .03 if occupied else 0
    else:
        fraction = (.25 if lunch else .55 if coffee else .8) if occupied else 0
        fraction *= 1 + .12 * math.sin(local.toordinal() * 1.7)
    people = room["people"] * fraction
    solar_peak = 9.5 if room["aspect"] == "NE" else 15.5
    solar = math.exp(-((hour - solar_peak) / 2.4) ** 2) * room["solar_c"]
    # A reproducible ventilation fault is a scenario, never an inferred office fault.
    fault = room["id"] == "ne-3" and weekday and local.toordinal() % 7 in (0, 1) and 10 <= hour < 16
    ach = room["ach"] * (.27 if fault else 1) if weekday and 7 <= hour < 18 else .18
    target_temp = room["setpoint_c"] + solar + people * .065 + .3 * math.sin(local.toordinal() / 4)
    return people, ach, target_temp


def co2_step(current, people, volume_m3, ach, seconds, outdoor=430.0):
    # G=0.0045 L/s/person is an assumed scenario input, not a measured parameter.
    generation_ppm_h = people * .0045 / 1000 * 3600 / volume_m3 * 1_000_000
    equilibrium = outdoor + generation_ppm_h / ach
    return equilibrium + (current - equilibrium) * math.exp(-ach * seconds / 3600)


class Simulator:
    def __init__(self, config):
        self.config = config
        self.zone = ZoneInfo(config["timezone"])
        self.seed = config.get("seed", 20260914)
        self.state = {}
        self.last_ts = None

    def sample(self, ts, providers=("simulation",), gaps=True):
        room_ids = {s["room"] for s in self.config["sensors"] if s["provider"] in providers}
        rooms = [r for r in self.config["rooms"] if r["id"] in room_ids]
        # Re-warm after restart or long gaps rather than integrating a huge time step.
        if self.last_ts is None or ts < self.last_ts or ts - self.last_ts > 120:
            self.state = {r["id"]: [430., r["setpoint_c"]] for r in rooms}
            self.last_ts = ts - 12 * 3600
        while self.last_ts < ts:
            step = min(60, ts - self.last_ts)
            local = datetime.fromtimestamp(self.last_ts + step, self.zone)
            for room in rooms:
                co2, temp = self.state[room["id"]]
                people, ach, target = conditions(room, local)
                self.state[room["id"]] = [
                    co2_step(co2, people, room["volume_m3"], ach, step),
                    target + (temp - target) * math.exp(-step / (70 * 60))]
            self.last_ts += step
        local = datetime.fromtimestamp(ts, self.zone)
        readings = []
        for sensor in self.config["sensors"]:
            if sensor["provider"] not in providers:
                continue
            # A daily 25 minute outage makes missing-data behavior reviewable.
            if gaps and sensor["id"] == "ne-5" and local.weekday() < 5 and local.hour == 13 and local.minute < 25:
                continue
            co2, temp = self.state[sensor["room"]]
            temp += sensor.get("temperature_offset", 0)
            temp += .055 * noise(self.seed, sensor["id"] + "temp", ts)
            co2 += 9 * noise(self.seed, sensor["id"] + "co2", ts)
            for metric, value in (("temperature", round(temp, 2)), ("co2", round(co2))):
                readings.append((sensor["id"], metric, sensor["provider"], ts, value, "model"))
        return readings
