import copy
import io
import json
import sqlite3
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from kebnekaise import analytics, cli, collector, config, matter, server, storage
from scripts.daily_backup import daily_backup

ROOT = Path(__file__).resolve().parents[1]
T0 = 1789372800


class MatterTests(unittest.TestCase):
    def setUp(self):
        self.config = config.load(ROOT / "config/matter-pilot.example.json")
        self.sensor = self.config["sensors"][0]
        self.result = {"received_at": T0, "attributes": {"1/1026/0": 2392, "1/1037/0": 391, "1/1037/8": 0}}

    def decode(self, result=None):
        return matter.decode_sensor(self.sensor, self.result if result is None else result, T0, T0+15)

    def test_units_paths_and_receipt_time(self):
        rows, errors = self.decode()
        self.assertEqual(errors, [])
        self.assertEqual(rows, [("matter-sensor-1", "temperature", "matter", T0, 23.92, "matter_read_received"),
                                ("matter-sensor-1", "co2", "matter", T0, 391, "matter_read_received")])
        self.sensor["endpoints"]["co2"] = 4
        self.result["attributes"] = {"1/1026/0": 2392, "4/1037/0": 600.5, "4/1037/8": 0}
        self.assertEqual(self.decode()[0][1][4], 600.5)

    def test_invalid_co2_never_becomes_zero_or_blocks_valid_temperature(self):
        for raw in (None, True, False, "391", float("nan"), float("inf"), 0, 40001):
            with self.subTest(raw=raw):
                self.result["attributes"]["1/1037/0"] = raw
                rows, errors = self.decode()
                self.assertEqual([r[1] for r in rows], ["temperature"])
                self.assertTrue(errors)

    def test_temperature_is_nullable_integer_hundredths(self):
        for raw in (None, True, "2392", 2392.5, -32768, 8501):
            self.result["attributes"]["1/1026/0"] = raw
            rows, errors = self.decode()
            self.assertEqual([r[1] for r in rows], ["co2"])
            self.assertTrue(errors)

    def test_co2_requires_ppm_in_same_successful_read(self):
        for unit in (None, False, "0", 0.0, 1, 2):
            self.result["attributes"]["1/1037/8"] = unit
            self.assertEqual([r[1] for r in self.decode()[0]], ["temperature"])
        del self.result["attributes"]["1/1037/8"]
        self.assertEqual([r[1] for r in self.decode()[0]], ["temperature"])

    def test_cached_old_future_and_missing_timestamps_rejected(self):
        for ts in (None, True, T0-1, T0+16, float(T0)):
            self.result["received_at"] = ts
            self.assertEqual(self.decode()[0], [])
        for result in ({"attributes": {}}, {"error": "timeout", **self.result}, None, []):
            self.assertEqual(matter.decode_sensor(self.sensor, result, T0, T0+15)[0], [])

    def test_loopback_settings_and_duplicate_mapping_validation(self):
        for url in ("ws://192.0.2.10:5580/ws", "wss://127.0.0.1:5580/ws", "ws://user@127.0.0.1:5580/ws",
                    "ws://127.0.0.1:5580/ws?token=secret", "ws://127.0.0.1:5580/other"):
            changed = copy.deepcopy(self.config)
            changed["matter"]["url"] = url
            with self.assertRaises(ValueError):
                config.validate(changed)
        for key, value in (("node_id", True), ("node_id", 2**53), ("node_id", 1.5), ("endpoints", {"temperature": 1, "co2": False})):
            changed = copy.deepcopy(self.config)
            changed["sensors"][0][key] = value
            with self.assertRaises(ValueError):
                config.validate(changed)
        other = copy.deepcopy(self.sensor)
        other["id"] = "matter-sensor-2"
        self.config["sensors"].append(other)
        with self.assertRaisesRegex(ValueError, "Samma Matter"):
            config.validate(self.config)

    def test_read_process_is_bounded_and_batches_requested_attributes(self):
        second = copy.deepcopy(self.sensor)
        second["endpoints"] = {"temperature": 2, "co2": 2}
        with patch("kebnekaise.matter.subprocess.run") as run:
            run.return_value.stdout = json.dumps({"1": self.result})
            matter.read_nodes(self.config, [self.sensor, second])
            args, kwargs = run.call_args
            self.assertEqual(args[0], [self.config["matter"]["node_path"], str(matter.HELPER)])
            request = json.loads(kwargs["input"])
            self.assertEqual(len(request["reads"]), 1)
            self.assertEqual(len(request["reads"][0]["attributes"]), 6)
            self.assertEqual(kwargs["timeout"], 20)
            self.assertTrue(kwargs["check"])
            self.assertEqual(kwargs["env"], {})

    def test_missing_node_runtime_is_a_gap(self):
        self.config["matter"]["node_path"] = "/does-not-exist/node"
        rows, health = matter.collect(self.config, [self.sensor])
        self.assertEqual(rows, [])
        self.assertFalse(health[0][2])

    def test_unchanged_readings_then_outage_and_recovery_persist_correctly(self):
        with tempfile.TemporaryDirectory() as tmp:
            con = storage.connect(Path(tmp) / "pilot.sqlite3")
            self.addCleanup(con.close)
            storage.register(con, self.config)
            instance = collector.Collector(self.config)
            for ts in (T0, T0+60):
                self.result["received_at"] = ts
                with patch("kebnekaise.matter.read_nodes", return_value={"1": self.result}), patch("kebnekaise.matter.time.time", return_value=ts):
                    self.assertEqual(instance.tick(con, now=ts), 2)
                    self.assertEqual(instance.tick(con, now=ts), 0)  # Duplicate delivery.
            with patch("kebnekaise.matter.read_nodes", side_effect=OSError), patch("kebnekaise.matter.time.time", return_value=T0+240):
                self.assertEqual(instance.tick(con, now=T0+240), 0)
            self.assertEqual(con.execute("SELECT MAX(ts),COUNT(*) FROM readings").fetchone()[:], (T0+60, 4))
            self.assertFalse(con.execute("SELECT ok FROM health").fetchone()[0])
            self.result["received_at"] = T0+360
            with patch("kebnekaise.matter.read_nodes", return_value={"1": self.result}), patch("kebnekaise.matter.time.time", return_value=T0+360):
                self.assertEqual(instance.tick(con, now=T0+360), 2)
            self.assertTrue(con.execute("SELECT ok FROM health").fetchone()[0])
            summary = analytics.summarize(con, self.config, T0, T0+420, source="matter")
            self.assertEqual({r["observed_seconds"] for r in summary["summary"]}, {240})
            self.assertEqual({r["source"] for r in summary["summary"]}, {"matter"})
            handle = io.StringIO()
            self.assertEqual(cli.export_csv(con, handle, source="matter"), 6)
            self.assertIn("matter_read_received", handle.getvalue())
            self.assertEqual(cli.export_csv(con, io.StringIO(), source="ha"), 0)
            event = server.add_event(con, self.config, {"kind": "note", "note": "Start av pilottest"})
            self.assertEqual(con.execute("SELECT source FROM events WHERE id=?", (event,)).fetchone()[0], "matter")
            daily_backup(Path(tmp) / "pilot.sqlite3", Path(tmp) / "backups", prefix="pilot")
            backup_path, = (Path(tmp) / "backups").glob("pilot-*.sqlite3")
            restored = storage.connect(backup_path)
            try:
                storage.register(restored, self.config)
                self.assertEqual(restored.execute("PRAGMA integrity_check").fetchone()[0], "ok")
                self.assertEqual(restored.execute("SELECT COUNT(*) FROM readings").fetchone()[0], 6)
            finally:
                restored.close()


class MigrationTests(unittest.TestCase):
    def test_v1_migration_preserves_history_metadata_index_and_source_constraint(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "v1.sqlite3"
            original = sqlite3.connect(path)
            original.executescript(storage.SCHEMA.replace("'ha','matter',", "'ha',"))
            with original:
                original.executemany("INSERT INTO metadata VALUES (?,?)", [("schema_version", "1"), ("mode", "pilot")])
                original.execute("INSERT INTO configurations VALUES ('hash', ?, '{}')", (T0,))
                original.execute("INSERT INTO readings VALUES ('old','co2','ha',?,800,?,'hash','ha_last_reported')", (T0, T0))
                original.execute("INSERT INTO events VALUES ('note',?,'old','note','Kept','ha')", (T0,))
                original.execute("INSERT INTO health VALUES ('old',?,1,'Kept')", (T0,))
            original.close()
            for _ in range(2):
                con = storage.connect(path)
                try:
                    self.assertEqual(con.execute("SELECT value FROM metadata WHERE key='schema_version'").fetchone()[0], "2")
                    self.assertEqual(con.execute("SELECT value FROM readings WHERE source='ha'").fetchone()[0], 800)
                    self.assertEqual(con.execute("SELECT body FROM configurations").fetchone()[0], "{}")
                    self.assertEqual(con.execute("SELECT note FROM events").fetchone()[0], "Kept")
                    self.assertEqual(con.execute("SELECT detail FROM health").fetchone()[0], "Kept")
                    self.assertIsNotNone(con.execute("SELECT 1 FROM sqlite_master WHERE name='readings_time'").fetchone())
                    with self.assertRaises(sqlite3.IntegrityError), con:
                        con.execute("UPDATE readings SET source='invented'")
                    with con:
                        con.execute("INSERT OR IGNORE INTO readings VALUES ('new','co2','matter',?,391,?,'hash','matter_read_received')", (T0, T0))
                finally:
                    con.close()

    def test_unknown_schema_is_unchanged_even_in_journal_mode(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "future.sqlite3"
            con = sqlite3.connect(path)
            con.executescript("CREATE TABLE metadata(key TEXT PRIMARY KEY,value TEXT); INSERT INTO metadata VALUES ('schema_version','999');")
            con.close()
            before = path.read_bytes()
            with self.assertRaisesRegex(ValueError, "okänd"):
                storage.connect(path)
            self.assertEqual(path.read_bytes(), before)

    def test_failed_migration_rolls_back_original_table_and_schema(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "broken.sqlite3"
            con = sqlite3.connect(path)
            con.executescript(storage.SCHEMA.replace("'ha','matter',", "'ha',"))
            with con:
                con.execute("INSERT INTO metadata VALUES ('schema_version','1')")
                con.execute("INSERT INTO readings VALUES ('old','co2','ha',?,800,?,'hash','ha_last_reported')", (T0, T0))
            con.close()
            with patch("kebnekaise.storage.SCHEMA", storage.SCHEMA + "INVALID SQL;"), self.assertRaises(sqlite3.Error):
                storage.connect(path)
            with sqlite3.connect(path) as restored:
                self.assertEqual(restored.execute("SELECT value FROM metadata").fetchone()[0], "1")
                self.assertEqual(restored.execute("SELECT value FROM readings").fetchone()[0], 800)
                self.assertIsNone(restored.execute("SELECT 1 FROM sqlite_master WHERE name='readings_v1'").fetchone())
