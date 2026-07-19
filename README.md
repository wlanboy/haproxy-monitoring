# HAProxy Monitoring Stack

Vollständiger Monitoring-Stack für HAProxy mit Prometheus, Grafana und Blackbox Exporter. Das Setup simuliert eine Microservice-Landschaft mit 22 HAProxy-Backends, die alle über einen internen nginx-Container bedient werden. Drei Grafana-Dashboards zeigen HAProxy-Metriken, Backend-Erreichbarkeit per Blackbox-Probing sowie eine Backend-Registry.

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
                  │          │               für alle 22 Backends  │
                  │          ▼                                     │
                  │  haproxy-config-generator (Init-Container)     │
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
NAME        STATUS    PORTS
nginx       Up
haproxy     Up        0.0.0.0:8080->8080/tcp, 0.0.0.0:8404->8404/tcp
blackbox    Up        0.0.0.0:9115->9115/tcp
prometheus  Up        0.0.0.0:9090->9090/tcp
grafana     Up        0.0.0.0:3000->3000/tcp
```

### 4. HAProxy Stats-UI öffnen

Öffne im Browser: **<http://localhost:8404/stats>**

Der Browser fragt nach Zugangsdaten (`stats auth` in `haproxy.cfg`): **stats / statssecret**.

Alle 22 Backends sind sofort sichtbar. Da alle Server auf `nginx:80` zeigen, sollten sie den Status **grün/UP** haben.

### 5. Prometheus prüfen

Öffne: **<http://localhost:9090/targets>**

Zwei Job-Gruppen müssen den Status **UP** haben:

- `haproxy` – scrapt HAProxy-Metriken direkt
- `blackbox-http` – 22 Probing-Targets, einer pro Service

Testabfragen:

```promql
# Backend-Status (1 = UP, 0 = DOWN)
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
| **Blackbox Exporter** | HTTP-Erreichbarkeit und Latenzen aller 22 Services |
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

## HAProxy-Konfiguration

Die Datei [haproxy/haproxy.cfg](haproxy/haproxy.cfg) definiert 22 Backends. Alle Server zeigen im Demo-Setup auf `nginx:80` im internen Docker-Netzwerk. Health-Checks laufen alle 10 Sekunden.

```text
server <name> nginx:80 check inter 10s fall 3 rise 2
```

| Parameter | Bedeutung |
| --- | --- |
| `inter 10s` | Health-Check-Interval |
| `fall 3` | 3 fehlgeschlagene Checks → Backend DOWN |
| `rise 2` | 2 erfolgreiche Checks → Backend wieder UP |

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
    option httpchk
    http-check send meth GET uri /health
    http-check expect rstatus 2[0-9][0-9]|3[0-9][0-9]
    server meinserver mein-host:8080 check inter 10s fall 3 rise 2
```

Das Blackbox-Target für Prometheus muss **nicht** manuell gepflegt werden.
Der Init-Container `haproxy-config-generator` liest beim Start alle Backends
und deren Server-Adresse direkt aus dem HAProxy-Stats-CSV-Endpunkt
(`http://haproxy:8404/stats;csv`) aus und schreibt sie als
[file_sd-Target-Datei](https://prometheus.io/docs/guides/file-sd/) nach
`prometheus_targets:/haproxy_backends.json`. Prometheus liest diese Datei
über `file_sd_configs` und übernimmt neue Targets automatisch anhand von
`refresh_interval: 30s` – ganz ohne Prometheus-Reload.

**2. HAProxy neu laden (ohne Downtime):**

```bash
docker compose kill -s HUP haproxy
```

**3. Backend-Targets neu generieren:**

Der Generator läuft nur beim Start als Init-Container. Nach einer Änderung an
`haproxy.cfg` einmalig neu ausführen, damit die neue Zielliste geschrieben wird:

```bash
docker compose up -d haproxy-config-generator
```

Prometheus übernimmt die aktualisierte Datei automatisch innerhalb von 30s
(kein Reload nötig).

## Troubleshooting

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
