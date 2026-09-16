"""Continuous collection and a persistent collector lock per database."""

from __future__ import annotations

import fcntl
import logging
import os
import threading
import time
from pathlib import Path

from . import adapters, matter, storage
from .simulation import Simulator

LOG = logging.getLogger(__name__)


class Collector:
    def __init__(self, config):
        self.config = config
        self.simulator = Simulator(config)

    def tick(self, con, now=None):
        clock = now
        now = int(time.time()) if now is None else now
        ts = now // self.config["interval_seconds"] * self.config["interval_seconds"]
        rows = self.simulator.sample(ts) if any(s["provider"] == "simulation" for s in self.config["sensors"]) else []
        health = []
        for sensor in self.config["sensors"]:
            if sensor["provider"] == "simulation":
                ok = any(row[0] == sensor["id"] for row in rows)
                health.append((sensor["id"], now, ok, "Simulerad insamling" if ok else "Simulerat avbrott"))
        ha_sensors = [s for s in self.config["sensors"] if s["provider"] in {"ha", "mock"}]
        if ha_sensors:
            try:
                states = adapters.ha_states(self.config)
            except (ValueError, OSError):
                for sensor in ha_sensors:
                    health.append((sensor["id"], now, False, "HA ej tillgänglig; kontrollera anslutning och token"))
                LOG.warning("HA ej tillgänglig. Luckan behålls; ingen automatisk simulering.")
            else:
                for sensor in ha_sensors:
                    readings, errors = adapters.decode_sensor(sensor, states, now, self.config["max_hold_seconds"])
                    rows.extend(readings)
                    health.append((sensor["id"], now, not errors,
                                   "; ".join(errors) if errors else "HA-tillstånd läst; tidsstämpel från HA"))
        matter_sensors = [s for s in self.config["sensors"] if s["provider"] == "matter"]
        if matter_sensors:
            readings, checks = matter.collect(self.config, matter_sensors)
            rows.extend(readings)
            health.extend(checks)
        received_at = int(time.time()) if clock is None else clock
        count = storage.insert(con, self.config, rows, received_at)
        with con:
            con.executemany("INSERT OR REPLACE INTO health VALUES (?,?,?,?)", health)
        return count


def loop(path, config, stop: threading.Event):
    lock_path = Path(str(path) + ".collector.lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("w") as lock:
        os.chmod(lock_path, 0o600)
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise ValueError("En insamlare kör redan mot den här databasen") from None
        con = storage.connect(path)
        try:
            storage.register(con, config)
            collector = Collector(config)
            last_clock = time.time()
            while not stop.is_set():
                now = time.time()
                if now + 2 < last_clock:
                    LOG.warning("Systemklockan gick bakåt; inväntar senast observerad tid")
                    stop.wait(min(30, last_clock-now))
                    continue
                last_clock = now
                count = collector.tick(con)
                LOG.info("Insamling: %d nya värden", count)
                interval = config["interval_seconds"]
                stop.wait(max(.2, interval - time.time() % interval))
        finally:
            con.close()
