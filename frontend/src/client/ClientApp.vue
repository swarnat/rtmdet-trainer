<template>
  <q-layout view="hHh lpR fFf">
    <q-page-container>
      <ClientAnnotator v-if="state === 'ready'" @logout="logout" />
      <q-page v-else class="flex flex-center">
        <q-spinner v-if="state === 'checking'" size="48px" color="primary" />
        <q-card v-else class="bg-panel" style="width: 420px; max-width: 92vw">
          <q-card-section>
            <div class="text-h6">Kunden-Annotation</div>
            <div class="text-body2 text-muted">Access Token eingeben (CLIENT_ACCESS_TOKEN des Dienstes).</div>
          </q-card-section>
          <q-card-section class="q-pt-none">
            <q-form @submit="login">
              <q-input v-model="token" type="password" outlined dense autofocus label="Access Token" autocomplete="current-password" />
              <div v-if="error" class="text-negative text-caption q-mt-sm">{{ error }}</div>
              <q-btn type="submit" color="primary" label="Anmelden" no-caps class="full-width q-mt-md" :loading="busy" :disable="!token" />
            </q-form>
          </q-card-section>
        </q-card>
      </q-page>
    </q-page-container>
  </q-layout>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { ApiError, errorMessage } from '@/services/api'
import { clientApi, setUnauthorizedHandler } from './api'
import ClientAnnotator from './ClientAnnotator.vue'

const state = ref<'checking' | 'login' | 'ready'>('checking')
const token = ref('')
const error = ref('')
const busy = ref(false)

setUnauthorizedHandler(() => (state.value = 'login'))

async function login() {
  busy.value = true
  error.value = ''
  try {
    await clientApi.login(token.value.trim())
    token.value = ''
    state.value = 'ready'
  } catch (e) {
    error.value = e instanceof ApiError && e.status === 401 ? 'Token ungültig' : errorMessage(e)
  } finally {
    busy.value = false
  }
}

async function logout() {
  await clientApi.logout().catch(() => undefined)
  state.value = 'login'
}

onMounted(async () => {
  // still logged in (cookie)?
  try {
    await clientApi.getConfig()
    state.value = 'ready'
  } catch {
    state.value = 'login'
  }
})
</script>
