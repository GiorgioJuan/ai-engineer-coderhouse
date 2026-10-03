import { useQuery } from '@tanstack/react-query'
import { api, ApiError } from './client'
import type { Citation, SessionStatus } from './types'

export const active = (status?: SessionStatus) => status === 'QUEUED' || status === 'RUNNING'

/** A missing project/session will not appear by retrying: show "not found" right away. */
const retryUnlessMissing = (count: number, error: Error) =>
  !(error instanceof ApiError && error.status === 404) && count < 1

export function useProjectData(id: string) {
  const project = useQuery({
    queryKey: ['project', id],
    queryFn: ({ signal }) => api.project(id, signal),
    retry: retryUnlessMissing,
  })
  const documents = useQuery({
    queryKey: ['documents', id],
    queryFn: ({ signal }) => api.documents(id, signal),
    // Mientras se indexan, se consulta cada 2 s; al volver a la pestaña, de inmediato.
    refetchOnWindowFocus: true,
    refetchInterval: (query) =>
      query.state.data?.items.some(
        (doc) => doc.index_status !== 'READY' && doc.index_status !== 'FAILED',
      )
        ? 2000
        : false,
  })
  const profiles = useQuery({
    queryKey: ['profiles', id],
    queryFn: ({ signal }) => api.profiles(id, signal),
  })
  const rubrics = useQuery({
    queryKey: ['rubrics', id],
    queryFn: ({ signal }) => api.rubrics(id, signal),
  })
  const sessions = useQuery({
    queryKey: ['sessions', id],
    queryFn: ({ signal }) => api.sessions(id, signal),
  })
  return { project, documents, profiles, rubrics, sessions }
}

/**
 * Polls while the session is being prepared. TanStack Query pauses the interval by itself
 * while the tab is hidden (`refetchIntervalInBackground` is false) and, thanks to
 * `refetchOnWindowFocus`, refreshes immediately when the person comes back.
 */
export function useSession(id: string) {
  return useQuery({
    queryKey: ['session', id],
    queryFn: ({ signal }) => api.session(id, signal),
    refetchOnWindowFocus: true,
    staleTime: 0,
    retry: retryUnlessMissing,
    refetchInterval: (query) =>
      active(query.state.data?.status)
        ? Math.min(5000, 1000 + query.state.dataUpdateCount * 250)
        : false,
  })
}

/** Resolves "document title · section" labels for citations of one project. */
export function useCitationLabels(projectId: string) {
  const documents = useQuery({
    queryKey: ['documents', projectId],
    queryFn: ({ signal }) => api.documents(projectId, signal),
    enabled: !!projectId,
  })
  const items = documents.data?.items
  const titleOf = (citation: Pick<Citation, 'document_id' | 'version'>) =>
    items?.find(
      (doc) => doc.document_id === citation.document_id && doc.version === citation.version,
    )?.title ||
    items?.find((doc) => doc.document_id === citation.document_id)?.title ||
    ''
  return {
    titleOf,
    label: (citation: Citation) => citationLabel(titleOf(citation), citation.section),
  }
}

export function citationLabel(title: string, section?: string | null) {
  const part = section && section.trim() && section.trim() !== 'Documento' ? section.trim() : ''
  if (title && part) return `${title} · ${part}`
  return title || part || 'Fragmento de un material'
}
