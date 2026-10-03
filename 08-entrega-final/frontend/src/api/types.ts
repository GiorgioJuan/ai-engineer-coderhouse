import type { components } from './schema'

type S = components['schemas']
export type Page<T> = { items: T[]; next_cursor?: string | null }
export type Project = S['Project']
export type DocumentVersion = S['DocumentVersion']
export type PdfExtraction = S['PdfExtraction']
export type ProfileVersion = S['ProfileVersion']
export type RubricCriterion = S['Criterion']
export type RubricVersion = S['RubricVersion']
export type VersionRef = S['VersionRef']
export type DocumentRef = S['DocumentRef']
export type Citation = S['Citation']
export type Question = Omit<S['Question'], 'citations' | 'related_turn_ids'> & {
  citations: Citation[]
  related_turn_ids: string[]
}
export type Turn = Omit<S['Turn'], 'citations'> & { citations: Citation[] }
export type SessionSnapshot = S['SessionSnapshot']
export type SessionStatus = S['SessionStatus']
export type SessionView = Omit<
  S['SessionView'],
  'pending_question' | 'active_job_id' | 'report_id' | 'transcript'
> & {
  pending_question: Question | null
  active_job_id: string | null
  report_id: string | null
  transcript: Turn[]
}
export type CriterionChange = S['CriterionChange']
export type CriterionFeedback = Omit<S['CriterionFeedback'], 'citations' | 'related_turn_ids'> & {
  citations: Citation[]
  related_turn_ids: string[]
}
export type Report = Omit<S['Report'], 'criterion_feedback'> & {
  criterion_feedback: CriterionFeedback[]
}
export type JobAccepted = S['JobAccepted']
export type Job = S['Job']
export type ReadyHealth = S['ReadinessResponse']
