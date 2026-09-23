"""Open the real dashboard through its loopback-only SSH tunnel."""

import argparse
import json
import os
import socket
from pathlib import Path
import subprocess
import sys
import time
import threading

if __package__:
    from .view_proxy import make_proxy
else:
    from view_proxy import make_proxy
import urllib.error
import urllib.request
import webbrowser

ROOT = Path(__file__).resolve().parents[1]
URL = "http://127.0.0.1:8840"


def tunnel_listening(port=8840):
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=2):
            return True
    except OSError:
        return False


def dashboard_ready(url=URL):
    client = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with client.open(url + "/api/config", timeout=2) as response:
            config = json.load(response)
    except (urllib.error.URLError, OSError):
        return False
    providers = {sensor.get("provider") for sensor in config.get("sensors", [])}
    if (config.get("mode") not in {"pilot", "production"}
            or not providers & {"ha", "matter"}
            or providers - {"ha", "matter", "disabled"}):
        raise ValueError("Dashboarden visar inte enbart riktiga datakällor. Stäng den lokala dashboarden och försök igen.")
    return True


def connection_settings(args, with_options=False):
    settings_path = ROOT / "config/local-view.json"
    settings = json.loads(settings_path.read_text()) if settings_path.exists() else {}
    profile = settings.get(args.target, {})
    env_name = "KEBNEKAISE_MINI01_HOST" if args.target == "mini01" else "KEBNEKAISE_PI_HOST"
    host = (args.host or os.environ.get(env_name) or profile.get("host")
            or (settings.get("host") if args.target == "rpi" else None))
    if not isinstance(host, str) or not host or host.startswith("-") or any(c.isspace() for c in host):
        raise ValueError(f"Ange SSH-mål: just view-{args.target} användare@värd (eller {env_name}).")
    options = []
    # Only apply the saved address when using that profile's SSH identity.
    if profile.get("hostname") and host == profile.get("host"):
        hostname = profile["hostname"]
        if (not isinstance(hostname, str) or hostname.startswith("-")
                or any(c.isspace() for c in hostname)):
            raise ValueError("Ogiltigt hostname i config/local-view.json.")
        options = ["-o", f"Hostname={hostname}", "-o", f"HostKeyAlias={host.rsplit('@', 1)[-1]}"]
    return (host, options) if with_options else host


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("host", nargs="?")
    parser.add_argument("--target", choices=("rpi", "mini01"), default="rpi")
    parser.add_argument("--local-port", type=int)
    parser.add_argument("--remote-port", type=int, default=8840)
    args = parser.parse_args()
    tunnel = None
    proxy = None
    try:
        host, ssh_options = connection_settings(args, with_options=True)
        port = args.local_port if args.local_port is not None else (8841 if args.target == "mini01" else 8840)
        if not 1 <= port <= 65535 or not 1 <= args.remote_port <= 65535:
            raise ValueError("Porten måste vara mellan 1 och 65535.")
        url = f"http://127.0.0.1:{port}"
        if tunnel_listening(port):
            raise ValueError(f"Port {port} används redan. Stäng tunneln/dashboarden eller välj en annan lokal port.")
        ssh = ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=10",
               "-o", "StrictHostKeyChecking=yes"] + ssh_options
        service_command = ("systemctl --user start kebnekaise-dashboard.service"
                           if args.target == "mini01"
                           else "sudo -n systemctl start kebnekaise-dashboard.service")
        subprocess.run(ssh + [host, service_command], check=True)
        tunnel_port = port
        if port != args.remote_port:
            with socket.socket() as reservation:
                reservation.bind(("127.0.0.1", 0))
                tunnel_port = reservation.getsockname()[1]
            proxy = make_proxy(port, tunnel_port, args.remote_port)
            threading.Thread(target=proxy.serve_forever, daemon=True).start()
        tunnel = subprocess.Popen(ssh + ["-N", "-o", "ExitOnForwardFailure=yes",
                "-o", "ServerAliveInterval=30", "-o", "ServerAliveCountMax=3",
                "-L", f"127.0.0.1:{tunnel_port}:127.0.0.1:{args.remote_port}", host])
        deadline = time.monotonic() + 15
        while not dashboard_ready(url):
            if tunnel and tunnel.poll() is not None:
                raise ValueError("SSH-tunneln kunde inte starta. Kontrollera anslutningen och att den lokala porten är ledig.")
            if time.monotonic() >= deadline:
                raise ValueError("Värdens dashboard svarar inte. Kontrollera kebnekaise-dashboard.service på värden.")
            time.sleep(.2)
        if tunnel and tunnel.poll() is not None:
            raise ValueError("SSH-tunneln avslutades oväntat.")
        print(f"Kebnekaise · riktiga data · {host} · {url}", flush=True)
        try:
            opened = webbrowser.open(url, new=2)
        except (OSError, webbrowser.Error):
            opened = False
        if not opened:
            print(f"Öppna {url} i webbläsaren.")
        if tunnel:
            print("Ctrl-C stänger denna tunnel. Insamlingen på värden fortsätter.", flush=True)
            if tunnel.wait() != 0:
                raise ValueError("SSH-tunneln bröts. Kör just view-live igen.")
        return 0
    except KeyboardInterrupt:
        return 0
    except (OSError, ValueError, KeyError, subprocess.CalledProcessError) as exc:
        print(f"Fel: {exc}", file=sys.stderr)
        return 1
    finally:
        if proxy:
            proxy.shutdown()
            proxy.server_close()
        if tunnel and tunnel.poll() is None:
            tunnel.terminate()
            try:
                tunnel.wait(timeout=5)
            except subprocess.TimeoutExpired:
                tunnel.kill()
                tunnel.wait()


if __name__ == "__main__":
    sys.exit(main())
