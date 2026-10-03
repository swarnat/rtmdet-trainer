import { fileURLToPath, URL } from 'node:url'
import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import { quasar, transformAssetUrls } from '@quasar/vite-plugin'

// During `npm run dev` API calls are proxied to the API container (port from .env API_PORT)
const apiTarget = process.env.VITE_API_PROXY ?? 'http://localhost:8000'

export default defineConfig({
  plugins: [vue({ template: { transformAssetUrls } }), quasar()],
  resolve: {
    alias: { '@': fileURLToPath(new URL('./src', import.meta.url)) },
  },
  server: {
    port: 5173,
    proxy: { '/api': { target: apiTarget, changeOrigin: true } },
    // docker-compose.dev.yml: polling for mounts without inotify events
    watch: process.env.VITE_USE_POLLING === 'true' ? { usePolling: true, interval: 300 } : undefined,
  },
  build: { chunkSizeWarningLimit: 1500 },
})
