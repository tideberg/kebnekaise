"""Read only HA states. No third-party clients, redirects, or proxy inheritance."""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone

from .config import METRICS


def timestamp(text):
    if not isinstance(text, str):
        raise ValueError("Tidsstämpel saknas")
    parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("Tidsstämpeln måste ha tidszon")
    return int(parsed.timestamp())


def iso(ts):
    return datetime.fromtimestamp(ts, timezone.utc).isoformat().replace("+00:00", "Z")


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ValueError("HA-omdirigering avvisad; kontrollera den exakta API-adressen")


def ha_states(config):
    settings = config.get("home_assistant", {})
    url = settings.get("url", "http://127.0.0.1:8123").rstrip("/")
    parsed = urllib.parse.urlsplit(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError("Ogiltig HA-adress")
    # Plaintext tokens may only cross loopback. Remote HA requires verified HTTPS
    # or an SSH tunnel whose local end is loopback. Never disable TLS validation.
    supervisor = (url == "http://supervisor/core" and settings.get("supervisor_api") is True
                  and settings.get("token_env") == "SUPERVISOR_TOKEN")
    if parsed.scheme == "http" and parsed.hostname not in {"127.0.0.1", "localhost", "::1"} and not supervisor:
        raise ValueError("HA över nätverket kräver HTTPS; använd annars en lokal SSH-tunnel")
    token_var = settings.get("token_env", "KEBNEKAISE_HA_TOKEN")
    token = os.environ.get(token_var, "")
    if not token or "\n" in token or "\r" in token:
        raise ValueError(f"Giltig token saknas i miljövariabeln {token_var}")
    request = urllib.request.Request(url + "/api/states", headers={
        "Authorization": f"Bearer {token}", "Accept": "application/json"})
    client = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
    try:
        with client.open(request, timeout=8) as response:
            body = response.read(2_000_001)
    except urllib.error.HTTPError as exc:
        raise ValueError(f"HA svarade HTTP {exc.code}; kontrollera åtkomst och konfiguration") from None
    except (urllib.error.URLError, TimeoutError, OSError):
        raise ValueError("HA kan inte nås; inga mätvärden ersätts med simulering") from None
    if len(body) > 2_000_000:
        raise ValueError("HA-svaret är för stort")
    states = json.loads(body)
    if not isinstance(states, list) or any(not isinstance(s, dict) for s in states):
        raise ValueError("HA returnerade inte en lista med tillstånd")
    return {s["entity_id"]: s for s in states if "entity_id" in s}


def decode_sensor(sensor, states, now=None, max_age=600):
    now = int(time.time()) if now is None else now
    rows, errors = [], []
    for metric, entity in sensor["entities"].items():
        try:
            state = states.get(entity, {})
            if state.get("state") in {None, "unavailable", "unknown", ""}:
                raise ValueError("saknas eller unavailable")
            unit = state.get("attributes", {}).get("unit_of_measurement")
            if unit != METRICS[metric][0]:
                raise ValueError("fel eller saknad enhet")
            value = float(state["state"])
            key = "last_reported" if state.get("last_reported") else "last_updated"
            ts = timestamp(state.get(key))
            if now - ts > max_age:
                raise ValueError("för gammalt rapporterat värde")
            if ts > now + 120:
                raise ValueError("framtida tidsstämpel")
            _, low, high = METRICS[metric]
            if not low <= value <= high:
                raise ValueError("orimligt värde")
            rows.append((sensor["id"], metric, sensor["provider"], ts, value, "ha_" + key))
        except (TypeError, ValueError, KeyError):
            # Don't log state bodies: they can contain arbitrary data and secrets.
            errors.append(f"{metric}: saknas, gammalt eller ogiltigt; kontrollera entity, enhet och klocka")
    return rows, errors
