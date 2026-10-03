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
        :options="[
          { label: 'Alle Bilder', value: 'all' },
          { label: 'Offen', value: 'unlabeled' },
          { label: 'Fertig annotiert', value: 'labeled' },
          { label: 'Negativ (ohne Objekte)', value: 'negative' },
          { label: 'Nachprüfen (neue Klassen)', value: 'review' },
          { label: 'Mit Vorschlägen (Batch-Test)', value: 'suggestions' },
        ]"
      />
      <div class="row items-center no-wrap q-gutter-x-sm">
        <q-btn color="primary" icon="upload" label="Hochladen" dense no-caps no-wrap class="col q-py-xs" :loading="uploading" @click="fileInput?.click()" />
        <q-btn color="secondary" icon="playlist_play" label="Batch-Test" dense no-caps no-wrap class="col q-py-xs" @click="batchDialog = true">
          <q-tooltip>Modell auf allen offenen Bildern testen und Vorschläge speichern</q-tooltip>
        </q-btn>
        <q-btn flat round dense icon="refresh" @click="reload"><q-tooltip>Neu laden</q-tooltip></q-btn>
      </div>
      <div v-if="runningBatch" class="cursor-pointer" @click="batchDialog = true">
        <div class="text-caption text-secondary">
          Batch-Test #{{ runningBatch.id }} läuft: {{ runningBatch.processed }} / {{ runningBatch.total }}
        </div>
        <q-linear-progress :value="runningBatch.total ? runningBatch.processed / runningBatch.total : 0" color="secondary" rounded />
      </div>
      <BatchTestDialog v-model="batchDialog" @running="(b) => (runningBatch = b)" @finished="onBatchFinished" />
      <input ref="fileInput" type="file" accept="image/jpeg,image/png,image/webp,image/bmp" multiple hidden @change="onFiles" />
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
            <q-item-label class="ellipsis">#{{ img.id }} {{ img.original_filename }}</q-item-label>
            <q-item-label caption>
              <q-badge v-if="img.annotation_status === 'unlabeled'" outline color="grey-5" label="offen" />
              <q-badge v-else-if="img.annotation_count === 0" outline color="secondary" label="negativ" />
              <q-badge v-else outline color="positive" :label="`${img.annotation_count} Boxen`" />
              <q-badge v-if="img.suggestion_count != null" outline color="secondary" class="q-ml-xs" :label="`${img.suggestion_count} Vorschl.`">
                <q-tooltip>Vorschläge aus einem Batch-Test</q-tooltip>
              </q-badge>
              <q-badge v-if="img.hard_negative_count" outline color="blue-grey-3" class="q-ml-xs" :label="`${img.hard_negative_count} HN`">
                <q-tooltip>Hard Negatives (bekannte Fehlalarme)</q-tooltip>
              </q-badge>
              <q-badge v-if="img.needs_review" outline color="warning" class="q-ml-xs" label="prüfen">
                <q-tooltip>Noch nicht auf alle aktiven Klassen geprüft</q-tooltip>
              </q-badge>
              <q-badge v-if="img.dataset_split" outline color="primary" class="q-ml-xs" :label="img.dataset_split === 'train' ? 'train' : 'val'" />
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
import BatchTestDialog from './BatchTestDialog.vue'
import { api, errorMessage, type BatchTest, type ImageItem } from '@/services/api'

const props = defineProps<{ selectedId: number | null }>()
const emit = defineEmits<{ select: [id: number]; filterChange: [status: string | undefined]; batchFinished: [] }>()
const $q = useQuasar()

const PAGE = 100
const filter = ref<'all' | 'unlabeled' | 'labeled' | 'negative' | 'review' | 'suggestions'>('all')
const batchDialog = ref(false)
const runningBatch = ref<BatchTest | null>(null)
const items = ref<ImageItem[]>([])
const total = ref(0)
const loading = ref(false)
const uploading = ref(false)
const fileInput = ref<HTMLInputElement | null>(null)

function query(offset: number) {
  return api.listImages({
    status: filter.value === 'unlabeled' || filter.value === 'labeled' ? filter.value : undefined,
    negative: filter.value === 'negative',
    needs_review: filter.value === 'review',
    has_suggestions: filter.value === 'suggestions',
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
  const errors: string[] = []
  try {
    // upload in chunks to keep requests small
    for (let i = 0; i < files.length; i += 10) {
      const results = await api.uploadImages(files.slice(i, i + 10))
      for (const r of results) {
        if (r.status === 'created') created++
        else if (r.status === 'duplicate') duplicates++
        else errors.push(`${r.filename}: ${r.error}`)
      }
    }
    $q.notify({
      type: errors.length ? 'warning' : 'positive',
      message: `${created} hochgeladen, ${duplicates} Duplikate${errors.length ? `, ${errors.length} Fehler` : ''}`,
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

function onBatchFinished(b: BatchTest) {
  $q.notify({
    type: b.status === 'completed' ? 'positive' : 'warning',
    message: `Batch-Test #${b.id} ${b.status === 'completed' ? 'abgeschlossen' : b.status}: ${b.detections} Vorschläge für ${b.processed} Bilder`,
    caption: b.status === 'completed' ? 'Filter „Mit Vorschlägen“ zeigt die betroffenen Bilder' : (b.error ?? undefined),
  })
  if (b.status === 'completed') filter.value = 'suggestions'
  reload()
  emit('batchFinished')
}

watch(filter, () => {
  // previous/next navigation: suggestions are on open images
  const status = filter.value === 'suggestions' ? 'unlabeled' : filter.value
  emit('filterChange', status === 'unlabeled' || status === 'labeled' ? status : undefined)
  reload()
})
onMounted(reload)

defineExpose({ reload, patch, items, props })
</script>
