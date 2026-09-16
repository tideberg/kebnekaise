"""Loopback-only UI. Explicit assets, no directory listing, no external resources."""

from __future__ import annotations

import hmac
import json
import secrets
import sqlite3
import threading
import time
import urllib.parse
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from . import __version__, analytics, storage
from .adapters import timestamp
from .config import METRICS, SOURCES

WEB = Path(__file__).parent / "web"
ASSETS = {"/": ("index.html", "text/html; charset=utf-8"),
          "/style.css": ("style.css", "text/css; charset=utf-8"),
          "/app.js": ("app.js", "text/javascript; charset=utf-8")}
EVENT_KINDS = {"warm", "cold", "stuffy", "window", "presentation", "note"}


def add_event(con, config, body):
    sensor = body.get("sensor", "all")
    if sensor not in {s["id"] for s in config["sensors"]} | {"all"}:
        raise ValueError("Okänd mätpunkt")
    kind = body.get("kind")
    if kind not in EVENT_KINDS:
        raise ValueError("Okänd händelsetyp")
    note = body.get("note", "")
    if not isinstance(note, str) or len(note) > 200 or any(ord(c) < 32 for c in note):
        raise ValueError("Noteringen får innehålla högst 200 tecken, utan radbrytning")
    ts = timestamp(body["time"]) if body.get("time") else int(time.time())
    if not 946684800 <= ts <= time.time() + 120:
        raise ValueError("Händelsen måste ha en giltig tid som inte ligger i framtiden")
    active = next((s["provider"] for s in config["sensors"] if s["id"] == sensor), None)
    if sensor == "all":
        providers = {s["provider"] for s in config["sensors"] if s["provider"] in SOURCES}
        if len(providers) == 1:
            active = providers.pop()
    source = active if active in SOURCES else "ha" if config["mode"] == "production" else "simulation" if config["mode"] == "demo" else "replay"
    event_id = str(uuid.uuid4())
    with con:
        con.execute("INSERT INTO events VALUES (?,?,?,?,?,?)",
                    (event_id, ts, sensor, kind, note, source))
    return event_id


class LocalServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, address, handler):
        if address[0] != "127.0.0.1":
            raise ValueError("Dashboarden får bara lyssna på 127.0.0.1")
        self.slots = threading.BoundedSemaphore(8)
        super().__init__(address, handler)

    def process_request(self, request, client_address):
        if not self.slots.acquire(blocking=False):
            self.shutdown_request(request)
            return
        try:
            super().process_request(request, client_address)
        except BaseException:
            self.slots.release()
            raise

    def process_request_thread(self, request, client_address):
        try:
            super().process_request_thread(request, client_address)
        finally:
            self.slots.release()


def make_server(path, config, port=8840):
    csrf = secrets.token_urlsafe(32)

    class Handler(BaseHTTPRequestHandler):
        server_version = "Kebnekaise"
        sys_version = ""

        def setup(self):
            super().setup()
            self.connection.settimeout(10)

        def log_message(self, fmt, *args):
            pass  # No URLs, credentials, or user-supplied strings in access logs.

        def guard(self, write=False):
            port = self.server.server_port
            allowed = {f"127.0.0.1:{port}", f"localhost:{port}"}
            if self.headers.get("Host") not in allowed:
                self.reply(403, {"error": "Ogiltig Host"})
                return False
            origin = self.headers.get("Origin")
            if origin and origin not in {"http://" + host for host in allowed}:
                self.reply(403, {"error": "Extern origin avvisad"})
                return False
            if self.headers.get("Sec-Fetch-Site") == "cross-site":
                self.reply(403, {"error": "Extern webbplats avvisad"})
                return False
            if write and not hmac.compare_digest(self.headers.get("X-Kebnekaise-Token", "").encode(), csrf.encode()):
                self.reply(403, {"error": "Skrivtoken saknas; ladda om sidan"})
                return False
            return True

        def reply(self, status, body, content_type="application/json; charset=utf-8"):
            data = json.dumps(body, ensure_ascii=False, allow_nan=False).encode() if isinstance(body, (dict, list)) else body
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("X-Frame-Options", "DENY")
            self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'")
            self.send_header("Connection", "close")
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            if not self.guard():
                return
            parsed = urllib.parse.urlsplit(self.path)
            if parsed.path in ASSETS:
                name, mime = ASSETS[parsed.path]
                self.reply(200, (WEB / name).read_bytes(), mime)
                return
            if parsed.path == "/api/config":
                public = {key: config[key] for key in ("mode", "timezone", "interval_seconds", "max_hold_seconds", "thresholds", "work_hours")}
                public["sensors"] = [{k: s[k] for k in ("id", "name", "room", "zone", "provider")} for s in config["sensors"]]
                public["site_name"] = config.get("site_name", "Kontoret")
                public.update({"version": __version__, "csrf": csrf})
                self.reply(200, public)
                return
            con = None
            try:
                con = storage.read_connection(path)
                if parsed.path == "/api/status":
                    now = int(time.time())
                    latest = []
                    for sensor in config["sensors"]:
                        for metric in METRICS:
                            for source in sorted(SOURCES):
                                found = con.execute("SELECT sensor,metric,source,ts,value FROM readings WHERE sensor=? AND metric=? AND source=? ORDER BY ts DESC LIMIT 1",
                                    (sensor["id"], metric, source)).fetchone()
                                if found:
                                    row = dict(found)
                                    row["stale"] = now-row["ts"] > config["max_hold_seconds"]
                                    latest.append(row)
                    health = [dict(r) for r in con.execute("SELECT * FROM health")]
                    self.reply(200, {"now": now, "latest": latest, "health": health})
                elif parsed.path == "/api/data":
                    q = urllib.parse.parse_qs(parsed.query, max_num_fields=12)
                    source = q.get("source", ["all"])[0]
                    metric = q.get("metric", ["co2"])[0]
                    sensor = q.get("sensor", ["all"])[0]
                    if source not in SOURCES | {"all"} or metric not in METRICS or sensor not in {s["id"] for s in config["sensors"]} | {"all"}:
                        raise ValueError("Okänt filter")
                    end = int(q.get("end", [int(time.time())])[0])
                    start = int(q.get("start", [end-14*86400])[0])
                    if start < 946684800 or end > time.time()+120:
                        raise ValueError("Ogiltig period")
                    self.reply(200, analytics.summarize(con, config, start, end,
                        q.get("work", ["0"])[0] == "1", source, metric, sensor))
                else:
                    self.reply(404, {"error": "Finns inte"})
            except (ValueError, TypeError):
                self.reply(400, {"error": "Ogiltig fråga. Kontrollera filter och period (högst 366 dagar)."})
            except sqlite3.Error:
                self.reply(503, {"error": "Databasen är upptagen eller otillgänglig"})
            finally:
                if con:
                    con.close()

        def do_POST(self):
            if not self.guard(write=True):
                return
            if self.path != "/api/events":
                self.reply(404, {"error": "Finns inte"})
                return
            con = None
            try:
                size = int(self.headers.get("Content-Length", "0"))
                if not 1 <= size <= 4096 or self.headers.get("Content-Type") != "application/json" or self.headers.get("Transfer-Encoding"):
                    raise ValueError("Ogiltigt format")
                body = json.loads(self.rfile.read(size))
                if not isinstance(body, dict):
                    raise ValueError("Ett objekt krävs")
                con = storage.connect(path)
                event_id = add_event(con, config, body)
                self.reply(201, {"id": event_id})
            except (ValueError, TypeError):
                self.reply(400, {"error": "Ogiltig händelse. Kontrollera tid, mätpunkt och text (högst 200 tecken)."})
            except sqlite3.Error:
                self.reply(503, {"error": "Databasen är upptagen eller otillgänglig"})
            finally:
                if con:
                    con.close()

    return LocalServer(("127.0.0.1", port), Handler)
