import { createApp } from 'vue'

import App from './App.vue'
import { analysisApiKey, createAnalysisApi } from './api/analysis'
import { createExportsApi, exportsApiKey } from './api/exports'
import { createJobsApi, jobsApiKey } from './api/jobs'
import { createRevisionsApi, revisionsApiKey } from './api/revisions'

const app = createApp(App)

app.provide(jobsApiKey, createJobsApi())
app.provide(analysisApiKey, createAnalysisApi())
app.provide(exportsApiKey, createExportsApi())
app.provide(revisionsApiKey, createRevisionsApi())
app.mount('#app')
