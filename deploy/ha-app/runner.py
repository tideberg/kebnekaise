"""HA OS collector app. No HTTP listener, HA ingress, or public ports."""

import json
import logging
import os
import signal
import sys
import threading
from pathlib import Path

from kebnekaise import collector, config, storage
from scripts.daily_backup import daily_backup


def main():
    os.umask(0o077)
    logging.basicConfig(level=logging.INFO)
    options = json.loads(Path("/data/options.json").read_text())
    config_path = Path(options["config_file"]).resolve()
    if not config_path.is_relative_to(Path("/share/kebnekaise")):
        raise ValueError("Konfigurationen ska ligga under /share/kebnekaise")
    settings = config.load(config_path)
    settings["home_assistant"] = {"url": "http://supervisor/core", "token_env": "SUPERVISOR_TOKEN", "supervisor_api": True}
    if settings["mode"] != "production":
        raise ValueError("HA-appen kör bara production; aktivera rätt entities i office.json")
    if not os.environ.get("SUPERVISOR_TOKEN"):
        raise ValueError("Supervisor API-token saknas")
    db = "/data/office.sqlite3"
    snapshots = "/share/kebnekaise/snapshots"
    con = storage.connect(db)
    storage.register(con, settings)
    con.close()
    stop = threading.Event()
    failures = []

    def collect():
        try:
            collector.loop(db, settings, stop)
        except Exception as exc:
            logging.error("Insamlingen stoppades (%s)", type(exc).__name__)
            failures.append(exc)
            stop.set()

    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, lambda *_: stop.set())
    worker = threading.Thread(target=collect)
    worker.start()
    try:
        while not stop.wait(60):
            daily_backup(db, snapshots)
    finally:
        stop.set()
        worker.join(timeout=15)
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
