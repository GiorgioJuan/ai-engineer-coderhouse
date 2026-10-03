import { useEffect, useRef, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { ArrowRight, BookOpen, CornerDownLeft, Send, Square } from 'lucide-react'
import { Link, useLocation, useParams } from 'react-router-dom'
import { api, ApiError, commandKey } from '../api/client'
import { describeJobError, isNotFound } from '../api/errors'
import { useCitationLabels, useSession } from '../api/hooks'
import type { Citation } from '../api/types'
import { AppShell } from '../components/AppShell'
import { ConfirmDialog } from '../components/ConfirmDialog'
import { NotFoundState } from '../components/NotFound'
import { Button, ErrorNotice, LoadingState, StatePill, dateLabel } from '../components/UI'
import { CitationDrawer } from '../features/session/CitationDrawer'
import {
  FailedState,
  ProcessingState,
  type ProcessingPhase,
} from '../features/session/ProcessingState'
import { CitationButtons, TurnCard } from '../features/session/Turn'
import { scrollToElement, useDocumentTitle, useScrollToHash } from '../hooks/usePageHelpers'
import { humanizeId, questionBasisLabel, sessionStatus } from '../labels'

export function SessionRoom() {
  const { id = '' } = useParams()
  const { hash } = useLocation()
  const session = useSession(id)
  const projectId = session.data?.project_id || ''
  const profiles = useQuery({
    queryKey: ['profiles', projectId],
    queryFn: ({ signal }) => api.profiles(projectId, signal),
    enabled: !!projectId,
  })
  const rubrics = useQuery({
    queryKey: ['rubrics', projectId],
    queryFn: ({ signal }) => api.rubrics(projectId, signal),
    enabled: !!projectId,
  })
  const project = useQuery({
    queryKey: ['project', projectId],
    queryFn: ({ signal }) => api.project(projectId, signal),
    enabled: !!projectId,
  })
  const citations = useCitationLabels(projectId)
  const status = session.data?.status
  const activeJobId = session.data?.active_job_id
  // One fetch per status change: tells what the panel is doing (kind) and why it failed (error).
  const job = useQuery({
    queryKey: ['job', activeJobId, status],
    queryFn: ({ signal }) => api.job(activeJobId!, signal),
    enabled: !!activeJobId && (status === 'QUEUED' || status === 'RUNNING' || status === 'FAILED'),
  })
  const queryClient = useQueryClient()
  const question = session.data?.pending_question
  const draftKey = question ? `panellab:draft:${id}:${question.id}` : ''
  const [answer, setAnswer] = useState('')
  const [recovered, setRecovered] = useState(false)
  const [citation, setCitation] = useState<Citation | null>(null)
  const [confirmingFinish, setConfirmingFinish] = useState(false)
  const answerRef = useRef<HTMLTextAreaElement>(null)
  /** Last question id already seen: `undefined` until the session first loads. */
  const seenQuestion = useRef<string | null | undefined>(undefined)
  const pendingCommand = useRef<{
    key: string
    question_id: string
    expected_revision: number
    text: string
  } | null>(null)
  const finishCommand = useRef<{
    key: string
    question_id: string
    expected_revision: number
  } | null>(null)
  useEffect(() => {
    if (!draftKey) return
    const saved = sessionStorage.getItem(draftKey)
    setAnswer(saved || '')
    setRecovered(!!saved)
  }, [draftKey])
  useEffect(() => {
    if (draftKey) sessionStorage.setItem(draftKey, answer)
  }, [draftKey, answer])
  useEffect(() => {
    if (pendingCommand.current && pendingCommand.current.question_id !== question?.id)
      pendingCommand.current = null
    if (finishCommand.current && finishCommand.current.question_id !== question?.id)
      finishCommand.current = null
  }, [question?.id])
  // A new question arrives while the person is here: bring it into view and move focus to the
  // answer box. Skipped on first load and when the URL points at a specific turn.
  useEffect(() => {
    if (!session.data) return
    const current = question?.id ?? null
    if (seenQuestion.current === undefined) {
      seenQuestion.current = current
      return
    }
    if (current === seenQuestion.current) return
    seenQuestion.current = current
    if (!current || status !== 'WAITING_RESPONSE' || hash) return
    scrollToElement(document.getElementById(`turn-${current}`), 'start')
    answerRef.current?.focus({ preventScroll: true })
  }, [session.data, question?.id, status, hash])
  useScrollToHash(!!session.data)
  const respond = useMutation({
    mutationFn: () => {
      const command = (pendingCommand.current ||= {
        key: commandKey(),
        question_id: question!.id,
        expected_revision: session.data!.revision,
        text: answer.trim(),
      })
      return api.respond(
        id,
        {
          question_id: command.question_id,
          expected_revision: command.expected_revision,
          text: command.text,
        },
        command.key,
      )
    },
    onSuccess: () => {
      if (draftKey) sessionStorage.removeItem(draftKey)
      setAnswer('')
      pendingCommand.current = null
      setRecovered(false)
      queryClient.invalidateQueries({ queryKey: ['session', id] })
    },
    onError: (error) => {
      if (error instanceof ApiError && error.status === 409) {
        pendingCommand.current = null
        queryClient.invalidateQueries({ queryKey: ['session', id] })
      }
    },
  })
  const finish = useMutation({
    mutationFn: () => {
      const command = (finishCommand.current ||= {
        key: commandKey(),
        question_id: question!.id,
        expected_revision: session.data!.revision,
      })
      return api.finish(
        id,
        { question_id: command.question_id, expected_revision: command.expected_revision },
        command.key,
      )
    },
    onSuccess: () => {
      finishCommand.current = null
      queryClient.invalidateQueries({ queryKey: ['session', id] })
    },
    onError: (error) => {
      if (error instanceof ApiError && error.status === 409) {
        finishCommand.current = null
        queryClient.invalidateQueries({ queryKey: ['session', id] })
      }
    },
  })
  const retry = useMutation({
    mutationFn: () => api.retryJob(job.data!.id, job.data!.attempt, commandKey()),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['session', id] }),
  })
  const profileList = profiles.data?.items
  const profileOf = (reviewerId: string) => profileList?.find((p) => p.profile_id === reviewerId)
  const reviewerName = (reviewerId: string) =>
    profileOf(reviewerId)?.name || humanizeId(reviewerId, 'Evaluador')
  const criterionTitle = (criterionId: string) => {
    const ref = session.data?.snapshot.rubric_version
    const rubric =
      rubrics.data?.items.find((r) => r.rubric_id === ref?.id && r.version === ref?.version) ||
      rubrics.data?.items.find((r) => r.rubric_id === ref?.id)
    return (
      rubric?.criteria.find((c) => c.id === criterionId)?.title ||
      rubrics.data?.items.flatMap((r) => r.criteria).find((c) => c.id === criterionId)?.title ||
      humanizeId(criterionId, 'Criterio de la rúbrica')
    )
  }
  useDocumentTitle('Sesión', project.data?.title)
  function submit(event?: React.FormEvent) {
    event?.preventDefault()
    if (
      !question ||
      !answer.trim() ||
      respond.isPending ||
      session.data?.status !== 'WAITING_RESPONSE'
    )
      return
    respond.mutate()
  }

  if (session.isPending) {
    return (
      <AppShell back={{ to: '/', label: 'Mis proyectos' }}>
        <div className="page-wrap">
          <LoadingState label="Cargando la sesión…" rows={4} />
        </div>
      </AppShell>
    )
  }
  if (!session.data) {
    if (isNotFound(session.error))
      return (
        <AppShell back={{ to: '/', label: 'Mis proyectos' }}>
          <NotFoundState title="No encontramos esta sesión">
            Puede que el enlace sea incorrecto o que la sesión ya no exista.
          </NotFoundState>
        </AppShell>
      )
    return (
      <AppShell back={{ to: '/', label: 'Mis proyectos' }}>
        <div className="page-wrap">
          <h1 className="page-error-title">No pudimos abrir la sesión</h1>
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
  const transcript = data.transcript
  const answered = transcript.filter((turn) => turn.kind === 'answer').length
  const projectTo = projectId ? `/projects/${projectId}` : '/'
  const pillStatus = sessionStatus(status)
  const phase: ProcessingPhase =
    job.data?.kind === 'FINISH' ||
    finish.isPending ||
    finish.isSuccess ||
    answered >= data.max_questions
      ? 'report'
      : answered === 0
        ? 'first'
        : 'next'
  const questionInTranscript = transcript.some(
    (t) => t.kind === 'question' && t.id === question?.id,
  )
  const failure = describeJobError(job.data?.error)
  const retryable = job.data?.error?.retryable ?? true
  const activeProfile = question ? profileOf(question.reviewer_id) : undefined
  const reviewerRows = (profileList || []).filter((p) =>
    data.snapshot.profile_versions.some(
      (ref) => ref.id === p.profile_id && ref.version === p.version,
    ),
  )
  return (
    <AppShell
      back={{ to: projectTo, label: project.data?.title || 'Volver al proyecto' }}
      eyebrow={`Sesión del ${dateLabel(data.created_at)}`}
    >
      <div className="room-page">
        <header className="room-header">
          <div>
            <p className="eyebrow">SALA DE REVISIÓN / {project.data?.title || 'Proyecto'}</p>
            <h1>{data.objective}</h1>
          </div>
          <div className="room-header__side">
            <div className="room-progress">
              <span>{status === 'COMPLETED' ? 'PREGUNTAS RESPONDIDAS' : 'PREGUNTA'}</span>
              <strong>
                {status === 'COMPLETED' ? answered : data.question_count} <i>/</i>{' '}
                {data.max_questions}
              </strong>
            </div>
            {status === 'COMPLETED' ? (
              <Link className="button button--primary" to={`/sessions/${id}/report`}>
                Ver informe <ArrowRight size={17} aria-hidden />
              </Link>
            ) : null}
          </div>
        </header>
        {session.error ? (
          <div className="room-notice">
            <ErrorNotice
              error={session.error}
              onRetry={() => void session.refetch()}
              retrying={session.isFetching}
            />
          </div>
        ) : null}
        <div className="room-layout">
          <aside className="room-panel" aria-label="El panel de evaluadores">
            <div className="room-sticky">
              <span className="eyebrow">EL PANEL</span>
              <div className="room-reviewers">
                {profiles.isPending ? (
                  <p className="muted" role="status">
                    Cargando evaluadores…
                  </p>
                ) : (
                  reviewerRows.map((p, index) => {
                    const active = question?.reviewer_id === p.profile_id
                    return (
                      <div
                        className={`room-reviewer room-reviewer--${index % 3} ${active ? 'active' : ''}`}
                        key={`${p.profile_id}:${p.version}`}
                      >
                        <span className="room-reviewer__dot" aria-hidden />
                        <div>
                          <strong>{p.name}</strong>
                          <small>{p.role}</small>
                        </div>
                        {active ? <span className="room-reviewer__active">En turno</span> : null}
                      </div>
                    )
                  })
                )}
              </div>
              <div className="room-panel__foot">
                <span>EN ESTA CONVERSACIÓN</span>
                <p>
                  Las preguntas se basan en tus materiales y respuestas. Cada cita se puede abrir en
                  su versión original.
                </p>
              </div>
            </div>
          </aside>
          <section className="room-conversation" aria-label="Conversación">
            <div className="conversation-head">
              <span>CONVERSACIÓN</span>
              <StatePill tone={pillStatus.tone}>{pillStatus.label}</StatePill>
            </div>
            <div className="transcript">
              {transcript.map((turn) => {
                const isCurrent = turn.kind === 'question' && turn.id === question?.id
                const profile = turn.kind === 'question' ? profileOf(turn.author_id) : undefined
                return (
                  <TurnCard
                    key={turn.id}
                    turn={turn}
                    name={reviewerName(turn.author_id)}
                    role={profile?.role}
                    criterion={
                      isCurrent && question ? criterionTitle(question.criterion_id) : undefined
                    }
                    highlighted={hash === `#turn-${turn.id}`}
                    onCitation={setCitation}
                    titleOf={citations.titleOf}
                  />
                )
              })}
              {status === 'QUEUED' || status === 'RUNNING' ? (
                <ProcessingState status={status} phase={phase} startedAt={data.updated_at} />
              ) : null}
              {status === 'FAILED' ? (
                <FailedState
                  info={failure}
                  projectTo={projectTo}
                  retrying={retry.isPending || job.isFetching}
                  retryError={retry.error}
                  onRetry={
                    job.data
                      ? retryable
                        ? () => retry.mutate()
                        : undefined
                      : () => void job.refetch()
                  }
                />
              ) : null}
              {status === 'COMPLETED' ? (
                <div className="completed-state">
                  <span className="eyebrow">REVISIÓN TERMINADA</span>
                  <h2>Tu informe está listo.</h2>
                  <Link className="button button--primary" to={`/sessions/${id}/report`}>
                    Ver informe <ArrowRight size={17} aria-hidden />
                  </Link>
                </div>
              ) : null}
              {question && status === 'WAITING_RESPONSE' && !questionInTranscript ? (
                <TurnCard
                  turn={{
                    id: question.id,
                    kind: 'question',
                    author_id: question.reviewer_id,
                    text: question.text,
                    citations: question.citations,
                    created_at: data.updated_at || new Date().toISOString(),
                  }}
                  name={reviewerName(question.reviewer_id)}
                  role={activeProfile?.role}
                  criterion={criterionTitle(question.criterion_id)}
                  highlighted={hash === `#turn-${question.id}`}
                  onCitation={setCitation}
                  titleOf={citations.titleOf}
                />
              ) : null}
            </div>
            {question && status === 'WAITING_RESPONSE' ? (
              <form className="answer-composer" onSubmit={submit}>
                <p className="answer-composer__progress">
                  Pregunta {data.question_count} de {data.max_questions} · podés terminar antes
                </p>
                <div className="answer-composer__top">
                  <label htmlFor="answer-input">TU RESPUESTA</label>
                  <span aria-live="off">{answer.length.toLocaleString('es-AR')} / 4.000</span>
                </div>
                {recovered ? (
                  <p className="recovered-note">Borrador recuperado en este navegador.</p>
                ) : null}
                <textarea
                  id="answer-input"
                  ref={answerRef}
                  value={answer}
                  onChange={(event) => setAnswer(event.target.value)}
                  maxLength={4000}
                  rows={5}
                  aria-describedby={`turn-text-${question.id}`}
                  placeholder="Respondé con decisiones, argumentos y evidencia concreta…"
                  onKeyDown={(event) => {
                    if ((event.ctrlKey || event.metaKey) && event.key === 'Enter') {
                      event.preventDefault()
                      submit()
                    }
                  }}
                />
                <div className="answer-composer__bottom">
                  <span>
                    <CornerDownLeft size={14} aria-hidden /> Ctrl/⌘ + Enter para enviar
                  </span>
                  <div>
                    <Button
                      type="button"
                      variant="secondary"
                      loading={finish.isPending}
                      disabled={respond.isPending}
                      onClick={() => setConfirmingFinish(true)}
                    >
                      <Square size={14} aria-hidden /> Terminar y ver informe
                    </Button>
                    <Button
                      type="submit"
                      loading={respond.isPending}
                      disabled={!answer.trim() || finish.isPending}
                    >
                      Enviar respuesta <Send size={16} aria-hidden />
                    </Button>
                  </div>
                </div>
                <ErrorNotice error={respond.error || finish.error}>
                  {respond.error instanceof ApiError && respond.error.status === 409
                    ? 'El turno cambió. Actualizamos la sesión y conservamos tu borrador.'
                    : undefined}
                </ErrorNotice>
              </form>
            ) : null}
          </section>
          <aside className="room-context" aria-label="En foco">
            <div className="room-sticky">
              <span className="eyebrow">EN FOCO</span>
              {question ? (
                <>
                  <span className="context-number" aria-hidden>
                    {String(data.question_count || 1).padStart(2, '0')}
                  </span>
                  <h2>{reviewerName(question.reviewer_id)}</h2>
                  {activeProfile?.role ? (
                    <p className="context-role">{activeProfile.role}</p>
                  ) : null}
                  <p>
                    <strong>Criterio:</strong> {criterionTitle(question.criterion_id)}
                  </p>
                  <div className="context-divider" />
                  <span className="eyebrow">BASE DE LA PREGUNTA</span>
                  <p>{questionBasisLabel(question.basis)}</p>
                  <CitationButtons
                    citations={question.citations}
                    onSelect={setCitation}
                    titleOf={citations.titleOf}
                  />
                </>
              ) : status === 'COMPLETED' ? (
                <>
                  <p>La sesión terminó. El informe resume cada criterio con sus citas.</p>
                  <Link className="button button--primary" to={`/sessions/${id}/report`}>
                    Ver informe <ArrowRight size={17} aria-hidden />
                  </Link>
                </>
              ) : (
                <p>
                  Cuando llegue la siguiente pregunta, vas a ver acá el criterio y las citas que la
                  respaldan.
                </p>
              )}
              {status !== 'COMPLETED' ? (
                <div className="room-context__foot">
                  <BookOpen size={20} aria-hidden />
                  <p>Tocá una cita para ver el fragmento y el documento original.</p>
                </div>
              ) : null}
            </div>
          </aside>
        </div>
      </div>
      <CitationDrawer
        citation={citation}
        projectId={projectId}
        documentTitle={citation ? citations.titleOf(citation) : undefined}
        onClose={() => setCitation(null)}
      />
      {confirmingFinish ? (
        <ConfirmDialog
          title="¿Terminar la sesión ahora?"
          cancelLabel="Seguir respondiendo"
          confirmLabel="Terminar sesión"
          onCancel={() => setConfirmingFinish(false)}
          onConfirm={() => {
            setConfirmingFinish(false)
            finish.mutate()
          }}
        >
          <p>
            Vas a recibir el informe con {answered} de {data.max_questions} preguntas respondidas.
            No vas a poder retomarla.
          </p>
          {answer.trim() ? (
            <p>La respuesta que escribiste y no enviaste no se va a tener en cuenta.</p>
          ) : null}
        </ConfirmDialog>
      ) : null}
    </AppShell>
  )
}
