"""One-process supervisor for the two-process HIL demonstration. No packages."""

import os
import secrets
import signal
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from kebnekaise import adapters, config


def main():
    children = []
    os.environ["KEBNEKAISE_HA_TOKEN"] = secrets.token_urlsafe(32)
    environment = os.environ.copy()
    prefix = [sys.executable, "-m", "kebnekaise", "--config", "config/hil.json", "--db", "data/hil.sqlite3"]
    stop = False

    def halt(*_):
        nonlocal stop
        stop = True

    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, halt)
    try:
        children.append(subprocess.Popen(prefix + ["mock-ha"], cwd=ROOT, env=environment))
        ready = False
        for _ in range(30):
            if stop or children[0].poll() is not None:
                break
            try:
                adapters.ha_states(config.load(ROOT / "config/hil.json"))
                ready = True
                break
            except ValueError:
                time.sleep(.1)
        if not ready:
            raise RuntimeError("Mock-HA kunde inte startas på port 8841")
        children.append(subprocess.Popen(prefix + ["run", "--port", "8842"], cwd=ROOT, env=environment))
        print("HIL-demo: http://127.0.0.1:8842 · NE-1 via mock-HA, övriga simulerade. Ctrl-C avslutar båda.", flush=True)
        while not stop:
            if any(c.poll() is not None for c in children):
                raise RuntimeError("En HIL-process avslutades oväntat")
            time.sleep(.25)
        return 0
    finally:
        for child in reversed(children):
            if child.poll() is None:
                child.terminate()
        for child in children:
            try:
                child.wait(timeout=12)
            except subprocess.TimeoutExpired:
                child.kill()
                child.wait()


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except RuntimeError as exc:
        print(f"Fel: {exc}", file=sys.stderr)
        raise SystemExit(1)
