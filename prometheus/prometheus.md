# prometheus.yml

Konfiguration des Prometheus-Servers für diesen Stack. Definiert zwei Scrape-Jobs.

## global

```yaml
scrape_interval: 15s
evaluation_interval: 15s
```

Alle Targets werden alle 15s gescrapt, Alerting-/Recording-Rules würden ebenfalls alle 15s ausgewertet (aktuell keine Rules konfiguriert).

## job: haproxy

```yaml
- job_name: 'haproxy'
  static_configs:
    - targets: ['haproxy:8404']
  metrics_path: /metrics
```

Statisches Target: scrapt `http://haproxy:8404/metrics` direkt. Das ist der native Prometheus-Exporter von HAProxy (`http-request use-service prometheus-exporter` in `haproxy.cfg`) und liefert Metriken wie `haproxy_backend_active_servers`, Sessions, Traffic etc. für alle 22 Backends auf einmal.

## job: blackbox-http

```yaml
- job_name: 'blackbox-http'
  metrics_path: /probe
  params:
    module: [http_2xx]
  file_sd_configs:
    - files:
        - /etc/prometheus/targets/haproxy_backends.json
      refresh_interval: 30s
  relabel_configs:
    - source_labels: [__address__]
      target_label: __param_target
    - source_labels: [service, haproxy_server]
      separator: "-"
      target_label: instance
    - target_label: __address__
      replacement: blackbox:9115
```

Nutzt das Blackbox-Exporter-Pattern für aktives HTTP-Probing statt eines statischen Targets:

- **`file_sd_configs`**: Die Zielliste wird nicht fest eingetragen, sondern aus `/etc/prometheus/targets/haproxy_backends.json` gelesen (Docker-Volume `prometheus_targets`). Diese Datei wird vom Init-Container `haproxy-config-generator` beim Start aus dem HAProxy-Stats-CSV generiert. `refresh_interval: 30s` sorgt dafür, dass Prometheus Änderungen an der Datei automatisch übernimmt, ganz ohne Reload.
- **`params.module: [http_2xx]`**: Jeder Scrape ruft den Blackbox Exporter mit dem `http_2xx`-Modul auf (aus `blackbox/blackbox.yml`), das prüft, ob die Ziel-URL mit einem 2xx-Statuscode antwortet.
- **`relabel_configs`** (in Reihenfolge wichtig, da Prometheus die Werte sequenziell umschreibt):
  1. `__address__` → `__param_target`: Die eigentliche Backend-URL aus der file_sd-Datei wird als `target`-Query-Parameter an den Blackbox-Probe-Request angehängt (`/probe?target=<url>`).
  2. `service` + `haproxy_server` → `instance`: Baut aus den Labels der file_sd-Datei einen sprechenden `instance`-Label-Wert (z. B. `api_backend-api1`), damit Dashboards die Probe-Ergebnisse einem konkreten Backend/Server zuordnen können.
  3. `__address__` → `blackbox:9115`: Überschreibt die Scrape-Adresse zuletzt auf den Blackbox-Exporter selbst — Prometheus scrapt also nicht das Backend direkt, sondern lässt Blackbox stellvertretend proben und liest dessen Ergebnis (`probe_success`, `probe_duration_seconds`, …).

Damit entsteht pro registriertem Backend automatisch ein Probing-Target, ohne dass `prometheus.yml` bei neuen Backends angefasst werden muss.
