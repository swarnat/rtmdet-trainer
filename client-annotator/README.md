# Kunden-Annotationsdienst (Client Annotator)

Eigenständiger Stack, der direkt auf dem Kundenserver läuft: Bilder per **Batch-Download** (URL-Liste) oder Upload laden,
gegen den **Inference-Server** prüfen, die Treffer anzeigen und **annotieren** – mit denselben Werkzeugen wie im
Trainingssystem (Boxen zeichnen, Vorschläge übernehmen, Fehlalarme als Hard Negative markieren, Tastenkürzel).

Kein Training, kein PostgreSQL, kein S3: Bilder, Thumbnails, eine SQLite-Datei und die Konfiguration liegen im Volume
`/data`. Das Trainingssystem überträgt die Konfiguration, holt alle Bilder samt Annotationen ab und löscht jedes
eingelesene Bild hier – danach kann der nächste Batch vorbereitet werden.

## Starten

```bash
cd client-annotator
cp .env.example .env          # CLIENT_ACCESS_TOKEN setzen, z. B. openssl rand -hex 32
docker compose up -d --build
curl http://localhost:8200/api/v1/health
```

Weboberfläche: `http://<kundenserver>:8200` – Anmeldung mit dem Access Token (Cookie, 30 Tage).

Im Trainingssystem unter **Einstellungen → Kunden-Annotationsdienst** die URL (z. B. `http://kundenserver:8200`), denselben
Access Token und – falls er vom Kundenserver aus anders erreichbar ist – die Adresse des Inference-Servers eintragen
(z. B. `http://localhost:8100`, wenn beide Dienste auf dem Kundenserver laufen; leer = URL des Produktivsystems), speichern
und **Konfiguration übertragen**. Erst danach lassen sich Bilder annotieren und prüfen.

Ohne eigenes Build auf dem Zielsystem: Image im Repository-Root bauen (`make client-annotator`, optional `TAG=1.0.0`)
und per Registry (`make client-annotator-push`, dort `docker compose pull && docker compose up -d --no-build`) oder
`docker save swarnat/rtmdet-client-annotator:latest | ssh kunde docker load` übertragen.

Die API ist nicht verschlüsselt: vor dem Netzwerk einen Reverse Proxy mit HTTPS vorschalten (der Token wird im Header
bzw. Cookie übertragen; hinter HTTPS wird das Cookie als `Secure` gesetzt, wenn der Proxy `X-Forwarded-Proto` sendet).

## Ablauf

1. **Bilder laden:** *Batch-Download* (eine URL pro Zeile) oder *Hochladen*. Gleiche Dateien werden nur einmal gespeichert.
2. **Prüfen:** *Prüfen* (Taste T) schickt das Bild an den Inference-Server, *Offene prüfen* alle offenen, noch nicht
   geprüften Bilder. Die Treffer erscheinen gestrichelt als Vorschläge.
3. **Annotieren:** Box ziehen, Klasse 1–9, Vorschlag übernehmen (Enter/Doppelklick, Shift+A = alle), Fehlalarm (N),
   Entf, Strg+Z, *Speichern* (Strg+S) markiert das Bild als annotiert – ohne Boxen als Bild ohne Objekte.
4. **Abholen:** im Trainingssystem *Client* → *Einlesen*. Annotierte Bilder werden dort als annotiert übernommen,
   offene mit ihrer Prüfung als Vorschläge; danach werden sie hier gelöscht.

## API

Alle Aufrufe außer `/health` brauchen den Token: `X-Access-Key: …`, `Authorization: Bearer …` oder das Login-Cookie.

| Methode | Pfad | Zweck |
|---|---|---|
| `GET` | `/api/v1/health` | Status (ohne Token) |
| `POST` / `DELETE` | `/api/v1/session` | Anmelden (`{"token": …}`, setzt Cookie) / Abmelden |
| `GET` / `PUT` | `/api/v1/config` | Konfiguration: `classes` (`name`, `label`, `color`), `inference_url`, `confidence` |
| `GET` | `/api/v1/images` | alle Bilder mit Annotationen und letzter Prüfung (`?status=open\|annotated`, `?limit=0` = nur Zähler) |
| `POST` | `/api/v1/images` | Upload (Multipart-Feld `files`) |
| `POST` | `/api/v1/images/from-url` | ein Bild von einer URL laden (`{"url": …}`) |
| `GET` | `/api/v1/images/{id}` · `/file` · `/thumbnail` | Metadaten, Originaldatei, Vorschaubild |
| `PUT` | `/api/v1/images/{id}/annotations` | alle Boxen ersetzen (`annotations`, `mark_annotated`) |
| `PATCH` | `/api/v1/images/{id}` | `{"status": "open"}` – wieder öffnen |
| `POST` | `/api/v1/images/{id}/detect` | gegen den Inference-Server prüfen (optional `{"confidence": …}`) |
| `DELETE` | `/api/v1/images/{id}` | löschen (auch nach dem Einlesen durch das Trainingssystem) |

## Konfiguration (`.env`)

| Variable | Standard | Bedeutung |
|---|---|---|
| `CLIENT_ACCESS_TOKEN` | – (Pflicht) | Access Token für Weboberfläche und Trainingssystem, mind. 16 Zeichen |
| `CLIENT_ANNOTATOR_PORT` | `8200` | Port auf dem Host |
| `MAX_UPLOAD_MB` | `50` | Größenlimit pro Bild |
| `DOWNLOAD_PROXY` | – | optionaler Proxy für den Batch-Download, z. B. `http://proxy-host:8888` |

## Entwicklung & Tests

```bash
make client-annotator-test                    # API-Tests in Docker
# Weboberfläche mit Hot Reload (Dienst läuft auf Port 8200):
cd frontend && VITE_API_PROXY=http://localhost:8200 npm run dev:client
```

Die Oberfläche ist ein zweiter Einstiegspunkt des Frontend-Projekts (`frontend/client.html`, `frontend/src/client/`) und
nutzt dessen Annotationskomponenten; Bildprüfung und Download kommen aus `common/odcore` (`images.py`, `download.py`).
