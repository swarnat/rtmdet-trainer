<template>
  <q-page padding>
    <q-card v-if="form" flat bordered style="max-width: 900px">
      <q-card-section>
        <div class="text-h6">Einstellungen</div>
        <div class="text-caption text-grey-7">In PostgreSQL gespeichert (Tabelle „settings“), wirksam ohne Neustart.</div>
      </q-card-section>
      <q-card-section class="column q-gutter-md">
        <div class="text-subtitle2">Inferenz</div>
        <div class="row q-col-gutter-md">
          <q-select v-model="form.default_input_size" :options="form.input_sizes" outlined dense label="Standard-Eingangsauflösung" class="col-12 col-sm-4" />
          <q-select
            v-model="form.input_sizes"
            multiple
            use-chips
            use-input
            new-value-mode="add-unique"
            hide-dropdown-icon
            outlined
            dense
            label="Angebotene Auflösungen (B×H, Vielfache von 32)"
            class="col-12 col-sm-8"
          />
          <q-input v-model.number="form.default_confidence" type="number" step="0.05" outlined dense label="Standard-Confidence" class="col-6 col-sm-4" />
          <q-input v-model.number="form.nms_iou_threshold" type="number" step="0.05" outlined dense label="NMS-IoU" class="col-6 col-sm-4" />
        </div>
        <div class="text-subtitle2">Dataset &amp; Evaluation</div>
        <div class="row q-col-gutter-md">
          <q-input
            v-model.number="form.validation_ratio"
            type="number"
            step="0.05"
            outlined
            dense
            label="Validierungsanteil für neue Bilder"
            hint="bestehende Zuordnungen bleiben unverändert"
            class="col-6 col-sm-4"
          />
          <q-input v-model.number="form.eval_confidence" type="number" step="0.05" outlined dense label="Confidence für Precision/Recall" class="col-6 col-sm-4" />
        </div>
        <div class="text-subtitle2">Klassen-Mapping COCO → eigene Klassen</div>
        <div class="text-caption text-grey-7">
          Verwendet für das importierte COCO-Basismodell und zur Initialisierung des Klassifikationskopfs beim Training ab COCO. Nach einer Änderung
          unter „Modelle“ das COCO-Basismodell neu importieren. Züge sind bewusst nicht als Fahrzeug zugeordnet.
        </div>
        <div v-for="c in CLASSES" :key="c.name" class="row items-center q-col-gutter-sm">
          <div class="col-12 col-sm-2"><span class="class-dot" :style="{ background: c.color }" />{{ c.label }}</div>
          <q-select
            v-model="form.coco_class_mapping[c.name]"
            :options="COCO_CLASSES"
            multiple
            use-chips
            outlined
            dense
            class="col-12 col-sm-10"
          />
        </div>
      </q-card-section>
      <q-card-actions align="right">
        <q-btn flat no-caps label="Standardwerte" @click="resetDefaults" />
        <q-btn color="primary" icon="save" label="Speichern" :loading="saving" @click="save" />
      </q-card-actions>
    </q-card>
  </q-page>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useQuasar } from 'quasar'
import { api, CLASSES, errorMessage, type Settings } from '@/services/api'
import { COCO_CLASSES } from '@/constants'
import { useModelsStore } from '@/stores/models'

const $q = useQuasar()
const models = useModelsStore()
const form = ref<Settings | null>(null)
const defaults = ref<Settings | null>(null)
const saving = ref(false)

async function load() {
  const res = await api.getSettings()
  form.value = structuredClone(res.values)
  defaults.value = res.defaults
}

function resetDefaults() {
  if (defaults.value) form.value = structuredClone(defaults.value)
}

async function save() {
  if (!form.value) return
  saving.value = true
  try {
    const res = await api.updateSettings(form.value)
    form.value = structuredClone(res.values)
    await models.refresh()
    $q.notify({ type: 'positive', message: 'Einstellungen gespeichert' })
  } catch (e) {
    $q.notify({ type: 'negative', message: errorMessage(e) })
  } finally {
    saving.value = false
  }
}

onMounted(load)
</script>
