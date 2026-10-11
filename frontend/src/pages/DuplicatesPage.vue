<template>
  <q-page :style-fn="pageStyle" class="column no-wrap">
    <div class="toolbar row items-center q-px-md bg-panel-soft q-gutter-x-sm no-wrap">
      <div class="text-subtitle1 text-weight-medium">Duplikate<HelpIcon term="duplicates" inline /></div>
      <div class="text-caption text-muted ellipsis">
        {{ groups.length }} Gruppen · {{ totalDuplicates }} Duplikate · Schwelle {{ threshold }}
        (<router-link to="/settings" class="text-primary">Einstellungen</router-link>)
      </div>
      <q-space />
      <q-btn outline dense no-caps color="secondary" icon="compare" label="Neu prüfen" :loading="checking" @click="check">
        <q-tooltip>Leere Bilder erneut vergleichen (läuft auch nach jedem Batch-Test). Offene Entscheidungen bleiben erhalten.</q-tooltip>
      </q-btn>
      <q-btn
        unelevated
        dense
        no-caps
        color="primary"
        icon="task_alt"
        :label="`Entscheidungen anwenden (${counts.keep} behalten, ${counts.delete} löschen)`"
        :disable="!counts.keep && !counts.delete"
        :loading="applying"
        @click="apply"
      />
    </div>

    <div v-if="!groups.length && !loading" class="col flex flex-center text-muted text-center q-pa-lg">
      Keine Duplikate. Leere Bilder (ohne Annotationen, ohne Vorschläge im Batch-Test) werden nach jedem Batch-Test verglichen.
    </div>

    <div v-else class="col row no-wrap" style="min-height: 0">
      <!-- groups -->
      <q-scroll-area class="group-col bg-panel">
        <q-list dense>
          <q-item
            v-for="g in groups"
            :key="g.original.id"
            clickable
            :active="g.original.id === selectedId"
            active-class="bg-active"
            @click="selectedId = g.original.id"
          >
            <q-item-section avatar>
              <q-img :src="api.thumbnailUrl(g.original.id)" width="80px" :ratio="16 / 9" class="rounded-borders" loading="lazy" />
            </q-item-section>
            <q-item-section>
              <q-item-label>#{{ g.original.id }}</q-item-label>
              <q-item-label caption>{{ g.duplicates.length }} Duplikate</q-item-label>
              <q-item-label caption>
                <span :class="decidedIn(g) === g.duplicates.length ? 'text-positive' : ''">{{ decidedIn(g) }} / {{ g.duplicates.length }} entschieden</span>
              </q-item-label>
            </q-item-section>
          </q-item>
        </q-list>
      </q-scroll-area>

      <!-- original -->
      <div v-if="group" class="col column no-wrap q-pa-md" style="min-width: 0">
        <div class="row items-center q-mb-sm q-gutter-x-sm">
          <div class="text-subtitle2">Original #{{ group.original.id }}</div>
          <q-badge outline :color="group.original.annotation_status === 'labeled' ? 'positive' : 'grey-5'"
                   :label="group.original.annotation_status === 'labeled' ? 'annotiert (negativ)' : 'offen'" />
          <span class="text-caption text-muted ellipsis">{{ group.original.original_filename }}</span>
          <q-space />
          <q-btn flat dense no-caps size="sm" icon="edit" label="Annotieren" :to="{ name: 'annotate', params: { id: group.original.id } }" />
        </div>
        <div class="col original-box rounded-borders">
          <img :src="api.imageUrl(group.original.id)" class="fit-img" alt="" />
        </div>
        <div class="text-caption text-muted q-mt-sm">
          Das Original bleibt immer erhalten. Rechts die Bilder, die ihm fast gleichen – anklicken zum Vergleichen und Durchschalten.
        </div>
      </div>

      <!-- duplicates -->
      <div v-if="group" class="dup-col bg-panel column no-wrap">
        <div class="q-pa-sm row items-center q-gutter-x-xs no-wrap">
          <div class="text-subtitle2 col">Duplikate ({{ group.duplicates.length }})</div>
          <q-btn dense flat no-caps size="sm" color="positive" label="Offene behalten" @click="decideOpen('keep')" />
          <q-btn dense flat no-caps size="sm" color="negative" label="Offene löschen" @click="decideOpen('delete')" />
        </div>
        <q-scroll-area class="col">
          <div class="q-px-sm q-pb-sm">
            <div
              v-for="(d, i) in group.duplicates"
              :key="d.id"
              class="dup-card rounded-borders cursor-pointer"
              :class="decisions[d.id] ? `dup-card--${decisions[d.id]}` : ''"
              @click="openLightbox(i)"
            >
              <q-img :src="api.thumbnailUrl(d.id)" :ratio="16 / 9" loading="lazy">
                <div v-if="decisions[d.id]" class="absolute-top-right q-ma-xs decision-chip" :class="`bg-${decisionColor[decisions[d.id]!]}`">
                  {{ decisionLabel[decisions[d.id]!] }}
                </div>
              </q-img>
              <div class="row items-center q-px-sm q-py-xs no-wrap">
                <div class="col text-caption">
                  #{{ d.id }} · Abweichung {{ fmtScore(d.duplicate_score) }}
                </div>
                <q-btn dense flat round size="sm" icon="check" color="positive" @click.stop="decide(d.id, 'keep')"><q-tooltip>Behalten (B)</q-tooltip></q-btn>
                <q-btn dense flat round size="sm" icon="delete" color="negative" @click.stop="decide(d.id, 'delete')"><q-tooltip>Löschen (L)</q-tooltip></q-btn>
              </div>
            </div>
          </div>
        </q-scroll-area>
      </div>
    </div>

    <!-- lightbox -->
    <q-dialog v-model="lightbox" maximized transition-show="fade" transition-hide="fade">
      <div v-if="group && current" class="lightbox column no-wrap" @keydown="onKey" tabindex="0" ref="lightboxEl">
        <div class="row items-center q-px-md q-py-sm q-gutter-x-sm no-wrap text-white">
          <div class="text-subtitle1">Duplikat {{ index + 1 }} / {{ group.duplicates.length }} · #{{ current.id }}</div>
          <div class="text-caption text-grey-5">Original #{{ group.original.id }} · Abweichung {{ fmtScore(current.duplicate_score) }}</div>
          <q-chip v-if="decisions[current.id]" dense :color="decisionColor[decisions[current.id]!]" text-color="white" :label="decisionLabel[decisions[current.id]!]" />
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
              { label: 'Nebeneinander', value: 'side' },
              { label: 'Überblenden', value: 'blink' },
            ]"
          />
          <q-btn flat round dense icon="close" color="white" v-close-popup />
        </div>

        <div class="col row no-wrap q-px-md q-gutter-x-md" style="min-height: 0">
          <div v-if="mode === 'side'" class="col column no-wrap">
            <div class="text-caption text-grey-5 q-mb-xs">Original #{{ group.original.id }}</div>
            <div class="col img-box"><img :src="api.imageUrl(group.original.id)" class="fit-img" alt="" /></div>
          </div>
          <div class="col column no-wrap">
            <div class="text-caption text-grey-5 q-mb-xs">
              <template v-if="mode === 'side'">Duplikat #{{ current.id }}</template>
              <template v-else>{{ showOriginal ? `Original #${group.original.id}` : `Duplikat #${current.id}` }} – Leertaste halten oder Maus drücken: Original zeigen</template>
            </div>
            <div
              class="col img-box"
              @mousedown="mode === 'blink' && (showOriginal = true)"
              @mouseup="showOriginal = false"
              @mouseleave="showOriginal = false"
            >
              <img :src="api.imageUrl(current.id)" class="fit-img" alt="" />
              <img v-if="mode === 'blink'" v-show="showOriginal" :src="api.imageUrl(group.original.id)" class="fit-img overlay-img" alt="" />
            </div>
          </div>
        </div>

        <div class="row items-center justify-center q-pa-md q-gutter-md text-white">
          <q-btn flat round icon="chevron_left" color="white" :disable="index === 0" @click="step(-1)" />
          <q-btn unelevated no-caps color="positive" icon="check" label="Behalten (B)" @click="decide(current.id, 'keep', true)" />
          <q-btn unelevated no-caps color="negative" icon="delete" label="Löschen (L)" @click="decide(current.id, 'delete', true)" />
          <q-btn outline no-caps color="grey-5" label="Offen (O)" @click="decide(current.id, null)" />
          <q-btn flat round icon="chevron_right" color="white" :disable="index >= group.duplicates.length - 1" @click="step(1)" />
          <div class="text-caption text-grey-5">← → blättern · B behalten · L/Entf löschen · O offen · Leertaste Original</div>
        </div>
        <!-- preload the next image -->
        <img v-if="group.duplicates[index + 1]" :src="api.imageUrl(group.duplicates[index + 1].id)" style="display: none" alt="" />
      </div>
    </q-dialog>
  </q-page>
</template>

<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { useQuasar } from 'quasar'
import HelpIcon from '@/components/HelpIcon.vue'
import { api, errorMessage, type DuplicateGroup } from '@/services/api'
import { useModelsStore } from '@/stores/models'

type Decision = 'keep' | 'delete'
const STORAGE_KEY = 'duplicate-decisions'

const $q = useQuasar()
const models = useModelsStore()
const groups = ref<DuplicateGroup[]>([])
const selectedId = ref<number | null>(null)
const loading = ref(false)
const checking = ref(false)
const applying = ref(false)
// decisions are collected here and applied together; kept in the browser in case the page is left
const decisions = reactive<Record<number, Decision>>(loadDecisions())
const decisionLabel: Record<Decision, string> = { keep: 'Behalten', delete: 'Löschen' }
const decisionColor: Record<Decision, string> = { keep: 'positive', delete: 'negative' }

const lightbox = ref(false)
const lightboxEl = ref<HTMLDivElement | null>(null)
const index = ref(0)
const mode = ref<'side' | 'blink'>('side')
const showOriginal = ref(false)

const group = computed(() => groups.value.find((g) => g.original.id === selectedId.value) ?? null)
const current = computed(() => group.value?.duplicates[index.value] ?? null)
const totalDuplicates = computed(() => groups.value.reduce((n, g) => n + g.duplicates.length, 0))
const threshold = computed(() => String(models.settings?.duplicate_max_difference ?? '–').replace('.', ','))
const counts = computed(() => {
  const ids = new Set(groups.value.flatMap((g) => g.duplicates.map((d) => d.id)))
  const c = { keep: 0, delete: 0 }
  for (const [id, d] of Object.entries(decisions)) if (ids.has(Number(id))) c[d]++
  return c
})

function pageStyle(offset: number) {
  return { height: offset ? `calc(100vh - ${offset}px)` : '100vh' }
}

function loadDecisions(): Record<number, Decision> {
  try {
    return JSON.parse(localStorage.getItem(STORAGE_KEY) ?? '{}')
  } catch {
    return {}
  }
}
watch(decisions, () => {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(decisions))
  } catch {
    /* storage unavailable: decisions live until the page is closed */
  }
})

const fmtScore = (s: number | null) => (s == null ? '–' : s.toFixed(3).replace('.', ','))
const decidedIn = (g: DuplicateGroup) => g.duplicates.filter((d) => decisions[d.id]).length

async function load() {
  loading.value = true
  try {
    groups.value = await api.duplicateGroups()
    if (!groups.value.some((g) => g.original.id === selectedId.value)) selectedId.value = groups.value[0]?.original.id ?? null
  } catch (e) {
    $q.notify({ type: 'negative', message: errorMessage(e) })
  } finally {
    loading.value = false
  }
}

function decide(id: number, d: Decision | null, advance = false) {
  if (d) decisions[id] = d
  else delete decisions[id]
  const g = group.value
  if (!advance || !g) return
  if (decidedIn(g) === g.duplicates.length) {
    // whole group decided: back to the overview, next group with open duplicates selected (lightbox started manually)
    lightbox.value = false
    const i = groups.value.indexOf(g)
    const n = groups.value.length
    const next = Array.from({ length: n - 1 }, (_, k) => groups.value[(i + 1 + k) % n]).find((x) => decidedIn(x) < x.duplicates.length)
    if (next) selectedId.value = next.original.id
    $q.notify({
      type: 'positive',
      message: `Alle ${g.duplicates.length} Duplikate von #${g.original.id} entschieden`,
      caption: next ? `weiter mit #${next.original.id}` : 'alle Gruppen entschieden – jetzt „Entscheidungen anwenden“',
      timeout: 2000,
    })
  } else {
    // next undecided image after the current one (wrapping around)
    const n = g.duplicates.length
    const next = Array.from({ length: n - 1 }, (_, k) => (index.value + 1 + k) % n).find((i) => !decisions[g.duplicates[i].id])
    if (next !== undefined) index.value = next
  }
}

function decideOpen(d: Decision) {
  group.value?.duplicates.forEach((x) => {
    if (!decisions[x.id]) decisions[x.id] = d
  })
}

function openLightbox(i: number) {
  index.value = i
  showOriginal.value = false
  lightbox.value = true
  nextTick(() => lightboxEl.value?.focus())
}

function step(delta: number) {
  if (!group.value) return
  index.value = Math.max(0, Math.min(group.value.duplicates.length - 1, index.value + delta))
}

function onKey(e: KeyboardEvent) {
  if (!current.value) return
  const k = e.key.toLowerCase()
  if (e.key === 'ArrowRight') step(1)
  else if (e.key === 'ArrowLeft') step(-1)
  else if (k === 'b') decide(current.value.id, 'keep', true)
  else if (k === 'l' || e.key === 'Delete') decide(current.value.id, 'delete', true)
  else if (k === 'o') decide(current.value.id, null)
  else if (e.key === ' ') {
    if (mode.value === 'blink') showOriginal.value = true
  } else return
  e.preventDefault()
}
function onKeyUp(e: KeyboardEvent) {
  if (e.key === ' ') showOriginal.value = false
}
window.addEventListener('keyup', onKeyUp)
onBeforeUnmount(() => window.removeEventListener('keyup', onKeyUp))

async function check() {
  checking.value = true
  try {
    const r = await api.checkDuplicates()
    $q.notify({ type: 'positive', message: `${r.duplicates} Duplikate unter ${r.checked} leeren Bildern` })
    await load()
  } catch (e) {
    $q.notify({ type: 'negative', message: errorMessage(e) })
  } finally {
    checking.value = false
  }
}

function apply() {
  const ids = new Set(groups.value.flatMap((g) => g.duplicates.map((d) => d.id)))
  const keep = Object.keys(decisions).map(Number).filter((id) => ids.has(id) && decisions[id] === 'keep')
  const del = Object.keys(decisions).map(Number).filter((id) => ids.has(id) && decisions[id] === 'delete')
  const run = async () => {
    applying.value = true
    try {
      const r = await api.resolveDuplicates({ keep, delete: del })
      for (const id of [...keep, ...del]) delete decisions[id]
      $q.notify({ type: 'positive', message: `${r.kept} behalten, ${r.deleted} gelöscht` })
      await load()
    } catch (e) {
      $q.notify({ type: 'negative', message: errorMessage(e) })
    } finally {
      applying.value = false
    }
  }
  if (!del.length) return run()
  $q.dialog({
    title: 'Entscheidungen anwenden',
    message: `${del.length} Bilder löschen und ${keep.length} behalten? Behaltene Bilder werden nie wieder als Duplikat markiert. ` +
      'Bilder, die in Trainings verwendet wurden, werden nur ausgeblendet.',
    cancel: { label: 'Abbrechen', flat: true },
    ok: { label: 'Anwenden', color: 'negative' },
    persistent: true,
  }).onOk(run)
}

onMounted(() => {
  models.refresh()
  load()
})
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
.dup-col {
  width: 360px;
  min-width: 300px;
  border-left: 1px solid var(--app-border);
}
.original-box {
  min-height: 0;
  background: #000;
  overflow: hidden;
}
.fit-img {
  width: 100%;
  height: 100%;
  object-fit: contain;
  display: block;
}
.dup-card {
  border: 2px solid var(--app-border);
  overflow: hidden;
  margin-bottom: 8px;
}
.dup-card--keep {
  border-color: var(--q-positive);
}
.dup-card--delete {
  border-color: var(--q-negative);
  opacity: 0.6;
}
.decision-chip {
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
.overlay-img {
  position: absolute;
  inset: 0;
}
</style>
