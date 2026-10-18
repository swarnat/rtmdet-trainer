<template>
  <q-page :style-fn="pageStyle" class="column no-wrap">
    <!-- header: configuration, counts, batch actions -->
    <div class="header row items-center q-px-md q-gutter-x-sm no-wrap bg-panel">
      <div class="text-subtitle1 text-weight-bold no-wrap">Kunden-Annotation</div>
      <div class="col text-caption text-muted ellipsis" style="min-width: 0">
        <template v-if="config">
          {{ config.classes.length }} Klassen · Inference: {{ config.inference_url || 'nicht konfiguriert' }} · Confidence ≥ {{ config.confidence }}
          · übertragen {{ fmtDate(config.pushed_at) }}
        </template>
        <span v-else class="text-warning">Noch nicht konfiguriert – im Trainingssystem „Konfiguration übertragen“.</span>
      </div>
      <div class="text-body2 no-wrap">
        <b>{{ counts.open }}</b> offen · <b>{{ counts.annotated }}</b> annotiert
      </div>
      <div v-if="download" class="progress-box cursor-pointer" @click="downloadDialog = true">
        <div class="text-caption text-primary">Download {{ download.done }} / {{ download.total }}</div>
        <q-linear-progress :value="download.total ? download.done / download.total : 0" color="primary" rounded />
      </div>
      <div v-if="checkRun" class="progress-box">
        <div class="text-caption text-secondary">Prüfung {{ checkRun.done }} / {{ checkRun.total }}<span v-if="checkRun.failed"> · {{ checkRun.failed }} Fehler</span></div>
        <q-linear-progress :value="checkRun.total ? checkRun.done / checkRun.total : 0" color="secondary" rounded />
      </div>
      <q-btn dense outline no-caps color="primary" icon="upload" label="Hochladen" @click="fileInput?.click()" />
      <input ref="fileInput" type="file" accept="image/jpeg,image/png,image/webp,image/bmp" multiple class="hidden" @change="onFiles" />
      <q-btn dense outline no-caps color="primary" icon="cloud_download" label="Batch-Download" @click="downloadDialog = true" />
      <q-btn v-if="checkRun" dense outline no-caps color="negative" icon="stop" label="Prüfung stoppen" @click="checkAbort?.abort()" />
      <q-btn v-else dense outline no-caps color="secondary" icon="science" label="Offene prüfen" :disable="!config?.inference_url || !uncheckedOpen.length" @click="checkOpen">
        <q-tooltip>Alle offenen, noch nicht geprüften Bilder ({{ uncheckedOpen.length }}) gegen den Inference-Server prüfen</q-tooltip>
      </q-btn>
      <q-btn dense flat round icon="logout" @click="emit('logout')"><q-tooltip>Abmelden</q-tooltip></q-btn>
      <UrlDownloadDialog v-model="downloadDialog" :download="clientApi.downloadImage" @progress="(p) => (download = p)" @finished="refresh" />
    </div>

    <div class="col row no-wrap" style="min-height: 0">
      <!-- left: image list -->
      <div class="browser-col bg-panel column no-wrap">
        <div class="q-pa-sm">
          <q-btn-toggle
            v-model="filter"
            spread
            dense
            no-caps
            toggle-color="primary"
            :options="[
              { label: `Alle (${counts.total})`, value: 'all' },
              { label: `Offen (${counts.open})`, value: 'open' },
              { label: `Annotiert (${counts.annotated})`, value: 'annotated' },
            ]"
          />
        </div>
        <q-scroll-area class="col">
          <q-list dense separator>
            <q-item v-for="img in visible" :key="img.id" clickable :active="img.id === store.image?.id" active-class="bg-active" @click="open(img.id)">
              <q-item-section avatar>
                <img :src="clientApi.thumbnailUrl(img.id)" class="thumb" alt="" loading="lazy" />
              </q-item-section>
              <q-item-section>
                <q-item-label class="ellipsis" :title="img.filename ?? undefined">#{{ img.id }} {{ fmtMiddle(img.filename, 18) }}</q-item-label>
                <q-item-label caption>
                  <q-badge outline :color="img.status === 'annotated' ? 'positive' : 'grey-5'">
                    {{ img.status === 'annotated' ? (img.annotations.length ? `${img.annotations.length} Boxen` : 'negativ') : 'offen' }}
                  </q-badge>
                  <q-badge v-if="img.status === 'open' && img.detection" outline color="secondary" class="q-ml-xs">
                    {{ img.detection.detections.length }} Vorschläge
                  </q-badge>
                </q-item-label>
              </q-item-section>
            </q-item>
          </q-list>
          <div v-if="!visible.length" class="q-pa-md text-caption text-muted">Keine Bilder – hochladen oder per Batch-Download laden.</div>
        </q-scroll-area>
      </div>

      <!-- center: canvas -->
      <div class="col column no-wrap">
        <div class="toolbar row items-center q-px-md bg-panel-soft q-gutter-x-sm no-wrap">
          <q-btn dense flat icon="chevron_left" :disable="!neighbour(-1)" @click="go(-1)"><q-tooltip>Vorheriges Bild (Bild ↑)</q-tooltip></q-btn>
          <q-btn dense flat icon="chevron_right" :disable="!neighbour(1)" @click="go(1)"><q-tooltip>Nächstes Bild (Bild ↓)</q-tooltip></q-btn>
          <div v-if="store.image" class="col text-body2 ellipsis" style="min-width: 0">
            <b>#{{ store.image.id }}</b> <span :title="store.image.original_filename ?? undefined">{{ fmtMiddle(store.image.original_filename, 36) }}</span> · {{ store.image.width }}×{{ store.image.height }}
            <q-badge outline :color="store.image.annotation_status === 'labeled' ? 'positive' : 'grey-5'" class="q-ml-sm">
              {{ store.image.annotation_status === 'labeled' ? 'annotiert' : 'offen' }}
            </q-badge>
            <q-badge v-if="store.dirty" outline color="orange-4" class="q-ml-xs">ungespeichert</q-badge>
          </div>
          <q-space v-else />
          <q-btn-group flat class="no-wrap">
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
          <q-btn dense flat icon="undo" :disable="!store.history.length" @click="store.undo()"><q-tooltip>Rückgängig (Strg+Z)</q-tooltip></q-btn>
          <q-btn dense flat icon="delete" :disable="!store.selectedId" @click="store.deleteSelected()"><q-tooltip>Box löschen (Entf)</q-tooltip></q-btn>
          <q-btn dense unelevated color="primary" icon="save" label="Speichern" no-caps no-wrap :loading="store.saving" :disable="!store.image || !config" @click="save(false)">
            <q-tooltip>Speichern und als annotiert markieren (Strg+S)</q-tooltip>
          </q-btn>
          <q-btn dense unelevated color="primary" icon-right="skip_next" label="& weiter" no-caps no-wrap :loading="store.saving" :disable="!store.image || !config" @click="save(true)" />
        </div>
        <div class="col relative-position">
          <AnnotationCanvas
            v-if="store.image"
            :image-url="clientApi.imageUrl(store.image.id)"
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
          <div v-else class="absolute-center text-muted text-h6">Bild links auswählen, hochladen oder per Batch-Download laden</div>
        </div>
      </div>

      <!-- right: boxes and check -->
      <div class="side-col bg-panel column no-wrap">
        <q-scroll-area class="col">
          <div v-if="store.image" class="q-pa-md">
            <div class="text-subtitle2 q-mb-xs">Annotationen ({{ positives.length }})</div>
            <div v-if="!positives.length" class="text-caption text-muted q-mb-sm">
              Keine Objekte. Speichern markiert das Bild als <b>negatives Bild</b> (ohne Objekte).
            </div>
            <q-list v-else dense bordered separator class="rounded-borders">
              <q-item v-for="(b, i) in positives" :key="b.uid" clickable :active="b.uid === store.selectedId" active-class="bg-active" @click="store.selectedId = b.uid">
                <q-item-section avatar style="min-width: 24px"><span class="class-dot" :style="{ background: classes.info(b.class).color }" /></q-item-section>
                <q-item-section>
                  <q-item-label>{{ i + 1 }}. {{ classes.info(b.class).label }}<span v-if="b.source === 'prediction'" class="text-muted"> (übernommen)</span></q-item-label>
                </q-item-section>
                <q-item-section side><q-btn dense flat round size="sm" icon="close" @click.stop="removeBox(b.uid)" /></q-item-section>
              </q-item>
            </q-list>

            <template v-if="hardNegatives.length">
              <div class="text-subtitle2 q-mt-md q-mb-xs">Fehlalarme / Hard Negatives ({{ hardNegatives.length }})</div>
              <q-list dense bordered separator class="rounded-borders">
                <q-item v-for="b in hardNegatives" :key="b.uid" clickable :active="b.uid === store.selectedId" active-class="bg-hn-active" @click="store.selectedId = b.uid">
                  <q-item-section avatar style="min-width: 24px"><q-icon name="block" size="xs" :style="{ color: classes.info(b.class).color }" /></q-item-section>
                  <q-item-section>
                    <q-item-label>kein(e) {{ classes.info(b.class).label }}</q-item-label>
                    <q-item-label caption>
                      {{ b.source_model ?? 'manuell' }}<span v-if="b.source_confidence != null"> · {{ (b.source_confidence * 100).toFixed(0) }} %</span>
                    </q-item-label>
                  </q-item-section>
                  <q-item-section side><q-btn dense flat round size="sm" icon="close" @click.stop="removeBox(b.uid)" /></q-item-section>
                </q-item>
              </q-list>
            </template>

            <q-separator class="q-my-md" />
            <div class="text-subtitle2 q-mb-sm">Gegen Inference-Server prüfen</div>
            <div class="column q-gutter-sm">
              <div>
                <div class="text-caption">Confidence-Threshold: {{ confidence.toFixed(2) }}</div>
                <q-slider v-model="confidence" :min="0.15" :max="0.95" :step="0.05" dense />
              </div>
              <q-btn color="secondary" icon="science" label="Prüfen" no-caps :loading="testing" :disable="!config?.inference_url" @click="runTest">
                <q-tooltip>Bild an den Inference-Server senden (Taste T)</q-tooltip>
              </q-btn>
            </div>

            <template v-if="store.lastDetection">
              <div class="text-caption text-muted q-mt-sm">
                {{ store.lastDetection.model.version }} · {{ store.lastDetection.model.input_width }}×{{ store.lastDetection.model.input_height }}
                <template v-if="store.fromSuggestion"> · gespeicherte Prüfung ≥ {{ store.fromSuggestion.confidence }}</template>
                <template v-else> · {{ store.lastDetection.inference_ms.toFixed(0) }} ms</template>
                · {{ store.predictions.length }} offen
              </div>
              <div class="row q-gutter-xs q-mt-xs">
                <q-toggle v-model="showPredictions" dense label="anzeigen" />
                <q-space />
                <q-btn dense flat no-caps size="sm" icon="clear" label="verwerfen" @click="store.clearPredictions()" />
              </div>
              <div class="row q-gutter-xs q-mt-xs">
                <q-btn dense outline no-caps color="secondary" icon="check" label="Übernehmen" class="col"
                       :disable="!store.selectedPrediction || !store.acceptable(store.selectedPrediction)" @click="store.acceptPrediction(store.selectedId!)">
                  <q-tooltip>Ausgewählten Vorschlag übernehmen (Enter oder Doppelklick)</q-tooltip>
                </q-btn>
                <q-btn dense unelevated no-caps color="secondary" icon="done_all" label="Alle übernehmen" class="col"
                       :disable="!store.predictions.some(store.acceptable)" @click="store.acceptAllPredictions()">
                  <q-tooltip>Shift+A</q-tooltip>
                </q-btn>
              </div>
              <q-btn dense outline no-caps color="blue-grey-3" icon="block" label="Als Fehlalarm markieren" class="full-width q-mt-xs"
                     :disable="!store.selectedPrediction || !store.acceptable(store.selectedPrediction)" @click="store.markHardNegative(store.selectedId!)">
                <q-tooltip>Ausgewählter Vorschlag ist kein Objekt – wird als Hard Negative übernommen (Taste N)</q-tooltip>
              </q-btn>
              <q-list dense bordered separator class="rounded-borders q-mt-sm">
                <q-item v-for="p in store.predictions" :key="p.uid" clickable :active="p.uid === store.selectedId" active-class="bg-violet-soft"
                        @click="store.selectedId = p.uid" @dblclick="store.acceptPrediction(p.uid)">
                  <q-item-section avatar style="min-width: 24px"><span class="class-dot" :style="{ border: `2px dashed ${classes.info(p.class).color}` }" /></q-item-section>
                  <q-item-section>
                    <q-item-label>{{ classes.info(p.class).label }} · {{ (p.confidence * 100).toFixed(1) }} %</q-item-label>
                    <q-item-label v-if="!store.acceptable(p)" caption class="text-warning">Klasse nicht konfiguriert – nicht übernehmbar</q-item-label>
                  </q-item-section>
                  <q-item-section side>
                    <div class="row no-wrap">
                      <q-btn dense flat round size="sm" icon="add_task" color="secondary" :disable="!store.acceptable(p)" @click.stop="store.acceptPrediction(p.uid)" />
                      <q-btn dense flat round size="sm" icon="block" color="blue-grey-3" :disable="!store.acceptable(p)" @click.stop="store.markHardNegative(p.uid)" />
                    </div>
                  </q-item-section>
                </q-item>
              </q-list>
            </template>

            <q-separator class="q-my-md" />
            <div class="text-subtitle2 q-mb-xs">Bild</div>
            <div v-if="current?.source_url" class="row items-center no-wrap q-mb-sm">
              <span class="col text-caption text-muted ellipsis">
                {{ shortUrl(current.source_url) }}
                <q-tooltip max-width="480px" class="break-all">{{ current.source_url }}</q-tooltip>
              </span>
              <q-btn dense flat round size="sm" icon="content_copy" @click="copyUrl(current.source_url)"><q-tooltip>URL kopieren</q-tooltip></q-btn>
            </div>
            <div class="column q-gutter-xs">
              <q-btn v-if="store.image.annotation_status === 'labeled'" dense outline no-caps icon="restart_alt" label="Wieder öffnen" :disable="store.dirty" @click="reopen">
                <q-tooltip>Zurück auf „offen“ – die Boxen bleiben erhalten, das Bild wird dann nicht als annotiert übernommen</q-tooltip>
              </q-btn>
              <q-btn dense outline no-caps color="negative" icon="delete_forever" label="Bild löschen" @click="deleteImage" />
            </div>
          </div>
        </q-scroll-area>
      </div>
    </div>
  </q-page>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { useQuasar } from 'quasar'
import AnnotationCanvas from '@/components/AnnotationCanvas.vue'
import UrlDownloadDialog, { type DownloadProgress } from '@/components/UrlDownloadDialog.vue'
import { errorMessage, fmtDate, fmtMiddle } from '@/services/api'
import { useAnnotationStore } from '@/stores/annotation'
import { useClassesStore } from '@/stores/classes'
import { clientApi, toDetail, toDetectionClasses, type ClientConfig, type ClientCounts, type ClientImage } from './api'

const emit = defineEmits<{ logout: [] }>()

const $q = useQuasar()
const store = useAnnotationStore()
const classes = useClassesStore()

const config = ref<ClientConfig | null>(null)
const images = ref<ClientImage[]>([])
const counts = ref<ClientCounts>({ total: 0, open: 0, annotated: 0 })
const filter = ref<'all' | 'open' | 'annotated'>('open')
const showPredictions = ref(true)
const confidence = ref(0.25)
const testing = ref(false)
const downloadDialog = ref(false)
const download = ref<DownloadProgress | null>(null)
const checkRun = ref<{ total: number; done: number; failed: number } | null>(null)
let checkAbort: AbortController | null = null
const fileInput = ref<HTMLInputElement | null>(null)

const visible = computed(() => (filter.value === 'all' ? images.value : images.value.filter((i) => i.status === filter.value)))
const current = computed(() => images.value.find((i) => i.id === store.image?.id) ?? null)
const uncheckedOpen = computed(() => images.value.filter((i) => i.status === 'open' && !i.detection))
const positives = computed(() => store.boxes.filter((b) => b.type === 'positive'))
const hardNegatives = computed(() => store.boxes.filter((b) => b.type === 'hard_negative'))

function pageStyle(offset: number) {
  return { height: offset ? `calc(100vh - ${offset}px)` : '100vh' }
}

function replaceImage(img: ClientImage) {
  const i = images.value.findIndex((x) => x.id === img.id)
  if (i >= 0) images.value[i] = img
}

async function refresh() {
  const [cfg, list] = await Promise.all([clientApi.getConfig(), clientApi.listImages()])
  config.value = cfg
  if (cfg) {
    classes.all = toDetectionClasses(cfg)
    classes.loaded = true
    confidence.value = Math.max(0.15, cfg.confidence)
    if (!classes.info(store.activeClass).known) store.activeClass = cfg.classes[0].name
  }
  images.value = list.items
  counts.value = list.counts
  // the shown image was deleted elsewhere (e.g. fetched by the training system)
  if (store.image && !images.value.some((i) => i.id === store.image!.id) && !store.dirty) store.image = null
}

function confirmDiscard(): Promise<boolean> {
  if (!store.dirty) return Promise.resolve(true)
  return new Promise((resolve) =>
    $q
      .dialog({ title: 'Ungespeicherte Änderungen', message: 'Änderungen an diesem Bild verwerfen?', cancel: true, persistent: true })
      .onOk(() => resolve(true))
      .onCancel(() => resolve(false)),
  )
}

async function open(id: number) {
  if (id === store.image?.id || !(await confirmDiscard())) return
  try {
    const img = await clientApi.getImage(id)
    replaceImage(img)
    store.load(toDetail(img))
  } catch (e) {
    $q.notify({ type: 'negative', message: errorMessage(e) })
  }
}

/** previous/next image of the visible list */
function neighbour(step: -1 | 1): ClientImage | null {
  const list = visible.value
  const i = list.findIndex((x) => x.id === store.image?.id)
  if (i < 0) return list[0] ?? null
  return list[i + step] ?? null
}

function go(step: -1 | 1) {
  const n = neighbour(step)
  if (n) open(n.id)
}

async function save(next: boolean) {
  if (!store.image) return
  // the next image of the list *before* saving (with the "open" filter the saved image leaves the list)
  const following = next ? neighbour(1) : null
  try {
    const ok = await store.save(true, async (id, annotations, markLabeled) => {
      const img = await clientApi.saveAnnotations(id, annotations, markLabeled)
      replaceImage(img)
      return toDetail(img)
    })
    if (!ok) return
    counts.value = (await clientApi.listImages()).counts
    $q.notify({ type: 'positive', message: 'Gespeichert', timeout: 1000 })
    if (following) open(following.id)
  } catch (e) {
    $q.notify({ type: 'negative', message: errorMessage(e) })
  }
}

/** host, shortened file name and a hint for the query, e.g. "cam:8080/…/a4abd4…afe62.jpg?…" (full URL in the tooltip) */
function shortUrl(url: string): string {
  try {
    const u = new URL(url)
    const name = decodeURIComponent(u.pathname.split('/').pop() ?? '')
    const dirs = u.pathname.split('/').length > 2 ? '/…' : ''
    return `${u.host}${dirs}/${fmtMiddle(name, 16)}${u.search ? '?…' : ''}`
  } catch {
    return fmtMiddle(url, 40)
  }
}

async function copyUrl(url: string) {
  try {
    await navigator.clipboard.writeText(url)
    $q.notify({ type: 'positive', message: 'URL kopiert', timeout: 1000 })
  } catch {
    // no clipboard access (plain HTTP outside localhost): show the URL to copy by hand
    $q.dialog({ title: 'Quell-URL', message: url, style: 'word-break: break-all' })
  }
}

function removeBox(uid: string) {
  store.selectedId = uid
  store.deleteSelected()
}

async function runTest() {
  if (!store.image || !config.value?.inference_url) return
  testing.value = true
  try {
    const img = await clientApi.detect(store.image.id, confidence.value)
    replaceImage(img)
    const d = img.detection!
    store.setDetection({
      image: { width: img.width, height: img.height },
      model: { version: d.model_version, status: 'inference', input_width: d.input_width, input_height: d.input_height },
      inference_ms: d.inference_ms ?? 0,
      detections: d.detections,
    })
    showPredictions.value = true
  } catch (e) {
    $q.notify({ type: 'negative', message: errorMessage(e) })
  } finally {
    testing.value = false
  }
}

/** check all open images without a stored check, two at a time */
async function checkOpen() {
  const queue = uncheckedOpen.value.map((i) => i.id)
  checkRun.value = { total: queue.length, done: 0, failed: 0 }
  checkAbort = new AbortController()
  const signal = checkAbort.signal
  let lastError = ''
  async function worker() {
    while (queue.length && !signal.aborted) {
      const id = queue.shift()!
      try {
        const img = await clientApi.detect(id, confidence.value, signal)
        replaceImage(img)
        // the shown image: show its suggestions unless it is being edited
        if (img.id === store.image?.id && !store.dirty) store.load(toDetail(img))
      } catch (e) {
        if (signal.aborted) return
        checkRun.value!.failed++
        lastError = errorMessage(e)
      }
      checkRun.value!.done++
    }
  }
  try {
    await Promise.all([worker(), worker()])
  } finally {
    if (lastError) $q.notify({ type: 'warning', message: `${checkRun.value?.failed} Prüfung(en) fehlgeschlagen: ${lastError}` })
    checkRun.value = null
    checkAbort = null
  }
}

async function onFiles(e: Event) {
  const input = e.target as HTMLInputElement
  const files = [...(input.files ?? [])]
  input.value = ''
  if (!files.length) return
  try {
    const results = await clientApi.uploadImages(files)
    const created = results.filter((r) => r.status === 'created').length
    const failed = results.filter((r) => r.status === 'error')
    $q.notify({
      type: failed.length ? 'warning' : 'positive',
      message: `${created} neu, ${results.length - created - failed.length} Duplikate${failed.length ? `, ${failed.length} Fehler: ${failed[0].error}` : ''}`,
    })
    await refresh()
  } catch (err) {
    $q.notify({ type: 'negative', message: errorMessage(err) })
  }
}

async function reopen() {
  if (!store.image) return
  const img = await clientApi.reopen(store.image.id)
  replaceImage(img)
  store.load(toDetail(img))
  counts.value = (await clientApi.listImages()).counts
}

function deleteImage() {
  const image = store.image
  if (!image) return
  $q.dialog({ title: 'Bild löschen', message: `Bild #${image.id} mit seinen Annotationen löschen?`, cancel: true }).onOk(async () => {
    const following = neighbour(1) ?? neighbour(-1)
    try {
      await clientApi.deleteImage(image.id)
      store.dirty = false
      store.image = null
      await refresh()
      if (following && following.id !== image.id) open(following.id)
    } catch (e) {
      $q.notify({ type: 'negative', message: errorMessage(e) })
    }
  })
}

function onKeydown(e: KeyboardEvent) {
  const t = e.target as HTMLElement | null
  if (t && (t.tagName === 'INPUT' || t.tagName === 'TEXTAREA' || t.isContentEditable)) return
  if (e.repeat && !['Delete', 'Backspace', 'PageDown', 'PageUp'].includes(e.key)) {
    if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 's') e.preventDefault()
    return
  }
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
    go(1)
  } else if (e.key === 'PageUp') {
    e.preventDefault()
    go(-1)
  }
}

function onBeforeUnload(e: BeforeUnloadEvent) {
  if (store.dirty || download.value || checkRun.value) {
    e.preventDefault()
    e.returnValue = ''
  }
}

onMounted(async () => {
  window.addEventListener('keydown', onKeydown)
  window.addEventListener('beforeunload', onBeforeUnload)
  try {
    await refresh()
  } catch (e) {
    $q.notify({ type: 'negative', message: errorMessage(e) })
  }
})
onBeforeUnmount(() => {
  window.removeEventListener('keydown', onKeydown)
  window.removeEventListener('beforeunload', onBeforeUnload)
  checkAbort?.abort()
})
</script>

<style scoped>
.header {
  height: 56px;
  min-height: 56px;
  border-bottom: 1px solid var(--app-border);
}
.toolbar {
  height: 56px;
  min-height: 56px;
  border-bottom: 1px solid var(--app-border);
  overflow: hidden;
}
.browser-col {
  width: 300px;
  min-width: 240px;
  border-right: 1px solid var(--app-border);
}
.side-col {
  width: 320px;
  min-width: 280px;
  border-left: 1px solid var(--app-border);
}
.thumb {
  width: 72px;
  height: 40px;
  object-fit: cover;
  border-radius: 4px;
  display: block;
}
.progress-box {
  width: 150px;
}
</style>
