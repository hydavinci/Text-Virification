<script setup lang="ts">
import { computed, inject, nextTick, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'

import { jobsApiKey } from '../api/jobs'
import { verificationApiKey } from '../api/verification'
import JobProgress from '../components/JobProgress.vue'
import UploadWorkspace from '../components/UploadWorkspace.vue'
import { isTerminalJobStatus, type JobProgressEvent, type JobRead, type JobStatus } from '../types/jobs'
import type {
  AnalyzeOptions,
  GlossaryTerm,
  IssueState,
  Scenario,
  VerificationIssue,
  VerificationResult
} from '../types/verification'

interface JobProgressState {
  sourceName: string
  status: JobStatus
  progress: number
  message: string
  failureMessage: string | null
  connectionMessage: string | null
}

interface ScenarioOption {
  id: Scenario
  name: string
  description: string
  icon: string
}

const scenarios: ScenarioOption[] = [
  { id: 'general', name: '通用文档', description: '全面检查', icon: '通' },
  { id: 'academic', name: '学术论文', description: '术语与格式', icon: '学' },
  { id: 'business', name: '商务文档', description: '表达与规范', icon: '商' },
  { id: 'legal', name: '法律文书', description: '严谨与一致', icon: '法' },
  { id: 'news', name: '新闻稿', description: '准确与时效', icon: '新' },
  { id: 'technical', name: '技术文档', description: '术语与数字', icon: '技' }
]

const layers = [
  { id: 'character', name: '字符层', icon: 'A文', color: '#ef4444' },
  { id: 'vocabulary', name: '词汇层', icon: '词', color: '#f97316' },
  { id: 'sentence', name: '句子层', icon: '句', color: '#8b5cf6' },
  { id: 'format', name: '标点/格式层', icon: '符', color: '#0ea5e9' },
  { id: 'discourse', name: '语篇/语体层', icon: '篇', color: '#10b981' },
  { id: 'security', name: '合规/安全层', icon: '盾', color: '#d97706' }
]

const typeLabels: Record<string, string> = {
  typo: '错别字',
  variant_char: '异形词',
  width_mixed: '全半角混用',
  missing_char: '漏字/缺字',
  idiom_misuse: '成语误用',
  custom_term: '自定义术语',
  term_consistency: '术语不一致',
  expression: '语病/表达',
  grammar: '语法',
  logic: '逻辑',
  punctuation: '标点符号',
  spacing: '多余空格',
  number_format: '数字/格式',
  repetition: '重复词语',
  style: '文风/格式',
  colloquial: '口语化',
  banned_word: '禁用词',
  pii_id: '身份证号',
  pii_phone: '手机号',
  pii_email: '邮箱地址',
  pii_bank: '银行卡号',
  pii_key: '密钥/凭证',
  sensitive_politics: '涉政敏感词',
  sensitive_ethnic_religion: '民族宗教敏感词',
  sensitive_territory: '领土规范表述',
  ad_extreme: '广告法极限词'
}

const injectedJobsApi = inject(jobsApiKey)
if (!injectedJobsApi) {
  throw new Error('JobsApi is not provided.')
}
const jobsApi = injectedJobsApi
const verificationApi = inject(verificationApiKey, null)

const mode = ref<'file' | 'text'>('file')
const theme = ref<'light' | 'dark'>('light')
const selectedScenario = ref<Scenario>('general')
const enableSecurity = ref(true)
const enableSensitive = ref(true)
const enableAdExtreme = ref(false)
const trackChanges = ref(true)
const selectedLayer = ref('all')
const selectedSeverity = ref('all')
const settingsTab = ref<'settings' | 'terms' | 'banned'>('settings')
const resultTab = ref<'issues' | 'summary'>('issues')
const textInput = ref('')
const workingText = ref('')
const fileSource = ref<File | null>(null)
const result = ref<VerificationResult | null>(null)
const issueStates = reactive<Record<number, IssueState>>({})
const selectedSuggestions = reactive<Record<number, string>>({})
const glossary = ref<GlossaryTerm[]>([])
const bannedWords = ref<string[]>([])
const termOriginal = ref('')
const termStandard = ref('')
const bannedInput = ref('')
const isAnalyzing = ref(false)
const analysisStep = ref(0)
const errorMessage = ref<string | null>(null)
const toast = ref<string | null>(null)
const showHelp = ref(false)
const showPrivacy = ref(false)
const showEditor = ref(false)
const showPreview = ref(false)
const segmentedView = ref(true)
const findQuery = ref('')
const replaceText = ref('')
const caseSensitive = ref(false)
const showFindReplace = ref(false)
const activeFindIndex = ref(0)
const batchSnapshot = ref<Record<number, IssueState> | null>(null)
const editBackup = ref('')
const jobState = ref<JobProgressState | null>(null)

let unsubscribe: (() => void) | null = null
let requestGeneration = 0
let isMounted = true
let toastTimer: ReturnType<typeof setTimeout> | null = null

const currentOptions = computed<AnalyzeOptions>(() => ({
  scenario: selectedScenario.value,
  enableSecurity: enableSecurity.value,
  enableSensitive: enableSensitive.value,
  enableAdExtreme: enableAdExtreme.value,
  glossary: glossary.value,
  bannedWords: bannedWords.value
}))

const visibleIssues = computed(() => {
  if (!result.value) {
    return []
  }
  return result.value.issues
    .map((issue, index) => ({ issue, index }))
    .filter(({ issue }) => selectedLayer.value === 'all' || issue.layer === selectedLayer.value)
    .filter(({ issue }) => selectedSeverity.value === 'all' || issue.severity === selectedSeverity.value)
})

const pendingCount = computed(() =>
  result.value?.issues.filter((_, index) => (issueStates[index] ?? 'pending') === 'pending').length ?? 0
)
const acceptedCount = computed(() =>
  result.value?.issues.filter((_, index) => issueStates[index] === 'accepted').length ?? 0
)
const rejectedCount = computed(() =>
  result.value?.issues.filter((_, index) => issueStates[index] === 'rejected').length ?? 0
)

const modifiedText = computed(() => {
  if (!result.value) {
    return workingText.value
  }
  let text = workingText.value
  const accepted = result.value.issues
    .map((issue, index) => ({ issue, index }))
    .filter(({ index }) => issueStates[index] === 'accepted')
    .sort((a, b) => b.issue.position - a.issue.position)
  for (const { issue, index } of accepted) {
    const suggestion = selectedSuggestions[index] ?? issue.suggestion ?? ''
    if (
      issue.position >= 0 &&
      issue.end_position <= text.length &&
      text.slice(issue.position, issue.end_position) === issue.original
    ) {
      text = `${text.slice(0, issue.position)}${suggestion}${text.slice(issue.end_position)}`
    }
  }
  return text
})

const highlightedText = computed(() => {
  if (!result.value) {
    return ''
  }
  const issues = result.value.issues
    .map((issue, index) => ({ issue, index }))
    .sort((a, b) => a.issue.position - b.issue.position)
  let cursor = 0
  let html = ''
  for (const { issue, index } of issues) {
    if (issue.position < cursor || issue.position < 0 || issue.end_position > workingText.value.length) {
      continue
    }
    html += escapeHtml(workingText.value.slice(cursor, issue.position))
    const state = issueStates[index] ?? 'pending'
    html += `<mark class="issue-mark ${state} severity-${issue.severity}" data-issue="${index}">${escapeHtml(
      workingText.value.slice(issue.position, issue.end_position)
    )}</mark>`
    cursor = issue.end_position
  }
  html += escapeHtml(workingText.value.slice(cursor))
  return html
})

const findMatches = computed(() => {
  const query = findQuery.value
  if (!query) {
    return [] as Array<{ start: number; end: number }>
  }
  const source = caseSensitive.value ? workingText.value : workingText.value.toLowerCase()
  const needle = caseSensitive.value ? query : query.toLowerCase()
  const matches: Array<{ start: number; end: number }> = []
  let offset = 0
  while ((offset = source.indexOf(needle, offset)) >= 0) {
    matches.push({ start: offset, end: offset + needle.length })
    offset += Math.max(needle.length, 1)
  }
  return matches
})
const findCount = computed(() => findMatches.value.length)

function closeSubscription() {
  unsubscribe?.()
  unsubscribe = null
}

function buildInitialState(job: JobRead): JobProgressState {
  return {
    sourceName: job.source_name,
    status: job.status,
    progress: job.progress,
    message: job.error_message ?? defaultStatusMessage(job.status),
    failureMessage: job.error_message,
    connectionMessage: null
  }
}

function handleProgress(event: JobProgressEvent) {
  const currentSourceName = jobState.value?.sourceName ?? 'Uploaded document'
  const failure = event.status === 'failed' || event.status === 'partial' || event.status === 'expired'
  jobState.value = {
    sourceName: currentSourceName,
    status: event.status,
    progress: event.progress,
    message: event.message,
    failureMessage: failure ? event.message : null,
    connectionMessage: null
  }
}

function handleProgressError(message: string) {
  if (jobState.value && !isTerminalJobStatus(jobState.value.status)) {
    jobState.value = { ...jobState.value, connectionMessage: message }
  }
}

async function handleUpload(file: File) {
  fileSource.value = file
  if (verificationApi) {
    await runFileAnalysis(file)
    return
  }
  const generation = ++requestGeneration
  errorMessage.value = null
  closeSubscription()
  isAnalyzing.value = true
  try {
    const job = await jobsApi.createJob(file)
    if (!isRequestCurrent(generation)) {
      return
    }
    jobState.value = buildInitialState(job)
    unsubscribe = jobsApi.subscribe(
      job.job_id,
      (event) => isRequestCurrent(generation) && handleProgress(event),
      (message) => isRequestCurrent(generation) && handleProgressError(message)
    )
  } catch (error) {
    if (isRequestCurrent(generation)) {
      errorMessage.value = error instanceof Error ? error.message : 'Unable to create the job.'
    }
  } finally {
    if (isRequestCurrent(generation)) {
      isAnalyzing.value = false
    }
  }
}

async function runFileAnalysis(file: File) {
  if (!verificationApi || !confirmOptionalSettings()) {
    return
  }
  await runAnalysis(() => verificationApi.analyzeFile(file, currentOptions.value))
}

async function runTextAnalysis() {
  const text = textInput.value.trim()
  if (!text) {
    notify('请先输入需要检查的文本')
    return
  }
  if (!verificationApi || !confirmOptionalSettings()) {
    return
  }
  fileSource.value = null
  await runAnalysis(() => verificationApi.analyzeText(text, currentOptions.value))
}

async function runAnalysis(action: () => Promise<VerificationResult>) {
  const generation = ++requestGeneration
  isAnalyzing.value = true
  analysisStep.value = 0
  errorMessage.value = null
  const timer = window.setInterval(() => {
    analysisStep.value = Math.min(analysisStep.value + 1, 5)
  }, 420)
  try {
    const payload = await action()
    if (!isRequestCurrent(generation)) {
      return
    }
    result.value = payload
    workingText.value = payload.text
    resetIssueStates(payload.issues)
    showEditor.value = false
    showPreview.value = false
    analysisStep.value = 6
    saveSession()
    await nextTick()
  } catch (error) {
    if (isRequestCurrent(generation)) {
      errorMessage.value = error instanceof Error ? error.message : '检查失败，请稍后重试'
    }
  } finally {
    window.clearInterval(timer)
    if (isRequestCurrent(generation)) {
      isAnalyzing.value = false
    }
  }
}

function confirmOptionalSettings() {
  if (glossary.value.length || bannedWords.value.length) {
    return true
  }
  return window.confirm('尚未设置自定义术语表和禁用词库，将仅执行通用规则检查。是否继续？')
}

function resetIssueStates(issues: VerificationIssue[]) {
  for (const key of Object.keys(issueStates)) {
    delete issueStates[Number(key)]
  }
  for (const key of Object.keys(selectedSuggestions)) {
    delete selectedSuggestions[Number(key)]
  }
  issues.forEach((issue, index) => {
    issueStates[index] = 'pending'
    selectedSuggestions[index] = issue.suggestion ?? ''
  })
}

function setIssueState(index: number, state: IssueState) {
  issueStates[index] = state
  saveSession()
}

function setAllIssues(state: IssueState) {
  batchSnapshot.value = { ...issueStates }
  for (const { index } of visibleIssues.value) {
    issueStates[index] = state
  }
  saveSession()
}

function undoBatch() {
  if (!batchSnapshot.value) {
    return
  }
  for (const key of Object.keys(issueStates)) {
    delete issueStates[Number(key)]
  }
  Object.assign(issueStates, batchSnapshot.value)
  batchSnapshot.value = null
  saveSession()
}

function addGlossaryTerm() {
  const original = termOriginal.value.trim()
  const standard = termStandard.value.trim()
  if (!original || !standard || original === standard) {
    notify('请填写不同的原文写法和规范写法')
    return
  }
  if (glossary.value.some((term) => term.original === original && term.standard === standard)) {
    notify('该术语对已存在')
    return
  }
  glossary.value.push({ original, standard })
  termOriginal.value = ''
  termStandard.value = ''
}

function addBannedWord() {
  const word = bannedInput.value.trim()
  if (!word || bannedWords.value.includes(word)) {
    return
  }
  bannedWords.value.push(word)
  bannedInput.value = ''
}

function importGlossary(event: Event, kind: 'terms' | 'banned') {
  const input = event.target as HTMLInputElement
  const file = input.files?.[0]
  if (!file) {
    return
  }

  const reader = new FileReader()
  reader.onload = () => {
    const lines = String(reader.result ?? '').split(/\r?\n/)
    let added = 0
    for (const rawLine of lines) {
      const line = rawLine.trim()
      if (!line || line.startsWith('#')) {
        continue
      }
      if (kind === 'terms') {
        const parts = line.includes('\t')
          ? line.split('\t')
          : line.includes('→')
            ? line.split('→')
            : line.split(',')
        const original = parts[0]?.trim().replace(/^["']|["']$/g, '')
        const standard = parts[1]?.trim().replace(/^["']|["']$/g, '')
        if (
          original &&
          standard &&
          original !== standard &&
          !glossary.value.some((term) => term.original === original && term.standard === standard)
        ) {
          glossary.value.push({ original, standard })
          added += 1
        }
      } else {
        for (const word of line.split(/[,\t]/).map((item) => item.trim()).filter(Boolean)) {
          if (!bannedWords.value.includes(word)) {
            bannedWords.value.push(word)
            added += 1
          }
        }
      }
    }
    notify(`成功导入 ${added} 项`)
    input.value = ''
  }
  reader.readAsText(file, 'UTF-8')
}

function downloadSample(kind: 'terms' | 'banned') {
  const content = kind === 'terms'
    ? '# 原文写法,规范写法\nAI,人工智能\nAPP,应用程序\n'
    : '# 每行一个禁用词\n最好\n第一\n'
  downloadText(content, kind === 'terms' ? '术语表示例.csv' : '禁用词示例.txt')
}

function replaceAll() {
  if (!findQuery.value) {
    return
  }

  const escaped = findQuery.value.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
  const flags = caseSensitive.value ? 'g' : 'gi'
  const count = findCount.value
  workingText.value = workingText.value.replace(new RegExp(escaped, flags), replaceText.value)
  activeFindIndex.value = 0
  notify(`已替换 ${count} 处，请重新检查以刷新问题位置`)
}

function replaceCurrent() {
  const matches = findMatches.value
  if (!matches.length) {
    return
  }
  const match = matches[Math.min(activeFindIndex.value, matches.length - 1)]
  if (!match) {
    return
  }
  workingText.value =
    workingText.value.slice(0, match.start) + replaceText.value + workingText.value.slice(match.end)
  activeFindIndex.value = Math.min(activeFindIndex.value, Math.max(findMatches.value.length - 1, 0))
  notify('已替换当前匹配，请重新检查以刷新问题位置')
}

function moveFind(direction: 1 | -1) {
  if (!findCount.value) {
    activeFindIndex.value = 0
    return
  }
  activeFindIndex.value =
    (activeFindIndex.value + direction + findCount.value) % findCount.value
}

function startEdit() {
  editBackup.value = workingText.value
  showEditor.value = true
}

function saveEdit() {
  showEditor.value = false
  editBackup.value = ''
  notify('原文已更新，请重新检查以刷新问题位置')
}

function cancelEdit() {
  workingText.value = editBackup.value
  editBackup.value = ''
  showEditor.value = false
}

function handleDocumentClick(event: MouseEvent) {
  const element = event.target as HTMLElement
  const issueIndex = element.dataset.issue
  if (issueIndex === undefined) {
    return
  }
  document.getElementById(`issue-card-${issueIndex}`)?.scrollIntoView({
    behavior: 'smooth',
    block: 'center'
  })
}

async function recheck() {
  if (!verificationApi || !result.value) {
    return
  }
  const source = result.value
  textInput.value = modifiedText.value
  fileSource.value = null
  await runAnalysis(async () => {
    const checked = await verificationApi.analyzeText(textInput.value, currentOptions.value)
    if (!source.file_id) {
      return checked
    }
    return {
      ...checked,
      filename: source.filename,
      file_id: source.file_id,
      file_ext: source.file_ext
    }
  })
}

async function exportReport() {
  if (!verificationApi || !result.value) {
    return
  }
  try {
    await verificationApi.exportReport(result.value)
  } catch (error) {
    notify(error instanceof Error ? error.message : '报告导出失败')
  }
}

async function exportModified() {
  if (!result.value) {
    return
  }
  if (workingText.value !== result.value.text && acceptedCount.value > 0) {
    notify('手工编辑与已接受建议同时存在，请先重新检查后再导出原格式文件')
    return
  }
  if (!result.value.file_id || !verificationApi) {
    const text = trackChanges.value ? buildTrackedText() : modifiedText.value
    downloadText(text, `修改版_${result.value.filename.replace(/\.[^.]+$/, '')}.txt`)
    return
  }

  function buildTrackedText() {
    if (!result.value) {
      return workingText.value
    }
    let text = workingText.value
    const accepted = result.value.issues
      .map((issue, index) => ({ issue, index }))
      .filter(({ index }) => issueStates[index] === 'accepted')
      .sort((a, b) => b.issue.position - a.issue.position)
    for (const { issue, index } of accepted) {
      const suggestion = selectedSuggestions[index] ?? issue.suggestion ?? ''
      if (text.slice(issue.position, issue.end_position) === issue.original) {
        const tracked = `【删除：${issue.original}】【替换为：${suggestion || '（空）'}】`
        text = `${text.slice(0, issue.position)}${tracked}${text.slice(issue.end_position)}`
      }
    }
    return text
  }
  const replacements = result.value.issues
    .map((issue, index) => ({ issue, index }))
    .filter(({ index }) => issueStates[index] === 'accepted')
    .map(({ issue, index }) => ({
      original: issue.original,
      suggestion: selectedSuggestions[index] ?? issue.suggestion ?? '',
      position: issue.position,
      end_position: issue.end_position
    }))
  try {
    await verificationApi.exportOriginal(
      result.value,
      replacements,
      modifiedText.value,
      trackChanges.value
    )
  } catch (error) {
    notify(error instanceof Error ? error.message : '修改文件导出失败')
  }
}

function downloadText(text: string, filename: string) {
  const url = URL.createObjectURL(new Blob([text], { type: 'text/plain;charset=utf-8' }))
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = filename
  anchor.click()
  URL.revokeObjectURL(url)
}

function resetWorkspace() {
  result.value = null
  jobState.value = null
  fileSource.value = null
  textInput.value = ''
  workingText.value = ''
  errorMessage.value = null
  globalThis.sessionStorage?.removeItem('text-verification-session')
}

function toggleTheme() {
  theme.value = theme.value === 'light' ? 'dark' : 'light'
  applyTheme()
}

function applyTheme() {
  document.documentElement.dataset.theme = theme.value
  globalThis.localStorage?.setItem('text-verification-theme', theme.value)
}

function notify(message: string) {
  toast.value = message
  if (toastTimer) {
    window.clearTimeout(toastTimer)
  }
  toastTimer = window.setTimeout(() => {
    toast.value = null
  }, 2600)
}

function saveSession() {
  if (!result.value) {
    return
  }
  try {
    globalThis.sessionStorage?.setItem(
      'text-verification-session',
      JSON.stringify({
        result: result.value,
        workingText: workingText.value,
        issueStates: { ...issueStates },
        selectedSuggestions: { ...selectedSuggestions }
      })
    )
  } catch {
    // Large documents may exceed sessionStorage; the active in-memory session remains usable.
  }
}

function restoreSession() {
  const raw = globalThis.sessionStorage?.getItem('text-verification-session')
  if (!raw) {
    return
  }
  try {
    const saved = JSON.parse(raw) as {
      result: VerificationResult
      workingText: string
      issueStates: Record<number, IssueState>
      selectedSuggestions: Record<number, string>
    }
    result.value = saved.result
    workingText.value = saved.workingText
    Object.assign(issueStates, saved.issueStates)
    Object.assign(selectedSuggestions, saved.selectedSuggestions)
  } catch {
    globalThis.sessionStorage?.removeItem('text-verification-session')
  }
}

function isRequestCurrent(generation: number) {
  return isMounted && generation === requestGeneration
}

function defaultStatusMessage(status: JobStatus) {
  const messages: Record<JobStatus, string> = {
    queued: '作业已创建',
    upload_validated: '上传校验完成',
    parsing: '开始解析',
    checking_format: '正在检查格式',
    checking_sensitive: '正在检查敏感词',
    checking_chinese: '正在检查中文',
    checking_english: '正在检查英文',
    completed: '处理完成',
    partial: '部分完成',
    failed: '处理失败',
    expired: '任务已过期'
  }
  return messages[status]
}

function escapeHtml(value: string) {
  return value
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
    .replaceAll("'", '&#039;')
}

function handleKeyboard(event: KeyboardEvent) {
  if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === 'f' && result.value) {
    event.preventDefault()
    showFindReplace.value = true
    return
  }
  if (event.key === 'Escape') {
    showFindReplace.value = false
    showHelp.value = false
    showPrivacy.value = false
  }
}

watch([workingText, issueStates], saveSession, { deep: true })
watch([findQuery, caseSensitive], () => {
  activeFindIndex.value = 0
})

onMounted(() => {
  theme.value = globalThis.localStorage?.getItem('text-verification-theme') === 'dark' ? 'dark' : 'light'
  applyTheme()
  restoreSession()
  document.addEventListener('keydown', handleKeyboard)
})

onBeforeUnmount(() => {
  isMounted = false
  requestGeneration += 1
  closeSubscription()
  document.removeEventListener('keydown', handleKeyboard)
  if (toastTimer) {
    window.clearTimeout(toastTimer)
  }
})
</script>

<template>
  <div class="shell">
    <header class="topbar">
      <button class="brand" type="button" @click="resetWorkspace">
        <span class="brand-mark">啄</span>
        <span>
          <strong>啄木鸟</strong>
          <small>中英文字智能检查</small>
        </span>
      </button>
      <div class="top-actions">
        <template v-if="result">
          <button class="btn ghost" type="button" @click="recheck">重新检查</button>
          <button class="btn ghost" type="button" @click="exportReport">检查报告</button>
          <button class="btn primary" type="button" @click="exportModified">导出修改文件</button>
          <label class="switch compact">
            <input v-model="trackChanges" type="checkbox" />
            <span>保留修订</span>
          </label>
          <small v-if="result.file_ext === 'pdf'" class="pdf-export-note">
            PDF 原格式导出支持替换和删除，不支持纯插入
          </small>
        </template>
        <button class="icon-btn" type="button" title="隐私政策" @click="showPrivacy = true">隐</button>
        <button class="icon-btn" type="button" title="帮助" @click="showHelp = true">?</button>
        <button class="icon-btn" type="button" title="切换主题" @click="toggleTheme">
          {{ theme === 'light' ? '☾' : '☀' }}
        </button>
      </div>
    </header>

    <main v-if="!result" class="landing">
      <section class="hero">
        <div>
          <span class="eyebrow">DOCUMENT QUALITY GATE</span>
          <h1>解决文件交付的最后一英里</h1>
          <p>从字符、词汇、句子、格式、语篇与合规六个维度逐句扫描，精准定位中英文内容问题。</p>
        </div>
        <div class="radar" aria-hidden="true"><span></span></div>
      </section>

      <div class="landing-grid">
        <section class="input-card">
          <div class="mode-tabs">
            <button :class="{ active: mode === 'file' }" type="button" @click="mode = 'file'">上传文件</button>
            <button :class="{ active: mode === 'text' }" type="button" @click="mode = 'text'">粘贴文本</button>
          </div>

          <UploadWorkspace
            v-if="mode === 'file'"
            :busy="isAnalyzing"
            :server-error="errorMessage"
            @upload="handleUpload"
          />
          <div v-else class="text-mode">
            <textarea v-model="textInput" maxlength="500000" placeholder="在此粘贴需要检查的文本内容…" />
            <div class="text-footer">
              <span>{{ textInput.length.toLocaleString() }} 字符</span>
              <button class="btn primary" :disabled="isAnalyzing" type="button" @click="runTextAnalysis">
                开始检查
              </button>
            </div>
          </div>

          <div v-if="isAnalyzing" class="loading-card" role="status" aria-live="polite">
            <div class="spinner"></div>
            <div>
              <strong>正在执行六层检查</strong>
              <p>步骤 {{ Math.min(analysisStep + 1, 6) }}/6 · 请勿关闭页面</p>
            </div>
          </div>
          <JobProgress v-if="jobState" :state="jobState" />
          <p class="privacy-note">仅为完成检查处理文档；建议不要上传涉密文件。任务数据默认 24 小时后清理。</p>
        </section>

        <aside class="settings-card">
          <div class="side-tabs">
            <button :class="{ active: settingsTab === 'settings' }" @click="settingsTab = 'settings'">检查设置</button>
            <button :class="{ active: settingsTab === 'terms' }" @click="settingsTab = 'terms'">
              术语 {{ glossary.length }}
            </button>
            <button :class="{ active: settingsTab === 'banned' }" @click="settingsTab = 'banned'">
              禁用词 {{ bannedWords.length }}
            </button>
          </div>

          <div v-if="settingsTab === 'settings'" class="settings-body">
            <h2>文档场景</h2>
            <div class="scenario-grid">
              <button
                v-for="scenario in scenarios"
                :key="scenario.id"
                :class="{ active: selectedScenario === scenario.id }"
                type="button"
                @click="selectedScenario = scenario.id"
              >
                <span>{{ scenario.icon }}</span>
                <strong>{{ scenario.name }}</strong>
                <small>{{ scenario.description }}</small>
              </button>
            </div>
            <h2>合规开关</h2>
            <label class="switch"><span>个人信息与凭证扫描</span><input v-model="enableSecurity" type="checkbox" /></label>
            <label class="switch"><span>政治与敏感表述检查</span><input v-model="enableSensitive" type="checkbox" /></label>
            <label class="switch"><span>广告法极限词检查</span><input v-model="enableAdExtreme" type="checkbox" /></label>
          </div>

          <div v-else-if="settingsTab === 'terms'" class="settings-body">
            <h2>自定义术语表</h2>
            <p class="muted">规定原文写法应统一替换为的标准写法。</p>
            <div class="term-form">
              <input v-model="termOriginal" placeholder="原文写法" @keyup.enter="addGlossaryTerm" />
              <span>→</span>
              <input v-model="termStandard" placeholder="规范写法" @keyup.enter="addGlossaryTerm" />
              <button class="btn primary small" type="button" @click="addGlossaryTerm">添加</button>
            </div>
            <label class="import-btn">导入 CSV / TSV<input type="file" accept=".csv,.tsv,.txt" @change="importGlossary($event, 'terms')" /></label>
            <button class="link-btn" type="button" @click="downloadSample('terms')">下载示例</button>
            <button v-if="glossary.length" class="link-btn danger" type="button" @click="glossary = []">清空</button>
            <div class="chip-list">
              <div v-for="(term, index) in glossary" :key="`${term.original}-${term.standard}`" class="term-chip">
                <span class="original">{{ term.original }}</span><span>→</span><span class="standard">{{ term.standard }}</span>
                <button type="button" @click="glossary.splice(index, 1)">×</button>
              </div>
              <p v-if="!glossary.length" class="empty">暂无自定义术语</p>
            </div>
          </div>

          <div v-else class="settings-body">
            <h2>禁用词库</h2>
            <p class="muted">命中后作为独立问题提示替换或删除。</p>
            <div class="term-form">
              <input v-model="bannedInput" placeholder="输入禁用词" @keyup.enter="addBannedWord" />
              <button class="btn primary small" type="button" @click="addBannedWord">添加</button>
            </div>
            <label class="import-btn">批量导入<input type="file" accept=".csv,.tsv,.txt" @change="importGlossary($event, 'banned')" /></label>
            <button class="link-btn" type="button" @click="downloadSample('banned')">下载示例</button>
            <button v-if="bannedWords.length" class="link-btn danger" type="button" @click="bannedWords = []">清空</button>
            <div class="banned-list">
              <span v-for="(word, index) in bannedWords" :key="word">{{ word }}<button @click="bannedWords.splice(index, 1)">×</button></span>
              <p v-if="!bannedWords.length" class="empty">暂无禁用词</p>
            </div>
          </div>
        </aside>
      </div>

      <section class="layers">
        <article v-for="layer in layers" :key="layer.id" :style="{ '--layer-color': layer.color }">
          <span>{{ layer.icon }}</span><strong>{{ layer.name }}</strong>
        </article>
      </section>
    </main>

    <main v-else class="review-workspace">
      <section class="stats-strip">
        <article><small>{{ result.stats.primary_label }}</small><strong>{{ result.stats.primary_count }}</strong></article>
        <article><small>发现问题</small><strong>{{ result.summary.total }}</strong></article>
        <article><small>已接受</small><strong class="success">{{ acceptedCount }}</strong></article>
        <article><small>已忽略</small><strong class="muted-text">{{ rejectedCount }}</strong></article>
        <article><small>待处理</small><strong class="warning">{{ pendingCount }}</strong></article>
        <article><small>文件</small><strong class="filename">{{ result.filename }}</strong></article>
      </section>

      <section v-if="showFindReplace" class="find-panel">
        <input v-model="findQuery" placeholder="查找内容" />
        <input v-model="replaceText" placeholder="替换为（可留空）" />
        <label><input v-model="caseSensitive" type="checkbox" /> 区分大小写</label>
        <span>{{ findCount ? activeFindIndex + 1 : 0 }} / {{ findCount }}</span>
        <button class="btn ghost small" @click="moveFind(-1)">上一个</button>
        <button class="btn ghost small" @click="moveFind(1)">下一个</button>
        <button class="btn ghost small" @click="replaceCurrent">替换当前</button>
        <button class="btn primary small" @click="replaceAll">全部替换</button>
        <button class="btn ghost small" @click="showFindReplace = false">关闭</button>
      </section>

      <section class="review-toolbar">
        <div>
          <button class="btn ghost small" @click="showFindReplace = !showFindReplace">查找替换</button>
          <button v-if="!showEditor" class="btn ghost small" @click="startEdit">编辑原文</button>
          <button v-if="showEditor" class="btn accept small" @click="saveEdit">保存编辑</button>
          <button v-if="showEditor" class="btn reject small" @click="cancelEdit">取消编辑</button>
          <button class="btn ghost small" :class="{ active: showPreview }" @click="showPreview = !showPreview">修改预览</button>
          <button class="btn ghost small" :class="{ active: segmentedView }" @click="segmentedView = !segmentedView">句段视图</button>
        </div>
        <div>
          <button class="btn accept small" @click="setAllIssues('accepted')">全部接受</button>
          <button class="btn reject small" @click="setAllIssues('rejected')">全部忽略</button>
          <button class="btn ghost small" @click="setAllIssues('pending')">重置状态</button>
          <button v-if="batchSnapshot" class="btn ghost small" @click="undoBatch">撤销批量操作</button>
        </div>
      </section>

      <div class="review-grid">
        <section class="document-panel">
          <header><div><strong>{{ showPreview ? '修改预览' : '源文本' }}</strong><small>{{ result.filename }}</small></div></header>
          <textarea v-if="showEditor" v-model="workingText" class="document-editor" />
          <pre v-else-if="showPreview" class="document-content preview">{{ modifiedText }}</pre>
          <pre
            v-else
            class="document-content"
            :class="{ segmented: segmentedView }"
            v-html="highlightedText"
            @click="handleDocumentClick"
          ></pre>
        </section>

        <aside class="issues-panel">
          <header class="issues-header">
            <div class="side-tabs compact-tabs">
              <button :class="{ active: resultTab === 'issues' }" @click="resultTab = 'issues'">问题列表</button>
              <button :class="{ active: resultTab === 'summary' }" @click="resultTab = 'summary'">检查摘要</button>
            </div>
            <span>{{ visibleIssues.length }} 项</span>
          </header>

          <template v-if="resultTab === 'issues'">
            <div class="filters">
              <select v-model="selectedLayer">
                <option value="all">全部层级</option>
                <option v-for="layer in layers" :key="layer.id" :value="layer.id">{{ layer.name }}</option>
              </select>
              <select v-model="selectedSeverity">
                <option value="all">全部级别</option>
                <option value="error">错误</option>
                <option value="warning">警告</option>
                <option value="info">建议</option>
              </select>
            </div>
            <div class="issue-list">
              <article
                v-for="{ issue, index } in visibleIssues"
                :key="`${index}-${issue.rule_id}`"
                :id="`issue-card-${index}`"
                class="issue-card"
                :class="[issue.severity, issueStates[index] ?? 'pending']"
              >
                <div class="issue-meta">
                  <span>{{ typeLabels[issue.type] ?? issue.type }}</span>
                  <span>{{ layers.find((layer) => layer.id === issue.layer)?.name ?? issue.layer }}</span>
                  <span class="severity">{{ issue.severity }}</span>
                </div>
                <div class="diff">
                  <del>{{ issue.original || '（空）' }}</del><span>→</span>
                  <select
                    v-if="issue.alternatives?.length"
                    v-model="selectedSuggestions[index]"
                    aria-label="选择修改建议"
                  >
                    <option :value="issue.suggestion ?? ''">{{ issue.suggestion || '（删除）' }}</option>
                    <option v-for="alternative in issue.alternatives" :key="alternative" :value="alternative">
                      {{ alternative }}
                    </option>
                  </select>
                  <ins v-else>{{ issue.suggestion || '（删除）' }}</ins>
                </div>
                <p>{{ issue.description }}</p>
                <blockquote>{{ issue.context }}</blockquote>
                <p v-if="issue.review_reason" class="review-note">语义复核：{{ issue.review_reason }}</p>
                <div class="issue-actions">
                  <button class="accept" type="button" @click="setIssueState(index, 'accepted')">接受</button>
                  <button class="reject" type="button" @click="setIssueState(index, 'rejected')">忽略</button>
                  <button class="undo" type="button" @click="setIssueState(index, 'pending')">撤销</button>
                </div>
              </article>
              <div v-if="!visibleIssues.length" class="empty-state">当前筛选条件下没有问题</div>
            </div>
          </template>

          <div v-else class="summary-panel">
            <h3>按检查层级</h3>
            <div v-for="(count, label) in result.summary.by_layer" :key="label" class="summary-row">
              <span>{{ label }}</span><strong>{{ count }}</strong>
            </div>
            <h3>按问题类型</h3>
            <div v-for="(count, label) in result.summary.by_type" :key="label" class="summary-row">
              <span>{{ label }}</span><strong>{{ count }}</strong>
            </div>
          </div>
        </aside>
      </div>
    </main>

    <div v-if="toast" class="toast" role="status">{{ toast }}</div>
    <div v-if="showHelp || showPrivacy" class="modal-backdrop" @click.self="showHelp = showPrivacy = false">
      <section class="modal">
        <button class="modal-close" @click="showHelp = showPrivacy = false">×</button>
        <template v-if="showPrivacy">
          <h2>隐私政策</h2>
          <p>上传文件仅用于执行文档检查和导出。服务端按任务隔离存储，并在保留期结束后自动清理。</p>
          <p>启用云端语义复核时，仅发送规则命中位置附近的局部文本；未配置模型密钥时不会调用外部服务。</p>
        </template>
        <template v-else>
          <h2>使用帮助</h2>
          <p>选择文档场景和检查开关，可选配置术语表及禁用词，然后上传文件或粘贴文本。</p>
          <p>检查完成后可逐条接受、忽略或撤销建议，并通过查找替换和原文编辑完成最终校订。</p>
        </template>
      </section>
    </div>
  </div>
</template>

<style scoped>
:global(*) { box-sizing: border-box; }
:global(html) { color-scheme: light; }
:global(html[data-theme='dark']) { color-scheme: dark; }
:global(body) {
  margin: 0;
  min-width: 320px;
  min-height: 100vh;
  font-family: Inter, ui-sans-serif, -apple-system, BlinkMacSystemFont, "PingFang SC", "Microsoft YaHei", sans-serif;
  background: var(--bg);
  color: var(--text);
}
.shell {
  --primary: #2563eb;
  --primary-2: #06b6d4;
  --bg: #f5f7fb;
  --surface: #ffffff;
  --surface-2: #f8fafc;
  --border: #e2e8f0;
  --text: #172033;
  --muted: #64748b;
  --shadow: 0 18px 55px rgba(15, 23, 42, .09);
  min-height: 100vh;
  background:
    radial-gradient(circle at 8% 0%, rgba(37, 99, 235, .1), transparent 28rem),
    radial-gradient(circle at 96% 8%, rgba(6, 182, 212, .09), transparent 25rem),
    var(--bg);
}
:global(html[data-theme='dark']) .shell {
  --bg: #0c1220;
  --surface: #131c2e;
  --surface-2: #0f172a;
  --border: #26344c;
  --text: #e5edf8;
  --muted: #9aa9bd;
  --shadow: 0 18px 55px rgba(0, 0, 0, .28);
}
button, input, textarea, select { font: inherit; }
button { color: inherit; }
.topbar {
  height: 68px;
  padding: 0 28px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  position: sticky;
  top: 0;
  z-index: 20;
  border-bottom: 1px solid color-mix(in srgb, var(--border) 76%, transparent);
  background: color-mix(in srgb, var(--surface) 88%, transparent);
  backdrop-filter: blur(18px);
}
.brand { display: flex; align-items: center; gap: 11px; border: 0; background: none; cursor: pointer; text-align: left; }
.brand-mark {
  width: 38px; height: 38px; display: grid; place-items: center; border-radius: 13px;
  color: white; font-weight: 900; background: linear-gradient(135deg, var(--primary), var(--primary-2));
  box-shadow: 0 8px 20px rgba(37, 99, 235, .28);
}
.brand strong, .brand small { display: block; }
.brand strong { font-size: 16px; }
.brand small { color: var(--muted); font-size: 11px; margin-top: 1px; }
.top-actions { display: flex; align-items: center; gap: 8px; }
.icon-btn { width: 36px; height: 36px; border-radius: 11px; border: 1px solid var(--border); background: var(--surface); cursor: pointer; }
.btn { border: 1px solid transparent; border-radius: 11px; padding: 9px 15px; font-weight: 700; cursor: pointer; transition: .2s; }
.btn:disabled { opacity: .55; cursor: wait; }
.btn.primary { color: white; background: linear-gradient(135deg, var(--primary), var(--primary-2)); box-shadow: 0 7px 18px rgba(37, 99, 235, .2); }
.btn.ghost { border-color: var(--border); background: var(--surface); }
.btn.small { padding: 7px 11px; font-size: 12px; }
.btn.active { border-color: var(--primary); color: var(--primary); }
.btn.accept { background: #dcfce7; color: #15803d; }
.btn.reject { background: #fff1f2; color: #be123c; }
.landing { max-width: 1440px; margin: auto; padding: 36px 28px 50px; }
.hero {
  min-height: 215px; padding: 38px 44px; display: flex; align-items: center; justify-content: space-between;
  overflow: hidden; border-radius: 26px; color: white; background:
    linear-gradient(110deg, rgba(18, 67, 148, .98), rgba(22, 109, 162, .95) 55%, rgba(15, 145, 148, .92));
  box-shadow: var(--shadow);
}
.hero > div:first-child { max-width: 800px; }
.eyebrow { font-size: 11px; letter-spacing: .2em; opacity: .76; font-weight: 800; }
.hero h1 { font-size: clamp(30px, 4vw, 54px); line-height: 1.08; margin: 14px 0; letter-spacing: -.04em; }
.hero p { max-width: 700px; margin: 0; line-height: 1.8; opacity: .82; }
.radar { width: 160px; height: 160px; border: 1px solid rgba(255,255,255,.22); border-radius: 50%; position: relative; background: repeating-radial-gradient(circle, transparent 0 24px, rgba(255,255,255,.12) 25px 26px); }
.radar::before, .radar::after { content: ''; position: absolute; background: rgba(255,255,255,.16); }
.radar::before { width: 100%; height: 1px; top: 50%; }
.radar::after { width: 1px; height: 100%; left: 50%; }
.radar span { position: absolute; inset: 50% 50% 0 50%; transform-origin: top left; background: conic-gradient(from 0deg, rgba(255,255,255,.38), transparent 55deg); animation: sweep 4s linear infinite; }
@keyframes sweep { to { transform: rotate(360deg); } }
.landing-grid { display: grid; grid-template-columns: minmax(0, 1.7fr) minmax(340px, .8fr); gap: 22px; margin-top: 22px; }
.input-card, .settings-card, .document-panel, .issues-panel {
  border: 1px solid var(--border); border-radius: 20px; background: color-mix(in srgb, var(--surface) 96%, transparent); box-shadow: var(--shadow); overflow: hidden;
}
.input-card { padding: 24px; }
.mode-tabs, .side-tabs { display: flex; gap: 5px; padding: 4px; border-radius: 12px; background: var(--surface-2); }
.mode-tabs { width: fit-content; margin-bottom: 20px; }
.mode-tabs button, .side-tabs button { padding: 9px 17px; border: 0; border-radius: 9px; color: var(--muted); background: transparent; cursor: pointer; font-weight: 700; }
.mode-tabs button.active, .side-tabs button.active { color: var(--primary); background: var(--surface); box-shadow: 0 3px 10px rgba(15,23,42,.08); }
.text-mode textarea, .document-editor {
  width: 100%; resize: vertical; border: 1px solid var(--border); border-radius: 15px; color: var(--text); background: var(--surface-2); outline: none;
}
.text-mode textarea { min-height: 280px; padding: 18px; line-height: 1.8; }
.text-mode textarea:focus, input:focus, select:focus { border-color: var(--primary); outline: 3px solid rgba(37, 99, 235, .1); }
.text-footer { display: flex; align-items: center; justify-content: space-between; margin-top: 12px; color: var(--muted); }
.privacy-note { margin: 17px 0 0; color: var(--muted); font-size: 12px; }
.loading-card { margin-top: 16px; padding: 14px; display: flex; align-items: center; gap: 12px; border-radius: 13px; background: #eff6ff; color: #1d4ed8; }
.loading-card p { margin: 3px 0 0; font-size: 12px; }
.spinner { width: 27px; height: 27px; border: 3px solid #bfdbfe; border-top-color: #2563eb; border-radius: 50%; animation: spin .8s linear infinite; }
@keyframes spin { to { transform: rotate(360deg); } }
.settings-card { min-height: 460px; }
.settings-card > .side-tabs { margin: 16px; }
.settings-body { padding: 4px 20px 22px; }
.settings-body h2 { font-size: 14px; margin: 18px 0 10px; }
.scenario-grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 8px; }
.scenario-grid button { padding: 12px 7px; display: flex; flex-direction: column; gap: 3px; align-items: center; border: 1px solid var(--border); border-radius: 12px; background: var(--surface-2); cursor: pointer; }
.scenario-grid button.active { color: var(--primary); border-color: var(--primary); background: color-mix(in srgb, var(--primary) 8%, var(--surface)); }
.scenario-grid strong { font-size: 12px; }
.scenario-grid small { color: var(--muted); font-size: 10px; }
.switch { display: flex; align-items: center; justify-content: space-between; gap: 12px; padding: 10px 0; color: var(--muted); font-size: 13px; }
.switch input { width: 35px; height: 20px; accent-color: var(--primary); }
.switch.compact { padding: 0 8px; }
.term-form { display: flex; align-items: center; gap: 7px; }
.term-form input, .find-panel input, .filters select {
  min-width: 0; padding: 9px 10px; border: 1px solid var(--border); border-radius: 9px; color: var(--text); background: var(--surface-2);
}
.term-form input { flex: 1; }
.muted, .empty { color: var(--muted); font-size: 12px; }
.import-btn { display: inline-block; margin: 12px 0; padding: 6px 10px; border: 1px dashed var(--border); border-radius: 8px; color: var(--primary); font-size: 12px; cursor: pointer; }
.import-btn input { display: none; }
.link-btn { margin-left: 8px; border: 0; color: var(--primary); background: none; cursor: pointer; font-size: 12px; }
.link-btn.danger { color: #dc2626; }
.chip-list, .banned-list { max-height: 240px; overflow: auto; }
.term-chip { display: flex; gap: 6px; align-items: center; padding: 8px; margin-bottom: 6px; border-radius: 9px; background: var(--surface-2); font-size: 12px; }
.term-chip .original { color: #dc2626; font-weight: 700; }
.term-chip .standard { color: #059669; font-weight: 700; }
.term-chip button, .banned-list button { margin-left: auto; border: 0; color: var(--muted); background: none; cursor: pointer; }
.banned-list { display: flex; gap: 7px; flex-wrap: wrap; }
.banned-list > span { display: flex; gap: 6px; padding: 6px 9px; border-radius: 999px; background: #fff1f2; color: #be123c; font-size: 12px; }
.layers { display: grid; grid-template-columns: repeat(6, 1fr); gap: 10px; margin-top: 18px; }
.layers article { padding: 13px; display: flex; gap: 9px; align-items: center; border: 1px solid var(--border); border-top: 3px solid var(--layer-color); border-radius: 13px; background: var(--surface); }
.layers article span { color: var(--layer-color); font-weight: 900; }
.layers article strong { font-size: 12px; }
.review-workspace { height: calc(100vh - 68px); padding: 14px 18px 18px; display: flex; flex-direction: column; gap: 11px; }
.stats-strip { display: grid; grid-template-columns: repeat(5, minmax(90px, 130px)) minmax(220px, 1fr); gap: 8px; }
.stats-strip article { padding: 10px 13px; border: 1px solid var(--border); border-radius: 12px; background: var(--surface); }
.stats-strip small, .stats-strip strong { display: block; }
.stats-strip small { color: var(--muted); font-size: 10px; }
.stats-strip strong { margin-top: 2px; font-size: 18px; }
.stats-strip .filename { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-size: 13px; }
.success { color: #059669; }.warning { color: #d97706; }.muted-text { color: var(--muted); }
.review-toolbar, .find-panel { padding: 9px; display: flex; align-items: center; justify-content: space-between; gap: 10px; border: 1px solid var(--border); border-radius: 12px; background: var(--surface); }
.review-toolbar > div { display: flex; gap: 7px; }
.find-panel { justify-content: flex-start; }
.review-grid { flex: 1; min-height: 0; display: grid; grid-template-columns: minmax(0, 1.55fr) minmax(370px, .75fr); gap: 12px; }
.document-panel, .issues-panel { min-height: 0; display: flex; flex-direction: column; }
.document-panel > header, .issues-header { min-height: 54px; padding: 10px 15px; display: flex; align-items: center; justify-content: space-between; border-bottom: 1px solid var(--border); }
.document-panel header small { display: block; margin-top: 2px; color: var(--muted); }
.document-content, .document-editor { flex: 1; min-height: 0; margin: 0; padding: 24px 28px; overflow: auto; white-space: pre-wrap; color: var(--text); background: var(--surface); font: 15px/2 ui-monospace, SFMono-Regular, Menlo, monospace; }
.document-content.segmented { background-image: linear-gradient(var(--border) 1px, transparent 1px); background-size: 100% 30px; line-height: 30px; }
.document-content.preview { color: #075985; }
.document-editor { border: 0; border-radius: 0; resize: none; }
:deep(.issue-mark) { padding: 2px 1px; border-radius: 4px; background: #fef3c7; color: inherit; cursor: pointer; }
:deep(.issue-mark.severity-error) { background: #fecdd3; }
:deep(.issue-mark.severity-info) { background: #dbeafe; }
:deep(.issue-mark.accepted) { background: #bbf7d0; }
:deep(.issue-mark.rejected) { opacity: .45; text-decoration: line-through; }
.compact-tabs { padding: 3px; }
.compact-tabs button { padding: 7px 10px; font-size: 12px; }
.issues-header > span { color: var(--muted); font-size: 12px; }
.filters { padding: 10px; display: grid; grid-template-columns: 1fr 1fr; gap: 8px; border-bottom: 1px solid var(--border); }
.issue-list { flex: 1; min-height: 0; padding: 10px; overflow: auto; }
.issue-card { margin-bottom: 9px; padding: 13px; border: 1px solid var(--border); border-left: 4px solid #f59e0b; border-radius: 12px; background: var(--surface); }
.issue-card.error { border-left-color: #ef4444; }.issue-card.info { border-left-color: #3b82f6; }
.issue-card.accepted { background: color-mix(in srgb, #dcfce7 46%, var(--surface)); }
.issue-card.rejected { opacity: .58; }
.issue-meta { display: flex; gap: 5px; align-items: center; }
.issue-meta span { padding: 3px 7px; border-radius: 999px; background: var(--surface-2); color: var(--muted); font-size: 10px; font-weight: 800; }
.issue-meta .severity { margin-left: auto; text-transform: uppercase; }
.diff { display: flex; align-items: center; gap: 8px; margin: 11px 0; font-weight: 800; }
.diff del { color: #dc2626; }.diff ins { color: #059669; text-decoration: none; }
.diff select { max-width: 60%; padding: 5px; }
.issue-card p { margin: 7px 0; font-size: 12px; }
.issue-card blockquote { margin: 8px 0; padding: 8px 10px; border-left: 2px solid var(--border); color: var(--muted); background: var(--surface-2); font-size: 11px; }
.review-note { color: #7c3aed; }
.issue-actions { display: flex; gap: 7px; margin-top: 10px; }
.issue-actions button { padding: 5px 10px; border: 0; border-radius: 7px; cursor: pointer; font-size: 11px; font-weight: 800; }
.issue-actions .accept { color: #15803d; background: #dcfce7; }
.issue-actions .reject { color: #be123c; background: #fff1f2; }
.issue-actions .undo { color: var(--muted); background: var(--surface-2); }
.summary-panel { padding: 16px; overflow: auto; }
.summary-panel h3 { margin: 8px 0 10px; font-size: 13px; }
.summary-row { padding: 8px 0; display: flex; justify-content: space-between; border-bottom: 1px solid var(--border); font-size: 12px; }
.empty-state { padding: 40px 10px; text-align: center; color: var(--muted); }
.toast { position: fixed; left: 50%; bottom: 28px; transform: translateX(-50%); z-index: 40; padding: 11px 18px; border-radius: 10px; color: white; background: #172033; box-shadow: var(--shadow); }
.modal-backdrop { position: fixed; inset: 0; z-index: 50; display: grid; place-items: center; padding: 20px; background: rgba(2, 6, 23, .55); }
.modal { width: min(560px, 100%); padding: 28px; position: relative; border-radius: 18px; background: var(--surface); box-shadow: var(--shadow); }
.modal h2 { margin-top: 0; }.modal p { color: var(--muted); line-height: 1.8; }
.modal-close { position: absolute; right: 14px; top: 14px; border: 0; background: none; font-size: 24px; cursor: pointer; }
@media (max-width: 980px) {
  .landing-grid, .review-grid { grid-template-columns: 1fr; }
  .review-workspace { height: auto; }
  .document-panel { min-height: 540px; }
  .issues-panel { min-height: 600px; }
  .layers { grid-template-columns: repeat(3, 1fr); }
  .stats-strip { grid-template-columns: repeat(3, 1fr); }
  .radar { display: none; }
}
@media (max-width: 680px) {
  .topbar { padding: 0 13px; }
  .brand small, .top-actions .compact, .top-actions .ghost { display: none; }
  .landing { padding: 18px 12px 30px; }
  .hero { padding: 28px 22px; }
  .hero h1 { font-size: 32px; }
  .landing-grid { grid-template-columns: minmax(0, 1fr); }
  .scenario-grid, .layers { grid-template-columns: repeat(2, 1fr); }
  .stats-strip { grid-template-columns: repeat(2, 1fr); }
  .review-toolbar { align-items: stretch; flex-direction: column; }
  .review-toolbar > div { overflow-x: auto; }
  .find-panel { flex-wrap: wrap; }
}
@media (prefers-reduced-motion: reduce) {
  *, *::before, *::after { animation-duration: .01ms !important; animation-iteration-count: 1 !important; }
}
</style>
