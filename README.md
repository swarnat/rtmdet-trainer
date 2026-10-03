# Object Detection Training & Inference

Lokal betreibbare Webanwendung zur Objekterkennung in 16:9-Kamerabildern mit RTMDet (Größen tiny, S, M wählbar). Die Klassen sind in der Anwendung konfigurierbar; ausgeliefert wird sie mit **Personen**, **Fahrrädern** und **Fahrzeugen**, inklusive Annotation, manuell gestartetem Nachtraining (RTMDet-S / MMDetection) und Modellverwaltung mit Production/Candidate/Archiv-Versionen. Die Inferenz läuft mit OpenVINO auf der CPU, das Training in einem separaten Container (GPU optional).

```
            ┌──────────────┐  /api  ┌──────────────────────────┐        ┌────────────┐
 Browser ──►│  frontend    │───────►│  api (FastAPI)           │◄──SQL─►│  postgres  │
            │  Vue/Quasar  │        │  OpenVINO-Inferenz (CPU) │        └────────────┘
            │  nginx       │        │  REST, OpenAPI           │──S3───►┌────────────┐
            └──────────────┘        └──────────┬───────────────┘        │  garage    │
                                               │ RQ-Job                 │  (S3)      │
                                         ┌─────▼─────┐                  └─────▲──────┘
                                         │  redis    │                        │
                                         └─────┬─────┘                        │
                                     ┌─────────▼──────────────────────┐       │
                                     │ trainer (PyTorch, MMDetection) │───────┘
                                     │ RTMDet-S, ONNX/OpenVINO-Export │
                                     └────────────────────────────────┘
```

| Dienst        | Aufgabe |
|---------------|---------|
| `frontend`    | Vue 3 + Quasar + vue-konva, ausgeliefert über nginx, Proxy `/api` → `api` |
| `api`         | FastAPI: `/api/v1/detect`, Bilder, Annotationen, Training, Modelle, Settings; OpenVINO-Inferenz |
| `trainer`     | RQ-Worker: Dataset-Snapshot, RTMDet-S-Training, Evaluation, ONNX/OpenVINO-Export, Registrierung |
| `postgres`    | Metadaten (Images, Annotations, TrainingRuns, ModelVersions, Settings) |
| `redis`       | Job-Queue (RQ) |
| `garage`      | S3-Storage für Bilder, Dataset-Snapshots, Modelle |
| `garage-init` | einmalige, idempotente Initialisierung (Layout, S3-Key, Buckets) |

## Schnellstart

Voraussetzungen: Docker mit Compose v2. Für GPU-Training zusätzlich NVIDIA-Treiber und das NVIDIA Container Toolkit. Ohne GPU läuft das Training auf der CPU, aber sehr langsam.

```bash
./scripts/generate-env.sh      # erzeugt .env mit zufälligen Secrets, erkennt die NVIDIA-Runtime
docker compose up -d           # baut und startet alles
./scripts/wait-for-services.sh # wartet, bis die API gesund ist
```

* UI: <http://localhost:8080> (`FRONTEND_PORT`)
* OpenAPI/Swagger: <http://localhost:8080/api/v1/docs> (auch direkt: <http://localhost:8000/api/v1/docs>, `API_PORT`)

Beim ersten Start lädt der Trainer den COCO-pretrained RTMDet-S-Checkpoint, legt ihn in S3 ab (`models/base/…`) und exportiert ihn als `model-0001`. Dabei werden die COCO-Klassen per Mapping auf die konfigurierten Klassen abgebildet (siehe unten). Da noch kein Production-Modell existiert, wird `model-0001` Production. `/detect` funktioniert also sofort, ohne eigene Trainingsdaten. Abschalten lässt sich das mit `BOOTSTRAP_ON_START=false`.

Alle Daten liegen in Docker-Volumes (`postgres-data`, `garage-meta`, `garage-data`, `redis-data`, `model-cache`) und überleben Neustarts und `docker compose down`. `docker compose down -v` löscht alles.

### Konfiguration

Sämtliche Zugangsdaten kommen aus der `.env` (Vorlage: `.env.example`). Im Quellcode stehen keine Secrets. Garage liest `rpc_secret` und `admin_token` aus `GARAGE_RPC_SECRET` und `GARAGE_ADMIN_TOKEN`. Der S3-Key (`S3_ACCESS_KEY_ID`/`S3_SECRET_ACCESS_KEY`, Format `GK` + 24 Hex bzw. 64 Hex) wird von `garage-init` importiert.

GPU-Training wird über `COMPOSE_FILE=docker-compose.yml:docker-compose.gpu.yml` in der `.env` aktiviert. Ohne GPU diese Zeile auf `docker-compose.yml` setzen.

Die Klassen samt COCO-Mapping werden unter **Klassen** gepflegt (Tabelle `detection_classes`). Weitere fachliche Einstellungen (Standardauflösung, angebotene Auflösungen, Confidence, NMS-IoU, Validierungsanteil) liegen in der Tabelle `settings` und sind in der UI unter **Einstellungen** änderbar. Sie wirken ohne Neustart.

## Bedienung

### Annotation (`/annotate`)

* Links: Bildliste mit Filter (alle / offen / fertig / negativ / prüfen), Upload per Button oder Drag & Drop (JPEG/PNG/WebP/BMP, Duplikate werden per SHA-256 erkannt).
* Mitte: Bild mit Bounding Boxes (Konva). **Ziehen auf freier Fläche** erzeugt eine Box mit der aktiven Klasse. Eine Box **anklicken** wählt sie aus, **ziehen** verschiebt sie, die **Anfasser** skalieren sie. Mausrad zoomt, Leertaste, mittlere oder rechte Maustaste + Ziehen verschiebt die Ansicht.
* Rechts: Liste der Boxen, Modelltest, Bildaktionen.
* **Speichern** markiert das Bild als `labeled`. Ein gespeichertes Bild **ohne Boxen** ist ein gültiges **negatives Trainingsbild**. Ein noch nicht bearbeitetes Bild bleibt `unlabeled` und kommt nicht ins Training.

| Taste | Funktion |
|-------|----------|
| `1` … `9` | Klasse in der unter „Klassen“ festgelegten Reihenfolge (für neue Boxen und die ausgewählte Box). Bis 5 aktive Klassen als Buttons, darüber als Dropdown |
| `Entf` / `Backspace` | ausgewählte Box löschen |
| `Strg+S` | speichern |
| `Strg+Z` | rückgängig |
| `Esc` | Auswahl aufheben |
| `T` | Modell testen |
| `H` | Predictions ein-/ausblenden |
| `Enter` / Doppelklick | ausgewählte Prediction übernehmen |
| `N` | ausgewählte Prediction als False Positive / Hard Negative markieren |
| `Umschalt+A` | alle Predictions übernehmen |
| `Bild↑` / `Bild↓` | vorheriges / nächstes Bild |

**Hard Negatives:** Erkennt ein Modell etwas fälschlich (z. B. ein Hinweisschild als Person), markiert „Als False Positive / Hard Negative markieren“ (Taste `N` oder ⊘ in der Prediction-Liste) die Region als bekannten Fehlalarm dieser Klasse. Im Canvas erscheinen Hard Negatives abgedunkelt, kurz gestrichelt und mit „⊘ HN“-Label; in der Seitenleiste haben sie eine eigene Liste. Ein Bild nur mit Hard Negatives zählt als negatives Bild. Details unter [Hard Negatives](#hard-negatives).

**Batch-Test:** Der Button „Batch-Test“ über der Bildliste testet ein Modell (Production, Candidate oder eine Version; Auflösung und Confidence wählbar) einmal auf allen offenen Bildern, optional auch auf annotierten Bildern, die für neue Klassen nachzuprüfen sind. Die Erkennungen werden pro Bild als **Vorschläge** gespeichert (Tabelle `image_suggestions`), Annotationen bleiben unverändert. Nach Abschluss zeigt der Filter „Mit Vorschlägen“ die betroffenen Bilder (Badge „n Vorschl.“, „0 Vorschl.“ = Kandidat für ein Negativbild). Beim Öffnen eines Bildes erscheinen die Vorschläge als Predictions; Vorschläge, die eine vorhandene Box gleicher Klasse bereits abdeckt (IoU ≥ 0,5), werden ausgeblendet. Dann wie gewohnt übernehmen, alle übernehmen oder als Hard Negative markieren. Beim Speichern als annotiert werden die restlichen Vorschläge des Bildes verworfen; ein neuer Batch-Test ersetzt ältere Vorschläge. Der Batch-Test läuft im API-Container auf einem Hintergrund-Thread (immer nur einer gleichzeitig, mit Fortschritt und Abbruch) und nutzt dieselben kompilierten OpenVINO-Modelle wie `/detect` (ca. 0,3–0,5 s pro Bild mit RTMDet-S bei 1536×864). Laufende `/detect`-Anfragen teilen sich währenddessen die CPU.

**Modell testen:** Production-Modell, neuesten Candidate oder eine beliebige Version wählen, dazu Eingangsauflösung und Confidence. Die API führt eine normale Detection auf dem gespeicherten Bild aus. Predictions erscheinen gestrichelt, kursiv, mit ⚡ und Confidence und sind so klar von manuellen Annotationen zu unterscheiden. „Prediction übernehmen“ bzw. „Alle übernehmen“ macht daraus normale, editierbare Annotationen (Quelle `prediction`).

### Klassen (`/classes`)

Klassen hinzufügen, umbenennen (Anzeigename), einfärben, sortieren, deaktivieren oder (ohne Annotationen) löschen sowie das COCO-Mapping pflegen. Details unter [Klassen](#klassen).

### Modellgrößen

Als Basis stehen drei COCO-pretrained RTMDet-Größen zur Wahl (Trainingsdialog „Base Model“; Vorauswahl unter Einstellungen):

| Basis | COCO AP | Parameter | CPU-Inferenz 1536×864* | GPU-Speicher Training (Batch 4, 1536×864)* |
|-------|---------|-----------|------------------------|---------------------------------------------|
| `rtmdet-tiny-coco` | 41,1 | 4,8 M | ~250 ms | ~2,3 GB |
| `rtmdet-s-coco` (Standard) | 44,6 | 8,9 M | ~310–400 ms | ~3,3 GB |
| `rtmdet-m-coco` | 49,4 | 24,7 M | ~970 ms | ~5,9 GB |

\* gemessen auf i9-12900H (WSL2, OpenVINO CPU) bzw. RTX 3070 Ti Laptop (8 GB).

Annotationen sind modellunabhängig (Originalpixel in PostgreSQL) und bleiben beim Wechsel der Größe unverändert. Zum Ausprobieren einer anderen Größe ohne Training: **Modelle → „COCO-Basismodell importieren“**, Größe wählen, dann in der Annotation mit „Modell testen“ die neue Version auswählen. Ein Training ab einer anderen Größe erzeugt eine eigene Candidate-Version; der automatische Vergleich mit dem Production-Modell funktioniert auch größenübergreifend. Weitertrainieren einer eigenen Version erfolgt immer in deren Größe (`architecture` der Version). Die Checkpoints werden beim ersten Gebrauch heruntergeladen (der Model Zoo ist teils langsam; Fortschritt im Trainer-Log), per SHA-256-Präfix geprüft und in `models/base/` abgelegt.

### Training (`/training`)

Dialog mit den zu trainierenden **Klassen** (Standard: alle aktiven), Base Model (RTMDet-S COCO oder eine eigene Version zum Weitertrainieren), Input Resolution, Epochs, Batch Size, optionaler Learning Rate und Anzahl Loader-Worker. Ein Lauf durchläuft `queued → running → completed | failed`. Die UI zeigt Fortschritt (Epoche, Loss, ETA), die Validierungs-mAP je Epoche und das Live-Log. Läufe lassen sich abbrechen. Ein Training wird **nie automatisch Production**, das Ergebnis ist immer eine neue **Candidate**-Version.

### Modelle (`/models`)

Liste aller unveränderlichen Versionen (`model-0001`, `model-0002`, …) mit Status `candidate | production | archived`, Metriken und Artefakt-Downloads (PyTorch-Checkpoint, ONNX, OpenVINO, Config). **Als Production aktivieren** wirkt sofort für die nächste `/detect`-Anfrage, ein Neustart ist nicht nötig. Die vorherige Production-Version wird archiviert und kann jederzeit wieder aktiviert werden (Rollback). In der Datenbank stellt ein partieller Unique-Index sicher, dass es höchstens ein Production-Modell gibt.

## API

Vollständige Dokumentation: `/api/v1/docs` (Swagger UI) bzw. `/api/v1/openapi.json`.

```bash
curl -s -X POST http://localhost:8080/api/v1/detect \
  -F image=@kamera.jpg \
  -F confidence=0.3 \
  -F input_size=1536x864 \
  -F model=production            # optional: production | candidate | model-0003
```

```json
{
  "image": { "width": 1920, "height": 1080 },
  "model": { "version": "model-0003", "status": "production", "input_width": 1536, "input_height": 864 },
  "inference_ms": 312.4,
  "detections": [
    { "class": "person", "confidence": 0.972, "bbox": { "x1": 452, "y1": 181, "x2": 611, "y2": 793 } }
  ]
}
```

* Das Bild wird **nicht gespeichert**.
* Boxen sind immer Pixelkoordinaten des **Originalbildes**, unabhängig von der Modellauflösung.
* Defaults: aktives Production-Modell, `1536x864`, Confidence `0.25` (alles über die Settings änderbar).
* `inference_ms` umfasst Letterboxing, Inferenz und Post-Processing.

Python:

```python
import httpx
with open("kamera.jpg", "rb") as f:
    r = httpx.post("http://localhost:8080/api/v1/detect", files={"image": f}, data={"confidence": "0.3"})
for d in r.json()["detections"]:
    print(d["class"], d["confidence"], d["bbox"])
```

Weitere Endpunkte (Auszug):

| Methode & Pfad | Zweck |
|----------------|-------|
| `POST /api/v1/images` | Trainingsbilder hochladen (multipart, mehrere `files`) |
| `GET /api/v1/images?status=unlabeled&negative=false` | Bilder auflisten |
| `GET/PUT /api/v1/images/{id}/annotations` | Annotationen lesen / komplett ersetzen (`[]` = negatives Bild); `type`: `positive` oder `hard_negative` (+ `source_confidence`, `source_model`) |
| `POST /api/v1/images/{id}/detect` | Modelltest auf gespeichertem Bild |
| `POST /api/v1/batch-tests`, `GET /api/v1/batch-tests[/{id}]`, `POST …/{id}/cancel` | Batch-Test starten, Fortschritt, Abbruch |
| `GET /api/v1/images?has_suggestions=true` | Bilder mit Vorschlägen (Detail: Feld `suggestion`) |
| `POST /api/v1/training/runs` | Training starten |
| `GET /api/v1/training/runs/{id}` / `…/log` / `POST …/cancel` | Status, Log, Abbruch |
| `GET /api/v1/models`, `POST /api/v1/models/{version}/activate` | Modelle, Aktivierung/Rollback |
| `POST /api/v1/models/bootstrap?base_model=rtmdet-m-coco` | COCO-Basismodell einer Größe (neu) importieren |
| `GET /api/v1/training/base-models` | wählbare Basismodelle (COCO-Größen und eigene Versionen) |
| `GET/POST /api/v1/classes`, `PATCH/DELETE /api/v1/classes/{name}`, `PUT /api/v1/classes/order` | Klassen verwalten |
| `GET /api/v1/training/eligibility?classes=a,b` | verwendbare Bilder für eine Klassenauswahl |
| `GET/PUT /api/v1/settings` | Einstellungen |

## Funktionsweise im Detail

### Klassen

Die Klassen werden in der Anwendung unter **Klassen** verwaltet (Tabelle `detection_classes`). Ausgeliefert werden:

| Name | Anzeigename | COCO-Quellklassen |
|------|-------------|-------------------|
| `person`  | Person   | person |
| `bicycle` | Fahrrad  | bicycle |
| `vehicle` | Fahrzeug | car, motorcycle, bus, truck |

Züge und Schienenfahrzeuge (`train`) werden bewusst **nicht** als `vehicle` behandelt.

* **Name** ist die feste Kennung. Er steht in Annotationen, API-Antworten (`"class"`) und Modellversionen und ist deshalb nicht änderbar (`a–z`, `0–9`, `_`). Anzeigename, Farbe, Reihenfolge (Tasten 1–9) und COCO-Mapping sind jederzeit änderbar.
* **Jede Modellversion speichert ihre eigene Klassenliste** (`class_names`). `/detect` liefert immer die Klassen des verwendeten Modells, auch wenn die Konfiguration inzwischen anders aussieht.
* **Neue Klasse, z. B. „Batterie“:** Bereits annotierte Bilder wurden nicht auf sie geprüft. Jedes Bild speichert daher, für welche Klassen es geprüft wurde (`images.reviewed_classes`, gesetzt beim Speichern). Ein Training verwendet nur Bilder, die für **alle** Klassen des Laufs geprüft sind; die übrigen erscheinen unter Annotation → „Prüfen“. So lernt das Modell ungeprüfte Objekte nicht als Hintergrund. Für die bisherigen Klassen bleiben die Bilder weiter nutzbar.
* **Klassen pro Trainingslauf:** Im Trainingsdialog lassen sich Klassen auswählen, z. B. für ein separates Modell nur mit `battery` und `ladder_type`. Boxen anderer Klassen gelten in diesem Lauf als Hintergrund. Der Dialog zeigt, wie viele Bilder für die Auswahl verwendbar sind.
* **Deaktivieren** blendet eine Klasse in Annotation und Training aus, die Boxen bleiben erhalten. Löschen geht nur, solange die Klasse keine Annotationen hat. Mindestens eine Klasse muss aktiv bleiben.

Die **COCO-Quellklassen** sind optional und werden verwendet

1. für das importierte COCO-Modell. Es enthält alle aktiven Klassen *mit* Mapping; der Score einer Klasse ist das Maximum der Scores der zugeordneten COCO-Klassen, direkt im exportierten Graphen.
2. zur Initialisierung des Klassifikationskopfs beim Training: pro Klasse aus dem Basismodell, falls dort per Name vorhanden (Weitertraining), sonst als Mittelwert der zugeordneten COCO-Klassen, sonst zufällig wie bei RTMDet (Klassen ohne COCO-Entsprechung). Welche Variante gewählt wurde, steht im Log und in den Modelldetails.

Nach einer Mapping-Änderung unter „Modelle“ das COCO-Basismodell neu importieren (oder `python3 scripts/bootstrap-model.py --url http://localhost:8080`).

### Hard Negatives

Eine Annotation hat den Typ `positive` (echtes Objekt) oder `hard_negative` (Region, die ein Modell fälschlich als `class` erkannt hat):

```json
{ "type": "hard_negative", "class": "person", "x1": 100, "y1": 80, "x2": 140, "y2": 150,
  "source": "prediction", "source_confidence": 0.40, "source_model": "model-0003" }
```

Hard Negatives werden **nicht** als zusätzliche Klasse (etwa `not_person`) trainiert, und es gibt keinen eigenen Loss. Stattdessen:

1. **Training:** Das Originalbild wird normal verwendet, ohne Box an dieser Stelle. Für jedes Hard Negative eines *Trainingsbildes* erzeugt der Snapshot zusätzlich einen Ausschnitt `images/hn_<id>.jpg`: Box × Kontextfaktor (Standard 3) je Seite, auf 16:9 erweitert, mindestens 25 % der Bildbreite. Die Mindestgröße verhindert, dass MMDetection winzige Ausschnitte beim Skalieren auf die Modellauflösung stark vergrößert und die Struktur so in einem unrealistischen Maßstab gelernt wird. Der Ausschnitt enthält keine Box für die falsche Erkennung. Echte annotierte Objekte darin werden auf Ausschnittkoordinaten transformiert und geclippt. Jeder Ausschnitt wird mehrfach in `train.json` aufgenommen (Oversampling, Standard 3×). RTMDet lernt so über den normalen Background-Loss, dass diese Struktur kein `person` ist.
2. **Regressionstest nach jedem Training:** Für alle Hard Negatives der Trainingsklassen (Trainings- und Validierungsbilder) wird geprüft, ob das neue Modell dort wieder dieselbe Klasse erkennt (Confidence ≥ `eval_confidence`, IoU ≥ 0.5). Gespeichert werden pro Klasse Anzahl, „weiterhin falsch erkannt“ und HN-FP-Rate, gesamt und separat nur für Validierungsbilder (die das Modell nicht als Crop gesehen hat).
3. **Fairer Vergleich:** Zusätzlich wird das aktuelle Production-Modell auf denselben Validierungsbildern und Hard Negatives ausgewertet. Die UI zeigt pro Klasse die Deltas für Recall, Precision, mAP und HN-FP-Rate und warnt, wenn ein Modell weniger Fehlalarme hat, aber auch weniger echte Objekte findet (Recall-Rückgang > 2 Prozentpunkte). Ein Modell gilt also nicht schon deshalb als besser, weil es generell weniger erkennt.

Einstellungen (unter **Einstellungen**): `hard_negative_context_factor`, `hard_negative_min_crop_fraction`, `hard_negative_oversample` (0 = keine Crops, nur Regressionstest). Bei sehr vielen Hard Negatives im Verhältnis zu den Originalbildern das Oversampling reduzieren und auf den Recall im Vergleich achten.

### Bildauflösung & Letterboxing

Das Originalbild wird mit erhaltenem Seitenverhältnis auf die Modellauflösung skaliert (`scale = min(W/w, H/h)`), oben links platziert und rechts/unten mit dem Wert 114 aufgefüllt. Das ist dieselbe Konvention wie MMDetections `Resize(keep_ratio=True)` + `Pad` im Training. 16:9-Bilder auf `1536x864` brauchen kein Padding. Modellauflösungen müssen Vielfache von 32 sein. Die Rückrechnung der Boxen geschieht durch Division durch `scale` mit anschließendem Clipping auf das Originalbild (`common/odcore/geometry.py`). Die Annotationen werden immer in Originalpixeln gespeichert. Hinweis: Hochformatbilder werden bei der Inferenz korrekt behandelt, im Training (MMDetection-`Resize`) sind aber Querformatbilder vorgesehen.

### Inferenz (API)

Der ONNX-Export enthält Normalisierung, Prior-Erzeugung und Box-Dekodierung und hat dynamische H/W. Ausgaben sind `boxes [1,N,4]` (xyxy in Input-Pixeln) und `scores [1,N,C]`. Die API lädt das OpenVINO-IR einer Version einmalig aus S3, setzt per `reshape` einen **statischen Input-Shape** (z. B. `[1, 3, 864, 1536]`), kompiliert und cacht das Ergebnis pro *(Version, Auflösung)* (LRU, `COMPILED_MODEL_CACHE_SIZE`, zusätzlich OpenVINO-Blob-Cache im Volume `model-cache`). Die klassenweise NMS (IoU 0.6) läuft in numpy. Gemessen: ca. 310 ms reine Inferenz bei 1536×864 auf einem i9-12900H unter WSL2, ca. 9 ms Vorverarbeitung.

Beim Export wird das OpenVINO-Modell gegen PyTorch verifiziert (max. Score-Abweichung ~1e-5, Box-Abweichung < 0.05 px). Bei Abweichungen schlägt das Training fehl, statt ein fehlerhaftes Modell zu registrieren.

### Dataset-Snapshots

Bei jedem Training erzeugt der Trainer aus PostgreSQL und S3 einen Snapshot unter `s3://datasets/<training-run-id>/`:

```
manifest.json            Bild-IDs, SHA-256, Split, Quell-Keys, Statistik
annotations/train.json   COCO Detection Format (Kategorien 1..N in der Klassenreihenfolge des Laufs)
annotations/val.json
images/<sha256>.<ext>    Kopien der Bilder (bleiben erhalten, auch wenn Bilder später gelöscht werden)
```

* Zusätzlich: `annotations/hard_negatives.json` (alle Hard Negatives des Snapshots) und `images/hn_<id>.jpg` (Hard-Negative-Ausschnitte, siehe oben).
* Es werden alle Bilder mit Status `labeled` verwendet, die für alle Klassen des Laufs geprüft sind, **inklusive negativer Bilder ohne Boxen** (in der Trainings-Pipeline auch über `filter_empty_gt=False`, `allow_negative_crop=True` usw.).
* Der Split (`train`/`validation`, Default 85/15) wird beim ersten Labeln deterministisch aus dem Bild-Hash bestimmt und am Bild **persistiert**. Er wird nie neu gewürfelt, auch nicht bei geändertem Validierungsanteil. Manuelles Umsetzen ist per `PATCH /api/v1/images/{id}` möglich.
* Der Snapshot entsteht beim **Start** des Laufs (nicht beim Einreihen).

### Training

* Modell: RTMDet-tiny/S/M (`rtmdet_<größe>_8xb32-300e_coco.py` aus MMDetection 3.3.0), initialisiert mit dem COCO-Checkpoint der Größe bzw. dem gewählten Basismodell, `num_classes` = Anzahl Klassen des Laufs, BN statt SyncBN (Single-GPU).
* Pipeline wie RTMDet (CachedMosaic, RandomResize, RandomCrop, HSV, Flip, CachedMixUp), angepasst auf die gewählte Auflösung. In den letzten ~15 % der Epochen läuft sie ohne Mosaic/MixUp (`PipelineSwitchHook`), dazu EMA.
* Optimizer AdamW. Ohne Angabe gilt `LR = 0.00025 × Batch/4` (Fine-Tuning) mit linearem Warm-up und Cosine-Decay. Auf der GPU wird mit AMP trainiert.
* Validierung jede Epoche (bis 50 Epochen). Exportiert wird der beste Checkpoint nach COCO-mAP (EMA-Gewichte).
* Jeder Job läuft in einem eigenen Prozess. Das gibt GPU-Speicher zuverlässig frei, isoliert Abstürze und ermöglicht den Abbruch.
* Gespeichert pro Version unter `s3://models/<version>/`: `checkpoint.pth`, `model.onnx`, `openvino/model.{xml,bin}`, `config.py`, `metrics.json`. Das vollständige Log liegt unter `training-runs/<id>/train.log`.

### Metriken

Ausgewertet wird das **exportierte OpenVINO-Modell** auf dem Validierungssplit, mit exakt der Vor- und Nachverarbeitung der API:

* **mAP50, mAP50-95** (COCO-Protokoll via pycocotools): gesamt, pro Klasse und pro Boxgröße (klein < 32², mittel < 96², groß; Fläche in Originalpixeln), dazu mAP für kleine Objekte pro Klasse.
* **Precision / Recall** bei Confidence ≥ `eval_confidence` (Default 0.25) und IoU 0.5 mit greedy 1:1-Matching: gesamt, pro Klasse, pro Boxgröße, inklusive TP/FP/FN.
* **Hard-Negative-Regressionstest** pro Klasse und der **Vergleich mit dem Production-Modell** (siehe [Hard Negatives](#hard-negatives)).
* Zusätzlich der Verlauf der MMDetection-Validierung je Epoche.

## Datenmodell

| Tabelle | Wichtigste Felder |
|---------|-------------------|
| `images` | `s3_object_key`, `sha256` (unique), `width`, `height`, `annotation_status` (`unlabeled`/`labeled`), `dataset_split`, `reviewed_classes`, `created_at`, `updated_at` |
| `annotations` | `image_id`, `class_name`, `x1`, `y1`, `x2`, `y2` (Originalpixel), `type` (`positive`/`hard_negative`), `source` (`manual`/`prediction`), `source_confidence`, `source_model` |
| `detection_classes` | `name` (unique, fest), `label`, `color`, `coco_classes`, `sort_order`, `active` |
| `training_runs` | `status`, `base_model_id`, `class_names`, `dataset_snapshot`, `input_width/height`, `epochs`, `batch_size`, `learning_rate`, `started_at`, `finished_at`, `progress_json`, `metrics_json`, `log`, `error` |
| `model_versions` | `version`, `status`, `kind`, `checkpoint_key`, `onnx_key`, `openvino_key`, `config_key`, `input_width/height`, `class_names`, `metrics_json`, `dataset_snapshot`, `training_run_id`, `created_at`, `activated_at` |
| `prediction_batches` | `status`, `model_ref`, `model_version`, `input_width/height`, `confidence`, `scope`, `total`, `processed`, `detections`, `failed_images` |
| `image_suggestions` | `image_id` (unique), `batch_id`, `model_version`, `confidence`, `detections_json` |
| `settings` | `key`, `value` (JSON) |

Migrationen: Alembic (`backend/alembic`), werden beim Start der API automatisch ausgeführt. Die ORM-Modelle liegen im gemeinsamen Paket `common/odcore`, das API und Trainer verwenden.

## Projektstruktur

```
docker-compose.yml, docker-compose.gpu.yml, docker-compose.dev.yml, .env.example, Makefile
common/odcore/        gemeinsamer Code: Klassen, Geometrie/Letterboxing, ORM, S3, OpenVINO-Detector
backend/              FastAPI (app/api/routes, core, db, schemas, services), Alembic, requirements.lock
trainer/              RQ-Worker, Snapshot, Training, Evaluation, ONNX/OpenVINO-Export, rtmdet/ Config
frontend/             Vue 3 + Vite + Quasar + vue-konva
inference-server/     eigenständiger Produktiv-Stack: Erkennungs-API, Modell per API austauschbar (siehe inference-server/README.md)
infrastructure/garage garage.toml, idempotentes init.sh (Admin-API)
scripts/              generate-env.sh, wait-for-services.sh, bootstrap-model.py
tests/                backend/ (Geometrie, Annotation, Detection-API, Modelle), trainer/, integration/
```

## Produktivsystem (Inference-Server)

`inference-server/` ist ein eigener Stack (eigenes Dockerfile und `docker-compose.yml`, Image `swarnat/rtmdet-detection`, gebaut mit `make inference-server`) für den produktiven Einsatz:
`POST /api/v1/detect` prüft ein Bild mit dem aktiven Modell und liefert Erkennungen und Kategorien als JSON
(Mindest-Confidence 0.15). Das Image enthält kein Modell; es wird von hier aus übertragen:

1. Inference-Server starten (siehe `inference-server/README.md`), dort `MODEL_UPLOAD_KEY` setzen.
2. Hier unter **Einstellungen → Produktivsystem** URL und denselben Access Key eintragen (der Key wird nach dem
   Speichern nicht mehr angezeigt), „Verbindung testen“.
3. Auf der Seite **Modelle** beim gewünschten Modell „Ausrollen“ (Wolken-Symbol). Das Produktivsystem prüft das Modell
   und ersetzt dann sein aktives Modell; die Spalte Status zeigt „live“ beim dort aktiven Modell.

API: `GET /api/v1/deployment` (Status des Produktivsystems), `POST /api/v1/deployment {"version": "model-0005"}`.
Der Production-Status hier im System ist davon unabhängig.

## Tests

```bash
# Backend: Box-Konvertierung, Letterboxing, Detection-API mit echtem OpenVINO-Modell, Modellwechsel
docker compose run --rm --no-deps api python -m pytest -q

# Trainer: COCO-Snapshot inkl. Negativbilder, Precision/Recall, MMDetection-Config
docker compose run --rm --no-deps trainer python -m pytest -q /srv/tests/trainer

# Inference-Server (Produktivsystem)
make inference-server-test

# Integration gegen den laufenden Stack
docker compose run --rm --no-deps -e OD_BASE_URL=http://frontend api python -m pytest -q /srv/tests/integration
```

## Entwicklung

* **Dev-Modus mit automatischem Neuladen** (`docker-compose.dev.yml`): API (`uvicorn --reload`, Quellcode aus `backend/` und `common/` gemountet) und Frontend (Vite-Dev-Server mit Hot Reload statt nginx-Build) übernehmen Dateiänderungen sofort, ohne Image-Build. Gleiche Ports wie im normalen Stack.
  ```bash
  # dauerhaft: in .env die Datei an COMPOSE_FILE anhängen
  COMPOSE_FILE=docker-compose.yml:docker-compose.gpu.yml:docker-compose.dev.yml
  docker compose up -d
  # zurück zum normalen Stack: Eintrag wieder entfernen, dann
  docker compose up -d --build
  ```
  Neue Alembic-Migrationen laufen nur beim Containerstart (`docker compose restart api`). Der Trainer lädt nicht automatisch neu (`docker compose up -d --build trainer`). Werden Änderungen nicht erkannt (z. B. Quellcode auf einem Windows-Laufwerk), `VITE_USE_POLLING=true` in `.env` setzen.
* Frontend mit Hot Reload ohne Docker: `cd frontend && npm ci && VITE_API_PROXY=http://localhost:8000 npm run dev`
* Python-Abhängigkeiten: direkte Abhängigkeiten in `pyproject.toml` (exakt gepinnt), vollständiger Satz in `requirements.lock` (wird in den Dockerfiles als Constraints-Datei verwendet). Node: `package.json` (exakt) + `package-lock.json`.
* Versionen: Python 3.11 (API), Python 3.10 + PyTorch 2.1.2/CUDA 12.1 + MMCV 2.1.0 + MMDetection 3.3.0 + MMEngine 0.10.5 (Trainer), OpenVINO 2024.6 (beide), Vue 3.5, Quasar 2.17, Vite 6, Konva 9.

## Lizenzen & Herkunft

> Keine Rechtsberatung. Vor einem kommerziellen Einsatz die Lizenzen selbst prüfen.

### Code

* **Dieses Projekt:** Für den projekteigenen Code ist noch keine Lizenz festgelegt (keine `LICENSE`-Datei). Das bestimmt der Rechteinhaber.
* **Wesentliche Abhängigkeiten:** MMDetection, MMEngine, MMCV (Apache-2.0), PyTorch (BSD-3-Clause), OpenVINO (Apache-2.0), ONNX (Apache-2.0), FastAPI/Starlette/Pydantic/SQLAlchemy (MIT), Alembic (MIT), RQ (BSD-2-Clause), pycocotools (BSD-2-Clause), OpenCV (Apache-2.0), Vue/Quasar/Pinia/Vue Router/Vite/Konva/vue-konva (MIT).
* **Dienste (unverändert, als eigene Container):** Garage (AGPL-3.0), PostgreSQL (PostgreSQL License), Redis 7.2 (BSD-3-Clause; bewusst 7.2, da Redis ab 7.4 unter RSALv2/SSPLv1 steht).

### Modell & Trainingsdaten (getrennt vom Code zu betrachten)

* **Base-Checkpoints** aus dem MMDetection-v3-Model-Zoo von OpenMMLab (`https://download.openmmlab.com/mmdetection/v3.0/rtmdet/…`, SHA-256-Präfix im Dateinamen, wird beim Download geprüft; Katalog in `common/odcore/architectures.py`):
  `rtmdet_tiny_8xb32-300e_coco_20220902_112414-78e30dcc.pth`,
  `rtmdet_s_8xb32-300e_coco_20220905_161602-387a891e.pth` (SHA-256 `387a891e157cf0ab57d76b3ffc17bf77247089d672532427930b3140f9e789d6`),
  `rtmdet_m_8xb32-300e_coco_20220719_112220-229f527c.pth`. OpenMMLab veröffentlicht die Gewichte im MMDetection-Repository, das unter Apache-2.0 steht. Eine separate Lizenz nur für die Gewichte ist dort nicht ausgewiesen.
* **Trainingsdaten des Checkpoints:** COCO 2017 (train). Die COCO-Annotationen stehen unter CC BY 4.0. Die Bilder stammen von Flickr, für sie gelten die jeweiligen Flickr-Lizenzen bzw. Nutzungsbedingungen. Der CSPNeXt-Backbone wurde von OpenMMLab zuvor auf ImageNet-1k vortrainiert, dessen Nutzungsbedingungen auf nicht-kommerzielle Forschung ausgelegt sind. Ob und wie sich das auf abgeleitete Gewichte auswirkt, ist rechtlich nicht abschließend geklärt.
* **Eigene Modelle** (`model-0002`, …) sind von diesem Checkpoint abgeleitet und zusätzlich mit den eigenen Kamerabildern trainiert. Für diese Bilder gelten die Rechte bzw. Datenschutzanforderungen des Betreibers (Personen auf Kamerabildern sind personenbezogene Daten).
* Die COCO-Checkpoints werden zur Laufzeit heruntergeladen und im Bucket `models/base/` abgelegt. Sie sind nicht Teil des Repositorys.

## Troubleshooting

* `docker compose logs -f trainer` zeigt Training und Bootstrap, `docker compose logs -f api` die API.
* **„no production model is active“ (503):** Der Bootstrap lief noch nicht oder ist fehlgeschlagen. Unter „Modelle“ → „COCO-Basismodell importieren“ und anschließend aktivieren.
* **CUDA out of memory:** Batch Size oder Auflösung reduzieren. RTMDet-S braucht bei 1536×864 und Batch 4 etwa 3,3 GB VRAM.
* **Dataloader-Fehler wegen Shared Memory:** `TRAINER_SHM_SIZE` erhöhen oder Loader-Worker reduzieren.
* **Port belegt:** `FRONTEND_PORT` / `API_PORT` in der `.env` anpassen.
* Garage-Init erneut ausführen (idempotent): `docker compose run --rm garage-init`.
