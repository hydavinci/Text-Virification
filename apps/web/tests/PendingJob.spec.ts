import { beforeEach, describe, expect, it } from 'vitest'
import { usePendingJob, PENDING_JOB_KEY } from '../src/composables/usePendingJob'
import { createDefaultAnalyzeOptions } from '../src/api/analyzeOptions'

const metadata = () => ({
  jobId: '11111111-1111-4111-8111-111111111111',
  sourceName: 'synthetic.pdf', sizeBytes: 1024,
  expiresAt: new Date(Date.now() + 60_000).toISOString(),
  options: createDefaultAnalyzeOptions()
})

describe('pending task persistence', () => {
  beforeEach(() => sessionStorage.clear())
  it('restores bounded metadata and settings without file contents', () => {
    const pending = usePendingJob(sessionStorage)
    expect(pending.save(metadata())).toBe(true)
    const restored = usePendingJob(sessionStorage).restore()
    expect(restored?.jobId).toBe(metadata().jobId)
    expect(restored?.sourceName).toBe('synthetic.pdf')
    expect(Object.keys(restored!).sort()).toEqual(['expiresAt', 'jobId', 'options', 'sizeBytes', 'sourceName'])
  })
  it.each(['broken', JSON.stringify({ version: 999 }), 'x'.repeat(140_000)])('discards invalid state', (raw) => {
    sessionStorage.setItem(PENDING_JOB_KEY, raw)
    const pending = usePendingJob(sessionStorage)
    expect(pending.restore()).toBeNull()
    expect(sessionStorage.getItem(PENDING_JOB_KEY)).toBeNull()
    expect(pending.warning.value).toBeTruthy()
  })
  it('discards expired jobs and clears explicitly', () => {
    const pending = usePendingJob(sessionStorage)
    expect(pending.save({ ...metadata(), expiresAt: new Date(Date.now() - 1).toISOString() })).toBe(false)
    expect(pending.save(metadata())).toBe(true)
    pending.clear()
    expect(usePendingJob(sessionStorage).restore()).toBeNull()
  })
})
