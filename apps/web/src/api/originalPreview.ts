import { readApiRequestError } from './errors'

const MAX_PREVIEW_BYTES = 25 * 1024 * 1024
const PREVIEW_MEDIA_TYPES = new Set(['application/pdf', 'image/png', 'image/jpeg'])

export async function fetchOriginalPreview(jobId: string, signal: AbortSignal): Promise<Blob> {
  const response = await fetch(`/api/v1/jobs/${encodeURIComponent(jobId)}/preview`, { signal })
  const body = await readPreviewBody(response, PREVIEW_MEDIA_TYPES)
  return new Blob([body.content], { type: body.mediaType })
}

async function readPreviewBody(
  response: Response, mediaTypes: ReadonlySet<string>
): Promise<{ content: Uint8Array<ArrayBuffer>; mediaType: string }> {
  if (!response.ok) throw await readApiRequestError(response, '无法加载原版式预览。')
  const mediaType = response.headers.get('content-type')?.split(';')[0].trim() ?? ''
  if (!mediaTypes.has(mediaType) || !response.body) {
    throw new Error('原版式预览格式无效。')
  }
  const reader = response.body.getReader()
  const chunks: Uint8Array<ArrayBuffer>[] = []
  let size = 0
  try {
    while (true) {
      const { done, value } = await reader.read()
      if (done) break
      size += value.byteLength
      if (size > MAX_PREVIEW_BYTES) {
        await reader.cancel()
        throw new Error('原版式预览超过 25 MiB 上限。')
      }
      chunks.push(new Uint8Array(value))
    }
  } finally {
    reader.releaseLock()
  }
  const content = new Uint8Array(size)
  let offset = 0
  for (const chunk of chunks) {
    content.set(chunk, offset)
    offset += chunk.length
  }
  return { content, mediaType }
}

export interface LayoutGlyph {
  start: number
  end: number
  x: number
  y: number
  width: number
  height: number
}

export interface LayoutPage {
  width: number
  height: number
  image: string
  text: string
  glyphs: LayoutGlyph[]
}

export interface ReviewLayout {
  pages: LayoutPage[]
  revision_applied: boolean
  notice: string | null
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null
}

function isPositive(value: unknown): value is number {
  return typeof value === 'number' && Number.isFinite(value) && value > 0
}

function isPage(value: unknown): value is LayoutPage {
  if (!isRecord(value) || !isPositive(value.width) || !isPositive(value.height) ||
    typeof value.image !== 'string' ||
    !/^data:image\/(?:png|svg\+xml);base64,[A-Za-z0-9+/]+=*$/.test(value.image) ||
    typeof value.text !== 'string' || !Array.isArray(value.glyphs)) return false
  const { width, height } = value
  return value.glyphs.every((glyph: unknown) =>
    isRecord(glyph) &&
    typeof glyph.start === 'number' && Number.isInteger(glyph.start) && glyph.start >= 0 &&
    typeof glyph.end === 'number' && Number.isInteger(glyph.end) && glyph.end > glyph.start &&
    typeof glyph.x === 'number' && Number.isFinite(glyph.x) && glyph.x >= 0 &&
    typeof glyph.y === 'number' && Number.isFinite(glyph.y) && glyph.y >= 0 &&
    isPositive(glyph.width) && isPositive(glyph.height) &&
    glyph.x + glyph.width <= width + 0.01 && glyph.y + glyph.height <= height + 0.01
  )
}

export async function fetchReviewLayout(
  jobId: string, sourceVersion: string, text: string, signal: AbortSignal
): Promise<ReviewLayout> {
  const response = await fetch(`/api/v1/jobs/${encodeURIComponent(jobId)}/preview/layout`, {
    method: 'POST', signal, headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ source_version: sourceVersion, text })
  })
  const body = await readPreviewBody(response, new Set(['application/json']))
  const value: unknown = JSON.parse(new TextDecoder('utf-8', { fatal: true }).decode(body.content))
  if (!isRecord(value) || typeof value.revision_applied !== 'boolean' ||
    (value.notice !== null && typeof value.notice !== 'string') ||
    !Array.isArray(value.pages) || value.pages.length > 80 || !value.pages.every(isPage)) {
    throw new Error('版式预览页面数据无效。')
  }
  return {
    revision_applied: value.revision_applied, notice: value.notice,
    pages: value.pages.map((page) => ({
      ...page, glyphs: [...page.glyphs].sort((a, b) => a.start - b.start)
    }))
  }
}
