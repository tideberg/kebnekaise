"""Create one verified backup a day; rotate only explicitly managed snapshots."""

import re
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from kebnekaise import storage


def daily_backup(db, directory, keep=7, prefix="office"):
    if not re.fullmatch(r"[a-z][a-z0-9-]{0,47}", prefix):
        raise ValueError("Ogiltigt backupprefix")
    if not Path(db).is_file():
        raise ValueError("Källdatabasen saknas")
    target = Path(directory) / (prefix + "-" + datetime.now(timezone.utc).strftime("%Y-%m-%d") + ".sqlite3")
    if target.exists():
        return
    con = storage.read_connection(db)
    try:
        storage.backup(con, target)
        snapshot = sqlite3.connect(target)
        try:
            with snapshot:
                snapshot.execute("INSERT OR REPLACE INTO metadata VALUES ('managed_backup','kebnekaise-daily-v1')")
        finally:
            snapshot.close()
        print(f"Verifierad backup: {target}")
    finally:
        con.close()
    # Retention applies only to verified snapshots created by this script.
    # Raw data and unmarked backups are never deleted.
    managed = []
    for candidate in sorted(Path(directory).glob(prefix + "-*.sqlite3")):
        if not re.fullmatch(re.escape(prefix) + r"-\d{4}-\d{2}-\d{2}\.sqlite3", candidate.name) or candidate.is_symlink():
            continue
        check = storage.read_connection(candidate)
        try:
            mark = check.execute("SELECT value FROM metadata WHERE key='managed_backup'").fetchone()
            if mark and mark[0] == 'kebnekaise-daily-v1':
                managed.append(candidate)
        except sqlite3.Error:
            continue
        finally:
            check.close()
    for candidate in managed[:-keep]:
        candidate.unlink()
        print(f"Roterad äldre dagsbackup: {candidate.name}")


if __name__ == "__main__":
    if len(sys.argv) not in {3, 4}:
        raise SystemExit("Användning: python3 scripts/daily_backup.py DATABASE DIRECTORY [PREFIX]")
    daily_backup(sys.argv[1], sys.argv[2], prefix=sys.argv[3] if len(sys.argv) == 4 else "office")
