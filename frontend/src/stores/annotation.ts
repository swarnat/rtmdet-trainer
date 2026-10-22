import { defineStore } from 'pinia'
import { computed, ref } from 'vue'
import { api, type AnnotationInput, type AnnotationType, type ClassName, type DetectResponse, type ImageDetail } from '@/services/api'
import { useClassesStore } from './classes'

/** A box being edited in the UI (original image pixel coordinates). */
export interface EditBox {
  uid: string
  class: ClassName
  x1: number
  y1: number
  x2: number
  y2: number
  type: AnnotationType
  /** reflection (window, mirror ...): only marked, trained like any other box */
  reflected?: boolean
  source: 'manual' | 'prediction'
  source_confidence?: number | null
  source_model?: string | null
}

export interface Prediction extends EditBox {
  confidence: number
}

/** Stores the boxes of an image and returns it again (default: the training system's API). */
export type AnnotationSaver = (id: number, annotations: AnnotationInput[], markLabeled: boolean) => Promise<ImageDetail>

let counter = 0
const uid = (prefix: string) => `${prefix}-${Date.now().toString(36)}-${(counter++).toString(36)}`

const MAX_HISTORY = 100

export const useAnnotationStore = defineStore('annotation', () => {
  const image = ref<ImageDetail | null>(null)
  const boxes = ref<EditBox[]>([])
  const predictions = ref<Prediction[]>([])
  const lastDetection = ref<DetectResponse | null>(null)
  /** predictions shown come from a stored batch-test suggestion (not a live test) */
  const fromSuggestion = ref<ImageDetail['suggestion']>(null)
  /** predictions shown are the false positives of an error analysis; its false negatives are highlighted */
  const fromErrorMark = ref<ImageDetail['error_mark']>(null)
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
      type: a.type,
      reflected: a.reflected ?? false,
      source: a.source,
      source_confidence: a.source_confidence,
      source_model: a.source_model,
    }))
    predictions.value = []
    lastDetection.value = null
    fromSuggestion.value = null
    fromErrorMark.value = null
    selectedId.value = null
    history.value = []
    dirty.value = false
    if (detail.error_mark) loadErrorMark(detail)
    else if (detail.suggestion) loadSuggestion(detail)
  }

  /** Show the false positives of an error analysis as predictions (accept = missing annotation, N = hard negative),
   *  minus those already covered by a box (positive or hard negative) of the same class. */
  function loadErrorMark(detail: ImageDetail) {
    const m = detail.error_mark!
    setDetection({
      image: { width: detail.width, height: detail.height },
      model: { version: m.model_version, status: 'analysis', input_width: m.input_width, input_height: m.input_height },
      inference_ms: 0,
      detections: m.false_positives.filter(
        (d) => !boxes.value.some((b) => b.class === d.class && iou(b, d.bbox) >= 0.5),
      ),
    })
    fromErrorMark.value = m
  }

  /** Show batch-test suggestions as predictions, minus those already covered by a box of the same class. */
  function loadSuggestion(detail: ImageDetail) {
    const s = detail.suggestion!
    setDetection({
      image: { width: detail.width, height: detail.height },
      model: { version: s.model_version, status: 'batch', input_width: s.input_width, input_height: s.input_height },
      inference_ms: 0,
      detections: s.detections.filter(
        (d) => !boxes.value.some((b) => b.class === d.class && iou(b, d.bbox) >= 0.5),
      ),
    })
    fromSuggestion.value = s
  }

  function iou(a: { x1: number; y1: number; x2: number; y2: number }, b: { x1: number; y1: number; x2: number; y2: number }) {
    const iw = Math.max(0, Math.min(a.x2, b.x2) - Math.max(a.x1, b.x1))
    const ih = Math.max(0, Math.min(a.y2, b.y2) - Math.max(a.y1, b.y1))
    const inter = iw * ih
    const union = (a.x2 - a.x1) * (a.y2 - a.y1) + (b.x2 - b.x1) * (b.y2 - b.y1) - inter
    return union > 0 ? inter / union : 0
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

  function discardPrediction(id: string) {
    predictions.value = predictions.value.filter((p) => p.uid !== id)
    if (selectedId.value === id) selectedId.value = null
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

  /** Object <-> ignore region (neither object nor background: not trained, not evaluated). */
  function toggleIgnoreForSelected() {
    const b = selectedBox.value
    if (b) updateBox(b.uid, { type: b.type === 'ignore' ? 'positive' : 'ignore' })
  }

  function toggleReflectedForSelected() {
    const b = selectedBox.value
    if (b) updateBox(b.uid, { reflected: !b.reflected })
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
    fromSuggestion.value = null
    fromErrorMark.value = null
    predictions.value = res.detections.map((d) => ({
      uid: uid('p'),
      class: d.class,
      confidence: d.confidence,
      x1: d.bbox.x1,
      y1: d.bbox.y1,
      x2: d.bbox.x2,
      y2: d.bbox.y2,
      type: 'positive',
      source: 'prediction',
      source_model: res.model.version,
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
    const b = addBox({ class: p.class, x1: p.x1, y1: p.y1, x2: p.x2, y2: p.y2, type: 'positive', source: 'prediction' })
    predictions.value = predictions.value.filter((x) => x.uid !== id)
    selectedId.value = b.uid
  }

  /** False positive of the model: store the region as hard negative of the predicted class. */
  function markHardNegative(id: string) {
    const p = predictions.value.find((x) => x.uid === id)
    if (!p || !acceptable(p)) return
    const b = addBox({
      class: p.class, x1: p.x1, y1: p.y1, x2: p.x2, y2: p.y2,
      type: 'hard_negative', source: 'prediction', source_confidence: p.confidence, source_model: p.source_model ?? null,
    })
    predictions.value = predictions.value.filter((x) => x.uid !== id)
    selectedId.value = b.uid
  }

  function acceptAllPredictions() {
    const accepted = predictions.value.filter(acceptable)
    if (!accepted.length) return
    snapshot()
    for (const p of accepted) {
      boxes.value.push(clamp({ uid: uid('a'), class: p.class, x1: p.x1, y1: p.y1, x2: p.x2, y2: p.y2, type: 'positive', source: 'prediction' }))
    }
    predictions.value = predictions.value.filter((p) => !acceptable(p))
    selectedId.value = null
    dirty.value = true
  }

  function clearPredictions() {
    predictions.value = []
    lastDetection.value = null
    fromSuggestion.value = null
    fromErrorMark.value = null
  }

  async function save(markLabeled = true, saver: AnnotationSaver = api.saveAnnotations) {
    // a save is already running (double click, held Ctrl+S): ignore, the running one stores the same boxes
    if (!image.value || saving.value) return false
    saving.value = true
    try {
      const detail = await saver(
        image.value.id,
        boxes.value.map((b) => ({
          class: b.class,
          x1: Math.round(b.x1 * 10) / 10,
          y1: Math.round(b.y1 * 10) / 10,
          x2: Math.round(b.x2 * 10) / 10,
          y2: Math.round(b.y2 * 10) / 10,
          type: b.type,
          reflected: b.reflected ?? false,
          source: b.source,
          source_confidence: b.source_confidence ?? null,
          source_model: b.source_model ?? null,
        })),
        markLabeled,
      )
      const preds = predictions.value
      const det = lastDetection.value
      const sug = fromSuggestion.value
      const mark = fromErrorMark.value
      load(detail)
      predictions.value = preds
      lastDetection.value = det
      fromSuggestion.value = sug
      fromErrorMark.value = mark
      return true
    } finally {
      saving.value = false
    }
  }

  return {
    image, boxes, predictions, lastDetection, fromSuggestion, fromErrorMark, selectedId, activeClass, dirty, saving, history,
    selectedBox, selectedPrediction,
    load, addBox, updateBox, deleteSelected, toggleIgnoreForSelected, toggleReflectedForSelected, setClassForSelected, undo,
    setDetection, acceptable, acceptPrediction, markHardNegative, discardPrediction, acceptAllPredictions, clearPredictions, save,
  }
})
