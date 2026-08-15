import { createApp } from 'vue'

import App from './App.vue'
import { createJobsApi, jobsApiKey } from './api/jobs'

const app = createApp(App)

app.provide(jobsApiKey, createJobsApi())
app.mount('#app')
