#!/usr/bin/env python3
"""Zeigt die HAProxy-Stats aller Proxies, deren Name auf ein Regex passt, fuer
jede HAProxy-Instanz aus einer Liste (Standard: haproxy.txt).

Nur Standardbibliothek, keine Dependencies.

Beispiele:
    ./stats.py oauth                 # matcht z.B. backend_oauth_xyz, oauth_backend
    ./stats.py '^api_' -f prod.txt
    ./stats.py 'auth|session' --no-servers

haproxy.txt: eine Instanz pro Zeile, '#' leitet Kommentare ein. Erlaubt sind
    lb1.example.com                      -> http://lb1.example.com:8404/stats;csv
    lb2.example.com:9000                 -> http://lb2.example.com:9000/stats;csv
    https://lb3.example.com/haproxy?stats -> ;csv wird bei Bedarf angehaengt

.env: HAPROXY_STATS_USER und HAPROXY_STATS_PASSWORD (gleiche Namen wie beim
config-generator). Bereits gesetzte Umgebungsvariablen haben Vorrang.
"""

import argparse
import base64
import csv
import io
import os
import re
import ssl
import sys
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DEFAULT_PORT = 8404
DEFAULT_PATH = "/stats"

# (CSV-Spalte, Ueberschrift)
COLUMNS = [
    ("pxname", "PROXY"),
    ("svname", "SERVER"),
    ("status", "STATUS"),
    ("check_status", "CHECK"),
    ("scur", "CUR"),
    ("smax", "MAX"),
    ("slim", "LIMIT"),
    ("stot", "TOTAL"),
    ("rate", "RATE/s"),
    ("qcur", "QUEUE"),
    ("bin", "IN"),
    ("bout", "OUT"),
    ("hrsp_4xx", "4XX"),
    ("hrsp_5xx", "5XX"),
    ("econ", "ECON"),
    ("eresp", "ERESP"),
    ("rtime", "RTIME"),
    ("lastchg", "LASTCHG"),
]


def find_file(name: str) -> str:
    """Sucht relative Pfade erst im aktuellen Verzeichnis, dann neben dem Script."""
    if os.path.isabs(name) or os.path.exists(name):
        return name
    candidate = os.path.join(SCRIPT_DIR, name)
    return candidate if os.path.exists(candidate) else name


def load_env(path: str) -> None:
    try:
        with open(path, encoding="utf-8") as f:
            lines = f.readlines()
    except FileNotFoundError:
        return
    for line in lines:
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip().removeprefix("export ").strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        os.environ.setdefault(key, value)


def load_targets(path: str) -> list:
    targets = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.split("#", 1)[0].strip()
            if line:
                targets.append(line)
    return targets


def to_stats_url(entry: str) -> str:
    if "://" not in entry:
        host, _, path = entry.partition("/")
        if ":" not in host:
            host = f"{host}:{DEFAULT_PORT}"
        entry = f"http://{host}/{path}" if path else f"http://{host}{DEFAULT_PATH}"
    if not entry.endswith(";csv"):
        entry += ";csv"
    return entry


def fetch_csv(url: str, user: str, password: str, timeout: float, insecure: bool) -> str:
    request = urllib.request.Request(url, headers={"User-Agent": "haproxy-stats-cli"})
    if user:
        credentials = base64.b64encode(f"{user}:{password}".encode("utf-8")).decode("ascii")
        request.add_header("Authorization", f"Basic {credentials}")
    context = ssl._create_unverified_context() if insecure else None
    with urllib.request.urlopen(request, timeout=timeout, context=context) as response:
        return response.read().decode("utf-8", errors="replace")


def parse_csv(csv_text: str) -> list:
    header, _, rest = csv_text.partition("\n")
    header = header.lstrip("# ").strip()
    return list(csv.DictReader(io.StringIO(header + "\n" + rest)))


def human_bytes(value: str) -> str:
    try:
        n = float(value)
    except ValueError:
        return value
    for unit in ("B", "K", "M", "G", "T"):
        if n < 1024 or unit == "T":
            return f"{n:.0f}{unit}" if unit == "B" else f"{n:.1f}{unit}"
        n /= 1024
    return value


def human_duration(value: str) -> str:
    try:
        seconds = int(value)
    except ValueError:
        return value
    days, seconds = divmod(seconds, 86400)
    hours, seconds = divmod(seconds, 3600)
    minutes, seconds = divmod(seconds, 60)
    if days:
        return f"{days}d{hours}h"
    if hours:
        return f"{hours}h{minutes}m"
    if minutes:
        return f"{minutes}m{seconds}s"
    return f"{seconds}s"


def format_row(row: dict) -> list:
    cells = []
    for key, _ in COLUMNS:
        value = row.get(key) or ""
        if key in ("bin", "bout") and value:
            value = human_bytes(value)
        elif key == "lastchg" and value:
            value = human_duration(value)
        elif key == "rtime" and value:
            value = f"{value}ms"
        cells.append(value)
    return cells


def status_color(status: str) -> str:
    if status.startswith("UP") or status == "OPEN":
        return "\033[32m"
    if status.startswith("DOWN") or status in ("MAINT", "NOLB"):
        return "\033[31m"
    if status:
        return "\033[33m"
    return ""


def print_table(rows: list, use_color: bool) -> None:
    headers = [title for _, title in COLUMNS]
    table = [format_row(r) for r in rows]
    widths = [max(len(h), *(len(r[i]) for r in table)) for i, h in enumerate(headers)]
    status_idx = headers.index("STATUS")

    print("  ".join(h.ljust(widths[i]) for i, h in enumerate(headers)))
    for raw, cells in zip(rows, table):
        is_summary = raw.get("svname") in ("FRONTEND", "BACKEND")
        parts = []
        for i, cell in enumerate(cells):
            text = cell.ljust(widths[i])
            if use_color and i == status_idx:
                color = status_color(cell)
                if color:
                    text = f"{color}{text}\033[0m"
            parts.append(text)
        line = "  ".join(parts).rstrip()
        if use_color and is_summary:
            line = f"\033[1m{line}\033[0m"
        print(line)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="HAProxy-Stats fuer Proxies anzeigen, deren Name auf ein Regex passt."
    )
    parser.add_argument("pattern", help="Regex auf den Proxy-Namen (pxname), case-insensitive, z.B. 'oauth'")
    parser.add_argument("-f", "--file", default="haproxy.txt", help="Liste der HAProxy-Instanzen (Default: haproxy.txt)")
    parser.add_argument("-e", "--env", default=".env", help="Env-Datei mit User/Passwort (Default: .env)")
    parser.add_argument("-s", "--server", action="store_true", help="Regex zusaetzlich auf den Servernamen (svname) anwenden")
    parser.add_argument("--no-servers", action="store_true", help="nur FRONTEND/BACKEND-Summen, keine einzelnen Server")
    parser.add_argument("--no-frontends", action="store_true", help="FRONTEND-Zeilen ausblenden")
    parser.add_argument("-t", "--timeout", type=float, default=5.0, help="HTTP-Timeout in Sekunden (Default: 5)")
    parser.add_argument("-k", "--insecure", action="store_true", help="TLS-Zertifikate nicht pruefen")
    parser.add_argument("--no-color", action="store_true", help="keine ANSI-Farben")
    args = parser.parse_args()

    try:
        regex = re.compile(args.pattern, re.IGNORECASE)
    except re.error as exc:
        print(f"Ungueltiges Regex {args.pattern!r}: {exc}", file=sys.stderr)
        return 2

    load_env(find_file(args.env))
    user = os.environ.get("HAPROXY_STATS_USER", "")
    password = os.environ.get("HAPROXY_STATS_PASSWORD", "")

    list_file = find_file(args.file)
    try:
        targets = load_targets(list_file)
    except OSError as exc:
        print(f"Kann {list_file} nicht lesen: {exc}", file=sys.stderr)
        return 2
    if not targets:
        print(f"{list_file} enthaelt keine HAProxy-Instanzen", file=sys.stderr)
        return 2

    use_color = not args.no_color and sys.stdout.isatty() and not os.environ.get("NO_COLOR")

    def fetch(entry: str):
        url = to_stats_url(entry)
        try:
            return entry, url, parse_csv(fetch_csv(url, user, password, args.timeout, args.insecure)), None
        except urllib.error.HTTPError as exc:
            hint = " (HAPROXY_STATS_USER/HAPROXY_STATS_PASSWORD pruefen)" if exc.code in (401, 403) else ""
            return entry, url, None, f"HTTP {exc.code} {exc.reason}{hint}"
        except (urllib.error.URLError, OSError, ValueError) as exc:
            return entry, url, None, str(getattr(exc, "reason", exc))

    with ThreadPoolExecutor(max_workers=min(16, len(targets))) as pool:
        results = list(pool.map(fetch, targets))

    exit_code = 0
    total_matches = 0
    for index, (entry, url, rows, error) in enumerate(results):
        if index:
            print()
        title = f"== {entry} ({url})"
        print(f"\033[1;36m{title}\033[0m" if use_color else title)
        if error:
            print(f"   FEHLER: {error}")
            exit_code = 1
            continue

        matched = []
        for row in rows:
            svname = row.get("svname", "")
            is_summary = svname in ("FRONTEND", "BACKEND")
            if args.no_servers and not is_summary:
                continue
            if args.no_frontends and svname == "FRONTEND":
                continue
            if regex.search(row.get("pxname", "")) or (args.server and not is_summary and regex.search(svname)):
                matched.append(row)

        if not matched:
            print(f"   keine Proxies passend zu /{args.pattern}/")
            continue
        total_matches += len(matched)
        print_table(matched, use_color)

    if total_matches == 0 and exit_code == 0:
        exit_code = 1
    return exit_code


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit(130)
