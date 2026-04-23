# HAProxy Monitoring Stack

Vollständiger Monitoring-Stack für HAProxy mit Prometheus und Grafana. Das Grafana-Dashboard zeigt den Status aller konfigurierten Backends als Ampelsystem sowie eine detaillierte Backend-Liste mit Session- und Traffic-Daten.

## Architektur

```text
                  ┌──────────────────────────────────────────┐
                  │           Docker Compose Stack           │
                  │                                          │
  :80  ──────────►│  HAProxy 3.x                             │
  :8404 ──────────│  ├── :8404/stats  → Stats-UI             │
                  │  └── :8404/metrics → Prometheus-Exporter │
                  │          │                               │
                  │          ▼                               │
                  │  Prometheus :9090                        │
                  │  └── scrape interval: 15s                │
                  │          │                               │
                  │          ▼                               │
  :3000 ──────────│  Grafana                                 │
                  │  └── Dashboard: Ampelsystem + Tabelle    │
                  └──────────────────────────────────────────┘

  HAProxy überwacht (Health-Checks alle 10s):
  ├── https://git.gmk.lan:3300/           (Gitea)
  ├── http://gmk.lan:8090/                (Web)
  ├── https://prometheus.gmk.lan:9090/    (Prometheus)
  ├── https://gmk.lan:9443/               (Secure Web)
  └── http://gmk.fritz.box:8080/          (FritzBox)
```

## Voraussetzungen

- Docker Engine ≥ 24
- Docker Compose ≥ 2.x
- Die konfigurierten Hostnamen (`gmk.lan`, `git.gmk.lan` usw.) müssen vom Docker-Host aus per DNS auflösbar sein

## Schritt-für-Schritt-Anleitung

### 1. Repository klonen

```bash
git clone <repository-url>
cd haproxy-monitoring
```

### 2. DNS-Auflösung prüfen

Teste, ob der Docker-Host die internen Hostnamen auflösen kann:

```bash
nslookup git.gmk.lan
nslookup gmk.lan
nslookup prometheus.gmk.lan
nslookup gmk.fritz.box
```

Falls die Auflösung fehlschlägt, in `docker-compose.yml` den eigenen DNS-Server eintragen:

```yaml
# In der haproxy-Service-Sektion:
dns:
  - 192.168.1.1   # IP des lokalen DNS-Servers anpassen
```

Alternativ können feste IPs über `extra_hosts` eingetragen werden:

```yaml
extra_hosts:
  - "git.gmk.lan:192.168.1.10"
  - "gmk.lan:192.168.1.20"
  - "prometheus.gmk.lan:192.168.1.30"
  - "gmk.fritz.box:192.168.178.1"
```

### 3. HAProxy-Konfiguration anpassen (optional)

Die Datei `haproxy/haproxy.cfg` enthält alle Backends mit ihren Health-Check-Einstellungen.

Relevante Parameter pro Backend:

```text
server <name> <host>:<port> check [ssl verify none] inter 10s fall 3 rise 2
```

| Parameter | Bedeutung |
| --- | --- |
| `inter 10s` | Health-Check-Interval |
| `fall 3` | 3 fehlgeschlagene Checks → Backend DOWN |
| `rise 2` | 2 erfolgreiche Checks → Backend wieder UP |
| `ssl verify none` | HTTPS-Backend ohne Zertifikatsprüfung (für self-signed Certs) |

### 4. Stack starten

```bash
docker compose up -d
```

Alle drei Container starten nacheinander. Der erste vollständige Prometheus-Scrape erfolgt nach ca. 15 Sekunden.

### 5. Verfügbarkeit prüfen

```bash
docker compose ps
```

Erwartete Ausgabe:

```text
NAME         STATUS          PORTS
haproxy      Up              0.0.0.0:80->80/tcp, 0.0.0.0:8404->8404/tcp
prometheus   Up              0.0.0.0:9090->9090/tcp
grafana      Up              0.0.0.0:3000->3000/tcp
```

### 6. HAProxy Stats-UI öffnen

Öffne im Browser: **<http://localhost:8404/stats>**

Hier sind alle Backends sofort mit ihrem aktuellen Status (grün/rot) sichtbar. Dies ist eine schnelle Kontrolle, ob die Health-Checks funktionieren.

### 7. Prometheus prüfen

Öffne: **<http://localhost:9090/targets>**

Der Target `haproxy` muss den Status **UP** haben. Falls nicht, Fehlermeldung unter „Error" prüfen.

Testabfrage in Prometheus (<http://localhost:9090/graph>):

```promql
haproxy_backend_active_servers
```

Liefert für jedes Backend die Anzahl aktiver Server. Wert `1` = Backend UP, `0` = Backend DOWN.

### 8. Grafana Dashboard öffnen

Öffne: **<http://localhost:3000>**

Anmeldedaten: `admin` / `admin` (bitte nach dem ersten Login ändern)

Das Dashboard **„HAProxy Backend Monitor"** wird automatisch als Startseite geladen.

#### Dashboard-Übersicht

| Bereich | Inhalt |
| --- | --- |
| **Ampelsystem** | 5 Kacheln — grün = UP, rot = DOWN, grau = keine Daten |
| **Backend-Tabelle** | Alle Backends mit Status (farbig), aktive Sessions, Verbindungen gesamt |
| **Session-Verlauf** | Zeitreihe der aktiven Sessions pro Backend |
| **Traffic** | Eingehender und ausgehender Datendurchsatz pro Backend |

### 9. Passwort ändern (empfohlen)

In Grafana: **Avatar oben rechts → Profile → Change Password**

Oder direkt in `docker-compose.yml` vor dem ersten Start:

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
| HAProxy Stats-UI | 8404 | <http://localhost:8404/stats> | — |
| HAProxy Prometheus-Metrics | 8404 | <http://localhost:8404/metrics> | — |
| HAProxy Proxy | 80 | <http://localhost:80> | — |

## Daten persistieren

Prometheus-Daten und Grafana-Konfiguration werden in Docker-Volumes gespeichert und bleiben bei `docker compose down` erhalten. Nur `docker compose down -v` löscht die Volumes.

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
docker compose logs -f grafana
```

## Neues Backend hinzufügen

**1. `haproxy/haproxy.cfg` – Backend-Sektion ergänzen:**

```haproxy
backend mein_backend
    description "Mein Service (host:port)"
    option httpchk
    http-check send meth GET uri /health
    http-check expect rstatus 2[0-9][0-9]|3[0-9][0-9]
    server meinserver host.example.com:8080 check inter 10s fall 3 rise 2
```

**2. Frontend-ACL in `haproxy.cfg` ergänzen:**

```haproxy
acl host_mein  hdr(host) -i host.example.com
use_backend mein_backend if host_mein
```

**3. HAProxy neu laden (ohne Downtime):**

```bash
docker compose kill -s HUP haproxy
```

**4. Grafana Dashboard anpassen:**

Im Dashboard Editor den neuen Backend-Namen (`mein_backend`) in den bestehenden Queries ergänzen oder ein neues Stat-Panel hinzufügen.

## Troubleshooting

### Backend bleibt rot / DOWN

```bash
# HAProxy-Logs prüfen
docker compose logs haproxy

# Health-Check manuell testen (vom Host aus)
curl -v https://git.gmk.lan:3300/
curl -v http://gmk.lan:8090/
```

### Prometheus scraped keine Daten

```bash
# Metrics-Endpoint direkt testen
curl http://localhost:8404/metrics | grep haproxy_backend
```

### Grafana zeigt "No data"

- Prometheus-Target muss UP sein: <http://localhost:9090/targets>
- Scrape muss mindestens einmal erfolgt sein (nach ~15s)
- Dashboard-Zeitraum prüfen: Standardmäßig „Letzte 1 Stunde"

### DNS nicht auflösbar im Container

```bash
# DNS-Auflösung im HAProxy-Container testen
docker compose exec haproxy nslookup git.gmk.lan
docker compose exec haproxy wget -qO- http://gmk.lan:8090/
```
