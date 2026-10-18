import { fileURLToPath, URL } from 'node:url'
import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import { quasar, transformAssetUrls } from '@quasar/vite-plugin'

// During `npm run dev` API calls are proxied to the API container (port from .env API_PORT)
const apiTarget = process.env.VITE_API_PROXY ?? 'http://localhost:8000'

// `--mode client`: web UI of the client annotator (client.html, served by client-annotator/), output dist-client/
export default defineConfig(({ mode }) => ({
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
  build:
    mode === 'client'
      ? { outDir: 'dist-client', chunkSizeWarningLimit: 1500, rollupOptions: { input: fileURLToPath(new URL('./client.html', import.meta.url)) } }
      : { chunkSizeWarningLimit: 1500 },
}))
