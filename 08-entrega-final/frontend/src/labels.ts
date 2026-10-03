import type { CriterionFeedback, DocumentVersion, Job, SessionStatus } from './api/types'

/**
 * Every enum / id the API returns, translated once. UI code must go through these
 * helpers so that people never read `source`, `WAITING_RESPONSE` or a UUID.
 * Unknown values fall back to a readable label instead of rendering empty.
 */
export type Tone = 'neutral' | 'good' | 'busy' | 'bad'
type Entry = { label: string; tone: Tone }

function lookup<K extends string>(
  table: Record<K, Entry>,
  value: string | null | undefined,
  fallbackLabel: string,
): Entry {
  if (value && Object.prototype.hasOwnProperty.call(table, value)) return table[value as K]
  return { label: fallbackLabel, tone: 'neutral' }
}

// Document kind --------------------------------------------------------------------
export type DocumentKind = DocumentVersion['kind']
const documentKinds: Record<DocumentKind, string> = {
  source: 'Fuente',
  progress: 'Avance',
  presentation: 'Presentación',
}
export const documentKindOptions = Object.entries(documentKinds) as Array<[DocumentKind, string]>
export const documentKindLabel = (kind?: string | null) =>
  (kind && documentKinds[kind as DocumentKind]) || 'Material'

// Document (indexing) status -------------------------------------------------------
type DocumentStatus = DocumentVersion['index_status']
const documentStatuses: Record<DocumentStatus, Entry> = {
  QUEUED: { label: 'En cola', tone: 'busy' },
  RUNNING: { label: 'Preparando', tone: 'busy' },
  READY: { label: 'Listo', tone: 'good' },
  FAILED: { label: 'Falló', tone: 'bad' },
}
export const documentStatus = (status?: string | null) =>
  lookup(documentStatuses, status, 'Preparando')

export const documentIsPending = (status?: string | null) => documentStatus(status).tone === 'busy'

/** Plain-language explanation shown under a material that is not ready. */
export function documentStatusNote(status?: string | null): string | null {
  const { tone } = documentStatus(status)
  if (tone === 'good') return null
  if (tone === 'bad')
    return 'No pudimos preparar este material, así que el panel todavía no puede consultarlo. Subí una nueva versión para reintentarlo.'
  return 'Lo estamos leyendo para que el panel pueda citarlo. Suele tardar menos de un minuto y esta lista se actualiza sola.'
}

// Session status -------------------------------------------------------------------
const sessionStatuses: Record<SessionStatus, Entry> = {
  QUEUED: { label: 'En cola', tone: 'busy' },
  RUNNING: { label: 'Preparando', tone: 'busy' },
  WAITING_RESPONSE: { label: 'Tu turno', tone: 'busy' },
  COMPLETED: { label: 'Terminada', tone: 'good' },
  FAILED: { label: 'Falló', tone: 'bad' },
}
export const sessionStatus = (status?: string | null) =>
  lookup(sessionStatuses, status, 'En proceso')

// Job status -----------------------------------------------------------------------
const jobStatuses: Record<Job['status'], Entry> = {
  QUEUED: { label: 'En cola', tone: 'busy' },
  RUNNING: { label: 'En curso', tone: 'busy' },
  SUCCEEDED: { label: 'Listo', tone: 'good' },
  FAILED: { label: 'Falló', tone: 'bad' },
}
export const jobStatus = (status?: string | null) => lookup(jobStatuses, status, 'En curso')

// Report status per criterion ------------------------------------------------------
const reportStatuses: Record<CriterionFeedback['status'], Entry> = {
  supported: { label: 'Sustentado', tone: 'good' },
  partial: { label: 'Parcial', tone: 'busy' },
  missing: { label: 'Sin evidencia', tone: 'bad' },
  not_assessed: { label: 'No evaluado', tone: 'neutral' },
}
export const reportStatus = (status?: string | null) =>
  lookup(reportStatuses, status, 'Sin clasificar')

// Question basis -------------------------------------------------------------------
const questionBases: Record<string, string> = {
  document: 'Se basa en tus materiales',
  user_statement: 'Se basa en lo que dijiste antes',
  clarification: 'Pide aclarar algo que faltaba',
}
export const questionBasisLabel = (basis?: string | null) =>
  (basis && questionBases[basis]) || 'Pregunta del panel'

// Evaluator style ------------------------------------------------------------------
/** `style` is free text written by the user in the profile; just present it as a sentence. */
export function styleLabel(style?: string | null): string {
  const text = (style || '').trim()
  if (!text) return 'Sin estilo definido'
  return text.charAt(0).toUpperCase() + text.slice(1)
}

// Ids → human text -----------------------------------------------------------------
/** `decisiones_tecnicas` → `Decisiones tecnicas`. Hex/UUID-looking ids are not shown. */
export function humanizeId(id?: string | null, fallback = 'Sin nombre'): string {
  if (!id || /^[0-9a-f]{16,}$/i.test(id) || id.length > 64) return fallback
  const text = id.replace(/[-_]+/g, ' ').trim()
  return text ? text.charAt(0).toUpperCase() + text.slice(1) : fallback
}

export const turnKindLabel: Record<string, string> = {
  presentation: 'Tu presentación',
  answer: 'Tu respuesta',
  notice: 'Nota del panel',
  question: 'Pregunta del panel',
}
