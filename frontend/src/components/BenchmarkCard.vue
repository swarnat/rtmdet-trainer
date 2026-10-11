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

      <q-table
        v-if="rows.length"
        flat
        bordered
        dense
        :rows="rows"
        :columns="columns"
        row-key="version"
        :pagination="{ rowsPerPage: 0, sortBy: 'map5095', descending: true }"
        hide-bottom
      >
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
          <q-td :props="props" :class="isBest(props.col.name, raw(props.col, props.row)) ? 'text-positive text-weight-bold' : ''">
            {{ props.value }}
          </q-td>
        </template>
        <template #body-cell-counts="props">
          <q-td :props="props" class="mono">{{ props.value }}</q-td>
        </template>
      </q-table>
      <div class="text-caption text-muted q-mt-sm">
        Alle Modelle auf denselben, aktuellen Validierungsbildern – jedes in seiner eigenen Auflösung, mit der Bewertung des Trainings.
        Validierungsbilder werden nie trainiert, kein Modell hat sie gesehen. Grün = bester Wert der Spalte.
        <span v-if="fewBoxes.length">Wenig Daten (&lt; 30 Boxen): {{ fewBoxes.join(', ') }} – Unterschiede dort sind oft Zufall.</span>
        <span v-if="noBoxes.length"> Ohne Validierungsboxen (nicht bewertbar): {{ noBoxes.join(', ') }}.</span>
      </div>
    </q-card-section>
    <q-card-section v-else class="q-pt-none text-body2 text-muted">
      Die beim Training gespeicherten Metriken stammen jeweils vom damaligen, kleineren Validierungsset und sind nicht miteinander
      vergleichbar. Der Vergleich bewertet alle Modelle neu auf den heutigen Validierungsbildern.
    </q-card-section>
  </q-card>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
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

interface Row {
  version: string
  status: string
  error?: string
  seen?: number | null
  size?: string
  precision?: number | null
  recall?: number | null
  map50?: number | null
  map5095?: number | null
  small?: number | null
  counts?: string
  hn?: number | null
  hnText?: string
  [cls: `cls_${string}`]: number | null | undefined
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
    for (const c of classNames.value) row[`cls_${c}`] = m.per_class?.[c]?.mAP50 ?? null
    return row
  }),
)

const fewBoxes = computed(() =>
  shownClasses.value.filter((c) => classBoxes.value[c] < MIN_RELIABLE_BOXES).map((c) => `${classes.info(c).label} (${classBoxes.value[c]})`),
)
const noBoxes = computed(() => classNames.value.filter((c) => results.value.length && classBoxes.value[c] === 0).map((c) => classes.info(c).label))

const pct = (v: unknown) => (v == null ? '–' : fmtPct(v as number))
const columns = computed<QTableColumn<Row>[]>(() => [
  { name: 'version', label: 'Modell', field: 'version', align: 'left', sortable: true },
  { name: 'size', label: 'Auflösung', field: 'size', align: 'left' },
  { name: 'precision', label: 'Precision', field: 'precision', format: pct, sortable: true },
  { name: 'recall', label: 'Recall', field: 'recall', format: pct, sortable: true },
  { name: 'map50', label: 'mAP50', field: 'map50', format: pct, sortable: true },
  { name: 'map5095', label: 'mAP50-95', field: 'map5095', format: pct, sortable: true },
  { name: 'small', label: 'mAP50-95 klein', field: 'small', format: pct, sortable: true },
  ...shownClasses.value.map((c) => ({
    name: `cls_${c}`, label: `mAP50 ${classes.info(c).label}`, field: (r: Row) => r[`cls_${c}`], format: pct, sortable: true,
  })),
  { name: 'counts', label: 'TP / FP / FN', field: 'counts' },
  {
    name: 'hn', label: 'HN-FP-Rate', field: 'hn', sortable: true,
    format: (v: unknown, r: Row) => (v == null ? '–' : `${fmtPct(v as number)} (${r.hnText})`),
  },
])

function raw(col: QTableColumn<Row>, row: Row): unknown {
  return typeof col.field === 'function' ? col.field(row) : row[col.field as keyof Row]
}

// lower is better for the hard-negative FP rate
const LOWER_BETTER = new Set(['hn'])
const NUMERIC = computed(() => columns.value.filter((c) => c.sortable && c.name !== 'version').map((c) => c.name))
function isBest(name: string, value: unknown) {
  if (typeof value !== 'number' || !NUMERIC.value.includes(name) || rows.value.length < 2) return false
  const values = rows.value.map((r) => (name.startsWith('cls_') ? r[name as `cls_${string}`] : r[name as keyof Row])).filter((v): v is number => typeof v === 'number')
  return value === (LOWER_BETTER.has(name) ? Math.min(...values) : Math.max(...values))
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
