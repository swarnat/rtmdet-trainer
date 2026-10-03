<template>
  <q-page padding>
    <div class="row q-col-gutter-md">
      <div class="col-12 col-lg-8">
        <q-card flat bordered>
          <q-card-section class="row items-center">
            <div class="text-h6">Klassen</div>
            <q-space />
            <q-btn flat round dense icon="refresh" @click="classes.refresh()" />
          </q-card-section>
          <q-markup-table flat dense separator="horizontal">
            <thead>
              <tr>
                <th class="text-left" style="width: 70px">Reihenf.</th>
                <th class="text-left">Taste</th>
                <th class="text-left">Farbe</th>
                <th class="text-left">Name</th>
                <th class="text-left">Anzeigename</th>
                <th class="text-left" style="min-width: 260px">COCO-Quellklassen</th>
                <th class="text-right">Boxen</th>
                <th class="text-right">HN</th>
                <th class="text-center">Aktiv</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="(c, i) in classes.all" :key="c.name" :class="{ 'text-grey-6': !c.active }">
                <td>
                  <q-btn dense flat round size="sm" icon="arrow_upward" :disable="i === 0" @click="move(i, -1)" />
                  <q-btn dense flat round size="sm" icon="arrow_downward" :disable="i === classes.all.length - 1" @click="move(i, 1)" />
                </td>
                <td class="mono">{{ classes.shortcuts[c.name] ?? '–' }}</td>
                <td>
                  <q-btn dense round size="sm" :style="{ background: c.color }" class="color-swatch">
                    <q-popup-proxy>
                      <q-color :model-value="c.color" no-header-tabs default-view="palette" @change="(v) => update(c.name, { color: v })" />
                    </q-popup-proxy>
                  </q-btn>
                </td>
                <td class="mono">{{ c.name }}</td>
                <td class="cursor-pointer">
                  {{ c.label }} <q-icon name="edit" size="xs" color="grey-6" />
                  <q-popup-edit v-slot="scope" :model-value="c.label" buttons label-set="OK" label-cancel="Abbrechen" @save="(v) => update(c.name, { label: v })">
                    <q-input v-model="scope.value" dense autofocus @keyup.enter="scope.set" />
                  </q-popup-edit>
                </td>
                <td>
                  <q-select
                    :model-value="c.coco_classes"
                    :options="cocoOptions"
                    multiple
                    use-chips
                    use-input
                    dense
                    borderless
                    options-dense
                    :placeholder="c.coco_classes.length ? undefined : 'keine (neue Klasse)'"
                    @filter="filterCoco"
                    @update:model-value="(v) => update(c.name, { coco_classes: v })"
                  />
                </td>
                <td class="text-right">{{ c.annotation_count }}</td>
                <td class="text-right">{{ c.hard_negative_count }}</td>
                <td class="text-center">
                  <q-toggle :model-value="c.active" dense @update:model-value="(v) => update(c.name, { active: v })" />
                </td>
                <td>
                  <q-btn dense flat round size="sm" icon="delete" color="negative" :disable="c.annotation_count + c.hard_negative_count > 0" @click="remove(c.name)">
                    <q-tooltip>{{ c.annotation_count + c.hard_negative_count > 0 ? 'Klasse hat Annotationen – stattdessen deaktivieren' : 'Klasse löschen' }}</q-tooltip>
                  </q-btn>
                </td>
              </tr>
            </tbody>
          </q-markup-table>
        </q-card>

        <q-card flat bordered class="q-mt-md">
          <q-card-section>
            <div class="text-h6">Neue Klasse</div>
          </q-card-section>
          <q-card-section class="row q-col-gutter-sm items-start">
            <q-input
              v-model="form.name"
              dense
              outlined
              label="Name (technisch)"
              hint="a–z, 0–9, _ · nicht änderbar"
              :rules="[(v) => /^[a-z][a-z0-9_]{0,31}$/.test(v) || 'a–z, 0–9, _, beginnt mit Buchstabe']"
              lazy-rules
              class="col-12 col-sm-3"
            />
            <q-input v-model="form.label" dense outlined label="Anzeigename" class="col-12 col-sm-3" />
            <q-select
              v-model="form.coco_classes"
              :options="cocoOptions"
              multiple
              use-chips
              use-input
              dense
              outlined
              options-dense
              label="COCO-Quellklassen (optional)"
              hint="leer für Klassen ohne COCO-Entsprechung (z. B. Batterie)"
              class="col-12 col-sm-4"
              @filter="filterCoco"
            />
            <div class="col-12 col-sm-2">
              <q-btn color="primary" icon="add" label="Anlegen" no-caps class="full-width" :disable="!form.name || !form.label" @click="create" />
            </div>
          </q-card-section>
        </q-card>
      </div>

      <div class="col-12 col-lg-4">
        <q-card flat bordered>
          <q-card-section>
            <div class="text-h6">So funktionieren Klassen</div>
          </q-card-section>
          <q-card-section class="q-pt-none text-body2">
            <p>
              <b>Name</b> ist die feste Kennung (in Annotationen, API-Antworten und Modellen) und kann nicht geändert werden. Anzeigename, Farbe,
              Reihenfolge (Tasten 1–9 bei der Annotation) und COCO-Mapping sind jederzeit änderbar.
            </p>
            <p>
              <b>Neue Klasse hinzufügen:</b> Bereits annotierte Bilder wurden noch nicht auf die neue Klasse geprüft. Sie erscheinen unter
              Annotation → Filter „Prüfen“ und werden erst nach dem Prüfen und Speichern für Trainings mit dieser Klasse verwendet. So lernt
              das Modell ungeprüfte Objekte nicht als Hintergrund.
            </p>
            <p>
              <b>Training:</b> Pro Trainingslauf lassen sich die Klassen wählen, z. B. ein eigenes Modell nur für Batterien. Jedes Modell
              speichert seine Klassenliste; die API liefert immer die Klassen des verwendeten Modells.
            </p>
            <p>
              <b>COCO-Quellklassen:</b> Mit Mapping startet der Klassifikationskopf beim Training mit den Gewichten der COCO-Klassen (Mittelwert),
              ohne Mapping zufällig. Das importierte COCO-Basismodell erkennt nur Klassen mit Mapping; nach Änderungen unter „Modelle“ neu
              importieren.
            </p>
            <p class="q-mb-none">
              <b>Deaktivieren</b> blendet eine Klasse in Annotation und Training aus, vorhandene Boxen bleiben erhalten. Löschen ist nur ohne
              Annotationen möglich.
            </p>
          </q-card-section>
        </q-card>
      </div>
    </div>
  </q-page>
</template>

<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { useQuasar } from 'quasar'
import { api, errorMessage, type DetectionClass } from '@/services/api'
import { useClassesStore } from '@/stores/classes'

const $q = useQuasar()
const classes = useClassesStore()
const allCoco = ref<string[]>([])
const cocoOptions = ref<string[]>([])
const form = reactive({ name: '', label: '', coco_classes: [] as string[] })

function filterCoco(val: string, done: (fn: () => void) => void) {
  done(() => {
    const needle = val.toLowerCase()
    cocoOptions.value = needle ? allCoco.value.filter((c) => c.includes(needle)) : allCoco.value
  })
}

async function run(action: () => Promise<unknown>, success?: string) {
  try {
    await action()
    if (success) $q.notify({ type: 'positive', message: success, timeout: 1500 })
  } catch (e) {
    $q.notify({ type: 'negative', message: errorMessage(e) })
  } finally {
    await classes.refresh()
  }
}

function update(name: string, patch: Partial<Pick<DetectionClass, 'label' | 'color' | 'coco_classes' | 'active'>>) {
  run(() => api.updateClass(name, patch))
}

function move(index: number, delta: number) {
  const names = classes.all.map((c) => c.name)
  const [item] = names.splice(index, 1)
  names.splice(index + delta, 0, item)
  run(() => api.reorderClasses(names))
}

function create() {
  run(async () => {
    await api.createClass({ name: form.name.trim(), label: form.label.trim(), coco_classes: form.coco_classes })
    form.name = ''
    form.label = ''
    form.coco_classes = []
  }, 'Klasse angelegt')
}

function remove(name: string) {
  $q.dialog({
    title: 'Klasse löschen',
    message: `Klasse „${name}“ endgültig löschen?`,
    cancel: { label: 'Abbrechen', flat: true },
    ok: { label: 'Löschen', color: 'negative' },
  }).onOk(() => run(() => api.deleteClass(name), 'Klasse gelöscht'))
}

onMounted(async () => {
  allCoco.value = await api.cocoClasses()
  cocoOptions.value = allCoco.value
  await classes.refresh()
})
</script>

<style scoped>
.color-swatch {
  width: 22px;
  height: 22px;
  min-height: 22px;
  border: 1px solid rgba(0, 0, 0, 0.25);
}
</style>
