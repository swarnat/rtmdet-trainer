<template>
  <div v-if="metrics?.overall">
    <q-markup-table dense flat bordered separator="cell" class="q-mb-sm">
      <thead>
        <tr>
          <th class="text-left">Klasse</th>
          <th>Precision</th>
          <th>Recall</th>
          <th>mAP50</th>
          <th>mAP50-95</th>
          <th>mAP50-95 klein</th>
          <th>TP / FP / FN</th>
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
        <tr v-for="c in CLASSES" :key="c.name">
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
          <th class="text-left">Boxgröße (Originalpixel)</th>
          <th>Precision</th>
          <th>Recall</th>
          <th>mAP50</th>
          <th>mAP50-95</th>
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
    <div class="text-caption text-grey-7 q-mt-xs">
      {{ metrics.num_images }} Validierungsbilder, {{ metrics.num_boxes }} Boxen · ausgewertet mit {{ metrics.evaluated_with }}
      bei {{ metrics.input_size }} · Precision/Recall bei Confidence ≥ {{ metrics.confidence_for_pr }} und IoU 0.5
      <span v-if="metrics.note"> · {{ metrics.note }}</span>
    </div>
  </div>
  <div v-else class="text-grey-7">Keine Metriken vorhanden.</div>
</template>

<script setup lang="ts">
import { CLASSES, fmtPct, type MetricSet, type Metrics } from '@/services/api'

defineProps<{ metrics: Metrics | null | undefined }>()

const SIZES = { small: 'klein (< 32²)', medium: 'mittel (32²–96²)', large: 'groß (> 96²)' } as const

function counts(m: MetricSet | undefined) {
  return m && m.tp != null ? `${m.tp} / ${m.fp} / ${m.fn}` : '–'
}
</script>
