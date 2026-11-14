# generate_targets.py

Dieses Script fragt den HAProxy Stats-Endpoint (CSV-Export) ab, ermittelt daraus
**jeden einzelnen Server jedes konfigurierten Backends** samt Adresse und schreibt
sie als Prometheus `file_sd`-Target-Datei heraus. Diese Datei wird vom
`blackbox-exporter` als Service-Discovery-Quelle für den HTTP-Probe-Job genutzt –
so wird nicht nur ein Backend stellvertretend, sondern jeder Server dahinter
einzeln per HTTP-Probe überwacht.

Es läuft als Sidecar (siehe [Dockerfile](Dockerfile), Base-Image `python:3.13-alpine`,
unprivilegierter User mit UID 10001). Es fragt den Endpoint alle `INTERVAL` Sekunden
ab und schreibt die Zieldatei nur, wenn sich die Zielliste geändert hat. Neue
Backends in `haproxy.cfg` landen so ohne Neustart im Probing. Mit `INTERVAL=0`
läuft es einmalig und beendet sich.

## Ablauf

1. **Warten auf HAProxy** (`wait_for_stats`)
   Ruft `HAPROXY_STATS_URL` per HTTP GET ab. Schlägt der Request fehl (z. B. weil
   HAProxy noch nicht bereit ist), wird bis zu `MAX_RETRIES`-mal im Abstand von
   `RETRY_INTERVAL` Sekunden erneut versucht. Sind alle Versuche ausgeschöpft, bricht
   das Script mit `SystemExit` ab.

2. **CSV parsen** (`parse_backend_servers`)
   Die HAProxy-Stats-CSV enthält pro Backend mehrere Zeilen (u. a. `FRONTEND`,
   `BACKEND` und die einzelnen Server). Das Script filtert:
   - Zeilen ohne `pxname` oder mit `pxname == "stats"`
   - Zeilen mit `svname` in `FRONTEND`/`BACKEND`/leer

   Übrig bleiben die eigentlichen Server-Zeilen. Für **jeden** Server (nicht nur
   den ersten je Backend) wird ein Tupel `(backend_name, server_name, addr)`
   gesammelt.

3. **Target-Groups bauen** (`build_target_groups`)
   Für jeden Server wird ein eigenes Prometheus-Target-Group-Objekt erzeugt:
   - `targets`: `PROBE_SCHEME://<addr><PROBE_PATH>`, z. B. `http://10.0.0.5:8080/`
   - `labels.service`: Backend-Name ohne das Suffix `_backend`
   - `labels.haproxy_backend`: vollständiger HAProxy-Backend-Name
   - `labels.haproxy_server`: Name des einzelnen Servers (z. B. `gitea1`)

   Die Einträge werden dabei nach Backend- und Server-Name sortiert.

4. **Schreiben** (`update_targets`)
   Das Ergebnis wird mit dem Inhalt der vorhandenen `OUTPUT_FILE` verglichen. Nur bei
   einer Abweichung wird die Datei atomar neu geschrieben (tmp-Datei + rename,
   Verzeichnis wird bei Bedarf angelegt); das Log zeigt dann hinzugekommene und
   entfallene Targets, z. B. `Zielliste geändert (+2/-0)`.

5. **Schleife** (`run_loop`, nur bei `INTERVAL > 0`)
   Nach `INTERVAL` Sekunden beginnt der Ablauf ab Schritt 2 erneut, mit genau einem
   Abrufversuch pro Durchlauf. Schlägt ein Durchlauf fehl (HAProxy nicht erreichbar,
   keine Server, Schreibfehler), wird das geloggt und die zuletzt geschriebene Datei
   bleibt unverändert. `SIGTERM` (z. B. `docker stop`) beendet das Script sofort mit
   Exit-Code 0.

## Beispielausgabe

```json
[
  {
    "targets": ["http://10.0.0.5:8080/"],
    "labels": {
      "service": "webapp",
      "haproxy_backend": "webapp_backend",
      "haproxy_server": "webapp1"
    }
  },
  {
    "targets": ["http://10.0.0.6:8080/"],
    "labels": {
      "service": "webapp",
      "haproxy_backend": "webapp_backend",
      "haproxy_server": "webapp2"
    }
  }
]
```

Da jetzt pro Server ein eigenes Target entsteht, vergibt `prometheus/prometheus.yml`
das `instance`-Label aus `service` **und** `haproxy_server` (statt nur `service`),
damit mehrere Server desselben Backends im Dashboard nicht kollidieren.

## Umgebungsvariablen

| Variable            | Default                                 | Bedeutung                                      |
|---------------------|------------------------------------------|-------------------------------------------------|
| `HAPROXY_STATS_URL`  | `http://haproxy:8404/stats;csv`          | URL des HAProxy Stats-CSV-Endpoints              |
| `HAPROXY_STATS_USER`     | *(leer)*                             | Benutzername für HTTP-Basic-Auth am Stats-Endpoint (nur nötig, wenn `stats auth` in `haproxy.cfg` gesetzt ist) |
| `HAPROXY_STATS_PASSWORD` | *(leer)*                             | Passwort für HTTP-Basic-Auth am Stats-Endpoint. Wird niemals geloggt |
| `LOG_LEVEL`           | `INFO`                                   | Log-Level (`DEBUG`, `INFO`, `WARNING`, `ERROR`)  |
| `OUTPUT_FILE`         | `/output/haproxy_backends.json`          | Zielpfad der generierten Prometheus-`file_sd`-Datei |
| `PROBE_SCHEME`        | `http`                                   | Schema für die generierten Probe-Target-URLs     |
| `PROBE_PATH`          | `/`                                      | Pfad für die generierten Probe-Target-URLs       |
| `RETRY_INTERVAL`      | `2`                                       | Wartezeit in Sekunden zwischen Verbindungsversuchen |
| `MAX_RETRIES`         | `30`                                      | Maximale Anzahl an Verbindungsversuchen beim ersten Durchlauf |
| `INTERVAL`            | `60`                                      | Sekunden zwischen zwei Durchläufen im Sidecar-Modus. `0` = einmalig laufen und beenden. Mit `restart: unless-stopped` in Compose würde Docker den Container dann aber neu starten, also `0` nur für `docker run` verwenden |

## Konfiguration via .env

Die Datei [.env.example](.env.example) enthält alle Umgebungsvariablen aus der obigen
Tabelle mit ihren Defaultwerten und einer kurzen Erklärung als Kommentar. Für den
lokalen Einsatz (z. B. mit `docker run --env-file` oder `docker-compose`):

```bash
cp .env.example .env
# Werte bei Bedarf anpassen, z. B. HAPROXY_STATS_URL auf den eigenen Host zeigen lassen
```

`docker-compose`-Beispiel:

```yaml
services:
  config-generator:
    build: ./config-generator
    env_file: .env
    volumes:
      - ./output:/output
```

Ohne `.env`-Datei bzw. ohne gesetzte Variablen verwendet das Script die im Code
hinterlegten Defaults (siehe Tabelle oben).

## Fehlerfälle

Beim ersten Durchlauf:

- **HAProxy Stats-Endpoint nicht erreichbar**: Nach `MAX_RETRIES` Versuchen bricht
  das Script mit einer Fehlermeldung ab (Exit-Code ≠ 0). In Compose startet Docker
  den Container danach neu.
- **Authentifizierung fehlgeschlagen (HTTP 401/403)**: Bricht sofort ohne weitere
  Retries ab, da falsche Credentials sich durch Warten nicht beheben – geprüft
  werden sollten `HAPROXY_STATS_USER`/`HAPROXY_STATS_PASSWORD`.
- **Keine Backends gefunden**: Bricht ebenfalls mit Fehlermeldung ab, auch wenn der
  Stats-Endpoint erfolgreich erreichbar war.
- **Zieldatei nicht schreibbar** (`Permission denied`): Meist ein Volume, das noch
  vom früheren root-Container angelegt wurde. Lösung siehe Troubleshooting im
  [Haupt-README](../README.md).

In späteren Durchläufen beenden nur Authentifizierungsfehler das Script. Alle
anderen Fehler werden als Warnung geloggt, die bisherigen Targets bleiben stehen.
