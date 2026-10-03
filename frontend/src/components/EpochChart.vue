<template>
  <div ref="container" class="epoch-chart">
    <div class="legend row items-center q-gutter-x-md text-caption">
      <span v-for="s in series" :key="s.key" class="row items-center no-wrap">
        <span class="legend-line" :style="{ background: s.color }" />{{ s.label }}<HelpIcon :term="s.help" inline />
      </span>
      <q-space />
      <span v-for="b in bands" :key="b.label" class="row items-center no-wrap text-muted">
        <span class="legend-band" :style="{ background: b.swatch }" />{{ b.label }}
      </span>
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
      <g v-for="s in series" :key="s.key">
        <path :d="linePath(s.key)" :stroke="s.color" class="line" />
        <circle
          v-for="p in pointsOf(s.key)"
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
      <div class="text-weight-medium q-mb-xs">Epoch {{ hover.epoch }}</div>
      <div v-for="s in series" :key="s.key" class="row items-center no-wrap">
        <span class="legend-line" :style="{ background: s.color }" />
        <span class="text-muted q-mr-sm">{{ s.label }}</span>
        <q-space />
        <span class="text-weight-medium">{{ fmt(hover[s.key]) }}</span>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import HelpIcon from './HelpIcon.vue'

/** mAP values per validated epoch (0..1), e.g. TrainingRun.progress_json.val_history */
const props = defineProps<{
  history: { epoch: number; bbox_mAP?: number; bbox_mAP_50?: number }[]
  maxEpochs?: number
}>()

type Key = 'bbox_mAP_50' | 'bbox_mAP'
const series: { key: Key; label: string; color: string; help: 'mAP50' | 'mAP5095' }[] = [
  { key: 'bbox_mAP_50', label: 'mAP50', color: '#06b6d4', help: 'mAP50' },
  { key: 'bbox_mAP', label: 'mAP50-95', color: '#a78bfa', help: 'mAP5095' },
]
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
function pointsOf(key: Key) {
  return points.value.flatMap((p, i) => (p[key] == null ? [] : [{ i, x: x(p.epoch), y: y(p[key]! * 100) }]))
}
function linePath(key: Key) {
  return pointsOf(key)
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
  const left = px > width.value - 190 ? px - 182 : px + 12
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
.legend-line {
  display: inline-block;
  width: 14px;
  height: 3px;
  border-radius: 2px;
  margin-right: 6px;
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
  stroke-width: 2;
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
  min-width: 170px;
  pointer-events: none;
  background: #1e293b;
  border: 1px solid var(--app-border-strong);
  border-radius: 8px;
  padding: 8px 10px;
  box-shadow: 0 8px 24px rgba(0, 0, 0, 0.4);
}
</style>
