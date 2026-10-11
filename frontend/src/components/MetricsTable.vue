<template>
  <div v-if="metrics?.overall">
    <q-markup-table dense flat bordered separator="cell" class="q-mb-sm">
      <thead>
        <tr>
          <th class="text-left">Klasse</th>
          <th>Precision<HelpIcon term="precision" inline /></th>
          <th>Recall<HelpIcon term="recall" inline /></th>
          <th>mAP50<HelpIcon term="mAP50" inline /></th>
          <th>mAP50-95<HelpIcon term="mAP5095" inline /></th>
          <th>mAP50-95 klein<HelpIcon term="mAPSmall" inline /></th>
          <th>TP / FP / FN<HelpIcon term="tpFpFn" inline /></th>
        </tr>
      </thead>
      <tbody>
        <tr class="text-weight-bold">
          <td class="text-left">Gesamt</td>
          <td class="text-right">{{ fmtPct(metrics.overall.precision) }}</td>
          <td class="text-right">{{ fmtPct(metrics.overall.recall) }}</td>
          <td class="text-right">{{ fmtPct(metrics.overall.mAP50) }}</td>
          <td class="text-right">{{ fmtPct(metrics.overall['mAP50-95']) }}</td>
          <td class="text-right">{{ fmtPct(metrics.per_size?.small?.['mAP50-95']) }}</td>
          <td class="text-right">{{ counts(metrics.overall) }}</td>
        </tr>
        <tr v-for="c in rows" :key="c.name">
          <td class="text-left"><span class="class-dot" :style="{ background: c.color }" />{{ c.label }}</td>
          <td class="text-right">{{ fmtPct(metrics.per_class?.[c.name]?.precision) }}</td>
          <td class="text-right">{{ fmtPct(metrics.per_class?.[c.name]?.recall) }}</td>
          <td class="text-right">{{ fmtPct(metrics.per_class?.[c.name]?.mAP50) }}</td>
          <td class="text-right">{{ fmtPct(metrics.per_class?.[c.name]?.['mAP50-95']) }}</td>
          <td class="text-right">{{ fmtPct(metrics.per_class?.[c.name]?.small?.['mAP50-95']) }}</td>
          <td class="text-right">{{ counts(metrics.per_class?.[c.name]) }}</td>
        </tr>
      </tbody>
    </q-markup-table>
    <q-markup-table v-if="metrics.per_size" dense flat bordered separator="cell">
      <thead>
        <tr>
          <th class="text-left">Boxgröße (Originalpixel)<HelpIcon term="boxSize" inline /></th>
          <th>Precision<HelpIcon term="precision" inline /></th>
          <th>Recall<HelpIcon term="recall" inline /></th>
          <th>mAP50<HelpIcon term="mAP50" inline /></th>
          <th>mAP50-95<HelpIcon term="mAP5095" inline /></th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="(label, key) in SIZES" :key="key">
          <td class="text-left">{{ label }}</td>
          <td class="text-right">{{ fmtPct(metrics.per_size[key]?.precision) }}</td>
          <td class="text-right">{{ fmtPct(metrics.per_size[key]?.recall) }}</td>
          <td class="text-right">{{ fmtPct(metrics.per_size[key]?.mAP50) }}</td>
          <td class="text-right">{{ fmtPct(metrics.per_size[key]?.['mAP50-95']) }}</td>
        </tr>
      </tbody>
    </q-markup-table>
    <template v-if="metrics.hard_negatives && metrics.hard_negatives.overall.total">
      <div class="text-subtitle2 q-mt-md">Hard-Negative-Regressionstest<HelpIcon term="hardNegatives" inline /></div>
      <q-markup-table dense flat bordered separator="cell">
        <thead>
          <tr>
            <th class="text-left">Klasse</th>
            <th>Hard Negatives</th>
            <th>weiterhin falsch erkannt<HelpIcon term="hnStillDetected" inline /></th>
            <th>HN-FP-Rate<HelpIcon term="hnFpRate" inline /></th>
          </tr>
        </thead>
        <tbody>
          <tr class="text-weight-bold">
            <td class="text-left">Gesamt</td>
            <td class="text-right">{{ metrics.hard_negatives.overall.total }}</td>
            <td class="text-right">{{ metrics.hard_negatives.overall.still_detected }}</td>
            <td class="text-right">{{ fmtPct(metrics.hard_negatives.overall.fp_rate, 2) }}</td>
          </tr>
          <tr v-for="(b, name) in metrics.hard_negatives.per_class" :key="name">
            <td class="text-left"><span class="class-dot" :style="{ background: classes.info(name).color }" />{{ classes.info(name).label }}</td>
            <td class="text-right">{{ b.total }}</td>
            <td class="text-right">{{ b.still_detected }}</td>
            <td class="text-right">{{ fmtPct(b.fp_rate, 2) }}</td>
          </tr>
          <tr v-if="metrics.hard_negatives.validation_only.total" class="text-muted">
            <td class="text-left">nur Validierungsbilder (nicht trainiert)</td>
            <td class="text-right">{{ metrics.hard_negatives.validation_only.total }}</td>
            <td class="text-right">{{ metrics.hard_negatives.validation_only.still_detected }}</td>
            <td class="text-right">{{ fmtPct(metrics.hard_negatives.validation_only.fp_rate, 2) }}</td>
          </tr>
        </tbody>
      </q-markup-table>
      <div class="text-caption text-muted">
        „Weiterhin falsch erkannt“ = gleiche Klasse mit Confidence ≥ {{ metrics.hard_negatives.confidence }} und IoU ≥
        {{ metrics.hard_negatives.iou }} zur gespeicherten Box. Immer zusammen mit Recall/Precision bewerten.
      </div>
    </template>

    <template v-if="metrics.comparison">
      <div class="text-subtitle2 q-mt-md">Vergleich mit {{ metrics.comparison.baseline_model }} (aktuelles Production-Modell, gleiche Daten)<HelpIcon term="delta" inline /></div>
      <q-banner v-for="w in metrics.comparison.warnings" :key="w" dense rounded class="bg-amber-soft q-mb-xs text-body2">
        <template #avatar><q-icon name="warning" color="warning" /></template>{{ w }}
      </q-banner>
      <q-markup-table dense flat bordered separator="cell">
        <thead>
          <tr>
            <th class="text-left">Klasse</th>
            <th>Val-Boxen</th>
            <th>Recall Δ<HelpIcon term="recall" inline /></th>
            <th>Precision Δ<HelpIcon term="precision" inline /></th>
            <th>mAP50 Δ<HelpIcon term="mAP50" inline /></th>
            <th>mAP50-95 Δ<HelpIcon term="mAP5095" inline /></th>
            <th>TP / FP / FN<HelpIcon term="tpFpFn" inline /><div class="text-caption text-muted">neu ← {{ metrics.comparison.baseline_model }}</div></th>
            <th>
              HN-FP-Rate Δ<HelpIcon term="hnFpRate" inline />
              <div class="text-caption text-muted">nur Validierung</div>
              <q-tooltip>Darunter: Hard Negatives, die weiterhin erkannt werden (neu ← {{ metrics.comparison.baseline_model }})</q-tooltip>
            </th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="r in comparisonRows" :key="r.key" :class="{ 'text-weight-bold': r.key === '_overall' }">
            <td class="text-left">
              <span v-if="r.color" class="class-dot" :style="{ background: r.color }" />{{ r.label }}
            </td>
            <td class="text-right">
              {{ r.boxes ?? '–' }}
              <q-badge v-if="!r.reliable" outline color="warning" class="q-ml-xs" label="wenig Daten">
                <q-tooltip max-width="320px">
                  Nur {{ r.boxes ?? 0 }} Validierungsboxen (empfohlen ≥ {{ minBoxes }}). Eine Box mehr oder weniger ändert den Recall
                  hier um {{ r.boxes ? (100 / r.boxes).toFixed(1) : '–' }} Prozentpunkte. Die Deltas sind deshalb nicht farbig bewertet.
                </q-tooltip>
              </q-badge>
            </td>
            <td class="text-right" :class="deltaClass(r.delta.recall, false, r.reliable)">{{ fmtDelta(r.delta.recall) }}</td>
            <td class="text-right" :class="deltaClass(r.delta.precision, false, r.reliable)">{{ fmtDelta(r.delta.precision) }}</td>
            <td class="text-right" :class="deltaClass(r.delta.mAP50, false, r.reliable)">{{ fmtDelta(r.delta.mAP50) }}</td>
            <td class="text-right" :class="deltaClass(r.delta['mAP50-95'], false, r.reliable)">{{ fmtDelta(r.delta['mAP50-95']) }}</td>
            <td class="text-right text-no-wrap">{{ counts(r.next) }} <span class="text-muted">← {{ counts(r.base) }}</span></td>
            <td v-if="r.hnLegacy" class="text-right text-muted">
              –*
              <q-tooltip max-width="320px">
                Für dieses Modell nur inklusive Trainingsbildern gespeichert: {{ fmtDelta(r.hnDelta) }}
                ({{ hnCount(r.hnNew) }} ← {{ hnCount(r.hnBase) }}). Nicht fair vergleichbar.
              </q-tooltip>
            </td>
            <td v-else class="text-right text-no-wrap">
              <span :class="deltaClass(r.hnDelta, true, r.hnReliable)">{{ fmtDelta(r.hnDelta) }}</span>
              <div v-if="r.hnNew || r.hnBase" class="text-caption text-muted">{{ hnCount(r.hnNew) }} ← {{ hnCount(r.hnBase) }}</div>
            </td>
          </tr>
        </tbody>
      </q-markup-table>
      <div class="text-caption text-muted">
        Δ in Prozentpunkten (neu − {{ metrics.comparison.baseline_model }}); grün = besser. Farbig bewertet nur ab {{ minBoxes }}
        Validierungsboxen bzw. {{ minBoxes }} Hard Negatives, darunter ist der Unterschied meist Zufall. Die HN-FP-Rate wird nur auf
        Validierungsbildern verglichen: Hard Negatives auf Trainingsbildern hat das neue Modell als Ausschnitte gelernt.
        Nur Klassen, die beide Modelle kennen.
        <template v-if="comparisonRows.some((r) => r.hnLegacy)">
          <br />* Vor dieser Korrektur trainiert: Pro Klasse ist nur der Wert inklusive Trainingsbildern gespeichert, der das neue Modell
          bevorzugt (Wert im Tooltip). Die Zeile „Gesamt“ ist bereits fair.
        </template>
      </div>
    </template>

    <div class="text-caption text-muted q-mt-xs">
      {{ metrics.num_images }} Validierungsbilder, {{ metrics.num_boxes }} Boxen · ausgewertet mit {{ metrics.evaluated_with }}
      bei {{ metrics.input_size }} · Precision/Recall bei Confidence ≥ {{ metrics.confidence_for_pr }} und IoU 0.5
      <span v-if="metrics.note"> · {{ metrics.note }}</span>
    </div>
  </div>
  <div v-else class="text-muted">Keine Metriken vorhanden.</div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import HelpIcon from './HelpIcon.vue'
import { fmtPct, type HardNegativeBucket, type MetricSet, type Metrics } from '@/services/api'
import { useClassesStore } from '@/stores/classes'

const props = defineProps<{ metrics: Metrics | null | undefined }>()
const classes = useClassesStore()
// rows = classes of the evaluated model (not the currently configured ones)
const rows = computed(() => Object.keys(props.metrics?.per_class ?? {}).map((n) => classes.info(n)))

const SIZES = { small: 'klein (< 32²)', medium: 'mittel (32²–96²)', large: 'groß (> 96²)' } as const

function fmtDelta(v: number | null | undefined) {
  if (v === null || v === undefined) return '–'
  const pp = v * 100
  return `${pp > 0 ? '+' : ''}${pp.toFixed(1)} pp`
}

/** green = better; for the hard-negative FP rate lower is better; too little data = not judged */
function deltaClass(v: number | null | undefined, lowerIsBetter = false, reliable = true) {
  if (v === null || v === undefined) return ''
  if (!reliable) return 'text-muted'
  if (Math.abs(v) < 0.0005) return ''
  return (v > 0) !== lowerIsBetter ? 'text-positive' : 'text-negative'
}

// below this many validation boxes one box shifts recall by more than 3 pp (trainer: evaluate.MIN_RELIABLE_BOXES)
const minBoxes = computed(() => props.metrics?.comparison?.min_reliable_boxes ?? 30)

type DeltaKey = 'precision' | 'recall' | 'mAP50' | 'mAP50-95'

function diff(a: number | null | undefined, b: number | null | undefined) {
  return a == null || b == null ? null : a - b
}

/** "Gesamt" + one row per class; counts and reliability are derived from the stored TP/FP/FN (also for older runs) */
const comparisonRows = computed(() => {
  const m = props.metrics
  const cmp = m?.comparison
  if (!m || !cmp) return []
  const fair = cmp.hard_negative_basis === 'validation'
  const row = (
    key: string,
    label: string,
    color: string | null,
    next: MetricSet | null | undefined,
    base: MetricSet | null | undefined,
    delta: Record<DeltaKey, number | null>,
    hnNew: HardNegativeBucket | undefined,
    hnBase: HardNegativeBucket | undefined,
    hnDelta: number | null,
    hnLegacy: boolean,
  ) => {
    const boxes = next?.tp != null && next?.fn != null ? next.tp + next.fn : null
    const hnTotal = Math.min(hnNew?.total ?? 0, hnBase?.total ?? 0)
    return {
      key, label, color, next, base, delta, boxes, hnNew, hnBase, hnDelta, hnLegacy,
      reliable: boxes != null && boxes >= minBoxes.value,
      hnReliable: hnTotal >= minBoxes.value,
    }
  }
  const keys: DeltaKey[] = ['precision', 'recall', 'mAP50', 'mAP50-95']
  const overallDelta = Object.fromEntries(keys.map((k) => [k, diff(m.overall?.[k], cmp.baseline.overall?.[k])])) as Record<DeltaKey, number | null>
  const hnNewAll = m.hard_negatives?.validation_only
  const hnBaseAll = cmp.baseline.hard_negatives?.validation_only
  const rows = [
    row('_overall', 'Gesamt', null, m.overall, cmp.baseline.overall, overallDelta,
      hnNewAll?.total ? hnNewAll : undefined, hnBaseAll?.total ? hnBaseAll : undefined,
      hnNewAll?.total && hnBaseAll?.total ? diff(hnNewAll.fp_rate, hnBaseAll.fp_rate) : null, false),
  ]
  for (const [name, d] of Object.entries(cmp.delta_per_class)) {
    const info = classes.info(name)
    const hnNew = fair ? m.hard_negatives?.per_class_validation?.[name] : m.hard_negatives?.per_class?.[name]
    const hnBase = fair ? cmp.baseline.hard_negatives?.per_class_validation?.[name] : cmp.baseline.hard_negatives?.per_class?.[name]
    rows.push(row(name, info.label, info.color, m.per_class?.[name], cmp.baseline.per_class?.[name], d, hnNew, hnBase,
      d.hard_negative_fp_rate, !fair && d.hard_negative_fp_rate != null))
  }
  return rows
})

function hnCount(b: HardNegativeBucket | undefined) {
  return b ? `${b.still_detected}/${b.total}` : '–'
}

function counts(m: MetricSet | null | undefined) {
  return m && m.tp != null ? `${m.tp} / ${m.fp} / ${m.fn}` : '–'
}
</script>
