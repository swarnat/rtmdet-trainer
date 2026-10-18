<template>
  <div class="column no-wrap full-height">
    <div class="q-pa-sm column q-gutter-sm">
      <q-select
        v-model="filter"
        dense
        outlined
        emit-value
        map-options
        options-dense
        label="Filter"
        :options="filterOptions"
        :option-disable="(o: FilterOption) => !!o.header"
      >
        <template #option="{ opt, itemProps }">
          <q-item-label v-if="opt.header" header class="q-pt-sm q-pb-xs text-weight-medium">{{ opt.label }}</q-item-label>
          <q-item v-else v-bind="itemProps" class="q-pl-lg">
            <q-item-section>
              <q-item-label>{{ opt.label }}</q-item-label>
              <q-item-label v-if="opt.caption" caption>{{ opt.caption }}</q-item-label>
            </q-item-section>
          </q-item>
        </template>
      </q-select>
      <div class="row items-center no-wrap q-gutter-x-sm">
        <q-btn color="primary" icon="upload" label="Hochladen" dense no-caps no-wrap class="col q-py-xs" :loading="uploading" @click="fileInput?.click()" />
        <q-btn color="primary" outline icon="cloud_download" label="Batch-Download" dense no-caps no-wrap class="col q-py-xs" @click="downloadDialog = true">
          <q-tooltip>Bilder von einer Liste von URLs herunterladen</q-tooltip>
        </q-btn>
      </div>
      <div class="row items-center no-wrap q-gutter-x-sm">
        <q-btn color="secondary" icon="playlist_play" label="Batch-Test" dense no-caps no-wrap class="col q-py-xs" @click="batchDialog = true">
          <q-tooltip>Modell auf allen offenen Bildern testen und Vorschläge speichern</q-tooltip>
        </q-btn>
        <q-btn color="secondary" outline icon="move_to_inbox" label="Client" dense no-caps no-wrap class="col q-py-xs" @click="clientDialog = true">
          <q-tooltip>Client-Annotationen einlesen: Bilder und Annotationen vom Kunden-Annotationsdienst holen</q-tooltip>
        </q-btn>
        <q-btn flat round dense icon="refresh" @click="reload"><q-tooltip>Neu laden</q-tooltip></q-btn>
      </div>
      <div v-if="runningBatch" class="cursor-pointer" @click="batchDialog = true">
        <div class="text-caption text-secondary">
          {{ isErrorAnalysis(runningBatch) ? 'Fehleranalyse' : 'Batch-Test' }} #{{ runningBatch.id }} läuft: {{ runningBatch.processed }} / {{ runningBatch.total }}
        </div>
        <q-linear-progress :value="runningBatch.total ? runningBatch.processed / runningBatch.total : 0" color="secondary" rounded />
      </div>
      <div v-if="download" class="cursor-pointer" @click="downloadDialog = true">
        <div class="text-caption text-primary">Batch-Download: {{ download.done }} / {{ download.total }}</div>
        <q-linear-progress :value="download.total ? download.done / download.total : 0" color="primary" rounded />
      </div>
      <div v-if="clientImport" class="cursor-pointer" @click="clientDialog = true">
        <div class="text-caption text-secondary">Client-Import: {{ clientImport.done }} / {{ clientImport.total }}</div>
        <q-linear-progress :value="clientImport.total ? clientImport.done / clientImport.total : 0" color="secondary" rounded />
      </div>
      <UrlDownloadDialog v-model="downloadDialog" @progress="(p) => (download = p)" @finished="onDownloadFinished" />
      <ClientImportDialog v-model="clientDialog" @progress="(p) => (clientImport = p)" @finished="onClientImportFinished" />
      <BatchTestDialog v-model="batchDialog" @running="(b) => (runningBatch = b)" @finished="onBatchFinished" />
      <input ref="fileInput" type="file" accept="image/jpeg,image/png,image/webp,image/bmp" multiple hidden @change="onFiles" />
      <q-btn v-if="filter === 'duplicates'" outline color="secondary" icon="compare" label="Duplikate prüfen und entscheiden" dense no-caps to="/duplicates" />
      <div class="text-caption text-muted">{{ total }} Bilder</div>
    </div>
    <q-separator />
    <q-scroll-area class="col" @dragover.prevent @drop.prevent="onDrop">
      <q-list dense>
        <q-item
          v-for="img in items"
          :key="img.id"
          clickable
          :active="img.id === selectedId"
          active-class="bg-active"
          @click="emit('select', img.id)"
        >
          <q-item-section avatar>
            <q-img :src="api.thumbnailUrl(img.id)" width="96px" :ratio="16 / 9" class="rounded-borders" loading="lazy" />
          </q-item-section>
          <q-item-section>
            <q-item-label class="ellipsis" :title="img.original_filename ?? undefined">#{{ img.id }} {{ fmtMiddle(img.original_filename, 18) }}</q-item-label>
            <q-item-label caption>
              <q-badge v-if="img.annotation_status === 'unlabeled'" outline color="grey-5" label="offen" />
              <q-badge v-else-if="img.annotation_count === 0" outline color="secondary" label="negativ" />
              <q-badge v-else outline color="positive" :label="`${img.annotation_count} Boxen`" />
              <q-badge v-if="img.suggestion_count != null" outline color="secondary" class="q-ml-xs" :label="`${img.suggestion_count} Vorschl.`">
                <q-tooltip>Vorschläge aus einem Batch-Test</q-tooltip>
              </q-badge>
              <q-badge v-if="img.duplicate_of" outline color="warning" class="q-ml-xs" :label="`Duplikat von #${img.duplicate_of}`">
                <q-tooltip max-width="320px">Leeres Bild, fast identisch zu #{{ img.duplicate_of }} – wird nicht fürs Training verwendet</q-tooltip>
              </q-badge>
              <q-badge v-if="img.error_fp != null" outline color="negative" class="q-ml-xs" :label="`${img.error_fp} FP · ${img.error_fn} FN`">
                <q-tooltip>Fehleranalyse: {{ img.error_fp }} Fehlalarme (False Positives), {{ img.error_fn }} nicht erkannte Objekte (False Negatives)</q-tooltip>
              </q-badge>
              <q-badge v-if="img.hard_negative_count" outline color="blue-grey-3" class="q-ml-xs" :label="`${img.hard_negative_count} HN`">
                <q-tooltip>Hard Negatives (bekannte Fehlalarme)</q-tooltip>
              </q-badge>
              <q-badge v-if="img.needs_review" outline color="warning" class="q-ml-xs" label="prüfen">
                <q-tooltip>Noch nicht auf alle aktiven Klassen geprüft</q-tooltip>
              </q-badge>
              <q-badge v-if="img.dataset_split" outline color="primary" class="q-ml-xs" :label="img.dataset_split === 'train' ? 'train' : 'val'" />
              <q-badge v-if="img.snapshot_refs" outline color="blue-grey-3" class="q-ml-xs">
                <q-icon name="link" size="12px" class="q-mr-xs" />{{ img.snapshot_refs }}
                <q-tooltip max-width="320px">In {{ img.snapshot_refs }} Training(s) verwendet. {{ GLOSSARY.snapshotRefs }}</q-tooltip>
              </q-badge>
            </q-item-label>
          </q-item-section>
        </q-item>
      </q-list>
      <div v-if="items.length < total" class="q-pa-sm text-center">
        <q-btn flat dense no-caps label="Mehr laden" :loading="loading" @click="loadMore" />
      </div>
      <div v-if="!items.length && !loading" class="q-pa-md text-muted text-center">
        Keine Bilder. Hochladen per Button oder Drag &amp; Drop.
      </div>
    </q-scroll-area>
  </div>
</template>

<script setup lang="ts">
import { onMounted, ref, watch } from 'vue'
import { useQuasar } from 'quasar'
import { useRoute } from 'vue-router'
import BatchTestDialog from './BatchTestDialog.vue'
import UrlDownloadDialog, { type DownloadProgress } from './UrlDownloadDialog.vue'
import ClientImportDialog, { type ClientImportProgress } from './ClientImportDialog.vue'
import { GLOSSARY } from '@/glossary'
import { api, errorMessage, fmtMiddle, isErrorAnalysis, type BatchTest, type ImageItem, type NavFilter } from '@/services/api'

const props = defineProps<{ selectedId: number | null }>()
const emit = defineEmits<{ select: [id: number]; filterChange: [filter: NavFilter]; batchFinished: [] }>()
const $q = useQuasar()

const PAGE = 100
type Filter = 'all' | 'unlabeled' | 'last_upload' | 'unlabeled_no_suggestions' | 'sugg_high' | 'sugg_medium' | 'sugg_low' | 'labeled' | 'negative' | 'review' | 'suggestions' | 'train' | 'validation' | 'errors' | 'duplicates'
interface FilterOption {
  label: string
  value?: Filter
  caption?: string
  header?: boolean
}
const filterOptions: FilterOption[] = [
  { label: 'Alle Bilder', value: 'all' },
  { label: 'Offene Bilder', header: true },
  { label: 'Alle offenen', value: 'unlabeled' },
  { label: 'Aus letztem Upload', value: 'last_upload', caption: 'jüngste Upload-Sitzung (Pausen < 30 min)' },
  { label: 'Ohne Vorschläge', value: 'unlabeled_no_suggestions', caption: 'Batch-Test fand nichts oder lief noch nicht' },
  { label: 'Mit Vorschlägen (alle)', value: 'suggestions' },
  { label: 'Vorschläge ≥ 0,7', value: 'sugg_high', caption: 'alle sicher – meist „Alle übernehmen“' },
  { label: 'Vorschläge 0,4–0,7', value: 'sugg_medium', caption: 'unsicherster Vorschlag mittel' },
  { label: 'Vorschläge < 0,4', value: 'sugg_low', caption: 'mindestens einer unsicher – genau prüfen' },
  { label: 'Annotierte Bilder', header: true },
  { label: 'Alle annotierten', value: 'labeled' },
  { label: 'Negativ (ohne Objekte)', value: 'negative' },
  { label: 'Nachprüfen (neue Klassen)', value: 'review' },
  { label: 'Trainingsbilder', value: 'train' },
  { label: 'Validierungsbilder', value: 'validation' },
  { label: 'Fehlerbilder (Fehleranalyse)', value: 'errors' },
  { label: 'Weitere', header: true },
  { label: 'Duplikate (leere Bilder)', value: 'duplicates' },
]
const SUGGESTION_LEVEL = { sugg_high: 'high', sugg_medium: 'medium', sugg_low: 'low' } as const

// ?filter=errors: opened from the training page after an error analysis
const filter = ref<Filter>(useRoute().query.filter === 'errors' ? 'errors' : 'all')
const batchDialog = ref(false)
const runningBatch = ref<BatchTest | null>(null)
const downloadDialog = ref(false)
const download = ref<DownloadProgress | null>(null)
const clientDialog = ref(false)
const clientImport = ref<ClientImportProgress | null>(null)
const items = ref<ImageItem[]>([])
const total = ref(0)
const loading = ref(false)
const uploading = ref(false)
const fileInput = ref<HTMLInputElement | null>(null)

function query(offset: number) {
  return api.listImages({
    status: ['unlabeled', 'unlabeled_no_suggestions', 'last_upload'].includes(filter.value) ? 'unlabeled' : filter.value === 'labeled' ? 'labeled' : undefined,
    last_upload: filter.value === 'last_upload',
    no_suggestions: filter.value === 'unlabeled_no_suggestions',
    suggestion_level: filter.value in SUGGESTION_LEVEL ? SUGGESTION_LEVEL[filter.value as keyof typeof SUGGESTION_LEVEL] : undefined,
    split: filter.value === 'train' || filter.value === 'validation' ? filter.value : undefined,
    negative: filter.value === 'negative',
    needs_review: filter.value === 'review',
    has_suggestions: filter.value === 'suggestions',
    has_errors: filter.value === 'errors',
    duplicate: filter.value === 'duplicates',
    offset,
    limit: PAGE,
  })
}

async function reload() {
  loading.value = true
  try {
    const res = await query(0)
    items.value = res.items
    total.value = res.total
  } catch (e) {
    $q.notify({ type: 'negative', message: errorMessage(e) })
  } finally {
    loading.value = false
  }
}

async function loadMore() {
  loading.value = true
  try {
    const res = await query(items.value.length)
    items.value.push(...res.items)
    total.value = res.total
  } finally {
    loading.value = false
  }
}

/** Update a single entry after saving without reloading the whole list. */
function patch(img: ImageItem) {
  const i = items.value.findIndex((x) => x.id === img.id)
  if (i >= 0) items.value[i] = { ...items.value[i], ...img }
}

async function upload(files: File[]) {
  if (!files.length) return
  uploading.value = true
  let created = 0
  let duplicates = 0
  let deleted = 0
  const errors: string[] = []
  try {
    // upload in chunks to keep requests small
    for (let i = 0; i < files.length; i += 10) {
      const results = await api.uploadImages(files.slice(i, i + 10))
      for (const r of results) {
        if (r.status === 'created') created++
        else if (r.status === 'duplicate') duplicates++
        else if (r.status === 'deleted') deleted++
        else errors.push(`${r.filename}: ${r.error}`)
      }
    }
    $q.notify({
      type: errors.length ? 'warning' : 'positive',
      message: `${created} hochgeladen, ${duplicates} Duplikate${deleted ? `, ${deleted} früher gelöscht` : ''}${errors.length ? `, ${errors.length} Fehler` : ''}`,
      caption: errors.slice(0, 3).join('; '),
    })
    await reload()
  } catch (e) {
    $q.notify({ type: 'negative', message: errorMessage(e) })
  } finally {
    uploading.value = false
  }
}

function onFiles(e: Event) {
  const input = e.target as HTMLInputElement
  upload(Array.from(input.files ?? []))
  input.value = ''
}

function onDrop(e: DragEvent) {
  upload(Array.from(e.dataTransfer?.files ?? []).filter((f) => f.type.startsWith('image/')))
}

function onDownloadFinished(p: DownloadProgress) {
  $q.notify({
    type: p.failed ? 'warning' : 'positive',
    message: `Batch-Download: ${p.created} heruntergeladen, ${p.duplicates} Duplikate${p.deleted ? `, ${p.deleted} früher gelöscht` : ''}${p.failed ? `, ${p.failed} Fehler` : ''}`,
    caption: p.done < p.total ? `abgebrochen nach ${p.done} von ${p.total} URLs` : undefined,
  })
  if (p.created) reload()
}

function onClientImportFinished(p: ClientImportProgress) {
  $q.notify({
    type: p.failed ? 'warning' : 'positive',
    message: `Client-Import: ${p.created} neu, ${p.duplicates} Duplikate · ${p.annotated} annotiert übernommen, ${p.suggestions} mit Vorschlägen${p.failed ? `, ${p.failed} Fehler` : ''}`,
    caption: p.done < p.total ? `abgebrochen nach ${p.done} von ${p.total} Bildern` : undefined,
  })
  if (p.created || p.annotated || p.suggestions) reload()
}

function onBatchFinished(b: BatchTest) {
  if (isErrorAnalysis(b)) {
    $q.notify({
      type: b.status === 'completed' ? 'positive' : 'warning',
      message: `Fehleranalyse #${b.id} ${b.status === 'completed' ? 'abgeschlossen' : b.status}: ${b.marked_images} von ${b.processed} Bildern mit Fehlern`,
      caption: b.status === 'completed' ? 'Filter „Fehlerbilder“ zeigt die betroffenen Bilder' : (b.error ?? undefined),
    })
    if (b.status === 'completed') filter.value = 'errors'
    reload()
    emit('batchFinished')
    return
  }
  $q.notify({
    type: b.status === 'completed' ? 'positive' : 'warning',
    message: `Batch-Test #${b.id} ${b.status === 'completed' ? 'abgeschlossen' : b.status}: ${b.detections} Vorschläge für ${b.processed} Bilder`,
    caption: b.status === 'completed' ? 'Filter „Mit Vorschlägen“ zeigt die betroffenen Bilder' : (b.error ?? undefined),
  })
  if (b.status === 'completed') filter.value = 'suggestions'
  reload()
  emit('batchFinished')
}

function emitFilter() {
  // previous/next navigation: suggestions are on open images
  const f = filter.value === 'suggestions' ? 'unlabeled' : filter.value
  const level = f in SUGGESTION_LEVEL ? SUGGESTION_LEVEL[f as keyof typeof SUGGESTION_LEVEL] : undefined
  emit('filterChange', {
    status: ['unlabeled', 'unlabeled_no_suggestions', 'last_upload'].includes(f) ? 'unlabeled' : f === 'labeled' ? 'labeled' : undefined,
    last_upload: f === 'last_upload' || undefined,
    split: f === 'train' || f === 'validation' ? f : undefined,
    has_errors: f === 'errors' || undefined,
    duplicate: f === 'duplicates' || undefined,
    no_suggestions: f === 'unlabeled_no_suggestions' || undefined,
    suggestion_level: level,
  })
}

watch(filter, () => {
  emitFilter()
  reload()
})
onMounted(() => {
  if (filter.value !== 'all') emitFilter()
  reload()
})

defineExpose({ reload, patch, items, props })
</script>
