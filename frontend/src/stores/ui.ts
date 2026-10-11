import { defineStore } from 'pinia'
import { computed, ref, watch } from 'vue'

export type UiMode = 'simple' | 'advanced'
const STORAGE_KEY = 'ui-mode'

function load(): UiMode {
  try {
    return localStorage.getItem(STORAGE_KEY) === 'advanced' ? 'advanced' : 'simple'
  } catch {
    return 'simple'
  }
}

/** "Einfach" hides details one rarely changes (model choice, resolution, split, coordinates); "Erweitert" shows them. */
export const useUiStore = defineStore('ui', () => {
  const mode = ref<UiMode>(load())
  const advanced = computed(() => mode.value === 'advanced')
  watch(mode, (m) => {
    try {
      localStorage.setItem(STORAGE_KEY, m)
    } catch {
      /* storage unavailable: mode lasts until the page is reloaded */
    }
  })
  return { mode, advanced }
})
