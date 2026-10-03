# Inference-Server (Produktivsystem)

Eigenständiger Stack für den produktiven Einsatz: nimmt ein Bild entgegen, prüft es mit dem **aktiven Modell** und
liefert die erkannten Objekte und die Liste der Kategorien als JSON. Kein Training, keine Datenbank, kein S3.

Das Docker-Image enthält **kein Modell**. Das Modell wird vom Trainingssystem per API übertragen
(Einstellungen → Produktivsystem, dann „Ausrollen“ auf der Seite *Modelle*), auf einem Volume gespeichert und ersetzt
das bisher aktive Modell. Ein neues Modell wird erst aktiviert, nachdem es geladen und testweise ausgeführt wurde –
schlägt das fehl, bleibt das alte Modell aktiv.

## Starten

```bash
cd inference-server
cp .env.example .env          # MODEL_UPLOAD_KEY setzen, z. B. openssl rand -hex 32
docker compose up -d --build
curl http://localhost:8100/api/v1/health
```

Danach im Trainingssystem unter **Einstellungen → Produktivsystem** die URL (z. B. `http://prod-server:8100`) und
denselben Access Key eintragen, speichern, „Verbindung testen“ – und auf der Seite *Modelle* ein Modell ausrollen.

Ohne eigenes Build auf dem Zielsystem: Image auf dem Build-Rechner im Repository-Root bauen (`make inference-server`,
optional `TAG=1.0.0`) und übertragen – per Registry (`make inference-server-push`, auf dem Zielsystem
`docker compose pull && docker compose up -d --no-build`) oder direkt per
`docker save swarnat/rtmdet-detection:latest | ssh prod docker load`. Image und Tag stehen in `.env`
(`INFERENCE_IMAGE`, `INFERENCE_TAG`).

Die API ist nicht verschlüsselt: vor dem Internet/Netzwerk einen Reverse Proxy mit HTTPS vorschalten
(der Access Key wird im Header übertragen).

## API

| Methode | Pfad | Zweck |
|---|---|---|
| `POST` | `/api/v1/detect` | Bild prüfen (Multipart-Feld `image`, optional `confidence` ≥ `MIN_CONFIDENCE`) |
| `GET` | `/api/v1/model` | aktives Modell (404, solange keins installiert ist) |
| `PUT` | `/api/v1/model` | Modell installieren – Access Key nötig (`X-Access-Key: …` oder `Authorization: Bearer …`) |
| `GET` | `/api/v1/health` | Status, auch ohne Modell |
| `GET` | `/api/v1/docs` | OpenAPI-Dokumentation |

```bash
curl -F image=@bild.jpg http://localhost:8100/api/v1/detect
```

```json
{
  "model": {"version": "model-0005", "architecture": "rtmdet-m", "class_names": ["person", "vehicle"],
            "input_width": 1536, "input_height": 864, "installed_at": "2026-10-03T20:24:36+00:00"},
  "image": {"width": 1920, "height": 1080},
  "confidence_threshold": 0.15,
  "inference_ms": 826.1,
  "categories": [
    {"class": "person", "count": 1, "max_confidence": 0.8095},
    {"class": "vehicle", "count": 6, "max_confidence": 0.7011}
  ],
  "detections": [
    {"class": "person", "confidence": 0.8095, "bbox": {"x1": 579, "y1": 155, "x2": 590, "y2": 181}}
  ]
}
```

`categories` = alle erkannten Klassen, sortiert nach höchster Confidence; `bbox` in Pixeln des hochgeladenen Bildes.
Ohne installiertes Modell antwortet `/detect` mit 503.

`PUT /api/v1/model` (Multipart): `manifest` (JSON mit `version`, `class_names`, `input_width`, `input_height`,
optional `nms_iou_threshold`, `architecture`, `metrics`), `model_xml` und `model_bin` (OpenVINO IR).

## Konfiguration (`.env`)

| Variable | Standard | Bedeutung |
|---|---|---|
| `MODEL_UPLOAD_KEY` | – (Pflicht) | Access Key für Modell-Uploads, mind. 16 Zeichen |
| `INFERENCE_PORT` | `8100` | Port auf dem Host |
| `MIN_CONFIDENCE` | `0.15` | niedrigste Confidence einer Erkennung (Standard-Schwelle von `/detect`) |
| `OPENVINO_DEVICE` | `CPU` | OpenVINO-Gerät |
| `MAX_UPLOAD_MB` / `MAX_MODEL_UPLOAD_MB` | `50` / `1024` | Größenlimits für Bilder bzw. Modelldateien |

## Tests

```bash
make inference-server-test
```
