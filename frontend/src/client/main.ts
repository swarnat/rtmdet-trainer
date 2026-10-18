// Web UI of the client annotator (client-annotator/): same look and annotation components as the training system
import { createApp } from 'vue'
import { createPinia } from 'pinia'
import { Quasar, Notify, Dialog } from 'quasar'
import langDe from 'quasar/lang/de-DE'
import VueKonva from 'vue-konva'

import '@quasar/extras/material-icons/material-icons.css'
import 'quasar/src/css/index.sass'
import '../styles.css'

import ClientApp from './ClientApp.vue'

const app = createApp(ClientApp)
app.use(createPinia())
app.use(Quasar, {
  plugins: { Notify, Dialog },
  lang: langDe,
  config: {
    dark: true,
    brand: {
      primary: '#06b6d4',
      secondary: '#a78bfa',
      accent: '#a78bfa',
      positive: '#34d399',
      negative: '#fb7185',
      info: '#22d3ee',
      warning: '#fbbf24',
      dark: '#0f172a',
      'dark-page': '#0a0f1a',
    },
    notify: { position: 'top-right', timeout: 3000 },
  },
})
app.use(VueKonva)
app.mount('#app')
