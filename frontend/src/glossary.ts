// Plain-language explanations for the "?" icons (HelpIcon term="…"), no technical knowledge assumed
export const GLOSSARY = {
  precision:
    'Precision (Genauigkeit): Wie viele der gefundenen Objekte wirklich stimmen. 90 % heißt: von 10 Treffern sind 9 richtig, 1 ist ein Fehlalarm. ' +
    'Hoch = wenige Fehlalarme.',
  recall:
    'Recall (Trefferquote): Wie viele der tatsächlich vorhandenen Objekte das Modell findet. 90 % heißt: von 10 echten Objekten werden 9 gefunden, 1 wird übersehen. ' +
    'Hoch = wenig übersehen.',
  mAP50:
    'mAP50: Gesamtnote für die Erkennung (0–100 %), die Fehlalarme und übersehene Objekte zusammen bewertet. ' +
    'Eine Erkennung zählt als richtig, wenn der Rahmen das Objekt mindestens zur Hälfte trifft. Höher ist besser – ab etwa 80 % gilt ein Modell als gut.',
  mAP5095:
    'mAP50-95: Wie mAP50, aber strenger – die Rahmen müssen das Objekt zusätzlich sehr genau umschließen. ' +
    'Der Wert ist deshalb immer deutlich niedriger als mAP50. Er zeigt vor allem, wie exakt die Rahmen sitzen.',
  mAPSmall:
    'mAP50-95 klein: Die strenge Gesamtnote nur für sehr kleine Objekte (weniger als 32 × 32 Pixel im Originalbild). ' +
    'Kleine Objekte sind am schwersten zu erkennen, deshalb ist dieser Wert meist niedrig.',
  tpFpFn:
    'TP / FP / FN: Anzahl richtiger Treffer (TP), Fehlalarme (FP – etwas erkannt, wo nichts ist) und übersehener Objekte (FN – vorhanden, aber nicht erkannt) ' +
    'auf den Prüfbildern.',
  boxSize:
    'Boxgröße: Die Ergebnisse getrennt nach Objektgröße im Originalbild – klein (unter 32 × 32 Pixel), mittel (bis 96 × 96 Pixel) und groß. ' +
    'So sieht man, ob das Modell z. B. nur bei weit entfernten Objekten Probleme hat.',
  hardNegatives:
    'Hard Negatives (HN): Bekannte Fehlalarme – Stellen, an denen ein Modell fälschlich etwas erkannt hat (z. B. ein Schild als Person). ' +
    'Sie werden gespeichert, damit neue Modelle diesen Fehler nicht wiederholen, und nach jedem Training überprüft.',
  hnStillDetected:
    'Weiterhin falsch erkannt: Wie viele der bekannten Fehlalarme das neue Modell trotzdem noch macht. Weniger ist besser.',
  hnFpRate:
    'HN-FP-Rate: Anteil der bekannten Fehlalarme, die das Modell immer noch macht. 0 % = keinen davon wiederholt. Niedriger ist besser.',
  delta:
    'Δ (Differenz): Um wie viele Prozentpunkte das neue Modell besser (grün) oder schlechter (rot) ist als das aktuelle Production-Modell.',
  loss:
    'Loss: Fehlerwert während des Lernens. Er sollte im Lauf des Trainings sinken. Wichtig ist der Verlauf, nicht die genaue Zahl.',
  epoch:
    'Epoch: Ein kompletter Durchgang durch alle Trainingsbilder. Bei 30 Epochs sieht das Modell jedes Bild 30-mal.',
  valChart:
    'Nach jeder Epoche wird das Modell an Prüfbildern getestet, die es nicht zum Lernen benutzt. ' +
    'Die Linien zeigen, wie gut es dabei war – steigen sie, lernt das Modell dazu. Die Farben zeigen grob die Qualität (rot = schwach, orange = mittel, grün = gut).',
  status:
    'Status eines Modells: „production“ ist das Modell, das gerade für alle Erkennungen benutzt wird (immer genau eins). ' +
    '„candidate“ ist ein neues Modell, das noch geprüft und bei Bedarf aktiviert werden kann. „archived“ ist ein früheres Modell, das jederzeit wieder aktiviert werden kann.',
  runStatus:
    'Status des Trainings: „queued“ = wartet auf den Start, „running“ = läuft gerade, „completed“ = fertig (ein neues Modell wurde erstellt), „failed“ = abgebrochen oder fehlgeschlagen.',
  architecture:
    'Architektur: Bauart und Größe des Modells (RTMDet tiny, S oder M). Größere Modelle erkennen genauer, brauchen aber mehr Rechenzeit.',
  kind:
    'Art: „COCO“ = fertiges Modell aus einem öffentlichen Datensatz, nicht mit deinen Bildern trainiert. „trainiert“ = mit deinen annotierten Bildern trainiert.',
  base:
    'Base (Basismodell): Das Modell, von dem das Training ausgegangen ist – ein allgemeines COCO-Modell oder ein eigenes, früher trainiertes Modell.',
  resolution:
    'Auflösung: Bildgröße (Breite × Höhe in Pixeln), auf die Bilder für das Modell gebracht werden. Größer erkennt kleine Objekte besser, ist aber langsamer.',
  confidence:
    'Confidence (Sicherheit): Wie sicher sich das Modell bei einer Erkennung sein muss, damit sie angezeigt wird. ' +
    'Niedriger Wert = mehr Treffer, aber auch mehr Fehlalarme. Höherer Wert = weniger, aber sicherere Treffer.',
  nmsIou:
    'NMS-IoU: Regelt, wann zwei sich überlappende Rahmen als dasselbe Objekt gelten und zu einem zusammengefasst werden. ' +
    'Niedriger Wert = Überlappungen werden stärker zusammengefasst. Normalerweise nicht ändern.',
  datasetSnapshot:
    'Dataset-Snapshot: Eine eingefrorene Kopie der Bilder und Annotationen, mit denen dieses Training gemacht wurde. ' +
    'So lässt sich später genau nachvollziehen, womit das Modell gelernt hat.',
  split:
    'Split (train / val): Jedes annotierte Bild ist fest entweder ein Trainingsbild (train – damit lernt das Modell) oder ein Prüfbild ' +
    '(val – damit wird das Modell getestet, ohne dass es diese Bilder vorher gesehen hat).',
  negative:
    'Negativ: Ein annotiertes Bild ohne Objekte. Solche Bilder sind wichtig – das Modell lernt daran, wo nichts zu erkennen ist.',
  needsReview:
    'Nachprüfen: Das Bild wurde schon annotiert, aber noch nicht auf eine später hinzugefügte Klasse geprüft. ' +
    'Erst nach dem Prüfen wird es für Trainings mit dieser Klasse benutzt.',
  batchTest:
    'Batch-Test: Ein Modell sucht einmal auf vielen Bildern nach Objekten und speichert die Treffer als Vorschläge. ' +
    'Beim Annotieren kannst du die Vorschläge dann übernehmen statt alles selbst einzuzeichnen.',
  predictions:
    'Predictions: Was das Modell auf diesem Bild erkannt hat (gestrichelte Rahmen). Du kannst sie übernehmen oder als Fehlalarm (Hard Negative) markieren.',
  cocoMapping:
    'COCO-Mapping: Welche Objektarten des öffentlichen COCO-Datensatzes zu deiner Klasse gehören (z. B. car, bus und truck → Fahrzeug). ' +
    'Damit kann ein Modell die Klasse schon vor dem ersten eigenen Training erkennen und lernt danach schneller.',
  headInit:
    'Initialisierung Klassifikationskopf: Womit das Modell beim Training für jede Klasse gestartet ist – mit Vorwissen aus passenden COCO-Klassen ' +
    'oder ohne Vorwissen (zufällig).',
  artifacts:
    'Artefakte: Die Dateien des Modells zum Herunterladen. ONNX und OpenVINO sind Formate zum Einsetzen des Modells in anderen Programmen, ' +
    'der Checkpoint wird zum Weitertrainieren gebraucht.',
  validationRatio:
    'Validierungsanteil: Welcher Anteil neu annotierter Bilder als Prüfbild (val) statt als Trainingsbild verwendet wird, z. B. 0.15 = 15 %.',
  evalConfidence:
    'Confidence für Precision/Recall: Ab welcher Sicherheit eine Erkennung bei der Bewertung eines Modells als Treffer zählt.',
  hnCrops:
    'Einstellungen dafür, wie bekannte Fehlalarme (Hard Negatives) ins Training einfließen: Kontextfaktor = wie viel Umgebung um die Stelle mitgenommen wird, ' +
    'Mindestbreite = wie klein der Ausschnitt höchstens werden darf, Oversampling = wie oft er im Training wiederholt wird (0 = gar nicht, nur Prüfung).',
  hn: 'HN = Hard Negatives: bekannte Fehlalarme, also Stellen, an denen ein Modell fälschlich etwas erkannt hat.',
  productionSystem:
    'Produktivsystem: Ein separater Server, der im laufenden Betrieb Bilder prüft. Er hat immer genau ein aktives Modell, ' +
    'das von hier aus mit „Ausrollen“ übertragen wird. Unabhängig davon, welches Modell hier „production“ ist.',
  deploymentUrl:
    'Adresse des Produktivsystems, z. B. https://erkennung.firma.de oder http://10.0.0.5:8100 – ohne /api/v1 am Ende.',
  deploymentKey:
    'Zugangsschlüssel, mit dem sich dieses System beim Produktivsystem ausweist. Muss dort als MODEL_UPLOAD_KEY eingetragen sein ' +
    '(mindestens 16 Zeichen). Aus Sicherheitsgründen wird er nach dem Speichern nicht mehr angezeigt – leer lassen bzw. Sternchen stehen lassen, um ihn zu behalten.',
  deploy:
    'Ausrollen: Überträgt dieses Modell auf das Produktivsystem. Dort wird es zuerst geprüft und ersetzt dann sofort das bisher aktive Modell. ' +
    'Schlägt die Prüfung fehl, bleibt das alte Modell aktiv.',
} as const

export type GlossaryTerm = keyof typeof GLOSSARY
