<template>
  <div ref="container" class="annotation-canvas" :style="{ cursor }" @contextmenu.prevent>
    <v-stage
      v-if="size.w > 0"
      ref="stageRef"
      :config="stageConfig"
      @mousedown="onMouseDown"
      @mousemove="onMouseMove"
      @mouseup="onMouseUp"
      @mouseleave="onMouseUp"
      @wheel="onWheel"
    >
      <v-layer :config="{ imageSmoothingEnabled: view.scale < 2 }">
        <v-image v-if="img" :config="{ image: img, width: imageWidth, height: imageHeight, name: 'background' }" />
      </v-layer>
      <v-layer>
        <template v-if="showPredictions">
          <!-- error analysis: annotations the model missed (false negatives), drawn around the box -->
          <template v-for="(m, i) in missed ?? []" :key="`missed-${i}`">
            <v-rect :config="missedConfig(m)" />
            <v-text :config="missedLabel(m)" />
          </template>
          <BoundingBox
            v-for="p in predictions"
            :key="p.uid"
            :box="p"
            :scale="view.scale"
            :selected="p.uid === selectedId"
            :image-width="imageWidth"
            :image-height="imageHeight"
            prediction
            @select="(id) => emit('select', id)"
            @accept="(id) => emit('accept', id)"
          />
        </template>
        <BoundingBox
          v-for="b in boxes"
          :key="b.uid"
          :box="b"
          :scale="view.scale"
          :selected="b.uid === selectedId"
          :image-width="imageWidth"
          :image-height="imageHeight"
          @select="(id) => emit('select', id)"
          @change="(id, c) => emit('change', id, c)"
        />
        <v-rect v-if="draft" :config="draftConfig" />
        <v-transformer ref="transformerRef" :config="transformerConfig" />
      </v-layer>
    </v-stage>
    <!-- the selected suggestion: yes (accept) / no (hard negative) / delete (discard), right below its box -->
    <div v-if="actionBar" class="prediction-actions row no-wrap items-center" :style="actionBar.style" @mousedown.stop @wheel.stop>
      <q-btn dense unelevated round size="sm" color="positive" icon="check" :disable="!actionBar.usable" @click="emit('accept', actionBar.uid)">
        <q-tooltip>Ja – als Annotation übernehmen (Enter)</q-tooltip>
      </q-btn>
      <q-btn dense unelevated round size="sm" color="negative" icon="block" :disable="!actionBar.usable" @click="emit('reject', actionBar.uid)">
        <q-tooltip>Nein – Fehlalarm, als Hard Negative speichern (N)</q-tooltip>
      </q-btn>
      <q-btn dense unelevated round size="sm" color="grey-7" icon="delete" @click="emit('discard', actionBar.uid)">
        <q-tooltip>Löschen – Vorschlag verwerfen (Entf)</q-tooltip>
      </q-btn>
    </div>
    <div v-if="loading" class="absolute-center text-white">
      <q-spinner size="48px" />
    </div>
    <div class="canvas-hud text-caption">
      {{ Math.round((view.scale / fitScale) * 100) }}% · Ziehen = neue Box · Mausrad = Zoom · Leertaste/Mitteltaste/Rechtsklick + Ziehen = verschieben
      <q-btn dense flat size="sm" class="text-muted" icon="fit_screen" label="Einpassen" @click="fit" />
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import BoundingBox from './BoundingBox.vue'
import type { ClassName } from '@/services/api'
import { useClassesStore } from '@/stores/classes'
import type { EditBox, Prediction } from '@/stores/annotation'

const props = defineProps<{
  imageUrl: string | null
  imageWidth: number
  imageHeight: number
  boxes: EditBox[]
  predictions: Prediction[]
  selectedId: string | null
  activeClass: ClassName
  showPredictions: boolean
  /** error analysis: annotation boxes the model did not detect */
  missed?: { x1: number; y1: number; x2: number; y2: number }[]
}>()

const emit = defineEmits<{
  select: [uid: string | null]
  change: [uid: string, coords: { x1: number; y1: number; x2: number; y2: number }]
  create: [coords: { x1: number; y1: number; x2: number; y2: number }]
  accept: [uid: string]
  /** false positive of the model: store as hard negative */
  reject: [uid: string]
  /** drop the suggestion without storing anything */
  discard: [uid: string]
}>()

const classes = useClassesStore()
const MIN_BOX_PX = 3 // minimum box size in original image pixels

const container = ref<HTMLDivElement | null>(null)
// eslint-disable-next-line @typescript-eslint/no-explicit-any
const stageRef = ref<any>(null)
// eslint-disable-next-line @typescript-eslint/no-explicit-any
const transformerRef = ref<any>(null)
const img = ref<HTMLImageElement | null>(null)
const loading = ref(false)
const size = reactive({ w: 0, h: 0 })
const view = reactive({ scale: 1, x: 0, y: 0 })
const fitScale = ref(1)
const draft = ref<{ x1: number; y1: number; x2: number; y2: number } | null>(null)
const panning = ref<{ x: number; y: number } | null>(null)
const spaceDown = ref(false)

const stageConfig = computed(() => ({
  width: size.w,
  height: size.h,
  scaleX: view.scale,
  scaleY: view.scale,
  x: view.x,
  y: view.y,
}))

const BAR_W = 108 // px, three round buttons
const BAR_H = 34
const actionBar = computed(() => {
  const p = props.showPredictions ? props.predictions.find((x) => x.uid === props.selectedId) : undefined
  if (!p || draft.value || panning.value) return null
  const left = Math.max(4, Math.min(size.w - BAR_W - 4, view.x + p.x1 * view.scale))
  let top = view.y + p.y2 * view.scale + 6
  if (top + BAR_H > size.h - 4) top = Math.max(4, view.y + p.y1 * view.scale - BAR_H - 6) // no room below: above the box
  return { uid: p.uid, usable: classes.info(p.class).active, style: { left: `${left}px`, top: `${top}px` } }
})

const cursor = computed(() => (panning.value ? 'grabbing' : spaceDown.value ? 'grab' : 'crosshair'))

const draftConfig = computed(() => {
  const d = draft.value!
  return {
    x: Math.min(d.x1, d.x2),
    y: Math.min(d.y1, d.y2),
    width: Math.abs(d.x2 - d.x1),
    height: Math.abs(d.y2 - d.y1),
    stroke: classes.info(props.activeClass).color,
    strokeWidth: 2,
    strokeScaleEnabled: false,
    dash: [6 / view.scale, 4 / view.scale],
    listening: false,
  }
})

const MISSED_COLOR = '#ff1744'
function missedConfig(m: { x1: number; y1: number; x2: number; y2: number }) {
  const pad = 4 / view.scale
  return {
    x: m.x1 - pad,
    y: m.y1 - pad,
    width: m.x2 - m.x1 + 2 * pad,
    height: m.y2 - m.y1 + 2 * pad,
    stroke: MISSED_COLOR,
    strokeWidth: 3,
    strokeScaleEnabled: false,
    dash: [3 / view.scale, 3 / view.scale],
    listening: false,
  }
}
function missedLabel(m: { x1: number; y1: number; x2: number; y2: number }) {
  return {
    x: m.x1 - 4 / view.scale,
    y: m.y2 + 6 / view.scale,
    text: 'nicht erkannt',
    fontSize: 12 / view.scale,
    fontStyle: 'bold',
    fill: MISSED_COLOR,
    listening: false,
  }
}

const transformerConfig = computed(() => ({
  rotateEnabled: false,
  flipEnabled: false,
  keepRatio: false,
  ignoreStroke: true,
  anchorSize: 9,
  borderStroke: '#ffffff',
  anchorStroke: '#333',
  anchorFill: '#fff',
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  boundBoxFunc: (oldBox: any, newBox: any) =>
    newBox.width < MIN_BOX_PX * view.scale || newBox.height < MIN_BOX_PX * view.scale ? oldBox : newBox,
}))

// ---- image loading & fitting ------------------------------------------------
watch(
  () => props.imageUrl,
  (url) => {
    img.value = null
    if (!url) return
    loading.value = true
    const el = new window.Image()
    el.onload = () => {
      if (props.imageUrl === url) {
        img.value = el
        loading.value = false
        fit()
      }
    }
    el.onerror = () => (loading.value = false)
    el.src = url
  },
  { immediate: true },
)

function fit() {
  if (!size.w || !props.imageWidth) return
  const s = Math.min(size.w / props.imageWidth, size.h / props.imageHeight) * 0.98
  fitScale.value = s
  view.scale = s
  view.x = (size.w - props.imageWidth * s) / 2
  view.y = (size.h - props.imageHeight * s) / 2
}

let observer: ResizeObserver | null = null
onMounted(() => {
  observer = new ResizeObserver(() => {
    if (!container.value) return
    const r = container.value.getBoundingClientRect()
    const changed = Math.round(r.width) !== size.w || Math.round(r.height) !== size.h
    size.w = Math.round(r.width)
    size.h = Math.round(r.height)
    if (changed) fit()
  })
  if (container.value) observer.observe(container.value)
  window.addEventListener('keydown', onKey)
  window.addEventListener('keyup', onKey)
})
onBeforeUnmount(() => {
  observer?.disconnect()
  window.removeEventListener('keydown', onKey)
  window.removeEventListener('keyup', onKey)
})

function onKey(e: KeyboardEvent) {
  if (e.code !== 'Space') return
  const t = e.target as HTMLElement | null
  if (t && (t.tagName === 'INPUT' || t.tagName === 'TEXTAREA')) return
  e.preventDefault()
  spaceDown.value = e.type === 'keydown'
}

// ---- transformer follows the selected box ----------------------------------------
function syncTransformer() {
  const tr = transformerRef.value?.getNode()
  const stage = stageRef.value?.getNode()
  if (!tr || !stage) return
  const node = props.selectedId ? stage.findOne('#' + props.selectedId) : null
  tr.nodes(node && node.name() === 'box' ? [node] : [])
  tr.getLayer()?.batchDraw()
}
watch(() => [props.selectedId, props.boxes], () => nextTick(syncTransformer), { deep: true })

// ---- mouse handling ------------------------------------------------------------------
function imagePointer() {
  const stage = stageRef.value?.getNode()
  const p = stage?.getRelativePointerPosition()
  if (!p) return null
  return {
    x: Math.max(0, Math.min(props.imageWidth, p.x)),
    y: Math.max(0, Math.min(props.imageHeight, p.y)),
  }
}

// eslint-disable-next-line @typescript-eslint/no-explicit-any
function onMouseDown(e: any) {
  const evt: MouseEvent = e.evt
  if (evt.button === 1 || evt.button === 2 || spaceDown.value) {
    panning.value = { x: evt.clientX, y: evt.clientY }
    evt.preventDefault()
    return
  }
  if (evt.button !== 0) return
  const target = e.target
  const onShape = target.name() === 'box' || target.name() === 'prediction' || target.getParent()?.className === 'Transformer'
  if (onShape) return // handled by the box (select/drag/resize)
  const p = imagePointer()
  if (!p) return
  emit('select', null)
  draft.value = { x1: p.x, y1: p.y, x2: p.x, y2: p.y }
}

// eslint-disable-next-line @typescript-eslint/no-explicit-any
function onMouseMove(e: any) {
  const evt: MouseEvent = e.evt
  if (panning.value) {
    view.x += evt.clientX - panning.value.x
    view.y += evt.clientY - panning.value.y
    panning.value = { x: evt.clientX, y: evt.clientY }
    return
  }
  if (draft.value) {
    const p = imagePointer()
    if (p) draft.value = { ...draft.value, x2: p.x, y2: p.y }
  }
}

function onMouseUp() {
  panning.value = null
  const d = draft.value
  draft.value = null
  if (!d) return
  const box = { x1: Math.min(d.x1, d.x2), y1: Math.min(d.y1, d.y2), x2: Math.max(d.x1, d.x2), y2: Math.max(d.y1, d.y2) }
  if (box.x2 - box.x1 >= MIN_BOX_PX && box.y2 - box.y1 >= MIN_BOX_PX) emit('create', box)
}

// eslint-disable-next-line @typescript-eslint/no-explicit-any
function onWheel(e: any) {
  const evt: WheelEvent = e.evt
  evt.preventDefault()
  const stage = stageRef.value?.getNode()
  const pointer = stage?.getPointerPosition()
  if (!pointer) return
  const factor = evt.deltaY < 0 ? 1.15 : 1 / 1.15
  const newScale = Math.max(fitScale.value * 0.5, Math.min(fitScale.value * 20, view.scale * factor))
  const mx = (pointer.x - view.x) / view.scale
  const my = (pointer.y - view.y) / view.scale
  view.scale = newScale
  view.x = pointer.x - mx * newScale
  view.y = pointer.y - my * newScale
}

defineExpose({ fit })
</script>

<style scoped>
.annotation-canvas {
  position: relative;
  width: 100%;
  height: 100%;
  background-color: var(--app-bg);
  background-image: linear-gradient(var(--app-border) 1px, transparent 1px), linear-gradient(90deg, var(--app-border) 1px, transparent 1px);
  background-size: 24px 24px;
  overflow: hidden;
  user-select: none;
}
.prediction-actions {
  position: absolute;
  gap: 6px;
  padding: 4px 6px;
  background: var(--app-panel);
  border: 1px solid var(--app-border);
  border-radius: 999px;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.35);
}
.canvas-hud {
  position: absolute;
  left: 16px;
  bottom: 16px;
  color: var(--app-muted);
  background: var(--app-panel);
  border: 1px solid var(--app-border);
  padding: 4px 4px 4px 12px;
  border-radius: 8px;
}
</style>
