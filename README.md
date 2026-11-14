# HAProxy Monitoring Stack

Vollständiger Monitoring-Stack für HAProxy mit Prometheus, Grafana und Blackbox Exporter. Das Setup simuliert eine Microservice-Landschaft mit 23 HAProxy-Backends, die alle über einen internen nginx-Container bedient werden. Drei Grafana-Dashboards zeigen HAProxy-Metriken, Backend-Erreichbarkeit per Blackbox-Probing sowie eine Backend-Registry.

## Architektur

```text
                  ┌────────────────────────────────────────────────┐
                  │             Docker Compose Stack               │
                  │                                                │
  :8080 ─────────►│  HAProxy 3.x (non-root, unprivileged Port)     │
  :8404 ──────────│  ├── :8404/stats   → Stats-UI                  │
                  │  └── :8404/metrics → Prometheus-Exporter       │
                  │          │                          │          │
                  │          │                          ▼          │
                  │          │               nginx (intern :80)    │
                  │          │               └── Demo-Backend      │
                  │          │               für alle 23 Backends  │
                  │          ▼                                     │
                  │  haproxy-config-generator (Sidecar, alle 60s)  │
                  │  └── liest haproxy:8404/stats;csv und          │
                  │      schreibt Prometheus file_sd-Targets       │
                  │          │                                     │
                  │          ▼                                     │
                  │  Prometheus :9090                              │
                  │  ├── scrape: haproxy:8404/metrics (15s)        │
                  │  └── scrape: blackbox:9115 (file_sd, dynamisch)│
                  │          │                                     │
                  │          ▼                                     │
                  │  Blackbox Exporter :9115                       │
                  │  └── http_2xx Probing                          │
                  │          │                                     │
                  │          ▼                                     │
  :3000 ──────────│  Grafana                                       │
                  │  ├── Dashboard: HAProxy Backend Monitor        │
                  │  ├── Dashboard: Blackbox Exporter              │
                  │  └── Dashboard: HAProxy Registry               │
                  └────────────────────────────────────────────────┘

  HAProxy Backends (alle zeigen intern auf nginx:80):
  ├── gitea_backend       ├── api_backend        ├── auth_backend
  ├── users_backend       ├── orders_backend     ├── payments_backend
  ├── inventory_backend   ├── notifications_backend ├── search_backend
  ├── reporting_backend   ├── logging_backend    ├── config_backend
  ├── gateway_backend     ├── scheduler_backend  ├── cache_backend
  ├── media_backend       ├── mail_backend       ├── webhook_backend
  ├── audit_backend       ├── metrics_backend    ├── session_backend
  └── gmk8090_backend / gmk9443_backend
```

## Voraussetzungen

- Docker Engine ≥ 24
- Docker Compose ≥ 2.x

> Keine externen DNS-Abhängigkeiten – alle Backends laufen intern über den `nginx`-Container im selben Docker-Netzwerk.

## Schritt-für-Schritt-Anleitung

### 1. Repository klonen

```bash
git clone <repository-url>
cd haproxy-monitoring
```

### 2. Stack starten

```bash
./start.sh
```

Das Script legt beim ersten Lauf `config-generator/.env` an (Stats-Auth-Credentials
passend zu `haproxy/haproxy.cfg`), baut das `haproxy-config-generator`-Image und
startet den Stack per `docker compose up -d`. Alternativ manuell:

```bash
cp config-generator/.env.example config-generator/.env   # einmalig, Credentials eintragen
docker compose up -d
```

Alle Container starten nacheinander. Der erste vollständige Prometheus-Scrape erfolgt nach ca. 15 Sekunden.

### 3. Verfügbarkeit prüfen

```bash
docker compose ps
```

Erwartete Ausgabe:

```text
NAME                      STATUS          PORTS
nginx                     Up
haproxy                   Up (healthy)    0.0.0.0:8080->8080/tcp, 0.0.0.0:8404->8404/tcp
haproxy-config-generator  Up
blackbox                  Up              127.0.0.1:9115->9115/tcp
prometheus                Up              127.0.0.1:9090->9090/tcp
grafana                   Up              0.0.0.0:3000->3000/tcp
```

### 4. HAProxy Stats-UI öffnen

Öffne im Browser: **<http://localhost:8404/stats>**

Der Browser fragt nach Zugangsdaten (`stats auth` in `haproxy.cfg`): **stats / statssecret**.

Alle 23 Backends sind sofort sichtbar. Da alle Server auf `nginx:80` zeigen, sollten sie den Status **grün/UP** haben.

### 5. Prometheus prüfen

Öffne: **<http://localhost:9090/targets>**

Zwei Job-Gruppen müssen den Status **UP** haben:

- `haproxy` – scrapt HAProxy-Metriken direkt
- `blackbox-http` – 69 Probing-Targets, eins pro Server (23 Backends × 3 Server)

Testabfragen:

```promql
# Anzahl aktiver Server pro Backend im Status UP (hier 3, 0 = Backend komplett DOWN)
haproxy_backend_active_servers

# Blackbox HTTP-Erreichbarkeit (1 = OK, 0 = Fehler)
probe_success
```

### 6. Grafana Dashboards öffnen

Öffne: **<http://localhost:3000>**

Anmeldedaten: `admin` / `admin` (bitte nach dem ersten Login ändern)

| Dashboard | Inhalt |
| --- | --- |
| **HAProxy Backend Monitor** | Ampelsystem + Session/Traffic-Tabelle pro Backend |
| **Blackbox Exporter** | HTTP-Erreichbarkeit und Latenzen aller 69 Server (23 Services) |
| **HAProxy Registry** | Übersicht aller registrierten Backends |

### 7. Passwort ändern (empfohlen)

In Grafana: **Avatar oben rechts → Profile → Change Password**

Oder vorab in `docker-compose.yml`:

```yaml
environment:
  - GF_SECURITY_ADMIN_PASSWORD=MeinSicheresPasswort
```

---

## Dienste und Ports

| Dienst | Port | URL | Zugang |
| --- | --- | --- | --- |
| Grafana | 3000 | <http://localhost:3000> | admin / admin |
| Prometheus | 9090 | <http://localhost:9090> | — |
| Blackbox Exporter UI | 9115 | <http://localhost:9115> | — |
| Blackbox Exporter Metrics | 9115 | <http://localhost:9115/metrics> | — |
| HAProxy Stats-UI | 8404 | <http://localhost:8404/stats> | stats / statssecret |
| HAProxy Prometheus-Metrics | 8404 | <http://localhost:8404/metrics> | — |
| HAProxy Proxy | 8080 | <http://localhost:8080> | — |

Prometheus (9090) und Blackbox Exporter (9115) sind nur an `127.0.0.1` gebunden. Beide sind ohne Login erreichbar: Über `/probe?target=…` würde der Blackbox Exporter beliebige URLs aus dem Docker-Netz abrufen, und `--web.enable-lifecycle` erlaubt `POST /-/quit`. Von einem anderen Rechner aus geht der Zugriff per SSH-Tunnel, z. B. `ssh -L 9090:localhost:9090 <host>`.

## HAProxy-Konfiguration

Die Datei [haproxy/haproxy.cfg](haproxy/haproxy.cfg) definiert 23 Backends mit je 3 Servern. Alle Server zeigen im Demo-Setup auf `nginx:80` im internen Docker-Netzwerk.

Health-Check und Server-Optionen stehen einmal in der `defaults`-Sektion und gelten für alle Backends:

```haproxy
option httpchk
http-check send meth GET uri /
http-check expect rstatus 2[0-9][0-9]|3[0-9][0-9]
default-server check inter 10s fall 3 rise 2
```

| Parameter | Bedeutung |
| --- | --- |
| `inter 10s` | Health-Check-Interval |
| `fall 3` | 3 fehlgeschlagene Checks → Server DOWN |
| `rise 2` | 2 erfolgreiche Checks → Server wieder UP |

Das Frontend auf Port 8080 wählt das Backend über den Host-Header: `<name>.localhost` geht an `<name>_backend`, unbekannte Hosts an `gitea_backend`.

```bash
curl -H 'Host: api.localhost' http://localhost:8080/
```

Im Browser funktioniert direkt <http://api.localhost:8080/>, weil `*.localhost` auf 127.0.0.1 auflöst.

## Daten persistieren

Prometheus-Daten (30 Tage Retention) und Grafana-Konfiguration werden in Docker-Volumes gespeichert.

```bash
# Stack stoppen (Daten bleiben erhalten)
docker compose down

# Stack stoppen und alle Daten löschen
docker compose down -v
```

## Logs anzeigen

```bash
# Alle Container
docker compose logs -f

# Einzelner Container
docker compose logs -f haproxy
docker compose logs -f prometheus
docker compose logs -f blackbox
docker compose logs -f grafana
```

## Neues Backend hinzufügen

**1. `haproxy/haproxy.cfg` – Backend-Sektion ergänzen:**

```haproxy
backend mein_backend
    description "Mein Service"
    server meinserver mein-host:8080
```

Health-Check-Optionen kommen aus `defaults`. Weicht der Check-Pfad ab, reicht im Backend `http-check send meth GET uri /health` (zusammen mit einer eigenen `http-check expect`-Zeile, weil Backends mit eigenen Check-Regeln die aus `defaults` komplett ersetzen).

Damit das Backend über Port 8080 erreichbar ist, im Frontend `http_in` eine Routing-Zeile ergänzen:

```haproxy
    use_backend mein_backend if { var(txn.host) -m str mein.localhost }
```

Das Blackbox-Target für Prometheus muss **nicht** manuell gepflegt werden.
Der Sidecar `haproxy-config-generator` liest alle 60 Sekunden alle Backends
und deren Server-Adresse direkt aus dem HAProxy-Stats-CSV-Endpunkt
(`http://haproxy:8404/stats;csv`) aus und schreibt sie als
[file_sd-Target-Datei](https://prometheus.io/docs/guides/file-sd/) nach
`prometheus_targets:/haproxy_backends.json`, allerdings nur, wenn sich die
Zielliste geändert hat. Prometheus liest diese Datei
über `file_sd_configs` und übernimmt neue Targets automatisch anhand von
`refresh_interval: 30s` – ganz ohne Prometheus-Reload.

**2. HAProxy neu laden (ohne Downtime):**

```bash
docker compose kill -s HUP haproxy
```

Mehr ist nicht nötig. Der Generator erkennt das neue Backend beim nächsten
Durchlauf (spätestens nach 60s, einstellbar über `INTERVAL` in
`config-generator/.env`) und schreibt die Zielliste neu. Im Log steht dann
z. B. `Zielliste geändert (+1/-0)`. Prometheus übernimmt die Datei innerhalb
von weiteren 30s.

## Troubleshooting

### Generator startet nicht oder schreibt keine Targets

```bash
docker compose logs haproxy-config-generator
```

- `Authentifizierung ... fehlgeschlagen (HTTP 401)`: `HAPROXY_STATS_USER`/
  `HAPROXY_STATS_PASSWORD` in `config-generator/.env` passen nicht zu
  `stats auth` in `haproxy.cfg`.
- `Schreiben von /output/haproxy_backends.json fehlgeschlagen: [Errno 13] Permission denied`:
  Das Volume `prometheus_targets` stammt noch aus der Zeit, als der Generator als
  root lief. Seit er als UID 10001 läuft, gehört ihm ein bereits vorhandenes Volume
  nicht. Einmalig umstellen:

  ```bash
  docker compose run --rm --no-deps --user root --entrypoint chown \
      haproxy-config-generator -R 10001:10001 /output
  docker compose restart haproxy-config-generator
  ```

  Alternativ das Volume löschen (es enthält nur generierte Daten):
  `docker compose down` und danach `docker volume rm haproxy-monitoring_prometheus_targets`.
- Der Generator wartet, bis HAProxy `healthy` ist (Healthcheck auf
  `http://127.0.0.1:8404/healthz`, siehe `monitor-uri` in `haproxy.cfg`).
  Fällt HAProxy später aus, behält er die zuletzt geschriebenen Targets und
  versucht es im nächsten Durchlauf erneut.

### Backend bleibt rot / DOWN

```bash
# HAProxy-Logs prüfen
docker compose logs haproxy

# Health-Check manuell aus dem Container testen
docker compose exec haproxy wget -qO- http://nginx:80/
```

### Prometheus scraped keine Daten

```bash
# HAProxy Metrics-Endpoint direkt testen
curl http://localhost:8404/metrics | grep haproxy_backend

# Blackbox Probe manuell testen
curl "http://localhost:9115/probe?target=http://nginx:80/&module=http_2xx"
```

### Grafana zeigt "No data"

- Prometheus-Targets müssen UP sein: <http://localhost:9090/targets>
- Scrape muss mindestens einmal erfolgt sein (nach ~15s)
- Dashboard-Zeitraum prüfen: Standardmäßig „Letzte 1 Stunde"
