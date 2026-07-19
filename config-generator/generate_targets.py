#!/usr/bin/env python3
"""Ermittelt alle HAProxy-Backends samt ihrer Server über den Stats-CSV-Endpoint
und schreibt sie als Prometheus file_sd-Target-Datei für den
Blackbox-Exporter-Probe-Job heraus.
"""

import csv
import io
import json
import logging
import os
import sys
import tempfile
import time
import urllib.error
import urllib.request

STATS_URL = os.environ.get("HAPROXY_STATS_URL", "http://haproxy:8404/stats;csv")
OUTPUT_FILE = os.environ.get("OUTPUT_FILE", "/output/haproxy_backends.json")
PROBE_SCHEME = os.environ.get("PROBE_SCHEME", "http")
PROBE_PATH = os.environ.get("PROBE_PATH", "/")
RETRY_INTERVAL = float(os.environ.get("RETRY_INTERVAL", "2"))
MAX_RETRIES = int(os.environ.get("MAX_RETRIES", "30"))
LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO").upper()

logging.basicConfig(
    level=LOG_LEVEL,
    format="%(asctime)s %(levelname)-8s %(message)s",
    stream=sys.stderr,
)
logger = logging.getLogger("generate_targets")


def fetch_stats_csv(url: str) -> str:
    request = urllib.request.Request(url, headers={"User-Agent": "haproxy-config-generator"})
    with urllib.request.urlopen(request, timeout=5) as response:
        if response.status != 200:
            raise urllib.error.HTTPError(
                url, response.status, "unerwarteter HTTP-Status", response.headers, None
            )
        body = response.read()
    try:
        return body.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError(f"Antwort konnte nicht als UTF-8 dekodiert werden: {exc}") from exc


def wait_for_stats(url: str) -> str:
    last_error = None
    logger.info(
        "Warte auf HAProxy-Stats-Endpoint %s (max. %d Versuch(e), Intervall %ss)",
        url, MAX_RETRIES, RETRY_INTERVAL,
    )
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            csv_text = fetch_stats_csv(url)
            logger.info(
                "HAProxy-Stats-Endpoint erreichbar (Versuch %d/%d, %d Bytes empfangen)",
                attempt, MAX_RETRIES, len(csv_text),
            )
            return csv_text
        except (urllib.error.URLError, TimeoutError, ValueError, OSError) as exc:
            last_error = exc
            logger.warning(
                "[%d/%d] HAProxy-Stats-Endpoint noch nicht bereit (%s)",
                attempt, MAX_RETRIES, exc,
            )
            if attempt < MAX_RETRIES:
                time.sleep(RETRY_INTERVAL)
    logger.error("HAProxy-Stats-Endpoint wurde nie erreichbar: %s", last_error)
    raise SystemExit(1)


def parse_backend_servers(csv_text: str) -> list:
    """Liefert (backend_name, server_name, addr) für jede Server-Zeile
    (svname nicht FRONTEND/BACKEND) der Stats-CSV, also für jeden Server
    jedes Backends.
    """
    if not csv_text.strip():
        logger.error("Stats-CSV-Antwort ist leer")
        return []

    header_line, sep, rest = csv_text.partition("\n")
    if not sep:
        logger.error("Stats-CSV enthält keinen Zeilenumbruch nach dem Header")
        return []

    header_line = header_line.lstrip("# ").strip()
    if not header_line:
        logger.error("Stats-CSV enthält keine Header-Zeile")
        return []

    reader = csv.DictReader(io.StringIO(header_line + "\n" + rest))
    if not reader.fieldnames or "pxname" not in reader.fieldnames or "svname" not in reader.fieldnames:
        logger.error(
            "Stats-CSV-Header enthält nicht die erwarteten Spalten pxname/svname: %s",
            reader.fieldnames,
        )
        return []

    servers = []
    row_count = 0
    skipped_no_addr = 0
    for row in reader:
        row_count += 1
        pxname = row.get("pxname")
        svname = row.get("svname")
        addr = (row.get("addr") or "").strip()
        if not pxname or pxname == "stats" or svname in (None, "", "FRONTEND", "BACKEND"):
            continue
        if not addr:
            skipped_no_addr += 1
            logger.debug("Server ohne addr übersprungen: pxname=%s svname=%s", pxname, svname)
            continue
        servers.append((pxname, svname, addr))

    logger.info(
        "%d CSV-Zeile(n) verarbeitet, %d Server-Adresse(n) gefunden, %d ohne addr übersprungen",
        row_count, len(servers), skipped_no_addr,
    )
    return servers


def build_target_groups(servers: list) -> list:
    groups = []
    for backend_name, server_name, addr in sorted(servers):
        if ":" not in addr:
            logger.warning(
                "Adresse ohne Port für Backend=%s Server=%s: %r (wird trotzdem verwendet)",
                backend_name, server_name, addr,
            )
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


def write_target_groups(target_groups: list, output_file: str) -> None:
    """Schreibt die Zieldatei atomar (tmp-Datei + rename), damit Prometheus/
    Blackbox-Exporter niemals eine unvollständige Datei einliest."""
    output_dir = os.path.dirname(output_file) or "."
    os.makedirs(output_dir, exist_ok=True)

    fd, tmp_path = tempfile.mkstemp(dir=output_dir, prefix=".haproxy_backends_", suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(target_groups, f, indent=2)
            f.write("\n")
        os.replace(tmp_path, output_file)
    except BaseException:
        os.unlink(tmp_path)
        raise


def main() -> None:
    logger.info(
        "Starte Target-Generierung (stats_url=%s output=%s probe=%s://...%s)",
        STATS_URL, OUTPUT_FILE, PROBE_SCHEME, PROBE_PATH,
    )

    csv_text = wait_for_stats(STATS_URL)
    servers = parse_backend_servers(csv_text)
    if not servers:
        logger.error("Keine HAProxy-Backends über den Stats-Endpoint gefunden")
        raise SystemExit(1)

    target_groups = build_target_groups(servers)

    try:
        write_target_groups(target_groups, OUTPUT_FILE)
    except OSError as exc:
        logger.error("Schreiben von %s fehlgeschlagen: %s", OUTPUT_FILE, exc)
        raise SystemExit(1) from exc

    logger.info("%d Server-Target(s) nach %s geschrieben", len(target_groups), OUTPUT_FILE)


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except Exception:
        logger.exception("Unerwarteter Fehler bei der Target-Generierung")
        sys.exit(1)
