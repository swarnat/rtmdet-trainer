<template>
  <q-page class="q-pa-md">
    <div class="row items-center q-gutter-sm q-mb-sm">
      <div class="text-h6">Annotationen kontrollieren<HelpIcon term="annotationReview" inline /></div>
      <div class="text-caption text-muted">Jede annotierte Box als Ausschnitt mit {{ margin }} Pixeln Rand – Klick öffnet das Bild.</div>
      <q-space />
      <q-btn outline dense no-caps color="secondary" icon="refresh" label="Neu laden" :loading="loading" @click="reload">
        <q-tooltip>Nach Korrekturen im Annotations-Tab neu laden</q-tooltip>
      </q-btn>
    </div>

    <q-tabs v-model="cls" dense no-caps inline-label align="left" active-color="primary" indicator-color="primary" class="q-mb-sm">
      <q-tab v-for="c in counts" :key="c.class" :name="c.class">
        <div class="row items-center no-wrap q-gutter-x-xs">
          <span class="swatch" :style="{ background: classes.info(c.class).color }" />
          <span>{{ classes.info(c.class).label }}</span>
          <q-badge rounded color="grey-7" :label="badgeCount(c)" />
        </div>
      </q-tab>
    </q-tabs>

    <div class="row items-center q-gutter-sm q-mb-md">
      <q-btn-toggle
        v-model="type"
        dense
        no-caps
        unelevated
        toggle-color="primary"
        :options="[
          { label: 'Objekte', value: 'positive' },
          { label: 'Hard Negatives', value: 'hard_negative' },
          { label: 'Ignoriert', value: 'ignore' },
        ]"
      />
      <q-toggle v-model="reflectedOnly" dense label="Nur Spiegelungen" />
      <q-select v-model="split" :options="splitOptions" emit-value map-options dense outlined label="Split" style="min-width: 140px" />
      <q-select v-model="sort" :options="sortOptions" emit-value map-options dense outlined label="Sortierung" style="min-width: 220px" />
      <div class="row items-center no-wrap" style="width: 200px">
        <q-icon name="photo_size_select_large" class="q-mr-sm text-muted" />
        <q-slider v-model="tileHeight" :min="60" :max="260" :step="20" dense />
      </div>
      <q-toggle v-model="showBox" dense label="Box einzeichnen" />
      <q-space />
      <div class="text-caption text-muted">{{ items.length }} von {{ total }}</div>
    </div>

    <div v-if="!loading && !items.length" class="text-muted q-pa-lg text-center">Keine Annotationen für diese Auswahl.</div>

    <div class="tiles">
      <a
        v-for="c in items"
        :key="c.id"
        class="tile"
        :href="`/annotate/${c.image_id}`"
        target="_blank"
        :style="tileStyle(c)"
      >
        <img :src="api.cropUrl(c)" loading="lazy" :alt="`#${c.image_id}`" />
        <div v-if="showBox" class="box" :style="boxStyle(c)" />
        <div class="label">#{{ c.image_id }}<span v-if="c.dataset_split === 'validation'"> · V</span></div>
        <q-tooltip :delay="400">
          Bild #{{ c.image_id }} · {{ Math.round(c.x2 - c.x1) }}×{{ Math.round(c.y2 - c.y1) }} px ·
          {{ c.dataset_split === 'validation' ? 'Validierung' : c.dataset_split === 'train' ? 'Training' : 'kein Split' }} ·
          {{ c.source === 'prediction' ? 'aus Vorschlag übernommen' : 'manuell' }} · {{ fmtDate(c.updated_at) }}
        </q-tooltip>
      </a>
    </div>

    <div v-if="items.length < total" class="row justify-center q-mt-md">
      <q-btn outline no-caps color="primary" :label="`Weitere ${Math.min(PAGE, total - items.length)} laden`" :loading="loading" @click="loadMore" />
    </div>
  </q-page>
</template>

<script setup lang="ts">
import { onMounted, ref, watch } from 'vue'
import { useQuasar } from 'quasar'
import HelpIcon from '@/components/HelpIcon.vue'
import { api, errorMessage, fmtDate, type AnnotationType, type ReviewClassCount, type ReviewCrop, type ReviewSort } from '@/services/api'
import { useClassesStore } from '@/stores/classes'

const PAGE = 300
const $q = useQuasar()
const classes = useClassesStore()

const counts = ref<ReviewClassCount[]>([])
const cls = ref('')
const type = ref<AnnotationType>('positive')
const reflectedOnly = ref(false)

function badgeCount(c: ReviewClassCount) {
  return reflectedOnly.value ? c[`${type.value}_reflected`] : c[type.value]
}
const split = ref<'' | 'train' | 'validation'>('')
const sort = ref<ReviewSort>('newest')
const tileHeight = ref(stored('review-tile-height', 120))
const showBox = ref(stored('review-show-box', true))
const items = ref<ReviewCrop[]>([])
const total = ref(0)
const margin = ref(20)
const loading = ref(false)

const splitOptions = [
  { label: 'Alle', value: '' },
  { label: 'Training', value: 'train' },
  { label: 'Validierung', value: 'validation' },
]
const sortOptions: { label: string; value: ReviewSort }[] = [
  { label: 'Zuletzt bearbeitet', value: 'newest' },
  { label: 'Älteste zuerst', value: 'oldest' },
  { label: 'Kleinste Boxen zuerst', value: 'smallest' },
  { label: 'Größte Boxen zuerst', value: 'largest' },
  { label: 'Breiteste zuerst (liegend, 2 Objekte)', value: 'widest' },
  { label: 'Schmalste zuerst', value: 'tallest' },
  { label: 'Nach Bild', value: 'image' },
]

function stored<T>(key: string, fallback: T): T {
  try {
    const v = localStorage.getItem(key)
    return v == null ? fallback : (JSON.parse(v) as T)
  } catch {
    return fallback
  }
}
function remember(key: string, value: unknown) {
  try {
    localStorage.setItem(key, JSON.stringify(value))
  } catch {
    /* storage unavailable: setting just isn't kept */
  }
}
watch(tileHeight, (v) => remember('review-tile-height', v))
watch(showBox, (v) => remember('review-show-box', v))

// crop window in original pixels: same formula as the backend (box + margin, clipped to the image)
function cropWindow(c: ReviewCrop) {
  const x1 = Math.max(0, Math.floor(c.x1 - margin.value))
  const y1 = Math.max(0, Math.floor(c.y1 - margin.value))
  const x2 = Math.min(c.image_width, Math.ceil(c.x2 + margin.value))
  const y2 = Math.min(c.image_height, Math.ceil(c.y2 + margin.value))
  return { x1, y1, w: Math.max(1, x2 - x1), h: Math.max(1, y2 - y1) }
}

function tileStyle(c: ReviewCrop) {
  const w = cropWindow(c)
  // very wide crops are capped, the height shrinks with them (aspect ratio stays exact for the box overlay)
  const width = Math.min(tileHeight.value * (w.w / w.h), tileHeight.value * 3)
  return { width: `${width}px`, height: `${width * (w.h / w.w)}px` }
}

function boxStyle(c: ReviewCrop) {
  const w = cropWindow(c)
  return {
    left: `${((c.x1 - w.x1) / w.w) * 100}%`,
    top: `${((c.y1 - w.y1) / w.h) * 100}%`,
    width: `${((c.x2 - c.x1) / w.w) * 100}%`,
    height: `${((c.y2 - c.y1) / w.h) * 100}%`,
    borderColor: classes.info(c.class).color,
  }
}

async function loadCounts() {
  counts.value = await api.reviewClasses()
  if (!counts.value.some((c) => c.class === cls.value)) cls.value = counts.value[0]?.class ?? ''
}

let request = 0
async function load(append = false) {
  if (!cls.value) {
    items.value = []
    total.value = 0
    return
  }
  const id = ++request
  loading.value = true
  try {
    const res = await api.reviewCrops({
      class: cls.value, type: type.value, reflected: reflectedOnly.value, split: split.value || undefined, sort: sort.value,
      offset: append ? items.value.length : 0, limit: PAGE,
    })
    if (id !== request) return // a newer selection is loading
    margin.value = res.margin
    total.value = res.total
    items.value = append ? [...items.value, ...res.items] : res.items
  } catch (e) {
    $q.notify({ type: 'negative', message: errorMessage(e) })
  } finally {
    if (id === request) loading.value = false
  }
}

const loadMore = () => load(true)
async function reload() {
  try {
    await loadCounts()
  } catch (e) {
    $q.notify({ type: 'negative', message: errorMessage(e) })
  }
  await load()
}

watch([cls, type, reflectedOnly, split, sort], () => load())
onMounted(() => {
  classes.refresh()
  reload()
})
</script>

<style scoped>
.tiles {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  align-items: flex-end;
}
.tile {
  position: relative;
  display: block;
  overflow: hidden;
  border-radius: 4px;
  background: #222;
  outline: 1px solid rgba(128, 128, 128, 0.3);
}
.tile:hover {
  outline: 2px solid var(--q-primary);
}
.tile img {
  display: block;
  width: 100%;
  height: 100%;
}
.box {
  position: absolute;
  border: 1px solid;
  pointer-events: none;
  box-sizing: border-box;
}
.label {
  position: absolute;
  left: 0;
  bottom: 0;
  padding: 0 4px;
  font-size: 10px;
  line-height: 14px;
  color: #fff;
  background: rgba(0, 0, 0, 0.55);
  border-top-right-radius: 4px;
  opacity: 0;
  transition: opacity 0.1s;
}
.tile:hover .label {
  opacity: 1;
}
.swatch {
  width: 10px;
  height: 10px;
  border-radius: 2px;
  display: inline-block;
}
</style>
