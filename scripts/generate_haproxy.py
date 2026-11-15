# /// script
# requires-python = ">=3.12"
# dependencies = ["pyyaml>=6"]
# ///
"""Erzeugt haproxy/backends.cfg und haproxy/hosts.map aus haproxy/backends.yml.

Aufruf:
    uv run scripts/generate_haproxy.py           # Dateien schreiben
    uv run scripts/generate_haproxy.py --check   # nur prüfen, Exit 1 bei Abweichung
"""

import argparse
import re
import sys
from pathlib import Path

import yaml

HAPROXY_DIR = Path(__file__).resolve().parent.parent / "haproxy"
SOURCE = HAPROXY_DIR / "backends.yml"
BACKENDS_CFG = HAPROXY_DIR / "backends.cfg"
HOSTS_MAP = HAPROXY_DIR / "hosts.map"

HEADER = "# Erzeugt von scripts/generate_haproxy.py aus haproxy/backends.yml.\n# Nicht von Hand ändern.\n"

NAME_RE = re.compile(r"^[a-z0-9][a-z0-9_-]*$")
HOST_RE = re.compile(r"^[a-z0-9.-]+$")
SERVER_RE = re.compile(r"^[A-Za-z0-9._-]+:\d{1,5}$")


class ConfigError(Exception):
    pass


def load(path: Path) -> dict:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or not isinstance(data.get("backends"), list):
        raise ConfigError(f"{path}: Schlüssel 'backends' mit einer Liste fehlt")
    return data


def validate(data: dict) -> list[dict]:
    domain = data.get("domain", "localhost")
    seen_names: set[str] = set()
    seen_hosts: dict[str, str] = {}
    backends = []

    for i, entry in enumerate(data["backends"], start=1):
        where = f"Backend #{i}"
        if not isinstance(entry, dict):
            raise ConfigError(f"{where}: Eintrag ist kein Mapping")

        name = entry.get("name")
        if not isinstance(name, str) or not NAME_RE.match(name):
            raise ConfigError(f"{where}: 'name' fehlt oder enthält ungültige Zeichen: {name!r}")
        where = f"Backend {name!r}"
        if name in seen_names:
            raise ConfigError(f"{where}: Name doppelt")
        seen_names.add(name)

        servers = entry.get("servers")
        if not isinstance(servers, list) or not servers:
            raise ConfigError(f"{where}: 'servers' muss eine nicht leere Liste sein")
        for server in servers:
            if not isinstance(server, str) or not SERVER_RE.match(server):
                raise ConfigError(f"{where}: Server {server!r} ist nicht im Format host:port")

        hosts = entry.get("hosts", [f"{name}.{domain}"])
        if not isinstance(hosts, list) or not all(isinstance(h, str) for h in hosts):
            raise ConfigError(f"{where}: 'hosts' muss eine Liste von Strings sein")
        hosts = [h.lower() for h in hosts]
        for host in hosts:
            if not HOST_RE.match(host):
                raise ConfigError(f"{where}: Host {host!r} enthält ungültige Zeichen")
            if host in seen_hosts:
                raise ConfigError(f"{where}: Host {host!r} ist schon {seen_hosts[host]!r} zugeordnet")
            seen_hosts[host] = name

        description = entry.get("description")
        if description is not None and ('"' in str(description) or "\n" in str(description)):
            raise ConfigError(f"{where}: 'description' darf keine Anführungszeichen oder Umbrüche enthalten")

        health_uri = entry.get("health_uri")
        if health_uri is not None and (
            not isinstance(health_uri, str) or not health_uri.startswith("/") or " " in health_uri
        ):
            raise ConfigError(f"{where}: 'health_uri' muss ein Pfad ohne Leerzeichen sein, z. B. /health")

        backends.append(
            {
                "name": name,
                "description": description,
                "servers": servers,
                "hosts": hosts,
                "health_uri": health_uri,
            }
        )
    return backends


def server_name(backend: str, index: int) -> str:
    sep = "-" if backend[-1].isdigit() else ""
    return f"{backend}{sep}{index}"


def render_backends(backends: list[dict]) -> str:
    blocks = []
    for b in backends:
        lines = [f"backend {b['name']}_backend"]
        if b["description"]:
            lines.append(f'    description "{b["description"]}"')
        if b["health_uri"]:
            # Eigene http-check-Regeln ersetzen die aus defaults komplett,
            # deshalb auch expect wiederholen.
            lines.append(f"    http-check send meth GET uri {b['health_uri']}")
            lines.append("    http-check expect rstatus 2[0-9][0-9]|3[0-9][0-9]")
        for i, server in enumerate(b["servers"], start=1):
            lines.append(f"    server {server_name(b['name'], i)} {server}")
        blocks.append("\n".join(lines))
    return HEADER + "\n" + "\n\n".join(blocks) + "\n"


def render_map(backends: list[dict]) -> str:
    rows = [(host, f"{b['name']}_backend") for b in backends for host in b["hosts"]]
    width = max(len(host) for host, _ in rows)
    return HEADER + "".join(f"{host:<{width}} {backend}\n" for host, backend in rows)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--check", action="store_true", help="nur prüfen, ob die erzeugten Dateien aktuell sind")
    args = parser.parse_args()

    try:
        backends = validate(load(SOURCE))
    except (ConfigError, yaml.YAMLError) as exc:
        print(f"Fehler: {exc}", file=sys.stderr)
        return 2

    outputs = {BACKENDS_CFG: render_backends(backends), HOSTS_MAP: render_map(backends)}
    stale = [p for p, content in outputs.items() if not p.exists() or p.read_text(encoding="utf-8") != content]

    if args.check:
        for path in stale:
            print(f"veraltet: {path.relative_to(HAPROXY_DIR.parent)}", file=sys.stderr)
        return 1 if stale else 0

    for path in stale:
        # In-place schreiben statt umbenennen: Docker bindet die Dateien einzeln
        # ein, ein neuer Inode wäre im Container nicht sichtbar.
        path.write_text(outputs[path], encoding="utf-8")
        print(f"geschrieben: {path.relative_to(HAPROXY_DIR.parent)}")
    if not stale:
        print("unverändert")
    print(f"{len(backends)} Backends")
    return 0


if __name__ == "__main__":
    sys.exit(main())
