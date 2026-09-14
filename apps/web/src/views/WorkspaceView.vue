<script setup lang="ts">
import { computed, inject, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'

import { jobsApiKey } from '../api/jobs'
import { verificationApiKey } from '../api/verification'
import JobProgress from '../components/JobProgress.vue'
import DocumentViewer from '../components/workspace/DocumentViewer.vue'
import EditPreview from '../components/workspace/EditPreview.vue'
import ExportPanel from '../components/workspace/ExportPanel.vue'
import HelpDialog from '../components/workspace/HelpDialog.vue'
import IssueList from '../components/workspace/IssueList.vue'
import OriginalDocumentPreview from '../components/workspace/OriginalDocumentPreview.vue'
import PrivacyDialog from '../components/workspace/PrivacyDialog.vue'
import ReviewActions from '../components/workspace/ReviewActions.vue'
import SearchReplacePanel from '../components/workspace/SearchReplacePanel.vue'
import WorkspaceHeader from '../components/workspace/WorkspaceHeader.vue'
import WorkspaceSettingsDialog from '../components/workspace/WorkspaceSettingsDialog.vue'
import WorkspaceSetup from '../components/workspace/WorkspaceSetup.vue'
import { useIssueNavigation } from '../composables/useIssueNavigation'
import type { DocumentSearchState } from '../composables/useSearchReplace'
import { projectDocumentIssues } from '../utils/documentPresentation'
import { revealWithinPane } from '../utils/revealWithinPane'
import { useVerificationExecution } from '../composables/useVerificationExecution'
import {
  bindWorkspaceExportAuthority,
  isWorkspaceExportAuthorityBoundToResult,
  type WorkspaceExportAuthority,
  type WorkspaceExportAuthoritySource,
  useWorkspaceSession
} from '../composables/useWorkspaceSession'
import {
  applyStoredWorkspaceTheme,
  persistWorkspaceTheme
} from '../composables/useWorkspaceTheme'
import { useVerificationWorkspace } from '../composables/useVerificationWorkspace'
import { validateDirectText } from '../validation/verificationLimits'
import type {
  AnalyzeOptions,
  DocumentRevision,
  DraftDocumentRevision,
  IssueState,
  OcrLanguage,
  VerificationIssue,
  VerificationResult
} from '../types/verification'

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

const theme = ref<'light' | 'dark'>('light')
const selectedScenario = ref<AnalyzeOptions['scenario']>('general')
const enableSecurity = ref(true)
const enableSensitive = ref(true)
const enableAdExtreme = ref(false)
const ocrLanguage = ref<OcrLanguage | undefined>(undefined)
const enableExtendedRules = ref<boolean | undefined>(undefined)
const trackChanges = ref(false)
const settingsTab = ref<'settings' | 'terms' | 'banned'>('settings')
const settingsOpen = ref(false)
const resultTab = ref<'issues' | 'summary'>('issues')
const reviewPane = ref<'document' | 'issues' | 'search'>('document')
const textInput = ref('')
const fileSource = ref<File | null>(null)
const verificationWorkspace = useVerificationWorkspace()
const workspaceSession = useWorkspaceSession(
  window.sessionStorage,
  verificationWorkspace
)
const execution = useVerificationExecution({
  jobsApi,
  verificationApi,
  fileExecutionMode: 'jobs'
})
const result = computed(() => verificationWorkspace.result.value)
const documentReveal = ref(0)
const documentNavigationTarget = ref<'issue' | 'search'>('issue')
const originalPreviewSource = computed(() => {
  const source = captureFileExportAuthority()
  return source && ['docx', 'doc', 'rtf', 'pdf', 'png', 'jpg'].includes(source.fileType)
    ? source : null
})
const issueStates = verificationWorkspace.issueStates
const selectedSuggestions = verificationWorkspace.selectedSuggestions
const canUndoLastBatch = computed(
  () => verificationWorkspace.canUndoLastBatch.value
)
const currentIssueStates = computed(() => issueStates.value)
const currentSelectedSuggestions = computed(
  () => selectedSuggestions.value
)
const issueNavigation = useIssueNavigation({
  issues: () => verificationWorkspace.visibleIssues.value
})
const selectedLayer = issueNavigation.selectedLayer
const selectedSeverity = issueNavigation.selectedSeverity
const selectedIssueId = issueNavigation.selectedIssueId
const visibleIssues = issueNavigation.visibleIssues
const glossary = ref<AnalyzeOptions['glossary']>([])
const bannedWords = ref<string[]>([])
const isAnalyzing = execution.isActive
const errorMessage = computed(() => execution.error.value?.message ?? null)
const toast = ref<string | null>(null)
const showHelp = ref(false)
const showPrivacy = ref(false)
const sidebarSearch = ref<HTMLElement | null>(null)
const documentSearch = ref<DocumentSearchState | null>(null)
const isExporting = ref(false)
const exportError = ref<string | null>(null)
const fileExportAuthority = ref<WorkspaceExportAuthority | null>(null)
const jobState = computed(() => {
  const job = execution.job.value
  const status = execution.jobStatus.value
  const stage = execution.stage.value
  if (!job || !status || !stage) {
    return null
  }
  const isFailure =
    status === 'failed' || status === 'partial' || status === 'expired'
  return {
    sourceName: job.source_name,
    status,
    stage,
    progress: execution.progress.value,
    message: execution.message.value,
    failureMessage: isFailure ? execution.message.value : null,
    connectionMessage: execution.connectionMessage.value
  }
})

let loadedExecutionResult: VerificationResult | null = null
let toastTimer: ReturnType<typeof setTimeout> | null = null
let exportGeneration = 0
let recheckGeneration = 0
let disposed = false

const currentOptions = computed<AnalyzeOptions>(() => ({
  scenario: selectedScenario.value,
  enableSecurity: enableSecurity.value,
  enableSensitive: enableSensitive.value,
  enableAdExtreme: enableAdExtreme.value,
  ...(ocrLanguage.value === undefined ? {} : { ocrLanguage: ocrLanguage.value }),
  ...(enableExtendedRules.value === undefined ? {} : {
    enableExtendedRules: enableExtendedRules.value
  }),
  glossary: glossary.value,
  bannedWords: bannedWords.value
}))

const acceptedCount = computed(() => verificationWorkspace.summary.value.accepted)
const rejectedCount = computed(() => verificationWorkspace.summary.value.rejected)

const modifiedText = computed(() => verificationWorkspace.modifiedText.value)
const currentRevisionText = computed(
  () =>
    verificationWorkspace.currentRevision.value?.text ??
    verificationWorkspace.result.value?.text ??
    ''
)
const displayIssues = computed(() => {
  if (
    verificationWorkspace.requiresReverification.value ||
    verificationWorkspace.hasReplacementConflicts.value
  ) {
    // Manual edits and conflicting reviews do not have a safe source mapping.
    return []
  }
  return projectDocumentIssues(
    currentRevisionText.value,
    visibleIssues.value,
    verificationWorkspace.acceptedReplacements.value
  )
})
const activeDocumentSearch = computed(() =>
  documentSearch.value?.text === currentRevisionText.value
    ? documentSearch.value : null
)
function updateDocumentSearch(state: DocumentSearchState): void {
  documentSearch.value = state
  documentNavigationTarget.value = 'search'
}

function selectReviewIssue(issueId: string): void {
  documentNavigationTarget.value = 'issue'
  documentReveal.value += 1
  if (originalPreviewSource.value) reviewPane.value = 'document'
  issueNavigation.selectIssue(issueId)
}

const recheckedAuthorityRequiresRecheck = computed(() => {
  const currentResult = result.value
  return (
    fileExportAuthority.value !== null &&
    currentResult !== null &&
    currentResult.execution_mode === 'synchronous' &&
    currentRevisionText.value !== currentResult.text
  )
})
const selectedIssueState = computed<IssueState | null>(() => {
  const issueId = selectedIssueId.value
  return issueId === null
    ? null
    : issueStates.value[issueId] ?? 'pending'
})
const reviewActionsDisabled = computed(
  () =>
    isExporting.value ||
    verificationWorkspace.requiresReverification.value ||
    verificationWorkspace.visibleIssues.value.length === 0
)
const workspaceMutationLocked = computed(() => isExporting.value)
const exportBlockedReason = computed(() => {
  if (verificationWorkspace.hasReplacementConflicts.value) {
    return '存在重叠的已接受修改，请先解决冲突'
  }
  if (verificationWorkspace.requiresReverification.value) {
    return '当前文本已修改，请重新检查后再导出'
  }
  if (recheckedAuthorityRequiresRecheck.value) {
    return '重新检查后的审阅修改需要再次检查后再导出'
  }
  return null
})
const pdfExportNote = computed(() => {
  if (result.value?.file_type === 'png' || result.value?.file_type === 'jpg') {
    return '图片将导出为可编辑 DOCX，保留识别后的文字结构，不覆盖原图，也不保证还原原图版式。'
  }
  if (result.value?.file_type !== 'pdf') {
    return null
  }
  return result.value.pdf_metadata === undefined ||
    result.value.ocr_requirement !== undefined
    ? '扫描或混合 PDF 将导出为重建 DOCX，以保留 OCR 文本与版面。'
    : '文本 PDF 将保留 PDF 格式；纯插入修改可能被导出器明确拒绝。'
})
const statusAnnouncement = computed(() => {
  if (execution.isActive.value) {
    return execution.message.value || '正在执行文档检查'
  }
  if (toast.value) {
    return toast.value
  }
  if (result.value) {
    return `检查结果已就绪，共 ${result.value.summary.total} 项问题`
  }
  return '工作区已就绪'
})

async function handleUpload(file: File) {
  if (execution.isActive.value) {
    return
  }
  invalidateRecheckOperation()
  fileExportAuthority.value = null
  fileSource.value = file
  await execution.analyzeFile(file, currentOptions.value)
}

async function runTextAnalysis(submittedText: string) {
  if (execution.isActive.value) {
    return
  }
  const validation = validateDirectText(submittedText)
  if (validation !== null) {
    notify(
      validation === 'empty'
        ? '请先输入需要检查的文本'
        : validation === 'too_many_code_points'
          ? '文本不能超过 5,000,000 个 Unicode 字符'
          : '文本的 UTF-8 大小不能超过 25 MiB'
    )
    return
  }
  if (!verificationApi) {
    return
  }
  invalidateRecheckOperation()
  fileExportAuthority.value = null
  textInput.value = submittedText
  fileSource.value = null
  await execution.analyzeText(submittedText, currentOptions.value)
}

function setIssueState(issueId: string, state: IssueState) {
  verificationWorkspace.setIssueState(issueId, state)
  saveSession()
}

function setVisibleIssueStates(issueIds: string[], state: IssueState) {
  verificationWorkspace.setIssueStates(issueIds, state)
  saveSession()
}

function undoIssue(issueId: string) {
  verificationWorkspace.undoIssue(issueId)
  saveSession()
}

function undoBatch() {
  verificationWorkspace.undoLastBatch()
  saveSession()
}

function selectSuggestion(issueId: string, suggestion: string | null) {
  verificationWorkspace.selectSuggestion(issueId, suggestion)
  saveSession()
}

function applyOptions(options: AnalyzeOptions) {
  selectedScenario.value = options.scenario
  enableSecurity.value = options.enableSecurity
  enableSensitive.value = options.enableSensitive
  enableAdExtreme.value = options.enableAdExtreme
  ocrLanguage.value = options.ocrLanguage
  enableExtendedRules.value = options.enableExtendedRules
  glossary.value = options.glossary.map((term) => ({ ...term }))
  bannedWords.value = [...options.bannedWords]
}

function invalidateSourceNavigation(): void {
  selectedIssueId.value = null
  selectedLayer.value = 'all'
  selectedSeverity.value = 'all'
}

function saveSearchReplacement(
  text: string,
  kind: 'current' | 'all',
  count: number
): void {
  const revision = verificationWorkspace.saveManualEdit(text)
  if (revision === null) {
    return
  }
  invalidateSourceNavigation()
  saveSession()
  notify(
    kind === 'all'
      ? `已替换 ${count} 处，请重新检查以刷新问题位置`
      : '已替换当前匹配，请重新检查以刷新问题位置'
  )
}

function saveFreeEdit(text: string): void {
  const revision = verificationWorkspace.saveManualEdit(text)
  if (revision === null) {
    return
  }
  invalidateSourceNavigation()
  saveSession()
}

function undoTextEdit(): void {
  if (workspaceMutationLocked.value || isAnalyzing.value) {
    notify('正在处理文档，请稍后撤销修改')
    return
  }
  if (verificationWorkspace.undoTextEdit() === null) {
    notify('当前没有可撤销的文本修改')
    return
  }
  invalidateSourceNavigation()
  saveSession()
  notify(
    verificationWorkspace.requiresReverification.value
      ? '已撤销上一次文本修改，请重新检查以刷新问题位置'
      : '已撤销上一次文本修改，并恢复此前的审阅状态'
  )
}

function utf16IndexAtCodePointOffset(
  value: string,
  codePointOffset: number
): number | null {
  if (!Number.isInteger(codePointOffset) || codePointOffset < 0) {
    return null
  }
  let offset = 0
  let utf16Index = 0
  for (const character of value) {
    if (offset === codePointOffset) {
      return utf16Index
    }
    offset += 1
    utf16Index += character.length
  }
  return offset === codePointOffset ? utf16Index : null
}

async function recheck() {
  if (!verificationApi || !result.value || execution.isActive.value) {
    return
  }
  const source = result.value
  const exportAuthoritySource = captureFileExportAuthority()
  if (
    source.execution_mode === 'asynchronous' &&
    exportAuthoritySource === null
  ) {
    notify('当前文件缺少可验证的任务导出身份，无法重新检查')
    return
  }
  const priorAuthority = fileExportAuthority.value
  const submittedText = modifiedText.value
  const operation = beginRecheckOperation(source, submittedText)
  let boundAuthority: WorkspaceExportAuthority | null = null
  textInput.value = submittedText
  fileSource.value = null
  const transform = (checked: VerificationResult, grant?: string) => {
      if (!isCurrentRecheckSource(operation)) {
        throw new Error('重新检查请求已被新的工作区状态取代')
      }
      const transformed = {
        ...checked,
        filename: source.filename,
        file_id: null,
        file_ext: null
      }
      if (exportAuthoritySource !== null) {
        if (grant === undefined) {
          throw new Error('重新检查未返回服务端授权')
        }
        boundAuthority = bindWorkspaceExportAuthority(
          exportAuthoritySource,
          transformed,
          submittedText,
          grant
        )
        if (boundAuthority === null) {
          throw new Error('重新检查结果与提交文本或保留任务身份不匹配')
        }
      }
      operation.completedResultIdentity =
        verificationResultIdentity(transformed)
      return transformed
  }
  if (exportAuthoritySource === null) {
    await execution.analyzeText(
      textInput.value,
      currentOptions.value,
      transform
    )
  } else {
    await execution.recheckJob(
      exportAuthoritySource.jobId,
      textInput.value,
      currentOptions.value,
      transform
    )
  }
  if (!isCurrentRecheckCompletion(operation)) {
    return
  }
  fileExportAuthority.value = exportAuthoritySource === null
    ? null
    : execution.state.value === 'completed'
      ? boundAuthority
      : priorAuthority
  saveSession()
}

interface RecheckOperation {
  generation: number
  sourceResult: VerificationResult
  sourceRevision: DocumentRevision | null
  submittedText: string
  completedResultIdentity: string | null
}

function beginRecheckOperation(
  sourceResult: VerificationResult,
  submittedText: string
): RecheckOperation {
  recheckGeneration += 1
  return {
    generation: recheckGeneration,
    sourceResult,
    sourceRevision: verificationWorkspace.currentRevision.value,
    submittedText,
    completedResultIdentity: null
  }
}

function invalidateRecheckOperation(): void {
  recheckGeneration += 1
}

function isCurrentRecheckSource(operation: RecheckOperation): boolean {
  return (
    !disposed &&
    operation.generation === recheckGeneration &&
    result.value === operation.sourceResult &&
    verificationWorkspace.currentRevision.value ===
      operation.sourceRevision &&
    modifiedText.value === operation.submittedText
  )
}

function isCurrentRecheckCompletion(operation: RecheckOperation): boolean {
  if (disposed || operation.generation !== recheckGeneration) {
    return false
  }
  const currentResult = result.value
  if (currentResult === null) {
    return false
  }
  if (operation.completedResultIdentity !== null) {
    return (
      verificationResultIdentity(currentResult) ===
        operation.completedResultIdentity ||
      (
        execution.result.value !== null &&
        verificationResultIdentity(execution.result.value) ===
          operation.completedResultIdentity
      )
    )
  }
  return (
    currentResult === operation.sourceResult &&
    verificationWorkspace.currentRevision.value === operation.sourceRevision
  )
}

function verificationResultIdentity(value: VerificationResult): string {
  return [
    value.document_id,
    value.verification_run_id,
    value.source_version,
    value.execution_mode,
    value.text
  ].join('\u0000')
}

async function exportReport() {
  if (!verificationApi || !result.value) {
    return
  }
  exportError.value = null
  if (verificationWorkspace.requiresReverification.value) {
    notify('当前文本已修改，请重新检查后再导出报告')
    return
  }
  if (verificationWorkspace.hasReplacementConflicts.value) {
    notify('存在重叠的已接受修改，请先解决冲突后再导出')
    return
  }
  try {
    await verificationApi.exportReport(result.value)
    exportError.value = null
  } catch (error) {
    exportError.value =
      error instanceof Error ? error.message : '报告导出失败'
  }
}

async function exportModified() {
  if (!result.value) {
    return
  }
  exportError.value = null
  if (verificationWorkspace.hasReplacementConflicts.value) {
    notify('存在重叠的已接受修改，请先解决冲突后再导出')
    return
  }
  if (verificationWorkspace.requiresReverification.value) {
    notify('当前文本已修改，请重新检查后再导出')
    return
  }
  if (recheckedAuthorityRequiresRecheck.value) {
    notify('重新检查后的审阅修改需要再次检查后再导出')
    return
  }
  if (
    result.value.execution_mode === 'asynchronous'
  ) {
    const operation = beginExportOperation()
    if (!verificationApi || operation === null) {
      if (!verificationApi) {
        exportError.value = '异步文档导出服务不可用'
      }
      return
    }
    try {
      const revisionId = await persistDraftRevisionChain(operation)
      assertCurrentExportOperation(operation)
      await verificationApi.exportJob(
        operation.jobId,
        jobExportFormat(operation),
        revisionId,
        operation.trackChanges,
        () => isCurrentExportOperation(operation)
      )
      assertCurrentExportOperation(operation)
      notify('导出文件已生成')
    } catch (error) {
      if (
        !(error instanceof StaleExportOperationError) &&
        isCurrentExportOperation(operation)
      ) {
        exportError.value =
          error instanceof Error ? error.message : '修改文件导出失败'
      }
    } finally {
      if (isCurrentExportOperation(operation)) {
        isExporting.value = false
      }
    }
    return
  }
  if (fileExportAuthority.value !== null) {
    await exportRecheckedFile()
    return
  }
  if (!result.value.file_id || !verificationApi) {
    const text = trackChanges.value ? buildTrackedText() : modifiedText.value
    downloadText(text, `修改版_${result.value.filename.replace(/\.[^.]+$/, '')}.txt`)
    exportError.value = null
    return
  }

  function buildTrackedText() {
    if (!result.value) {
      return currentRevisionText.value
    }
    let text = result.value.text
    const accepted = verificationWorkspace.visibleIssues.value
      .filter(
        (issue) => issueStates.value[issue.issue_id] === 'accepted'
      )
      .filter((issue) => effectiveSuggestion(issue) !== null)
      .sort(
        (left, right) =>
          right.start - left.start ||
          right.end - left.end ||
          right.issue_id.localeCompare(left.issue_id)
      )
    for (const issue of accepted) {
      const start = utf16IndexAtCodePointOffset(text, issue.start)
      const end = utf16IndexAtCodePointOffset(text, issue.end)
      if (
        start === null ||
        end === null ||
        text.slice(start, end) !== issue.original
      ) {
        continue
      }
      const suggestion = effectiveSuggestion(issue)
      const tracked = `【删除：${issue.original}】【替换为：${
        suggestion || '（空）'
      }】`
      text = `${text.slice(0, start)}${tracked}${text.slice(end)}`
    }
    return text
  }
  const replacements = verificationWorkspace.visibleIssues.value
    .filter((issue) => issueStates.value[issue.issue_id] === 'accepted')
    .filter((issue) => effectiveSuggestion(issue) !== null)
    .map((issue) => ({
      original: issue.original,
      suggestion: effectiveSuggestion(issue) ?? '',
      position: issue.start,
      end_position: issue.end
    }))
  try {
    await verificationApi.exportOriginal(
      result.value,
      replacements,
      modifiedText.value,
      trackChanges.value
    )
    exportError.value = null
  } catch (error) {
    exportError.value =
      error instanceof Error ? error.message : '修改文件导出失败'
  }
}

function captureFileExportAuthority(): WorkspaceExportAuthoritySource | null {
  const currentResult = result.value
  if (
    fileExportAuthority.value !== null &&
    currentResult !== null &&
    isWorkspaceExportAuthorityBoundToResult(
      fileExportAuthority.value,
      currentResult
    )
  ) {
    return exportAuthoritySource(fileExportAuthority.value)
  }
  const jobId = execution.jobId.value
  if (
    currentResult === null ||
    currentResult.execution_mode !== 'asynchronous' ||
    jobId === null ||
    currentResult.document_id !== jobId
  ) {
    return null
  }
  const latestPersisted = [...verificationWorkspace.revisionChain.value]
    .reverse()
    .find((revision) => revision.persistence_state === 'persisted')
  return Object.freeze({
    jobId,
    documentId: currentResult.document_id,
    verificationRunId: currentResult.verification_run_id,
    sourceVersion: currentResult.source_version,
    fileType: currentResult.file_type,
    requiresOcrReconstruction: requiresReconstruction(currentResult),
    latestRevisionId: latestPersisted?.revision_id ?? null,
    latestRevisionNumber: latestPersisted?.revision_number ?? 0,
    persistedText: latestPersisted?.text ?? null
  })
}

function exportAuthoritySource(
  authority: WorkspaceExportAuthority
): WorkspaceExportAuthoritySource {
  return Object.freeze({
    jobId: authority.jobId,
    documentId: authority.documentId,
    verificationRunId: authority.verificationRunId,
    sourceVersion: authority.sourceVersion,
    fileType: authority.fileType,
    requiresOcrReconstruction: authority.requiresOcrReconstruction,
    latestRevisionId: authority.latestRevisionId,
    latestRevisionNumber: authority.latestRevisionNumber,
    persistedText: authority.persistedText
  })
}

interface RecheckedExportOperation {
  generation: number
  resultIdentity: string
  revisionIdentity: string
  authorityFingerprint: string
  authority: WorkspaceExportAuthority
  trackChanges: boolean
}

async function exportRecheckedFile(): Promise<void> {
  const operation = beginRecheckedExportOperation()
  if (operation === null || verificationApi === null) {
    if (verificationApi === null) {
      exportError.value = '异步文档导出服务不可用'
    }
    return
  }
  try {
    let revisionId = operation.authority.latestRevisionId
    if (
      revisionId === null ||
      operation.authority.persistedText !== currentRevisionText.value
    ) {
      const draft: DraftDocumentRevision = Object.freeze({
        revision_id: crypto.randomUUID(),
        document_id: operation.authority.documentId,
        verification_run_id: operation.authority.verificationRunId,
        source_version: operation.authority.sourceVersion,
        revision_number: null,
        created_at: new Date().toISOString(),
        parent_revision_id: operation.authority.latestRevisionId,
        persistence_state: 'draft',
        kind: 'manual',
        text: currentRevisionText.value
      })
      const currentResult = result.value
      if (currentResult === null) {
        throw new StaleExportOperationError(
          'Export operation was superseded.'
        )
      }
      const persisted = await verificationApi.persistRevision(
        operation.authority.jobId,
        draft,
        currentResult,
        recheckProvenance(operation.authority, currentResult)
      )
      assertCurrentRecheckedExportOperation(operation)
      const nextAuthority = bindWorkspaceExportAuthority({
        ...operation.authority,
        latestRevisionId: persisted.revision_id,
        latestRevisionNumber: persisted.revision_number,
        persistedText: persisted.text
      }, currentResult, currentResult.text, operation.authority.recheckGrant)
      if (nextAuthority === null) {
        throw new Error('保留的任务导出身份与重新检查结果不匹配')
      }
      fileExportAuthority.value = nextAuthority
      operation.authority = nextAuthority
      operation.authorityFingerprint = exportAuthorityFingerprint(nextAuthority)
      revisionId = persisted.revision_id
      saveSession()
    }
    assertCurrentRecheckedExportOperation(operation)
    await verificationApi.exportJob(
      operation.authority.jobId,
      operation.authority.requiresOcrReconstruction
        ? 'docx_reconstruction'
        : 'original_format',
      revisionId,
      operation.trackChanges,
      () => isCurrentRecheckedExportOperation(operation)
    )
    assertCurrentRecheckedExportOperation(operation)
    exportError.value = null
    notify('导出文件已生成')
  } catch (error) {
    if (
      !(error instanceof StaleExportOperationError) &&
      isCurrentRecheckedExportOperation(operation)
    ) {
      exportError.value =
        error instanceof Error ? error.message : '修改文件导出失败'
    }
  } finally {
    if (isCurrentRecheckedExportOperation(operation)) {
      isExporting.value = false
    }
  }
}

function beginRecheckedExportOperation(): RecheckedExportOperation | null {
  const currentResult = result.value
  const currentRevision = verificationWorkspace.currentRevision.value
  const authority = fileExportAuthority.value
  if (
    isExporting.value ||
    currentResult === null ||
    currentRevision === null ||
    authority === null ||
    recheckedAuthorityRequiresRecheck.value ||
    !isWorkspaceExportAuthorityBoundToResult(authority, currentResult)
  ) {
    exportError.value = recheckedAuthorityRequiresRecheck.value
      ? '重新检查后的审阅修改需要再次检查后再导出'
      : '异步文档缺少可验证的任务身份，无法导出'
    return null
  }
  exportGeneration += 1
  isExporting.value = true
  exportError.value = null
  return {
    generation: exportGeneration,
    resultIdentity: resultIdentityFingerprint(currentResult),
    revisionIdentity: revisionIdentityFingerprint(currentRevision),
    authorityFingerprint: exportAuthorityFingerprint(authority),
    authority,
    trackChanges: trackChanges.value
  }
}

function isCurrentRecheckedExportOperation(
  operation: RecheckedExportOperation
): boolean {
  const currentResult = result.value
  const currentRevision = verificationWorkspace.currentRevision.value
  const authority = fileExportAuthority.value
  return (
    !disposed &&
    operation.generation === exportGeneration &&
    currentResult !== null &&
    currentRevision !== null &&
    authority !== null &&
    isWorkspaceExportAuthorityBoundToResult(authority, currentResult) &&
    resultIdentityFingerprint(currentResult) === operation.resultIdentity &&
    revisionIdentityFingerprint(currentRevision) === operation.revisionIdentity &&
    exportAuthorityFingerprint(authority) === operation.authorityFingerprint
  )
}

function assertCurrentRecheckedExportOperation(
  operation: RecheckedExportOperation
): void {
  if (!isCurrentRecheckedExportOperation(operation)) {
    throw new StaleExportOperationError('Export operation was superseded.')
  }
}

function resultIdentityFingerprint(value: VerificationResult): string {
  return JSON.stringify([
    value.document_id,
    value.verification_run_id,
    value.source_version,
    value.text
  ])
}

function revisionIdentityFingerprint(
  value: Readonly<DocumentRevision>
): string {
  return JSON.stringify([
    value.revision_id,
    value.parent_revision_id,
    value.kind,
    value.text
  ])
}

function exportAuthorityFingerprint(
  value: WorkspaceExportAuthority
): string {
  return JSON.stringify([
    value.jobId,
    value.documentId,
    value.verificationRunId,
    value.sourceVersion,
    value.fileType,
    value.requiresOcrReconstruction,
    value.latestRevisionId,
    value.latestRevisionNumber,
    value.persistedText,
    value.recheckGrant
  ])
}

function recheckProvenance(
  authority: WorkspaceExportAuthority,
  currentResult: VerificationResult | null
) {
  if (currentResult === null) {
    throw new StaleExportOperationError('Export operation was superseded.')
  }
  return Object.freeze({
    grant: authority.recheckGrant,
    result_document_id: currentResult.document_id,
    result_verification_run_id: currentResult.verification_run_id,
    result_source_version: currentResult.source_version
  })
}

function jobExportFormat(
  operation: ExportOperation
): 'docx_reconstruction' | 'original_format' {
  if (operation.requiresOcrReconstruction) {
    return 'docx_reconstruction'
  }

  return 'original_format'
}

function requiresReconstruction(currentResult: VerificationResult): boolean {
  return (
    currentResult.file_type === 'png' ||
    currentResult.file_type === 'jpg' ||
    (currentResult.file_type === 'pdf' &&
      (currentResult.pdf_metadata === undefined ||
        currentResult.pdf_metadata.pages.some((page) => page.kind !== 'text')))
  )
}

interface ExportOperation {
  generation: number
  jobId: string
  documentId: string
  verificationRunId: string
  sourceVersion: string
  fileType: VerificationResult['file_type']
  requiresOcrReconstruction: boolean
  currentRevisionId: string | null
  currentRevisionText: string
  revisionFingerprint: string
  trackChanges: boolean
  chain: readonly Readonly<DocumentRevision>[]
  baseResult: VerificationResult
}

class StaleExportOperationError extends Error {}

function beginExportOperation(): ExportOperation | null {
  const currentResult = result.value
  const currentRevision = verificationWorkspace.currentRevision.value
  const jobId = execution.jobId.value
  if (
    isExporting.value ||
    currentResult === null ||
    currentRevision === null ||
    jobId === null ||
    currentResult.document_id !== jobId
  ) {
    exportError.value = '异步文档缺少可验证的任务身份，无法导出'
    return null
  }
  exportGeneration += 1
  isExporting.value = true
  exportError.value = null
  const chain = [...verificationWorkspace.revisionChain.value]
  return {
    generation: exportGeneration,
    jobId,
    documentId: currentResult.document_id,
    verificationRunId: currentResult.verification_run_id,
    sourceVersion: currentResult.source_version,
    fileType: currentResult.file_type,
    requiresOcrReconstruction: requiresReconstruction(currentResult),
    currentRevisionId: currentRevision.revision_id,
    currentRevisionText: currentRevision.text,
    revisionFingerprint: revisionChainFingerprint(chain),
    trackChanges: trackChanges.value,
    chain,
    baseResult: currentResult
  }
}

function revisionChainFingerprint(
  chain: readonly Readonly<{
    revision_id: string | null
    document_id: string
    verification_run_id: string
    source_version: string
    parent_revision_id: string | null
    kind: string
    text: string
  }>[]
): string {
  return JSON.stringify(
    chain.map((revision) => [
      revision.revision_id,
      revision.document_id,
      revision.verification_run_id,
      revision.source_version,
      revision.parent_revision_id,
      revision.kind,
      revision.text
    ])
  )
}

function isCurrentExportOperation(operation: ExportOperation): boolean {
  const currentResult = result.value
  const currentRevision = verificationWorkspace.currentRevision.value
  return (
    !disposed &&
    operation.generation === exportGeneration &&
    currentResult !== null &&
    currentRevision !== null &&
    execution.jobId.value === operation.jobId &&
    currentResult.document_id === operation.documentId &&
    currentResult.verification_run_id === operation.verificationRunId &&
    currentResult.source_version === operation.sourceVersion &&
    currentRevision.revision_id === operation.currentRevisionId &&
    currentRevision.text === operation.currentRevisionText &&
    revisionChainFingerprint(verificationWorkspace.revisionChain.value) ===
      operation.revisionFingerprint
  )
}

function assertCurrentExportOperation(operation: ExportOperation): void {
  if (!isCurrentExportOperation(operation)) {
    throw new StaleExportOperationError('Export operation was superseded.')
  }
}

function invalidateExportOperation(): void {
  exportGeneration += 1
  isExporting.value = false
}

async function persistDraftRevisionChain(
  operation: ExportOperation
): Promise<string | null> {
  if (!verificationApi) {
    throw new Error('修订持久化服务不可用')
  }
  for (const revision of operation.chain) {
    if (revision.persistence_state !== 'draft') {
      continue
    }
    const persisted = await verificationApi.persistRevision(
      operation.jobId,
      revision as DraftDocumentRevision,
      operation.baseResult
    )
    assertCurrentExportOperation(operation)
    if (!verificationWorkspace.hydratePersistedRevision(persisted)) {
      throw new Error('服务端修订与当前工作区不一致')
    }
    assertCurrentExportOperation(operation)
  }
  saveSession()
  const current = verificationWorkspace.currentRevision.value
  return current?.persistence_state === 'persisted'
    ? current.revision_id
    : null
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
  documentNavigationTarget.value = 'issue'
  trackChanges.value = false
  invalidateRecheckOperation()
  invalidateExportOperation()
  exportError.value = null
  fileExportAuthority.value = null
  execution.reset()
  verificationWorkspace.clearResult()
  loadedExecutionResult = null
  invalidateSourceNavigation()
  resultTab.value = 'issues'
  documentSearch.value = null
  fileSource.value = null
  textInput.value = ''
  workspaceSession.clear()
}

function toggleTheme() {
  theme.value = theme.value === 'light' ? 'dark' : 'light'
  applyTheme()
}

function applyTheme() {
  persistWorkspaceTheme(
    theme.value,
    window.localStorage,
    document.documentElement
  )
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
  workspaceSession.save({
    options: currentOptions.value,
    filters: {
      layer: selectedLayer.value,
      severity: selectedSeverity.value
    },
    viewMode: 'sentence',
    ui: {
      settingsTab: settingsTab.value,
      resultTab: resultTab.value,
      showFindReplace: true,
      trackChanges: trackChanges.value,
      selectedIssueId: selectedIssueId.value
    },
    jobId: execution.jobId.value,
    exportAuthority: fileExportAuthority.value
  })
}

function restoreSession() {
  const restored = workspaceSession.restore()
  if (restored === null) {
    return
  }
  applyOptions(restored.options)
  selectedLayer.value = restored.filters.layer
  selectedSeverity.value = restored.filters.severity
  settingsTab.value = restored.ui.settingsTab
  resultTab.value = restored.ui.resultTab
  // Tracking requires a fresh opt-in whenever a workspace is opened.
  trackChanges.value = false
  selectedIssueId.value = restored.ui.selectedIssueId
  fileExportAuthority.value = restored.exportAuthority
  if (
    restored.jobId !== null &&
    result.value !== null &&
    !execution.restoreJobContext(restored.jobId, result.value)
  ) {
    resetWorkspace()
    return
  }
  if (verificationWorkspace.requiresReverification.value) {
    invalidateSourceNavigation()
  }
}

function effectiveSuggestion(issue: VerificationIssue): string | null {
  return Object.prototype.hasOwnProperty.call(
    selectedSuggestions.value,
    issue.issue_id
  )
    ? selectedSuggestions.value[issue.issue_id]
    : issue.suggestion
}

async function handleKeyboard(event: KeyboardEvent) {
  if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === 'f' && result.value) {
    event.preventDefault()
    if (
      typeof window.matchMedia === 'function' &&
      window.matchMedia('(max-width: 760px)').matches
    ) {
      reviewPane.value = 'search'
    }
    await nextTick()
    const input = sidebarSearch.value?.querySelector<HTMLInputElement>('[data-search-input]')
    if (input) {
      revealWithinPane(input, sidebarSearch.value?.closest<HTMLElement>('.search-panel') ?? null)
      input.focus({ preventScroll: true })
    }
    return
  }
  if (event.key === 'Escape') {
    showHelp.value = false
    showPrivacy.value = false
  }
}

watch(
  [
    () => verificationWorkspace.currentRevision.value,
    () => issueStates.value,
    () => selectedSuggestions.value
  ],
  saveSession,
  { deep: true }
)

watch(
  [
    () => currentOptions.value,
    () => selectedLayer.value,
    () => selectedSeverity.value,
    () => settingsTab.value,
    () => resultTab.value,
    () => trackChanges.value,
    () => selectedIssueId.value,
    () => fileExportAuthority.value
  ],
  saveSession,
  { deep: true }
)

watch(
  [() => execution.state.value, () => execution.result.value],
  ([executionState, executionResult]) => {
    if (executionState === 'submitting') {
      invalidateExportOperation()
      loadedExecutionResult = null
      return
    }
    if (
      executionState !== 'completed' ||
      executionResult === null ||
      executionResult === loadedExecutionResult
    ) {
      return
    }
    loadedExecutionResult = executionResult
    invalidateExportOperation()
    exportError.value = null
    verificationWorkspace.loadResult(executionResult)
    invalidateSourceNavigation()
    resultTab.value = 'issues'
    documentSearch.value = null
    reviewPane.value = 'document'
    saveSession()
  }
)

onMounted(() => {
  theme.value = applyStoredWorkspaceTheme(
    window.localStorage,
    document.documentElement
  )
  applyTheme()
  restoreSession()
  document.addEventListener('keydown', handleKeyboard)
})

onBeforeUnmount(() => {
  invalidateRecheckOperation()
  disposed = true
  invalidateExportOperation()
  execution.dispose()
  document.removeEventListener('keydown', handleKeyboard)
  if (toastTimer) {
    window.clearTimeout(toastTimer)
  }
})
</script>

<template>
  <div class="shell" :class="{ 'is-reviewing': result !== null }">
    <WorkspaceHeader
      :theme="theme"
      :has-result="result !== null"
      :settings-open="settingsOpen"
      @reset="resetWorkspace"
      @open-settings="settingsOpen = true"
      @open-privacy="showPrivacy = true"
      @open-help="showHelp = true"
      @toggle-theme="toggleTheme"
    >
      <template #exports>
        <ExportPanel
          :track-changes="trackChanges"
          :report-disabled="exportBlockedReason !== null"
          :modified-disabled="exportBlockedReason !== null"
          :recheck-disabled="isAnalyzing"
          :busy="isExporting"
          :blocked-reason="exportBlockedReason"
          @update:track-changes="trackChanges = $event"
          @recheck="recheck"
          @export-report="exportReport"
          @export-modified="exportModified"
        />
        <small
          v-if="pdfExportNote"
          class="pdf-export-note"
        >
          {{ pdfExportNote }}
        </small>
      </template>
    </WorkspaceHeader>

    <p
      class="visually-hidden"
      data-workspace-status
      role="status"
      aria-live="polite"
      aria-atomic="true"
    >
      {{ statusAnnouncement }}
    </p>
    <p
      v-if="workspaceSession.warning.value"
      class="session-warning"
      data-session-warning
      role="alert"
      aria-live="assertive"
    >
      {{ workspaceSession.warning.value }}
    </p>
    <div
      v-if="exportError"
      class="export-error"
      data-export-error
      role="alert"
      aria-live="assertive"
    >
      <span>{{ exportError }}</span>
      <button
        type="button"
        data-dismiss-export-error
        aria-label="关闭导出错误"
        @click="exportError = null"
      >
        ×
      </button>
    </div>

    <WorkspaceSetup
      v-if="!result"
      v-model:text="textInput"
      :settings-open="settingsOpen"
      :options="currentOptions"
      :busy="isAnalyzing"
      :error="errorMessage"
      @update:options="applyOptions"
      @open-settings="settingsOpen = true"
      @submit-file="handleUpload"
      @submit-text="runTextAnalysis"
    >
      <template #progress>
        <div v-if="isAnalyzing && !jobState" class="loading-card" role="status" aria-live="polite">
          <div class="spinner"></div>
          <span>正在检查文本，请稍候…</span>
        </div>
        <JobProgress v-if="jobState" :state="jobState" />
      </template>
    </WorkspaceSetup>

    <main v-else class="review-workspace">
      <p
        v-if="errorMessage"
        class="execution-error"
        data-review-execution-error
        role="alert"
        aria-live="assertive"
      >
        {{ errorMessage }}
      </p>
      <p
        v-if="execution.jobStatus.value === 'partial'"
        class="execution-warning"
        data-execution-warning
        role="status"
        aria-live="polite"
      >
        {{ execution.message.value }}
      </p>
      <section class="review-summary" aria-label="检查概况">
        <div class="document-identity">
          <strong :title="result.filename">{{ result.filename }}</strong>
          <span>{{ result.stats.primary_count.toLocaleString() }} {{ result.stats.primary_label }}</span>
          <span>发现问题 <strong>{{ result.summary.total }}</strong></span>
        </div>
        <ReviewActions
          :selected-issue-id="selectedIssueId"
          :selected-issue-state="selectedIssueState"
          :visible-issue-ids="visibleIssues.map((issue) => issue.issue_id)"
          :summary="verificationWorkspace.summary.value"
          :has-conflicts="verificationWorkspace.hasReplacementConflicts.value"
          :conflict-issue-ids="
            verificationWorkspace.replacementConflictIssueIds.value
          "
          :can-undo-last-batch="canUndoLastBatch"
          :disabled="reviewActionsDisabled"
          @set-issue-state="setIssueState"
          @undo-issue="undoIssue"
          @set-visible-state="setVisibleIssueStates"
          @undo-batch="undoBatch"
        />
      </section>

      <div class="mobile-view-switch" aria-label="审阅视图">
        <button type="button" :aria-pressed="reviewPane === 'document'" @click="reviewPane = 'document'">文档</button>
        <button type="button" :aria-pressed="reviewPane === 'issues'" @click="reviewPane = 'issues'">问题 {{ visibleIssues.length }}</button>
        <button type="button" :aria-pressed="reviewPane === 'search'" @click="reviewPane = 'search'">查找替换</button>
      </div>
      <div class="review-grid" :data-review-pane="reviewPane">
        <aside class="search-panel" aria-label="查找替换工具">
          <header class="tools-header"><h2>查找替换</h2></header>
          <div ref="sidebarSearch" class="sidebar-search">
            <SearchReplacePanel
              :key="result.verification_run_id"
              :text="currentRevisionText"
              :disabled="workspaceMutationLocked"
              :can-undo="verificationWorkspace.canUndoTextEdit.value && !isAnalyzing"
              @replace-text="saveSearchReplacement"
              @search-change="updateDocumentSearch"
              @undo-text-edit="undoTextEdit"
            />
          </div>
        </aside>

        <section class="document-panel">
          <EditPreview
            :text="currentRevisionText"
            :title="verificationWorkspace.requiresReverification.value ? '当前手工修订' : '当前文档'"
            :disabled="workspaceMutationLocked"
            @save="saveFreeEdit"
          >
            <template #default="{ showIssueMarkers }">
              <OriginalDocumentPreview
                v-if="originalPreviewSource"
                :job-id="originalPreviewSource.jobId"
                :source-version="originalPreviewSource.sourceVersion"
                :text="currentRevisionText"
                :issues="showIssueMarkers ? displayIssues : []"
                :issue-states="currentIssueStates"
                :selected-issue-id="showIssueMarkers ? selectedIssueId : null"
                :reveal-key="`${reviewPane}:${documentReveal}`"
                :navigation-target="documentNavigationTarget"
                :search-matches="activeDocumentSearch?.matches"
                :active-search-match-index="activeDocumentSearch?.activeMatchIndex"
                @select-issue="selectReviewIssue"
              />
              <DocumentViewer
                v-else
                :result="result"
                :text="currentRevisionText"
                :issues="showIssueMarkers ? displayIssues : []"
                :issue-states="currentIssueStates"
                :selected-issue-id="showIssueMarkers ? selectedIssueId : null"
                mode="sentence"
                :data-current-revision="verificationWorkspace.requiresReverification.value ? '' : undefined"
                :reveal-key="`${reviewPane}:${documentReveal}`"
                :search-matches="activeDocumentSearch?.matches"
                :active-search-match-index="activeDocumentSearch?.activeMatchIndex"
                @select-issue="selectReviewIssue"
              />
            </template>
          </EditPreview>
        </section>

        <aside class="issues-panel">
          <header class="issues-header">
            <div class="side-tabs compact-tabs">
              <button :class="{ active: resultTab === 'issues' }" @click="resultTab = 'issues'">问题列表</button>
              <button :class="{ active: resultTab === 'summary' }" @click="resultTab = 'summary'">检查摘要</button>
            </div>
            <span>{{ visibleIssues.length }} 项</span>
          </header>

          <div
            v-if="
              resultTab === 'issues' &&
              verificationWorkspace.requiresReverification.value
            "
            class="reverification-state"
            role="status"
          >
            文本已修改。请重新检查后再使用问题筛选、定位和审阅操作。
          </div>
          <template v-else-if="resultTab === 'issues'">
            <IssueList
              :issues="visibleIssues"
              :selected-issue-id="selectedIssueId"
              :issue-states="currentIssueStates"
              :selected-suggestions="currentSelectedSuggestions"
              :selected-layer="selectedLayer"
              :selected-severity="selectedSeverity"
              :layer-options="layers"
              :type-labels="typeLabels"
              :reveal-key="reviewPane"
              :disabled="workspaceMutationLocked"
              @select-issue="selectReviewIssue"
              @update:selected-layer="selectedLayer = $event"
              @update:selected-severity="selectedSeverity = $event"
              @update:suggestion="selectSuggestion"
              @set-state="setIssueState"
            />
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

    <div v-if="toast" class="toast" role="status" aria-live="polite">{{ toast }}</div>
    <WorkspaceSettingsDialog
      v-model:settings-tab="settingsTab"
      :open="settingsOpen"
      :options="currentOptions"
      :busy="isAnalyzing"
      :has-result="result !== null"
      @close="settingsOpen = false"
      @update:options="applyOptions"
      @notify="notify"
    />
    <PrivacyDialog :open="showPrivacy" @close="showPrivacy = false" />
    <HelpDialog :open="showHelp" @close="showHelp = false" />
  </div>
</template>

<style scoped>
.shell { min-height: 100vh; }
.shell.is-reviewing { height: 100dvh; min-height: 0; display: flex; flex-direction: column; }
.shell.is-reviewing > :deep(.topbar) { flex-shrink: 0; }
.document-panel, .issues-panel, .search-panel { border: 1px solid var(--border); border-radius: 10px; background: var(--surface); overflow: hidden; }
.side-tabs { display: flex; gap: 5px; padding: 4px; border-radius: 12px; background: var(--surface-2); }
.side-tabs button { padding: 9px 17px; border: 0; border-radius: 9px; color: var(--muted); background: transparent; cursor: pointer; font-weight: 700; }
.side-tabs button.active { color: var(--primary); background: var(--surface); box-shadow: 0 3px 10px rgba(15,23,42,.08); }
input:focus, select:focus { border-color: var(--primary); outline: 3px solid rgba(37, 99, 235, .1); }
.loading-card { margin-top: 16px; padding: 14px; display: flex; align-items: center; gap: 12px; border-radius: 8px; background: var(--surface-2); color: var(--muted); font-size: 13px; }
.loading-card p { margin: 3px 0 0; font-size: 12px; }
.spinner { width: 27px; height: 27px; border: 3px solid #bfdbfe; border-top-color: #2563eb; border-radius: 50%; animation: spin .8s linear infinite; }
@keyframes spin { to { transform: rotate(360deg); } }
.review-workspace { isolation: isolate; flex: 1; min-height: 0; width: 100%; padding: 20px 24px; display: flex; flex-direction: column; gap: 12px; max-width: 1680px; margin: auto; }
.review-workspace > :not(.review-grid) { flex-shrink: 0; }
.review-summary { display: flex; align-items: center; justify-content: space-between; gap: 20px; padding: 0 2px 6px; }
.document-identity { min-width: 0; display: flex; align-items: baseline; gap: 12px; flex-wrap: wrap; }
.document-identity > strong { max-width: 420px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-size: 16px; font-weight: 600; }
.document-identity > span { flex: 0 0 auto; font-size: 11px; color: var(--muted); }
.execution-warning,
.execution-error {
  margin: 0;
  padding: 10px 13px;
  border-radius: 12px;
  font-size: 12px;
}
.execution-warning { border: 1px solid #f59e0b; color: #92400e; background: #fffbeb; }
.execution-error { border: 1px solid #ef4444; color: #991b1b; background: #fef2f2; }
.session-warning {
  margin: 12px 18px 0;
  padding: 10px 13px;
  border: 1px solid #ef4444;
  border-radius: 12px;
  color: #991b1b;
  background: #fef2f2;
  font-size: 12px;
}
.export-error {
  margin: 12px 18px 0;
  padding: 10px 13px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  border: 1px solid #ef4444;
  border-radius: 12px;
  color: #991b1b;
  background: #fef2f2;
  font-size: 12px;
}
.export-error button {
  border: 0;
  color: inherit;
  background: transparent;
  cursor: pointer;
  font-size: 18px;
}
.visually-hidden {
  width: 1px;
  height: 1px;
  padding: 0;
  position: absolute;
  overflow: hidden;
  clip: rect(0 0 0 0);
  white-space: nowrap;
  border: 0;
}
.sidebar-search { flex-shrink: 0; border-bottom: 1px solid var(--border); }
.issues-panel { overflow: auto; }
.issues-panel :deep(.issue-list-shell) { min-height: 220px; }
.issues-panel > .issues-header { flex-shrink: 0; }
.review-grid { flex: 1; min-height: 0; display: grid; grid-template-columns: minmax(240px, 280px) minmax(0, 1fr) minmax(300px, 340px); grid-template-areas: "search document issues"; gap: 16px; }
.document-panel, .issues-panel, .search-panel { min-width: 0; min-height: 0; display: flex; flex-direction: column; }
.document-panel { grid-area: document; }
.issues-panel { grid-area: issues; }
.search-panel { grid-area: search; overflow: auto; }
.tools-header { flex-shrink: 0; min-height: 54px; padding: 10px 15px; display: flex; align-items: center; border-bottom: 1px solid var(--border); }
.tools-header h2 { margin: 0; font-size: 13px; font-weight: 600; }
.search-panel :deep(.search-replace-panel) { grid-template-columns: minmax(0, 1fr); }
.search-panel :deep(.actions) { grid-template-columns: repeat(2, minmax(0, 1fr)); }
.issues-header { min-height: 54px; padding: 10px 15px; display: flex; align-items: center; justify-content: space-between; border-bottom: 1px solid var(--border); }
.document-content, .document-editor { flex: 1; min-height: 0; margin: 0; padding: 24px 28px; overflow: auto; white-space: pre-wrap; color: var(--text); background: var(--surface); font: 15px/2 ui-monospace, SFMono-Regular, Menlo, monospace; }
.document-content:not(.preview) { padding: 0; }
.document-content.preview { color: #075985; }
.document-editor { border: 0; border-radius: 0; resize: none; }
.current-revision-text {
  min-height: 100%;
  margin: 0;
  padding: 24px 28px;
  white-space: pre-wrap;
  color: var(--text);
  background: var(--surface);
  font: 15px/2 ui-monospace, SFMono-Regular, Menlo, monospace;
}
.reverification-state {
  margin: 14px;
  padding: 16px;
  border: 1px solid #f59e0b;
  border-radius: 12px;
  color: #92400e;
  background: #fffbeb;
  line-height: 1.7;
  font-size: 12px;
}
.compact-tabs { padding: 3px; }
.compact-tabs button { padding: 7px 10px; font-size: 12px; }
.issues-header > span { color: var(--muted); font-size: 12px; }
.summary-panel { min-height: 160px; padding: 16px; overflow: auto; }
.summary-panel h3 { margin: 8px 0 10px; font-size: 13px; }
.summary-row { padding: 8px 0; display: flex; justify-content: space-between; border-bottom: 1px solid var(--border); font-size: 12px; }
.toast { position: fixed; left: 50%; bottom: 28px; transform: translateX(-50%); z-index: 40; padding: 11px 18px; border-radius: 10px; color: white; background: #172033; box-shadow: var(--shadow); }
.mobile-view-switch { display: none; }
@media (min-width: 761px) and (max-width: 1199px) {
  .review-grid { grid-template-columns: minmax(160px, 180px) minmax(0, 1fr) minmax(200px, 240px); gap: 12px; }
}
@media (max-width: 760px) {
  .review-workspace { padding: 16px 12px; }
  .review-summary { align-items: flex-start; flex-direction: column; gap: 10px; }
  .document-identity { width: 100%; flex-wrap: wrap; }
  .document-identity > strong { max-width: 100%; }
  .mobile-view-switch { display: flex; padding: 3px; gap: 4px; background: var(--surface-2); border-radius: 8px; }
  .mobile-view-switch button { flex: 1; border: 0; border-radius: 6px; padding: 10px; background: transparent; cursor: pointer; font-size: 13px; }
  .mobile-view-switch button[aria-pressed='true'] { background: var(--surface); color: var(--primary); }
  .review-grid { grid-template-columns: minmax(0, 1fr); grid-template-areas: none; }
  .document-panel, .issues-panel, .search-panel { grid-area: auto; }
  .review-grid[data-review-pane='document'] > :not(.document-panel),
  .review-grid[data-review-pane='issues'] > :not(.issues-panel),
  .review-grid[data-review-pane='search'] > :not(.search-panel) { display: none; }
}
@media (prefers-reduced-motion: reduce) {
  *, *::before, *::after { animation-duration: .01ms !important; animation-iteration-count: 1 !important; }
}
</style>
