"""SQLite is the source of truth; writes are transactional and idempotent."""

from __future__ import annotations

import json
import math
import os
import sqlite3
import time
from pathlib import Path

from .config import METRICS, SOURCES, fingerprint

SCHEMA = """
CREATE TABLE IF NOT EXISTS metadata(key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS configurations(
    hash TEXT PRIMARY KEY, first_seen INTEGER NOT NULL, body TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS readings(
    sensor TEXT NOT NULL, metric TEXT NOT NULL,
    source TEXT NOT NULL CHECK(source IN ('simulation','ha','matter','mock','replay')),
    ts INTEGER NOT NULL, value REAL NOT NULL, received_at INTEGER NOT NULL,
    config_hash TEXT NOT NULL, timestamp_kind TEXT NOT NULL,
    PRIMARY KEY(sensor, metric, source, ts)
) WITHOUT ROWID;
CREATE INDEX IF NOT EXISTS readings_time ON readings(ts);
CREATE TABLE IF NOT EXISTS events(
    id TEXT PRIMARY KEY, ts INTEGER NOT NULL, sensor TEXT NOT NULL,
    kind TEXT NOT NULL, note TEXT NOT NULL, source TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS health(
    sensor TEXT PRIMARY KEY, checked_at INTEGER NOT NULL,
    ok INTEGER NOT NULL, detail TEXT NOT NULL);
"""


def connect(path):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(path, timeout=15)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA busy_timeout=15000")
    try:
        schema_version(con)  # Refuse unknown versions before changing even journal mode.
        con.execute("PRAGMA journal_mode=WAL")
        con.execute("PRAGMA synchronous=FULL")
        con.execute("BEGIN IMMEDIATE")
        version = schema_version(con)
        if version == "1":
            con.execute("ALTER TABLE readings RENAME TO readings_v1")
            con.execute("DROP INDEX IF EXISTS readings_time")
        # execute(), not executescript(), keeps the entire migration transactional.
        for statement in SCHEMA.split(";"):
            if statement.strip():
                con.execute(statement)
        if version == "1":
            con.execute("INSERT INTO readings SELECT * FROM readings_v1")
            con.execute("DROP TABLE readings_v1")
        con.execute("INSERT OR REPLACE INTO metadata VALUES ('schema_version','2')")
        con.commit()
    except BaseException:
        con.rollback()
        con.close()
        raise
    os.chmod(path, 0o600)
    return con


def schema_version(con):
    if not con.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='metadata'").fetchone():
        if con.execute("SELECT 1 FROM sqlite_master WHERE type='table'").fetchone():
            raise ValueError("Databasens schemaversion saknas")
        return None
    row = con.execute("SELECT value FROM metadata WHERE key='schema_version'").fetchone()
    if not row or row[0] not in {"1", "2"}:
        raise ValueError("Databasen har en okänd schemaversion")
    return row[0]


def read_connection(path):
    con = sqlite3.connect(Path(path).resolve().as_uri() + "?mode=ro", uri=True, timeout=15)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA busy_timeout=15000")
    return con


def register(con, config):
    mode = config["mode"]
    existing = con.execute("SELECT value FROM metadata WHERE key='mode'").fetchone()
    if existing and existing[0] != mode:
        raise ValueError(f"Databasen är {existing[0]}, konfigurationen är {mode}; använd en separat databas")
    digest = fingerprint(config)
    with con:
        con.execute("INSERT OR IGNORE INTO metadata VALUES ('mode',?)", (mode,))
        con.execute("INSERT OR IGNORE INTO configurations VALUES (?,?,?)",
                    (digest, int(time.time()), json.dumps(config, ensure_ascii=False)))
        con.execute("INSERT OR REPLACE INTO metadata VALUES ('active_config',?)", (digest,))
    return digest


def validate_reading(reading, config, now=None):
    now = int(time.time()) if now is None else now
    sensors = {s["id"]: s for s in config["sensors"]}
    sensor, metric, source, ts, value, timestamp_kind = reading
    if sensor not in sensors or metric not in METRICS or source not in SOURCES:
        raise ValueError("Okänd mätpunkt, storhet eller källa")
    if sensors[sensor]["provider"] != source:
        raise ValueError(f"Källa {source} är inte aktiv för {sensor}; ingen automatisk fallback")
    if isinstance(ts, bool) or not isinstance(ts, int) or not 946684800 <= ts <= now + 120:
        raise ValueError("Ogiltig eller framtida tidsstämpel")
    if isinstance(value, bool) or not isinstance(value, (float, int)) or not math.isfinite(value):
        raise ValueError("Mätvärdet måste vara ändligt")
    _, low, high = METRICS[metric]
    if not low <= value <= high:
        raise ValueError(f"Orimligt {metric}: värdet avvisat")
    if timestamp_kind not in {"model", "ha_last_reported", "ha_last_updated", "imported", "matter_read_received"}:
        raise ValueError("Okänd tidsstämpeltyp")
    if (source == "matter") != (timestamp_kind == "matter_read_received"):
        raise ValueError("Matter kräver tidsstämpel från en lyckad fjärravläsning")
    return reading


def insert(con, config, readings, now=None):
    now = int(time.time()) if now is None else now
    digest = fingerprint(config)
    rows = []
    for reading in readings:
        sensor, metric, source, ts, value, kind = validate_reading(reading, config, now)
        rows.append((sensor, metric, source, ts, value, now, digest, kind))
    # Validate the whole batch before starting a write; no partial imports.
    with con:
        before = con.total_changes
        con.executemany("INSERT OR IGNORE INTO readings VALUES (?,?,?,?,?,?,?,?)", rows)
    return con.total_changes - before


def set_health(con, sensor, ok, detail, now=None):
    with con:
        con.execute("INSERT OR REPLACE INTO health VALUES (?,?,?,?)",
                    (sensor, int(time.time()) if now is None else now, bool(ok), detail[:300]))


def backup(con, target):
    target = Path(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    # Exclusive creation prevents an accidental overwrite of an earlier backup.
    fd = os.open(target, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    os.close(fd)
    try:
        dest = sqlite3.connect(target)
        try:
            con.backup(dest)
            if dest.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise ValueError("Backup klarade inte integritetskontrollen")
        finally:
            dest.close()
    except BaseException:
        target.unlink(missing_ok=True)
        raise
