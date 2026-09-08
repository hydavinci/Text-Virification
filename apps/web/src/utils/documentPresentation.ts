import type { VerificationIssue } from '../types/verification'

export interface DocumentTextReplacement {
  readonly start: number
  readonly end: number
  readonly text: string
}

export type DocumentIssue = Pick<
  VerificationIssue,
  'issue_id' | 'start' | 'end' | 'original' | 'message' | 'severity'
> & { sourceOriginal?: string }

// Replacements come from the workspace's sorted, conflict-free acceptance plan.
export function projectDocumentIssues(
  text: string,
  issues: readonly DocumentIssue[],
  replacements: readonly DocumentTextReplacement[]
): readonly DocumentIssue[] {
  if (replacements.length === 0) {
    return issues
  }
  let delta = 0
  const ranges = replacements.map((replacement) => {
    const displayStart = replacement.start + delta
    const displayEnd = displayStart + Array.from(replacement.text).length
    delta = displayEnd - replacement.end
    return { ...replacement, displayStart, displayEnd, delta }
  })
  const utf16Offsets = [0]
  for (const character of text) {
    utf16Offsets.push(utf16Offsets[utf16Offsets.length - 1] + character.length)
  }

  function project(position: number, edge: 'start' | 'end'): number {
    let low = 0
    let high = ranges.length
    while (low < high) {
      const middle = Math.floor((low + high) / 2)
      if (ranges[middle].start <= position) {
        low = middle + 1
      } else {
        high = middle
      }
    }
    const range = ranges[low - 1]
    if (!range) {
      return position
    }
    if (position >= range.end) {
      return position + range.delta
    }
    if (position === range.start || edge === 'start') {
      return range.displayStart
    }
    return range.displayEnd
  }

  return issues.map((issue) => {
    const start = project(issue.start, 'start')
    const end = project(issue.end, 'end')
    return {
      issue_id: issue.issue_id,
      message: issue.message,
      severity: issue.severity,
      sourceOriginal: issue.original,
      start,
      end,
      original: text.slice(utf16Offsets[start], utf16Offsets[end])
    }
  })
}
