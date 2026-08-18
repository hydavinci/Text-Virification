import type { IssueSeverity } from '../../types/review'

interface SeverityPresentation {
  readonly icon: string
  readonly text: string
}

const severityPresentationByLevel: Record<IssueSeverity, SeverityPresentation> = {
  error: { icon: '⛔', text: '错误' },
  warning: { icon: '⚠', text: '警告' },
  info: { icon: 'ℹ', text: '提示' }
}

export function describeSeverity(severity: IssueSeverity): SeverityPresentation {
  return severityPresentationByLevel[severity]
}
