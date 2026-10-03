<template>
  <q-page padding>
    <div class="row q-col-gutter-md">
      <!-- start dialog -->
      <div class="col-12 col-md-4">
        <q-card flat bordered>
          <q-card-section>
            <div class="text-h6">Training starten</div>
            <div class="text-caption text-grey-7">
              Das Training läuft im separaten Trainer-Container und blockiert die Inferenz nicht. Neue Modelle werden
              immer als <b>Candidate</b> registriert.
            </div>
          </q-card-section>
          <q-card-section class="column q-gutter-md">
            <q-select v-model="form.base_model_id" :options="baseModels" option-value="id" option-label="label" emit-value map-options outlined dense label="Base Model">
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
            />
            <q-select v-model="form.input_size" :options="models.inputSizes" outlined dense label="Input Resolution (B×H)" />
            <div class="row q-col-gutter-sm">
              <q-input v-model.number="form.epochs" type="number" :min="1" :max="1000" outlined dense label="Epochs" class="col-6" />
              <q-input v-model.number="form.batch_size" type="number" :min="1" :max="128" outlined dense label="Batch Size" class="col-6" />
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
              />
              <q-input v-model.number="form.num_workers" type="number" :min="0" :max="32" outlined dense label="Loader-Worker" class="col-4" />
            </div>
            <div v-if="elig" class="text-caption">
              Verwendbar: <b>{{ elig.usable.train }}</b> train / <b>{{ elig.usable.validation }}</b> val
              (davon {{ elig.negative }} negativ), {{ elig.hard_negatives }} Hard Negatives.
              <span v-if="elig.needs_review" class="text-warning">
                {{ elig.needs_review }} annotierte Bilder sind für diese Klassen noch nicht geprüft und werden ausgelassen.
              </span>
              <span v-if="stats?.images_unlabeled"> {{ stats.images_unlabeled }} Bilder offen.</span>
              <div v-if="!elig.usable.validation" class="text-negative">Mindestens ein verwendbares Validierungsbild nötig.</div>
            </div>
            <q-btn color="primary" icon="play_arrow" label="Training starten" :loading="starting" @click="start" />
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
            <template #body-cell-status="props">
              <q-td :props="props">
                <q-chip dense square :color="statusColor[props.row.status]" text-color="white" :label="props.row.status" />
              </q-td>
            </template>
            <template #body-cell-progress="props">
              <q-td :props="props" style="min-width: 160px">
                <template v-if="props.row.status === 'running'">
                  <q-linear-progress :value="(props.row.progress_json?.percent ?? 0) / 100" rounded size="10px" color="blue" />
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
            <q-chip dense square :color="statusColor[selected.status]" text-color="white" :label="selected.status" />
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
                <div><b>Base Model:</b> {{ selected.base_model_id }}</div>
                <div><b>Klassen:</b> {{ (selected.class_names ?? []).map((n) => classes.info(n).label).join(', ') }}</div>
                <div><b>Auflösung:</b> {{ selected.input_width }}×{{ selected.input_height }}</div>
                <div><b>Epochs / Batch:</b> {{ selected.epochs }} / {{ selected.batch_size }}</div>
                <div><b>Learning Rate:</b> {{ selected.learning_rate ?? 'auto' }}</div>
                <div><b>Dataset-Snapshot:</b> <span class="mono">{{ selected.dataset_snapshot ?? '–' }}</span></div>
              </div>
              <div class="col-12 col-sm-6">
                <div><b>Erstellt:</b> {{ fmtDate(selected.created_at) }}</div>
                <div><b>Gestartet:</b> {{ fmtDate(selected.started_at) }}</div>
                <div><b>Beendet:</b> {{ fmtDate(selected.finished_at) }}</div>
                <div v-if="selected.progress_json?.phase"><b>Phase:</b> {{ selected.progress_json.phase }} {{ progressText(selected) }}</div>
                <div v-if="selected.dataset_stats_json">
                  <b>Daten:</b>
                  train {{ selected.dataset_stats_json.train?.images }} Bilder / {{ selected.dataset_stats_json.train?.boxes }} Boxen,
                  val {{ selected.dataset_stats_json.validation?.images }} / {{ selected.dataset_stats_json.validation?.boxes }}
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
              color="blue"
            >
              <div class="absolute-full flex flex-center text-caption text-white">{{ selected.progress_json?.percent ?? 0 }} %</div>
            </q-linear-progress>
            <div v-if="selected.error" class="text-negative q-mt-sm mono text-caption">{{ selected.error }}</div>
          </q-card-section>
          <q-card-section v-if="valHistory.length" class="q-pt-none">
            <div class="text-subtitle2">Validierung während des Trainings (MMDetection, COCO-mAP)</div>
            <div class="row q-gutter-xs text-caption">
              <q-chip v-for="v in valHistory" :key="v.epoch" dense square>
                E{{ v.epoch }}: {{ fmtPct(v.bbox_mAP) }} / {{ fmtPct(v.bbox_mAP_50) }}
              </q-chip>
            </div>
          </q-card-section>
          <q-card-section v-if="selected.metrics_json" class="q-pt-none">
            <div class="text-subtitle2 q-mb-xs">Metriken des exportierten Modells</div>
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
import MetricsTable from '@/components/MetricsTable.vue'
import { api, errorMessage, fmtDate, fmtPct, type BaseModelOption, type DatasetStats, type TrainingEligibility, type TrainingRun } from '@/services/api'
import { useClassesStore } from '@/stores/classes'
import { useModelsStore } from '@/stores/models'

const $q = useQuasar()
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

const statusColor: Record<string, string> = { queued: 'grey-7', running: 'blue-7', completed: 'green-7', failed: 'red-7' }
const columns: QTableColumn<TrainingRun>[] = [
  { name: 'id', label: '#', field: 'id', align: 'left', sortable: true },
  { name: 'status', label: 'Status', field: 'status', align: 'left' },
  { name: 'base', label: 'Base', field: 'base_model_id', align: 'left' },
  { name: 'classes', label: 'Klassen', field: (r) => (r.class_names ?? []).join(', '), align: 'left' },
  { name: 'res', label: 'Auflösung', field: (r) => `${r.input_width}×${r.input_height}`, align: 'left' },
  { name: 'epochs', label: 'Epochs', field: 'epochs' },
  { name: 'map', label: 'mAP50', field: (r) => fmtPct(r.metrics_json?.overall?.mAP50) },
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

let timer: number | undefined
onMounted(async () => {
  await Promise.all([models.refresh(), classes.refresh()])
  form.input_size = models.defaultInputSize
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
onBeforeUnmount(() => window.clearInterval(timer))
</script>
