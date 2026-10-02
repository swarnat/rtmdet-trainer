<template>
  <div class="column no-wrap full-height">
    <div class="q-pa-sm column q-gutter-sm">
      <q-btn-toggle
        v-model="filter"
        spread
        dense
        no-caps
        toggle-color="primary"
        :options="[
          { label: 'Alle', value: 'all' },
          { label: 'Offen', value: 'unlabeled' },
          { label: 'Fertig', value: 'labeled' },
          { label: 'Negativ', value: 'negative' },
        ]"
      />
      <div class="row items-center no-wrap q-gutter-x-sm">
        <q-btn color="primary" icon="upload" label="Bilder hochladen" no-caps class="col" :loading="uploading" @click="fileInput?.click()" />
        <q-btn flat round dense icon="refresh" @click="reload"><q-tooltip>Neu laden</q-tooltip></q-btn>
      </div>
      <input ref="fileInput" type="file" accept="image/jpeg,image/png,image/webp,image/bmp" multiple hidden @change="onFiles" />
      <div class="text-caption text-grey-7">{{ total }} Bilder</div>
    </div>
    <q-separator />
    <q-scroll-area class="col" @dragover.prevent @drop.prevent="onDrop">
      <q-list dense>
        <q-item
          v-for="img in items"
          :key="img.id"
          clickable
          :active="img.id === selectedId"
          active-class="bg-blue-1"
          @click="emit('select', img.id)"
        >
          <q-item-section avatar>
            <q-img :src="api.thumbnailUrl(img.id)" width="96px" :ratio="16 / 9" class="rounded-borders" loading="lazy" />
          </q-item-section>
          <q-item-section>
            <q-item-label class="ellipsis">#{{ img.id }} {{ img.original_filename }}</q-item-label>
            <q-item-label caption>
              <q-badge v-if="img.annotation_status === 'unlabeled'" color="grey-6" label="offen" />
              <q-badge v-else-if="img.annotation_count === 0" color="purple-6" label="negativ" />
              <q-badge v-else color="green-7" :label="`${img.annotation_count} Boxen`" />
              <q-badge v-if="img.dataset_split" outline color="blue-grey" class="q-ml-xs" :label="img.dataset_split === 'train' ? 'train' : 'val'" />
            </q-item-label>
          </q-item-section>
        </q-item>
      </q-list>
      <div v-if="items.length < total" class="q-pa-sm text-center">
        <q-btn flat dense no-caps label="Mehr laden" :loading="loading" @click="loadMore" />
      </div>
      <div v-if="!items.length && !loading" class="q-pa-md text-grey-7 text-center">
        Keine Bilder. Hochladen per Button oder Drag &amp; Drop.
      </div>
    </q-scroll-area>
  </div>
</template>

<script setup lang="ts">
import { onMounted, ref, watch } from 'vue'
import { useQuasar } from 'quasar'
import { api, errorMessage, type ImageItem } from '@/services/api'

const props = defineProps<{ selectedId: number | null }>()
const emit = defineEmits<{ select: [id: number]; filterChange: [status: string | undefined] }>()
const $q = useQuasar()

const PAGE = 100
const filter = ref<'all' | 'unlabeled' | 'labeled' | 'negative'>('all')
const items = ref<ImageItem[]>([])
const total = ref(0)
const loading = ref(false)
const uploading = ref(false)
const fileInput = ref<HTMLInputElement | null>(null)

function query(offset: number) {
  return api.listImages({
    status: filter.value === 'unlabeled' || filter.value === 'labeled' ? filter.value : undefined,
    negative: filter.value === 'negative',
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

watch(filter, () => {
  emit('filterChange', filter.value === 'unlabeled' || filter.value === 'labeled' ? filter.value : undefined)
  reload()
})
onMounted(reload)

defineExpose({ reload, patch, items, props })
</script>
