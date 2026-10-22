<template>
  <q-layout view="hHh LpR fFf">
    <q-header class="app-header">
      <q-toolbar class="app-toolbar">
        <div class="brand row items-center no-wrap">
          <div class="brand-logo"><q-icon name="center_focus_strong" size="18px" /></div>
          <span class="brand-name">Object Detection</span>
        </div>
        <q-tabs inline-label shrink no-caps indicator-color="transparent" active-class="app-tab--active" class="app-tabs">
          <q-route-tab to="/" exact label="Dashboard" />
          <q-route-tab :to="{ name: 'annotate' }" label="Annotation" />
          <q-route-tab to="/review" label="Sichtung" />
          <q-route-tab to="/annotation-review" label="Kontrolle" />
          <q-route-tab to="/candidates" label="Kandidaten" />
          <q-route-tab to="/duplicates" label="Duplikate" />
          <q-route-tab to="/training" label="Training" />
          <q-route-tab to="/models" label="Modelle" />
          <q-route-tab to="/classes" label="Klassen" />
          <q-route-tab to="/backups" label="Backups" />
          <q-route-tab to="/settings" label="Einstellungen" />
        </q-tabs>
        <q-space />
        <q-btn-toggle
          v-model="ui.mode"
          dense
          no-caps
          unelevated
          rounded
          size="sm"
          toggle-color="primary"
          color="transparent"
          text-color="grey-5"
          class="q-mr-sm mode-toggle"
          :options="[
            { label: 'Einfach', value: 'simple' },
            { label: 'Erweitert', value: 'advanced' },
          ]"
        >
          <q-tooltip>Erweitert zeigt zusätzliche Einstellungen, die man selten ändert (Modellwahl, Auflösung, Split, Koordinaten …)</q-tooltip>
        </q-btn-toggle>
        <q-chip v-if="models.production" dense outline color="positive" icon="verified">
          Production: {{ models.production.version }}
        </q-chip>
        <q-chip v-else dense outline color="grey-5" icon="warning">kein Production-Modell</q-chip>
        <q-btn flat dense icon="api" class="header-icon-btn q-ml-sm" href="/api/v1/docs" target="_blank">
          <q-tooltip>OpenAPI-Dokumentation</q-tooltip>
        </q-btn>
      </q-toolbar>
    </q-header>
    <q-page-container>
      <router-view />
    </q-page-container>
  </q-layout>
</template>

<script setup lang="ts">
import { onMounted } from 'vue'
import { useClassesStore } from '@/stores/classes'
import { useModelsStore } from '@/stores/models'
import { useUiStore } from '@/stores/ui'

const models = useModelsStore()
const ui = useUiStore()
const classes = useClassesStore()
onMounted(() => {
  models.refresh()
  classes.refresh()
})
</script>

<style scoped>
.mode-toggle {
  border: 1px solid var(--app-border);
}
.app-header {
  background: var(--app-bg);
  color: var(--app-text);
  border-bottom: 1px solid var(--app-border);
}
.app-toolbar {
  height: 64px;
  padding: 0 40px;
  gap: 8px;
}
.brand {
  gap: 10px;
  margin-right: 32px;
}
.brand-logo {
  width: 32px;
  height: 32px;
  border-radius: 8px;
  background: var(--app-cyan);
  color: white;
  display: flex;
  align-items: center;
  justify-content: center;
}
.brand-name {
  font-size: 1.25rem;
  font-weight: 600;
  letter-spacing: -0.01em;
}
.app-tabs :deep(.q-tab) {
  min-height: 36px;
  padding: 0 16px;
  margin-right: 4px;
  border-radius: 8px;
  border: 1px solid transparent;
  color: var(--app-muted);
  font-size: 14px;
  font-weight: 500;
}
.app-tabs :deep(.q-tab:hover) {
  color: var(--app-text);
}
.app-tabs :deep(.q-tab .q-focus-helper) {
  display: none;
}
.app-tabs :deep(.app-tab--active) {
  color: var(--app-text);
  background: var(--app-panel);
  border-color: var(--app-border);
}
.header-icon-btn {
  width: 36px;
  height: 36px;
  border: 1px solid var(--app-border);
  color: var(--app-muted);
}
@media (max-width: 1023px) {
  .app-toolbar { padding: 0 16px; }
  .brand { margin-right: 12px; }
}
</style>
