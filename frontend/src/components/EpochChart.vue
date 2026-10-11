<template>
  <div ref="container" class="epoch-chart">
    <div class="legend row items-center q-gutter-x-md q-gutter-y-xs text-caption">
      <q-btn-toggle
        v-model="metric"
        dense
        no-caps
        unelevated
        size="sm"
        toggle-color="primary"
        :options="[
          { label: 'mAP50', value: 'mAP50' },
          { label: 'mAP50-95', value: 'mAP50-95' },
        ]"
      />
      <HelpIcon :term="metric === 'mAP50' ? 'mAP50' : 'mAP5095'" inline />
      <span
        v-for="s in series"
        :key="s.key"
        class="legend-item row items-center no-wrap cursor-pointer"
        :class="{ 'legend-off': hidden.has(s.key) }"
        @click="toggle(s.key)"
      >
        <svg width="18" height="6" class="q-mr-xs"><line x1="1" y1="3" x2="17" y2="3" :stroke="s.color" stroke-width="3" :stroke-dasharray="s.dash" /></svg>{{ s.label }}
        <q-tooltip>{{ hidden.has(s.key) ? 'einblenden' : 'ausblenden' }}</q-tooltip>
      </span>
      <q-space />
      <span v-for="b in bands" :key="b.label" class="row items-center no-wrap text-muted">
        <span class="legend-band" :style="{ background: b.swatch }" />{{ b.label }}
      </span>
    </div>
    <div v-if="points.length && !hasDetail" class="text-caption text-muted q-mb-xs">
      Einzelwerte je Klasse und Boxgröße gibt es erst für Trainings, die nach dieser Erweiterung gestartet wurden.
    </div>
    <svg v-if="width > 0" :width="width" :height="HEIGHT" @mousemove="onMove" @mouseleave="hoverIndex = null">
      <!-- quality bands (background) -->
      <rect v-for="b in bands" :key="b.label" :x="M.l" :y="y(b.to)" :width="plotW" :height="y(b.from) - y(b.to)" :fill="b.fill" />
      <!-- grid + y axis -->
      <g v-for="t in [0, 20, 40, 60, 80, 100]" :key="t">
        <line :x1="M.l" :x2="M.l + plotW" :y1="y(t)" :y2="y(t)" class="grid" />
        <text :x="M.l - 6" :y="y(t)" class="tick" text-anchor="end" dominant-baseline="middle">{{ t }} %</text>
      </g>
      <!-- x axis -->
      <text v-for="e in xTicks" :key="e" :x="x(e)" :y="M.t + plotH + 18" class="tick" text-anchor="middle">{{ e }}</text>
      <text :x="M.l + plotW" :y="HEIGHT - 2" class="tick" text-anchor="end">Epoch</text>
      <!-- series -->
      <g v-for="s in visibleSeries" :key="s.key">
        <path :d="linePath(s)" :stroke="s.color" :stroke-dasharray="s.dash" :stroke-width="s.width" class="line" />
        <circle
          v-for="p in pointsOf(s)"
          v-show="points.length <= 60 || hoverIndex === p.i"
          :key="p.i"
          :cx="p.x"
          :cy="p.y"
          :r="hoverIndex === p.i ? 5 : 3"
          :fill="s.color"
          class="dot"
        />
      </g>
      <!-- crosshair -->
      <line v-if="hover" :x1="x(hover.epoch)" :x2="x(hover.epoch)" :y1="M.t" :y2="M.t + plotH" class="crosshair" />
      <text v-if="!points.length" :x="M.l + plotW / 2" :y="M.t + plotH / 2" class="tick" text-anchor="middle">
        Noch keine Validierung – die erste Epoche läuft.
      </text>
    </svg>
    <div v-if="hover" class="chart-tooltip text-caption" :style="tooltipStyle">
      <div class="text-weight-medium q-mb-xs">Epoch {{ hover.epoch }} · {{ metric }}</div>
      <div v-for="s in visibleSeries" :key="s.key" class="row items-center no-wrap">
        <svg width="18" height="6" class="q-mr-xs"><line x1="1" y1="3" x2="17" y2="3" :stroke="s.color" stroke-width="3" :stroke-dasharray="s.dash" /></svg>
        <span class="text-muted q-mr-sm">{{ s.label }}</span>
        <q-space />
        <span class="text-weight-medium">{{ fmt(valueOf(hover, s)) }}</span>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, reactive, ref } from 'vue'
import HelpIcon from './HelpIcon.vue'
import type { ValHistoryEntry, ValMaps } from '@/services/api'
import { useClassesStore } from '@/stores/classes'

/** mAP values per validated epoch (0..1), e.g. TrainingRun.progress_json.val_history */
const props = defineProps<{
  history: ValHistoryEntry[]
  maxEpochs?: number
}>()
const classes = useClassesStore()

type Metric = keyof ValMaps
interface Series {
  key: string
  label: string
  color: string
  dash?: string
  width: number
  value: (e: ValHistoryEntry, m: Metric) => number | undefined
}

const metric = ref<Metric>('mAP50')
const hidden = reactive(new Set<string>())

const SIZES = [
  { key: 'small', label: 'klein', color: '#f472b6' },
  { key: 'medium', label: 'mittel', color: '#facc15' },
  { key: 'large', label: 'groß', color: '#94a3b8' },
]

const hasDetail = computed(() => props.history.some((e) => e.per_class || e.per_size))

/** overall (MMDetection), one line per class, one dashed line per box size (only those present in the history) */
const series = computed<Series[]>(() => {
  const out: Series[] = [
    {
      key: 'overall', label: 'Gesamt', color: '#e5e7eb', width: 3,
      value: (e, m) => (m === 'mAP50' ? e.bbox_mAP_50 : e.bbox_mAP),
    },
  ]
  const classNames = [...new Set(props.history.flatMap((e) => Object.keys(e.per_class ?? {})))]
  for (const name of classNames) {
    const info = classes.info(name)
    out.push({ key: `class:${name}`, label: info.label, color: info.color, width: 2, value: (e, m) => e.per_class?.[name]?.[m] })
  }
  for (const s of SIZES) {
    if (!props.history.some((e) => e.per_size?.[s.key])) continue
    out.push({ key: `size:${s.key}`, label: `Boxen ${s.label}`, color: s.color, dash: '6 4', width: 2, value: (e, m) => e.per_size?.[s.key]?.[m] })
  }
  return out
})
const visibleSeries = computed(() => series.value.filter((s) => !hidden.has(s.key)))

function toggle(key: string) {
  if (hidden.has(key)) hidden.delete(key)
  else hidden.add(key)
}

function valueOf(e: ValHistoryEntry, s: Series) {
  return s.value(e, metric.value)
}
const bands = [
  { from: 0, to: 60, label: '0–60 %', fill: 'rgba(251, 113, 133, 0.18)', swatch: 'rgba(251, 113, 133, 0.7)' },
  { from: 60, to: 80, label: '61–80 %', fill: 'rgba(251, 146, 60, 0.20)', swatch: 'rgba(251, 146, 60, 0.75)' },
  { from: 80, to: 100, label: '> 80 %', fill: 'rgba(52, 211, 153, 0.18)', swatch: 'rgba(52, 211, 153, 0.7)' },
]

const HEIGHT = 260
const M = { t: 12, r: 16, b: 34, l: 48 }
const container = ref<HTMLDivElement | null>(null)
const width = ref(0)
const hoverIndex = ref<number | null>(null)

const plotW = computed(() => Math.max(0, width.value - M.l - M.r))
const plotH = HEIGHT - M.t - M.b
const points = computed(() => [...props.history].sort((a, b) => a.epoch - b.epoch))
const xMax = computed(() => Math.max(props.maxEpochs ?? 1, ...points.value.map((p) => p.epoch), 2))

function x(epoch: number) {
  return M.l + ((epoch - 1) / (xMax.value - 1)) * plotW.value
}
function y(pct: number) {
  return M.t + (1 - pct / 100) * plotH
}
function pointsOf(s: Series) {
  return points.value.flatMap((p, i) => {
    const v = valueOf(p, s)
    return v == null ? [] : [{ i, x: x(p.epoch), y: y(v * 100) }]
  })
}
function linePath(s: Series) {
  return pointsOf(s)
    .map((p, n) => `${n ? 'L' : 'M'}${p.x.toFixed(1)},${p.y.toFixed(1)}`)
    .join('')
}

const xTicks = computed(() => {
  const step = [1, 2, 5, 10, 20, 50, 100, 200].find((s) => xMax.value / s <= 10) ?? 500
  const ticks = [1]
  for (let e = step; e <= xMax.value; e += step) if (e > 1) ticks.push(e)
  return ticks
})

const hover = computed(() => (hoverIndex.value == null ? null : points.value[hoverIndex.value] ?? null))
const tooltipStyle = computed(() => {
  if (!hover.value) return {}
  const px = x(hover.value.epoch)
  const left = px > width.value - 210 ? px - 202 : px + 12
  return { left: `${left}px`, top: `${M.t + 28}px` }
})

function onMove(e: MouseEvent) {
  if (!points.value.length) return
  const mx = e.offsetX
  let best = 0
  points.value.forEach((p, i) => {
    if (Math.abs(x(p.epoch) - mx) < Math.abs(x(points.value[best].epoch) - mx)) best = i
  })
  hoverIndex.value = best
}

function fmt(v: number | undefined) {
  return v == null ? '–' : `${(v * 100).toFixed(1)} %`
}

let observer: ResizeObserver | undefined
onMounted(() => {
  observer = new ResizeObserver(([entry]) => (width.value = Math.floor(entry.contentRect.width)))
  if (container.value) observer.observe(container.value)
})
onBeforeUnmount(() => observer?.disconnect())
</script>

<style scoped>
.epoch-chart {
  position: relative;
}
.legend {
  margin: 4px 0 8px;
}
.legend-item {
  user-select: none;
}
.legend-off {
  opacity: 0.35;
  text-decoration: line-through;
}
.legend-band {
  display: inline-block;
  width: 10px;
  height: 10px;
  border-radius: 2px;
  margin-right: 6px;
}
svg {
  display: block;
}
.grid {
  stroke: var(--app-border);
  stroke-width: 1;
}
.tick {
  fill: var(--app-muted);
  font-size: 11px;
}
.line {
  fill: none;
  stroke-linejoin: round;
  stroke-linecap: round;
}
.dot {
  stroke: var(--app-panel);
  stroke-width: 2;
}
.crosshair {
  stroke: var(--app-muted);
  stroke-width: 1;
  stroke-dasharray: 3 3;
}
.chart-tooltip {
  position: absolute;
  min-width: 190px;
  pointer-events: none;
  background: #1e293b;
  border: 1px solid var(--app-border-strong);
  border-radius: 8px;
  padding: 8px 10px;
  box-shadow: 0 8px 24px rgba(0, 0, 0, 0.4);
}
</style>
