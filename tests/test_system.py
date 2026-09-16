import copy
import csv
import io
import json
import os
import sqlite3
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
import zipfile
from datetime import datetime
from pathlib import Path
from unittest.mock import patch
from zoneinfo import ZoneInfo

from kebnekaise import adapters, analytics, cli, collector, config, mock_ha, server, storage
from kebnekaise.simulation import Simulator, co2_step

ROOT = Path(__file__).resolve().parents[1]
T0 = 1789372800  # A fixed historical timestamp; no dependency on network time.


class DatabaseCase(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / "test.sqlite3"
        self.config = config.load(ROOT / "config/demo.json")
        self.con = storage.connect(self.path)
        storage.register(self.con, self.config)

    def tearDown(self):
        self.con.close()
        self.temp.cleanup()

    def put(self, rows):
        return storage.insert(self.con, self.config, rows)

    def row(self, ts=T0, value=800, metric="co2", source="simulation", sid="ne-1"):
        return sid, metric, source, ts, value, "model" if source == "simulation" else "imported"


class StorageTests(DatabaseCase):
    def test_read_connection_is_enforced_read_only(self):
        connection = storage.read_connection(self.path)
        try:
            with self.assertRaises(sqlite3.OperationalError):
                connection.execute("DELETE FROM metadata")
        finally:
            connection.close()

    def test_second_continuous_collector_is_refused(self):
        import fcntl
        with Path(str(self.path) + ".collector.lock").open("w") as handle:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
            with self.assertRaisesRegex(ValueError, "redan"):
                collector.loop(self.path, self.config, threading.Event())

    def test_duplicate_delivery_is_idempotent(self):
        row = self.row()
        self.assertEqual(self.put([row]), 1)
        self.assertEqual(self.put([row]), 0)
        self.assertEqual(self.con.execute("SELECT COUNT(*) FROM readings").fetchone()[0], 1)

    def test_invalid_batch_is_atomic_and_never_clamps(self):
        for value in (float("nan"), float("inf"), -200, 50000, True):
            with self.assertRaises(ValueError):
                self.put([self.row(), self.row(T0+60, value)])
            self.assertEqual(self.con.execute("SELECT COUNT(*) FROM readings").fetchone()[0], 0)

    def test_source_and_database_mode_cannot_be_changed_silently(self):
        with self.assertRaises(ValueError):
            self.put([self.row(source="ha")])
        office = config.load(ROOT / "config/office.example.json")
        with self.assertRaises(ValueError):
            storage.register(self.con, office)
        office["sensors"][0]["provider"] = "simulation"
        with self.assertRaises(ValueError):
            config.validate(office)

    def test_future_and_unknown_sensor_rejected(self):
        for row in (self.row(int(time.time())+10000), self.row(sid="unknown")):
            with self.assertRaises(ValueError):
                self.put([row])

    def test_backup_restores_committed_wal_data_and_refuses_overwrite(self):
        self.put([self.row()])
        target = Path(self.temp.name) / "backup.sqlite3"
        storage.backup(self.con, target)
        with sqlite3.connect(target) as restore:
            self.assertEqual(restore.execute("PRAGMA integrity_check").fetchone()[0], "ok")
            self.assertEqual(restore.execute("SELECT value FROM readings").fetchone()[0], 800)
        with self.assertRaises(FileExistsError):
            storage.backup(self.con, target)
        self.assertEqual(target.stat().st_mode & 0o777, 0o600)

    def test_configuration_history_is_preserved(self):
        before = config.fingerprint(self.config)
        self.put([self.row()])
        self.config["sensors"][0]["name"] = "Flyttad placering"
        after = storage.register(self.con, self.config)
        self.assertNotEqual(before, after)
        self.put([self.row(T0+60)])
        self.assertEqual(self.con.execute("SELECT COUNT(DISTINCT config_hash) FROM readings").fetchone()[0], 2)


class AnalyticsTests(DatabaseCase):
    def test_time_weighted_mean_p95_and_missing_time(self):
        self.config["max_hold_seconds"] = 60
        storage.register(self.con, self.config)
        self.put([self.row(T0, 800), self.row(T0+30, 1200), self.row(T0+300, 600)])
        result = analytics.summarize(self.con, self.config, T0, T0+360)
        row = result["summary"][0]
        # 30s*800 + 60s*1200 + 60s*600; 210s missing.
        self.assertEqual(row["observed_seconds"], 150)
        self.assertEqual(row["above_seconds"], 60)
        self.assertAlmostEqual(row["mean"], 880)
        self.assertEqual(row["p95"], 1200)
        self.assertAlmostEqual(row["coverage"], 150/360)
        self.assertTrue(any(p["mean"] is None for p in result["series"][0]["points"]))

    def test_preperiod_value_is_held_only_until_age_limit(self):
        self.config["max_hold_seconds"] = 60
        self.put([self.row(T0-20, 900)])
        row = analytics.summarize(self.con, self.config, T0, T0+120)["summary"][0]
        self.assertEqual(row["observed_seconds"], 40)

    def test_temperature_above_and_below_are_separate(self):
        self.put([self.row(T0, 19, "temperature"), self.row(T0+60, 25, "temperature")])
        row = analytics.summarize(self.con, self.config, T0, T0+120, metric="temperature")["summary"][0]
        self.assertEqual((row["below_seconds"], row["above_seconds"]), (60, 60))

    def test_sources_are_never_averaged_together(self):
        self.put([self.row(T0, 800)])
        self.config["sensors"][0]["provider"] = "replay"
        storage.register(self.con, self.config)
        self.put([self.row(T0, 1800, source="replay")])
        result = analytics.summarize(self.con, self.config, T0, T0+60)
        self.assertEqual({r["mean"] for r in result["summary"]}, {800, 1800})
        result = analytics.summarize(self.con, self.config, T0, T0+60, source="replay")
        self.assertEqual(len(result["summary"]), 1)

    def test_empty_weekend_does_not_report_zero_or_full_coverage(self):
        zone = ZoneInfo("Europe/Stockholm")
        start = int(datetime(2026, 9, 12, tzinfo=zone).timestamp())
        self.put([self.row(start, 800)])
        result = analytics.summarize(self.con, self.config, start, start+86400, True)
        self.assertEqual(result["expected_seconds"], 0)
        self.assertIsNone(result["summary"][0]["mean"])
        self.assertIsNone(result["summary"][0]["coverage"])

    def test_dst_days_and_workday_boundaries(self):
        zone = ZoneInfo("Europe/Stockholm")
        for date, hours in (((2026, 3, 29), 23), ((2025, 10, 26), 25)):
            start = int(datetime(*date, tzinfo=zone).timestamp())
            from datetime import timedelta
            end = int((datetime(*date, tzinfo=zone) + timedelta(days=1)).timestamp())
            spans = analytics.windows(start, end, str(zone), [0, 24], False)
            self.assertEqual(sum(b-a for a, b in spans), hours*3600)
        start = int(datetime(2026, 3, 27, tzinfo=zone).timestamp())
        end = int(datetime(2026, 3, 31, tzinfo=zone).timestamp())
        spans = analytics.windows(start, end, str(zone), [8, 17], True)
        self.assertEqual(sum(b-a for a, b in spans), 2*9*3600)

    def test_unbounded_query_refused(self):
        with self.assertRaises(ValueError):
            analytics.summarize(self.con, self.config, T0, T0+367*86400)


class SimulationTests(DatabaseCase):
    def test_physical_equilibrium_and_ventilation_recovery(self):
        self.assertEqual(co2_step(430, 0, 100, 2, 60), 430)
        rise = co2_step(430, 10, 100, 2, 3600)
        self.assertGreater(rise, 1000)
        self.assertLess(co2_step(rise, 0, 100, 2, 3600), rise)
        self.assertLess(co2_step(430, 10, 100, 4, 3600), rise)

    def test_repeatability_and_shared_large_room(self):
        a, b = Simulator(self.config), Simulator(self.config)
        for ts in range(T0, T0+180, 60):
            self.assertEqual(a.sample(ts), b.sample(ts))
        readings = a.sample(T0+180)
        values = {(r[0], r[1]): r[4] for r in readings}
        self.assertLess(abs(values['sw-3a', 'co2']-values['sw-3b', 'co2']), 20)
        self.assertAlmostEqual(values['sw-3a', 'temperature']-values['sw-3b', 'temperature'], 1.4, delta=.12)
        self.assertEqual(len(readings), 20)

    def test_demo_seed_is_idempotent_and_production_is_refused(self):
        count = cli.seed(self.con, self.config, 1, T0)
        self.assertGreater(count, 20000)
        self.assertEqual(cli.seed(self.con, self.config, 1, T0), 0)
        self.config["mode"] = "production"
        with self.assertRaises(ValueError):
            cli.seed(self.con, self.config, 1, T0)


class AdapterTests(unittest.TestCase):
    def setUp(self):
        self.sensor = config.load(ROOT / "config/hil.json")["sensors"][0]
        self.now = int(time.time())

    def states(self, timestamp_key="last_reported"):
        return {entity: {"state": "22" if metric == "temperature" else "850", "attributes": {
            "unit_of_measurement": config.METRICS[metric][0]}, timestamp_key: adapters.iso(self.now)}
            for metric, entity in self.sensor["entities"].items()}

    def test_fresh_value_has_ha_timestamp_not_poll_time(self):
        rows, errors = adapters.decode_sensor(self.sensor, self.states(), self.now+5)
        self.assertFalse(errors)
        self.assertTrue(all(row[3] == self.now for row in rows))
        self.assertTrue(all(row[5] == "ha_last_reported" for row in rows))

    def test_unchanged_last_changed_is_not_used_for_freshness(self):
        states = self.states()
        for state in states.values():
            state["last_changed"] = adapters.iso(self.now-86400)
        rows, errors = adapters.decode_sensor(self.sensor, states, self.now)
        self.assertEqual(len(rows), 2)
        self.assertFalse(errors)

    def test_last_updated_fallback_is_marked(self):
        rows, errors = adapters.decode_sensor(self.sensor, self.states("last_updated"), self.now)
        self.assertFalse(errors)
        self.assertTrue(all(r[5] == "ha_last_updated" for r in rows))

    def test_stale_unavailable_bad_units_and_future_are_not_samples(self):
        for update in ({"state": "unavailable"}, {"state": "unknown"}, {"state": "nan"},
                       {"last_reported": adapters.iso(self.now-1000)},
                       {"last_reported": adapters.iso(self.now+1000)},
                       {"attributes": {"unit_of_measurement": "°F"}}):
            states = self.states()
            states[self.sensor["entities"]["temperature"]].update(update)
            rows, errors = adapters.decode_sensor(self.sensor, states, self.now)
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0][1], "co2")
            self.assertEqual(len(errors), 1)

    def test_no_plaintext_token_to_remote_host(self):
        with self.assertRaisesRegex(ValueError, "HTTPS"):
            adapters.ha_states({"home_assistant": {"url": "http://192.0.2.5:8123"}})

    def test_naive_timestamp_rejected(self):
        with self.assertRaises(ValueError):
            adapters.timestamp("2026-01-01T12:00:00")


class ExportTests(DatabaseCase):
    def test_late_invalid_import_rolls_back_prior_chunks(self):
        self.config["sensors"][0]["provider"] = "replay"
        storage.register(self.con, self.config)
        file = Path(self.temp.name) / "late-invalid.csv"
        with file.open("w", newline="") as handle:
            writer = csv.writer(handle)
            writer.writerow(["timestamp", "sensor", "metric", "value"])
            for offset in range(5000):
                writer.writerow([adapters.iso(T0+offset), "ne-1", "co2", 800])
            writer.writerow([adapters.iso(T0+5001), "ne-1", "co2", "nan"])
        with self.assertRaises(ValueError):
            cli.import_csv(self.con, self.config, file)
        self.assertEqual(self.con.execute("SELECT COUNT(*) FROM readings").fetchone()[0], 0)

    def test_daily_backup_retention_leaves_unmarked_backups(self):
        from scripts.daily_backup import daily_backup
        directory = Path(self.temp.name) / "backups"
        directory.mkdir()
        for day in range(1, 10):
            path = directory / f"office-2026-08-{day:02}.sqlite3"
            storage.backup(self.con, path)
            backup = sqlite3.connect(path)
            try:
                with backup:
                    backup.execute("INSERT INTO metadata VALUES ('managed_backup','kebnekaise-daily-v1')")
            finally:
                backup.close()
        unmarked = directory / "office-2026-01-01.sqlite3"
        storage.backup(self.con, unmarked)
        daily_backup(self.path, directory)
        self.assertTrue(unmarked.exists())
        self.assertEqual(len(list(directory.glob("*.sqlite3"))), 8)
        self.assertFalse((directory / "office-2026-08-01.sqlite3").exists())

    def test_csv_roundtrip_keeps_replay_separate(self):
        self.put([self.row()])
        handle = io.StringIO()
        self.assertEqual(cli.export_csv(self.con, handle), 1)
        file = Path(self.temp.name) / "data.csv"
        file.write_text(handle.getvalue())
        self.config["sensors"][0]["provider"] = "replay"
        storage.register(self.con, self.config)
        self.assertEqual(cli.import_csv(self.con, self.config, file), 1)
        self.assertEqual(cli.import_csv(self.con, self.config, file), 0)
        sources = {r[0] for r in self.con.execute("SELECT source FROM readings")}
        self.assertEqual(sources, {"simulation", "replay"})

    def test_bundle_has_checksum_and_real_default_filter(self):
        self.put([self.row()])
        file = Path(self.temp.name) / "bundle.zip"
        self.assertEqual(cli.make_bundle(self.con, self.config, file, "ha"), 0)
        with zipfile.ZipFile(file) as z:
            manifest = json.loads(z.read("manifest.json"))
            import hashlib
            self.assertEqual(manifest["files"]["readings.csv"]["sha256"], hashlib.sha256(z.read("readings.csv")).hexdigest())
            self.assertEqual(manifest["rows"], 0)


class NetworkTests(DatabaseCase):
    def setUp(self):
        super().setUp()
        self.http = server.make_server(self.path, self.config, 0)
        self.thread = threading.Thread(target=self.http.serve_forever)
        self.thread.start()
        self.url = f"http://127.0.0.1:{self.http.server_port}"
        self.client = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    def tearDown(self):
        self.http.shutdown()
        self.http.server_close()
        self.thread.join()
        super().tearDown()

    def request(self, path, headers=None, data=None):
        req = urllib.request.Request(self.url+path, headers=headers or {}, data=data)
        return self.client.open(req, timeout=10)

    def test_interface_is_loopback_and_files_are_allowlisted(self):
        self.assertEqual(self.http.server_address[0], "127.0.0.1")
        with self.assertRaises(ValueError):
            server.LocalServer(("0.0.0.0", 0), server.BaseHTTPRequestHandler)
        for path in ("/../config/demo.json", "/data/demo.sqlite3", "/.env"):
            with self.assertRaises(urllib.error.HTTPError) as error:
                self.request(path)
            self.assertEqual(error.exception.code, 404)
            error.exception.close()

    def test_host_origin_and_cross_site_requests_rejected(self):
        for headers in ({"Host": "evil.example"}, {"Origin": "https://evil.example"}, {"Sec-Fetch-Site": "cross-site"}):
            with self.assertRaises(urllib.error.HTTPError) as error:
                self.request("/api/config", headers)
            self.assertEqual(error.exception.code, 403)
            error.exception.close()

    def test_oversized_event_and_unbounded_query_refused(self):
        with self.request("/api/config") as response:
            token = json.load(response)["csrf"]
        with self.assertRaises(urllib.error.HTTPError) as error:
            self.request("/api/events", {"Content-Type": "application/json", "X-Kebnekaise-Token": token}, b"x"*5000)
        self.assertEqual(error.exception.code, 400)
        error.exception.close()
        with self.assertRaises(urllib.error.HTTPError) as error:
            self.request(f"/api/data?start={T0-400*86400}&end={T0}")
        self.assertEqual(error.exception.code, 400)
        error.exception.close()

    def test_write_requires_csrf_token_and_persists(self):
        body = json.dumps({"sensor": "ne-1", "kind": "warm", "note": "Test: upplevelse"}).encode()
        with self.assertRaises(urllib.error.HTTPError) as error:
            self.request("/api/events", {"Content-Type": "application/json"}, body)
        self.assertEqual(error.exception.code, 403)
        error.exception.close()
        with self.request("/api/config") as response:
            settings = json.load(response)
            self.assertIn("frame-ancestors 'none'", response.headers["Content-Security-Policy"])
            self.assertNotIn("home_assistant", settings)
        with self.request("/api/events", {"Content-Type": "application/json", "X-Kebnekaise-Token": settings["csrf"]}, body) as response:
            self.assertEqual(response.status, 201)
        self.assertEqual(self.con.execute("SELECT note FROM events").fetchone()[0], "Test: upplevelse")

    def test_mock_adapter_roundtrip_then_disconnect_keeps_gap(self):
        self.con.close()
        self.path = Path(self.temp.name)/"pilot.sqlite3"
        self.config = config.load(ROOT / "config/hil.json")
        self.con = storage.connect(self.path)
        storage.register(self.con, self.config)
        with patch.dict(os.environ, {"KEBNEKAISE_HA_TOKEN": "test-only-token"}):
            mock = mock_ha.make_mock(self.config, 0)
            worker = threading.Thread(target=mock.serve_forever)
            worker.start()
            self.config["home_assistant"]["url"] = f"http://127.0.0.1:{mock.server_port}"
            storage.register(self.con, self.config)
            try:
                c = collector.Collector(self.config)
                c.tick(self.con)
                self.assertEqual(self.con.execute("SELECT COUNT(*) FROM readings WHERE source='mock'").fetchone()[0], 2)
                first_count = self.con.execute("SELECT COUNT(*) FROM readings WHERE sensor='ne-1'").fetchone()[0]
            finally:
                mock.shutdown(); mock.server_close(); worker.join()
            c.tick(self.con, int(time.time())+60)
            self.assertEqual(self.con.execute("SELECT COUNT(*) FROM readings WHERE sensor='ne-1'").fetchone()[0], first_count)
            self.assertFalse(self.con.execute("SELECT ok FROM health WHERE sensor='ne-1'").fetchone()[0])
            self.assertEqual(self.con.execute("SELECT COUNT(*) FROM readings WHERE sensor='ne-1' AND source='simulation'").fetchone()[0], 0)


if __name__ == "__main__":
    unittest.main()
