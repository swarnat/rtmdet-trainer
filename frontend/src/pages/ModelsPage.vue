<template>
  <q-page padding>
    <q-card flat bordered>
      <q-card-section class="row items-center q-gutter-sm">
        <div class="text-h6">Modellversionen</div>
        <div class="text-caption text-muted">
          Versionen sind unveränderlich. Aktivieren wirkt sofort für <span class="mono">/detect</span>; die bisherige Production-Version wird archiviert
          und kann jederzeit wieder aktiviert werden (Rollback).
        </div>
        <q-space />
        <q-chip v-if="deployment?.model" dense outline color="primary" icon="cloud_done">
          Produktivsystem: {{ deployment.model.version }}
        </q-chip>
        <q-chip v-else-if="deployment?.configured" dense outline :color="deployment.reachable ? 'grey-5' : 'negative'" icon="cloud_off">
          {{ deployment.reachable ? 'Produktivsystem: kein Modell' : 'Produktivsystem nicht erreichbar' }}
          <q-tooltip v-if="deployment.error">{{ deployment.error }}</q-tooltip>
        </q-chip>
        <q-chip v-else dense outline color="grey-5" icon="cloud_off" clickable @click="$router.push('/settings')">
          Produktivsystem nicht eingerichtet
          <q-tooltip>URL und Access Key unter Einstellungen → Produktivsystem eintragen</q-tooltip>
        </q-chip>
        <q-chip v-if="deployment?.warnings?.length" dense outline color="warning" icon="warning">
          Warnung Produktivsystem
          <q-tooltip max-width="420px">{{ deployment.warnings.join(' ') }}</q-tooltip>
        </q-chip>
        <HelpIcon term="productionSystem" inline class="q-mr-sm" />
        <q-btn outline no-caps icon="download_for_offline" label="COCO-Basismodell importieren" @click="bootstrap" />
        <q-btn flat round dense icon="refresh" @click="models.refresh(); loadDeployment()" />
      </q-card-section>
      <q-table :rows="models.versions" :columns="columns" row-key="version" flat dense :loading="models.loading" :pagination="{ rowsPerPage: 20 }">
        <template #header-cell="props">
          <q-th :props="props">
            {{ props.col.label }}<HelpIcon v-if="columnHelp[props.col.name]" :term="columnHelp[props.col.name]" inline />
          </q-th>
        </template>
        <template #body-cell-status="props">
          <q-td :props="props">
            <q-chip dense outline :color="statusColor[props.row.status]" :label="props.row.status" />
            <q-chip v-if="deployment?.model?.version === props.row.version" dense outline color="primary" icon="cloud_done" label="live">
              <q-tooltip>Ist auf dem Produktivsystem aktiv</q-tooltip>
            </q-chip>
          </q-td>
        </template>
        <template #body-cell-actions="props">
          <q-td :props="props" class="actions-cell">
            <q-btn
              v-if="props.row.status !== 'production'"
              dense
              unelevated
              no-caps
              color="positive"
              icon="rocket_launch"
              :label="props.row.status === 'archived' ? 'Rollback' : 'Aktivieren'"
              class="q-px-sm"
              @click="activate(props.row)"
            >
              <q-tooltip>Als Production aktivieren – wird sofort für alle Erkennungen benutzt</q-tooltip>
            </q-btn>
            <q-btn v-if="props.row.status === 'candidate'" dense flat round icon="archive" @click="archive(props.row)">
              <q-tooltip>Archivieren</q-tooltip>
            </q-btn>
            <q-btn
              dense
              flat
              round
              color="primary"
              icon="cloud_upload"
              :disable="!deployment?.configured"
              :loading="deploying === props.row.version"
              @click="deploy(props.row)"
            >
              <q-tooltip>{{ deployment?.configured ? 'Auf das Produktivsystem ausrollen' : 'Produktivsystem unter Einstellungen einrichten' }}</q-tooltip>
            </q-btn>
            <q-btn dense flat round icon="info" @click="detail = props.row"><q-tooltip>Details</q-tooltip></q-btn>
            <q-btn v-if="props.row.status !== 'production'" dense flat round color="negative" icon="delete" @click="remove(props.row)">
              <q-tooltip>Löschen</q-tooltip>
            </q-btn>
          </q-td>
        </template>
      </q-table>
    </q-card>

    <q-dialog :model-value="!!detail" @update:model-value="(v) => !v && (detail = null)">
      <q-card v-if="detail" style="width: 900px; max-width: 95vw">
        <q-card-section class="row items-center q-gutter-sm">
          <div class="text-h6">{{ detail.version }}</div>
          <q-chip dense outline :color="statusColor[detail.status]" :label="detail.status" />
          <HelpIcon term="status" inline />
          <q-space />
          <q-btn flat round dense icon="close" v-close-popup />
        </q-card-section>
        <q-card-section class="q-pt-none text-body2">
          <div class="row q-col-gutter-md">
            <div class="col-12 col-sm-6">
              <div><b>Art<HelpIcon term="kind" inline />:</b> {{ detail.kind === 'coco-bootstrap' ? 'COCO-pretrained (nicht nachtrainiert)' : 'eigenes Training' }}</div>
              <div><b>Architektur<HelpIcon term="architecture" inline />:</b> {{ detail.architecture }}</div>
              <div><b>Trainingsauflösung<HelpIcon term="resolution" inline />:</b> {{ detail.input_width }}×{{ detail.input_height }}</div>
              <div><b>Klassen:</b> {{ detail.class_names.map((n) => classes.info(n).label).join(', ') }}</div>
              <div v-if="detail.metrics_json?.head_init">
                <b>Initialisierung Klassifikationskopf<HelpIcon term="headInit" inline />:</b>
                {{ Object.entries(detail.metrics_json.head_init).map(([k, v]) => `${k}: ${v}`).join('; ') }}
              </div>
              <div v-if="detail.class_mapping_json"><b>COCO-Mapping<HelpIcon term="cocoMapping" inline />:</b> {{ mappingText(detail.class_mapping_json) }}</div>
            </div>
            <div class="col-12 col-sm-6">
              <div><b>Erstellt:</b> {{ fmtDate(detail.created_at) }}</div>
              <div><b>Zuletzt aktiviert:</b> {{ fmtDate(detail.activated_at) }}</div>
              <div><b>Trainingslauf:</b> {{ detail.training_run_id ? `#${detail.training_run_id}` : '–' }}</div>
              <div><b>Dataset-Snapshot<HelpIcon term="datasetSnapshot" inline />:</b> <span class="mono">{{ detail.dataset_snapshot ?? '–' }}</span></div>
            </div>
          </div>
          <q-input v-model="notes" dense outlined autogrow label="Notizen" class="q-mt-md">
            <template #after><q-btn dense flat icon="save" @click="saveNotes" /></template>
          </q-input>
        </q-card-section>
        <q-card-section class="q-pt-none">
          <div class="text-subtitle2 q-mb-xs">Metriken</div>
          <MetricsTable :metrics="detail.metrics_json" />
        </q-card-section>
        <q-card-section class="q-pt-none">
          <div class="text-subtitle2 q-mb-xs">Artefakte (Garage S3, Bucket „models“)<HelpIcon term="artifacts" inline /></div>
          <div class="q-gutter-sm">
            <q-btn v-for="a in artifacts" :key="a.id" outline dense no-caps icon="download" :label="a.label" :href="api.artifactUrl(detail.version, a.id)" />
          </div>
        </q-card-section>
      </q-card>
    </q-dialog>
  </q-page>
</template>

<script setup lang="ts">
import { onMounted, ref, watch } from 'vue'
import { useQuasar, type QTableColumn } from 'quasar'
import HelpIcon from '@/components/HelpIcon.vue'
import MetricsTable from '@/components/MetricsTable.vue'
import type { GlossaryTerm } from '@/glossary'
import { api, errorMessage, fmtDate, fmtPct, type CocoBaseModel, type DeploymentStatus, type ModelVersion } from '@/services/api'
import { useClassesStore } from '@/stores/classes'
import { useModelsStore } from '@/stores/models'

const $q = useQuasar()
const models = useModelsStore()
const classes = useClassesStore()
const detail = ref<ModelVersion | null>(null)
const notes = ref('')
const deployment = ref<DeploymentStatus | null>(null)
const deploying = ref<string | null>(null)

async function loadDeployment() {
  try {
    deployment.value = await api.deploymentStatus()
  } catch {
    deployment.value = null
  }
}

function deploy(m: ModelVersion) {
  const current = deployment.value?.model?.version
  $q.dialog({
    title: `${m.version} ausrollen`,
    message:
      `${m.version} wird auf das Produktivsystem (${deployment.value?.url}) übertragen und ersetzt dort ` +
      `${current ? `das aktive Modell ${current}` : 'das aktive Modell'}, sobald es erfolgreich geprüft wurde. ` +
      'Schlägt die Prüfung fehl, bleibt das bisherige Modell aktiv. Der Status „production“ hier im System ändert sich dadurch nicht.',
    cancel: { label: 'Abbrechen', flat: true },
    ok: { label: 'Ausrollen', color: 'primary' },
  }).onOk(async () => {
    deploying.value = m.version
    try {
      await api.deployModel(m.version)
      $q.notify({ type: 'positive', message: `${m.version} ist jetzt auf dem Produktivsystem aktiv` })
    } catch (e) {
      $q.notify({ type: 'negative', message: errorMessage(e), timeout: 8000 })
    } finally {
      deploying.value = null
      await loadDeployment()
    }
  })
}

const statusColor: Record<string, string> = { production: 'positive', candidate: 'primary', archived: 'grey-5' }
const artifacts = [
  { id: 'checkpoint', label: 'PyTorch-Checkpoint' },
  { id: 'onnx', label: 'ONNX' },
  { id: 'openvino-xml', label: 'OpenVINO .xml' },
  { id: 'openvino-bin', label: 'OpenVINO .bin' },
  { id: 'config', label: 'Training-Config' },
]
const columns: QTableColumn<ModelVersion>[] = [
  { name: 'version', label: 'Version', field: 'version', align: 'left', sortable: true },
  { name: 'status', label: 'Status', field: 'status', align: 'left' },
  { name: 'arch', label: 'Architektur', field: 'architecture', align: 'left' },
  { name: 'kind', label: 'Art', field: (m) => (m.kind === 'coco-bootstrap' ? 'COCO' : 'trainiert'), align: 'left' },
  { name: 'classes', label: 'Klassen', field: (m) => m.class_names.join(', '), align: 'left' },
  { name: 'res', label: 'Auflösung', field: (m) => `${m.input_width}×${m.input_height}`, align: 'left' },
  { name: 'p', label: 'Precision', field: (m) => fmtPct(m.metrics_json?.overall?.precision) },
  { name: 'r', label: 'Recall', field: (m) => fmtPct(m.metrics_json?.overall?.recall) },
  { name: 'map50', label: 'mAP50', field: (m) => fmtPct(m.metrics_json?.overall?.mAP50) },
  { name: 'map', label: 'mAP50-95', field: (m) => fmtPct(m.metrics_json?.overall?.['mAP50-95']) },
  { name: 'created', label: 'Erstellt', field: (m) => fmtDate(m.created_at), align: 'left' },
  { name: 'actions', label: '', field: 'id', align: 'right' },
]

const columnHelp: Record<string, GlossaryTerm> = {
  status: 'status',
  arch: 'architecture',
  kind: 'kind',
  res: 'resolution',
  p: 'precision',
  r: 'recall',
  map50: 'mAP50',
  map: 'mAP5095',
}

watch(detail, (d) => (notes.value = d?.notes ?? ''))

function mappingText(m: Record<string, string[]>) {
  return Object.entries(m)
    .map(([k, v]) => `${k} ← ${v.join(', ')}`)
    .join('; ')
}

function activate(m: ModelVersion) {
  $q.dialog({
    title: 'Als Production aktivieren',
    message: `${m.version} wird sofort für alle /detect-Anfragen verwendet. ${models.production ? `${models.production.version} wird archiviert.` : ''}`,
    cancel: { label: 'Abbrechen', flat: true },
    ok: { label: 'Aktivieren', color: 'positive' },
  }).onOk(async () => {
    try {
      await api.activateModel(m.version)
      $q.notify({ type: 'positive', message: `${m.version} ist jetzt Production` })
      await models.refresh()
    } catch (e) {
      $q.notify({ type: 'negative', message: errorMessage(e) })
    }
  })
}

async function archive(m: ModelVersion) {
  try {
    await api.archiveModel(m.version)
    await models.refresh()
  } catch (e) {
    $q.notify({ type: 'negative', message: errorMessage(e) })
  }
}

function remove(m: ModelVersion) {
  $q.dialog({
    title: `${m.version} löschen`,
    message:
      `${m.version} und alle zugehörigen Dateien (ONNX, OpenVINO, Checkpoint, Metriken) werden endgültig gelöscht. ` +
      'Das lässt sich nicht rückgängig machen. Trainingsläufe bleiben in der Liste, verlieren aber den Verweis auf das Modell; ' +
      'der Datenstand ihres Trainings (Snapshot) wird freigegeben. ' +
      'Bilder und Annotationen der Bibliothek sind nicht betroffen; bereits gelöschte Bilder, die nur noch dieses Modell ' +
      'verwendet hat, werden jetzt endgültig entfernt.',
    cancel: { label: 'Abbrechen', flat: true },
    ok: { label: 'Endgültig löschen', color: 'negative' },
  }).onOk(async () => {
    try {
      await api.deleteModel(m.version)
      if (detail.value?.version === m.version) detail.value = null
      $q.notify({ type: 'positive', message: `${m.version} gelöscht` })
      await models.refresh()
    } catch (e) {
      $q.notify({ type: 'negative', message: errorMessage(e) })
    }
  })
}

async function saveNotes() {
  if (!detail.value) return
  try {
    detail.value = await api.updateModelNotes(detail.value.version, notes.value)
    await models.refresh()
    $q.notify({ type: 'positive', message: 'Notizen gespeichert', timeout: 1200 })
  } catch (e) {
    $q.notify({ type: 'negative', message: errorMessage(e) })
  }
}

async function bootstrap() {
  let bases: CocoBaseModel[] = []
  try {
    bases = await api.cocoBaseModels()
  } catch (e) {
    $q.notify({ type: 'negative', message: errorMessage(e) })
    return
  }
  $q.dialog({
    title: 'COCO-Basismodell importieren',
    message:
      'Exportiert einen COCO-pretrained RTMDet-Checkpoint als neue Modellversion (ohne Training), z. B. um eine andere Modellgröße ' +
      'mit „Modell testen“ auf den vorhandenen Bildern auszuprobieren. Enthalten sind alle aktiven Klassen mit COCO-Mapping. ' +
      'Annotationen bleiben unverändert.',
    options: {
      type: 'radio',
      model: models.production?.architecture ? `${models.production.architecture}-coco` : 'rtmdet-s-coco',
      items: bases.map((b) => ({ label: `${b.label} – COCO AP ${b.coco_ap}, ${b.params_m} M Parameter`, value: b.id })),
    },
    cancel: { label: 'Abbrechen', flat: true },
    ok: { label: 'Importieren' },
  }).onOk(async (baseModel: string) => {
    try {
      await api.bootstrapModel(true, baseModel)
      $q.notify({ type: 'info', message: 'Import im Trainer eingereiht – die neue Version erscheint in 1–2 Minuten (erster Download des Checkpoints).' })
    } catch (e) {
      $q.notify({ type: 'negative', message: errorMessage(e) })
    }
  })
}

onMounted(() => {
  models.refresh()
  loadDeployment()
})
</script>

<style scoped>
.actions-cell {
  white-space: nowrap;
}
.actions-cell > .q-btn + .q-btn {
  margin-left: 4px;
}
</style>
