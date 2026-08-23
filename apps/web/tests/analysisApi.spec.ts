import { describe, expect, it, vi } from 'vitest'

import { createAnalysisApi } from '../src/api/analysis'
import type { DecisionCommand, IssueDecision } from '../src/types/analysis'

type AcceptedDecisionCommand = Extract<DecisionCommand, { action: 'accepted' }>
type IgnoredDecisionCommand = Extract<DecisionCommand, { action: 'ignored' }>
type UnreviewedDecisionCommand = Extract<DecisionCommand, { action: 'unreviewed' }>

function buildAcceptedDecisionCommand(
  overrides: Partial<Omit<AcceptedDecisionCommand, 'action'>> = {}
): AcceptedDecisionCommand {
  return {
    issue_id: '11111111-1111-1111-1111-111111111111',
    issue_version: 3,
    expected_revision: 1,
    action: 'accepted',
    replacement: '替换建议',
    suggestion_id: null,
    ...overrides
  }
}

function buildIgnoredDecisionCommand(
  overrides: Partial<Omit<IgnoredDecisionCommand, 'action'>> = {}
): IgnoredDecisionCommand {
  return {
    issue_id: '11111111-1111-1111-1111-111111111111',
    issue_version: 3,
    expected_revision: 1,
    action: 'ignored',
    replacement: null,
    suggestion_id: null,
    ...overrides
  }
}

function buildUnreviewedDecisionCommand(
  overrides: Partial<Omit<UnreviewedDecisionCommand, 'action'>> = {}
): UnreviewedDecisionCommand {
  return {
    issue_id: '11111111-1111-1111-1111-111111111111',
    issue_version: 3,
    expected_revision: 1,
    action: 'unreviewed',
    replacement: null,
    suggestion_id: null,
    ...overrides
  }
}

describe('createAnalysisApi', () => {
  it('requests document pages with encoded cursor and limit', async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({
        job_id: '6d96fe0f-f4fc-4b43-90fd-68e5bd09f21f',
        status: 'completed',
        document_id: 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa',
        file_type: 'docx',
        source_name: 'sample.docx',
        version: 2,
        metadata: { page_count: 3 },
        blocks: [
          {
            block_id: 'b-1',
            kind: 'paragraph',
            text: '第一段',
            page: 1,
            paragraph_index: 0,
            parent_id: null,
            style: { name: 'Normal' },
            source_locator: { path: 'body.0' }
          }
        ],
        total_blocks: 10,
        next_cursor: 'cursor-2',
        checker_failures: {
          security: {
            code: 'security_checker_failed',
            message: '安全检查暂不可用。'
          }
        }
      })
    })

    const result = await createAnalysisApi({ fetch: fetchMock }).getDocumentPage('job-1', {
      version_id: 'version/1',
      cursor: 'cursor-1',
      limit: 25
    })

    expect(fetchMock).toHaveBeenCalledWith(
      '/api/v1/jobs/job-1/document?version_id=version%2F1&cursor=cursor-1&limit=25',
      undefined
    )
    expect(result.blocks[0]?.kind).toBe('paragraph')
    expect(result.checker_failures.security?.code).toBe('security_checker_failed')
  })

  it('encodes issue filters and cursor', async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({
        job_id: '6d96fe0f-f4fc-4b43-90fd-68e5bd09f21f',
        status: 'partial',
        total: 2,
        items: [
          {
            issue_id: '11111111-1111-1111-1111-111111111111',
            document_id: 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa',
            document_version: 2,
            block_id: 'b-1',
            page: 1,
            start: 3,
            end: 5,
            original: '涉',
            suggestion: '敏',
            alternatives: ['敏'],
            type: 'sensitive_term',
            severity: 'warning',
            layer: 'security',
            message: '疑似敏感词。',
            rule_id: 'security-1',
            source: 'rule_checker',
            source_version: '2026.08',
            confidence: 0.93,
            auto_fixable: false,
            context: '上下文',
            decision: null
          }
        ],
        next_cursor: 'next',
        checker_failures: {}
      })
    })

    await createAnalysisApi({ fetch: fetchMock }).getIssues('job-1', {
      category: 'security',
      decision: 'unreviewed',
      version_id: 'version/1',
      cursor: 'next',
      limit: 50
    })

    expect(fetchMock).toHaveBeenCalledWith(
      '/api/v1/jobs/job-1/issues?category=security&decision=unreviewed&version_id=version%2F1&cursor=next&limit=50',
      undefined
    )
  })

  it('returns every decision outcome', async () => {
    const acceptedDecision = buildAcceptedDecisionCommand()
    const staleDecision = buildAcceptedDecisionCommand({
      issue_id: '22222222-2222-2222-2222-222222222222',
      replacement: '替换建议'
    })
    const missingDecision = buildIgnoredDecisionCommand({
      issue_id: '33333333-3333-3333-3333-333333333333'
    })
    const appliedDecision = {
      issue_id: acceptedDecision.issue_id,
      issue_version: acceptedDecision.issue_version,
      revision: acceptedDecision.expected_revision + 1,
      action: acceptedDecision.action,
      replacement: acceptedDecision.replacement,
      suggestion_id: acceptedDecision.suggestion_id,
      updated_at: '2026-08-15T12:00:00Z'
    } satisfies IssueDecision
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({
        batch_id: 'batch-1',
        outcomes: [
          {
            issue_id: acceptedDecision.issue_id,
            status: 'applied',
            code: null,
            decision: appliedDecision
          },
          {
            issue_id: staleDecision.issue_id,
            status: 'conflict',
            code: 'stale_issue_version',
            decision: null
          },
          {
            issue_id: missingDecision.issue_id,
            status: 'invalid',
            code: 'issue_not_found',
            decision: null
          }
        ]
      })
    })

    const result = await createAnalysisApi({ fetch: fetchMock }).putDecisions('job-1', [
      acceptedDecision,
      staleDecision,
      missingDecision
    ])

    expect(fetchMock).toHaveBeenCalledWith(
      '/api/v1/jobs/job-1/decisions',
      expect.objectContaining({
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          decisions: [acceptedDecision, staleDecision, missingDecision]
        })
      })
    )
    expect(result.outcomes.map((item) => item.status)).toEqual(['applied', 'conflict', 'invalid'])
  })

  it('rejects decision batches larger than 500 items', async () => {
    const fetchMock = vi.fn()
    const decisions = Array.from({ length: 501 }, (_, index) =>
      buildAcceptedDecisionCommand({
        issue_id: `00000000-0000-0000-0000-${String(index).padStart(12, '0')}`
      })
    )

    await expect(createAnalysisApi({ fetch: fetchMock }).putDecisions('job-1', decisions)).rejects
      .toThrow('Decisions must contain between 1 and 500 items.')
    expect(fetchMock).not.toHaveBeenCalled()
  })

  it('requests the analysis summary', async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({
        job_id: '6d96fe0f-f4fc-4b43-90fd-68e5bd09f21f',
        status: 'completed',
        total_issues: 3,
        by_category: {
          character: 0,
          vocabulary: 0,
          sentence: 0,
          format: 1,
          discourse: 0,
          security: 2
        },
        by_severity: {
          error: 1,
          warning: 2,
          info: 0
        },
        by_decision: {
          accepted: 1,
          ignored: 1,
          unreviewed: 1
        },
        checker_failures: {}
      })
    })

    const result = await createAnalysisApi({ fetch: fetchMock }).getSummary('job-1', {
      version_id: 'version/1'
    })

    expect(fetchMock).toHaveBeenCalledWith(
      '/api/v1/jobs/job-1/summary?version_id=version%2F1',
      undefined
    )
    expect(result.by_decision.unreviewed).toBe(1)
  })

  it('sends unreviewed decisions as command-only requests', async () => {
    const command = buildUnreviewedDecisionCommand()
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({
        batch_id: 'batch-1',
        outcomes: [
          {
            issue_id: command.issue_id,
            status: 'applied',
            code: null,
            decision: null
          }
        ]
      })
    })

    await createAnalysisApi({ fetch: fetchMock }).putDecisions('job-1', [command])

    expect(fetchMock).toHaveBeenCalledWith(
      '/api/v1/jobs/job-1/decisions',
      expect.objectContaining({
        method: 'PUT',
        body: JSON.stringify({ decisions: [command] })
      })
    )
  })
})
