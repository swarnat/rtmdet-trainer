<template>
  <q-page padding>
    <q-card flat bordered>
      <q-card-section class="row items-center q-gutter-sm">
        <div class="text-h6">Backups<HelpIcon term="backup" inline /></div>
        <div class="text-caption text-muted">
          Datenbank, Bilder, Annotationen, Klassen, Einstellungen, Trainingsläufe, Dataset-Snapshots und Modelle in einer Datei.
        </div>
        <q-space />
        <span v-if="list?.free_bytes != null" class="text-caption text-muted">frei: {{ fmtBytes(list.free_bytes) }}</span>
        <q-btn
          color="primary"
          icon="backup"
          label="Backup erstellen"
          :loading="starting"
          :disable="!list?.available || active"
          @click="start"
        >
          <q-tooltip v-if="active">Es läuft bereits ein Backup oder eine Wiederherstellung</q-tooltip>
        </q-btn>
        <q-btn flat round dense icon="refresh" @click="load" />
      </q-card-section>

      <q-banner v-if="list && !list.available" dense rounded class="bg-amber-soft text-body2 q-mx-md q-mb-md">
        <template #avatar><q-icon name="warning" color="warning" /></template>
        Der Backup-Ordner ist im API-Container nicht eingebunden (BACKUP_PATH in docker-compose).
      </q-banner>

      <q-table :rows="list?.backups ?? []" :columns="columns" row-key="name" flat dense :pagination="{ rowsPerPage: 20 }" :loading="loading">
        <template #body-cell-status="props">
          <q-td :props="props">
            <q-chip dense outline :color="statusColor[props.row.status]" :label="statusLabel[props.row.status] ?? props.row.status" />
            <q-icon v-if="props.row.warnings?.length" name="warning" color="warning" size="xs">
              <q-tooltip max-width="420px">{{ props.row.warnings.join(' · ') }}</q-tooltip>
            </q-icon>
          </q-td>
        </template>
        <template #body-cell-contents="props">
          <q-td :props="props">
            <template v-if="props.row.status === 'running' && props.row.progress">
              <div class="text-caption">
                {{ phaseLabel[props.row.phase ?? ''] ?? props.row.phase }} ·
                {{ props.row.progress.objects_done }} / {{ props.row.progress.objects_total }} Dateien ·
                {{ fmtBytes(props.row.progress.bytes_done) }} / {{ fmtBytes(props.row.progress.bytes_total) }}
              </div>
              <q-linear-progress
                :value="props.row.progress.bytes_total ? props.row.progress.bytes_done / props.row.progress.bytes_total : 0"
                color="primary"
                size="6px"
                style="min-width: 260px"
              />
            </template>
            <span v-else-if="props.row.status === 'queued'" class="text-caption text-muted">wartet auf den Backup-Dienst …</span>
            <span v-else-if="props.row.error" class="text-caption text-negative">{{ props.row.error }}</span>
            <span v-else class="text-caption">{{ contentsText(props.row) }}</span>
          </q-td>
        </template>
        <template #body-cell-actions="props">
          <q-td :props="props" class="actions-cell">
            <template v-if="props.row.status === 'completed' && props.row.file_exists">
              <q-btn dense flat round icon="download" :href="api.backupDownloadUrl(props.row.name)">
                <q-tooltip>Herunterladen ({{ fmtBytes(props.row.size_bytes) }})</q-tooltip>
              </q-btn>
              <q-btn dense flat round icon="settings_backup_restore" @click="restoreHelp = props.row">
                <q-tooltip>Wiederherstellen …</q-tooltip>
              </q-btn>
            </template>
            <q-btn
              v-if="props.row.status !== 'running' && props.row.status !== 'queued'"
              dense
              flat
              round
              color="negative"
              icon="delete"
              @click="remove(props.row)"
            >
              <q-tooltip>Löschen</q-tooltip>
            </q-btn>
          </q-td>
        </template>
        <template #no-data>
          <div class="full-width text-center text-muted q-pa-md">Noch keine Backups.</div>
        </template>
      </q-table>
    </q-card>

    <q-card flat bordered class="q-mt-md">
      <q-card-section>
        <div class="text-subtitle2">Wiederherstellen<HelpIcon term="restore" inline /></div>
        <div class="text-body2 text-muted q-mt-xs">
          Ein Backup ersetzt beim Wiederherstellen den <b>kompletten</b> aktuellen Stand. Das geht bewusst nur auf dem Server, im
          Projektverzeichnis: API, Trainer und Weboberfläche anhalten, im laufenden Backup-Dienst wiederherstellen, alles wieder
          starten. Der Restore-Befehl prüft die Datei zuerst vollständig (vorher wird nichts verändert) und stellt dann Datenbank und
          Dateien wieder her. Die bisherige Datenbank bleibt bis zur nächsten Wiederherstellung als Sicherheitskopie erhalten.
        </div>
        <pre class="log-view q-mt-sm q-mb-none">{{ commandFor(list?.backups.find((b) => b.status === 'completed')?.name ?? 'backup-JJJJMMTT-HHMMSS') }}</pre>
        <div class="text-caption text-muted q-mt-xs">
          Kurzform mit make: <span class="mono">make restore FILE=&lt;Name&gt;</span> (führt dieselben drei Schritte aus).
        </div>
        <div class="text-caption text-muted q-mt-xs">
          Backups von einem anderen System: .tar-Datei in den Backup-Ordner kopieren – sie erscheint dann hier in der Liste.
        </div>
      </q-card-section>
    </q-card>

    <q-dialog :model-value="!!restoreHelp" @update:model-value="(v) => !v && (restoreHelp = null)">
      <q-card v-if="restoreHelp" style="width: 640px; max-width: 95vw">
        <q-card-section class="row items-center">
          <div class="text-h6">{{ restoreHelp.name }} wiederherstellen</div>
          <q-space />
          <q-btn flat round dense icon="close" v-close-popup />
        </q-card-section>
        <q-card-section class="q-pt-none text-body2">
          <p>
            Stand vom <b>{{ fmtDate(restoreHelp.created_at) }}</b>: {{ contentsText(restoreHelp) }}. Alles, was danach erstellt wurde
            (Bilder, Annotationen, Trainings, Modelle, Einstellungen), geht verloren.
          </p>
          <p class="q-mb-xs">Auf dem Server im Projektverzeichnis ausführen:</p>
          <div class="row items-center no-wrap q-gutter-sm">
            <pre class="log-view col q-ma-none">{{ restoreCommand }}</pre>
            <q-btn flat round dense icon="content_copy" @click="copy(restoreCommand)"><q-tooltip>Kopieren</q-tooltip></q-btn>
          </div>
          <p class="text-caption text-muted q-mt-sm q-mb-none">
            Der Restore-Befehl fragt vor dem Überschreiben noch einmal nach. Diese Seite ist währenddessen nicht erreichbar.
            Kurzform: <span class="mono">make restore FILE={{ restoreHelp.name }}</span>
          </p>
        </q-card-section>
      </q-card>
    </q-dialog>
  </q-page>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { copyToClipboard, useQuasar, type QTableColumn } from 'quasar'
import HelpIcon from '@/components/HelpIcon.vue'
import { api, errorMessage, fmtDate, type Backup, type BackupList } from '@/services/api'

const $q = useQuasar()
const list = ref<BackupList | null>(null)
const loading = ref(false)
const starting = ref(false)
const restoreHelp = ref<Backup | null>(null)

const active = computed(() => !!list.value && (list.value.busy || list.value.backups.some((b) => b.status === 'queued' || b.status === 'running')))
// API, trainer and frontend must be stopped; the restore runs inside the running backup service
function commandFor(name: string) {
  return ['docker compose stop api trainer frontend', `docker compose exec backup odbackup restore ${name}`, 'docker compose up -d'].join('\n')
}
const restoreCommand = computed(() => (restoreHelp.value ? commandFor(restoreHelp.value.name) : ''))

const statusColor: Record<string, string> = { queued: 'grey-5', running: 'primary', completed: 'positive', failed: 'negative', invalid: 'negative' }
const statusLabel: Record<string, string> = { queued: 'wartet', running: 'läuft', completed: 'fertig', failed: 'fehlgeschlagen', invalid: 'ungültig' }
const phaseLabel: Record<string, string> = {
  inventory: 'Bestandsaufnahme',
  database: 'Datenbank',
  images: 'Bilder',
  datasets: 'Dataset-Snapshots',
  models: 'Modelle',
  finalizing: 'Abschluss',
}
const sourceLabel: Record<string, string> = { ui: 'Weboberfläche', cli: 'Kommandozeile', imported: 'kopiert' }
const columns: QTableColumn<Backup>[] = [
  { name: 'name', label: 'Backup', field: 'name', align: 'left' },
  { name: 'status', label: 'Status', field: 'status', align: 'left' },
  { name: 'created', label: 'Erstellt', field: (b) => fmtDate(b.created_at), align: 'left' },
  { name: 'size', label: 'Größe', field: (b) => fmtBytes(b.size_bytes) },
  { name: 'duration', label: 'Dauer', field: (b) => fmtDuration(b.duration_s) },
  { name: 'source', label: 'Erstellt über', field: (b) => sourceLabel[b.source ?? ''] ?? '–', align: 'left' },
  { name: 'contents', label: 'Inhalt', field: 'name', align: 'left' },
  { name: 'actions', label: '', field: 'name', align: 'right' },
]

function fmtBytes(n: number | null | undefined) {
  if (n == null) return '–'
  const units = ['B', 'KB', 'MB', 'GB', 'TB']
  let i = 0
  while (n >= 1024 && i < units.length - 1) {
    n /= 1024
    i++
  }
  return `${n.toFixed(i ? 1 : 0)} ${units[i]}`
}

function fmtDuration(s: number | null | undefined) {
  if (s == null) return '–'
  return s < 60 ? `${s} s` : `${Math.floor(s / 60)} min ${s % 60} s`
}

function contentsText(b: Backup) {
  const c = b.contents
  if (!c) return '–'
  return `${c.images ?? 0} Bilder · ${c.annotations ?? 0} Boxen · ${c.hard_negatives ?? 0} Hard Negatives · ${c.classes ?? 0} Klassen · ${c.model_versions ?? 0} Modelle · ${c.training_runs ?? 0} Trainingsläufe`
}

async function load() {
  loading.value = true
  try {
    list.value = await api.listBackups()
  } catch (e) {
    $q.notify({ type: 'negative', message: errorMessage(e) })
  } finally {
    loading.value = false
  }
}

async function start() {
  starting.value = true
  try {
    const b = await api.startBackup()
    $q.notify({ type: 'info', message: `${b.name} gestartet – läuft im Hintergrund, die Seite kann verlassen werden.` })
    await load()
  } catch (e) {
    $q.notify({ type: 'negative', message: errorMessage(e) })
  } finally {
    starting.value = false
  }
}

function remove(b: Backup) {
  $q.dialog({
    title: `${b.name} löschen`,
    message: `Die Backup-Datei (${fmtBytes(b.size_bytes)}) wird endgültig gelöscht.`,
    cancel: { label: 'Abbrechen', flat: true },
    ok: { label: 'Löschen', color: 'negative' },
  }).onOk(async () => {
    try {
      await api.deleteBackup(b.name)
      await load()
    } catch (e) {
      $q.notify({ type: 'negative', message: errorMessage(e) })
    }
  })
}

async function copy(text: string) {
  await copyToClipboard(text)
  $q.notify({ type: 'positive', message: 'Befehl kopiert', timeout: 1200 })
}

// poll while something is running; slow poll otherwise (e.g. backups started on the command line)
let timer: number | undefined
let ticks = 0
onMounted(async () => {
  await load()
  timer = window.setInterval(() => {
    ticks++
    if (active.value || ticks % 15 === 0) load()
  }, 2000)
})
onBeforeUnmount(() => window.clearInterval(timer))
</script>

<style scoped>
.actions-cell {
  white-space: nowrap;
}
</style>
