import type {
  DocumentRef,
  DocumentVersion,
  Job,
  JobAccepted,
  Page,
  PdfExtraction,
  ProfileVersion,
  Project,
  ReadyHealth,
  Report,
  RubricVersion,
  SessionView,
  VersionRef,
} from './types'

export class ApiError extends Error {
  /** Backend error code (`conflict`, `validation_error`, `http_404`, …) when the server sent one. */
  code?: string
  /** `METHOD /path` of the failed request, kept only for the technical detail. */
  request?: string
  /** Spanish message that is already safe to show to people (only set for endpoints that send one). */
  userMessage?: string

  constructor(
    public status: number,
    message: string,
    public detail?: unknown,
    extra: { code?: string; request?: string; userMessage?: string } = {},
  ) {
    super(message)
    this.name = 'ApiError'
    this.code = extra.code
    this.request = extra.request
    this.userMessage = extra.userMessage
  }
}

export function commandKey(): string {
  return crypto.randomUUID()
}

export async function request<T>(
  path: string,
  options: RequestInit = {},
  key?: string,
): Promise<T> {
  const headers = new Headers(options.headers)
  if (options.body && !headers.has('Content-Type')) headers.set('Content-Type', 'application/json')
  if (key) headers.set('Idempotency-Key', key)
  const requestLabel = `${(options.method || 'GET').toUpperCase()} /api${path.split('?')[0]}`
  let response: Response
  try {
    response = await fetch(`/api${path}`, { ...options, headers })
  } catch {
    throw new ApiError(0, 'Network request failed', undefined, { request: requestLabel })
  }
  const data: unknown = await response.json().catch(() => null)
  if (!response.ok) {
    const payload = data as { detail?: unknown; message?: unknown; code?: unknown } | null
    const message =
      typeof payload?.detail === 'string'
        ? payload.detail
        : typeof payload?.message === 'string'
          ? payload.message
          : typeof payload?.detail === 'object' &&
              payload.detail !== null &&
              'message' in payload.detail
            ? String(payload.detail.message)
            : `HTTP ${response.status}`
    throw new ApiError(response.status, message, data, {
      code: typeof payload?.code === 'string' ? payload.code : undefined,
      request: requestLabel,
    })
  }
  return data as T
}

const json = (value: unknown) => JSON.stringify(value)
async function listAll<T>(
  path: string,
  signal?: AbortSignal,
  query: Record<string, string> = {},
): Promise<Page<T>> {
  const items: T[] = []
  let cursor: string | null = null
  const seen = new Set<string>()
  do {
    const params = new URLSearchParams({ limit: '100', ...query, ...(cursor ? { cursor } : {}) })
    const page: Page<T> = await request<Page<T>>(`${path}?${params}`, { signal })
    items.push(...page.items)
    cursor = page.next_cursor || null
    if (cursor && seen.has(cursor))
      throw new ApiError(502, 'Pagination cursor repeated', undefined, {
        code: 'pagination_loop',
        request: `GET /api${path}`,
      })
    if (cursor) seen.add(cursor)
  } while (cursor)
  return { items, next_cursor: null }
}
export const api = {
  health: (signal?: AbortSignal) => request<ReadyHealth>('/health/ready', { signal }),
  /** Active projects by default; `archived: true` lists only the archived ones. */
  projects: (signal?: AbortSignal, archived = false) =>
    listAll<Project>('/projects', signal, archived ? { archived: 'true' } : {}),
  project: (id: string, signal?: AbortSignal) => request<Project>(`/projects/${id}`, { signal }),
  updateProject: (id: string, input: { expected_revision: number; archived?: boolean }) =>
    request<Project>(`/projects/${id}`, { method: 'PATCH', body: json(input) }),
  createProject: (input: { title: string; context: string; objective: string }, key: string) =>
    request<Project>('/projects', { method: 'POST', body: json(input) }, key),
  documents: (projectId: string, signal?: AbortSignal) =>
    listAll<DocumentVersion>(`/projects/${projectId}/documents`, signal),
  document: (projectId: string, documentId: string, version: number, signal?: AbortSignal) =>
    request<DocumentVersion>(`/projects/${projectId}/documents/${documentId}/versions/${version}`, {
      signal,
    }),
  addDocument: (
    projectId: string,
    input: {
      title: string
      kind: 'source' | 'progress' | 'presentation'
      text: string
      document_id?: string
    },
    key: string,
  ) =>
    request<JobAccepted>(
      `/projects/${projectId}/documents`,
      { method: 'POST', body: json(input) },
      key,
    ),
  extractPdf: (projectId: string, file: File, signal?: AbortSignal) =>
    request<PdfExtraction>(
      `/projects/${projectId}/documents/extract?filename=${encodeURIComponent(file.name)}`,
      { method: 'POST', headers: { 'Content-Type': 'application/pdf' }, body: file, signal },
    ).catch((error: unknown) => {
      // The PDF endpoint explains 413/415/422 failures in Spanish already.
      if (error instanceof ApiError && [413, 415, 422].includes(error.status))
        error.userMessage = error.message
      throw error
    }),
  seedDemo: (projectId: string, key: string) =>
    request<{ items: JobAccepted[] }>(`/projects/${projectId}/demo`, { method: 'POST' }, key),
  profiles: (projectId: string, signal?: AbortSignal) =>
    listAll<ProfileVersion>(`/projects/${projectId}/profiles`, signal),
  saveProfile: (projectId: string, markdown: string, key: string, profileId?: string) =>
    request<ProfileVersion>(
      `/projects/${projectId}/profiles`,
      { method: 'POST', body: json({ markdown, ...(profileId ? { profile_id: profileId } : {}) }) },
      key,
    ),
  rubrics: (projectId: string, signal?: AbortSignal) =>
    listAll<RubricVersion>(`/projects/${projectId}/rubrics`, signal),
  saveRubric: (projectId: string, markdown: string, key: string, rubricId?: string) =>
    request<RubricVersion>(
      `/projects/${projectId}/rubrics`,
      { method: 'POST', body: json({ markdown, ...(rubricId ? { rubric_id: rubricId } : {}) }) },
      key,
    ),
  sessions: (projectId: string, signal?: AbortSignal) =>
    listAll<SessionView>(`/projects/${projectId}/sessions`, signal),
  session: (id: string, signal?: AbortSignal) =>
    request<SessionView>(`/sessions/${id}`, { signal }),
  createSession: (
    projectId: string,
    input: {
      objective: string
      presentation: string
      profile_versions: VersionRef[]
      rubric_version: VersionRef
      document_versions: DocumentRef[]
      previous_session_id: string | null
      max_questions: number
    },
    key: string,
  ) =>
    request<JobAccepted>(
      `/projects/${projectId}/sessions`,
      { method: 'POST', body: json(input) },
      key,
    ),
  respond: (
    id: string,
    input: { question_id: string; expected_revision: number; text: string },
    key: string,
  ) =>
    request<JobAccepted>(`/sessions/${id}/responses`, { method: 'POST', body: json(input) }, key),
  finish: (id: string, input: { question_id: string; expected_revision: number }, key: string) =>
    request<JobAccepted>(`/sessions/${id}/finish`, { method: 'POST', body: json(input) }, key),
  report: (id: string, signal?: AbortSignal) =>
    request<Report>(`/sessions/${id}/report`, { signal }),
  job: (id: string, signal?: AbortSignal) => request<Job>(`/jobs/${id}`, { signal }),
  retryJob: (id: string, attempt: number, key: string) =>
    request<JobAccepted>(
      `/jobs/${id}/retry`,
      { method: 'POST', body: json({ expected_attempt: attempt }) },
      key,
    ),
}
