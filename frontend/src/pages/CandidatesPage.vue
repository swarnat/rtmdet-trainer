<template>
  <q-page class="q-pa-md">
    <div class="row items-center q-gutter-sm q-mb-sm">
      <div class="text-h6">Kandidaten finden<HelpIcon term="candidateSearch" inline /></div>
      <div class="text-caption text-muted">Objekte einer (neuen) Klasse in den vorhandenen Bildern suchen und schnell übernehmen.</div>
    </div>

    <!-- new search -->
    <q-card flat bordered class="q-mb-md">
      <q-card-section class="q-pb-none">
        <q-btn-toggle
          v-model="form.mode" dense no-caps unelevated toggle-color="primary"
          :options="[{ label: 'Per Text', value: 'text', icon: 'text_fields' }, { label: 'Mit Beispielen', value: 'examples', icon: 'image_search' }]"
        />
        <span class="text-caption text-muted q-ml-sm">
          {{ form.mode === 'text' ? 'Objekte per Begriff beschreiben' : 'Objekte finden, die gewählten Beispielen ähneln – funktioniert auch ohne passenden Begriff' }}
        </span>
      </q-card-section>
      <q-card-section class="row items-start q-col-gutter-sm">
        <q-select
          v-model="form.class" :options="classOptions" emit-value map-options dense outlined label="Klasse" class="col-12 col-sm-3"
          hint="Diese Klasse bekommen übernommene Treffer"
        />
        <q-input
          v-if="form.mode === 'text'"
          v-model="form.prompts" dense outlined label="Suchbegriffe (englisch, mit Komma trennen)" class="col-12 col-sm-4"
          placeholder="excavator, digger" hint="z. B. excavator, digger" @keyup.enter="start"
        />
        <div v-else class="col-12 col-sm-4">
          <q-btn outline no-caps color="secondary" icon="add_photo_alternate" :label="examples.length ? `Beispiele ändern (${examples.length})` : 'Beispiele wählen'" @click="pickerOpen = true" />
          <div v-if="!examples.length" class="text-caption text-muted q-mt-xs">Vorhandene Annotationen als Vorbild wählen</div>
          <div v-else class="row q-gutter-xs q-mt-xs">
            <div v-for="e in examples" :key="e.id" class="example-thumb" :title="`Bild #${e.image_id}`">
              <img :src="api.cropUrl(e)" draggable="false" alt="" />
              <q-btn dense flat round size="xs" icon="close" class="remove" @click="examples = examples.filter((x) => x.id !== e.id)" />
            </div>
          </div>
        </div>
        <q-select v-model="form.scope" :options="scopeOptions" emit-value map-options dense outlined label="Bilder" class="col-6 col-sm-2" />
        <q-input v-model.number="form.max_images" type="number" min="0" dense outlined label="Max. Bilder" class="col-6 col-sm-1" hint="0 = alle">
          <q-tooltip>Für einen schnellen Test: nur die ersten n Bilder durchsuchen</q-tooltip>
        </q-input>
        <q-input v-model.number="form.min_score" type="number" min="0.01" max="0.95" step="0.05" dense outlined label="Min. Score" class="col-6 col-sm-1">
          <q-tooltip>Treffer darunter werden nicht gespeichert. Niedriger = mehr Treffer, mehr Fehlalarme</q-tooltip>
        </q-input>
        <div class="col-6 col-sm-1">
          <q-btn unelevated no-caps color="primary" icon="search" label="Suchen" :loading="starting" :disable="busy || !form.class" @click="start" />
        </div>
      </q-card-section>
      <q-card-section v-if="busy" class="q-pt-none text-caption text-muted">
        Es läuft bereits eine Suche (#{{ current?.id }}). Sie kann unten abgebrochen werden.
      </q-card-section>
    </q-card>

    <ExamplePicker v-model="pickerOpen" :initial-class="form.class" :selected="examples" @confirm="(list) => (examples = list)" />

    <!-- searches -->
    <div v-if="!searches.length" class="text-muted q-pa-lg text-center">Noch keine Suche gestartet.</div>
    <template v-else>
      <div class="row items-center q-gutter-sm q-mb-sm">
        <q-select v-model="searchId" :options="searchOptions" emit-value map-options dense outlined label="Suche" style="min-width: 380px" />
        <template v-if="current">
          <q-badge :color="statusColor[current.status]" :label="statusLabel[current.status]" />
          <span class="text-caption text-muted">
            {{ current.processed }} / {{ current.total }} Bilder · {{ current.found }} Treffer<span v-if="current.model && ui.advanced"> · {{ current.model }}</span>
          </span>
          <q-space />
          <q-btn v-if="busy" outline dense no-caps color="negative" icon="stop" label="Abbrechen" @click="cancel" />
          <q-btn v-else outline dense no-caps color="negative" icon="delete" label="Suche löschen" @click="remove" />
        </template>
      </div>
      <q-linear-progress v-if="current && busy" :value="current.total ? current.processed / current.total : 0" :indeterminate="!current.total" class="q-mb-sm" />
      <q-banner v-if="current?.error" dense rounded class="bg-negative-soft text-body2 q-mb-sm">{{ current.error }}</q-banner>

      <template v-if="current">
        <div class="row items-center q-gutter-sm q-mb-md">
          <q-btn-toggle
            v-model="status" dense no-caps unelevated toggle-color="primary"
            :options="[
              { label: `Offen (${current.pending})`, value: 'pending' },
              { label: `Übernommen (${current.accepted})`, value: 'accepted' },
              { label: `Abgelehnt (${current.rejected})`, value: 'rejected' },
            ]"
          />
          <div class="row items-center no-wrap" style="width: 220px">
            <span class="text-caption q-mr-sm no-wrap">ab {{ minScore.toFixed(2) }}</span>
            <q-slider v-model="minScore" :min="current.min_score" :max="0.9" :step="0.05" dense label />
            <q-tooltip>Nur Treffer mit mindestens diesem Score zeigen</q-tooltip>
          </div>
          <q-select v-model="sort" :options="sortOptions" emit-value map-options dense outlined label="Sortierung" style="min-width: 200px" />
          <div class="row items-center no-wrap" style="width: 160px">
            <q-icon name="photo_size_select_large" class="q-mr-sm text-muted" />
            <q-slider v-model="tileHeight" :min="80" :max="300" :step="20" dense />
          </div>
          <q-space />
          <div class="text-caption text-muted">{{ items.length }} von {{ total }}</div>
        </div>

        <div class="row items-center q-gutter-sm q-mb-md">
          <q-btn unelevated no-caps color="positive" icon="check" :label="`Übernehmen (${selected.size})`" :disable="!selected.size || deciding" @click="decide('accept')">
            <q-tooltip>Ausgewählte Treffer übernehmen (Enter)</q-tooltip>
          </q-btn>
          <q-btn unelevated no-caps color="negative" icon="block" :label="`Ablehnen (${selected.size})`" :disable="!selected.size || deciding" @click="decide('reject')">
            <q-tooltip>Ausgewählte Treffer ablehnen (N)</q-tooltip>
          </q-btn>
          <q-btn flat dense no-caps icon="select_all" label="Alle sichtbaren wählen" :disable="!items.length" @click="selectAll" />
          <q-btn flat dense no-caps icon="deselect" label="Auswahl leeren" :disable="!selected.size" @click="selected.clear()" />
          <q-space />
          <div class="text-caption text-muted">
            Klick = auswählen · Pfeil-Symbol öffnet das Bild
            <HelpIcon term="candidateReview" inline />
          </div>
        </div>

        <div v-if="!loading && !items.length" class="text-muted q-pa-lg text-center">
          {{ busy && status === 'pending' ? 'Noch keine Treffer – die Suche läuft.' : 'Keine Treffer für diese Auswahl.' }}
        </div>

        <div class="tiles">
          <div
            v-for="c in items" :key="c.id" class="tile" :class="{ selected: selected.has(c.id), exists: c.action === 'exists' }"
            :style="tileStyle(c)" @click="toggle(c.id)"
          >
            <img :src="api.candidateCropUrl(c)" loading="lazy" :alt="`#${c.image_id}`" draggable="false" />
            <div class="box" :style="boxStyle(c)" />
            <div class="score">{{ Math.round(c.score * 100) }} %</div>
            <a class="open" :href="`/annotate/${c.image_id}`" target="_blank" @click.stop><q-icon name="open_in_new" size="14px" /></a>
            <div class="label" :class="c.action">{{ actionLabel(c) }}</div>
            <div v-if="selected.has(c.id)" class="check"><q-icon name="check_circle" color="positive" size="22px" /></div>
            <q-tooltip :delay="500">
              Bild #{{ c.image_id }} · „{{ c.prompt }}“ · {{ Math.round(c.x2 - c.x1) }}×{{ Math.round(c.y2 - c.y1) }} px ·
              {{ c.action === 'new' ? 'Übernehmen legt eine neue Box an' : c.action === 'reclassify' ? `Übernehmen ändert die vorhandene Box (${classes.info(c.current_class ?? '').label}) auf diese Klasse` : 'Hier ist schon eine Box dieser Klasse' }}
            </q-tooltip>
          </div>
        </div>

        <div v-if="items.length < total" class="row justify-center q-mt-md">
          <q-btn outline no-caps color="primary" :label="`Weitere ${Math.min(PAGE, total - items.length)} laden`" :loading="loading" @click="load(true)" />
        </div>
      </template>
    </template>
  </q-page>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { useQuasar } from 'quasar'
import ExamplePicker from '@/components/ExamplePicker.vue'
import HelpIcon from '@/components/HelpIcon.vue'
import { api, errorMessage, type Candidate, type CandidateSearch, type ReviewCrop } from '@/services/api'
import { useClassesStore } from '@/stores/classes'
import { useUiStore } from '@/stores/ui'

const PAGE = 300
const $q = useQuasar()
const classes = useClassesStore()
const ui = useUiStore()

const statusLabel = { queued: 'wartet', running: 'läuft', completed: 'fertig', failed: 'fehlgeschlagen', cancelled: 'abgebrochen' }
const statusColor = { queued: 'grey-5', running: 'secondary', completed: 'positive', failed: 'negative', cancelled: 'warning' }
const scopeOptions = [
  { label: 'Alle Bilder', value: 'all' },
  { label: 'Nur annotierte', value: 'labeled' },
  { label: 'Nur offene', value: 'unlabeled' },
]
const sortOptions = [
  { label: 'Beste zuerst', value: 'score' },
  { label: 'Nach Bild', value: 'image' },
]

const classOptions = computed(() => classes.active.map((c) => ({ value: c.name, label: c.label })))
const form = reactive({ mode: 'text' as 'text' | 'examples', class: '', prompts: '', scope: 'all', max_images: 0, min_score: 0.1 })
const examples = ref<ReviewCrop[]>([])
const pickerOpen = ref(false)
// example matches are scored differently (a clear match is ~0.8+): a higher default threshold
watch(() => form.mode, (mode) => (form.min_score = mode === 'examples' ? 0.3 : 0.1))
const starting = ref(false)

const searches = ref<CandidateSearch[]>([])
const searchId = ref<number | null>(null)
const current = computed(() => searches.value.find((s) => s.id === searchId.value) ?? null)
const busy = computed(() => searches.value.some((s) => s.status === 'queued' || s.status === 'running'))
const searchOptions = computed(() =>
  searches.value.map((s) => ({
    value: s.id,
    label: `#${s.id} · ${classes.info(s.class).label} · ${s.mode === 'examples' ? `${s.examples} Beispiele` : `„${s.prompts.join(', ')}“`} · ${s.found} Treffer`,
  })),
)

const status = ref<'pending' | 'accepted' | 'rejected'>('pending')
const minScore = ref(0.2)
const sort = ref<'score' | 'image'>('score')
const tileHeight = ref(stored('candidates-tile-height', 160))
const items = ref<Candidate[]>([])
const total = ref(0)
const margin = ref(20)
const loading = ref(false)
const deciding = ref(false)
const selected = reactive(new Set<number>())

function stored<T>(key: string, fallback: T): T {
  try {
    const v = localStorage.getItem(key)
    return v == null ? fallback : (JSON.parse(v) as T)
  } catch {
    return fallback
  }
}
watch(tileHeight, (v) => {
  try {
    localStorage.setItem('candidates-tile-height', JSON.stringify(v))
  } catch {
    /* storage unavailable: the size just isn't kept */
  }
})

// crop window in original pixels: same formula as the backend (box + margin, clipped to the image)
function cropWindow(c: Candidate) {
  const x1 = Math.max(0, Math.floor(c.x1 - margin.value))
  const y1 = Math.max(0, Math.floor(c.y1 - margin.value))
  const x2 = Math.min(c.image_width, Math.ceil(c.x2 + margin.value))
  const y2 = Math.min(c.image_height, Math.ceil(c.y2 + margin.value))
  return { x1, y1, w: Math.max(1, x2 - x1), h: Math.max(1, y2 - y1) }
}

function tileStyle(c: Candidate) {
  const w = cropWindow(c)
  const width = Math.min(tileHeight.value * (w.w / w.h), tileHeight.value * 3)
  return { width: `${width}px`, height: `${width * (w.h / w.w)}px` }
}

function boxStyle(c: Candidate) {
  const w = cropWindow(c)
  return {
    left: `${((c.x1 - w.x1) / w.w) * 100}%`,
    top: `${((c.y1 - w.y1) / w.h) * 100}%`,
    width: `${((c.x2 - c.x1) / w.w) * 100}%`,
    height: `${((c.y2 - c.y1) / w.h) * 100}%`,
    borderColor: classes.info(current.value?.class ?? '').color,
  }
}

function actionLabel(c: Candidate) {
  if (c.action === 'reclassify') return `ersetzt: ${classes.info(c.current_class ?? '').label}`
  return c.action === 'exists' ? 'schon vorhanden' : 'neu'
}

function toggle(id: number) {
  if (selected.has(id)) selected.delete(id)
  else selected.add(id)
}
function selectAll() {
  items.value.forEach((c) => selected.add(c.id))
}

async function refreshSearches(keepSelection = true) {
  searches.value = await api.candidateSearches()
  if (!keepSelection || !searches.value.some((s) => s.id === searchId.value)) searchId.value = searches.value[0]?.id ?? null
}

let request = 0
async function load(append = false) {
  if (!current.value) {
    items.value = []
    total.value = 0
    return
  }
  const id = ++request
  loading.value = true
  try {
    const res = await api.candidates(current.value.id, {
      status: status.value, min_score: minScore.value, sort: sort.value, offset: append ? items.value.length : 0, limit: PAGE,
    })
    if (id !== request) return // a newer selection is loading
    margin.value = res.margin
    total.value = res.total
    items.value = append ? [...items.value, ...res.items] : res.items
    const present = new Set(items.value.map((c) => c.id))
    for (const sel of [...selected]) if (!present.has(sel)) selected.delete(sel)
  } catch (e) {
    $q.notify({ type: 'negative', message: errorMessage(e) })
  } finally {
    if (id === request) loading.value = false
  }
}

async function start() {
  const prompts = form.prompts.split(',').map((p) => p.trim()).filter(Boolean)
  const byExample = form.mode === 'examples'
  if (!form.class || (byExample ? !examples.value.length : !prompts.length)) {
    $q.notify({ type: 'warning', message: byExample ? 'Klasse und mindestens ein Beispiel wählen' : 'Klasse und mindestens einen Suchbegriff angeben' })
    return
  }
  starting.value = true
  try {
    const s = await api.startCandidateSearch({
      class: form.class, mode: form.mode, scope: form.scope, max_images: form.max_images || 0, min_score: form.min_score,
      ...(byExample ? { exemplar_ids: examples.value.map((e) => e.id) } : { prompts }),
    })
    await refreshSearches(false)
    searchId.value = s.id
    status.value = 'pending'
    minScore.value = Math.max(s.min_score, 0.2)
    $q.notify({ type: 'positive', message: `Suche #${s.id} gestartet`, timeout: 1500 })
  } catch (e) {
    $q.notify({ type: 'negative', message: errorMessage(e) })
  } finally {
    starting.value = false
  }
}

async function cancel() {
  if (!current.value) return
  try {
    await api.cancelCandidateSearch(current.value.id)
    await refreshSearches()
  } catch (e) {
    $q.notify({ type: 'negative', message: errorMessage(e) })
  }
}

function remove() {
  const s = current.value
  if (!s) return
  $q.dialog({
    title: `Suche #${s.id} löschen?`,
    message: `Alle ${s.found} Treffer dieser Suche werden verworfen. Bereits übernommene Boxen bleiben erhalten.`,
    cancel: { label: 'Abbrechen', flat: true, noCaps: true },
    ok: { label: 'Löschen', color: 'negative', noCaps: true, unelevated: true },
  }).onOk(async () => {
    try {
      await api.deleteCandidateSearch(s.id)
      await refreshSearches(false)
    } catch (e) {
      $q.notify({ type: 'negative', message: errorMessage(e) })
    }
  })
}

async function decide(kind: 'accept' | 'reject') {
  if (!selected.size || deciding.value) return
  const ids = [...selected]
  deciding.value = true
  try {
    const r = await api.decideCandidates(kind === 'accept' ? ids : [], kind === 'reject' ? ids : [])
    const parts =
      kind === 'accept'
        ? [r.added && `${r.added} neue Boxen`, r.reclassified && `${r.reclassified} Boxen umklassifiziert`, r.already_present && `${r.already_present} schon vorhanden`]
        : [`${r.rejected} abgelehnt`]
    $q.notify({ type: 'positive', message: parts.filter(Boolean).join(' · ') || 'Nichts geändert', timeout: 1800 })
    selected.clear()
    await Promise.all([refreshSearches(), load()])
  } catch (e) {
    $q.notify({ type: 'negative', message: errorMessage(e) })
  } finally {
    deciding.value = false
  }
}

function onKeydown(e: KeyboardEvent) {
  const t = e.target as HTMLElement | null
  if (t && (t.tagName === 'INPUT' || t.tagName === 'TEXTAREA' || t.isContentEditable)) return
  if (e.ctrlKey || e.metaKey || e.repeat) return
  if (e.key === 'Enter') decide('accept')
  else if (e.key.toLowerCase() === 'n') decide('reject')
}

// results appear while the search runs
let timer: number | undefined
async function poll() {
  const before = current.value?.found ?? 0
  try {
    await refreshSearches()
    if (current.value && current.value.found !== before) await load()
  } catch {
    /* next tick */
  }
  timer = window.setTimeout(poll, busy.value ? 3000 : 10000)
}

watch([() => current.value?.id, status, minScore, sort], () => {
  selected.clear()
  load()
})
watch(
  () => classes.active,
  (list) => {
    if (!form.class && list.length) form.class = list[0].name
  },
  { immediate: true },
)
onMounted(async () => {
  classes.refresh()
  try {
    await refreshSearches(false)
    if (current.value) minScore.value = Math.max(current.value.min_score, 0.2)
  } catch (e) {
    $q.notify({ type: 'negative', message: errorMessage(e) })
  }
  window.addEventListener('keydown', onKeydown)
  timer = window.setTimeout(poll, 3000)
})
onBeforeUnmount(() => {
  window.removeEventListener('keydown', onKeydown)
  window.clearTimeout(timer)
})
</script>

<style scoped>
.example-thumb {
  position: relative;
  height: 44px;
  border-radius: 4px;
  overflow: hidden;
  background: #222;
  outline: 1px solid rgba(128, 128, 128, 0.4);
}
.example-thumb img {
  height: 100%;
  display: block;
}
.example-thumb .remove {
  position: absolute;
  right: 0;
  top: 0;
  color: #fff;
  background: rgba(0, 0, 0, 0.55);
}
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
  cursor: pointer;
  border-radius: 4px;
  background: #222;
  outline: 1px solid rgba(128, 128, 128, 0.3);
  user-select: none;
}
.tile:hover {
  outline: 2px solid var(--q-primary);
}
.tile.selected {
  outline: 3px solid var(--q-positive);
}
.tile.exists img {
  opacity: 0.5;
}
.tile img {
  display: block;
  width: 100%;
  height: 100%;
}
.box {
  position: absolute;
  border: 2px solid;
  pointer-events: none;
  box-sizing: border-box;
}
.score,
.label {
  position: absolute;
  padding: 0 4px;
  font-size: 10px;
  line-height: 14px;
  color: #fff;
  background: rgba(0, 0, 0, 0.6);
  pointer-events: none;
}
.score {
  left: 0;
  top: 0;
  border-bottom-right-radius: 4px;
}
.label {
  left: 0;
  bottom: 0;
  border-top-right-radius: 4px;
}
.label.reclassify {
  background: rgba(245, 124, 0, 0.85);
}
.open {
  position: absolute;
  right: 0;
  top: 0;
  padding: 1px 3px;
  color: #fff;
  background: rgba(0, 0, 0, 0.6);
  border-bottom-left-radius: 4px;
  line-height: 0;
  opacity: 0;
  transition: opacity 0.1s;
}
.tile:hover .open {
  opacity: 1;
}
.check {
  position: absolute;
  right: 2px;
  bottom: 2px;
  line-height: 0;
  background: #fff;
  border-radius: 50%;
}
</style>
