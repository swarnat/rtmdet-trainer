<template>
  <q-page padding>
    <div class="row q-col-gutter-md">
      <div v-for="card in cards" :key="card.label" class="col-6 col-md-3">
        <q-card flat bordered class="full-height">
          <q-card-section>
            <div class="text-caption text-muted text-weight-medium q-mb-sm">
              {{ card.label }}<HelpIcon v-if="card.help" :term="card.help" inline />
            </div>
            <div class="text-h4">{{ card.value }}</div>
            <div class="text-caption text-muted">{{ card.hint }}</div>
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
            <div v-else class="text-muted">
              Noch kein Production-Modell. Der Trainer importiert beim ersten Start automatisch das COCO-pretrained RTMDet-S, oder aktiviere eine
              Version unter <router-link to="/models">Modelle</router-link>.
            </div>
          </q-card-section>
        </q-card>
      </div>

      <div class="col-12 col-md-6">
        <q-card flat bordered class="full-height">
          <q-card-section>
            <div class="text-h6">Annotationen pro Klasse<HelpIcon term="hn" inline /></div>
            <div v-for="c in classRows" :key="c.name" class="q-my-sm">
              <div class="row text-body2">
                <span class="class-dot" :style="{ background: c.color, marginTop: '5px' }" />{{ c.label }}
                <q-space />{{ stats?.annotations_per_class[c.name] ?? 0 }}
                <span v-if="stats?.hard_negatives_per_class?.[c.name]" class="text-muted q-ml-sm">
                  + {{ stats.hard_negatives_per_class[c.name] }} HN
                </span>
              </div>
              <q-linear-progress :value="classShare(c.name)" :style="{ color: c.color }" track-color="track" rounded size="8px" />
            </div>
            <div class="text-caption text-muted q-mt-md">
              Split: {{ stats?.splits.train ?? 0 }} train / {{ stats?.splits.validation ?? 0 }} validation (fest pro Bild zugeordnet)<HelpIcon term="split" inline />
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
            <q-select v-model="opts.input_size" :options="models.inputSizes" dense outlined label="Auflösung" style="min-width: 160px">
              <template #append><HelpIcon term="resolution" /></template>
            </q-select>
            <div style="width: 180px">
              <div class="text-caption">Confidence {{ opts.confidence.toFixed(2) }}<HelpIcon term="confidence" inline /></div>
              <q-slider v-model="opts.confidence" :min="0.05" :max="0.95" :step="0.05" dense />
            </div>
          </q-card-section>
          <q-card-section class="row items-center q-gutter-md q-pt-none">
            <q-file v-model="file" dense outlined accept="image/*" label="Bild wählen" style="min-width: 220px" @update:model-value="detect">
              <template #prepend><q-icon name="image" /></template>
            </q-file>
            <div class="text-muted">oder</div>
            <q-input
              v-model="url"
              dense
              outlined
              clearable
              label="Bild-URL (http/https)"
              class="col"
              style="min-width: 280px"
              @keyup.enter="detectFromUrl"
            >
              <template #prepend><q-icon name="link" /></template>
              <q-tooltip>Die API lädt das Bild selbst herunter – funktioniert auch für Kamera-URLs, die nur vom Server erreichbar sind.</q-tooltip>
            </q-input>
            <q-btn
              color="primary"
              icon="search"
              label="Erkennen"
              :disable="!file && !url?.trim()"
              :loading="detecting"
              @click="url?.trim() && !file ? detectFromUrl() : detect()"
            />
          </q-card-section>
          <q-card-section v-if="result && preview" class="row q-col-gutter-md">
            <div class="col-12 col-md-8">
              <DetectionOverlay :src="preview" :result="result" />
            </div>
            <div class="col-12 col-md-4">
              <div class="text-body2 q-mb-sm">
                {{ result.model.version }} · {{ result.model.input_width }}×{{ result.model.input_height }} · {{ result.inference_ms.toFixed(0) }} ms ·
                {{ result.detections.length }} Treffer. Das Bild wurde nicht gespeichert.
                <div v-if="source" class="text-caption text-muted ellipsis">Quelle: {{ source }}<q-tooltip>{{ source }}</q-tooltip></div>
              </div>
              <pre class="log-view" style="max-height: 420px">{{ JSON.stringify(resultJson, null, 2) }}</pre>
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
import HelpIcon from '@/components/HelpIcon.vue'
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
const url = ref<string | null>(stored('quicktest-url'))
const source = ref<string | null>(null)
// the response as /detect returns it (without the image of a URL test)
const resultJson = computed(() => {
  if (!result.value) return null
  const { image_data_url: _image, ...rest } = result.value as DetectResponse & { image_data_url?: string }
  return rest
})
const preview = ref<string | null>(null)
const result = ref<DetectResponse | null>(null)
const detecting = ref(false)
const opts = reactive({ model: 'production', input_size: '1536x864', confidence: 0.25 })

const cards = computed(() => [
  {
    label: 'Trainingsbilder',
    value: stats.value?.images_total ?? '–',
    hint: stats.value?.images_retained_for_snapshots
      ? `in Garage S3 · + ${stats.value.images_retained_for_snapshots} gelöschte, noch von Modellen verwendet`
      : 'in Garage S3',
  },
  { label: 'Annotiert', help: 'negative' as const, value: stats.value?.images_labeled ?? '–', hint: `davon ${stats.value?.images_negative ?? 0} negativ (ohne Objekte)` },
  {
    label: 'Offen',
    help: 'needsReview' as const,
    value: stats.value?.images_unlabeled ?? '–',
    hint: `noch nicht bearbeitet · ${stats.value?.images_needs_review ?? 0} nachzuprüfen (neue Klassen)`,
  },
  { label: 'Modellversionen', help: 'status' as const, value: models.versions.length, hint: `${models.versions.filter((m) => m.status === 'candidate').length} Candidates` },
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

function stored(key: string): string | null {
  try {
    return localStorage.getItem(key)
  } catch {
    return null
  }
}

function setPreview(src: string) {
  if (preview.value?.startsWith('blob:')) URL.revokeObjectURL(preview.value)
  preview.value = src
}

async function detectFromUrl() {
  const target = url.value?.trim()
  if (!target) return
  detecting.value = true
  try {
    const res = await api.detectUrl(target, opts)
    result.value = res
    setPreview(res.image_data_url)
    source.value = target
    file.value = null
    try {
      localStorage.setItem('quicktest-url', target) // e.g. a camera snapshot URL tested again and again
    } catch {
      /* storage unavailable */
    }
  } catch (e) {
    $q.notify({ type: 'negative', message: errorMessage(e) })
  } finally {
    detecting.value = false
  }
}

async function detect() {
  if (!file.value) return
  detecting.value = true
  try {
    result.value = await api.detectUpload(file.value, opts)
    setPreview(URL.createObjectURL(file.value))
    source.value = file.value.name
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
onBeforeUnmount(() => preview.value?.startsWith('blob:') && URL.revokeObjectURL(preview.value))
</script>
