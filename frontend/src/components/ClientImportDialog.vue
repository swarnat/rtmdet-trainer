<template>
  <q-dialog :model-value="modelValue" @update:model-value="(v) => emit('update:modelValue', v)" @show="loadStatus">
    <q-card style="width: 640px; max-width: 95vw">
      <q-card-section class="row items-center">
        <div class="text-h6">Client-Annotationen einlesen<HelpIcon term="clientAnnotator" inline /></div>
        <q-space />
        <q-btn flat round dense icon="close" v-close-popup />
      </q-card-section>
      <q-card-section class="q-pt-none text-body2 text-muted">
        Holt die Bilder des Kunden-Annotationsdienstes samt Annotationen. Annotierte Bilder werden hier als annotiert gespeichert,
        offene mit ihrer Prüfung als Vorschläge. Jedes eingelesene Bild wird danach auf dem Kundenserver gelöscht.
      </q-card-section>

      <q-card-section class="q-pt-none">
        <div v-if="loading" class="row items-center q-gutter-sm"><q-spinner size="20px" /><span>Verbinde …</span></div>
        <template v-else-if="st">
          <div v-if="!st.configured" class="text-negative">
            Nicht konfiguriert – unter <router-link to="/settings" v-close-popup>Einstellungen</router-link> URL und Access Token eintragen.
          </div>
          <div v-else-if="!st.reachable" class="text-negative">{{ st.url }}: {{ st.error }}</div>
          <template v-else>
            <div class="text-body2">
              {{ st.url }} · <b>{{ st.counts?.annotated ?? 0 }}</b> annotiert · <b>{{ st.counts?.open ?? 0 }}</b> offen
            </div>
            <div v-if="!st.config" class="text-caption text-warning">Noch keine Konfiguration übertragen (Einstellungen → Kunden-Annotationsdienst).</div>
            <q-toggle v-model="onlyAnnotated" dense :disable="running" label="Nur annotierte Bilder (offene bleiben auf dem Kundenserver)" class="q-mt-sm" />
          </template>
        </template>
      </q-card-section>

      <q-card-section v-if="progress.total" class="q-pt-none">
        <q-linear-progress :value="progress.done / progress.total" size="14px" rounded color="primary" class="q-mb-sm">
          <div class="absolute-full flex flex-center text-caption text-white">{{ progress.done }} / {{ progress.total }}</div>
        </q-linear-progress>
        <div class="text-caption">
          {{ progress.created }} neu, {{ progress.duplicates }} Duplikate · {{ progress.annotated }} mit Annotationen übernommen,
          {{ progress.suggestions }} mit Vorschlägen<span v-if="progress.kept">, {{ progress.kept }} hier schon annotiert (beibehalten)</span><span v-if="progress.deleted">, {{ progress.deleted }} früher gelöscht</span><span v-if="errors.length">, {{ errors.length }} Fehler</span>
          <span v-if="cancelled"> · abgebrochen</span>
        </div>
        <q-list v-if="errors.length" dense bordered separator class="q-mt-sm rounded-borders" style="max-height: 160px; overflow: auto">
          <q-item v-for="(e, i) in errors" :key="i">
            <q-item-section>
              <q-item-label class="ellipsis text-caption" :title="e.filename ?? undefined">#{{ e.id }} {{ fmtMiddle(e.filename, 60) }}</q-item-label>
              <q-item-label caption class="text-negative">{{ e.error }}</q-item-label>
            </q-item-section>
          </q-item>
        </q-list>
      </q-card-section>

      <q-card-actions align="right">
        <q-btn v-if="running" outline color="negative" icon="stop" label="Abbrechen" no-caps @click="cancel" />
        <template v-else>
          <q-btn flat no-caps icon="refresh" label="Aktualisieren" @click="loadStatus" />
          <q-btn color="primary" icon="move_to_inbox" label="Einlesen" no-caps :disable="!st?.reachable || !pending" @click="start" />
        </template>
      </q-card-actions>
    </q-card>
  </q-dialog>
</template>

<script setup lang="ts">
import { computed, reactive, ref } from 'vue'
import HelpIcon from './HelpIcon.vue'
import { api, errorMessage, fmtMiddle, type ClientAnnotatorStatus } from '@/services/api'

export interface ClientImportProgress {
  total: number
  done: number
  created: number
  duplicates: number
  deleted: number
  /** saved with the client's annotations */
  annotated: number
  /** the client's check became suggestions */
  suggestions: number
  /** already labeled here: annotations kept */
  kept: number
  failed: number
}

defineProps<{ modelValue: boolean }>()
const emit = defineEmits<{
  'update:modelValue': [value: boolean]
  progress: [p: ClientImportProgress | null]
  finished: [p: ClientImportProgress]
}>()

// parallel requests to the backend (each imports one image)
const CONCURRENCY = 2

const st = ref<ClientAnnotatorStatus | null>(null)
const loading = ref(false)
const onlyAnnotated = ref(false)
const running = ref(false)
const cancelled = ref(false)
const empty = (): ClientImportProgress => ({ total: 0, done: 0, created: 0, duplicates: 0, deleted: 0, annotated: 0, suggestions: 0, kept: 0, failed: 0 })
const progress = reactive<ClientImportProgress>(empty())
const errors = ref<{ id: number; filename: string | null; error: string }[]>([])
let abort: AbortController | null = null

const pending = computed(() => (onlyAnnotated.value ? st.value?.counts?.annotated : st.value?.counts?.total) ?? 0)

async function loadStatus() {
  if (running.value) return
  loading.value = true
  try {
    st.value = await api.clientAnnotatorStatus()
  } catch (e) {
    st.value = { configured: true, url: null, reachable: false, error: errorMessage(e), config: null, counts: null }
  } finally {
    loading.value = false
  }
}

async function start() {
  Object.assign(progress, empty())
  errors.value = []
  cancelled.value = false
  running.value = true
  abort = new AbortController()
  const signal = abort.signal
  try {
    const list = await api.listClientImages()
    const queue = list.items.filter((i) => !onlyAnnotated.value || i.status === 'annotated')
    progress.total = queue.length
    emit('progress', { ...progress })

    async function worker() {
      while (queue.length && !signal.aborted) {
        const item = queue.shift()!
        try {
          const r = await api.importClientImage(item.id, signal)
          if (r.status === 'created') progress.created++
          else if (r.status === 'duplicate') progress.duplicates++
          else if (r.status === 'deleted') progress.deleted++
          if (r.applied === 'annotations') progress.annotated++
          else if (r.applied === 'suggestions') progress.suggestions++
          else if (r.applied === 'kept') progress.kept++
          // also "imported, but not deleted on the client"
          if (r.error) errors.value.push({ id: item.id, filename: item.filename, error: r.error })
        } catch (e) {
          if (signal.aborted) return
          errors.value.push({ id: item.id, filename: item.filename, error: errorMessage(e) })
        }
        progress.failed = errors.value.length
        progress.done++
        emit('progress', { ...progress })
      }
    }
    await Promise.all(Array.from({ length: CONCURRENCY }, worker))
  } catch (e) {
    errors.value.push({ id: 0, filename: 'Liste', error: errorMessage(e) })
    progress.failed = errors.value.length
  } finally {
    running.value = false
    abort = null
    emit('progress', null)
    emit('finished', { ...progress })
    loadStatus()
  }
}

function cancel() {
  cancelled.value = true
  abort?.abort()
}
</script>
