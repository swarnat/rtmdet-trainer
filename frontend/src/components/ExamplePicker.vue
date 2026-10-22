<template>
  <q-dialog :model-value="modelValue" @update:model-value="(v) => emit('update:modelValue', v)" @show="onShow">
    <q-card style="width: 1000px; max-width: 95vw">
      <q-card-section class="row items-center q-gutter-sm">
        <div class="text-h6">Beispiele wählen</div>
        <q-space />
        <q-select
          v-model="cls" :options="classOptions" emit-value map-options dense outlined label="Aus Klasse" style="min-width: 200px"
        />
      </q-card-section>
      <q-card-section class="q-pt-none text-caption text-muted">
        Typische, <b>unterschiedliche</b> Beispiele wählen (3–10, höchstens {{ MAX }}): verschiedene Größen, Blickwinkel, Hintergründe.
        Die Suche findet Objekte, die diesen Beispielen ähneln. Es zählen echte Objekte, keine Hard Negatives oder ignorierten Bereiche.
      </q-card-section>
      <q-card-section style="max-height: 55vh" class="scroll">
        <div v-if="!loading && !items.length" class="text-muted text-center q-pa-lg">Keine annotierten Objekte in dieser Klasse.</div>
        <div class="tiles">
          <div
            v-for="c in items" :key="c.id" class="tile" :class="{ selected: chosen.has(c.id) }" :style="tileStyle(c)" @click="toggle(c)"
          >
            <img :src="api.cropUrl(c)" loading="lazy" draggable="false" :alt="`#${c.image_id}`" />
            <div class="box" :style="boxStyle(c)" />
            <div v-if="chosen.has(c.id)" class="check"><q-icon name="check_circle" color="positive" size="22px" /></div>
          </div>
        </div>
        <div v-if="items.length < total" class="row justify-center q-mt-md">
          <q-btn outline no-caps color="primary" :label="`Weitere ${Math.min(PAGE, total - items.length)} laden`" :loading="loading" @click="load(true)" />
        </div>
      </q-card-section>
      <q-card-actions align="right">
        <div class="text-caption text-muted q-mr-md">{{ chosen.size }} gewählt</div>
        <q-btn flat no-caps label="Abbrechen" @click="emit('update:modelValue', false)" />
        <q-btn unelevated no-caps color="primary" label="Übernehmen" :disable="!chosen.size" @click="confirm" />
      </q-card-actions>
    </q-card>
  </q-dialog>
</template>

<script setup lang="ts">
import { computed, reactive, ref, watch } from 'vue'
import { useQuasar } from 'quasar'
import { api, errorMessage, type ReviewCrop } from '@/services/api'
import { useClassesStore } from '@/stores/classes'

const MAX = 20
const PAGE = 120
const TILE_H = 110
const props = defineProps<{ modelValue: boolean; initialClass: string; selected: ReviewCrop[] }>()
const emit = defineEmits<{ 'update:modelValue': [open: boolean]; confirm: [examples: ReviewCrop[]] }>()

const $q = useQuasar()
const classes = useClassesStore()
const cls = ref('')
const items = ref<ReviewCrop[]>([])
const total = ref(0)
const margin = ref(20)
const loading = ref(false)
// chosen examples keep their crop data: the selection survives switching the class
const chosen = reactive(new Map<number, ReviewCrop>())
const classOptions = ref<{ value: string; label: string }[]>([])

function toggle(c: ReviewCrop) {
  if (chosen.has(c.id)) chosen.delete(c.id)
  else if (chosen.size >= MAX) $q.notify({ type: 'warning', message: `Höchstens ${MAX} Beispiele`, timeout: 1500 })
  else chosen.set(c.id, c)
}

function cropWindow(c: ReviewCrop) {
  const x1 = Math.max(0, Math.floor(c.x1 - margin.value))
  const y1 = Math.max(0, Math.floor(c.y1 - margin.value))
  const x2 = Math.min(c.image_width, Math.ceil(c.x2 + margin.value))
  const y2 = Math.min(c.image_height, Math.ceil(c.y2 + margin.value))
  return { x1, y1, w: Math.max(1, x2 - x1), h: Math.max(1, y2 - y1) }
}
function tileStyle(c: ReviewCrop) {
  const w = cropWindow(c)
  const width = Math.min(TILE_H * (w.w / w.h), TILE_H * 3)
  return { width: `${width}px`, height: `${width * (w.h / w.w)}px` }
}
function boxStyle(c: ReviewCrop) {
  const w = cropWindow(c)
  return {
    left: `${((c.x1 - w.x1) / w.w) * 100}%`,
    top: `${((c.y1 - w.y1) / w.h) * 100}%`,
    width: `${((c.x2 - c.x1) / w.w) * 100}%`,
    height: `${((c.y2 - c.y1) / w.h) * 100}%`,
    borderColor: classes.info(cls.value).color,
  }
}

let request = 0
async function load(append = false) {
  if (!cls.value) return
  const id = ++request
  loading.value = true
  try {
    const res = await api.reviewCrops({ class: cls.value, type: 'positive', sort: 'newest', offset: append ? items.value.length : 0, limit: PAGE })
    if (id !== request) return
    margin.value = res.margin
    total.value = res.total
    items.value = append ? [...items.value, ...res.items] : res.items
  } catch (e) {
    $q.notify({ type: 'negative', message: errorMessage(e) })
  } finally {
    if (id === request) loading.value = false
  }
}

async function onShow() {
  chosen.clear()
  props.selected.forEach((c) => chosen.set(c.id, c))
  try {
    const counts = await api.reviewClasses()
    classOptions.value = counts.filter((c) => c.positive > 0).map((c) => ({ value: c.class, label: `${classes.info(c.class).label} (${c.positive})` }))
  } catch (e) {
    $q.notify({ type: 'negative', message: errorMessage(e) })
  }
  const preferred = classOptions.value.some((o) => o.value === props.initialClass) ? props.initialClass : classOptions.value[0]?.value ?? ''
  if (cls.value === preferred) await load()
  else cls.value = preferred
}
watch(cls, () => load())

function confirm() {
  emit('confirm', [...chosen.values()])
  emit('update:modelValue', false)
}
</script>

<style scoped>
.tiles {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  align-items: flex-end;
}
.tile {
  position: relative;
  overflow: hidden;
  cursor: pointer;
  border-radius: 4px;
  background: #222;
  outline: 1px solid rgba(128, 128, 128, 0.3);
  user-select: none;
}
.tile:hover {
  outline: 2px solid var(--q-primary);
}
.tile.selected {
  outline: 3px solid var(--q-positive);
}
.tile img {
  display: block;
  width: 100%;
  height: 100%;
}
.box {
  position: absolute;
  border: 2px solid;
  pointer-events: none;
  box-sizing: border-box;
}
.check {
  position: absolute;
  right: 2px;
  bottom: 2px;
  line-height: 0;
  background: #fff;
  border-radius: 50%;
}
</style>
