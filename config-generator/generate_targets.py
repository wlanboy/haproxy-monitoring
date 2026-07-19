#!/usr/bin/env python3
"""Discover HAProxy backends via the stats CSV endpoint and write them out
as a Prometheus file_sd target file for the blackbox-exporter probe job.
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
                f"[{attempt}/{MAX_RETRIES}] HAProxy stats endpoint not ready "
                f"({exc}), retrying in {RETRY_INTERVAL}s",
                file=sys.stderr,
            )
            time.sleep(RETRY_INTERVAL)
    raise SystemExit(f"HAProxy stats endpoint never became available: {last_error}")


def parse_backend_addrs(csv_text: str) -> dict:
    """Map backend name -> address of its first server, read from the
    individual server rows (svname not FRONTEND/BACKEND) of the stats CSV.
    """
    header_line, _, rest = csv_text.partition("\n")
    header_line = header_line.lstrip("# ").strip()
    reader = csv.DictReader(io.StringIO(header_line + "\n" + rest))

    backend_addrs = {}
    for row in reader:
        pxname = row.get("pxname")
        svname = row.get("svname")
        addr = (row.get("addr") or "").strip()
        if not pxname or pxname == "stats" or svname in (None, "", "FRONTEND", "BACKEND"):
            continue
        if addr:
            backend_addrs.setdefault(pxname, addr)
    return backend_addrs


def build_target_groups(backend_addrs: dict) -> list:
    groups = []
    for backend_name, addr in sorted(backend_addrs.items()):
        service = backend_name.removesuffix("_backend")
        target_url = f"{PROBE_SCHEME}://{addr}{PROBE_PATH}"
        groups.append(
            {
                "targets": [target_url],
                "labels": {"service": service, "haproxy_backend": backend_name},
            }
        )
    return groups


def main() -> None:
    csv_text = wait_for_stats(STATS_URL)
    backend_addrs = parse_backend_addrs(csv_text)
    if not backend_addrs:
        raise SystemExit("No HAProxy backends discovered via stats endpoint")

    target_groups = build_target_groups(backend_addrs)

    os.makedirs(os.path.dirname(OUTPUT_FILE), exist_ok=True)
    with open(OUTPUT_FILE, "w") as f:
        json.dump(target_groups, f, indent=2)
        f.write("\n")

    print(f"Wrote {len(target_groups)} backend target(s) to {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
