#!/usr/bin/env bash
# Startet den kompletten Monitoring-Stack:
#   1. legt config-generator/.env an (falls noch nicht vorhanden)
#   2. baut das haproxy-config-generator Docker-Image
#   3. startet den Stack im Hintergrund (docker compose up -d)
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")"

ENV_FILE="config-generator/.env"
ENV_EXAMPLE="config-generator/.env.example"

echo "==> Pruefe ${ENV_FILE}"
if [[ -f "${ENV_FILE}" ]]; then
    echo "    vorhanden, wird nicht ueberschrieben"
else
    echo "    nicht vorhanden, erzeuge aus ${ENV_EXAMPLE}"
    cp "${ENV_EXAMPLE}" "${ENV_FILE}"
    # Stats-Auth-Credentials passend zu "stats auth stats:statssecret" in
    # haproxy/haproxy.cfg setzen, sonst schlaegt der config-generator mit
    # HTTP 401 fehl.
    sed -i 's/^HAPROXY_STATS_USER=.*/HAPROXY_STATS_USER=stats/' "${ENV_FILE}"
    sed -i 's/^HAPROXY_STATS_PASSWORD=.*/HAPROXY_STATS_PASSWORD=statssecret/' "${ENV_FILE}"
    echo "    ${ENV_FILE} erzeugt (Credentials: stats/statssecret)"
fi

echo "==> Baue Docker-Image(s)"
docker compose build

echo "==> Starte Stack im Hintergrund"
docker compose up -d

echo "==> Container-Status"
docker compose ps

cat <<'EOF'

Fertig. Nuetzliche Befehle:
  docker compose ps                Status der Container anzeigen
  docker compose logs -f           Logs aller Services verfolgen
  docker compose logs -f <service> Logs eines einzelnen Services (z.B. haproxy)

Stack wieder beenden:
  docker compose down       Container stoppen und entfernen, Daten (Volumes) bleiben erhalten
  docker compose down -v    Container UND Volumes entfernen (Prometheus-/Grafana-Daten,
                             generierte Blackbox-Targets) - kompletter Reset
EOF
