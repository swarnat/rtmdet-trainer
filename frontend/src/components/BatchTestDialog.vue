<template>
  <q-dialog :model-value="modelValue" @update:model-value="(v) => emit('update:modelValue', v)">
    <q-card style="width: 560px; max-width: 95vw">
      <q-card-section class="row items-center">
        <div class="text-h6">Batch-Test<HelpIcon term="batchTest" inline /></div>
        <q-space />
        <q-btn flat round dense icon="close" v-close-popup />
      </q-card-section>
      <q-card-section class="q-pt-none text-body2 text-muted">
        Testet ein Modell einmal auf allen offenen Bildern und speichert die Erkennungen als <b>Vorschläge</b>. Beim Öffnen eines Bildes
        erscheinen sie als Predictions zum Übernehmen oder als Hard Negative markieren. Annotationen werden nicht verändert; vorhandene
        Vorschläge der betroffenen Bilder werden ersetzt.
      </q-card-section>

      <q-card-section v-if="active" class="q-pt-none">
        <div class="text-subtitle2">
          Läuft: #{{ active.id }} · {{ active.model_version }} · {{ active.input_width }}×{{ active.input_height }} · ≥ {{ active.confidence }}
        </div>
        <q-linear-progress :value="active.total ? active.processed / active.total : 0" size="14px" rounded color="secondary" class="q-my-sm">
          <div class="absolute-full flex flex-center text-caption text-white">{{ active.processed }} / {{ active.total }}</div>
        </q-linear-progress>
        <div v-if="isErrorAnalysis(active)" class="text-caption">Fehleranalyse: {{ active.marked_images }} Bilder mit Fehlern bisher</div>
        <div v-else class="text-caption">{{ active.detections }} Vorschläge bisher<span v-if="active.failed_images">, {{ active.failed_images }} Fehler</span></div>
        <q-btn outline color="negative" icon="stop" label="Abbrechen" no-caps class="q-mt-sm" @click="cancel(active.id)" />
      </q-card-section>

      <q-card-section v-else class="q-pt-none column q-gutter-sm">
        <ModelSelector v-model="form.model" />
        <q-select v-model="form.input_size" :options="models.inputSizes" dense outlined label="Eingangsauflösung">
          <template #append><HelpIcon term="resolution" /></template>
        </q-select>
        <div>
          <div class="text-caption">Confidence-Threshold: {{ form.confidence.toFixed(2) }}<HelpIcon term="confidence" inline /></div>
          <q-slider v-model="form.confidence" :min="0.05" :max="0.95" :step="0.05" dense />
        </div>
        <q-list dense class="q-mx-none">
          <q-item v-for="o in scopeOptions" :key="o.value" tag="label" v-ripple dense class="q-px-none">
            <q-item-section avatar style="min-width: 36px">
              <q-radio v-model="form.scope" :val="o.value" dense />
            </q-item-section>
            <q-item-section>
              <q-item-label>{{ o.label }}</q-item-label>
              <q-item-label caption>{{ o.caption }}</q-item-label>
            </q-item-section>
          </q-item>
        </q-list>
        <q-btn color="secondary" icon="playlist_play" label="Batch-Test starten" no-caps :loading="starting" @click="start" />
      </q-card-section>

      <q-card-section v-if="history.length" class="q-pt-none">
        <div class="text-subtitle2 q-mb-xs">Letzte Batch-Tests</div>
        <q-markup-table dense flat bordered>
          <tbody>
            <tr v-for="b in history" :key="b.id">
              <td>#{{ b.id }}</td>
              <td>
                <q-chip dense outline :color="statusColor[b.status]" :label="b.status" />
              </td>
              <td>{{ b.model_version }}</td>
              <td>{{ b.processed }}/{{ b.total }} Bilder</td>
              <td v-if="isErrorAnalysis(b)">Fehleranalyse: {{ b.marked_images }} Bilder mit {{ b.detections }} Fehlern</td>
              <td v-else>{{ b.detections }} Vorschläge</td>
              <td class="text-caption">{{ fmtDate(b.finished_at ?? b.created_at) }}</td>
            </tr>
          </tbody>
        </q-markup-table>
      </q-card-section>
    </q-card>
  </q-dialog>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, reactive, ref, watch } from 'vue'
import { useQuasar } from 'quasar'
import ModelSelector from './ModelSelector.vue'
import HelpIcon from './HelpIcon.vue'
import { api, errorMessage, fmtDate, isErrorAnalysis, type BatchScope, type BatchTest } from '@/services/api'
import { useModelsStore } from '@/stores/models'

const props = defineProps<{ modelValue: boolean }>()
const emit = defineEmits<{ 'update:modelValue': [value: boolean]; finished: [batch: BatchTest]; running: [batch: BatchTest | null] }>()
const $q = useQuasar()
const models = useModelsStore()

const batches = ref<BatchTest[]>([])
const starting = ref(false)
const scopeOptions: { label: string; caption: string; value: BatchScope }[] = [
  { label: 'Offene Bilder', caption: 'alle noch nicht annotierten Bilder', value: 'unlabeled' },
  { label: 'Offene Bilder aus letztem Upload', caption: 'jüngste Upload-Sitzung (Pausen < 30 min)', value: 'unlabeled_last_upload' },
  { label: 'Offene + nachzuprüfende Bilder', caption: 'zusätzlich annotierte Bilder, die für neue Klassen zu prüfen sind', value: 'unlabeled_and_review' },
  { label: 'Offene, noch nicht getestete Bilder', caption: 'nur Bilder, auf denen noch kein Batch-Test lief', value: 'unlabeled_untested' },
]
const form = reactive<{ model: string; input_size: string; confidence: number; scope: BatchScope }>({
  model: 'production', input_size: '1536x864', confidence: 0.25, scope: 'unlabeled',
})
const statusColor: Record<string, string> = {
  queued: 'grey-5', running: 'secondary', completed: 'positive', failed: 'negative', cancelled: 'warning',
}

const active = computed(() => batches.value.find((b) => b.status === 'queued' || b.status === 'running') ?? null)
const history = computed(() => batches.value.filter((b) => b !== active.value).slice(0, 5))

watch(
  () => models.settings,
  (s) => {
    if (s) {
      form.input_size = s.default_input_size
      form.confidence = s.default_confidence
    }
  },
  { immediate: true },
)

let timer: number | undefined
async function refresh() {
  try {
    const wasActive = active.value
    batches.value = await api.listBatchTests()
    emit('running', active.value)
    if (wasActive && !active.value) {
      const done = batches.value.find((b) => b.id === wasActive.id)
      if (done) emit('finished', done)
    }
  } catch {
    /* polling: ignore transient errors */
  }
  window.clearTimeout(timer)
  // poll fast while a batch runs, slowly otherwise (status chip in the image browser)
  timer = window.setTimeout(refresh, active.value ? 1500 : props.modelValue ? 5000 : 15000)
}

async function start() {
  starting.value = true
  try {
    await api.startBatchTest({ model: form.model, input_size: form.input_size, confidence: form.confidence, scope: form.scope })
    await refresh()
  } catch (e) {
    $q.notify({ type: 'negative', message: errorMessage(e) })
  } finally {
    starting.value = false
  }
}

async function cancel(id: number) {
  try {
    await api.cancelBatchTest(id)
    await refresh()
  } catch (e) {
    $q.notify({ type: 'negative', message: errorMessage(e) })
  }
}

watch(() => props.modelValue, (open) => open && refresh())
refresh()
onBeforeUnmount(() => window.clearTimeout(timer))
</script>
