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
      @transformend="onTransformEnd"
      @mouseenter="hover = true"
      @mouseleave="hover = false"
    />
    <v-label :config="{ x: box.x1, y: labelY, listening: false, opacity: prediction && !selected ? 0.8 : 1 }">
      <v-tag :config="{ fill: hardNegative ? '#0f172a' : color, stroke: hardNegative ? color : undefined, strokeWidth: 1, cornerRadius: 2 / scale }" />
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
const color = computed(() => classes.info(props.box.class).color)
// hard negative = known false positive of the model (never a real object)
const hardNegative = computed(() => !props.prediction && props.box.type === 'hard_negative')
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
  dash: props.prediction ? [8 / props.scale, 5 / props.scale] : hardNegative.value ? [3 / props.scale, 3 / props.scale] : undefined,
  fill: props.prediction
    ? 'rgba(255,255,255,0.04)'
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
  return props.box.source === 'prediction' ? `${info.label} ✓` : info.label
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
}

// eslint-disable-next-line @typescript-eslint/no-explicit-any
function onDragEnd(e: any) {
  const node = e.target
  emit('change', props.box.uid, { x1: node.x(), y1: node.y(), x2: node.x() + node.width(), y2: node.y() + node.height() })
}

// eslint-disable-next-line @typescript-eslint/no-explicit-any
function onTransformEnd(e: any) {
  const node = e.target
  const w = Math.max(1, node.width() * node.scaleX())
  const h = Math.max(1, node.height() * node.scaleY())
  node.scaleX(1)
  node.scaleY(1)
  emit('change', props.box.uid, { x1: node.x(), y1: node.y(), x2: node.x() + w, y2: node.y() + h })
}
</script>
