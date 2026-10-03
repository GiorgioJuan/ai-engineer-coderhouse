import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import {
  ArrowRight,
  BookOpen,
  Check,
  CircleAlert,
  Compass,
  MessageSquare,
  Minus,
  Printer,
  Sparkles,
} from 'lucide-react'
import { Link, useParams } from 'react-router-dom'
import { api } from '../api/client'
import { isNotFound } from '../api/errors'
import { citationLabel, useCitationLabels } from '../api/hooks'
import type { Citation, CriterionFeedback } from '../api/types'
import { AppShell } from '../components/AppShell'
import { NotFoundState } from '../components/NotFound'
import { ErrorNotice, LoadingState, StatePill, dateLabel } from '../components/UI'
import { CitationDrawer } from '../features/session/CitationDrawer'
import { ComparisonTable } from '../features/session/ComparisonTable'
import { summarizeReport } from '../features/session/reportSummary'
import { useDocumentTitle } from '../hooks/usePageHelpers'
import { humanizeId, reportStatus } from '../labels'

const plural = (count: number, one: string, many: string) => `${count} ${count === 1 ? one : many}`

export function SessionReport() {
  const { id = '' } = useParams()
  const session = useQuery({
    queryKey: ['session', id],
    queryFn: ({ signal }) => api.session(id, signal),
    retry: (count, error) => !isNotFound(error) && count < 1,
  })
  const report = useQuery({
    queryKey: ['report', id],
    queryFn: ({ signal }) => api.report(id, signal),
    enabled: session.data?.status === 'COMPLETED',
  })
  const projectId = session.data?.project_id || ''
  const project = useQuery({
    queryKey: ['project', projectId],
    queryFn: ({ signal }) => api.project(projectId, signal),
    enabled: !!projectId,
  })
  const rubrics = useQuery({
    queryKey: ['rubrics', projectId],
    queryFn: ({ signal }) => api.rubrics(projectId, signal),
    enabled: !!projectId,
  })
  const citations = useCitationLabels(projectId)
  const [citation, setCitation] = useState<Citation | null>(null)
  useDocumentTitle('Informe', project.data?.title)
  const criterionTitle = (criterionId: string) => {
    const ref = session.data?.snapshot.rubric_version
    const rubric = rubrics.data?.items.find(
      (r) => r.rubric_id === ref?.id && r.version === ref?.version,
    )
    return (
      rubric?.criteria.find((c) => c.id === criterionId)?.title ||
      rubrics.data?.items.flatMap((r) => r.criteria).find((c) => c.id === criterionId)?.title ||
      humanizeId(criterionId, 'Criterio de la rúbrica')
    )
  }
  /** "Ver mi respuesta" only if the related turn really is one of the person's answers. */
  const turnLinkLabel = (turnId: string) => {
    const kind = session.data?.transcript.find((turn) => turn.id === turnId)?.kind
    return kind === 'presentation'
      ? 'Ver mi presentación'
      : kind === 'question'
        ? 'Ver la pregunta'
        : 'Ver mi respuesta'
  }
  function refs(item: CriterionFeedback) {
    return (
      <div className="report-refs no-print">
        {item.citations.map((ref, index) => {
          const label = citationLabel(citations.titleOf(ref), ref.section)
          return (
            <button
              type="button"
              key={`${ref.chunk_id}-${index}`}
              onClick={() => setCitation(ref)}
              title={`Ver el fragmento citado: ${label}`}
            >
              <BookOpen size={14} aria-hidden /> <span>{label}</span>
            </button>
          )
        })}
        {item.related_turn_ids.map((turnId) => (
          <Link key={turnId} to={`/sessions/${id}#turn-${turnId}`}>
            <MessageSquare size={14} aria-hidden /> {turnLinkLabel(turnId)}
          </Link>
        ))}
      </div>
    )
  }

  if (session.isPending) {
    return (
      <AppShell back={{ to: '/', label: 'Mis proyectos' }}>
        <div className="page-wrap">
          <LoadingState label="Cargando el informe…" rows={4} />
        </div>
      </AppShell>
    )
  }
  if (!session.data) {
    if (isNotFound(session.error))
      return (
        <AppShell back={{ to: '/', label: 'Mis proyectos' }}>
          <NotFoundState title="No encontramos este informe">
            Puede que el enlace sea incorrecto o que la sesión ya no exista.
          </NotFoundState>
        </AppShell>
      )
    return (
      <AppShell back={{ to: '/', label: 'Mis proyectos' }}>
        <div className="page-wrap">
          <h1 className="page-error-title">No pudimos abrir el informe</h1>
          <ErrorNotice
            error={session.error}
            onRetry={() => void session.refetch()}
            retrying={session.isFetching}
          />
          <Link className="text-link" to="/">
            Volver a mis proyectos
          </Link>
        </div>
      </AppShell>
    )
  }

  const data = session.data
  const completed = data.status === 'COMPLETED'
  const summary = summarizeReport(
    report.data?.criterion_feedback ?? [],
    criterionTitle,
    report.data?.pending_questions.length ?? 0,
  )
  const projectTitle = project.data?.title
  return (
    <AppShell
      breadcrumbs={[
        { label: 'Proyectos', to: '/' },
        { label: projectTitle || 'Proyecto', to: projectId ? `/projects/${projectId}` : '/' },
        { label: 'Informe' },
      ]}
    >
      <div className="page-wrap report-page">
        <div className="report-hero">
          <div>
            <p className="eyebrow">INFORME / {projectTitle || 'PROYECTO'}</p>
            <h1>
              Lo que dejó
              <br />
              <em>la conversación.</em>
            </h1>
            <p>{data.objective}</p>
            <div className="report-actions no-print">
              <button
                type="button"
                className="button button--secondary"
                onClick={() => window.print()}
              >
                <Printer size={17} aria-hidden /> Imprimir / guardar PDF
              </button>
              <Link className="button button--ghost" to={`/sessions/${id}`}>
                Ver la conversación
              </Link>
            </div>
          </div>
          {completed ? (
            <div className="report-stamp">
              <span>SESIÓN TERMINADA</span>
              <strong>{dateLabel(data.updated_at)}</strong>
              <span>{plural(data.question_count, 'PREGUNTA', 'PREGUNTAS')}</span>
            </div>
          ) : null}
        </div>
        <ErrorNotice
          error={session.error || report.error}
          onRetry={() => {
            if (session.error) void session.refetch()
            if (report.error) void report.refetch()
          }}
          retrying={session.isFetching || report.isFetching}
        />
        {!completed ? (
          <div className="notice">
            <CircleAlert size={18} aria-hidden />
            <p className="notice__text">
              Esta sesión todavía no terminó, así que el informe no está disponible.{' '}
              <Link to={`/sessions/${id}`}>Volver a la sala</Link>
            </p>
          </div>
        ) : null}
        {completed && report.isPending ? (
          <LoadingState label="Cargando el informe…" rows={4} />
        ) : null}
        {report.data ? (
          <>
            <div className="report-summary">
              <div className="report-summary__mark">
                <Sparkles size={26} aria-hidden />
              </div>
              <div>
                <span className="eyebrow">ESTADO POR CRITERIO</span>
                <ul className="status-chips" aria-label="Criterios por estado">
                  {summary.chips.map((chip) => (
                    <li
                      key={chip.key}
                      className={`status-chip status-chip--${chip.count ? chip.tone : 'zero'}`}
                    >
                      <strong>{chip.count}</strong> {chip.label}
                    </li>
                  ))}
                </ul>
                {rubrics.isPending ? null : <p>{summary.sentence}</p>}
              </div>
            </div>
            <section className="report-section">
              <div className="report-section__head">
                <span className="section-no">01</span>
                <div>
                  <p className="eyebrow">CRITERIO POR CRITERIO</p>
                  <h2>Qué quedó fundamentado</h2>
                </div>
              </div>
              <div className="criteria-list">
                {report.data.criterion_feedback.map((item, index) => {
                  const status = reportStatus(item.status)
                  return (
                    <article className="criterion-row" key={`${item.criterion_id}-${index}`}>
                      <span className="criterion-row__index">
                        {String(index + 1).padStart(2, '0')}
                      </span>
                      <div>
                        <div className="criterion-row__title">
                          <h3>{criterionTitle(item.criterion_id)}</h3>
                          <StatePill tone={status.tone}>{status.label}</StatePill>
                        </div>
                        <p>{item.observation}</p>
                        {item.next_action ? (
                          <div className="criterion-action">
                            <Compass size={16} aria-hidden /> {item.next_action}
                          </div>
                        ) : null}
                        {refs(item)}
                      </div>
                    </article>
                  )
                })}
              </div>
            </section>
            <div className="report-columns">
              <section className="report-card report-card--strength">
                <div className="report-card__icon">
                  <Check size={20} aria-hidden />
                </div>
                <p className="eyebrow">02 / FORTALEZAS</p>
                <h2>Lo que ya sostiene tu propuesta</h2>
                {report.data.strengths.length ? (
                  <ul>
                    {report.data.strengths.map((item, index) => (
                      <li key={index}>{item}</li>
                    ))}
                  </ul>
                ) : (
                  <p>No se registraron fortalezas suficientes en esta sesión.</p>
                )}
              </section>
              <section className="report-card report-card--pending">
                <div className="report-card__icon">
                  <Minus size={20} aria-hidden />
                </div>
                <p className="eyebrow">03 / POR RESOLVER</p>
                <h2>Preguntas abiertas</h2>
                {report.data.pending_questions.length ? (
                  <ul>
                    {report.data.pending_questions.map((item, index) => (
                      <li key={index}>{item}</li>
                    ))}
                  </ul>
                ) : (
                  <p>No quedaron preguntas pendientes registradas.</p>
                )}
              </section>
            </div>
            {report.data.comparison ? (
              <section className="weekly-comparison">
                <div>
                  <span className="eyebrow">EN PERSPECTIVA</span>
                  <h2>Desde la sesión anterior</h2>
                </div>
                {report.data.comparison_items?.length ? (
                  <ComparisonTable changes={report.data.comparison_items} />
                ) : (
                  <p>{report.data.comparison}</p>
                )}
              </section>
            ) : null}
            <section className="next-steps">
              <div>
                <p className="eyebrow">04 / PRÓXIMA ITERACIÓN</p>
                <h2>Ahora, ¿qué sigue?</h2>
                <p>Son sugerencias del panel para preparar el próximo avance.</p>
              </div>
              <ol>
                {report.data.next_steps.map((step, index) => (
                  <li key={index}>
                    <span>{String(index + 1).padStart(2, '0')}</span>
                    {step}
                  </li>
                ))}
              </ol>
            </section>
            <div className="report-end no-print">
              <div>
                <span className="eyebrow">EL TRABAJO CONTINÚA</span>
                <p>Las próximas decisiones las tomás vos, con mejores preguntas sobre la mesa.</p>
              </div>
              <Link
                className="button button--primary"
                to={`/projects/${projectId}/sessions/new?previous=${encodeURIComponent(id)}`}
              >
                Preparar próxima sesión <ArrowRight size={17} aria-hidden />
              </Link>
            </div>
          </>
        ) : null}
      </div>
      <CitationDrawer
        citation={citation}
        projectId={projectId}
        documentTitle={citation ? citations.titleOf(citation) : undefined}
        onClose={() => setCitation(null)}
      />
    </AppShell>
  )
}
