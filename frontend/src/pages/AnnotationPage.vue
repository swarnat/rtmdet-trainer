<template>
  <q-page :style-fn="pageStyle" class="row no-wrap">
    <!-- left: image browser -->
    <div class="browser-col bg-white">
      <ImageBrowser
        ref="browser"
        :selected-id="imageId"
        @select="openImage"
        @filter-change="(s) => (statusFilter = s)"
        @batch-finished="reloadCurrentSuggestions"
      />
    </div>

    <!-- center: canvas -->
    <div class="col column no-wrap">
      <!-- fixed height: a wrapping toolbar would resize/refit the canvas while editing -->
      <div class="toolbar row items-center q-px-sm bg-grey-2 q-gutter-x-sm no-wrap">
        <q-btn dense flat icon="chevron_left" :disable="!neighbours.previous" @click="go(neighbours.previous)">
          <q-tooltip>Vorheriges Bild (Bild ↑)</q-tooltip>
        </q-btn>
        <q-btn dense flat icon="chevron_right" :disable="!neighbours.next" @click="go(neighbours.next)">
          <q-tooltip>Nächstes Bild (Bild ↓)</q-tooltip>
        </q-btn>
        <div v-if="store.image" class="col text-body2 ellipsis" style="min-width: 0">
          <b>#{{ store.image.id }}</b> {{ store.image.original_filename }} · {{ store.image.width }}×{{ store.image.height }}
          <q-badge :color="store.image.annotation_status === 'labeled' ? 'green-7' : 'grey-6'" class="q-ml-sm">
            {{ store.image.annotation_status === 'labeled' ? (store.image.annotation_count ? 'annotiert' : 'negativ') : 'offen' }}
          </q-badge>
          <q-badge v-if="store.image.dataset_split" outline color="blue-grey" class="q-ml-xs">{{ store.image.dataset_split }}</q-badge>
          <q-badge v-if="store.image.needs_review" color="amber-9" class="q-ml-xs">nachprüfen</q-badge>
          <q-badge v-if="store.dirty" color="orange-8" class="q-ml-xs">ungespeichert</q-badge>
        </div>
        <q-space v-if="!store.image" />
        <!-- few classes: buttons, many classes: dropdown (shortcuts 1-9 work in both cases) -->
        <q-btn-group v-if="classes.active.length <= 5" flat class="no-wrap">
          <q-btn
            v-for="c in classes.active"
            :key="c.name"
            dense
            no-caps
            no-wrap
            :outline="store.activeClass !== c.name"
            :unelevated="store.activeClass === c.name"
            :style="store.activeClass === c.name ? { background: c.color, color: 'white' } : { color: c.color }"
            :label="`${classes.shortcuts[c.name] ?? ''} ${c.label}`"
            @click="store.setClassForSelected(c.name)"
          />
        </q-btn-group>
        <q-select
          v-else
          :model-value="store.activeClass"
          :options="classOptions"
          emit-value
          map-options
          dense
          outlined
          options-dense
          label="Klasse"
          style="min-width: 190px"
          @update:model-value="(v) => store.setClassForSelected(v)"
        >
          <template #selected-item="scope">
            <span class="class-dot" :style="{ background: scope.opt.color }" />{{ scope.opt.label }}
          </template>
          <template #option="scope">
            <q-item v-bind="scope.itemProps">
              <q-item-section avatar style="min-width: 20px"><span class="class-dot" :style="{ background: scope.opt.color }" /></q-item-section>
              <q-item-section>{{ scope.opt.label }}</q-item-section>
              <q-item-section side>{{ scope.opt.key }}</q-item-section>
            </q-item>
          </template>
        </q-select>
        <q-btn dense flat icon="undo" :disable="!store.history.length" @click="store.undo()"><q-tooltip>Rückgängig (Strg+Z)</q-tooltip></q-btn>
        <q-btn dense flat icon="delete" :disable="!store.selectedId" @click="store.deleteSelected()"><q-tooltip>Box löschen (Entf)</q-tooltip></q-btn>
        <q-btn dense unelevated color="primary" icon="save" label="Speichern" no-caps no-wrap :loading="store.saving" :disable="!store.image" @click="save(false)">
          <q-tooltip>Speichern und als annotiert markieren (Strg+S)</q-tooltip>
        </q-btn>
        <q-btn dense unelevated color="primary" icon-right="skip_next" label="& weiter" no-caps no-wrap :loading="store.saving" :disable="!store.image" @click="save(true)" />
      </div>
      <div class="col relative-position">
        <AnnotationCanvas
          v-if="store.image"
          ref="canvas"
          :image-url="api.imageUrl(store.image.id)"
          :image-width="store.image.width"
          :image-height="store.image.height"
          :boxes="store.boxes"
          :predictions="store.predictions"
          :selected-id="store.selectedId"
          :active-class="store.activeClass"
          :show-predictions="showPredictions"
          @select="(id) => (store.selectedId = id)"
          @change="(id, c) => store.updateBox(id, c)"
          @create="(c) => store.addBox({ ...c, class: store.activeClass, type: 'positive', source: 'manual' })"
          @accept="(id) => store.acceptPrediction(id)"
        />
        <div v-else class="absolute-center text-grey-6 text-h6">Bild links auswählen oder hochladen</div>
      </div>
    </div>

    <!-- right: boxes, test function -->
    <div class="side-col bg-white column no-wrap">
      <q-scroll-area class="col">
        <div class="q-pa-sm">
          <q-banner v-if="store.image?.needs_review" dense rounded class="bg-amber-2 text-body2 q-mb-sm">
            <template #avatar><q-icon name="fact_check" color="amber-9" /></template>
            Noch nicht geprüft auf: <b>{{ missingClasses.map((c) => classes.info(c).label).join(', ') }}</b>.
            Bild auf diese Klassen prüfen und speichern – erst dann wird es für Trainings mit diesen Klassen verwendet.
          </q-banner>
          <div class="text-subtitle2 q-mb-xs">Annotationen ({{ positives.length }})</div>
          <div v-if="store.image && !positives.length" class="text-caption text-grey-7 q-mb-sm">
            Keine Objekte. Speichern markiert das Bild als <b>negatives Trainingsbild</b>.
          </div>
          <q-list v-if="positives.length" dense bordered separator class="rounded-borders">
            <q-item
              v-for="(b, i) in positives"
              :key="b.uid"
              clickable
              :active="b.uid === store.selectedId"
              active-class="bg-blue-1"
              @click="store.selectedId = b.uid"
            >
              <q-item-section avatar style="min-width: 24px">
                <span class="class-dot" :style="{ background: classes.info(b.class).color }" />
              </q-item-section>
              <q-item-section>
                <q-item-label>{{ i + 1 }}. {{ classes.info(b.class).label }}<span v-if="b.source === 'prediction'" class="text-grey-6"> (übernommen)</span></q-item-label>
                <q-item-label caption class="mono">
                  {{ Math.round(b.x1) }},{{ Math.round(b.y1) }} – {{ Math.round(b.x2) }},{{ Math.round(b.y2) }}
                </q-item-label>
              </q-item-section>
              <q-item-section side>
                <q-btn dense flat round size="sm" icon="close" @click.stop="removeBox(b.uid)" />
              </q-item-section>
            </q-item>
          </q-list>

          <template v-if="hardNegatives.length">
            <div class="text-subtitle2 q-mt-md q-mb-xs">
              Hard Negatives ({{ hardNegatives.length }})
              <q-icon name="help_outline" size="xs" color="grey-7">
                <q-tooltip max-width="320px">
                  Bekannte Fehlalarme: Regionen, die ein Modell fälschlich als diese Klasse erkannt hat. Sie werden nicht als eigene Klasse
                  trainiert, sondern als Hintergrund-Ausschnitte (oversampled) und nach jedem Training als Regressionstest geprüft.
                </q-tooltip>
              </q-icon>
            </div>
            <q-list dense bordered separator class="rounded-borders">
              <q-item
                v-for="b in hardNegatives"
                :key="b.uid"
                clickable
                :active="b.uid === store.selectedId"
                active-class="bg-grey-4"
                @click="store.selectedId = b.uid"
              >
                <q-item-section avatar style="min-width: 24px">
                  <q-icon name="block" size="xs" :style="{ color: classes.info(b.class).color }" />
                </q-item-section>
                <q-item-section>
                  <q-item-label>kein(e) {{ classes.info(b.class).label }}</q-item-label>
                  <q-item-label caption>
                    {{ b.source_model ?? 'manuell' }}<span v-if="b.source_confidence != null"> · {{ (b.source_confidence * 100).toFixed(0) }} %</span>
                  </q-item-label>
                </q-item-section>
                <q-item-section side>
                  <q-btn dense flat round size="sm" icon="close" @click.stop="removeBox(b.uid)" />
                </q-item-section>
              </q-item>
            </q-list>
          </template>

          <q-separator class="q-my-md" />

          <div class="text-subtitle2 q-mb-sm">Modell testen</div>
          <div class="column q-gutter-sm">
            <ModelSelector v-model="test.model" />
            <q-select v-model="test.inputSize" :options="models.inputSizes" dense outlined label="Eingangsauflösung" />
            <div>
              <div class="text-caption">Confidence-Threshold: {{ test.confidence.toFixed(2) }}</div>
              <q-slider v-model="test.confidence" :min="0.05" :max="0.95" :step="0.05" dense />
            </div>
            <q-btn color="deep-purple" icon="science" label="Modell testen" no-caps :loading="testing" :disable="!store.image" @click="runTest" />
          </div>

          <template v-if="store.lastDetection">
            <q-banner v-if="store.fromSuggestion" dense rounded class="bg-deep-purple-1 text-body2 q-mt-sm">
              <template #avatar><q-icon name="playlist_add_check" color="deep-purple" /></template>
              Vorschläge aus Batch-Test #{{ store.fromSuggestion.batch_id }} ({{ store.fromSuggestion.model_version }},
              {{ store.fromSuggestion.input_width }}×{{ store.fromSuggestion.input_height }}, ≥ {{ store.fromSuggestion.confidence }}).
              <span v-if="store.fromSuggestion.detections.length > store.predictions.length">
                {{ store.fromSuggestion.detections.length - store.predictions.length }} bereits annotiert/übernommen.
              </span>
              Beim Speichern werden die restlichen Vorschläge verworfen.
            </q-banner>
            <div v-else class="text-caption text-grey-8 q-mt-sm">
              {{ store.lastDetection.model.version }} ({{ store.lastDetection.model.status }}) ·
              {{ store.lastDetection.model.input_width }}×{{ store.lastDetection.model.input_height }} ·
              {{ store.lastDetection.inference_ms.toFixed(0) }} ms · {{ store.lastDetection.detections.length }} Treffer
            </div>
            <div class="row q-gutter-xs q-mt-xs">
              <q-toggle v-model="showPredictions" dense label="anzeigen" />
              <q-space />
              <q-btn dense flat no-caps size="sm" icon="clear" label="verwerfen" @click="store.clearPredictions()" />
            </div>
            <div class="row q-gutter-xs q-mt-xs">
              <q-btn
                dense
                outline
                no-caps
                color="deep-purple"
                icon="check"
                label="Prediction übernehmen"
                class="col"
                :disable="!store.selectedPrediction || !store.acceptable(store.selectedPrediction)"
                @click="store.acceptPrediction(store.selectedId!)"
              >
                <q-tooltip>Ausgewählte Prediction übernehmen (Enter oder Doppelklick)</q-tooltip>
              </q-btn>
              <q-btn
                dense
                unelevated
                no-caps
                color="deep-purple"
                icon="done_all"
                label="Alle übernehmen"
                class="col"
                :disable="!store.predictions.some(store.acceptable)"
                @click="store.acceptAllPredictions()"
              />
            </div>
            <q-btn
              dense
              outline
              no-caps
              color="grey-9"
              icon="block"
              label="Als False Positive / Hard Negative markieren"
              class="full-width q-mt-xs"
              :disable="!store.selectedPrediction || !store.acceptable(store.selectedPrediction)"
              @click="store.markHardNegative(store.selectedId!)"
            >
              <q-tooltip>Ausgewählte Prediction ist ein Fehlalarm (Taste N)</q-tooltip>
            </q-btn>
            <q-list dense bordered separator class="rounded-borders q-mt-sm">
              <q-item
                v-for="p in store.predictions"
                :key="p.uid"
                clickable
                :active="p.uid === store.selectedId"
                active-class="bg-deep-purple-1"
                @click="store.selectedId = p.uid"
                @dblclick="store.acceptPrediction(p.uid)"
              >
                <q-item-section avatar style="min-width: 24px">
                  <span class="class-dot" :style="{ border: `2px dashed ${classes.info(p.class).color}` }" />
                </q-item-section>
                <q-item-section>
                  <q-item-label>{{ classes.info(p.class).label }} · {{ (p.confidence * 100).toFixed(1) }} %</q-item-label>
                  <q-item-label v-if="!store.acceptable(p)" caption class="text-warning">Klasse hier nicht aktiv – nicht übernehmbar</q-item-label>
                </q-item-section>
                <q-item-section side>
                  <div class="row no-wrap">
                    <q-btn dense flat round size="sm" icon="add_task" color="deep-purple" :disable="!store.acceptable(p)" @click.stop="store.acceptPrediction(p.uid)">
                      <q-tooltip>Übernehmen</q-tooltip>
                    </q-btn>
                    <q-btn dense flat round size="sm" icon="block" color="grey-9" :disable="!store.acceptable(p)" @click.stop="store.markHardNegative(p.uid)">
                      <q-tooltip>Als False Positive / Hard Negative markieren</q-tooltip>
                    </q-btn>
                  </div>
                </q-item-section>
              </q-item>
            </q-list>
          </template>

          <q-separator class="q-my-md" />
          <div class="text-subtitle2 q-mb-xs">Bild</div>
          <div class="column q-gutter-xs">
            <q-btn
              v-if="store.image?.annotation_status === 'labeled'"
              dense
              flat
              no-caps
              icon="restart_alt"
              label="Als unbearbeitet markieren"
              @click="markUnlabeled"
            />
            <q-btn dense flat no-caps color="negative" icon="delete_forever" label="Bild löschen" :disable="!store.image" @click="deleteImage" />
          </div>

          <q-expansion-item dense icon="keyboard" label="Tastenkürzel" class="q-mt-md text-caption">
            <div class="q-pa-sm text-caption">
              <div><b>1 … 9</b> Klasse wählen (Reihenfolge unter „Klassen“; gilt auch für die ausgewählte Box)</div>
              <div><b>Entf</b> Box löschen · <b>Esc</b> Auswahl aufheben</div>
              <div><b>Strg+S</b> speichern · <b>Strg+Z</b> rückgängig</div>
              <div><b>Enter</b> Prediction übernehmen · <b>Umschalt+A</b> alle übernehmen</div>
              <div><b>N</b> ausgewählte Prediction als False Positive / Hard Negative markieren</div>
              <div><b>T</b> Modell testen · <b>H</b> Predictions ein/aus</div>
              <div><b>Bild ↑ / Bild ↓</b> vorheriges / nächstes Bild</div>
              <div>Mausrad: Zoom · Leertaste/Mitteltaste/Rechtsklick + Ziehen: verschieben</div>
            </div>
          </q-expansion-item>
        </div>
      </q-scroll-area>
    </div>
  </q-page>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { onBeforeRouteLeave, useRoute, useRouter } from 'vue-router'
import { useQuasar } from 'quasar'
import AnnotationCanvas from '@/components/AnnotationCanvas.vue'
import ImageBrowser from '@/components/ImageBrowser.vue'
import ModelSelector from '@/components/ModelSelector.vue'
import { api, errorMessage } from '@/services/api'
import { useClassesStore } from '@/stores/classes'
import { useAnnotationStore } from '@/stores/annotation'
import { useModelsStore } from '@/stores/models'

const $q = useQuasar()
const route = useRoute()
const router = useRouter()
const store = useAnnotationStore()
const models = useModelsStore()
const classes = useClassesStore()

const classOptions = computed(() =>
  classes.active.map((c) => ({ value: c.name, label: c.label, color: c.color, key: classes.shortcuts[c.name] ?? '' })),
)
const positives = computed(() => store.boxes.filter((b) => b.type !== 'hard_negative'))
const hardNegatives = computed(() => store.boxes.filter((b) => b.type === 'hard_negative'))
const missingClasses = computed(() => {
  const reviewed = new Set(store.image?.reviewed_classes ?? [])
  return classes.active.map((c) => c.name).filter((n) => !reviewed.has(n))
})

// default drawing class: first active class
watch(
  () => classes.active,
  (list) => {
    if (list.length && !list.some((c) => c.name === store.activeClass)) store.activeClass = list[0].name
  },
  { immediate: true },
)

const browser = ref<InstanceType<typeof ImageBrowser> | null>(null)
const imageId = ref<number | null>(null)
const statusFilter = ref<string | undefined>(undefined)
const neighbours = reactive<{ previous: number | null; next: number | null }>({ previous: null, next: null })
const showPredictions = ref(true)
const testing = ref(false)
const test = reactive({ model: 'production', inputSize: '1536x864', confidence: 0.25 })

function pageStyle(offset: number) {
  return { height: offset ? `calc(100vh - ${offset}px)` : '100vh' }
}

watch(
  () => models.settings,
  (s) => {
    if (s) {
      test.inputSize = s.default_input_size
      test.confidence = s.default_confidence
    }
  },
  { immediate: true },
)

async function load(id: number) {
  try {
    const detail = await api.getImage(id)
    store.load(detail)
    imageId.value = id
    await loadNeighbours()
  } catch (e) {
    $q.notify({ type: 'negative', message: errorMessage(e) })
  }
}

async function loadNeighbours() {
  if (!imageId.value) return
  const n = await api.neighbours(imageId.value, statusFilter.value)
  neighbours.previous = n.previous
  neighbours.next = n.next
}
watch(statusFilter, loadNeighbours)

function confirmDiscard(): Promise<boolean> {
  if (!store.dirty) return Promise.resolve(true)
  return new Promise((resolve) => {
    $q.dialog({
      title: 'Ungespeicherte Änderungen',
      message: 'Die Änderungen an diesem Bild wurden nicht gespeichert. Verwerfen?',
      cancel: { label: 'Abbrechen', flat: true },
      ok: { label: 'Verwerfen', color: 'negative' },
      persistent: true,
    })
      .onOk(() => resolve(true))
      .onCancel(() => resolve(false))
  })
}

async function openImage(id: number) {
  if (id === imageId.value) return
  if (!(await confirmDiscard())) return
  store.dirty = false
  router.push({ name: 'annotate', params: { id } })
}

function go(id: number | null) {
  if (id) openImage(id)
}

watch(
  () => route.params.id,
  (id) => {
    const n = Number(id)
    if (n && n !== imageId.value) load(n)
  },
  { immediate: true },
)

onBeforeRouteLeave(async () => confirmDiscard())

async function save(next: boolean) {
  if (!store.image) return
  try {
    await store.save(true)
    const img = store.image
    browser.value?.patch(img)
    $q.notify({
      type: 'positive',
      message: positives.value.length
        ? `${positives.value.length} Boxen gespeichert`
        : 'Als negatives Trainingsbild gespeichert',
      caption: hardNegatives.value.length ? `${hardNegatives.value.length} Hard Negatives` : undefined,
      timeout: 1500,
    })
    await loadNeighbours()
    if (next && neighbours.next) openImage(neighbours.next)
  } catch (e) {
    $q.notify({ type: 'negative', message: errorMessage(e) })
  }
}

/** After a batch test finished: show new suggestions for the open image (if it has no unsaved edits). */
async function reloadCurrentSuggestions() {
  if (!imageId.value || store.dirty) return
  try {
    store.load(await api.getImage(imageId.value))
  } catch {
    /* image may have been deleted */
  }
}

function removeBox(uid: string) {
  store.selectedId = uid
  store.deleteSelected()
}

async function runTest() {
  if (!store.image) return
  testing.value = true
  try {
    const res = await api.detectStored(store.image.id, { model: test.model, input_size: test.inputSize, confidence: test.confidence })
    store.setDetection(res)
    showPredictions.value = true
  } catch (e) {
    $q.notify({ type: 'negative', message: errorMessage(e) })
  } finally {
    testing.value = false
  }
}

async function markUnlabeled() {
  if (!store.image) return
  const detail = await api.updateImage(store.image.id, { annotation_status: 'unlabeled' })
  store.load(detail)
  browser.value?.patch(detail)
}

function deleteImage() {
  const img = store.image
  if (!img) return
  $q.dialog({
    title: 'Bild löschen',
    message: `Bild #${img.id} inklusive Annotationen endgültig löschen? (Bestehende Dataset-Snapshots bleiben erhalten.)`,
    cancel: { label: 'Abbrechen', flat: true },
    ok: { label: 'Löschen', color: 'negative' },
  }).onOk(async () => {
    try {
      const next = neighbours.next ?? neighbours.previous
      await api.deleteImage(img.id)
      store.dirty = false
      store.image = null
      imageId.value = null
      await browser.value?.reload()
      if (next) router.push({ name: 'annotate', params: { id: next } })
      else router.push({ name: 'annotate' })
    } catch (e) {
      $q.notify({ type: 'negative', message: errorMessage(e) })
    }
  })
}

function onKeydown(e: KeyboardEvent) {
  const t = e.target as HTMLElement | null
  if (t && (t.tagName === 'INPUT' || t.tagName === 'TEXTAREA' || t.isContentEditable)) return
  const ctrl = e.ctrlKey || e.metaKey
  if (ctrl && e.key.toLowerCase() === 's') {
    e.preventDefault()
    save(false)
  } else if (ctrl && e.key.toLowerCase() === 'z') {
    e.preventDefault()
    store.undo()
  } else if (ctrl) {
    return
  } else if (/^[1-9]$/.test(e.key) && classes.byShortcut(e.key)) {
    store.setClassForSelected(classes.byShortcut(e.key)!.name)
  } else if (e.key === 'Delete' || e.key === 'Backspace') {
    e.preventDefault()
    store.deleteSelected()
  } else if (e.key === 'Escape') {
    store.selectedId = null
  } else if (e.key.toLowerCase() === 'n' && store.selectedPrediction) {
    store.markHardNegative(store.selectedPrediction.uid)
  } else if (e.key === 'Enter' && store.selectedPrediction) {
    store.acceptPrediction(store.selectedPrediction.uid)
  } else if (e.key === 'A' && e.shiftKey) {
    store.acceptAllPredictions()
  } else if (e.key.toLowerCase() === 't') {
    runTest()
  } else if (e.key.toLowerCase() === 'h') {
    showPredictions.value = !showPredictions.value
  } else if (e.key === 'PageDown') {
    e.preventDefault()
    go(neighbours.next)
  } else if (e.key === 'PageUp') {
    e.preventDefault()
    go(neighbours.previous)
  }
}

function onBeforeUnload(e: BeforeUnloadEvent) {
  if (store.dirty) {
    e.preventDefault()
    e.returnValue = ''
  }
}

onMounted(() => {
  window.addEventListener('keydown', onKeydown)
  window.addEventListener('beforeunload', onBeforeUnload)
  if (!models.settings) models.refresh()
  classes.refresh()
})
onBeforeUnmount(() => {
  window.removeEventListener('keydown', onKeydown)
  window.removeEventListener('beforeunload', onBeforeUnload)
})
</script>

<style scoped>
.toolbar {
  height: 44px;
  min-height: 44px;
  overflow: hidden;
}
.browser-col {
  width: 320px;
  min-width: 260px;
  border-right: 1px solid #ddd;
}
.side-col {
  width: 330px;
  min-width: 280px;
  border-left: 1px solid #ddd;
}
</style>
