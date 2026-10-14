<template>
  <q-card flat bordered class="q-mt-md">
    <q-card-section class="row items-center q-gutter-sm">
      <div class="text-h6">Vergleich auf aktuellem Validierungsset<HelpIcon term="benchmark" inline /></div>
      <q-space />
      <q-btn
        color="primary"
        unelevated
        no-caps
        icon="leaderboard"
        :label="benchmark ? 'Neu berechnen' : 'Alle Modelle vergleichen'"
        :loading="starting"
        :disable="running"
        @click="start"
      />
    </q-card-section>

    <q-card-section v-if="benchmark" class="q-pt-none">
      <div class="text-caption text-muted q-mb-sm">
        <template v-if="benchmark.num_images">
          {{ benchmark.num_images }} Validierungsbilder · {{ benchmark.num_boxes }} Boxen · {{ benchmark.num_hard_negatives }} Hard Negatives ·
          Klassen {{ (benchmark.class_names ?? []).map((n) => classes.info(n).label).join(', ') }} ·
        </template>
        Stand {{ fmtDate(benchmark.finished_at ?? benchmark.started_at ?? benchmark.created_at) }}
        <span v-if="confidence != null"> · Precision/Recall bei Confidence ≥ {{ confidence }}, IoU 0,5</span>
      </div>
      <div v-if="running" class="q-mb-sm">
        <div class="text-caption text-secondary">
          {{ benchmark.status === 'queued' ? 'Wartet auf den Trainer (läuft nach einem laufenden Training)…' : `Modell ${benchmark.processed} / ${benchmark.total}` }}
        </div>
        <q-linear-progress :value="benchmark.total ? benchmark.processed / benchmark.total : 0" color="secondary" rounded />
      </div>
      <div v-if="benchmark.status === 'failed'" class="text-negative text-caption mono q-mb-sm">{{ benchmark.error }}</div>

      <!-- missed objects of the focus class: the worst kind of error, shown on its own -->
      <div v-if="missedRanking.length" class="missed q-pa-sm q-mb-md rounded-borders">
        <div class="row items-center q-mb-xs">
          <q-icon name="person_off" color="negative" size="20px" class="q-mr-xs" />
          <div class="text-subtitle2">
            Nicht erkannte {{ focusLabel }}en
            <span class="text-caption text-muted">
              · von {{ focusBoxes }} {{ focusLabel }}en auf den Validierungsbildern, Confidence ≥ {{ confidence ?? '–' }}
            </span>
          </div>
          <HelpIcon term="benchmarkMissed" inline />
        </div>
        <div v-for="m in missedRanking" :key="m.version" class="row items-center no-wrap missed-row">
          <div class="missed-name mono ellipsis">{{ m.version }}</div>
          <div class="col missed-track">
            <div class="missed-bar" :style="{ width: `${missedMax ? (m.missed / missedMax) * 100 : 0}%` }" />
          </div>
          <div class="missed-value" :class="m.missed === missedMin ? 'text-positive text-weight-bold' : m.missed === missedMax && missedMax > missedMin ? 'text-negative text-weight-bold' : ''">
            {{ m.missed }} <span class="text-caption text-muted">({{ fmtPct(m.missed / focusBoxes) }})</span>
          </div>
        </div>
      </div>

      <div class="row items-center q-mb-xs">
        <div class="text-caption text-muted">Sortiert nach nicht erkannten {{ focusLabel }}en – Spaltenkopf klicken zum Umsortieren.</div>
        <q-space />
        <q-toggle v-model="allColumns" dense size="sm" label="Alle Kennzahlen" class="text-caption" />
      </div>
      <q-table
        v-if="rows.length"
        flat
        bordered
        dense
        :rows="rows"
        :columns="visibleColumns"
        row-key="version"
        class="sticky-first"
        :pagination="{ rowsPerPage: 0, sortBy: `missed_${focus}`, descending: false }"
        hide-bottom
      >
        <template #header-cell="props">
          <q-th :props="props" :class="props.col.focus ? 'focus-col text-weight-bold' : ''">
            {{ props.col.label }}
            <q-icon v-if="props.col.help" name="help_outline" size="14px" class="text-muted q-ml-xs">
              <q-tooltip max-width="340px">{{ props.col.help }}</q-tooltip>
            </q-icon>
          </q-th>
        </template>
        <template #body-cell-version="props">
          <q-td :props="props">
            <b>{{ props.row.version }}</b>
            <q-chip dense outline size="sm" :color="statusColor[props.row.status] ?? 'grey-5'" :label="props.row.status" class="q-ml-xs" />
            <div v-if="props.row.error" class="text-negative text-caption">{{ props.row.error }}</div>
            <div v-if="props.row.seen" class="text-warning text-caption">
              <q-icon name="warning" size="14px" /> {{ props.row.seen }} Validierungsbild{{ props.row.seen === 1 ? '' : 'er' }} trainiert
              <q-tooltip max-width="320px">
                Diese Bilder waren im Training dieses Modells Trainingsbilder und wurden später auf Validierung umgestellt.
                Das Modell kennt sie – seine Werte sind dadurch etwas zu gut.
              </q-tooltip>
            </div>
          </q-td>
        </template>
        <!-- props.value is already formatted by the column's format(); the raw number decides the best value -->
        <template #body-cell="props">
          <q-td :props="props" :class="cellClass(props.col, props.row)">
            {{ props.value }}
          </q-td>
        </template>
        <template #body-cell-counts="props">
          <q-td :props="props" class="mono">{{ props.value }}</q-td>
        </template>
      </q-table>
      <div class="text-caption text-muted q-mt-sm">
        Production- und Candidate-Modelle auf denselben, aktuellen Validierungsbildern – jedes in seiner eigenen Auflösung, mit der
        Bewertung des Trainings. Archivierte Modelle werden nicht getestet. Grün = bester Wert der Spalte.
        <span v-if="fewBoxes.length">Wenig Daten (&lt; 30 Boxen): {{ fewBoxes.join(', ') }} – Unterschiede dort sind oft Zufall.</span>
        <span v-if="noBoxes.length"> Ohne Validierungsboxen (nicht bewertbar): {{ noBoxes.join(', ') }}.</span>
      </div>
      <q-expansion-item dense dense-toggle icon="info_outline" label="Was bedeuten die Werte?" header-class="text-caption q-px-none" class="q-mt-xs">
        <div class="text-caption q-pl-md q-pb-sm explain">
          <p>
            Jede Erkennung ab Confidence {{ confidence ?? 'eval_confidence' }} wird mit den annotierten Boxen verglichen. Sie zählt als
            <b>Treffer (TP)</b>, wenn sie eine noch freie Box derselben Klasse mit IoU ≥ 0,5 überlappt (Boxen decken sich mindestens
            zur Hälfte, gemessen an der gemeinsamen Fläche). Eine Erkennung ohne passende Box ist ein <b>Fehlalarm (FP)</b>, eine Box
            ohne Erkennung ein <b>verpasstes Objekt (FN)</b>.
          </p>
          <p v-for="c in visibleColumns.filter((c) => c.help && c.name !== 'version')" :key="c.name"><b>{{ c.label }}:</b> {{ c.help }}</p>
        </div>
      </q-expansion-item>
    </q-card-section>
    <q-card-section v-else class="q-pt-none text-body2 text-muted">
      Die beim Training gespeicherten Metriken stammen jeweils vom damaligen, kleineren Validierungsset und sind nicht miteinander
      vergleichbar. Der Vergleich bewertet alle Modelle neu auf den heutigen Validierungsbildern.
    </q-card-section>
  </q-card>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useQuasar, type QTableColumn } from 'quasar'
import HelpIcon from './HelpIcon.vue'
import { api, errorMessage, fmtDate, fmtPct, type Benchmark, type Metrics } from '@/services/api'
import { useClassesStore } from '@/stores/classes'

const MIN_RELIABLE_BOXES = 30
const $q = useQuasar()
const classes = useClassesStore()
const benchmark = ref<Benchmark | null>(null)
const starting = ref(false)
const statusColor: Record<string, string> = { production: 'positive', candidate: 'primary', archived: 'grey-5' }

const running = computed(() => benchmark.value?.status === 'queued' || benchmark.value?.status === 'running')
const results = computed(() => Object.entries(benchmark.value?.results ?? {}) as [string, Metrics & { status: string; error?: string; seen_in_training?: number | null }][])
const confidence = computed(() => results.value.find(([, m]) => m.confidence_for_pr != null)?.[1].confidence_for_pr ?? null)
const classNames = computed(() => benchmark.value?.class_names ?? [])
// validation boxes per class (tp + fn of any evaluated model)
const classBoxes = computed(() => {
  const m = results.value.find(([, r]) => r.per_class)?.[1]
  return Object.fromEntries(classNames.value.map((c) => [c, (m?.per_class?.[c]?.tp ?? 0) + (m?.per_class?.[c]?.fn ?? 0)]))
})
const shownClasses = computed(() => classNames.value.filter((c) => classBoxes.value[c] > 0))

// focus class: persons are what the system is for; everything is judged by them first
const FOCUS_CLASS = 'person'
const focus = computed(() => (shownClasses.value.includes(FOCUS_CLASS) ? FOCUS_CLASS : shownClasses.value[0] ?? FOCUS_CLASS))
const focusLabel = computed(() => classes.info(focus.value).label)
const focusBoxes = computed(() => classBoxes.value[focus.value] ?? 0)
const otherClasses = computed(() => shownClasses.value.filter((c) => c !== focus.value))
const allColumns = ref(stored('benchmark-all-columns', false))
watch(allColumns, (v) => {
  try {
    localStorage.setItem('benchmark-all-columns', JSON.stringify(v))
  } catch {
    /* storage unavailable: setting just isn't kept */
  }
})
function stored<T>(key: string, fallback: T): T {
  try {
    const v = localStorage.getItem(key)
    return v == null ? fallback : (JSON.parse(v) as T)
  } catch {
    return fallback
  }
}

interface Row {
  version: string
  status: string
  error?: string
  seen?: number | null
  size?: string
  hnText?: string
  [metric: string]: number | string | null | undefined
}

const rows = computed<Row[]>(() =>
  results.value.map(([version, m]) => {
    const hn = m.hard_negatives?.overall
    const row: Row = {
      version,
      status: m.status,
      error: m.error,
      seen: m.seen_in_training,
      size: m.input_size,
      precision: m.overall?.precision,
      recall: m.overall?.recall,
      map50: m.overall?.mAP50,
      map5095: m.overall?.['mAP50-95'],
      small: m.per_size?.small?.['mAP50-95'],
      counts: m.overall ? `${m.overall.tp ?? '–'} / ${m.overall.fp ?? '–'} / ${m.overall.fn ?? '–'}` : '',
      hn: hn?.fp_rate ?? null,
      hnText: hn ? `${hn.still_detected}/${hn.total}` : '',
    }
    for (const c of classNames.value) {
      const pc = m.per_class?.[c]
      row[`missed_${c}`] = pc?.fn ?? null
      row[`map5095_${c}`] = pc?.['mAP50-95'] ?? null
      row[`map50_${c}`] = pc?.mAP50 ?? null
      row[`recall_${c}`] = pc?.recall ?? null
      row[`precision_${c}`] = pc?.precision ?? null
      row[`fp_${c}`] = pc?.fp ?? null
    }
    return row
  }),
)

const missedRanking = computed(() =>
  rows.value
    .filter((r) => typeof r[`missed_${focus.value}`] === 'number')
    .map((r) => ({ version: r.version, missed: r[`missed_${focus.value}`] as number }))
    .sort((a, b) => a.missed - b.missed),
)
const missedMax = computed(() => Math.max(0, ...missedRanking.value.map((m) => m.missed)))
const missedMin = computed(() => Math.min(...missedRanking.value.map((m) => m.missed)))

const fewBoxes = computed(() =>
  shownClasses.value.filter((c) => classBoxes.value[c] < MIN_RELIABLE_BOXES).map((c) => `${classes.info(c).label} (${classBoxes.value[c]})`),
)
const noBoxes = computed(() => classNames.value.filter((c) => results.value.length && classBoxes.value[c] === 0).map((c) => classes.info(c).label))

const pct = (v: unknown) => (v == null ? '–' : fmtPct(v as number))
type Column = QTableColumn<Row> & { help?: string; focus?: boolean; extra?: boolean; lowerBetter?: boolean }

function missedColumn(c: string, extra: boolean): Column {
  const label = classes.info(c).label
  return {
    name: `missed_${c}`, label: `Nicht erkannt ${label}`, field: `missed_${c}`, sortable: true, focus: !extra, extra, lowerBetter: true,
    format: (v: unknown) => (v == null ? '–' : `${v} (${fmtPct((v as number) / (classBoxes.value[c] || 1))})`),
    help: `Annotierte ${label}-Boxen, die das Modell nicht gefunden hat (FN) – von ${classBoxes.value[c]}. Das ist der schwerste Fehler: ` +
      'ein echtes Objekt ohne Alarm. In Klammern der Anteil (= 100 % − Recall). Niedriger ist besser.',
  }
}

const columns = computed<Column[]>(() => {
  const f = focus.value
  const fl = focusLabel.value
  return [
    { name: 'version', label: 'Modell', field: 'version', align: 'left', sortable: true },
    { name: 'size', label: 'Auflösung', field: 'size', align: 'left', help: 'Eingangsauflösung, in der das Modell trainiert wurde und hier getestet wird.' },
    missedColumn(f, false),
    {
      name: `map5095_${f}`, label: `mAP50-95 ${fl}`, field: `map5095_${f}`, format: pct, sortable: true, focus: true,
      help: `mAP50-95 nur für ${fl}en: Average Precision gemittelt über die IoU-Schwellen 0,50 bis 0,95. Bewertet, ob ${fl}en ` +
        'gefunden werden UND wie genau die Box sitzt. Hauptkennzahl.',
    },
    {
      name: `map50_${f}`, label: `mAP50 ${fl}`, field: `map50_${f}`, format: pct, sortable: true, focus: true,
      help: `mAP50 nur für ${fl}en: Average Precision bei IoU 0,5 – über alle Confidence-Schwellen gemittelt (Fläche unter der ` +
        'Precision-Recall-Kurve). Zeigt, wie gut das Modell echte von falschen Erkennungen trennt, unabhängig von der Boxgenauigkeit.',
    },
    {
      name: `recall_${f}`, label: `Recall ${fl}`, field: `recall_${f}`, format: pct, sortable: true,
      help: `TP / (TP + FN) für ${fl}en bei der eingestellten Confidence: Anteil der ${fl}en, die gefunden werden.`,
    },
    {
      name: `precision_${f}`, label: `Precision ${fl}`, field: `precision_${f}`, format: pct, sortable: true,
      help: `TP / (TP + FP) für ${fl}en: Anteil der ${fl}en-Erkennungen, die stimmen. 90 % = jede zehnte ist ein Fehlalarm.`,
    },
    {
      name: `fp_${f}`, label: `Fehlalarme ${fl}`, field: `fp_${f}`, sortable: true, lowerBetter: true,
      help: `${fl}en-Erkennungen ohne passende annotierte Box (FP) bei der eingestellten Confidence. Niedriger ist besser.`,
    },
    {
      name: 'hn', label: 'HN-FP-Rate', field: 'hn', sortable: true, lowerBetter: true,
      format: (v: unknown, r: Row) => (v == null ? '–' : `${fmtPct(v as number)} (${r.hnText})`),
      help: 'Hard-Negative-Fehlalarmrate: Von den als Hard Negative markierten Fehlalarmen auf Validierungsbildern (z. B. ein Pfosten, der ' +
        'als Person erkannt wurde) – wie viele erkennt das Modell immer noch? Gezählt wird ein Hard Negative, wenn eine Erkennung derselben ' +
        'Klasse mit mindestens der eingestellten Confidence es mit IoU ≥ 0,5 überlappt. Rate = noch erkannt / alle; in Klammern die Anzahl. ' +
        'Niedriger ist besser. Hard Negatives von Klassen, die das Modell nicht kennt, zählen nicht mit.',
    },
    // --- secondary metrics ("Alle Kennzahlen")
    ...otherClasses.value.flatMap((c): Column[] => [
      missedColumn(c, true),
      {
        name: `map5095_${c}`, label: `mAP50-95 ${classes.info(c).label}`, field: `map5095_${c}`, format: pct, sortable: true, extra: true,
        help: `mAP50-95 nur für die Klasse „${classes.info(c).label}“ (${classBoxes.value[c]} Validierungsboxen).`,
      },
      {
        name: `map50_${c}`, label: `mAP50 ${classes.info(c).label}`, field: `map50_${c}`, format: pct, sortable: true, extra: true,
        help: `mAP50 nur für die Klasse „${classes.info(c).label}“.`,
      },
    ]),
    {
      name: 'precision', label: 'Precision gesamt', field: 'precision', format: pct, sortable: true, extra: true,
      help: 'TP / (TP + FP) über alle Klassen: Anteil der Erkennungen, die stimmen.',
    },
    {
      name: 'recall', label: 'Recall gesamt', field: 'recall', format: pct, sortable: true, extra: true,
      help: 'TP / (TP + FN) über alle Klassen: Anteil der annotierten Objekte, die das Modell findet.',
    },
    {
      name: 'map50', label: 'mAP50 gesamt', field: 'map50', format: pct, sortable: true, extra: true,
      help: 'mAP50 gemittelt über alle Klassen.',
    },
    {
      name: 'map5095', label: 'mAP50-95 gesamt', field: 'map5095', format: pct, sortable: true, extra: true,
      help: 'mAP50-95 gemittelt über alle Klassen. Klassen mit wenigen Boxen zählen genauso viel wie Personen.',
    },
    {
      name: 'small', label: 'mAP50-95 klein', field: 'small', format: pct, sortable: true, extra: true,
      help: 'mAP50-95 nur für kleine Objekte (Boxfläche unter 32×32 = 1024 Pixel im Originalbild) – z. B. Personen weit von der Kamera entfernt.',
    },
    {
      name: 'counts', label: 'TP / FP / FN gesamt', field: 'counts', extra: true,
      help: 'Absolute Zahlen über alle Klassen bei der eingestellten Confidence: Treffer / Fehlalarme / verpasste Objekte.',
    },
  ]
})
const visibleColumns = computed(() => columns.value.filter((c) => allColumns.value || !c.extra))

function raw(col: Column, row: Row): unknown {
  return typeof col.field === 'function' ? col.field(row) : row[col.field as string]
}

function columnValues(col: Column) {
  return rows.value.map((r) => raw(col, r)).filter((v): v is number => typeof v === 'number')
}
function cellClass(col: Column, row: Row) {
  const value = raw(col, row)
  const out: string[] = col.focus ? ['focus-col'] : []
  if (typeof value !== 'number' || !col.sortable || col.name === 'version' || rows.value.length < 2) return out
  const values = columnValues(col)
  const best = col.lowerBetter ? Math.min(...values) : Math.max(...values)
  const worst = col.lowerBetter ? Math.max(...values) : Math.min(...values)
  if (value === best) out.push('text-positive', 'text-weight-bold')
  // a model that misses the most objects is flagged red
  else if (col.name.startsWith('missed_') && value === worst) out.push('text-negative', 'text-weight-bold')
  return out
}

let timer: number | undefined
async function refresh() {
  try {
    benchmark.value = await api.latestBenchmark()
  } catch {
    /* polling: ignore transient errors */
  }
  window.clearTimeout(timer)
  if (running.value) timer = window.setTimeout(refresh, 3000)
}

async function start() {
  starting.value = true
  try {
    benchmark.value = await api.startBenchmark()
    refresh()
  } catch (e) {
    $q.notify({ type: 'negative', message: errorMessage(e) })
  } finally {
    starting.value = false
  }
}

onMounted(() => {
  classes.refresh()
  refresh()
})
onBeforeUnmount(() => window.clearTimeout(timer))
</script>

<style scoped>
.explain p {
  margin: 0 0 6px;
}
.missed {
  border: 1px solid rgba(255, 23, 68, 0.35);
  background: rgba(255, 23, 68, 0.06);
}
.missed-row {
  height: 22px;
}
.missed-name {
  width: 110px;
  font-size: 12px;
}
.missed-track {
  height: 10px;
  margin: 0 10px;
  background: rgba(128, 128, 128, 0.15);
  border-radius: 5px;
  overflow: hidden;
}
.missed-bar {
  height: 100%;
  background: var(--q-negative);
  border-radius: 5px;
}
.missed-value {
  width: 90px;
  text-align: right;
}
/* model name stays visible while scrolling the wide table to the right */
.sticky-first :deep(thead th:first-child),
.sticky-first :deep(tbody td:first-child) {
  position: sticky;
  left: 0;
  z-index: 2;
  background: var(--app-panel);
  box-shadow: inset -1px 0 0 rgba(128, 128, 128, 0.3);
}
</style>
