<template>
  <q-select
    :model-value="modelValue"
    :options="options"
    emit-value
    map-options
    dense
    outlined
    :label="label"
    @update:model-value="(v) => emit('update:modelValue', v)"
  >
    <template #option="scope">
      <q-item v-bind="scope.itemProps">
        <q-item-section>
          <q-item-label>{{ scope.opt.label }}</q-item-label>
          <q-item-label caption>{{ scope.opt.caption }}</q-item-label>
        </q-item-section>
      </q-item>
    </template>
  </q-select>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { useModelsStore } from '@/stores/models'

withDefaults(defineProps<{ modelValue: string; label?: string }>(), { label: 'Modell' })
const emit = defineEmits<{ 'update:modelValue': [value: string] }>()
const models = useModelsStore()

const options = computed(() => {
  const opts = [
    {
      value: 'production',
      label: `Production${models.production ? ` (${models.production.version})` : ''}`,
      caption: models.production ? 'aktives Production-Modell' : 'noch kein Production-Modell',
    },
    {
      value: 'candidate',
      label: `Neuester Candidate${models.latestCandidate ? ` (${models.latestCandidate.version})` : ''}`,
      caption: models.latestCandidate ? 'zuletzt trainiertes, nicht aktiviertes Modell' : 'kein Candidate vorhanden',
    },
  ]
  for (const m of models.versions) {
    const map = m.metrics_json?.overall?.mAP50
    opts.push({
      value: m.version,
      label: m.version,
      caption: `${m.status} · ${m.kind} · ${m.input_width}×${m.input_height}${map != null ? ` · mAP50 ${(map * 100).toFixed(1)} %` : ''}`,
    })
  }
  return opts
})
</script>
