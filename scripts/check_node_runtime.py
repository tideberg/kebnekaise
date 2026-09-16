#!/usr/bin/env python3
"""Fail when the pinned Node.js major has a newer stable patch release."""

import json
import re
import sys
import urllib.request
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
INDEX_URL = "https://nodejs.org/dist/index.json"
MAX_INDEX_BYTES = 2_000_000


def version_tuple(value):
    match = re.fullmatch(r"v?(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)", value)
    if not match:
        raise ValueError(f"Ogiltig exakt Node-version: {value!r}")
    return tuple(map(int, match.groups()))


def latest_same_major(releases, configured):
    current = version_tuple(configured)
    candidates = []
    for release in releases:
        try:
            candidate = version_tuple(release["version"])
        except (KeyError, TypeError, ValueError):
            continue
        if candidate[0] == current[0]:
            candidates.append(candidate)
    if not candidates:
        raise ValueError(f"Inga Node {current[0]}-versioner i versionsindex")
    return max(candidates)


def fetch_releases():
    request = urllib.request.Request(INDEX_URL, headers={"User-Agent": "kebnekaise-runtime-check/1"})
    with urllib.request.urlopen(request, timeout=20) as response:
        payload = response.read(MAX_INDEX_BYTES + 1)
    if len(payload) > MAX_INDEX_BYTES:
        raise ValueError("Node-versionindex är oväntat stort")
    return json.loads(payload)


def main():
    package = json.loads((ROOT / "deploy/matter/package.json").read_text())
    configured_text = package["engines"]["node"]
    configured = version_tuple(configured_text)
    latest = latest_same_major(fetch_releases(), configured_text)
    if configured < latest:
        print(f"Node {configured_text} är föråldrad; senaste version i samma serie är {'.'.join(map(str, latest))}.")
        return 1
    if configured > latest:
        print("Den pinnade Node-versionen saknas i det officiella versionsindexet.")
        return 1
    print(f"Node {configured_text} är senaste version i sin huvudserie.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError, KeyError, json.JSONDecodeError) as error:
        print(f"Kunde inte verifiera Node-versionen: {error}", file=sys.stderr)
        raise SystemExit(2)
