import { afterEach, describe, expect, it, vi } from 'vitest'

import { fetchOriginalPreview, fetchReviewLayout } from '../src/api/originalPreview'

afterEach(() => vi.unstubAllGlobals())

describe('original preview API', () => {
  it('accepts vector page images for sharp text at any document zoom', async () => {
    const image = `data:image/svg+xml;base64,${btoa(
      '<svg xmlns="http://www.w3.org/2000/svg" width="600" height="800"><path d="M10 10h10v10H10z"/></svg>'
    )}`
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(Response.json({
      revision_applied: true, notice: null,
      pages: [{ image, width: 600, height: 800, text: '正文', glyphs: [] }]
    })))
    const layout = await fetchReviewLayout('job', 'version', '正文', new AbortController().signal)
    expect(layout.pages[0].image).toBe(image)
  })

  it('sends the current revision and retained source version for layout rendering', async () => {
    const fetch = vi.fn().mockResolvedValue(Response.json({
      pages: [], revision_applied: true, notice: null
    }))
    vi.stubGlobal('fetch', fetch)
    const signal = new AbortController().signal
    await fetchReviewLayout('job/id', 'sha256:source', '修订文本', signal)
    expect(fetch).toHaveBeenCalledWith('/api/v1/jobs/job%2Fid/preview/layout', {
      method: 'POST', signal, headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ source_version: 'sha256:source', text: '修订文本' })
    })
  })

  it('rejects active page images and invalid coordinate data', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(Response.json({
      revision_applied: true, notice: null,
      pages: [{ image: 'data:image/svg+xml,<svg onload="bad()"/>', width: 10, height: 10,
        text: '', glyphs: [] }]
    })))
    await expect(fetchReviewLayout('job', 'version', '', new AbortController().signal))
      .rejects.toThrow('页面数据无效')
  })
  it('fetches a bounded preview using an encoded job identity', async () => {
    const fetch = vi.fn().mockResolvedValue(new Response('%PDF-1.7', {
      headers: { 'Content-Type': 'application/pdf' }
    }))
    vi.stubGlobal('fetch', fetch)
    const signal = new AbortController().signal
    const preview = await fetchOriginalPreview('job/id', signal)
    expect(fetch).toHaveBeenCalledWith('/api/v1/jobs/job%2Fid/preview', { signal })
    expect(preview.type).toBe('application/pdf')
    expect(preview.size).toBe(8)
  })

  it('surfaces expired jobs instead of displaying a fabricated preview', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(JSON.stringify({
      detail: { code: 'job_result_expired', message: '原文件已过期' }
    }), { status: 410 })))
    await expect(fetchOriginalPreview('job', new AbortController().signal))
      .rejects.toThrow('原文件已过期')
  })

  it('refuses active HTML content', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response('<script>bad</script>', {
      headers: { 'Content-Type': 'text/html' }
    })))
    await expect(fetchOriginalPreview('job', new AbortController().signal))
      .rejects.toThrow('格式无效')
  })
})
