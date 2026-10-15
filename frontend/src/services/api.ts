// Typed client for the FastAPI backend (/api/v1)

// Class names are configured in the application (see ClassesPage / stores/classes.ts)
export type ClassName = string

export interface DetectionClass {
  id: number
  name: string
  label: string
  color: string
  coco_classes: string[]
  sort_order: number
  active: boolean
  annotation_count: number
  hard_negative_count: number
  created_at: string
  updated_at: string
}

/** positive = real object; hard_negative = region a model wrongly detected as `class` */
export type AnnotationType = 'positive' | 'hard_negative'

export interface Annotation {
  id: number
  class: ClassName
  x1: number
  y1: number
  x2: number
  y2: number
  type: AnnotationType
  source: 'manual' | 'prediction'
  source_confidence: number | null
  source_model: string | null
  created_at: string
  updated_at: string
}

export interface AnnotationInput {
  class: ClassName
  x1: number
  y1: number
  x2: number
  y2: number
  type: AnnotationType
  source: 'manual' | 'prediction'
  source_confidence?: number | null
  source_model?: string | null
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
  hard_negative_count: number
  suggestion_count: number | null
  /** latest error analysis: false positives / false negatives of the model (null = not marked) */
  error_fp: number | null
  error_fn: number | null
  /** empty image visually identical to this image (duplicate check); not used for training */
  duplicate_of: number | null
  /** largest block difference to the original (0 = pixel-identical) */
  duplicate_score: number | null
  /** reviewed on the duplicates page and kept */
  duplicate_keep: boolean
  reviewed_classes: string[] | null
  needs_review: boolean
  /** link count: training snapshots (models) that use this image */
  snapshot_refs: number
  created_at: string
  updated_at: string
  labeled_at: string | null
}

export interface DuplicateGroup {
  original: ImageItem
  duplicates: ImageItem[]
}

/** One annotated box for the annotation review (crop = box + margin, clipped to the image) */
export interface ReviewCrop {
  id: number
  image_id: number
  class: ClassName
  x1: number
  y1: number
  x2: number
  y2: number
  type: AnnotationType
  source: 'manual' | 'prediction'
  image_width: number
  image_height: number
  dataset_split: 'train' | 'validation' | null
  updated_at: string
}

export type ReviewSort = 'newest' | 'oldest' | 'smallest' | 'largest' | 'widest' | 'tallest' | 'image'

/** Open images without suggestions of one camera view, for the quick review */
export interface CameraGroup {
  /** camera identity from the metadata, e.g. "AXIS Q3536-LVE · B8A44F55F126" ("" = unknown or switched off) */
  camera: string
  images: {
    image: ImageItem
    /** image to blink-compare with: a known-empty image of the view ("negative") or the previous image ("previous") */
    compare_with: number | null
    compare_kind: 'negative' | 'previous' | null
  }[]
}

export interface ImageDetail extends ImageItem {
  annotations: Annotation[]
  suggestion: Suggestion | null
  error_mark: ErrorMark | null
}

/** Error analysis result for one labeled image: where the model disagrees with the annotations */
export interface ErrorMark {
  batch_id: number | null
  model_version: string
  input_width: number
  input_height: number
  confidence: number
  true_positives: number
  /** detections without a matching annotation */
  false_positives: DetectionItem[]
  /** annotations the model missed */
  false_negatives: { class: ClassName; bbox: { x1: number; y1: number; x2: number; y2: number } }[]
  created_at: string
}

/** Stored detections of a batch test for one image */
export interface Suggestion {
  batch_id: number | null
  model_version: string
  input_width: number
  input_height: number
  confidence: number
  detections: DetectionItem[]
  created_at: string
}

/** errors_*: error analysis on labeled images instead of suggestions for open images */
export type BatchScope = 'unlabeled' | 'unlabeled_and_review' | 'unlabeled_last_upload' | 'unlabeled_untested' | 'errors_validation' | 'errors_labeled'
export type TrainingDevice = 'gpu' | 'cpu'
export const isErrorAnalysis = (b: { scope: BatchScope }) => b.scope.startsWith('errors_')

export interface BatchTest {
  id: number
  status: 'queued' | 'running' | 'completed' | 'failed' | 'cancelled'
  model_ref: string
  model_version: string | null
  input_width: number
  input_height: number
  confidence: number
  scope: BatchScope
  total: number
  processed: number
  /** suggestions, or for an error analysis: number of false positives + false negatives */
  detections: number
  failed_images: number
  /** error analysis: images with at least one error */
  marked_images: number
  error: string | null
  created_at: string
  started_at: string | null
  finished_at: string | null
}

export interface UploadResult {
  filename: string | null
  /** deleted: the same file was deleted earlier and is not imported again */
  status: 'created' | 'duplicate' | 'deleted' | 'error'
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
  per_class?: Record<string, MetricSet | null>
  per_size?: Record<string, MetricSet>
  hard_negatives?: HardNegativeMetrics
  comparison?: Comparison
  mmdet_val_history?: ValHistoryEntry[]
  head_init?: Record<string, string>
  note?: string
}

/** All model versions evaluated on the current validation set (comparable values) */
export interface Benchmark {
  id: number
  status: 'queued' | 'running' | 'completed' | 'failed' | 'cancelled'
  class_names: string[] | null
  num_images: number
  num_boxes: number
  num_hard_negatives: number
  total: number
  processed: number
  /** seen_in_training: current validation images that were training images of the model */
  results: Record<string, Metrics & { status: string; error?: string; seen_in_training?: number | null }>
  error: string | null
  created_at: string
  started_at: string | null
  finished_at: string | null
}

export interface ValMaps {
  mAP50?: number
  'mAP50-95'?: number
}

/** MMDetection validation after one epoch (0..1); per_class/per_size only for runs since the detailed metric */
export interface ValHistoryEntry {
  epoch: number
  bbox_mAP?: number
  bbox_mAP_50?: number
  bbox_mAP_s?: number
  per_class?: Record<string, ValMaps>
  per_size?: Record<string, ValMaps>
}

export interface HardNegativeBucket {
  total: number
  still_detected: number
  fp_rate: number | null
}

export interface HardNegativeMetrics {
  confidence: number
  iou: number
  overall: HardNegativeBucket
  validation_only: HardNegativeBucket
  train_only: HardNegativeBucket
  per_class: Record<string, HardNegativeBucket>
  /** only hard negatives on validation images (missing in metrics of older runs) */
  per_class_validation?: Record<string, HardNegativeBucket>
}

export interface Comparison {
  baseline_model: string
  baseline: { overall: MetricSet; per_class: Record<string, MetricSet | null>; hard_negatives?: HardNegativeMetrics | null }
  delta_per_class: Record<
    string,
    { precision: number | null; recall: number | null; mAP50: number | null; 'mAP50-95': number | null; hard_negative_fp_rate: number | null }
  >
  /** 'validation' = HN-FP-rate delta on validation images only; missing = older runs (incl. training images) */
  hard_negative_basis?: 'validation'
  min_reliable_boxes?: number
  warnings: string[]
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

export interface TrainerGpuStatus {
  available: boolean
  devices: string[]
  error: string | null
  checked_at: string
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
  val_history?: ValHistoryEntry[]
}

export interface SplitStats {
  images: number
  negative_images: number
  boxes: number
  boxes_per_class: Record<string, number>
}

export interface TrainingEligibility {
  class_names: string[]
  usable: { train: number; validation: number }
  needs_review: number
  negative: number
  hard_negatives: number
  /** labeled empty images marked as duplicates, not used */
  duplicates?: number
}

export interface TrainingRun {
  id: number
  status: 'queued' | 'running' | 'completed' | 'failed'
  base_model_id: string
  class_names: string[] | null
  dataset_snapshot: string | null
  dataset_stats_json: {
    classes?: string[]
    excluded_needs_review?: number
    excluded_duplicates?: number
    hard_negatives?: { total: number; per_class: Record<string, number>; train_crops: number; oversample: number }
    train?: SplitStats
    validation?: SplitStats
  } | null
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
  architecture: string
  kind: 'coco' | 'model'
}

export interface CocoBaseModel {
  id: string
  architecture: string
  label: string
  coco_ap: number
  params_m: number
}

export interface DatasetStats {
  images_total: number
  images_labeled: number
  images_unlabeled: number
  images_negative: number
  images_needs_review: number
  /** empty images marked as duplicates of another empty image */
  images_duplicates?: number
  /** deleted images whose files are kept because training snapshots still use them */
  images_retained_for_snapshots?: number
  splits: { train: number; validation: number }
  annotations_per_class: Record<string, number>
  hard_negatives_per_class: Record<string, number>
}

export type Settings = Record<string, unknown> & {
  default_input_size: string
  input_sizes: string[]
  default_confidence: number
  nms_iou_threshold: number
  validation_ratio: number
  eval_confidence: number
  duplicate_max_difference: number
  camera_groups_use_metadata: boolean
  hard_negative_context_factor: number
  hard_negative_min_crop_fraction: number
  hard_negative_oversample: number
  default_base_model: string
  deployment_url: string
  /** write-only: '********' when set, '' when not set */
  deployment_access_key: string
}

export interface DeploymentStatus {
  configured: boolean
  url: string | null
  reachable: boolean
  model: { version: string; architecture: string | null; class_names: string[]; input_width: number; input_height: number; installed_at: string | null } | null
  error: string | null
  /** problems reported by the production system, e.g. missing CPU instruction sets */
  warnings: string[]
}

export interface Backup {
  name: string
  file: string
  status: 'queued' | 'running' | 'completed' | 'failed' | 'invalid'
  phase?: 'inventory' | 'database' | 'images' | 'datasets' | 'models' | 'finalizing' | null
  source?: 'ui' | 'cli' | 'imported'
  created_at: string | null
  finished_at?: string | null
  duration_s?: number
  size_bytes?: number
  estimated_bytes?: number
  file_exists?: boolean
  error: string | null
  warnings?: string[]
  contents?: Record<string, number>
  progress?: { objects_done: number; objects_total: number; bytes_done: number; bytes_total: number }
}

export interface BackupList {
  backups: Backup[]
  busy: boolean
  free_bytes: number | null
  available: boolean
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

/** restricts previous/next navigation in the annotation view to the image list filter */
export interface NavFilter {
  status?: 'unlabeled' | 'labeled'
  split?: 'train' | 'validation'
  has_errors?: boolean
  duplicate?: boolean
  no_suggestions?: boolean
  /** suggestions whose lowest confidence is >= 0.7 / 0.4-0.7 / < 0.4 */
  suggestion_level?: 'high' | 'medium' | 'low'
  /** images of the most recent upload session */
  last_upload?: boolean
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
  listImages(params: {
    status?: string
    split?: string
    negative?: boolean
    needs_review?: boolean
    has_suggestions?: boolean
    has_errors?: boolean
    duplicate?: boolean
    no_suggestions?: boolean
    suggestion_level?: 'high' | 'medium' | 'low'
    last_upload?: boolean
    offset?: number
    limit?: number
  }) {
    const q = new URLSearchParams()
    Object.entries(params).forEach(([k, v]) => {
      if (v !== undefined && v !== null && v !== '' && v !== false) q.set(k, String(v))
    })
    return request<{ total: number; items: ImageItem[] }>(`/images?${q}`)
  },
  getImage: (id: number) => request<ImageDetail>(`/images/${id}`),
  neighbours: (id: number, filter: NavFilter = {}) => {
    const q = new URLSearchParams()
    if (filter.status) q.set('status', filter.status)
    if (filter.split) q.set('split', filter.split)
    if (filter.has_errors) q.set('has_errors', 'true')
    if (filter.duplicate) q.set('duplicate', 'true')
    if (filter.no_suggestions) q.set('no_suggestions', 'true')
    if (filter.suggestion_level) q.set('suggestion_level', filter.suggestion_level)
    if (filter.last_upload) q.set('last_upload', 'true')
    const qs = q.toString()
    return request<{ previous: number | null; next: number | null }>(`/images/${id}/neighbours${qs ? `?${qs}` : ''}`)
  },
  imageUrl: (id: number) => `${BASE}/images/${id}/file`,
  thumbnailUrl: (id: number) => `${BASE}/images/${id}/thumbnail`,
  uploadImages(files: File[]) {
    const form = new FormData()
    files.forEach((f) => form.append('files', f, f.name))
    return request<UploadResult[]>('/images', { method: 'POST', body: form })
  },
  /** Backend downloads the image from `url` and stores it like an upload */
  downloadImage: (url: string, signal?: AbortSignal) =>
    request<UploadResult>('/images/from-url', { ...json('POST', { url }), signal }),
  updateImage: (id: number, body: { annotation_status?: string; dataset_split?: string }) =>
    request<ImageDetail>(`/images/${id}`, json('PATCH', body)),
  deleteImage: (id: number) => request<void>(`/images/${id}`, { method: 'DELETE' }),
  checkDuplicates: () =>
    request<{ checked: number; duplicates: number; fingerprints_computed: number; failed: number }>('/images/duplicates/check', { method: 'POST' }),
  /** untested: open images never batch-tested (not part of the review) */
  startBenchmark: () => request<Benchmark>('/models/benchmarks', { method: 'POST' }),
  latestBenchmark: () => request<Benchmark | null>('/models/benchmarks/latest'),
  cameraGroups: () => request<{ groups: CameraGroup[]; untested: number }>('/images/camera-groups'),
  reviewClasses: () => request<{ class: ClassName; positive: number; hard_negative: number }[]>('/annotations/review/classes'),
  reviewCrops: (p: { class: string; type: AnnotationType; split?: string; sort: ReviewSort; offset: number; limit: number }) => {
    const q = new URLSearchParams({ class: p.class, type: p.type, sort: p.sort, offset: String(p.offset), limit: String(p.limit) })
    if (p.split) q.set('split', p.split)
    return request<{ total: number; margin: number; items: ReviewCrop[] }>(`/annotations/review?${q}`)
  },
  /** updated_at in the URL: an edited box gets a new URL (the crop is cached by the browser) */
  cropUrl: (c: ReviewCrop) => `${BASE}/annotations/${c.id}/crop?v=${encodeURIComponent(c.updated_at)}`,
  duplicateGroups: () => request<DuplicateGroup[]>('/images/duplicates/groups'),
  resolveDuplicates: (body: { keep: number[]; delete: number[] }) =>
    request<{ kept: number; deleted: number }>('/images/duplicates/resolve', json('POST', body)),
  deleteErrorMark: (id: number) => request<ImageDetail>(`/images/${id}/error-mark`, { method: 'DELETE' }),
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
  /** the API downloads the image (camera URLs reachable only from the server, no CORS); returned as data URL, not stored */
  detectUrl: (url: string, opts: DetectOptions) =>
    request<DetectResponse & { image_data_url: string }>('/detect/url', json('POST', { url, ...opts })),

  // training
  baseModels: () => request<BaseModelOption[]>('/training/base-models'),
  listRuns: () => request<TrainingRun[]>('/training/runs'),
  getRun: (id: number) => request<TrainingRun>(`/training/runs/${id}`),
  getRunLog: (id: number) => request<{ id: number; status: string; log: string }>(`/training/runs/${id}/log`),
  eligibility: (classes: string[]) =>
    request<TrainingEligibility>(`/training/eligibility?classes=${encodeURIComponent(classes.join(','))}`),
  startRun: (body: { base_model_id: string; class_names?: string[]; input_size: string; epochs: number; batch_size: number; learning_rate?: number | null; num_workers?: number; device?: TrainingDevice }) =>
    request<TrainingRun>('/training/runs', json('POST', body)),
  /** status null = unknown (trainer not running / not checked yet) */
  trainerGpu: () => request<{ status: TrainerGpuStatus | null }>('/training/gpu'),
  cancelRun: (id: number) => request<TrainingRun>(`/training/runs/${id}/cancel`, { method: 'POST' }),

  // models
  listModels: () => request<ModelVersion[]>('/models'),
  activateModel: (version: string) => request<ModelVersion>(`/models/${version}/activate`, { method: 'POST' }),
  archiveModel: (version: string) => request<ModelVersion>(`/models/${version}/archive`, { method: 'POST' }),
  deleteModel: (version: string) => request<void>(`/models/${version}`, { method: 'DELETE' }),
  updateModelNotes: (version: string, notes: string) => request<ModelVersion>(`/models/${version}`, json('PATCH', { notes })),
  bootstrapModel: (force = false, baseModel = 'rtmdet-s-coco') =>
    request<{ job_id: string }>(`/models/bootstrap?force=${force}&base_model=${encodeURIComponent(baseModel)}`, { method: 'POST' }),
  cocoBaseModels: () => request<CocoBaseModel[]>('/models/base-models'),
  artifactUrl: (version: string, artifact: string) => `${BASE}/models/${version}/artifacts/${artifact}`,

  // batch tests
  startBatchTest: (body: { model: string; input_size?: string | null; confidence?: number | null; scope: BatchScope }) =>
    request<BatchTest>('/batch-tests', json('POST', body)),
  listBatchTests: () => request<BatchTest[]>('/batch-tests'),
  getBatchTest: (id: number) => request<BatchTest>(`/batch-tests/${id}`),
  cancelBatchTest: (id: number) => request<BatchTest>(`/batch-tests/${id}/cancel`, { method: 'POST' }),

  // classes
  listClasses: () => request<DetectionClass[]>('/classes'),
  cocoClasses: () => request<string[]>('/classes/coco'),
  createClass: (body: { name: string; label: string; color?: string | null; coco_classes: string[] }) =>
    request<DetectionClass>('/classes', json('POST', body)),
  updateClass: (name: string, body: Partial<Pick<DetectionClass, 'label' | 'color' | 'coco_classes' | 'active'>>) =>
    request<DetectionClass>(`/classes/${name}`, json('PATCH', body)),
  reorderClasses: (names: string[]) => request<DetectionClass[]>('/classes/order', json('PUT', { names })),
  deleteClass: (name: string) => request<void>(`/classes/${name}`, { method: 'DELETE' }),

  // production system (inference-server)
  deploymentStatus: () => request<DeploymentStatus>('/deployment'),
  deployModel: (version: string) => request<{ version: string }>('/deployment', json('POST', { version })),

  // backups
  listBackups: () => request<BackupList>('/backups'),
  startBackup: () => request<Backup>('/backups', { method: 'POST' }),
  deleteBackup: (name: string) => request<void>(`/backups/${name}`, { method: 'DELETE' }),
  backupDownloadUrl: (name: string) => `${BASE}/backups/${name}/download`,

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
