import { defineStore } from 'pinia'
import { computed, ref } from 'vue'
import { api, type DetectionClass } from '@/services/api'

const FALLBACK_COLOR = '#9e9e9e'

/** Detection classes configured in the application. */
export const useClassesStore = defineStore('classes', () => {
  const all = ref<DetectionClass[]>([])
  const loaded = ref(false)

  const active = computed(() => all.value.filter((c) => c.active))
  /** Keyboard shortcut per class: the first nine active classes get 1-9. */
  const shortcuts = computed(() => {
    const map: Record<string, string> = {}
    active.value.slice(0, 9).forEach((c, i) => (map[c.name] = String(i + 1)))
    return map
  })

  function info(name: string) {
    const c = all.value.find((x) => x.name === name)
    return {
      name,
      label: c?.label ?? name,
      color: c?.color ?? FALLBACK_COLOR,
      active: c?.active ?? false,
      known: !!c,
      key: shortcuts.value[name] ?? '',
    }
  }

  function byShortcut(key: string) {
    const i = Number(key) - 1
    return Number.isInteger(i) && i >= 0 && i < 9 ? active.value[i] ?? null : null
  }

  async function refresh() {
    all.value = await api.listClasses()
    loaded.value = true
  }

  async function ensureLoaded() {
    if (!loaded.value) await refresh()
  }

  return { all, active, shortcuts, loaded, info, byShortcut, refresh, ensureLoaded }
})
