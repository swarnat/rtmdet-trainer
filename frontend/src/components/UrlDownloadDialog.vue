<template>
  <q-dialog :model-value="modelValue" @update:model-value="(v) => emit('update:modelValue', v)" @hide="clearIfIdle">
    <q-card style="width: 640px; max-width: 95vw">
      <q-card-section class="row items-center">
        <div class="text-h6">Batch-Download</div>
        <q-space />
        <q-btn flat round dense icon="close" v-close-popup />
      </q-card-section>
      <q-card-section class="q-pt-none text-body2 text-muted">
        Lädt Bilder (JPEG/PNG/WebP/BMP) von den angegebenen URLs herunter und legt sie als offene Bilder zur Annotation an.
        Eine URL pro Zeile; bereits vorhandene Bilder werden als Duplikat erkannt.
      </q-card-section>

      <q-card-section class="q-pt-none">
        <q-input
          v-model="text"
          type="textarea"
          outlined
          autogrow
          :readonly="running"
          input-style="min-height: 240px; max-height: 50vh; font-family: monospace; font-size: 12px; white-space: pre; overflow: auto"
          placeholder="https://example.com/bild1.jpg&#10;https://example.com/bild2.png"
        />
        <div class="text-caption text-muted q-mt-xs">
          {{ urls.length }} URLs<span v-if="invalid.length">, {{ invalid.length }} ungültige Zeilen werden übersprungen</span>
        </div>
      </q-card-section>

      <q-card-section v-if="progress.total" class="q-pt-none">
        <q-linear-progress :value="progress.done / progress.total" size="14px" rounded color="primary" class="q-mb-sm">
          <div class="absolute-full flex flex-center text-caption text-white">{{ progress.done }} / {{ progress.total }}</div>
        </q-linear-progress>
        <div class="text-caption">
          {{ progress.created }} neu, {{ progress.duplicates }} Duplikate<span v-if="progress.deleted">, {{ progress.deleted }} früher gelöscht</span><span v-if="errors.length">, {{ errors.length }} Fehler</span>
          <span v-if="cancelled"> · abgebrochen</span>
        </div>
        <q-list v-if="errors.length" dense bordered separator class="q-mt-sm rounded-borders" style="max-height: 160px; overflow: auto">
          <q-item v-for="(e, i) in errors" :key="i">
            <q-item-section>
              <q-item-label class="ellipsis text-caption">{{ e.url }}</q-item-label>
              <q-item-label caption class="text-negative">{{ e.error }}</q-item-label>
            </q-item-section>
          </q-item>
        </q-list>
      </q-card-section>

      <q-card-actions align="right">
        <q-btn v-if="running" outline color="negative" icon="stop" label="Abbrechen" no-caps @click="cancel" />
        <template v-else>
          <q-btn v-if="errors.length" flat no-caps label="Fehlgeschlagene übernehmen" @click="retryFailed">
            <q-tooltip>Nur die fehlgeschlagenen URLs im Textfeld behalten</q-tooltip>
          </q-btn>
          <q-btn color="primary" icon="cloud_download" label="Herunterladen" no-caps :disable="!urls.length" @click="start" />
        </template>
      </q-card-actions>
    </q-card>
  </q-dialog>
</template>

<script setup lang="ts">
import { computed, reactive, ref } from 'vue'
import { api, errorMessage, type UploadResult } from '@/services/api'

export interface DownloadProgress {
  total: number
  done: number
  created: number
  duplicates: number
  /** deleted earlier: not imported again */
  deleted: number
  failed: number
}

const props = withDefaults(
  defineProps<{
    modelValue: boolean
    /** downloads one URL (default: into the training images of this system) */
    download?: (url: string, signal: AbortSignal) => Promise<Pick<UploadResult, 'status' | 'error'>>
  }>(),
  { download: api.downloadImage },
)
const emit = defineEmits<{
  'update:modelValue': [value: boolean]
  progress: [p: DownloadProgress | null]
  finished: [p: DownloadProgress]
}>()

// parallel requests to the backend (each downloads one image)
const CONCURRENCY = 4

const text = ref('')
const running = ref(false)
const cancelled = ref(false)
const progress = reactive<DownloadProgress>({ total: 0, done: 0, created: 0, duplicates: 0, deleted: 0, failed: 0 })
const errors = ref<{ url: string; error: string }[]>([])
let abort: AbortController | null = null

const lines = computed(() =>
  text.value
    .split(/\s+/)
    .map((l) => l.trim())
    .filter(Boolean),
)
const urls = computed(() => [...new Set(lines.value.filter((l) => /^https?:\/\/\S+$/i.test(l)))])
const invalid = computed(() => lines.value.filter((l) => !/^https?:\/\/\S+$/i.test(l)))

async function start() {
  const queue = [...urls.value]
  Object.assign(progress, { total: queue.length, done: 0, created: 0, duplicates: 0, deleted: 0, failed: 0 })
  errors.value = []
  cancelled.value = false
  running.value = true
  abort = new AbortController()
  const signal = abort.signal
  emit('progress', { ...progress })

  async function worker() {
    while (queue.length && !signal.aborted) {
      const url = queue.shift()!
      try {
        const r = await props.download(url, signal)
        if (r.status === 'created') progress.created++
        else if (r.status === 'duplicate') progress.duplicates++
        else if (r.status === 'deleted') progress.deleted++
        else errors.value.push({ url, error: r.error ?? 'Fehler' })
      } catch (e) {
        if (signal.aborted) return
        errors.value.push({ url, error: errorMessage(e) })
      }
      progress.failed = errors.value.length
      progress.done++
      emit('progress', { ...progress })
    }
  }

  try {
    await Promise.all(Array.from({ length: Math.min(CONCURRENCY, queue.length) }, worker))
  } finally {
    running.value = false
    abort = null
    emit('progress', null)
    emit('finished', { ...progress })
    // closed while the download ran in the background: clear now
    if (!props.modelValue) clearIfIdle()
  }
}

/** after closing, the URL list starts empty (a running download keeps its list until it is finished) */
function clearIfIdle() {
  if (!running.value) text.value = ''
}

function cancel() {
  cancelled.value = true
  abort?.abort()
}

function retryFailed() {
  text.value = errors.value.map((e) => e.url).join('\n')
}
</script>
