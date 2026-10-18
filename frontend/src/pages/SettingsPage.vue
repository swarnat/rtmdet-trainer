<template>
  <q-page padding>
    <q-card v-if="form" flat bordered style="max-width: 900px">
      <q-card-section>
        <div class="text-h6">Einstellungen</div>
        <div class="text-caption text-muted">In PostgreSQL gespeichert (Tabelle „settings“), wirksam ohne Neustart.</div>
      </q-card-section>
      <q-card-section class="column q-gutter-md">
        <div class="text-subtitle2">Inferenz</div>
        <div class="row q-col-gutter-md">
          <q-select v-model="form.default_input_size" :options="form.input_sizes" outlined dense label="Standard-Eingangsauflösung" class="col-12 col-sm-4">
            <template #append><HelpIcon term="resolution" /></template>
          </q-select>
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
          >
            <template #append><HelpIcon text="Die Bildgrößen, die beim Testen und Trainieren zur Auswahl stehen. Neue Größe eintippen und Enter drücken. Breite und Höhe müssen durch 32 teilbar sein." /></template>
          </q-select>
          <q-input v-model.number="form.default_confidence" type="number" step="0.05" outlined dense label="Standard-Confidence" class="col-6 col-sm-4">
            <template #append><HelpIcon term="confidence" /></template>
          </q-input>
          <q-input v-model.number="form.nms_iou_threshold" type="number" step="0.05" outlined dense label="NMS-IoU" class="col-6 col-sm-4">
            <template #append><HelpIcon term="nmsIou" /></template>
          </q-input>
        </div>
        <div class="text-subtitle2">Training</div>
        <div class="row q-col-gutter-md">
          <q-select
            v-model="form.default_base_model"
            :options="baseOptions"
            emit-value
            map-options
            outlined
            dense
            label="Vorausgewähltes Basismodell"
            hint="Gilt für neue Trainingsläufe; Annotationen sind modellunabhängig"
            class="col-12 col-sm-6"
          >
            <template #append><HelpIcon term="base" /></template>
          </q-select>
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
          >
            <template #append><HelpIcon term="validationRatio" /></template>
          </q-input>
          <q-input v-model.number="form.eval_confidence" type="number" step="0.05" outlined dense label="Confidence für Precision/Recall" class="col-6 col-sm-4">
            <template #append><HelpIcon term="evalConfidence" /></template>
          </q-input>
        </div>
        <div class="text-subtitle2">Duplikate<HelpIcon term="duplicates" inline /></div>
        <div class="row q-col-gutter-md">
          <q-input
            v-model.number="form.duplicate_max_difference"
            type="number"
            step="0.01"
            outlined
            dense
            label="Max. Abweichung für Duplikate"
            hint="kleiner = strenger; wirkt ab der nächsten Prüfung"
            class="col-6 col-sm-4"
          />
        </div>
        <div class="text-subtitle2">Sichtung<HelpIcon term="review" inline /></div>
        <q-toggle
          v-model="form.camera_groups_use_metadata"
          label="Kameras anhand der Bild-Metadaten trennen (EXIF-Seriennummer, z. B. AXIS)"
        />
        <div class="text-caption text-muted">
          An: Bilder verschiedener Geräte landen nie in derselben Gruppe; innerhalb eines Geräts werden Tag, Nacht und Infrarot
          großzügig zusammengefasst. Bilder ohne Metadaten werden nur untereinander nach Bildinhalt gruppiert.
          Aus: Gruppierung nur nach Bildinhalt.
        </div>
        <div class="text-subtitle2">Hard Negatives<HelpIcon term="hardNegatives" inline /></div>
        <div class="text-caption text-muted">
          Für jedes Hard Negative eines Trainingsbildes wird ein Ausschnitt erzeugt: Box × Kontextfaktor je Seite, auf 16:9 erweitert,
          mindestens der angegebene Anteil der Bildbreite (verhindert zu starkes Hochskalieren im Training). Der Ausschnitt wird
          entsprechend oft ins Training aufgenommen (0 = keine Ausschnitte, nur Regressionstest).
        </div>
        <div class="row q-col-gutter-md">
          <q-input v-model.number="form.hard_negative_context_factor" type="number" step="0.5" outlined dense label="Kontextfaktor" class="col-4">
            <template #append><HelpIcon term="hnCrops" /></template>
          </q-input>
          <q-input v-model.number="form.hard_negative_min_crop_fraction" type="number" step="0.05" outlined dense label="Mindestbreite (Anteil)" class="col-4">
            <template #append><HelpIcon term="hnCrops" /></template>
          </q-input>
          <q-input v-model.number="form.hard_negative_oversample" type="number" step="1" outlined dense label="Oversampling" class="col-4">
            <template #append><HelpIcon term="hnCrops" /></template>
          </q-input>
        </div>
        <div class="text-subtitle2">Produktivsystem<HelpIcon term="productionSystem" inline /></div>
        <div class="row q-col-gutter-md items-start">
          <q-input
            v-model="form.deployment_url"
            outlined
            dense
            label="URL des Produktivsystems"
            placeholder="https://erkennung.example.com"
            class="col-12 col-sm-6"
          >
            <template #append><HelpIcon term="deploymentUrl" /></template>
          </q-input>
          <q-input
            v-model="form.deployment_access_key"
            outlined
            dense
            :type="showKey ? 'text' : 'password'"
            label="Access Key"
            autocomplete="new-password"
            class="col-12 col-sm-6"
            @focus="form.deployment_access_key === MASK && (form.deployment_access_key = '')"
            @blur="!form.deployment_access_key && keyStored && (form.deployment_access_key = MASK)"
          >
            <template #append>
              <q-icon v-if="form.deployment_access_key !== MASK" :name="showKey ? 'visibility_off' : 'visibility'" class="cursor-pointer" @click="showKey = !showKey" />
              <HelpIcon term="deploymentKey" />
            </template>
          </q-input>
        </div>
        <div class="row items-center q-gutter-sm">
          <q-btn outline no-caps icon="lan" label="Verbindung testen" :loading="testing" @click="testConnection">
            <q-tooltip>Nutzt die gespeicherten Werte – vorher speichern</q-tooltip>
          </q-btn>
          <span v-if="connection" class="text-body2" :class="connection.ok ? 'text-positive' : 'text-negative'">{{ connection.text }}</span>
        </div>
        <q-banner v-for="w in connection?.warnings ?? []" :key="w" dense rounded class="bg-amber-soft text-body2">
          <template #avatar><q-icon name="warning" color="warning" /></template>
          Das Produktivsystem meldet: {{ w }}
        </q-banner>
        <div class="text-subtitle2">Kunden-Annotationsdienst<HelpIcon term="clientAnnotator" inline /></div>
        <div class="row q-col-gutter-md items-start">
          <q-input v-model="form.client_annotator_url" outlined dense label="URL des Dienstes" placeholder="http://kundenserver:8200" class="col-12 col-sm-6">
            <template #append><HelpIcon term="clientAnnotator" /></template>
          </q-input>
          <q-input
            v-model="form.client_annotator_access_key"
            outlined
            dense
            :type="showClientKey ? 'text' : 'password'"
            label="Access Token"
            autocomplete="new-password"
            class="col-12 col-sm-6"
            @focus="form.client_annotator_access_key === MASK && (form.client_annotator_access_key = '')"
            @blur="!form.client_annotator_access_key && clientKeyStored && (form.client_annotator_access_key = MASK)"
          >
            <template #append>
              <q-icon v-if="form.client_annotator_access_key !== MASK" :name="showClientKey ? 'visibility_off' : 'visibility'" class="cursor-pointer" @click="showClientKey = !showClientKey" />
              <HelpIcon term="clientAnnotatorKey" />
            </template>
          </q-input>
          <q-input
            v-model="form.client_inference_url"
            outlined
            dense
            label="Inference-Server aus Sicht des Kundenservers"
            :placeholder="form.deployment_url || 'http://localhost:8100'"
            class="col-12 col-sm-6"
          >
            <template #append><HelpIcon term="clientInferenceUrl" /></template>
          </q-input>
        </div>
        <div class="row items-center q-gutter-sm">
          <q-btn outline no-caps icon="lan" label="Verbindung testen" :loading="clientTesting" @click="testClient">
            <q-tooltip>Nutzt die gespeicherten Werte – vorher speichern</q-tooltip>
          </q-btn>
          <q-btn outline no-caps icon="publish" label="Konfiguration übertragen" :loading="pushing" @click="pushClientConfig">
            <q-tooltip>Aktive Klassen, Inference-Server und Confidence an den Dienst senden (gespeicherte Werte)</q-tooltip>
          </q-btn>
          <span v-if="clientConnection" class="text-body2" :class="clientConnection.ok ? 'text-positive' : 'text-negative'">{{ clientConnection.text }}</span>
        </div>
        <div class="text-caption text-muted">
          Klassen und ihr COCO-Mapping werden unter <router-link to="/classes">Klassen</router-link> verwaltet.
        </div>
      </q-card-section>
      <q-card-actions align="right">
        <q-btn flat no-caps label="Standardwerte" @click="resetDefaults" />
        <q-btn color="primary" icon="save" label="Speichern" :loading="saving" @click="save" />
      </q-card-actions>
    </q-card>

    <!-- danger zone -->
    <q-card v-if="form" flat bordered class="danger-card q-mt-lg" style="max-width: 900px">
      <q-card-section>
        <div class="text-h6 text-negative">System zurücksetzen</div>
        <div class="text-body2 text-muted q-mt-xs">
          Löscht <b>alle Bilder</b> mit Annotationen und Vorschlägen, alle Trainingsläufe, Batch-Tests und Benchmarks sowie
          <b>alle eigenen Modelle</b> und setzt die <b>Kategorien auf Standard</b> zurück. Erhalten bleiben die Einstellungen
          (inkl. Produktivsystem und Kunden-Annotationsdienst), die Backups und das COCO-Grundmodell. Nicht rückgängig zu machen.
        </div>
      </q-card-section>
      <q-card-actions align="right">
        <q-btn outline color="negative" icon="restart_alt" label="System zurücksetzen …" no-caps @click="openReset" />
      </q-card-actions>
    </q-card>

    <q-dialog v-model="resetDialog" persistent>
      <q-card style="width: 560px; max-width: 95vw">
        <q-card-section class="row items-center no-wrap">
          <q-icon name="warning" color="negative" size="32px" class="q-mr-sm" />
          <div class="text-h6">System wirklich zurücksetzen?</div>
        </q-card-section>
        <q-card-section v-if="!resetInfo" class="row justify-center"><q-spinner size="32px" /></q-card-section>
        <template v-else>
          <q-card-section class="q-pt-none text-body2">
            <q-banner dense rounded class="bg-negative-soft q-mb-md">
              Diese Aktion löscht endgültig – sie kann <b>nicht rückgängig</b> gemacht werden.
              Vorher ein <router-link to="/backups">Backup erstellen</router-link>, um den Stand bei Bedarf wiederherzustellen.
            </q-banner>
            <div>Gelöscht werden:</div>
            <ul class="q-my-xs">
              <li><b>{{ resetInfo.images }}</b> Bilder mit <b>{{ resetInfo.annotations }}</b> Annotationen</li>
              <li><b>{{ resetInfo.training_runs }}</b> Trainingsläufe samt Dataset-Snapshots, alle Batch-Tests und Benchmarks</li>
              <li>
                <b>{{ resetInfo.models_deleted.length }}</b> Modelle<span v-if="resetInfo.models_deleted.length">: {{ resetInfo.models_deleted.join(', ') }}</span>
              </li>
              <li>alle Kategorien – danach gelten wieder: {{ resetInfo.classes.join(', ') }}</li>
            </ul>
            <div class="text-muted">
              Erhalten: Einstellungen, Backups<span v-if="resetInfo.models_kept.length">, COCO-Grundmodell {{ resetInfo.models_kept.join(', ') }}</span>.
              <span v-if="!resetInfo.models_kept.length">Das COCO-Grundmodell wird danach neu importiert (dauert einige Minuten).</span>
            </div>
            <q-banner v-if="resetInfo.blocked_by.length" dense rounded class="bg-amber-soft q-mt-md">
              Gerade nicht möglich: {{ resetInfo.blocked_by.join('; ') }}. Abwarten oder abbrechen und erneut versuchen.
            </q-banner>
          </q-card-section>
          <q-card-section class="q-pt-none">
            <q-input
              v-model="resetConfirm"
              outlined
              dense
              autofocus
              label="Zum Bestätigen „reset“ eingeben"
              :disable="!!resetInfo.blocked_by.length"
              @keyup.enter="resetConfirmed && runReset()"
            />
          </q-card-section>
        </template>
        <q-card-actions align="right">
          <q-btn flat no-caps label="Abbrechen" :disable="resetting" v-close-popup />
          <q-btn unelevated color="negative" icon="delete_forever" label="Endgültig zurücksetzen" no-caps
                 :loading="resetting" :disable="!resetConfirmed" @click="runReset" />
        </q-card-actions>
      </q-card>
    </q-dialog>
  </q-page>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useQuasar } from 'quasar'
import HelpIcon from '@/components/HelpIcon.vue'
import { api, errorMessage, fmtDate, type ResetPreview, type Settings } from '@/services/api'
import { useClassesStore } from '@/stores/classes'
import { useModelsStore } from '@/stores/models'

const $q = useQuasar()
const models = useModelsStore()
const form = ref<Settings | null>(null)
const defaults = ref<Settings | null>(null)
const saving = ref(false)
const baseOptions = ref<{ label: string; value: string }[]>([])
// the stored access key is never sent to the browser; the API returns this mask instead
const MASK = '********'
const keyStored = ref(false)
const showKey = ref(false)
const testing = ref(false)
const connection = ref<{ ok: boolean; text: string; warnings?: string[] } | null>(null)
const classes = useClassesStore()
const resetDialog = ref(false)
const resetInfo = ref<ResetPreview | null>(null)
const resetConfirm = ref('')
const resetting = ref(false)
const resetConfirmed = computed(() => resetConfirm.value.trim().toLowerCase() === 'reset' && !resetInfo.value?.blocked_by.length)

async function openReset() {
  resetInfo.value = null
  resetConfirm.value = ''
  resetDialog.value = true
  try {
    resetInfo.value = await api.resetPreview()
  } catch (e) {
    resetDialog.value = false
    $q.notify({ type: 'negative', message: errorMessage(e) })
  }
}

async function runReset() {
  resetting.value = true
  try {
    const r = await api.resetSystem(resetConfirm.value)
    resetDialog.value = false
    await Promise.all([models.refresh(), classes.refresh()])
    $q.notify({
      type: r.warnings.length ? 'warning' : 'positive',
      message: `System zurückgesetzt: ${r.images} Bilder, ${r.training_runs} Trainingsläufe, ${r.models_deleted.length} Modelle gelöscht`,
      caption: [
        r.production_model ? `Production-Modell: ${r.production_model}` : r.bootstrap_queued ? 'COCO-Grundmodell wird neu importiert' : '',
        ...r.warnings,
      ].filter(Boolean).join(' · '),
      timeout: 8000,
    })
  } catch (e) {
    $q.notify({ type: 'negative', message: errorMessage(e) })
    resetInfo.value = await api.resetPreview().catch(() => resetInfo.value)
  } finally {
    resetting.value = false
  }
}

const clientKeyStored = ref(false)
const showClientKey = ref(false)
const clientTesting = ref(false)
const pushing = ref(false)
const clientConnection = ref<{ ok: boolean; text: string } | null>(null)

async function testClient() {
  clientTesting.value = true
  try {
    const st = await api.clientAnnotatorStatus()
    if (!st.configured) clientConnection.value = { ok: false, text: 'Nicht konfiguriert – URL und Access Token eintragen und speichern.' }
    else if (!st.reachable) clientConnection.value = { ok: false, text: `Nicht erreichbar (${st.error})` }
    else {
      const c = st.counts
      clientConnection.value = {
        ok: true,
        text: `Verbunden – ${c?.annotated ?? 0} annotiert, ${c?.open ?? 0} offen · ` +
          (st.config
            ? `Konfiguration vom ${fmtDate(st.config.pushed_at)} (${st.config.classes.length} Klassen, Confidence ${st.config.confidence}` +
              `${st.config.confidence_source === 'env' ? ' – dort per CHECK_CONFIDENCE überschrieben' : ''})`
            : 'noch keine Konfiguration übertragen'),
      }
    }
  } catch (e) {
    clientConnection.value = { ok: false, text: errorMessage(e) }
  } finally {
    clientTesting.value = false
  }
}

async function pushClientConfig() {
  pushing.value = true
  try {
    await api.pushClientConfig()
    $q.notify({ type: 'positive', message: 'Konfiguration an den Kunden-Annotationsdienst übertragen' })
    await testClient()
  } catch (e) {
    $q.notify({ type: 'negative', message: errorMessage(e) })
  } finally {
    pushing.value = false
  }
}

async function testConnection() {
  testing.value = true
  try {
    const st = await api.deploymentStatus()
    if (!st.configured) connection.value = { ok: false, text: 'Nicht konfiguriert – URL und Access Key eintragen und speichern.' }
    else if (!st.reachable) connection.value = { ok: false, text: `Nicht erreichbar (${st.error})` }
    else if (st.error) connection.value = { ok: false, text: st.error }
    else connection.value = { ok: true, text: st.model ? `Verbunden – aktives Modell: ${st.model.version}` : 'Verbunden – noch kein Modell installiert' }
    if (connection.value && st.warnings?.length) connection.value.warnings = st.warnings
  } catch (e) {
    connection.value = { ok: false, text: errorMessage(e) }
  } finally {
    testing.value = false
  }
}

async function load() {
  const res = await api.getSettings()
  form.value = structuredClone(res.values)
  keyStored.value = res.values.deployment_access_key === MASK
  clientKeyStored.value = res.values.client_annotator_access_key === MASK
  defaults.value = res.defaults
}

function resetDefaults() {
  if (!defaults.value || !form.value) return
  // the connections to the production system and the client annotator are not tuning values: keep them
  const { deployment_url, deployment_access_key, client_annotator_url, client_annotator_access_key, client_inference_url } = form.value
  form.value = {
    ...structuredClone(defaults.value),
    deployment_url, deployment_access_key, client_annotator_url, client_annotator_access_key, client_inference_url,
  }
}

async function save() {
  if (!form.value) return
  saving.value = true
  try {
    const res = await api.updateSettings(form.value)
    form.value = structuredClone(res.values)
    keyStored.value = res.values.deployment_access_key === MASK
    clientKeyStored.value = res.values.client_annotator_access_key === MASK
    showKey.value = false
    showClientKey.value = false
    await models.refresh()
    $q.notify({ type: 'positive', message: 'Einstellungen gespeichert' })
  } catch (e) {
    $q.notify({ type: 'negative', message: errorMessage(e) })
  } finally {
    saving.value = false
  }
}

onMounted(async () => {
  await load()
  baseOptions.value = (await api.cocoBaseModels()).map((b) => ({
    label: `${b.label} – COCO AP ${b.coco_ap}, ${b.params_m} M Parameter`,
    value: b.id,
  }))
})
</script>

<style scoped>
.danger-card {
  border-color: rgba(251, 113, 133, 0.45);
}
</style>
