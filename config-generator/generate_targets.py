#!/usr/bin/env python3
"""Ermittelt alle HAProxy-Backends samt ihrer Server über den Stats-CSV-Endpoint
und schreibt sie als Prometheus file_sd-Target-Datei für den
Blackbox-Exporter-Probe-Job heraus.
"""

import csv
import io
import json
import os
import sys
import time
import urllib.error
import urllib.request

STATS_URL = os.environ.get("HAPROXY_STATS_URL", "http://haproxy:8404/stats;csv")
OUTPUT_FILE = os.environ.get("OUTPUT_FILE", "/output/haproxy_backends.json")
PROBE_SCHEME = os.environ.get("PROBE_SCHEME", "http")
PROBE_PATH = os.environ.get("PROBE_PATH", "/")
RETRY_INTERVAL = float(os.environ.get("RETRY_INTERVAL", "2"))
MAX_RETRIES = int(os.environ.get("MAX_RETRIES", "30"))


def fetch_stats_csv(url: str) -> str:
    with urllib.request.urlopen(url, timeout=5) as response:
        return response.read().decode("utf-8")


def wait_for_stats(url: str) -> str:
    last_error = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            return fetch_stats_csv(url)
        except (urllib.error.URLError, TimeoutError) as exc:
            last_error = exc
            print(
                f"[{attempt}/{MAX_RETRIES}] HAProxy-Stats-Endpoint noch nicht bereit "
                f"({exc}), erneuter Versuch in {RETRY_INTERVAL}s",
                file=sys.stderr,
            )
            time.sleep(RETRY_INTERVAL)
    raise SystemExit(f"HAProxy-Stats-Endpoint wurde nie erreichbar: {last_error}")


def parse_backend_servers(csv_text: str) -> list:
    """Liefert (backend_name, server_name, addr) für jede Server-Zeile
    (svname nicht FRONTEND/BACKEND) der Stats-CSV, also für jeden Server
    jedes Backends.
    """
    header_line, _, rest = csv_text.partition("\n")
    header_line = header_line.lstrip("# ").strip()
    reader = csv.DictReader(io.StringIO(header_line + "\n" + rest))

    servers = []
    for row in reader:
        pxname = row.get("pxname")
        svname = row.get("svname")
        addr = (row.get("addr") or "").strip()
        if not pxname or pxname == "stats" or svname in (None, "", "FRONTEND", "BACKEND"):
            continue
        if addr:
            servers.append((pxname, svname, addr))
    return servers


def build_target_groups(servers: list) -> list:
    groups = []
    for backend_name, server_name, addr in sorted(servers):
        service = backend_name.removesuffix("_backend")
        target_url = f"{PROBE_SCHEME}://{addr}{PROBE_PATH}"
        groups.append(
            {
                "targets": [target_url],
                "labels": {
                    "service": service,
                    "haproxy_backend": backend_name,
                    "haproxy_server": server_name,
                },
            }
        )
    return groups


def main() -> None:
    csv_text = wait_for_stats(STATS_URL)
    servers = parse_backend_servers(csv_text)
    if not servers:
        raise SystemExit("Keine HAProxy-Backends über den Stats-Endpoint gefunden")

    target_groups = build_target_groups(servers)

    os.makedirs(os.path.dirname(OUTPUT_FILE), exist_ok=True)
    with open(OUTPUT_FILE, "w") as f:
        json.dump(target_groups, f, indent=2)
        f.write("\n")

    print(f"{len(target_groups)} Server-Target(s) nach {OUTPUT_FILE} geschrieben")


if __name__ == "__main__":
    main()
