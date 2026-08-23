import type { InjectionKey } from 'vue'

import { requestJson, type RequestJsonDependencies } from './client'
import type {
  AnalysisSummaryResponse,
  AnalysisSummaryQuery,
  DecisionBatchResponse,
  DecisionCommand,
  DocumentPageQuery,
  DocumentPageResponse,
  IssuesQuery,
  IssuePageResponse
} from '../types/analysis'

const MAX_DECISIONS_PER_BATCH = 500

export interface AnalysisApi {
  getDocumentPage(jobId: string, query?: DocumentPageQuery): Promise<DocumentPageResponse>
  getIssues(jobId: string, query?: IssuesQuery): Promise<IssuePageResponse>
  getSummary(jobId: string, query?: AnalysisSummaryQuery): Promise<AnalysisSummaryResponse>
  putDecisions(jobId: string, decisions: DecisionCommand[]): Promise<DecisionBatchResponse>
}

interface AnalysisApiDependencies extends RequestJsonDependencies {}

export const analysisApiKey: InjectionKey<AnalysisApi> = Symbol('analysisApi')

export function createAnalysisApi(
  overrides: Partial<AnalysisApiDependencies> = {}
): AnalysisApi {
  const dependencies: AnalysisApiDependencies = {
    fetch: overrides.fetch ?? fetch
  }

  return {
    getDocumentPage(jobId, query) {
      return requestJson<DocumentPageResponse>(
        dependencies,
        withSearch(
          `/jobs/${encodeURIComponent(jobId)}/document`,
          buildDocumentQueryParams(query)
        )
      )
    },
    getIssues(jobId, query) {
      return requestJson<IssuePageResponse>(
        dependencies,
        withSearch(`/jobs/${encodeURIComponent(jobId)}/issues`, buildIssuesQueryParams(query))
      )
    },
    getSummary(jobId, query) {
      return requestJson<AnalysisSummaryResponse>(
        dependencies,
        withSearch(`/jobs/${encodeURIComponent(jobId)}/summary`, buildSummaryQueryParams(query))
      )
    },
    async putDecisions(jobId, decisions) {
      assertDecisionBatchSize(decisions)

      return requestJson<DecisionBatchResponse>(
        dependencies,
        `/jobs/${encodeURIComponent(jobId)}/decisions`,
        {
          method: 'PUT',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ decisions })
        }
      )
    }
  }
}

function buildDocumentQueryParams(query: DocumentPageQuery | undefined): URLSearchParams {
  const params = new URLSearchParams()
  if (query?.version_id) {
    params.set('version_id', query.version_id)
  }
  if (query?.cursor) {
    params.set('cursor', query.cursor)
  }
  if (query?.limit !== undefined) {
    params.set('limit', String(query.limit))
  }
  return params
}

function buildIssuesQueryParams(query: IssuesQuery | undefined): URLSearchParams {
  const params = new URLSearchParams()

  if (query?.category) {
    params.set('category', query.category)
  }
  if (query?.severity) {
    params.set('severity', query.severity)
  }
  if (query?.decision) {
    params.set('decision', query.decision)
  }
  if (query?.search) {
    params.set('search', query.search)
  }
  if (query?.version_id) {
    params.set('version_id', query.version_id)
  }
  if (query?.cursor) {
    params.set('cursor', query.cursor)
  }
  if (query?.limit !== undefined) {
    params.set('limit', String(query.limit))
  }

  return params
}

function buildSummaryQueryParams(query: AnalysisSummaryQuery | undefined): URLSearchParams {
  const params = new URLSearchParams()
  if (query?.version_id) {
    params.set('version_id', query.version_id)
  }
  return params
}

function withSearch(path: string, params: URLSearchParams): string {
  const query = params.toString()
  return query ? `${path}?${query}` : path
}

function assertDecisionBatchSize(decisions: DecisionCommand[]): void {
  if (decisions.length < 1 || decisions.length > MAX_DECISIONS_PER_BATCH) {
    throw new RangeError('Decisions must contain between 1 and 500 items.')
  }
}
