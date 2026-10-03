<template>
  <q-page padding>
    <q-card flat bordered>
      <q-card-section class="row items-center q-gutter-sm">
        <div class="text-h6">Modellversionen</div>
        <div class="text-caption text-grey-7">
          Versionen sind unveränderlich. Aktivieren wirkt sofort für <span class="mono">/detect</span>; die bisherige Production-Version wird archiviert
          und kann jederzeit wieder aktiviert werden (Rollback).
        </div>
        <q-space />
        <q-btn outline no-caps icon="download_for_offline" label="COCO-Basismodell importieren" @click="bootstrap" />
        <q-btn flat round dense icon="refresh" @click="models.refresh()" />
      </q-card-section>
      <q-table :rows="models.versions" :columns="columns" row-key="version" flat dense :loading="models.loading" :pagination="{ rowsPerPage: 20 }">
        <template #body-cell-status="props">
          <q-td :props="props">
            <q-chip dense square :color="statusColor[props.row.status]" text-color="white" :label="props.row.status" />
          </q-td>
        </template>
        <template #body-cell-actions="props">
          <q-td :props="props" class="q-gutter-xs">
            <q-btn
              v-if="props.row.status !== 'production'"
              dense
              unelevated
              no-caps
              color="green-7"
              icon="rocket_launch"
              :label="props.row.status === 'archived' ? 'Rollback / aktivieren' : 'Als Production aktivieren'"
              @click="activate(props.row)"
            />
            <q-btn v-if="props.row.status === 'candidate'" dense flat no-caps icon="archive" label="Archivieren" @click="archive(props.row)" />
            <q-btn dense flat no-caps icon="info" label="Details" @click="detail = props.row" />
          </q-td>
        </template>
      </q-table>
    </q-card>

    <q-dialog :model-value="!!detail" @update:model-value="(v) => !v && (detail = null)">
      <q-card v-if="detail" style="width: 900px; max-width: 95vw">
        <q-card-section class="row items-center q-gutter-sm">
          <div class="text-h6">{{ detail.version }}</div>
          <q-chip dense square :color="statusColor[detail.status]" text-color="white" :label="detail.status" />
          <q-space />
          <q-btn flat round dense icon="close" v-close-popup />
        </q-card-section>
        <q-card-section class="q-pt-none text-body2">
          <div class="row q-col-gutter-md">
            <div class="col-12 col-sm-6">
              <div><b>Art:</b> {{ detail.kind === 'coco-bootstrap' ? 'COCO-pretrained (nicht nachtrainiert)' : 'eigenes Training' }}</div>
              <div><b>Architektur:</b> {{ detail.architecture }}</div>
              <div><b>Trainingsauflösung:</b> {{ detail.input_width }}×{{ detail.input_height }}</div>
              <div><b>Klassen:</b> {{ detail.class_names.map((n) => classes.info(n).label).join(', ') }}</div>
              <div v-if="detail.metrics_json?.head_init">
                <b>Initialisierung Klassifikationskopf:</b>
                {{ Object.entries(detail.metrics_json.head_init).map(([k, v]) => `${k}: ${v}`).join('; ') }}
              </div>
              <div v-if="detail.class_mapping_json"><b>COCO-Mapping:</b> {{ mappingText(detail.class_mapping_json) }}</div>
            </div>
            <div class="col-12 col-sm-6">
              <div><b>Erstellt:</b> {{ fmtDate(detail.created_at) }}</div>
              <div><b>Zuletzt aktiviert:</b> {{ fmtDate(detail.activated_at) }}</div>
              <div><b>Trainingslauf:</b> {{ detail.training_run_id ? `#${detail.training_run_id}` : '–' }}</div>
              <div><b>Dataset-Snapshot:</b> <span class="mono">{{ detail.dataset_snapshot ?? '–' }}</span></div>
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
          <div class="text-subtitle2 q-mb-xs">Artefakte (Garage S3, Bucket „models“)</div>
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
import MetricsTable from '@/components/MetricsTable.vue'
import { api, errorMessage, fmtDate, fmtPct, type CocoBaseModel, type ModelVersion } from '@/services/api'
import { useClassesStore } from '@/stores/classes'
import { useModelsStore } from '@/stores/models'

const $q = useQuasar()
const models = useModelsStore()
const classes = useClassesStore()
const detail = ref<ModelVersion | null>(null)
const notes = ref('')

const statusColor: Record<string, string> = { production: 'green-7', candidate: 'blue-7', archived: 'grey-6' }
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
    ok: { label: 'Aktivieren', color: 'green-7' },
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

onMounted(() => models.refresh())
</script>
