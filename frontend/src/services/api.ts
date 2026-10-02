// Typed client for the FastAPI backend (/api/v1)

export type ClassName = 'person' | 'bicycle' | 'vehicle'

export const CLASSES: { name: ClassName; label: string; color: string; key: string }[] = [
  { name: 'person', label: 'Person', color: '#e53935', key: '1' },
  { name: 'bicycle', label: 'Fahrrad', color: '#1e88e5', key: '2' },
  { name: 'vehicle', label: 'Fahrzeug', color: '#fb8c00', key: '3' },
]

export function classInfo(name: string) {
  return CLASSES.find((c) => c.name === name) ?? { name, label: name, color: '#9e9e9e', key: '' }
}

export interface Annotation {
  id: number
  class: ClassName
  x1: number
  y1: number
  x2: number
  y2: number
  source: 'manual' | 'prediction'
  created_at: string
  updated_at: string
}

export interface AnnotationInput {
  class: ClassName
  x1: number
  y1: number
  x2: number
  y2: number
  source: 'manual' | 'prediction'
}

export interface ImageItem {
  id: number
  sha256: string
  original_filename: string | null
  content_type: string
  size_bytes: number
  width: number
  height: number
  annotation_status: 'unlabeled' | 'labeled'
  dataset_split: 'train' | 'validation' | null
  annotation_count: number
  created_at: string
  updated_at: string
  labeled_at: string | null
}

export interface ImageDetail extends ImageItem {
  annotations: Annotation[]
}

export interface UploadResult {
  filename: string | null
  status: 'created' | 'duplicate' | 'error'
  image: ImageItem | null
  error: string | null
}

export interface DetectionItem {
  class: ClassName
  confidence: number
  bbox: { x1: number; y1: number; x2: number; y2: number }
}

export interface DetectResponse {
  image: { width: number; height: number }
  model: { version: string; status: string; input_width: number; input_height: number }
  inference_ms: number
  detections: DetectionItem[]
}

export interface MetricSet {
  precision: number | null
  recall: number | null
  mAP50: number | null
  'mAP50-95': number | null
  tp?: number | null
  fp?: number | null
  fn?: number | null
  small?: { mAP50: number | null; 'mAP50-95': number | null }
}

export interface Metrics {
  evaluated_with?: string
  input_size?: string
  num_images?: number
  num_boxes?: number
  confidence_for_pr?: number
  overall?: MetricSet
  per_class?: Record<string, MetricSet>
  per_size?: Record<string, MetricSet>
  mmdet_val_history?: { epoch: number; bbox_mAP?: number; bbox_mAP_50?: number; bbox_mAP_s?: number }[]
  note?: string
}

export interface ModelVersion {
  id: number
  version: string
  status: 'candidate' | 'production' | 'archived'
  kind: string
  architecture: string
  checkpoint_key: string
  onnx_key: string
  openvino_key: string
  config_key: string | null
  input_width: number
  input_height: number
  class_names: string[]
  class_mapping_json: Record<string, string[]> | null
  metrics_json: Metrics | null
  dataset_snapshot: string | null
  training_run_id: number | null
  notes: string | null
  created_at: string
  activated_at: string | null
}

export interface TrainingProgress {
  phase?: string
  epoch?: number
  max_epochs?: number
  iter?: number
  max_iters?: number
  loss?: number | null
  lr?: number
  percent?: number
  eta_seconds?: number | null
  val_history?: { epoch: number; bbox_mAP?: number; bbox_mAP_50?: number }[]
}

export interface TrainingRun {
  id: number
  status: 'queued' | 'running' | 'completed' | 'failed'
  base_model_id: string
  dataset_snapshot: string | null
  dataset_stats_json: Record<string, { images: number; negative_images: number; boxes: number; boxes_per_class: Record<string, number> }> | null
  input_width: number
  input_height: number
  epochs: number
  batch_size: number
  learning_rate: number | null
  params_json: Record<string, unknown> | null
  progress_json: TrainingProgress | null
  metrics_json: Metrics | null
  error: string | null
  model_version: string | null
  created_at: string
  started_at: string | null
  finished_at: string | null
}

export interface BaseModelOption {
  id: string
  label: string
  description: string
}

export interface DatasetStats {
  images_total: number
  images_labeled: number
  images_unlabeled: number
  images_negative: number
  splits: { train: number; validation: number }
  annotations_per_class: Record<string, number>
}

export type Settings = Record<string, unknown> & {
  default_input_size: string
  input_sizes: string[]
  default_confidence: number
  nms_iou_threshold: number
  validation_ratio: number
  eval_confidence: number
  coco_class_mapping: Record<string, string[]>
}

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message)
  }
}

const BASE = '/api/v1'

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const res = await fetch(BASE + path, init)
  if (!res.ok) {
    let detail = res.statusText
    try {
      const body = await res.json()
      detail = typeof body.detail === 'string' ? body.detail : JSON.stringify(body.detail)
    } catch {
      /* not JSON */
    }
    throw new ApiError(res.status, detail || `HTTP ${res.status}`)
  }
  if (res.status === 204) return undefined as T
  return (await res.json()) as T
}

function json(method: string, body?: unknown): RequestInit {
  return {
    method,
    headers: { 'Content-Type': 'application/json' },
    body: body === undefined ? undefined : JSON.stringify(body),
  }
}

export interface DetectOptions {
  model?: string | null
  input_size?: string | null
  confidence?: number | null
}

function detectForm(opts: DetectOptions, form = new FormData()) {
  if (opts.model) form.append('model', opts.model)
  if (opts.input_size) form.append('input_size', opts.input_size)
  if (opts.confidence != null) form.append('confidence', String(opts.confidence))
  return form
}

export const api = {
  // images
  listImages(params: { status?: string; split?: string; negative?: boolean; offset?: number; limit?: number }) {
    const q = new URLSearchParams()
    Object.entries(params).forEach(([k, v]) => {
      if (v !== undefined && v !== null && v !== '' && v !== false) q.set(k, String(v))
    })
    return request<{ total: number; items: ImageItem[] }>(`/images?${q}`)
  },
  getImage: (id: number) => request<ImageDetail>(`/images/${id}`),
  neighbours: (id: number, status?: string) =>
    request<{ previous: number | null; next: number | null }>(`/images/${id}/neighbours${status ? `?status=${status}` : ''}`),
  imageUrl: (id: number) => `${BASE}/images/${id}/file`,
  thumbnailUrl: (id: number) => `${BASE}/images/${id}/thumbnail`,
  uploadImages(files: File[]) {
    const form = new FormData()
    files.forEach((f) => form.append('files', f, f.name))
    return request<UploadResult[]>('/images', { method: 'POST', body: form })
  },
  updateImage: (id: number, body: { annotation_status?: string; dataset_split?: string }) =>
    request<ImageDetail>(`/images/${id}`, json('PATCH', body)),
  deleteImage: (id: number) => request<void>(`/images/${id}`, { method: 'DELETE' }),
  saveAnnotations: (id: number, annotations: AnnotationInput[], markLabeled = true) =>
    request<ImageDetail>(`/images/${id}/annotations`, json('PUT', { annotations, mark_labeled: markLabeled })),
  datasetStats: () => request<DatasetStats>('/images/stats'),

  // detection
  detectStored: (id: number, opts: DetectOptions) =>
    request<DetectResponse>(`/images/${id}/detect`, { method: 'POST', body: detectForm(opts) }),
  detectUpload(file: File, opts: DetectOptions) {
    const form = new FormData()
    form.append('image', file, file.name)
    return request<DetectResponse>('/detect', { method: 'POST', body: detectForm(opts, form) })
  },

  // training
  baseModels: () => request<BaseModelOption[]>('/training/base-models'),
  listRuns: () => request<TrainingRun[]>('/training/runs'),
  getRun: (id: number) => request<TrainingRun>(`/training/runs/${id}`),
  getRunLog: (id: number) => request<{ id: number; status: string; log: string }>(`/training/runs/${id}/log`),
  startRun: (body: { base_model_id: string; input_size: string; epochs: number; batch_size: number; learning_rate?: number | null; num_workers?: number }) =>
    request<TrainingRun>('/training/runs', json('POST', body)),
  cancelRun: (id: number) => request<TrainingRun>(`/training/runs/${id}/cancel`, { method: 'POST' }),

  // models
  listModels: () => request<ModelVersion[]>('/models'),
  activateModel: (version: string) => request<ModelVersion>(`/models/${version}/activate`, { method: 'POST' }),
  archiveModel: (version: string) => request<ModelVersion>(`/models/${version}/archive`, { method: 'POST' }),
  updateModelNotes: (version: string, notes: string) => request<ModelVersion>(`/models/${version}`, json('PATCH', { notes })),
  bootstrapModel: (force = false) => request<{ job_id: string }>(`/models/bootstrap?force=${force}`, { method: 'POST' }),
  artifactUrl: (version: string, artifact: string) => `${BASE}/models/${version}/artifacts/${artifact}`,

  // settings
  getSettings: () => request<{ values: Settings; defaults: Settings }>('/settings'),
  updateSettings: (values: Partial<Settings>) => request<{ values: Settings; defaults: Settings }>('/settings', json('PUT', { values })),
}

export function errorMessage(e: unknown): string {
  if (e instanceof ApiError) return `${e.status}: ${e.message}`
  if (e instanceof Error) return e.message
  return String(e)
}

export function fmtPct(v: number | null | undefined, digits = 1): string {
  return v === null || v === undefined ? '–' : `${(v * 100).toFixed(digits)} %`
}

export function fmtDate(v: string | null | undefined): string {
  return v ? new Date(v).toLocaleString('de-DE') : '–'
}
