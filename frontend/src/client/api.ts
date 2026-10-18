// Typed client for the client annotator API (client-annotator/, /api/v1); the login cookie authenticates every call
import { ApiError, type AnnotationInput, type DetectionClass, type DetectionItem, type ImageDetail } from '@/services/api'

export interface ClientClass {
  name: string
  label: string
  color: string
}

/** pushed by the training system */
export interface ClientConfig {
  classes: ClientClass[]
  /** inference server as seen from the customer server ("" = no checks) */
  inference_url: string
  /** effective value: CHECK_CONFIDENCE of the service if set, else the pushed one */
  confidence: number
  confidence_source: 'pushed' | 'env'
  pushed_confidence: number | null
  source: string | null
  pushed_at: string
}

export interface ClientAnnotation extends AnnotationInput {
  source_confidence: number | null
  source_model: string | null
}

/** latest check against the inference server */
export interface ClientDetection {
  model_version: string
  input_width: number
  input_height: number
  confidence: number
  inference_ms: number | null
  detections: DetectionItem[]
  created_at: string
}

export interface ClientImage {
  id: number
  sha256: string
  filename: string | null
  source_url: string | null
  content_type: string
  size_bytes: number
  width: number
  height: number
  status: 'open' | 'annotated'
  annotations: ClientAnnotation[]
  detection: ClientDetection | null
  created_at: string
  updated_at: string
  annotated_at: string | null
}

export interface ClientCounts {
  total: number
  open: number
  annotated: number
}

export interface ClientUploadResult {
  filename: string | null
  status: 'created' | 'duplicate' | 'error'
  image: ClientImage | null
  error: string | null
}

const BASE = '/api/v1'

/** called on 401 (token changed on the server or cookie expired) */
let onUnauthorized: () => void = () => {}
export function setUnauthorizedHandler(fn: () => void) {
  onUnauthorized = fn
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const res = await fetch(BASE + path, { credentials: 'same-origin', ...init })
  if (!res.ok) {
    let detail = res.statusText
    try {
      const body = await res.json()
      detail = typeof body.detail === 'string' ? body.detail : JSON.stringify(body.detail)
    } catch {
      /* not JSON */
    }
    if (res.status === 401 && path !== '/session') onUnauthorized()
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

export const clientApi = {
  login: (token: string) => request<void>('/session', json('POST', { token })),
  logout: () => request<void>('/session', { method: 'DELETE' }),
  getConfig: () => request<ClientConfig | null>('/config'),
  listImages: () => request<{ counts: ClientCounts; items: ClientImage[] }>('/images'),
  getImage: (id: number) => request<ClientImage>(`/images/${id}`),
  imageUrl: (id: number) => `${BASE}/images/${id}/file`,
  thumbnailUrl: (id: number) => `${BASE}/images/${id}/thumbnail`,
  uploadImages: (files: File[]) => {
    const form = new FormData()
    files.forEach((f) => form.append('files', f))
    return request<ClientUploadResult[]>('/images', { method: 'POST', body: form })
  },
  downloadImage: (url: string, signal?: AbortSignal) =>
    request<ClientUploadResult>('/images/from-url', { ...json('POST', { url }), signal }),
  saveAnnotations: (id: number, annotations: AnnotationInput[], markAnnotated = true) =>
    request<ClientImage>(`/images/${id}/annotations`, json('PUT', { annotations, mark_annotated: markAnnotated })),
  reopen: (id: number) => request<ClientImage>(`/images/${id}`, json('PATCH', { status: 'open' })),
  detect: (id: number, confidence?: number, signal?: AbortSignal) =>
    request<ClientImage>(`/images/${id}/detect`, { ...json('POST', { confidence }), signal }),
  deleteImage: (id: number) => request<void>(`/images/${id}`, { method: 'DELETE' }),
}

/** pushed classes in the shape of the training system's classes store (all active, order as pushed) */
export function toDetectionClasses(config: ClientConfig): DetectionClass[] {
  return config.classes.map((c, i) => ({
    id: i + 1, name: c.name, label: c.label, color: c.color, coco_classes: [], sort_order: i, active: true,
    annotation_count: 0, hard_negative_count: 0, created_at: config.pushed_at, updated_at: config.pushed_at,
  }))
}

/** A client image in the shape of the training system's image detail, so the annotation store can edit it;
 *  the latest check becomes the "suggestion" (shown as predictions, minus those already annotated). */
export function toDetail(img: ClientImage): ImageDetail {
  const positives = img.annotations.filter((a) => a.type === 'positive').length
  return {
    id: img.id, sha256: img.sha256, original_filename: img.filename, content_type: img.content_type, size_bytes: img.size_bytes,
    width: img.width, height: img.height, annotation_status: img.status === 'annotated' ? 'labeled' : 'unlabeled',
    dataset_split: null, annotation_count: positives, hard_negative_count: img.annotations.length - positives,
    suggestion_count: img.detection ? img.detection.detections.length : null, error_fp: null, error_fn: null,
    duplicate_of: null, duplicate_score: null, duplicate_keep: false, reviewed_classes: null, needs_review: false,
    snapshot_refs: 0, created_at: img.created_at, updated_at: img.updated_at, labeled_at: img.annotated_at,
    annotations: img.annotations.map((a, i) => ({ ...a, id: i + 1, created_at: img.updated_at, updated_at: img.updated_at })),
    suggestion: img.detection
      ? { batch_id: null, model_version: img.detection.model_version, input_width: img.detection.input_width,
          input_height: img.detection.input_height, confidence: img.detection.confidence,
          detections: img.detection.detections, created_at: img.detection.created_at }
      : null,
    error_mark: null,
  }
}
