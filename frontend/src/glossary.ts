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
  ignoreRegion:
    'Ignorierter Bereich: Eine Stelle, die weder Objekt noch Hintergrund ist (z. B. ein verdecktes, abgeschnittenes oder nicht eindeutiges Objekt). ' +
    'Das Training bestraft dort keine Erkennung, und in der Auswertung zählt eine Erkennung dort weder als Treffer noch als Fehlalarm. ' +
    'Der Bereich gilt für alle Klassen, die gewählte Klasse spielt dafür keine Rolle.',
  reflected:
    'Spiegelung: Das Objekt ist nur eine Spiegelung (Fenster, Spiegel, Pfütze …). Die Markierung ändert das Training nicht, ' +
    'sie dient dazu, diese Boxen später getrennt zu betrachten.',
  hnStillDetected:
    'Weiterhin falsch erkannt: Wie viele der bekannten Fehlalarme das neue Modell trotzdem noch macht. Weniger ist besser.',
  hnFpRate:
    'HN-FP-Rate: Anteil der bekannten Fehlalarme, die das Modell immer noch macht. 0 % = keinen davon wiederholt. Niedriger ist besser.',
  delta:
    'Δ (Differenz): Um wie viele Prozentpunkte das neue Modell besser (grün) oder schlechter (rot) ist als das aktuelle Production-Modell. ' +
    'Bei wenigen Validierungsboxen („wenig Daten“) bleibt die Zahl grau: Dann kann schon eine einzelne Box den Unterschied ausmachen.',
  loss:
    'Loss: Fehlerwert während des Lernens. Er sollte im Lauf des Trainings sinken. Wichtig ist der Verlauf, nicht die genaue Zahl.',
  epoch:
    'Epoch: Ein kompletter Durchgang durch alle Trainingsbilder. Bei 30 Epochs sieht das Modell jedes Bild 30-mal.',
  valChart:
    'Nach jeder Epoche wird das Modell an Prüfbildern getestet, die es nicht zum Lernen benutzt. ' +
    'Die Linien zeigen, wie gut es dabei war – steigen sie, lernt das Modell dazu. „Gesamt“ ist der Mittelwert, dazu gibt es je Klasse eine Linie ' +
    'und gestrichelt je Boxgröße (klein/mittel/groß). Ein Klick auf einen Legendeneintrag blendet die Linie aus oder ein. ' +
    'Die Hintergrundfarben zeigen grob die Qualität (rot = schwach, orange = mittel, grün = gut).',
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
    '(val – damit wird das Modell getestet, ohne dass es diese Bilder vorher gesehen hat). Zugeteilt wird automatisch beim ersten ' +
    'Speichern (Validierungsanteil unter Einstellungen); unter „Bild → Verwendung“ lässt es sich gezielt festlegen, z. B. echte ' +
    'Eindringlinge als Prüfbilder, die das Modell nie trainieren soll.',
  negative:
    'Negativ: Ein annotiertes Bild ohne Objekte. Solche Bilder sind wichtig – das Modell lernt daran, wo nichts zu erkennen ist.',
  needsReview:
    'Nachprüfen: Das Bild wurde schon annotiert, aber noch nicht auf eine später hinzugefügte Klasse geprüft. ' +
    'Erst nach dem Prüfen wird es für Trainings mit dieser Klasse benutzt.',
  batchTest:
    'Batch-Test: Ein Modell sucht einmal auf vielen Bildern nach Objekten und speichert die Treffer als Vorschläge. ' +
    'Beim Annotieren kannst du die Vorschläge dann übernehmen statt alles selbst einzuzeichnen.',
  benchmark:
    'Vergleich auf aktuellem Validierungsset: Die beim Training gespeicherten Metriken gelten für das damalige Validierungsset, das ' +
    'seitdem gewachsen ist – Werte verschiedener Modelle sind so nicht vergleichbar. Hier werden alle nicht archivierten Modelle ' +
    '(Production und Candidates) neu auf denselben, ' +
    'heutigen Validierungsbildern bewertet (exportiertes OpenVINO-Modell, eigene Auflösung, gleiche Confidence wie im Training), ' +
    'inklusive Hard-Negative-Test auf den Validierungsbildern. Läuft im Trainer, nach einem eventuell laufenden Training.',
  annotationReview:
    'Kontrolle: Jede annotierte Box als kleiner Ausschnitt (Box plus 20 Pixel Rand), getrennt nach Klasse – für einen schnellen ' +
    'Überblick, ob alles passt: falsche Klasse, zu große/zu kleine oder verrutschte Boxen, zwei Objekte in einer Box. Die Sortierung ' +
    'nach Größe oder Seitenverhältnis bringt Ausreißer nach vorn. Klick öffnet das Bild zum Korrigieren in einem neuen Tab, danach ' +
    '„Neu laden“. „V“ = Validierungsbild.',
  missed:
    'Nicht erkannt (FN): Annotierte Objekte, für die das Modell bei der eingestellten Confidence keine passende Erkennung ' +
    '(gleiche Klasse, IoU ≥ 0,5) liefert – angegeben als „x von Boxen (Anteil)“; der Anteil ist 100 % − Recall. Bei Personen der ' +
    'schwerste Fehler: ein echter Eindringling ohne Alarm. Weniger ist besser.',
  falseAlarms:
    'Fehlalarme (FP): Erkennungen ohne passende annotierte Box (gleiche Klasse, IoU ≥ 0,5) bei der eingestellten Confidence. ' +
    'Lästig, aber weniger schlimm als ein nicht erkanntes Objekt. Weniger ist besser.',
  benchmarkMissed:
    'Nicht erkannte Personen: Annotierte Personen auf den Validierungsbildern, für die das Modell bei der eingestellten Confidence ' +
    'keine passende Erkennung (IoU ≥ 0,5) liefert (False Negatives). Das ist der schwerste Fehler – ein echter Eindringling ohne Alarm. ' +
    'Alle Modelle werden auf denselben Bildern gezählt, die Zahlen sind direkt vergleichbar. Ein Fehlalarm ist lästig, eine nicht ' +
    'erkannte Person ist ein Sicherheitsproblem.',
  review:
    'Sichtung: Offene Bilder, auf denen ein Batch-Test nichts gefunden hat, nach Kamera gruppiert. Noch nie getestete Bilder fehlen hier ' +
    '(Hinweis oben) – sie gehören zuerst in einen Batch-Test. Jedes Bild folgt ' +
    'dem ähnlichsten; beim Überblenden (Leertaste) wird es mit dem ähnlichsten bekannt leeren Bild derselben Kamera verglichen, sonst mit ' +
    'dem vorherigen. Was dabei auftaucht oder verschwindet, ist ein Kandidat für ein Objekt. N speichert das Bild sofort als negativ (leer), ' +
    'A öffnet es zum Annotieren in einem neuen Tab.',
  duplicates:
    'Duplikate: Feste Kameras liefern viele fast gleiche Bilder, die eine Szene im Training überbetonen würden. Verglichen werden nur leere ' +
    'Bilder – ohne Annotationen und entweder als negativ gespeichert oder ohne Vorschläge im letzten Batch-Test. Gleiche Ansicht, gleiche ' +
    'Helligkeit und keine sichtbare Änderung (Zeitstempel oben wird ignoriert) = Duplikat. Das erste Bild jeder Gruppe bleibt (annotierte ' +
    'zuerst), die übrigen werden markiert und nicht fürs Training verwendet. Bilder mit Objekten oder Vorschlägen werden nie markiert. ' +
    'Die Prüfung läuft automatisch nach jedem Batch-Test. Auf der Seite „Duplikate“ entscheidest du je Bild: behalten (z. B. nützliches ' +
    'Nachtrauschen, bewegte Bäume) oder löschen. Abweichung = größter Blockunterschied zum Original (0 = pixelgleich); die Schwelle ist ' +
    'unter Einstellungen einstellbar.',
  errorAnalysis:
    'Fehleranalyse: Ein Modell läuft über annotierte Bilder; seine Treffer werden mit deinen Boxen verglichen (gleiche Klasse, IoU ≥ 0,5, ' +
    'Confidence ≥ Schwelle – wie bei Precision/Recall des Trainings). Bilder mit Fehlalarmen (False Positives) oder übersehenen Objekten ' +
    '(False Negatives) werden markiert und erscheinen im Filter „Fehlerbilder“. Fehlalarme sind oft fehlende Annotationen – dann übernehmen; ' +
    'echte Fehlalarme als Hard Negative markieren. Nur Klassen, auf die das Bild geprüft wurde. Jede neue Analyse ersetzt die vorherigen Markierungen.',
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
  snapshotRefs:
    'Verwendet in Trainings: In wie vielen Trainingsständen (Modellen) dieses Bild steckt – wie der Link-Zähler einer Datei. ' +
    'Ein Training merkt sich seine Bilder, statt sie zu kopieren. Löschst du ein Bild, das noch verwendet wird, verschwindet es nur aus der ' +
    'Liste; die Datei bleibt, damit nachvollziehbar bleibt, womit die Modelle trainiert wurden. Sie wird automatisch gelöscht, sobald das ' +
    'letzte dieser Modelle gelöscht ist. Fehlgeschlagene oder abgebrochene Trainings zählen nicht.',
  backup:
    'Backup: Eine einzige Datei (.tar) mit allem, was das System ausmacht – Datenbank (Bilder-Verwaltung, Annotationen, Klassen, ' +
    'Einstellungen, Trainingsläufe, Modellverwaltung), alle Bilder, alle Dataset-Snapshots und alle Modelle. Läuft im Hintergrund; ' +
    'du kannst die Seite währenddessen verlassen.',
  restore:
    'Wiederherstellen ersetzt den kompletten aktuellen Stand durch den Stand des Backups. Alles, was danach entstanden ist, geht verloren. ' +
    'Deshalb geht das bewusst nur auf der Kommandozeile: Der Befehl stoppt API und Trainer, prüft die Datei vollständig, stellt alles wieder her ' +
    'und startet das System neu.',
  productionSystem:
    'Produktivsystem: Ein separater Server, der im laufenden Betrieb Bilder prüft. Er hat immer genau ein aktives Modell, ' +
    'das von hier aus mit „Ausrollen“ übertragen wird. Unabhängig davon, welches Modell hier „production“ ist.',
  deploymentUrl:
    'Adresse des Produktivsystems, z. B. https://erkennung.firma.de oder http://10.0.0.5:8100 – ohne /api/v1 am Ende.',
  deploymentKey:
    'Zugangsschlüssel, mit dem sich dieses System beim Produktivsystem ausweist. Muss dort als MODEL_UPLOAD_KEY eingetragen sein ' +
    '(mindestens 16 Zeichen). Aus Sicherheitsgründen wird er nach dem Speichern nicht mehr angezeigt – leer lassen bzw. Sternchen stehen lassen, um ihn zu behalten.',
  clientAnnotator:
    'Kunden-Annotationsdienst: ein eigener Container auf dem Kundenserver (client-annotator/). Dort werden Bilder per ' +
    'Batch-Download geladen, gegen den Inference-Server geprüft und annotiert. Hier „Client-Annotationen einlesen“ holt alle ' +
    'Bilder samt Annotationen ab und löscht sie danach auf dem Kundenserver – dort kann der nächste Batch vorbereitet werden.',
  clientAnnotatorKey:
    'Access Token des Kunden-Annotationsdienstes: muss dort als CLIENT_ACCESS_TOKEN eingetragen sein (mindestens 16 Zeichen). ' +
    'Wird nach dem Speichern nicht mehr angezeigt – Sternchen stehen lassen, um ihn zu behalten.',
  clientInferenceUrl:
    'Adresse des Inference-Servers aus Sicht des Kundenservers, z. B. http://localhost:8100, wenn beide dort laufen. ' +
    'Leer = URL des Produktivsystems. Wird mit „Konfiguration übertragen“ an den Dienst geschickt.',
  deploy:
    'Ausrollen: Überträgt dieses Modell auf das Produktivsystem. Dort wird es zuerst geprüft und ersetzt dann sofort das bisher aktive Modell. ' +
    'Schlägt die Prüfung fehl, bleibt das alte Modell aktiv.',
} as const

export type GlossaryTerm = keyof typeof GLOSSARY
