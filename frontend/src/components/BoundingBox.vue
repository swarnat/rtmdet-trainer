<template>
  <v-group>
    <v-rect
      :config="rectConfig"
      @click="onSelect"
      @tap="onSelect"
      @dblclick="onDblClick"
      @dragstart="onSelect"
      @dragmove="onDragMove"
      @dragend="onDragEnd"
      @transform="onTransform"
      @transformend="onTransformEnd"
      @mouseenter="hover = true"
      @mouseleave="hover = false"
    />
    <!-- ignore region: struck through (both diagonals) -->
    <template v-if="ignored">
      <v-line v-for="(points, i) in strike" :key="i" :config="{ points, stroke: color, strokeWidth: 2, strokeScaleEnabled: false, opacity: 0.85, listening: false }" />
    </template>
    <v-label :config="{ x: box.x1, y: labelY, listening: false, opacity: prediction && !selected ? 0.8 : 1 }">
      <v-tag :config="{ fill: hardNegative ? '#0f172a' : ignored ? '#475569' : color, stroke: hardNegative ? color : undefined, strokeWidth: 1, cornerRadius: 2 / scale }" />
      <v-text :config="textConfig" />
    </v-label>
  </v-group>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'
import { useClassesStore } from '@/stores/classes'
import type { EditBox, Prediction } from '@/stores/annotation'

const props = defineProps<{
  box: EditBox | Prediction
  scale: number
  selected: boolean
  prediction?: boolean
  imageWidth: number
  imageHeight: number
}>()

const emit = defineEmits<{
  select: [uid: string]
  change: [uid: string, coords: { x1: number; y1: number; x2: number; y2: number }]
  accept: [uid: string]
}>()

const classes = useClassesStore()
const hover = ref(false)
// an ignore region applies to every class: neutral colour instead of the class colour
const color = computed(() => (ignored.value ? '#94a3b8' : classes.info(props.box.class).color))
// hard negative = known false positive of the model (never a real object)
const hardNegative = computed(() => !props.prediction && props.box.type === 'hard_negative')
// ignore region = neither object nor background (not trained, not evaluated)
const ignored = computed(() => !props.prediction && props.box.type === 'ignore')
const reflected = computed(() => !props.prediction && !!props.box.reflected)
// geometry while dragging/resizing (the box itself only changes when the edit is finished)
const live = ref<{ x: number; y: number; w: number; h: number } | null>(null)
const strike = computed(() => {
  const { x, y, w, h } = live.value ?? { x: props.box.x1, y: props.box.y1, w: props.box.x2 - props.box.x1, h: props.box.y2 - props.box.y1 }
  return [[x, y, x + w, y + h], [x + w, y, x, y + h]]
})
const width = computed(() => props.box.x2 - props.box.x1)
const height = computed(() => props.box.y2 - props.box.y1)

const rectConfig = computed(() => ({
  id: props.box.uid,
  name: props.prediction ? 'prediction' : 'box',
  x: props.box.x1,
  y: props.box.y1,
  width: width.value,
  height: height.value,
  stroke: color.value,
  // stroke width in screen pixels, independent of zoom
  strokeWidth: props.selected ? 3 : hover.value ? 2.5 : 2,
  strokeScaleEnabled: false,
  dash: props.prediction
    ? [8 / props.scale, 5 / props.scale]
    : hardNegative.value
      ? [3 / props.scale, 3 / props.scale]
      : ignored.value
        ? [10 / props.scale, 4 / props.scale]
        : reflected.value
          ? [12 / props.scale, 3 / props.scale, 2 / props.scale, 3 / props.scale]
          : undefined,
  fill: props.prediction
    ? 'rgba(255,255,255,0.04)'
    : ignored.value
      ? props.selected ? 'rgba(148,163,184,0.45)' : 'rgba(148,163,184,0.3)'
      : hardNegative.value
      ? props.selected ? 'rgba(0,0,0,0.5)' : 'rgba(0,0,0,0.35)'
      : props.selected ? `${color.value}33` : `${color.value}14`,
  draggable: !props.prediction,
  shadowForStrokeEnabled: false,
  perfectDrawEnabled: false,
}))

const fontSize = computed(() => 12 / props.scale)
const labelY = computed(() => Math.max(0, props.box.y1 - fontSize.value - 6 / props.scale))
const labelText = computed(() => {
  const info = classes.info(props.box.class)
  if (props.prediction && 'confidence' in props.box) return `⚡ ${info.label} ${(props.box.confidence * 100).toFixed(0)}%`
  if (hardNegative.value) return `⊘ HN: kein(e) ${info.label}`
  const suffix = reflected.value ? ' ⇋ Spiegelung' : ''
  if (ignored.value) return `∅ ignorieren${suffix}`
  return (props.box.source === 'prediction' ? `${info.label} ✓` : info.label) + suffix
})
const textConfig = computed(() => ({
  text: labelText.value,
  fontSize: fontSize.value,
  padding: 3 / props.scale,
  fill: 'white',
  fontFamily: 'Inter, system-ui, sans-serif',
  fontStyle: props.prediction ? 'italic' : 'bold',
}))

function onSelect() {
  emit('select', props.box.uid)
}

function onDblClick() {
  if (props.prediction) emit('accept', props.box.uid)
}

// eslint-disable-next-line @typescript-eslint/no-explicit-any
function onDragMove(e: any) {
  const node = e.target
  node.x(Math.max(0, Math.min(props.imageWidth - node.width(), node.x())))
  node.y(Math.max(0, Math.min(props.imageHeight - node.height(), node.y())))
  live.value = { x: node.x(), y: node.y(), w: node.width(), h: node.height() }
}

// eslint-disable-next-line @typescript-eslint/no-explicit-any
function onTransform(e: any) {
  const node = e.target
  live.value = { x: node.x(), y: node.y(), w: node.width() * node.scaleX(), h: node.height() * node.scaleY() }
}

// eslint-disable-next-line @typescript-eslint/no-explicit-any
function onDragEnd(e: any) {
  const node = e.target
  live.value = null
  emit('change', props.box.uid, { x1: node.x(), y1: node.y(), x2: node.x() + node.width(), y2: node.y() + node.height() })
}

// eslint-disable-next-line @typescript-eslint/no-explicit-any
function onTransformEnd(e: any) {
  const node = e.target
  const w = Math.max(1, node.width() * node.scaleX())
  const h = Math.max(1, node.height() * node.scaleY())
  node.scaleX(1)
  node.scaleY(1)
  live.value = null
  emit('change', props.box.uid, { x1: node.x(), y1: node.y(), x2: node.x() + w, y2: node.y() + h })
}
</script>
