import { createApp } from 'vue'
import { createPinia } from 'pinia'
import { Quasar, Notify, Dialog, Loading } from 'quasar'
import langDe from 'quasar/lang/de-DE'
import VueKonva from 'vue-konva'

import '@quasar/extras/material-icons/material-icons.css'
import 'quasar/src/css/index.sass'
import './styles.css'

import App from './App.vue'
import router from './router'

const app = createApp(App)
app.use(createPinia())
app.use(router)
app.use(Quasar, {
  plugins: { Notify, Dialog, Loading },
  lang: langDe,
  config: { notify: { position: 'top-right', timeout: 3000 } },
})
app.use(VueKonva)
app.mount('#app')
