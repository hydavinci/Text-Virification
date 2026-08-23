import { describe, expect, it, vi } from 'vitest'

import { createExportsApi } from '../src/api/exports'
import { ApiError } from '../src/types/api'

describe('createExportsApi', () => {
  it('posts export requests and returns dispatch status', async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({
        export_id: 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa',
        job_id: '6d96fe0f-f4fc-4b43-90fd-68e5bd09f21f',
        export_type: 'html_report',
        status: 'queued',
        file_name: 'report.html',
        warnings: [],
        error_code: null,
        error_message: null,
        created_at: '2026-08-15T12:00:00Z',
        updated_at: '2026-08-15T12:00:00Z',
        expires_at: '2026-08-16T12:00:00Z',
        dispatch_status: 'dispatched'
      })
    })

    const result = await createExportsApi({ fetch: fetchMock }).create('job-1', {
      type: 'html_report',
      version_id: 'version-1',
      confirm_warnings: true
    })

    expect(fetchMock).toHaveBeenCalledWith(
      '/api/v1/jobs/job-1/exports',
      expect.objectContaining({
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          type: 'html_report',
          version_id: 'version-1',
          confirm_warnings: true
        })
      })
    )
    expect(result.dispatch_status).toBe('dispatched')
  })

  it('preserves structured confirmation warnings', async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: false,
      status: 409,
      json: async () => ({
        detail: {
          code: 'export_confirmation_required',
          message: '检测到无法自动应用的 DOCX 修改，请确认警告后重试。',
          warnings: [
            {
              code: 'cannot_apply_run_split',
              message: '该段落跨多个样式片段，暂不支持自动替换。',
              issue_id: '11111111-1111-1111-1111-111111111111',
              block_id: 'b-1'
            }
          ]
        }
      })
    })

    const request = createExportsApi({ fetch: fetchMock }).create('job-1', {
      type: 'modified_document',
      confirm_warnings: false
    })

    await expect(request).rejects.toBeInstanceOf(Error)
    await expect(request).rejects.toBeInstanceOf(ApiError)
    await expect(request).rejects.toMatchObject({
      message: '检测到无法自动应用的 DOCX 修改，请确认警告后重试。',
      status: 409,
      detail: {
        code: 'export_confirmation_required',
        message: '检测到无法自动应用的 DOCX 修改，请确认警告后重试。',
        warnings: [
          {
            code: 'cannot_apply_run_split',
            message: '该段落跨多个样式片段，暂不支持自动替换。',
            issue_id: '11111111-1111-1111-1111-111111111111',
            block_id: 'b-1'
          }
        ]
      }
    })
  })

  it('falls back when confirmation warnings are malformed', async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: false,
      status: 409,
      json: async () => ({
        detail: {
          code: 'export_confirmation_required',
          message: '检测到无法自动应用的 DOCX 修改，请确认警告后重试。',
          warnings: [
            {
              code: 'cannot_apply_run_split',
              message: '该段落跨多个样式片段，暂不支持自动替换。',
              issue_id: 123,
              block_id: 'b-1'
            }
          ]
        }
      })
    })

    const error = await createExportsApi({ fetch: fetchMock })
      .create('job-1', {
        type: 'modified_document',
        confirm_warnings: false
      })
      .then(
        () => {
          throw new Error('Expected export confirmation request to reject.')
        },
        (reason) => reason as ApiError
      )

    expect(error).toBeInstanceOf(ApiError)
    expect(error).toMatchObject({
      status: 409,
      detail: {
        code: 'request_failed',
        message: 'Request failed with status 409.'
      }
    })
    expect(error.detail.warnings).toBeUndefined()
  })

  it('gets export status', async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({
        export_id: 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa',
        job_id: '6d96fe0f-f4fc-4b43-90fd-68e5bd09f21f',
        export_type: 'pdf_report',
        status: 'completed',
        file_name: 'report.pdf',
        warnings: [],
        error_code: null,
        error_message: null,
        created_at: '2026-08-15T12:00:00Z',
        updated_at: '2026-08-15T12:00:30Z',
        expires_at: '2026-08-16T12:00:00Z'
      })
    })

    const result = await createExportsApi({ fetch: fetchMock }).get('job-1', 'export-1')

    expect(fetchMock).toHaveBeenCalledWith('/api/v1/jobs/job-1/exports/export-1', undefined)
    expect(result.status).toBe('completed')
  })

  it('builds a same-origin export download URL', () => {
    expect(createExportsApi().downloadUrl('job 1', 'export/1')).toBe(
      '/api/v1/jobs/job%201/exports/export%2F1/download'
    )
  })
})
