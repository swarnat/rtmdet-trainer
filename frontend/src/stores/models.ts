import { defineStore } from 'pinia'
import { computed, ref } from 'vue'
import { api, type ModelVersion, type Settings } from '@/services/api'

export const useModelsStore = defineStore('models', () => {
  const versions = ref<ModelVersion[]>([])
  const settings = ref<Settings | null>(null)
  const loading = ref(false)

  const production = computed(() => versions.value.find((m) => m.status === 'production') ?? null)
  const latestCandidate = computed(() => versions.value.find((m) => m.status === 'candidate') ?? null)
  const inputSizes = computed(() => settings.value?.input_sizes ?? ['1536x864'])
  const defaultInputSize = computed(() => settings.value?.default_input_size ?? '1536x864')
  const defaultConfidence = computed(() => settings.value?.default_confidence ?? 0.25)

  async function refresh() {
    loading.value = true
    try {
      const [models, s] = await Promise.all([api.listModels(), api.getSettings()])
      versions.value = models
      settings.value = s.values
    } finally {
      loading.value = false
    }
  }

  return { versions, settings, loading, production, latestCandidate, inputSizes, defaultInputSize, defaultConfidence, refresh }
})
