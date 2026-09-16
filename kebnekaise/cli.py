"""Command line entry points. All defaults stay local and explicitly synthetic."""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import logging
import os
import signal
import sqlite3
import sys
import threading
import time
import uuid
import zipfile
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from . import __version__, adapters, analytics, collector, config as configuration, mock_ha, server, storage
from .simulation import Simulator


def seed(con, config, days, end):
    if config["mode"] != "demo" or any(s["provider"] != "simulation" for s in config["sensors"]):
        raise ValueError("Historisk simulering får bara skrivas till en ren demokonfiguration")
    if not 1 <= days <= 366:
        raise ValueError("Välj 1–366 dagar")
    if end > time.time() + 120 or end - days*86400 < 946684800:
        raise ValueError("Simuleringens tidsintervall ligger utanför tillåtna datum")
    interval = config["interval_seconds"]
    end = end // interval * interval
    start = end-days*86400
    simulator, rows, count = Simulator(config), [], 0
    for ts in range(start, end+1, interval):
        rows.extend(simulator.sample(ts))
        if len(rows) >= 10000:
            count += storage.insert(con, config, rows)
            rows.clear()
    count += storage.insert(con, config, rows)
    zone = ZoneInfo(config["timezone"])
    day = datetime.fromtimestamp(start, zone).date()
    last = datetime.fromtimestamp(end, zone).date()
    with con:
        while day <= last:
            if day.weekday() < 5:
                examples = [("sw-3a", "warm", 15, "Simulerad upplevelse: varmt vid fönstersidan"),
                            ("ne-1", "cold", 9, "Simulerad upplevelse: svalt på morgonen")]
                if day.weekday() == 2:
                    examples.append(("lunch", "presentation", 14, "Simulerad presentation i luncharean"))
                for sid, kind, hour, note in examples:
                    ts = int(datetime(day.year, day.month, day.day, hour, 15, tzinfo=zone).timestamp())
                    if start <= ts <= end:
                        event_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"kebnekaise/demo/{ts}/{sid}/{kind}"))
                        con.execute("INSERT OR IGNORE INTO events VALUES (?,?,?,?,?,?)",
                                    (event_id, ts, sid, kind, note, "simulation"))
            day += timedelta(days=1)
    return count


def export_csv(con, handle, source="all"):
    writer = csv.writer(handle)
    writer.writerow(["timestamp", "sensor", "metric", "value", "source", "timestamp_kind", "config_hash", "received_at"])
    sql = "SELECT * FROM readings"
    args = ()
    if source != "all":
        sql += " WHERE source=?"
        args = (source,)
    sql += " ORDER BY ts,sensor,metric,source"
    count = 0
    for row in con.execute(sql, args):
        writer.writerow([adapters.iso(row["ts"]), row["sensor"], row["metric"], row["value"], row["source"],
                         row["timestamp_kind"], row["config_hash"], adapters.iso(row["received_at"])])
        count += 1
    return count


def import_csv(con, config, filename):
    path = Path(filename)
    if path.stat().st_size > 500_000_000:
        raise ValueError("CSV-filen är större än 500 MB; dela den före import")
    rows, now, digest = [], int(time.time()), configuration.fingerprint(config)
    with path.open("rb") as handle:
        file_digest = hashlib.file_digest(handle, "sha256").hexdigest()
    # Stream bounded chunks inside one transaction: a late bad row rolls it all back.
    with con, path.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        if not {"timestamp", "sensor", "metric", "value"} <= set(reader.fieldnames or []):
            raise ValueError("CSV kräver timestamp,sensor,metric,value")
        before = con.total_changes
        for row in reader:
            reading = (row["sensor"], row["metric"], "replay", adapters.timestamp(row["timestamp"]),
                       float(row["value"]), "imported")
            storage.validate_reading(reading, config, now)
            sid, metric, source, ts, value, kind = reading
            rows.append((sid, metric, source, ts, value, now, digest, kind))
            if len(rows) == 4000:
                con.executemany("INSERT OR IGNORE INTO readings VALUES (?,?,?,?,?,?,?,?)", rows)
                rows.clear()
        con.executemany("INSERT OR IGNORE INTO readings VALUES (?,?,?,?,?,?,?,?)", rows)
        count = con.total_changes - before
        con.execute("INSERT OR IGNORE INTO metadata VALUES (?,?)",
                    ("import:" + file_digest, str(now)))
    return count


def exclusive_text(path):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    return os.fdopen(fd, "w", encoding="utf-8", newline="")


def make_bundle(con, config, target, source):
    # Offline hand-off artifact. No upload or network client is invoked here.
    import tempfile
    target = Path(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    os.close(fd)
    try:
        with tempfile.TemporaryDirectory(prefix="kebnekaise-export-") as tmp:
            csv_path = Path(tmp) / "readings.csv"
            with csv_path.open("w", encoding="utf-8", newline="") as handle:
                count = export_csv(con, handle, source)
            with csv_path.open("rb") as handle:
                digest = hashlib.file_digest(handle, "sha256").hexdigest()
            manifest = {"schema_version": 1, "app_version": __version__, "created_at": adapters.iso(int(time.time())),
                        "source_filter": source, "mode": config["mode"], "rows": count,
                        "files": {"readings.csv": {"sha256": digest, "bytes": csv_path.stat().st_size}},
                        "idempotency_key": ["sensor", "metric", "source", "timestamp"]}
            with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_DEFLATED) as out:
                out.write(csv_path, "readings.csv")
                out.writestr("manifest.json", json.dumps(manifest, indent=2, ensure_ascii=False))
        return count
    except BaseException:
        target.unlink(missing_ok=True)
        raise


def report(con, config, days, work):
    now = int(time.time())
    result = analytics.summarize(con, config, now-days*86400, now, work)
    names = {s["id"]: s["name"] for s in config["sensors"]}
    lines = ["# Klimatrapport", "", f"Läge: **{config['mode']}**. Genererad {adapters.iso(now)}.", "",
             f"Period: {adapters.iso(result['start'])} – {adapters.iso(now)}. " +
             (f"Vardagar {config['work_hours'][0]}–{config['work_hours'][1]}, {config['timezone']}." if work else "Hela dygnet."),
             "", "Källorna hålls isär. Referenslinjerna är undersökningsstöd, inte en bedömning av arbetsmiljön.", "",
             f"Analysreferenser: CO₂ {config['thresholds']['co2']} ppm; temperatur "
             f"{config['thresholds']['temperature_low']}–{config['thresholds']['temperature_high']} °C.", "",
             "| Mätpunkt | Källa | Storhet | Medel | P95 | Min–max | Över referens (h) | Under (h) | Täckning |",
             "|---|---|---|---:|---:|---:|---:|---:|---:|"]
    for row in result["summary"]:
        if row["mean"] is None:
            continue
        lines.append(f"| {names[row['sensor']].replace('|', '/')} | {row['source']} | {row['metric']} | "
                     f"{row['mean']:.1f} | {row['p95']:.1f} | {row['min']:.1f}–{row['max']:.1f} | "
                     f"{row['above_seconds']/3600:.1f} | {row['below_seconds']/3600:.1f} | "
                     f"{100*row['coverage']:.1f}% |")
    lines += ["", f"Värden hålls högst {config['max_hold_seconds']} s; därefter räknas tiden som saknad. "
              "Medel, P95 och tid över/under referens är tidsviktade. P95 avrundas till 0,01 °C respektive 1 ppm.",
              "Täckning betyder tid med ett tillräckligt färskt rapporterat värde, inte antal fysiska sensormätningar.",
              "Lufttemperatur och CO₂ kan inte ensamma beskriva drag, strålningstemperatur eller all luftkvalitet.", ""]
    return "\n".join(lines)


def run_service(args, config, with_collector):
    stop, failures = threading.Event(), []
    http = server.make_server(args.db, config, args.port)

    def collect():
        try:
            collector.loop(args.db, config, stop)
        except BaseException as exc:
            failures.append(exc)
            stop.set()
            http.shutdown()

    thread = threading.Thread(target=collect, name="collector") if with_collector else None

    def shutdown(*_):
        stop.set()
        threading.Thread(target=http.shutdown, daemon=True).start()

    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, shutdown)
    if thread:
        thread.start()
    print(f"Kebnekaise · {config['mode']} · http://127.0.0.1:{http.server_port} · Ctrl-C avslutar", flush=True)
    try:
        http.serve_forever(poll_interval=.2)
    finally:
        stop.set()
        http.server_close()
        if thread:
            thread.join(timeout=15)
    if failures:
        raise ValueError(f"Insamlaren stoppades: {failures[0]}")


def parser():
    p = argparse.ArgumentParser(description="Lokal klimathistorik. Python 3.11+, inga pip-paket.")
    p.add_argument("--config", default="config/demo.json")
    p.add_argument("--db", default="data/demo.sqlite3")
    sub = p.add_subparsers(dest="command", required=True)
    sub.add_parser("init", help="validera konfiguration och skapa databas")
    s = sub.add_parser("seed", help="skapa idempotent simulerad historik, endast demo")
    s.add_argument("--days", type=int, default=28)
    s.add_argument("--end", help="ISO-tid med tidszon; standard är nu")
    for name in ("run", "serve"):
        s = sub.add_parser(name, help="dashboard och insamling" if name == "run" else "bara dashboard")
        s.add_argument("--port", type=int, default=8840)
    s = sub.add_parser("collect", help="samla data utan dashboard")
    s.add_argument("--once", action="store_true")
    s = sub.add_parser("mock-ha", help="lokal HA-simulator för adaptertest")
    s.add_argument("--port", type=int, default=8841)
    s.add_argument("--fault", choices=["none", "offline", "stale", "bad-unit"], default="none")
    s = sub.add_parser("export", help="exportera alla råvärden till CSV")
    s.add_argument("--output", required=True)
    s.add_argument("--source", choices=["all"] + sorted(configuration.SOURCES), default="all")
    s = sub.add_parser("bundle", help="skapa ZIP med CSV och SHA-256-manifest för lokal överföring")
    s.add_argument("--output", required=True)
    s.add_argument("--source", choices=["all"] + sorted(configuration.SOURCES), default="ha")
    s = sub.add_parser("import-csv", help="importera CSV som replay, aldrig som verklig live-data")
    s.add_argument("--file", required=True)
    s = sub.add_parser("backup", help="konsistent SQLite-backup, även under pågående insamling")
    s.add_argument("--output", required=True)
    sub.add_parser("check", help="SQLite-integritet och antal lagrade värden")
    s = sub.add_parser("report", help="skriv tidsviktad rapport i Markdown")
    s.add_argument("--days", type=int, default=28)
    s.add_argument("--work", action="store_true")
    s.add_argument("--output", required=True)
    s = sub.add_parser("note", help="markera upplevelse eller händelse utan personuppgifter")
    s.add_argument("--sensor", default="all")
    s.add_argument("--kind", choices=sorted(server.EVENT_KINDS), required=True)
    s.add_argument("--text", default="")
    s.add_argument("--at", help="ISO-tid med tidszon; standard är nu")
    return p


def main(argv=None):
    os.umask(0o077)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    args = parser().parse_args(argv)
    try:
        config = configuration.load(args.config)
        con = storage.connect(args.db)
        try:
            storage.register(con, config)
            if args.command == "init":
                print(f"OK: {len(config['sensors'])} mätpunkter, {config['mode']}, {args.db}")
            elif args.command == "seed":
                end = adapters.timestamp(args.end) if args.end else int(time.time())
                print(f"{seed(con, config, args.days, end):,} nya simulerade värden")
            elif args.command in {"run", "serve"}:
                con.close()
                con = None
                run_service(args, config, args.command == "run")
            elif args.command == "collect":
                if args.once:
                    print(f"{collector.Collector(config).tick(con)} nya värden")
                else:
                    con.close()
                    con = None
                    stop = threading.Event()
                    for sig in (signal.SIGINT, signal.SIGTERM):
                        signal.signal(sig, lambda *_: stop.set())
                    collector.loop(args.db, config, stop)
            elif args.command == "mock-ha":
                mock = mock_ha.make_mock(config, args.port, args.fault)
                print(f"SIMULERAD HA på http://127.0.0.1:{args.port}, felfall={args.fault}", flush=True)
                try:
                    mock.serve_forever()
                finally:
                    mock.server_close()
            elif args.command == "export":
                with exclusive_text(args.output) as handle:
                    print(f"{export_csv(con, handle, args.source)} värden exporterade till {args.output}")
            elif args.command == "bundle":
                print(f"{make_bundle(con, config, args.output, args.source)} värden i {args.output}")
            elif args.command == "import-csv":
                print(f"{import_csv(con, config, args.file)} importerade replay-värden")
            elif args.command == "backup":
                storage.backup(con, args.output)
                print(f"Verifierad backup: {args.output}")
            elif args.command == "check":
                check = con.execute("PRAGMA integrity_check").fetchone()[0]
                if check != "ok":
                    raise ValueError("SQLite integrity_check misslyckades")
                rows = [dict(r) for r in con.execute("SELECT source,COUNT(*) AS readings,MIN(ts) AS first,MAX(ts) AS last FROM readings GROUP BY source")]
                print(json.dumps({"integrity": check, "mode": config["mode"], "sources": rows}, indent=2))
            elif args.command == "report":
                text = report(con, config, args.days, args.work)
                with exclusive_text(args.output) as handle:
                    handle.write(text)
                print(args.output)
            elif args.command == "note":
                print(server.add_event(con, config, {"sensor": args.sensor, "kind": args.kind, "note": args.text, "time": args.at}))
        finally:
            if con:
                con.close()
        return 0
    except KeyboardInterrupt:
        return 130
    except (ValueError, KeyError, OSError, sqlite3.Error) as exc:
        print(f"Fel: {exc}", file=sys.stderr)
        return 1
