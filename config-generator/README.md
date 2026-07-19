# generate_targets.py

Dieses Script fragt den HAProxy Stats-Endpoint (CSV-Export) ab, ermittelt daraus
**jeden einzelnen Server jedes konfigurierten Backends** samt Adresse und schreibt
sie als Prometheus `file_sd`-Target-Datei heraus. Diese Datei wird vom
`blackbox-exporter` als Service-Discovery-Quelle für den HTTP-Probe-Job genutzt –
so wird nicht nur ein Backend stellvertretend, sondern jeder Server dahinter
einzeln per HTTP-Probe überwacht.

Es läuft als Init-Container (siehe [Dockerfile](Dockerfile), Base-Image `python:3.13-alpine`)
vor dem eigentlichen Blackbox-Exporter und generiert die Zieldatei einmalig beim Start.

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

4. **Schreiben** (`main`)
   Das Ergebnis wird als JSON-Array nach `OUTPUT_FILE` geschrieben (Verzeichnis wird
   bei Bedarf angelegt). Werden keine Server gefunden, bricht das Script mit
   `SystemExit` ab.

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
| `OUTPUT_FILE`         | `/output/haproxy_backends.json`          | Zielpfad der generierten Prometheus-`file_sd`-Datei |
| `PROBE_SCHEME`        | `http`                                   | Schema für die generierten Probe-Target-URLs     |
| `PROBE_PATH`          | `/`                                      | Pfad für die generierten Probe-Target-URLs       |
| `RETRY_INTERVAL`      | `2`                                       | Wartezeit in Sekunden zwischen Verbindungsversuchen |
| `MAX_RETRIES`         | `30`                                      | Maximale Anzahl an Verbindungsversuchen          |

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

- **HAProxy Stats-Endpoint nicht erreichbar**: Nach `MAX_RETRIES` Versuchen bricht
  das Script mit einer Fehlermeldung ab (Exit-Code ≠ 0).
- **Keine Backends gefunden**: Bricht ebenfalls mit Fehlermeldung ab, auch wenn der
  Stats-Endpoint erfolgreich erreichbar war.
