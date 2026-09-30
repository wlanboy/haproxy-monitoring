# stats.py – Hat ein Dienst gerade Traffic?

`stats.py` fragt die Stats-Seite einer oder mehrerer HAProxy-Instanzen ab und
zeigt die Zahlen für alle Backends, deren Name auf ein Suchmuster passt. Damit
lässt sich schnell prüfen, ob bei einem Dienst Anfragen ankommen und ob seine
Server sie beantworten.

Das Skript braucht nur Python 3.9 oder neuer, weitere Pakete sind nicht nötig.

## Einrichtung

```bash
cd stats
cp .env.example .env
cp haproxy.txt.example haproxy.txt
```

In `.env` stehen die Zugangsdaten der Stats-Seite (`stats auth` in der
HAProxy-Konfiguration):

```
HAPROXY_STATS_USER=stats
HAPROXY_STATS_PASSWORD=geheim
```

In `haproxy.txt` steht eine HAProxy-Instanz pro Zeile:

```
# Kommentar
lb1.example.com                        # -> http://lb1.example.com:8404/stats;csv
lb2.example.com:9000                   # -> http://lb2.example.com:9000/stats;csv
https://lb3.example.com/haproxy?stats  # URL wird übernommen, ;csv angehängt
```

Beide Dateien stehen in `.gitignore` und werden nicht eingecheckt.

## Aufruf

```bash
./stats.py testservice
```

Das Suchmuster ist ein regulärer Ausdruck, Groß-/Kleinschreibung spielt keine
Rolle. Es muss nur irgendwo im Backend-Namen vorkommen: `testservice` findet also
`testservice_backend`, `backend_testservice_xyz` und `Test-Service`.

```bash
./stats.py '^api_'            # nur Backends, die mit api_ beginnen
./stats.py 'test|session'     # mehrere Dienste auf einmal
./stats.py test --no-servers # nur die Summenzeile je Backend
```

## Hat der Dienst Traffic?

Beispielausgabe:

```
== lb1 (http://lb1:8404/stats;csv)
PROXY              SERVER   STATUS  CHECK  CUR  MAX  LIMIT  TOTAL  RATE/s  QUEUE  IN      OUT   4XX  5XX  ECON  ERESP  RTIME  LASTCHG
backend_test_xyz  test   UP      L7OK   2    10          500    1       0      120.6K  9.4M  5    5    0     0      12ms   1h1m
backend_test_xyz  test2   DOWN    L4CON  0    3           20     0       0      1000B   2.0K  0    0    4     1      0ms    2m0s
backend_test_xyz  BACKEND  UP             2    10   400    520    1       0      121.5K  9.4M  5    5    4     1      12ms   1d1h
```

Die Zeile `BACKEND` ist die Summe über alle Server des Dienstes. Für die Frage
„kommt etwas an?“ reicht meist sie.

| Spalte | Bedeutung | Worauf achten |
|---|---|---|
| `CUR` | offene Verbindungen jetzt | > 0 heißt: in diesem Moment läuft Traffic |
| `RATE/s` | neue Verbindungen in der letzten Sekunde | Momentaufnahme; bei wenig genutzten Diensten oft 0, obwohl Traffic da ist |
| `TOTAL` | Verbindungen seit Start von HAProxy | zählt nur hoch; ein hoher Wert kann auch von gestern stammen |
| `IN` / `OUT` | übertragene Bytes seit Start | wie `TOTAL` |
| `STATUS` | `UP`, `DOWN`, `MAINT`, … | ohne einen Server auf `UP` wird kein Traffic ausgeliefert |
| `CHECK` | Ergebnis des letzten Health-Checks | `L7OK` ist gut, `L4CON`/`L4TOUT` heißt: Server nicht erreichbar |
| `4XX` / `5XX` | Antworten mit Fehlerstatus seit Start | steigender `5XX`-Wert: Traffic kommt an, der Dienst scheitert aber |
| `ECON` / `ERESP` | Verbindungs- bzw. Antwortfehler zum Server | > 0 heißt: HAProxy erreicht den Server nicht zuverlässig |
| `QUEUE` | Anfragen, die auf einen freien Server warten | > 0 heißt: der Dienst kommt nicht hinterher |
| `RTIME` | mittlere Antwortzeit der letzten Anfragen | |
| `LASTCHG` | Zeit seit dem letzten Statuswechsel | kurz heißt: der Server ist gerade erst hoch- oder runtergegangen |

### Sicher feststellen, ob gerade Traffic kommt

`CUR` und `RATE/s` sind Momentaufnahmen. Bei einem Dienst mit wenigen Anfragen
pro Minute stehen beide meistens auf 0. `TOTAL` zählt seit dem Start von
HAProxy und sagt allein nichts über „jetzt“.

Zuverlässig ist ein Vergleich von `TOTAL` über zwei Aufrufe:

```bash
./stats.py test --no-servers; sleep 60; ./stats.py test --no-servers
```

- `TOTAL` ist gestiegen: In dieser Minute kam Traffic an.
- `TOTAL` ist gleich geblieben: In dieser Minute kam nichts an.
- `TOTAL` ist gestiegen und `5XX` im gleichen Maß: Traffic kommt an, wird aber
  mit Fehlern beantwortet.

Bei mehreren HAProxy-Instanzen hinter einem Loadbalancer verteilt sich der
Traffic. Es reicht, wenn `TOTAL` auf einer Instanz steigt.

## Optionen

| Option | Wirkung |
|---|---|
| `-f DATEI` | andere Instanzliste statt `haproxy.txt` |
| `-e DATEI` | andere Env-Datei statt `.env` |
| `--no-servers` | nur `FRONTEND`-/`BACKEND`-Summen, keine einzelnen Server |
| `--no-frontends` | `FRONTEND`-Zeilen ausblenden |
| `-s` | Suchmuster zusätzlich auf Servernamen anwenden |
| `-t SEK` | HTTP-Timeout, Standard 5 Sekunden |
| `-k` | TLS-Zertifikat nicht prüfen (selbstsignierte Zertifikate) |
| `--no-color` | keine Farben (auch über `NO_COLOR=1`) |

`.env` und `haproxy.txt` werden zuerst im aktuellen Verzeichnis gesucht, dann
neben dem Skript. Bereits gesetzte Umgebungsvariablen haben Vorrang vor `.env`.

## Exit-Code

| Code | Bedeutung |
|---|---|
| 0 | mindestens ein Backend gefunden, alle Instanzen erreichbar |
| 1 | kein Backend passt, oder eine Instanz war nicht erreichbar |
| 2 | Aufruffehler (ungültiges Suchmuster, `haproxy.txt` fehlt oder ist leer) |

## Fehlermeldungen

| Meldung | Ursache |
|---|---|
| `HTTP 401 Unauthorized (HAPROXY_STATS_USER/…)` | Benutzer oder Passwort in `.env` falsch |
| `Connection refused` | Host oder Port falsch, oder die Stats-Seite ist nicht aktiviert |
| `timed out` | Host nicht erreichbar (Firewall, VPN) |
| `keine Proxies passend zu /…/` | Suchmuster trifft auf dieser Instanz kein Backend |
