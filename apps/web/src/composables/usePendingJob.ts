import { computed, shallowRef, ref } from 'vue'
import { createAnalyzeOptionsSnapshot } from '../api/analyzeOptions'
import type { AnalyzeOptions } from '../types/verification'

export const PENDING_JOB_KEY = 'text-verification-pending-job'
const MAX_BYTES = 128 * 1024
const MAX_AGE_MS = 24 * 60 * 60 * 1000
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i

export interface PendingJob {
  jobId: string
  sourceName: string
  sizeBytes: number
  expiresAt: string
  options: AnalyzeOptions
}

export function usePendingJob(storage: Storage) {
  const record = shallowRef<PendingJob | null>(null)
  const warning = ref<string | null>(null)

  function clear(): void {
    record.value = null
    try {
      storage.removeItem(PENDING_JOB_KEY)
      warning.value = null
    } catch {
      warning.value = '无法清除浏览器任务记录。'
    }
  }

  function parse(value: unknown): PendingJob {
    if (typeof value !== 'object' || value === null) throw new Error()
    const item = value as Record<string, unknown>
    if (Object.keys(item).sort().join(',') !== 'expiresAt,jobId,options,sizeBytes,sourceName' ||
      typeof item.jobId !== 'string' || !UUID.test(item.jobId) ||
      typeof item.sourceName !== 'string' || item.sourceName.length < 1 || item.sourceName.length > 1024 ||
      typeof item.sizeBytes !== 'number' || !Number.isSafeInteger(item.sizeBytes) ||
      item.sizeBytes < 0 || item.sizeBytes > 25 * 1024 * 1024 ||
      typeof item.expiresAt !== 'string' || !Number.isFinite(Date.parse(item.expiresAt)) ||
      Date.parse(item.expiresAt) <= Date.now() || Date.parse(item.expiresAt) > Date.now() + MAX_AGE_MS
    ) throw new Error()
    return Object.freeze({
      jobId: item.jobId, sourceName: item.sourceName, sizeBytes: item.sizeBytes,
      expiresAt: item.expiresAt,
      options: createAnalyzeOptionsSnapshot(item.options as AnalyzeOptions, 'persisted')
    })
  }

  function save(value: PendingJob): boolean {
    try {
      const next = parse(value)
      const raw = JSON.stringify({ version: 1, task: next })
      if (new TextEncoder().encode(raw).byteLength > MAX_BYTES) throw new Error()
      record.value = next
      storage.setItem(PENDING_JOB_KEY, raw)
      warning.value = null
      return true
    } catch {
      warning.value = '无法保存待完成任务记录；请勿刷新页面，以免丢失任务连接。'
      return false
    }
  }

  function restore(): PendingJob | null {
    try {
      const raw = storage.getItem(PENDING_JOB_KEY)
      if (raw === null) return null
      if (raw.length > MAX_BYTES || new TextEncoder().encode(raw).byteLength > MAX_BYTES) throw new Error()
      const value: unknown = JSON.parse(raw)
      if (typeof value !== 'object' || value === null ||
        Object.keys(value).sort().join(',') !== 'task,version' ||
        (value as { version: unknown }).version !== 1) throw new Error()
      record.value = parse((value as { task: unknown }).task)
      warning.value = null
      return record.value
    } catch {
      clear()
      warning.value = '已保存的任务记录无效或已过期，请重新选择文件。'
      return null
    }
  }

  return { record: computed(() => record.value), warning: computed(() => warning.value), save, restore, clear }
}
