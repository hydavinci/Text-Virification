import { createApp } from 'vue'

import App from './App.vue'
import { createJobsApi, jobsApiKey } from './api/jobs'
import { createVerificationApi, verificationApiKey } from './api/verification'
import { applyStoredWorkspaceTheme } from './composables/useWorkspaceTheme'

applyStoredWorkspaceTheme(window.localStorage, document.documentElement)
const app = createApp(App)

app.provide(jobsApiKey, createJobsApi())
app.provide(verificationApiKey, createVerificationApi())
app.mount('#app')
