<template>
  <q-layout view="hHh LpR fFf">
    <q-header elevated class="bg-blue-grey-9">
      <q-toolbar>
        <q-icon name="center_focus_strong" size="sm" class="q-mr-sm" />
        <q-toolbar-title shrink>Object Detection</q-toolbar-title>
        <q-tabs inline-label shrink stretch class="q-ml-md">
          <q-route-tab to="/" exact icon="dashboard" label="Dashboard" />
          <q-route-tab :to="{ name: 'annotate' }" icon="edit_square" label="Annotation" />
          <q-route-tab to="/training" icon="model_training" label="Training" />
          <q-route-tab to="/models" icon="inventory_2" label="Modelle" />
          <q-route-tab to="/classes" icon="category" label="Klassen" />
          <q-route-tab to="/settings" icon="settings" label="Einstellungen" />
        </q-tabs>
        <q-space />
        <q-chip v-if="models.production" dense color="green-7" text-color="white" icon="verified">
          Production: {{ models.production.version }}
        </q-chip>
        <q-chip v-else dense color="grey-7" text-color="white" icon="warning">kein Production-Modell</q-chip>
        <q-btn flat round dense icon="api" href="/api/v1/docs" target="_blank">
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

const models = useModelsStore()
const classes = useClassesStore()
onMounted(() => {
  models.refresh()
  classes.refresh()
})
</script>
