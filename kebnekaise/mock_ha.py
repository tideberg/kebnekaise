"""A local HA REST stand-in to exercise the real adapter without Matter hardware."""

import hmac
import json
import os
import time
from http.server import BaseHTTPRequestHandler

from .adapters import iso
from .config import METRICS
from .server import LocalServer
from .simulation import Simulator


def make_mock(config, port=8841, fault="none"):
    if fault not in {"none", "offline", "stale", "bad-unit"}:
        raise ValueError("Okänt felfall")
    simulator = Simulator(config)
    import threading
    lock = threading.Lock()
    token = os.environ.get(config.get("home_assistant", {}).get("token_env", "KEBNEKAISE_HA_TOKEN"), "")
    if not token:
        raise ValueError("Mock-servern kräver samma tokenmiljövariabel som klienten")

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def setup(self):
            super().setup()
            self.connection.settimeout(5)

        def do_GET(self):
            allowed = {f"127.0.0.1:{self.server.server_port}", f"localhost:{self.server.server_port}"}
            status, data = 200, []
            if self.headers.get("Host") not in allowed:
                status = 403
            elif not hmac.compare_digest(self.headers.get("Authorization", "").encode(), ("Bearer " + token).encode()):
                status = 401
            elif self.path != "/api/states":
                status = 404
            elif fault == "offline":
                status = 503
            else:
                ts = int(time.time()) // 60 * 60
                if fault == "stale":
                    ts -= 3600
                with lock:
                    rows = simulator.sample(ts, providers=("mock",), gaps=False)
                sensors = {s["id"]: s for s in config["sensors"]}
                for sid, metric, source, ts, value, kind in rows:
                    data.append({"entity_id": sensors[sid]["entities"][metric], "state": str(value),
                                 "attributes": {"unit_of_measurement": "wrong" if fault == "bad-unit" else METRICS[metric][0]},
                                 "last_updated": iso(ts), "last_reported": iso(ts)})
            body = json.dumps(data).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Connection", "close")
            self.end_headers()
            self.wfile.write(body)

    return LocalServer(("127.0.0.1", port), Handler)
