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
    <div v-if="loading" class="absolute-center text-white">
      <q-spinner size="48px" />
    </div>
    <div class="canvas-hud text-caption">
      {{ Math.round((view.scale / fitScale) * 100) }}% · Ziehen = neue Box · Mausrad = Zoom · Leertaste/Mitteltaste/Rechtsklick + Ziehen = verschieben
      <q-btn dense flat size="sm" color="white" icon="fit_screen" label="Einpassen" @click="fit" />
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
}>()

const emit = defineEmits<{
  select: [uid: string | null]
  change: [uid: string, coords: { x1: number; y1: number; x2: number; y2: number }]
  create: [coords: { x1: number; y1: number; x2: number; y2: number }]
  accept: [uid: string]
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
  background: #263238;
  overflow: hidden;
  user-select: none;
}
.canvas-hud {
  position: absolute;
  left: 8px;
  bottom: 6px;
  color: #cfd8dc;
  background: rgba(0, 0, 0, 0.45);
  padding: 2px 8px;
  border-radius: 4px;
}
</style>
