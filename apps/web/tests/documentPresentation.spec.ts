import { describe, expect, it } from 'vitest'

import { projectDocumentIssues, type DocumentIssue } from '../src/utils/documentPresentation'

function issue(start: number, end: number): DocumentIssue {
  return {
    issue_id: `${start}-${end}`, start, end, original: 'source',
    message: 'Check wording', severity: 'warning'
  }
}

describe('document presentation', () => {
  it('projects boundaries, overlaps, and deletions using code-point offsets without changing source issues', () => {
    const issues = [issue(1, 3), issue(3, 5), issue(2, 4), issue(6, 7)]
    const snapshot = structuredClone(issues)
    const displayed = projectDocumentIssues('\u{1f600}LONG\ncde', issues, [
      { start: 1, end: 3, text: 'LONG\n' },
      { start: 6, end: 7, text: '' }
    ])
    expect(displayed.map(({ start, end, original }) => ({ start, end, original }))).toEqual([
      { start: 1, end: 6, original: 'LONG\n' },
      { start: 6, end: 8, original: 'cd' },
      { start: 1, end: 7, original: 'LONG\nc' },
      { start: 9, end: 9, original: '' }
    ])
    expect(issues).toEqual(snapshot)
  })

  it('retains the original issue collection when no replacement is applied', () => {
    const issues = [issue(0, 1)]
    expect(projectDocumentIssues('source', issues, [])).toBe(issues)
  })
})
