<template>
  <q-icon
    name="help_outline"
    :size="inline ? '14px' : '18px'"
    class="help-icon text-muted cursor-pointer"
    :class="{ 'help-icon--inline': inline }"
    @click.stop
    @mousedown.stop
  >
    <q-tooltip max-width="320px" anchor="top middle" self="bottom middle" :offset="[0, 8]" class="text-body2">
      {{ term ? GLOSSARY[term] : text }}
    </q-tooltip>
  </q-icon>
</template>

<script setup lang="ts">
// Question-mark icon with an explanatory tooltip: inside form fields (#append slot) or inline next to a label
import { GLOSSARY, type GlossaryTerm } from '@/glossary'

defineProps<{ text?: string; term?: GlossaryTerm; inline?: boolean }>()
</script>

<style scoped>
.help-icon:hover {
  color: var(--app-cyan) !important;
}
.help-icon--inline {
  margin-left: 4px;
  vertical-align: -2px;
}
</style>
