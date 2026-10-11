<template>
  <q-page :style-fn="pageStyle" class="column no-wrap">
    <div class="toolbar row items-center q-px-md bg-panel-soft q-gutter-x-sm no-wrap">
      <div class="text-subtitle1 text-weight-medium">Sichtung<HelpIcon term="review" inline /></div>
      <div class="text-caption text-muted ellipsis">
        Offene Bilder, auf denen der Batch-Test nichts gefunden hat, nach Kamera gruppiert · {{ groups.length }} Kameras ·
        {{ totalImages }} Bilder · {{ doneCount }} erledigt
      </div>
      <q-space />
      <q-btn
        unelevated
        dense
        no-caps
        color="negative"
        icon="delete"
        :label="`Markierte löschen (${deleteIds.length})`"
        :disable="!deleteIds.length"
        :loading="deleting"
        @click="deleteMarked"
      >
        <q-tooltip>Mit D markierte Bilder endgültig löschen (z. B. manuell gefundene Duplikate)</q-tooltip>
      </q-btn>
      <q-btn outline dense no-caps color="secondary" icon="refresh" label="Neu laden" :loading="loading" @click="load">
        <q-tooltip>Gruppen neu berechnen (erledigte Bilder verschwinden, neue Negativbilder dienen als Vergleich)</q-tooltip>
      </q-btn>
    </div>

    <q-banner v-if="untested" dense class="bg-amber-soft text-body2">
      <template #avatar><q-icon name="science" color="warning" /></template>
      {{ untested }} offene {{ untested === 1 ? 'Bild ist' : 'Bilder sind' }} noch nicht mit dem Modell getestet und
      {{ untested === 1 ? 'fehlt' : 'fehlen' }} hier. Die Sichtung zeigt nur Bilder, auf denen ein Batch-Test nichts gefunden hat –
      zuerst einen Batch-Test ausführen (Annotation → „Batch-Test“), dann „Neu laden“.
      <template #action>
        <q-btn flat dense no-caps label="Zur Annotation" :to="{ name: 'annotate' }" />
      </template>
    </q-banner>

    <div v-if="!groups.length && !loading" class="col flex flex-center text-muted text-center q-pa-lg">
      Keine getesteten offenen Bilder ohne Vorschläge. Die Sichtung zeigt nur Bilder, auf denen ein Batch-Test nichts gefunden hat.
    </div>

    <div v-else class="col row no-wrap" style="min-height: 0">
      <!-- camera groups -->
      <q-scroll-area class="group-col bg-panel">
        <q-list dense>
          <q-item
            v-for="(g, gi) in groups"
            :key="g.images[0].image.id"
            clickable
            :active="gi === groupIndex"
            active-class="bg-active"
            @click="groupIndex = gi"
          >
            <q-item-section avatar>
              <q-img :src="api.thumbnailUrl(g.images[0].image.id)" width="80px" :ratio="16 / 9" class="rounded-borders" loading="lazy" />
            </q-item-section>
            <q-item-section>
              <q-item-label>Kamera {{ gi + 1 }}</q-item-label>
              <q-item-label v-if="g.camera" caption class="ellipsis">
                {{ g.camera }}<q-tooltip>Aus den Bild-Metadaten (EXIF)</q-tooltip>
              </q-item-label>
              <q-item-label caption>{{ g.images.length }} Bilder</q-item-label>
              <q-item-label caption>
                <span :class="doneIn(g) === g.images.length ? 'text-positive' : ''">{{ doneIn(g) }} / {{ g.images.length }} erledigt</span>
              </q-item-label>
            </q-item-section>
          </q-item>
        </q-list>
      </q-scroll-area>

      <!-- images of the group -->
      <div v-if="group" class="col column no-wrap" style="min-width: 0">
        <div class="q-px-md q-py-sm row items-center q-gutter-x-sm">
          <div class="text-subtitle2">Kamera {{ groupIndex + 1 }} · {{ group.images.length }} Bilder</div>
          <span v-if="group.camera" class="text-caption text-muted">{{ group.camera }}</span>
          <span class="text-caption text-muted">Reihenfolge: jedes Bild folgt dem ähnlichsten – Unterschiede fallen beim Überblenden sofort auf.</span>
          <q-space />
          <q-btn unelevated dense no-caps color="primary" icon="play_arrow" label="Sichtung starten" @click="openLightbox(firstOpen())" />
        </div>
        <q-scroll-area class="col">
          <div class="q-px-md q-pb-md row q-col-gutter-sm">
            <div v-for="(e, i) in group.images" :key="e.image.id" class="col-6 col-md-4 col-lg-3">
              <div class="img-card rounded-borders cursor-pointer" :class="status[e.image.id] ? `img-card--${status[e.image.id]}` : ''" @click="openLightbox(i)">
                <q-img :src="api.thumbnailUrl(e.image.id)" :ratio="16 / 9" loading="lazy">
                  <div v-if="status[e.image.id]" class="absolute-top-right q-ma-xs status-chip" :class="`bg-${statusColor[status[e.image.id]!]}`">
                    {{ statusLabel[status[e.image.id]!] }}
                  </div>
                </q-img>
                <div class="row items-center no-wrap q-pl-sm">
                  <div class="col text-caption ellipsis">#{{ e.image.id }} {{ e.image.original_filename }}</div>
                  <q-btn
                    dense
                    flat
                    round
                    size="sm"
                    icon="delete"
                    :color="status[e.image.id] === 'delete' ? 'negative' : 'grey-6'"
                    :disable="status[e.image.id] === 'negative'"
                    @click.stop="toggleDelete(e.image.id)"
                  >
                    <q-tooltip>Zum Löschen markieren (D)</q-tooltip>
                  </q-btn>
                </div>
              </div>
            </div>
          </div>
        </q-scroll-area>
      </div>
    </div>

    <!-- lightbox -->
    <q-dialog v-model="lightbox" maximized transition-show="fade" transition-hide="fade">
      <div v-if="group && current" ref="lightboxEl" class="lightbox column no-wrap" tabindex="0" @keydown="onKey">
        <div class="row items-center q-px-md q-py-sm q-gutter-x-sm no-wrap text-white">
          <div class="text-subtitle1">Kamera {{ groupIndex + 1 }} · Bild {{ index + 1 }} / {{ group.images.length }} · #{{ current.image.id }}</div>
          <div class="text-caption text-grey-5">{{ compareText }}</div>
          <q-chip v-if="status[current.image.id]" dense :color="statusColor[status[current.image.id]!]" text-color="white" :label="statusLabel[status[current.image.id]!]" />
          <q-space />
          <q-btn-toggle
            v-model="mode"
            dense
            no-caps
            unelevated
            toggle-color="primary"
            color="grey-9"
            text-color="grey-4"
            :options="[
              { label: 'Überblenden', value: 'blink' },
              { label: 'Nebeneinander', value: 'side' },
            ]"
          />
          <q-btn flat round dense icon="close" color="white" v-close-popup />
        </div>

        <div class="col row no-wrap q-px-md q-gutter-x-md" style="min-height: 0">
          <div v-if="mode === 'side' && current.compare_with" class="col column no-wrap">
            <div class="text-caption text-grey-5 q-mb-xs">Vergleich #{{ current.compare_with }}</div>
            <div class="col img-box"><img :src="api.imageUrl(current.compare_with)" class="fit-img" alt="" /></div>
          </div>
          <div class="col column no-wrap">
            <div class="text-caption text-grey-5 q-mb-xs">
              <template v-if="mode === 'blink' && current.compare_with">
                {{ showCompare ? `Vergleich #${current.compare_with}` : `Bild #${current.image.id}` }} – Leertaste halten oder Maus drücken: Vergleichsbild
              </template>
              <template v-else>Bild #{{ current.image.id }}</template>
            </div>
            <div
              class="col img-box"
              @mousedown="mode === 'blink' && (showCompare = true)"
              @mouseup="showCompare = false"
              @mouseleave="showCompare = false"
            >
              <img :src="api.imageUrl(current.image.id)" class="fit-img" alt="" />
              <img
                v-if="mode === 'blink' && current.compare_with"
                v-show="showCompare"
                :src="api.imageUrl(current.compare_with)"
                class="fit-img overlay-img"
                alt=""
              />
            </div>
          </div>
        </div>

        <div class="row items-center justify-center q-pa-md q-gutter-md text-white">
          <q-btn flat round icon="chevron_left" color="white" :disable="index === 0" @click="step(-1)" />
          <q-btn unelevated no-caps color="secondary" icon="crop_free" label="Leer → negativ (N)" :loading="saving" @click="markNegative" />
          <q-btn unelevated no-caps color="primary" icon="edit" label="Objekt → annotieren (A)" @click="annotate" />
          <q-btn unelevated no-caps color="negative" icon="delete" label="Löschen (D)" :disable="status[current.image.id] === 'negative'" @click="markDelete" />
          <q-btn outline no-caps color="grey-5" label="Überspringen (→)" @click="step(1)" />
          <q-btn flat round icon="chevron_right" color="white" :disable="index >= group.images.length - 1" @click="step(1)" />
          <div class="text-caption text-grey-5">← → blättern · N leer · A annotieren (neuer Tab) · D löschen (nochmal D: aufheben) · Leertaste Vergleichsbild</div>
        </div>
        <!-- preload the next image and its comparison image -->
        <template v-if="group.images[index + 1]">
          <img :src="api.imageUrl(group.images[index + 1].image.id)" style="display: none" alt="" />
          <img v-if="group.images[index + 1].compare_with" :src="api.imageUrl(group.images[index + 1].compare_with!)" style="display: none" alt="" />
        </template>
      </div>
    </q-dialog>
  </q-page>
</template>

<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, reactive, ref } from 'vue'
import { useQuasar } from 'quasar'
import { useRouter } from 'vue-router'
import HelpIcon from '@/components/HelpIcon.vue'
import { api, errorMessage, type CameraGroup } from '@/services/api'

type Status = 'negative' | 'annotate' | 'delete'

const $q = useQuasar()
const router = useRouter()
const groups = ref<CameraGroup[]>([])
const untested = ref(0)
const groupIndex = ref(0)
const loading = ref(false)
const saving = ref(false)
// what happened to an image in this session (negatives are saved immediately)
const status = reactive<Record<number, Status>>({})
const statusLabel: Record<Status, string> = { negative: 'negativ', annotate: 'annotieren', delete: 'löschen' }
const statusColor: Record<Status, string> = { negative: 'secondary', annotate: 'primary', delete: 'negative' }
const deleting = ref(false)

const lightbox = ref(false)
const lightboxEl = ref<HTMLDivElement | null>(null)
const index = ref(0)
const mode = ref<'blink' | 'side'>('blink')
const showCompare = ref(false)

const group = computed(() => groups.value[groupIndex.value] ?? null)
const current = computed(() => group.value?.images[index.value] ?? null)
const deleteIds = computed(() => Object.keys(status).map(Number).filter((id) => status[id] === 'delete'))
const totalImages = computed(() => groups.value.reduce((n, g) => n + g.images.length, 0))
const doneCount = computed(() => groups.value.reduce((n, g) => n + doneIn(g), 0))
const compareText = computed(() => {
  const c = current.value
  if (!c?.compare_with) return 'kein Vergleichsbild (erstes Bild dieser Kamera, kein bekannt leeres Bild)'
  return c.compare_kind === 'negative'
    ? `Vergleich mit #${c.compare_with} (bekannt leer, ähnlichste Aufnahme)`
    : `Vergleich mit #${c.compare_with} (vorheriges Bild)`
})

function pageStyle(offset: number) {
  return { height: offset ? `calc(100vh - ${offset}px)` : '100vh' }
}

const doneIn = (g: CameraGroup) => g.images.filter((e) => status[e.image.id]).length
const firstOpen = () => Math.max(0, group.value?.images.findIndex((e) => !status[e.image.id]) ?? 0)

async function load() {
  loading.value = true
  try {
    const res = await api.cameraGroups()
    groups.value = res.groups
    untested.value = res.untested
    groupIndex.value = Math.min(groupIndex.value, Math.max(0, groups.value.length - 1))
    // delete marks survive a reload (not applied yet); everything else is reflected by the new groups
    const present = new Set(res.groups.flatMap((g) => g.images.map((e) => e.image.id)))
    for (const k of Object.keys(status).map(Number)) {
      if (status[k] !== 'delete' || !present.has(k)) delete status[k]
    }
  } catch (e) {
    $q.notify({ type: 'negative', message: errorMessage(e) })
  } finally {
    loading.value = false
  }
}

function openLightbox(i: number) {
  index.value = i
  showCompare.value = false
  lightbox.value = true
  nextTick(() => lightboxEl.value?.focus())
}

function step(delta: number) {
  if (!group.value) return
  index.value = Math.max(0, Math.min(group.value.images.length - 1, index.value + delta))
}

/** After an action: next open image of the group, or - when the group is done - back to the overview with the next group. */
function advance() {
  const g = group.value
  if (!g) return
  const n = g.images.length
  const next = Array.from({ length: n - 1 }, (_, k) => (index.value + 1 + k) % n).find((i) => !status[g.images[i].image.id])
  if (next !== undefined) {
    index.value = next
    return
  }
  lightbox.value = false
  const finished = groupIndex.value
  const m = groups.value.length
  const nextGroup = Array.from({ length: m - 1 }, (_, k) => (groupIndex.value + 1 + k) % m).find((i) => doneIn(groups.value[i]) < groups.value[i].images.length)
  if (nextGroup !== undefined) groupIndex.value = nextGroup
  $q.notify({
    type: 'positive',
    message: `Kamera ${finished + 1} fertig gesichtet`,
    caption: [
      nextGroup !== undefined ? `weiter mit Kamera ${nextGroup + 1}` : 'alle Kameras gesichtet',
      deleteIds.value.length ? `${deleteIds.value.length} zum Löschen markiert – „Markierte löschen“ oben` : '',
    ].filter(Boolean).join(' · '),
    timeout: 3000,
  })
}

async function markNegative() {
  const c = current.value
  if (!c || saving.value) return
  saving.value = true
  try {
    await api.saveAnnotations(c.image.id, [], true)
    status[c.image.id] = 'negative'
    advance()
  } catch (e) {
    $q.notify({ type: 'negative', message: errorMessage(e) })
  } finally {
    saving.value = false
  }
}

function annotate() {
  const c = current.value
  if (!c) return
  // new tab: the review keeps its place
  window.open(router.resolve({ name: 'annotate', params: { id: c.image.id } }).href, '_blank')
  status[c.image.id] = 'annotate'
  advance()
}

function toggleDelete(id: number) {
  if (status[id] === 'delete') delete status[id]
  else if (status[id] !== 'negative') status[id] = 'delete'
}

function markDelete() {
  const c = current.value
  if (!c || status[c.image.id] === 'negative') return
  if (status[c.image.id] === 'delete') {
    delete status[c.image.id] // pressed again: undo, stay on the image
    return
  }
  status[c.image.id] = 'delete'
  advance()
}

function deleteMarked() {
  const ids = deleteIds.value
  $q.dialog({
    title: 'Bilder löschen',
    message: `${ids.length} markierte Bilder endgültig löschen? Bilder, die in Trainings verwendet wurden, werden nur ausgeblendet.`,
    cancel: { label: 'Abbrechen', flat: true },
    ok: { label: 'Löschen', color: 'negative' },
    persistent: true,
  }).onOk(async () => {
    deleting.value = true
    let done = 0
    try {
      for (const id of ids) {
        await api.deleteImage(id)
        delete status[id]
        done++
      }
      $q.notify({ type: 'positive', message: `${done} Bilder gelöscht` })
    } catch (e) {
      $q.notify({ type: 'negative', message: errorMessage(e), caption: `${done} von ${ids.length} gelöscht` })
    } finally {
      deleting.value = false
      await load()
    }
  })
}

function onKey(e: KeyboardEvent) {
  if (!current.value) return
  const k = e.key.toLowerCase()
  if (e.key === 'ArrowRight') step(1)
  else if (e.key === 'ArrowLeft') step(-1)
  else if (k === 'n') markNegative()
  else if (k === 'a') annotate()
  else if (k === 'd' || e.key === 'Delete') markDelete()
  else if (e.key === ' ') {
    if (mode.value === 'blink') showCompare.value = true
  } else return
  e.preventDefault()
}
function onKeyUp(e: KeyboardEvent) {
  if (e.key === ' ') showCompare.value = false
}
window.addEventListener('keyup', onKeyUp)
onBeforeUnmount(() => window.removeEventListener('keyup', onKeyUp))

onMounted(load)
</script>

<style scoped>
.toolbar {
  height: 56px;
  min-height: 56px;
  border-bottom: 1px solid var(--app-border);
}
.group-col {
  width: 240px;
  min-width: 200px;
  border-right: 1px solid var(--app-border);
}
.img-card {
  border: 2px solid var(--app-border);
  overflow: hidden;
}
.img-card--negative {
  border-color: var(--q-secondary);
  opacity: 0.6;
}
.img-card--annotate {
  border-color: var(--q-primary);
}
.status-chip {
  color: #fff;
  font-size: 11px;
  padding: 1px 6px;
  border-radius: 4px;
}
.lightbox {
  background: #0b0d12;
  width: 100vw;
  height: 100vh;
  outline: none;
}
.img-box {
  position: relative;
  min-height: 0;
  background: #000;
  user-select: none;
}
.fit-img {
  width: 100%;
  height: 100%;
  object-fit: contain;
  display: block;
}
.overlay-img {
  position: absolute;
  inset: 0;
}
</style>
