import type {
  CheckCategory,
  IssueDecisionState
} from '../../types/review'

const CATEGORY_LABELS: Record<CheckCategory, string> = {
  character: '文字',
  vocabulary: '词汇',
  sentence: '句子',
  format: '格式',
  discourse: '篇章',
  security: '安全'
}

const DECISION_LABELS: Record<IssueDecisionState, string> = {
  accepted: '已接受',
  ignored: '已忽略',
  unreviewed: '未处理'
}

const ISSUE_TYPE_LABELS: Record<string, string> = {
  literal: '规则匹配',
  dictionary_literal: '词典词条',
  dictionary_regex: '词典正则',
  regex: '正则规则',
  typo: '错别字',
  ...CATEGORY_LABELS
}

export function categoryLabel(category: string): string {
  return CATEGORY_LABELS[category as CheckCategory] ?? '其他类别'
}

export function decisionStateLabel(decision: IssueDecisionState): string {
  return DECISION_LABELS[decision]
}

export function issueTypeLabel(issueType: string): string {
  return ISSUE_TYPE_LABELS[issueType] ?? '其他问题'
}
