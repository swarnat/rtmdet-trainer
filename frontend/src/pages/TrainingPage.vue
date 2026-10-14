<template>
  <q-page padding>
    <div class="row q-col-gutter-md">
      <!-- start dialog -->
      <div class="col-12 col-md-4">
        <q-card flat bordered>
          <q-card-section>
            <div class="text-h6">Training starten</div>
            <div class="text-caption text-muted">
              Das Training läuft im separaten Trainer-Container und blockiert die Inferenz nicht. Neue Modelle werden
              immer als <b>Candidate</b> registriert.
            </div>
          </q-card-section>
          <q-card-section v-if="gpu && !gpu.available" class="q-pt-none">
            <q-banner dense rounded class="bg-negative text-white">
              <template #avatar><q-icon name="memory" /></template>
              <div class="text-weight-medium">Keine GPU im Trainer – Training nicht möglich</div>
              <div class="text-caption">{{ gpu.error }}</div>
              <div class="text-caption q-mt-xs">
                Trainer-Container neu erstellen: <span class="mono">docker compose up -d --force-recreate trainer</span>
              </div>
            </q-banner>
          </q-card-section>
          <q-card-section class="column q-gutter-md">
            <q-select
              v-model="form.base_model_id"
              :options="baseModels"
              option-value="id"
              option-label="label"
              emit-value
              map-options
              outlined
              dense
              label="Base Model"
              :hint="baseHint"
            >
              <template #append><HelpIcon :text="help.base_model" /></template>
              <template #option="scope">
                <q-item v-bind="scope.itemProps">
                  <q-item-section>
                    <q-item-label>{{ scope.opt.label }}</q-item-label>
                    <q-item-label caption>{{ scope.opt.description }}</q-item-label>
                  </q-item-section>
                </q-item>
              </template>
            </q-select>
            <q-select
              v-model="form.class_names"
              :options="classOptions"
              emit-value
              map-options
              multiple
              use-chips
              outlined
              dense
              label="Klassen"
              hint="Standard: alle aktiven Klassen"
            >
              <template #append><HelpIcon :text="help.classes" /></template>
            </q-select>
            <q-select v-model="form.input_size" :options="models.inputSizes" outlined dense label="Input Resolution (B×H)">
              <template #append><HelpIcon :text="help.input_size" /></template>
            </q-select>
            <div class="row q-col-gutter-sm">
              <q-input v-model.number="form.epochs" type="number" :min="1" :max="1000" outlined dense label="Epochs" class="col-6">
                <template #append><HelpIcon :text="help.epochs" /></template>
              </q-input>
              <q-input v-model.number="form.batch_size" type="number" :min="1" :max="128" outlined dense label="Batch Size" class="col-6">
                <template #append><HelpIcon :text="help.batch_size" /></template>
              </q-input>
            </div>
            <div class="row q-col-gutter-sm">
              <q-input
                v-model="form.learning_rate"
                outlined
                dense
                clearable
                label="Learning Rate (optional)"
                hint="leer = automatisch (0.00025 × Batch/4)"
                class="col-8"
              >
                <template #append><HelpIcon :text="help.learning_rate" /></template>
              </q-input>
              <q-input v-model.number="form.num_workers" type="number" :min="0" :max="32" outlined dense label="Loader-Worker" class="col-4">
                <template #append><HelpIcon :text="help.num_workers" /></template>
              </q-input>
            </div>
            <div v-if="elig" class="text-caption">
              Verwendbar: <b>{{ elig.usable.train }}</b> train / <b>{{ elig.usable.validation }}</b> val
              (davon {{ elig.negative }} negativ), {{ elig.hard_negatives }} Hard Negatives.
              <span v-if="elig.needs_review" class="text-warning">
                {{ elig.needs_review }} annotierte Bilder sind für diese Klassen noch nicht geprüft und werden ausgelassen.
              </span>
              <span v-if="elig.duplicates"> {{ elig.duplicates }} leere Duplikate werden ausgelassen.</span>
              <span v-if="stats?.images_unlabeled"> {{ stats.images_unlabeled }} Bilder offen.</span>
              <div v-if="!elig.usable.validation" class="text-negative">Mindestens ein verwendbares Validierungsbild nötig.</div>
            </div>
            <q-btn
              color="primary"
              icon="play_arrow"
              label="Training starten"
              :loading="starting"
              :disable="gpu?.available === false"
              @click="start"
            />
            <div v-if="gpu?.available" class="text-caption text-muted">
              <q-icon name="memory" size="14px" /> GPU: {{ gpu.devices.join(', ') }}
            </div>
          </q-card-section>
        </q-card>
      </div>

      <!-- runs -->
      <div class="col-12 col-md-8">
        <q-card flat bordered>
          <q-card-section class="row items-center">
            <div class="text-h6">Trainingsläufe</div>
            <q-space />
            <q-btn flat round dense icon="refresh" @click="refresh" />
          </q-card-section>
          <q-table :rows="runs" :columns="columns" row-key="id" flat dense :pagination="{ rowsPerPage: 15 }" @row-click="(_e, row) => select(row.id)">
            <template #header-cell="props">
              <q-th :props="props">
                {{ props.col.label }}<HelpIcon v-if="columnHelp[props.col.name]" :term="columnHelp[props.col.name]" inline />
              </q-th>
            </template>
            <template #body-cell-status="props">
              <q-td :props="props">
                <q-chip dense outline :color="statusColor[props.row.status]" :label="props.row.status" />
              </q-td>
            </template>
            <template #body-cell-progress="props">
              <q-td :props="props" style="min-width: 160px">
                <template v-if="props.row.status === 'running'">
                  <q-linear-progress :value="(props.row.progress_json?.percent ?? 0) / 100" rounded size="10px" color="primary" />
                  <div class="text-caption">{{ progressText(props.row) }}</div>
                </template>
                <span v-else-if="props.row.status === 'failed'" class="text-negative text-caption ellipsis" style="max-width: 220px; display: inline-block">
                  {{ props.row.error }}
                </span>
                <span v-else-if="props.row.model_version" class="text-caption">→ {{ props.row.model_version }}</span>
              </q-td>
            </template>
          </q-table>
        </q-card>

        <q-card v-if="selected" flat bordered class="q-mt-md">
          <q-card-section class="row items-center q-gutter-sm">
            <div class="text-h6">Lauf #{{ selected.id }}</div>
            <q-chip dense outline :color="statusColor[selected.status]" :label="selected.status" />
            <HelpIcon term="runStatus" inline />
            <q-space />
            <q-btn
              v-if="selected.status === 'queued' || selected.status === 'running'"
              outline
              color="negative"
              icon="stop"
              label="Abbrechen"
              no-caps
              @click="cancel(selected.id)"
            />
            <q-btn v-if="selected.model_version" flat color="primary" icon="inventory_2" :label="selected.model_version" no-caps to="/models" />
          </q-card-section>
          <q-card-section class="q-pt-none">
            <div class="row q-col-gutter-md text-body2">
              <div class="col-12 col-sm-6">
                <div><b>Base Model<HelpIcon term="base" inline />:</b> {{ selected.base_model_id }}</div>
                <div><b>Klassen:</b> {{ (selected.class_names ?? []).map((n) => classes.info(n).label).join(', ') }}</div>
                <div><b>Auflösung<HelpIcon term="resolution" inline />:</b> {{ selected.input_width }}×{{ selected.input_height }}</div>
                <div><b>Epochs / Batch<HelpIcon :text="`${GLOSSARY.epoch} ${help.batch_size}`" inline />:</b> {{ selected.epochs }} / {{ selected.batch_size }}</div>
                <div><b>Learning Rate<HelpIcon :text="help.learning_rate" inline />:</b> {{ selected.learning_rate ?? 'auto' }}</div>
                <div><b>Dataset-Snapshot<HelpIcon term="datasetSnapshot" inline />:</b> <span class="mono">{{ selected.dataset_snapshot ?? '–' }}</span></div>
              </div>
              <div class="col-12 col-sm-6">
                <div><b>Erstellt:</b> {{ fmtDate(selected.created_at) }}</div>
                <div><b>Gestartet:</b> {{ fmtDate(selected.started_at) }}</div>
                <div><b>Beendet:</b> {{ fmtDate(selected.finished_at) }}</div>
                <div v-if="selected.progress_json?.phase"><b>Phase<HelpIcon term="loss" inline />:</b> {{ selected.progress_json.phase }} {{ progressText(selected) }}</div>
                <div v-if="selected.dataset_stats_json">
                  <b>Daten<HelpIcon :text="`${GLOSSARY.split} ${GLOSSARY.hardNegatives}`" inline />:</b>
                  train {{ selected.dataset_stats_json.train?.images }} Bilder / {{ selected.dataset_stats_json.train?.boxes }} Boxen,
                  val {{ selected.dataset_stats_json.validation?.images }} / {{ selected.dataset_stats_json.validation?.boxes }}
                  <span v-if="selected.dataset_stats_json.excluded_duplicates">
                    · {{ selected.dataset_stats_json.excluded_duplicates }} Duplikate ausgelassen
                  </span>
                  <span v-if="selected.dataset_stats_json.excluded_needs_review">
                    · {{ selected.dataset_stats_json.excluded_needs_review }} ungeprüft ausgelassen
                  </span>
                  <span v-if="selected.dataset_stats_json.hard_negatives?.total">
                    · {{ selected.dataset_stats_json.hard_negatives.total }} Hard Negatives
                    ({{ selected.dataset_stats_json.hard_negatives.train_crops }} Crops × {{ selected.dataset_stats_json.hard_negatives.oversample }})
                  </span>
                </div>
              </div>
            </div>
            <q-linear-progress
              v-if="selected.status === 'running'"
              :value="(selected.progress_json?.percent ?? 0) / 100"
              size="14px"
              rounded
              class="q-mt-sm"
              color="primary"
            >
              <div class="absolute-full flex flex-center text-caption text-white">{{ selected.progress_json?.percent ?? 0 }} %</div>
            </q-linear-progress>
            <div v-if="selected.error" class="text-negative q-mt-sm mono text-caption">{{ selected.error }}</div>
          </q-card-section>
          <q-card-section v-if="valHistory.length || selected.status === 'running'" class="q-pt-none">
            <div class="text-subtitle2">Validierung während des Trainings (MMDetection, COCO-mAP)<HelpIcon term="valChart" inline /></div>
            <EpochChart :history="valHistory" :max-epochs="selected.epochs" />
          </q-card-section>
          <q-card-section v-if="selected.metrics_json" class="q-pt-none">
            <div class="row items-center q-gutter-sm q-mb-xs">
              <div class="text-subtitle2">Metriken des exportierten Modells</div>
              <q-space />
              <template v-if="selected.model_version && selected.status === 'completed'">
                <template v-if="analysis && analysis.model_version === selected.model_version">
                  <div v-if="analysis.status === 'queued' || analysis.status === 'running'" class="row items-center no-wrap q-gutter-x-sm" style="min-width: 220px">
                    <span class="text-caption text-secondary">Fehleranalyse {{ analysis.processed }} / {{ analysis.total }}</span>
                    <q-linear-progress :value="analysis.total ? analysis.processed / analysis.total : 0" color="secondary" rounded class="col" />
                  </div>
                  <q-btn
                    v-else-if="analysis.status === 'completed' && analysis.marked_images"
                    unelevated
                    dense
                    no-caps
                    color="negative"
                    icon="image_search"
                    :label="`${analysis.marked_images} Fehlerbilder annotieren`"
                    @click="openErrorImages"
                  >
                    <q-tooltip>{{ analysis.marked_images }} von {{ analysis.processed }} Bildern mit Fehlalarmen oder übersehenen Objekten</q-tooltip>
                  </q-btn>
                  <span v-else-if="analysis.status === 'completed'" class="text-caption text-positive">Keine Fehlerbilder gefunden</span>
                  <span v-else class="text-caption text-negative">Fehleranalyse {{ analysis.status }}<span v-if="analysis.error">: {{ analysis.error }}</span></span>
                </template>
                <q-btn-dropdown
                  outline
                  dense
                  no-caps
                  color="secondary"
                  icon="rule"
                  label="Fehlerbilder markieren"
                  :loading="analysisStarting"
                  :disable="analysis?.status === 'queued' || analysis?.status === 'running'"
                >
                  <q-list dense style="max-width: 360px">
                    <q-item v-close-popup clickable @click="startAnalysis('errors_validation')">
                      <q-item-section>
                        <q-item-label>Validierungsbilder</q-item-label>
                        <q-item-label caption>Die Bilder hinter TP/FP/FN oben: wo das Modell noch Fehler macht</q-item-label>
                      </q-item-section>
                    </q-item>
                    <q-item v-close-popup clickable @click="startAnalysis('errors_labeled')">
                      <q-item-section>
                        <q-item-label>Alle annotierten Bilder</q-item-label>
                        <q-item-label caption>Auch Trainingsbilder: Fehler dort deuten oft auf fehlende oder falsche Annotationen</q-item-label>
                      </q-item-section>
                    </q-item>
                  </q-list>
                </q-btn-dropdown>
                <HelpIcon term="errorAnalysis" inline />
              </template>
            </div>
            <MetricsTable :metrics="selected.metrics_json" />
          </q-card-section>
          <q-card-section class="q-pt-none">
            <div class="row items-center">
              <div class="text-subtitle2">Log</div>
              <q-space />
              <q-toggle v-model="autoScroll" dense label="automatisch scrollen" />
            </div>
            <div ref="logBox" class="log-view" style="height: 360px">{{ log || 'noch keine Ausgabe' }}</div>
          </q-card-section>
        </q-card>
      </div>
    </div>
  </q-page>
</template>

<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { useQuasar, type QTableColumn } from 'quasar'
import { useRouter } from 'vue-router'
import EpochChart from '@/components/EpochChart.vue'
import HelpIcon from '@/components/HelpIcon.vue'
import MetricsTable from '@/components/MetricsTable.vue'
import { GLOSSARY, type GlossaryTerm } from '@/glossary'
import { api, errorMessage, fmtDate, fmtPct, type BaseModelOption, type BatchScope, type BatchTest, type DatasetStats, type TrainerGpuStatus, type TrainingEligibility, type TrainingRun } from '@/services/api'
import { useClassesStore } from '@/stores/classes'
import { useModelsStore } from '@/stores/models'
import { focusPerClass, missedText } from '@/services/focus'

const $q = useQuasar()
const router = useRouter()
const models = useModelsStore()
const classes = useClassesStore()

const runs = ref<TrainingRun[]>([])
const baseModels = ref<BaseModelOption[]>([])
const stats = ref<DatasetStats | null>(null)
const selectedId = ref<number | null>(null)
const log = ref('')
const logBox = ref<HTMLDivElement | null>(null)
const autoScroll = ref(true)
const starting = ref(false)
const form = reactive({
  base_model_id: 'rtmdet-s-coco',
  input_size: '1536x864',
  epochs: 30,
  batch_size: 4,
  learning_rate: '' as string | null,
  num_workers: 4,
  class_names: [] as string[],
})
const elig = ref<TrainingEligibility | null>(null)
// explanations for the "?" icons in the start form, in plain language
const help = {
  base_model:
    'Das Modell, mit dem das Training beginnt. Ein „COCO“-Modell kennt schon allgemeine Dinge wie Personen oder Autos und lernt jetzt deine Klassen dazu. ' +
    'Wählst du ein eigenes, schon trainiertes Modell, wird es mit deinen Bildern weiter verbessert. ' +
    'Größere Modelle (M) erkennen genauer, sind aber langsamer – kleinere (tiny, S) sind schneller.',
  classes:
    'Welche Arten von Objekten das neue Modell erkennen soll, z. B. Person oder Fahrzeug. Normalerweise einfach alle auswählen. ' +
    'Zum Lernen werden nur Bilder benutzt, die du auf alle ausgewählten Klassen geprüft hast.',
  input_size:
    'Auf diese Größe werden die Bilder beim Training gebracht. Größer: kleine oder weit entfernte Objekte werden besser erkannt, ' +
    'aber Training und Erkennung dauern länger und brauchen mehr Grafikspeicher. Am besten dieselbe Größe wählen, die später bei der Erkennung benutzt wird.',
  epochs:
    'Wie oft das Modell alle Trainingsbilder komplett durchgeht. Mehr Durchgänge: es lernt gründlicher, das Training dauert aber länger. ' +
    'Ab einem gewissen Punkt bringen weitere Durchgänge nichts mehr. 30 ist ein guter Startwert.',
  batch_size:
    'Wie viele Bilder gleichzeitig verarbeitet werden. Ein höherer Wert kann das Training beschleunigen, braucht aber mehr Grafikspeicher. ' +
    'Bricht das Training mit einem Speicherfehler ab, diesen Wert kleiner machen (z. B. 2).',
  learning_rate:
    'Wie stark das Modell bei jedem Lernschritt umlernt. Am besten leer lassen – dann wird automatisch ein passender Wert berechnet. ' +
    'Zu hoch: das Modell lernt unruhig und wird schlechter. Zu niedrig: es lernt sehr langsam.',
  num_workers:
    'Wie viele Helfer gleichzeitig die Bilder laden und vorbereiten, damit das Training nicht auf Nachschub warten muss. ' +
    'Normalerweise 4 lassen. Bei Fehlern oder wenig Arbeitsspeicher kleiner stellen (0–2).',
}
const baseHint = computed(() => {
  const b = baseModels.value.find((x) => x.id === form.base_model_id)
  if (!b) return ''
  return b.kind === 'coco'
    ? `${b.architecture}: neues Modell ab COCO-Gewichten`
    : `${b.architecture}: weitertrainieren (gleiche Modellgröße)`
})
const classOptions = computed(() => classes.active.map((c) => ({ value: c.name, label: c.label })))

watch(
  () => [...form.class_names],
  async (names) => {
    try {
      elig.value = await api.eligibility(names)
    } catch {
      elig.value = null
    }
  },
)

const statusColor: Record<string, string> = { queued: 'grey-5', running: 'primary', completed: 'positive', failed: 'negative' }
const columnHelp: Record<string, GlossaryTerm> = { status: 'runStatus', base: 'base', res: 'resolution', epochs: 'epoch', missed: 'missed', map: 'mAP5095', map50: 'mAP50' }
const columns: QTableColumn<TrainingRun>[] = [
  { name: 'id', label: '#', field: 'id', align: 'left', sortable: true },
  { name: 'status', label: 'Status', field: 'status', align: 'left' },
  { name: 'base', label: 'Base', field: 'base_model_id', align: 'left' },
  { name: 'classes', label: 'Klassen', field: (r) => (r.class_names ?? []).join(', '), align: 'left' },
  { name: 'res', label: 'Auflösung', field: (r) => `${r.input_width}×${r.input_height}`, align: 'left' },
  { name: 'epochs', label: 'Epochs', field: 'epochs' },
  { name: 'missed', label: 'Nicht erkannt Person', field: (r) => missedText(focusPerClass(r.metrics_json)), classes: 'focus-col', headerClasses: 'focus-col' },
  { name: 'map', label: 'mAP50-95 Person', field: (r) => fmtPct(focusPerClass(r.metrics_json)?.['mAP50-95']), classes: 'focus-col', headerClasses: 'focus-col' },
  { name: 'map50', label: 'mAP50 Person', field: (r) => fmtPct(focusPerClass(r.metrics_json)?.mAP50), classes: 'focus-col', headerClasses: 'focus-col' },
  { name: 'progress', label: 'Fortschritt / Ergebnis', field: 'id', align: 'left' },
  { name: 'created', label: 'Erstellt', field: (r) => fmtDate(r.created_at), align: 'left' },
]

const selected = computed(() => runs.value.find((r) => r.id === selectedId.value) ?? null)
const valHistory = computed(() => selected.value?.metrics_json?.mmdet_val_history ?? selected.value?.progress_json?.val_history ?? [])

function progressText(r: TrainingRun) {
  const p = r.progress_json
  if (!p) return ''
  const parts: string[] = []
  if (p.epoch) parts.push(`Epoch ${p.epoch}/${p.max_epochs}`)
  if (p.loss != null) parts.push(`Loss ${p.loss.toFixed(3)}`)
  if (p.eta_seconds != null && r.status === 'running') parts.push(`ETA ${formatEta(p.eta_seconds)}`)
  return parts.join(' · ')
}

function formatEta(s: number) {
  const h = Math.floor(s / 3600)
  const m = Math.floor((s % 3600) / 60)
  return h ? `${h} h ${m} min` : `${m} min ${Math.floor(s % 60)} s`
}

async function refresh() {
  try {
    runs.value = await api.listRuns()
    if (selectedId.value === null && runs.value.length) selectedId.value = runs.value[0].id
    if (selectedId.value !== null) await loadLog()
  } catch (e) {
    $q.notify({ type: 'negative', message: errorMessage(e) })
  }
}

async function loadLog() {
  if (selectedId.value === null) return
  const res = await api.getRunLog(selectedId.value)
  if (res.log !== log.value) {
    log.value = res.log
    if (autoScroll.value) {
      await nextTick()
      if (logBox.value) logBox.value.scrollTop = logBox.value.scrollHeight
    }
  }
}

function select(id: number) {
  selectedId.value = id
  log.value = ''
  loadLog()
}

async function start() {
  const lr = form.learning_rate ? Number(form.learning_rate) : null
  if (lr !== null && (!Number.isFinite(lr) || lr <= 0)) {
    $q.notify({ type: 'warning', message: 'Ungültige Learning Rate' })
    return
  }
  starting.value = true
  try {
    const run = await api.startRun({
      base_model_id: form.base_model_id,
      class_names: form.class_names.length ? form.class_names : undefined,
      input_size: form.input_size,
      epochs: form.epochs,
      batch_size: form.batch_size,
      learning_rate: lr,
      num_workers: form.num_workers,
    })
    $q.notify({ type: 'positive', message: `Trainingslauf #${run.id} eingereiht` })
    selectedId.value = run.id
    await refresh()
  } catch (e) {
    $q.notify({ type: 'negative', message: errorMessage(e) })
  } finally {
    starting.value = false
  }
}

function cancel(id: number) {
  $q.dialog({
    title: 'Training abbrechen',
    message: `Trainingslauf #${id} wirklich abbrechen?`,
    cancel: { label: 'Nein', flat: true },
    ok: { label: 'Abbrechen', color: 'negative' },
  }).onOk(async () => {
    try {
      await api.cancelRun(id)
      await refresh()
    } catch (e) {
      $q.notify({ type: 'negative', message: errorMessage(e) })
    }
  })
}

// training requires a GPU; the trainer re-checks every 30 s (healthcheck)
const gpu = ref<TrainerGpuStatus | null>(null)
async function refreshGpu() {
  try {
    gpu.value = (await api.trainerGpu()).status
  } catch {
    gpu.value = null
  }
}

let timer: number | undefined
let gpuTimer: number | undefined
// error analysis of the selected run's model (a batch test with scope errors_*)
const analysis = ref<BatchTest | null>(null)
const analysisStarting = ref(false)
let analysisTimer: number | undefined

async function startAnalysis(scope: BatchScope) {
  const run = selected.value
  if (!run?.model_version) return
  analysisStarting.value = true
  try {
    analysis.value = await api.startBatchTest({
      model: run.model_version,
      // same parameters as the evaluation behind the metrics table
      input_size: `${run.input_width}x${run.input_height}`,
      confidence: run.metrics_json?.confidence_for_pr ?? null,
      scope,
    })
    pollAnalysis()
  } catch (e) {
    $q.notify({ type: 'negative', message: errorMessage(e) })
  } finally {
    analysisStarting.value = false
  }
}

async function pollAnalysis() {
  window.clearTimeout(analysisTimer)
  if (!analysis.value) return
  try {
    analysis.value = await api.getBatchTest(analysis.value.id)
  } catch {
    /* polling: ignore transient errors */
  }
  if (analysis.value.status === 'queued' || analysis.value.status === 'running') analysisTimer = window.setTimeout(pollAnalysis, 1500)
}

async function openErrorImages() {
  try {
    const first = (await api.listImages({ has_errors: true, limit: 1 })).items[0]
    router.push({ name: 'annotate', params: first ? { id: first.id } : {}, query: { filter: 'errors' } })
  } catch (e) {
    $q.notify({ type: 'negative', message: errorMessage(e) })
  }
}

onMounted(async () => {
  refreshGpu()
  gpuTimer = window.setInterval(refreshGpu, 30000)
  await Promise.all([models.refresh(), classes.refresh()])
  form.input_size = models.defaultInputSize
  form.base_model_id = models.settings?.default_base_model ?? 'rtmdet-s-coco'
  form.class_names = classes.active.map((c) => c.name)
  const [bm, st] = await Promise.all([api.baseModels(), api.datasetStats()])
  baseModels.value = bm
  stats.value = st
  await refresh()
  timer = window.setInterval(() => {
    const active = runs.value.some((r) => r.status === 'queued' || r.status === 'running')
    if (active || selected.value?.status === 'running') refresh()
  }, 3000)
})
onBeforeUnmount(() => {
  window.clearInterval(timer)
  window.clearInterval(gpuTimer)
  window.clearTimeout(analysisTimer)
})
</script>
