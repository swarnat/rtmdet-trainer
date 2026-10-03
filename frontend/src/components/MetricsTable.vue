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
            <th>Recall Δ<HelpIcon term="recall" inline /></th>
            <th>Precision Δ<HelpIcon term="precision" inline /></th>
            <th>mAP50 Δ<HelpIcon term="mAP50" inline /></th>
            <th>mAP50-95 Δ<HelpIcon term="mAP5095" inline /></th>
            <th>HN-FP-Rate Δ<HelpIcon term="hnFpRate" inline /></th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="(d, name) in metrics.comparison.delta_per_class" :key="name">
            <td class="text-left"><span class="class-dot" :style="{ background: classes.info(name).color }" />{{ classes.info(name).label }}</td>
            <td class="text-right" :class="deltaClass(d.recall)">{{ fmtDelta(d.recall) }}</td>
            <td class="text-right" :class="deltaClass(d.precision)">{{ fmtDelta(d.precision) }}</td>
            <td class="text-right" :class="deltaClass(d.mAP50)">{{ fmtDelta(d.mAP50) }}</td>
            <td class="text-right" :class="deltaClass(d['mAP50-95'])">{{ fmtDelta(d['mAP50-95']) }}</td>
            <td class="text-right" :class="deltaClass(d.hard_negative_fp_rate, true)">{{ fmtDelta(d.hard_negative_fp_rate) }}</td>
          </tr>
        </tbody>
      </q-markup-table>
      <div class="text-caption text-muted">
        Δ in Prozentpunkten (neu − {{ metrics.comparison.baseline_model }}); grün = besser. Nur Klassen, die beide Modelle kennen.
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
import { fmtPct, type MetricSet, type Metrics } from '@/services/api'
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

/** green = better; for the hard-negative FP rate lower is better */
function deltaClass(v: number | null | undefined, lowerIsBetter = false) {
  if (v === null || v === undefined || Math.abs(v) < 0.0005) return ''
  return (v > 0) !== lowerIsBetter ? 'text-positive' : 'text-negative'
}

function counts(m: MetricSet | null | undefined) {
  return m && m.tp != null ? `${m.tp} / ${m.fp} / ${m.fn}` : '–'
}
</script>
