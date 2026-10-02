import { defineStore } from 'pinia'
import { computed, ref } from 'vue'
import { api, type ClassName, type DetectResponse, type ImageDetail } from '@/services/api'
import { useClassesStore } from './classes'

/** A box being edited in the UI (original image pixel coordinates). */
export interface EditBox {
  uid: string
  class: ClassName
  x1: number
  y1: number
  x2: number
  y2: number
  source: 'manual' | 'prediction'
}

export interface Prediction extends EditBox {
  confidence: number
}

let counter = 0
const uid = (prefix: string) => `${prefix}-${Date.now().toString(36)}-${(counter++).toString(36)}`

const MAX_HISTORY = 100

export const useAnnotationStore = defineStore('annotation', () => {
  const image = ref<ImageDetail | null>(null)
  const boxes = ref<EditBox[]>([])
  const predictions = ref<Prediction[]>([])
  const lastDetection = ref<DetectResponse | null>(null)
  const selectedId = ref<string | null>(null)
  const activeClass = ref<ClassName>('')
  const dirty = ref(false)
  const saving = ref(false)
  const history = ref<string[]>([])

  const selectedBox = computed(() => boxes.value.find((b) => b.uid === selectedId.value) ?? null)
  const selectedPrediction = computed(() => predictions.value.find((p) => p.uid === selectedId.value) ?? null)

  function snapshot() {
    history.value.push(JSON.stringify(boxes.value))
    if (history.value.length > MAX_HISTORY) history.value.shift()
  }

  function load(detail: ImageDetail) {
    image.value = detail
    boxes.value = detail.annotations.map((a) => ({
      uid: uid('a'),
      class: a.class,
      x1: a.x1,
      y1: a.y1,
      x2: a.x2,
      y2: a.y2,
      source: a.source,
    }))
    predictions.value = []
    lastDetection.value = null
    selectedId.value = null
    history.value = []
    dirty.value = false
  }

  function clamp(b: EditBox): EditBox {
    const w = image.value?.width ?? Infinity
    const h = image.value?.height ?? Infinity
    const x1 = Math.max(0, Math.min(b.x1, b.x2))
    const x2 = Math.min(w, Math.max(b.x1, b.x2))
    const y1 = Math.max(0, Math.min(b.y1, b.y2))
    const y2 = Math.min(h, Math.max(b.y1, b.y2))
    return { ...b, x1, y1, x2, y2 }
  }

  function addBox(box: Omit<EditBox, 'uid'>) {
    snapshot()
    const b = clamp({ ...box, uid: uid('a') })
    boxes.value.push(b)
    selectedId.value = b.uid
    dirty.value = true
    return b
  }

  function updateBox(id: string, patch: Partial<EditBox>) {
    const i = boxes.value.findIndex((b) => b.uid === id)
    if (i < 0) return
    snapshot()
    boxes.value[i] = clamp({ ...boxes.value[i], ...patch })
    dirty.value = true
  }

  function deleteSelected() {
    if (!selectedId.value) return
    if (selectedPrediction.value) {
      predictions.value = predictions.value.filter((p) => p.uid !== selectedId.value)
      selectedId.value = null
      return
    }
    snapshot()
    boxes.value = boxes.value.filter((b) => b.uid !== selectedId.value)
    selectedId.value = null
    dirty.value = true
  }

  function setClassForSelected(cls: ClassName) {
    activeClass.value = cls
    if (selectedBox.value) updateBox(selectedBox.value.uid, { class: cls })
  }

  function undo() {
    const prev = history.value.pop()
    if (prev === undefined) return
    boxes.value = JSON.parse(prev)
    selectedId.value = null
    dirty.value = true
  }

  function setDetection(res: DetectResponse) {
    lastDetection.value = res
    predictions.value = res.detections.map((d) => ({
      uid: uid('p'),
      class: d.class,
      confidence: d.confidence,
      x1: d.bbox.x1,
      y1: d.bbox.y1,
      x2: d.bbox.x2,
      y2: d.bbox.y2,
      source: 'prediction',
    }))
    if (selectedId.value?.startsWith('p-')) selectedId.value = null
  }

  /** Turn a prediction into a normal, editable annotation. */
  /** Predictions of classes that are unknown/inactive here cannot become annotations. */
  function acceptable(p: Prediction) {
    return useClassesStore().info(p.class).active
  }

  function acceptPrediction(id: string) {
    const p = predictions.value.find((x) => x.uid === id)
    if (!p || !acceptable(p)) return
    const b = addBox({ class: p.class, x1: p.x1, y1: p.y1, x2: p.x2, y2: p.y2, source: 'prediction' })
    predictions.value = predictions.value.filter((x) => x.uid !== id)
    selectedId.value = b.uid
  }

  function acceptAllPredictions() {
    const accepted = predictions.value.filter(acceptable)
    if (!accepted.length) return
    snapshot()
    for (const p of accepted) {
      boxes.value.push(clamp({ uid: uid('a'), class: p.class, x1: p.x1, y1: p.y1, x2: p.x2, y2: p.y2, source: 'prediction' }))
    }
    predictions.value = predictions.value.filter((p) => !acceptable(p))
    selectedId.value = null
    dirty.value = true
  }

  function clearPredictions() {
    predictions.value = []
    lastDetection.value = null
  }

  async function save(markLabeled = true) {
    if (!image.value) return
    saving.value = true
    try {
      const detail = await api.saveAnnotations(
        image.value.id,
        boxes.value.map((b) => ({
          class: b.class,
          x1: Math.round(b.x1 * 10) / 10,
          y1: Math.round(b.y1 * 10) / 10,
          x2: Math.round(b.x2 * 10) / 10,
          y2: Math.round(b.y2 * 10) / 10,
          source: b.source,
        })),
        markLabeled,
      )
      const preds = predictions.value
      const det = lastDetection.value
      load(detail)
      predictions.value = preds
      lastDetection.value = det
    } finally {
      saving.value = false
    }
  }

  return {
    image, boxes, predictions, lastDetection, selectedId, activeClass, dirty, saving, history,
    selectedBox, selectedPrediction,
    load, addBox, updateBox, deleteSelected, setClassForSelected, undo,
    setDetection, acceptable, acceptPrediction, acceptAllPredictions, clearPredictions, save,
  }
})
