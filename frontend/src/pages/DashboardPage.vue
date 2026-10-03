<template>
  <q-page padding>
    <div class="row q-col-gutter-md">
      <div v-for="card in cards" :key="card.label" class="col-6 col-md-3">
        <q-card flat bordered>
          <q-card-section>
            <div class="text-caption text-grey-7">{{ card.label }}</div>
            <div class="text-h4">{{ card.value }}</div>
            <div class="text-caption">{{ card.hint }}</div>
          </q-card-section>
        </q-card>
      </div>

      <div class="col-12 col-md-6">
        <q-card flat bordered class="full-height">
          <q-card-section>
            <div class="text-h6">Production-Modell</div>
            <template v-if="models.production">
              <div class="text-body2">
                <b>{{ models.production.version }}</b> ·
                {{ models.production.kind === 'coco-bootstrap' ? 'COCO-pretrained (nicht nachtrainiert)' : 'eigenes Training' }} ·
                {{ models.production.input_width }}×{{ models.production.input_height }} · aktiviert {{ fmtDate(models.production.activated_at) }}
              </div>
              <MetricsTable class="q-mt-sm" :metrics="models.production.metrics_json" />
            </template>
            <div v-else class="text-grey-7">
              Noch kein Production-Modell. Der Trainer importiert beim ersten Start automatisch das COCO-pretrained RTMDet-S, oder aktiviere eine
              Version unter <router-link to="/models">Modelle</router-link>.
            </div>
          </q-card-section>
        </q-card>
      </div>

      <div class="col-12 col-md-6">
        <q-card flat bordered class="full-height">
          <q-card-section>
            <div class="text-h6">Annotationen pro Klasse</div>
            <div v-for="c in classRows" :key="c.name" class="q-my-sm">
              <div class="row text-body2">
                <span class="class-dot" :style="{ background: c.color, marginTop: '5px' }" />{{ c.label }}
                <q-space />{{ stats?.annotations_per_class[c.name] ?? 0 }}
                <span v-if="stats?.hard_negatives_per_class?.[c.name]" class="text-grey-7 q-ml-sm">
                  + {{ stats.hard_negatives_per_class[c.name] }} HN
                </span>
              </div>
              <q-linear-progress :value="classShare(c.name)" :style="{ color: c.color }" track-color="grey-3" rounded size="8px" />
            </div>
            <div class="text-caption text-grey-7 q-mt-md">
              Split: {{ stats?.splits.train ?? 0 }} train / {{ stats?.splits.validation ?? 0 }} validation (fest pro Bild zugeordnet)
            </div>
          </q-card-section>
        </q-card>
      </div>

      <div class="col-12">
        <q-card flat bordered>
          <q-card-section class="row items-center q-gutter-md">
            <div class="text-h6">Schnelltest <span class="text-caption mono">POST /api/v1/detect</span></div>
            <q-space />
            <ModelSelector v-model="opts.model" style="min-width: 260px" />
            <q-select v-model="opts.input_size" :options="models.inputSizes" dense outlined label="Auflösung" style="min-width: 140px" />
            <div style="width: 180px">
              <div class="text-caption">Confidence {{ opts.confidence.toFixed(2) }}</div>
              <q-slider v-model="opts.confidence" :min="0.05" :max="0.95" :step="0.05" dense />
            </div>
            <q-file v-model="file" dense outlined accept="image/*" label="Bild wählen" style="min-width: 220px" @update:model-value="detect">
              <template #prepend><q-icon name="image" /></template>
            </q-file>
            <q-btn color="primary" icon="search" label="Erkennen" :disable="!file" :loading="detecting" @click="detect" />
          </q-card-section>
          <q-card-section v-if="result && preview" class="row q-col-gutter-md">
            <div class="col-12 col-md-8">
              <DetectionOverlay :src="preview" :result="result" />
            </div>
            <div class="col-12 col-md-4">
              <div class="text-body2 q-mb-sm">
                {{ result.model.version }} · {{ result.model.input_width }}×{{ result.model.input_height }} · {{ result.inference_ms.toFixed(0) }} ms ·
                {{ result.detections.length }} Treffer. Das Bild wurde nicht gespeichert.
              </div>
              <pre class="log-view" style="max-height: 420px">{{ JSON.stringify(result, null, 2) }}</pre>
            </div>
          </q-card-section>
        </q-card>
      </div>
    </div>
  </q-page>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { useQuasar } from 'quasar'
import DetectionOverlay from '@/components/DetectionOverlay.vue'
import MetricsTable from '@/components/MetricsTable.vue'
import ModelSelector from '@/components/ModelSelector.vue'
import { api, errorMessage, fmtDate, type DatasetStats, type DetectResponse } from '@/services/api'
import { useClassesStore } from '@/stores/classes'
import { useModelsStore } from '@/stores/models'

const $q = useQuasar()
const models = useModelsStore()
const classes = useClassesStore()
// all classes that are active or still have boxes
const classRows = computed(() =>
  classes.all.filter((c) => c.active || (stats.value?.annotations_per_class[c.name] ?? 0) > 0).map((c) => classes.info(c.name)),
)
const stats = ref<DatasetStats | null>(null)
const file = ref<File | null>(null)
const preview = ref<string | null>(null)
const result = ref<DetectResponse | null>(null)
const detecting = ref(false)
const opts = reactive({ model: 'production', input_size: '1536x864', confidence: 0.25 })

const cards = computed(() => [
  { label: 'Trainingsbilder', value: stats.value?.images_total ?? '–', hint: 'in Garage S3' },
  { label: 'Annotiert', value: stats.value?.images_labeled ?? '–', hint: `davon ${stats.value?.images_negative ?? 0} negativ (ohne Objekte)` },
  {
    label: 'Offen',
    value: stats.value?.images_unlabeled ?? '–',
    hint: `noch nicht bearbeitet · ${stats.value?.images_needs_review ?? 0} nachzuprüfen (neue Klassen)`,
  },
  { label: 'Modellversionen', value: models.versions.length, hint: `${models.versions.filter((m) => m.status === 'candidate').length} Candidates` },
])

function classShare(name: string) {
  const counts = stats.value?.annotations_per_class ?? {}
  const max = Math.max(1, ...Object.values(counts))
  return (counts[name] ?? 0) / max
}

watch(
  () => models.settings,
  (s) => {
    if (s) {
      opts.input_size = s.default_input_size
      opts.confidence = s.default_confidence
    }
  },
  { immediate: true },
)

async function detect() {
  if (!file.value) return
  detecting.value = true
  try {
    result.value = await api.detectUpload(file.value, opts)
    if (preview.value) URL.revokeObjectURL(preview.value)
    preview.value = URL.createObjectURL(file.value)
  } catch (e) {
    $q.notify({ type: 'negative', message: errorMessage(e) })
  } finally {
    detecting.value = false
  }
}

onMounted(async () => {
  try {
    stats.value = await api.datasetStats()
    await models.refresh()
  } catch (e) {
    $q.notify({ type: 'negative', message: errorMessage(e) })
  }
})
onBeforeUnmount(() => preview.value && URL.revokeObjectURL(preview.value))
</script>
