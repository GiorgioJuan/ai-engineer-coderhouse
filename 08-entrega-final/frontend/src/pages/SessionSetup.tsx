import { useEffect, useRef, useState } from 'react'
import { useMutation } from '@tanstack/react-query'
import { ArrowRight, Check, CircleAlert, ChevronDown, FileText, Users } from 'lucide-react'
import { Link, useNavigate, useParams, useSearchParams } from 'react-router-dom'
import { api, ApiError, commandKey } from '../api/client'
import { isNotFound } from '../api/errors'
import { useProjectData } from '../api/hooks'
import { AppShell } from '../components/AppShell'
import { NotFoundState } from '../components/NotFound'
import {
  Button,
  ErrorNotice,
  FieldError,
  Label,
  StatePill,
  latest,
  dateLabel,
} from '../components/UI'
import { useDocumentTitle } from '../hooks/usePageHelpers'
import { documentKindLabel, documentStatus } from '../labels'

type SetupDraft = {
  objective?: string
  presentation?: string
  selectedProfiles?: string[] | null
  selectedDocs?: string[] | null
  rubricId?: string
  previousId?: string
  maxQuestions?: number
}
const draftKey = (projectId: string) => `panellab:session-draft:${projectId}`
function readDraft(projectId: string): SetupDraft {
  try {
    const parsed: unknown = JSON.parse(sessionStorage.getItem(draftKey(projectId)) || '{}')
    if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) return {}
    const value = parsed as Record<string, unknown>
    const strings = (input: unknown) =>
      Array.isArray(input) && input.every((item) => typeof item === 'string')
        ? (input as string[])
        : null
    return {
      objective: typeof value.objective === 'string' ? value.objective.slice(0, 500) : '',
      presentation:
        typeof value.presentation === 'string' ? value.presentation.slice(0, 12000) : '',
      selectedProfiles: strings(value.selectedProfiles)?.slice(0, 5) ?? null,
      selectedDocs: strings(value.selectedDocs),
      rubricId: typeof value.rubricId === 'string' ? value.rubricId : '',
      previousId: typeof value.previousId === 'string' ? value.previousId : '',
      maxQuestions: [3, 4, 5].includes(Number(value.maxQuestions)) ? Number(value.maxQuestions) : 5,
    }
  } catch {
    return {}
  }
}

export function SessionSetup() {
  const { id = '' } = useParams()
  return <SessionSetupContent key={id} />
}

function SessionSetupContent() {
  const { id = '' } = useParams()
  const [searchParams] = useSearchParams()
  const initialDraft = useRef(readDraft(id)).current
  const data = useProjectData(id)
  const navigate = useNavigate()
  const allDocs = data.documents.data?.items || []
  const docs = latest(
    allDocs.filter((d) => d.index_status === 'READY'),
    (d) => d.document_id,
    (d) => d.version,
  )
  // Newest versions that cannot be cited yet: say so instead of silently leaving them out.
  const unreadyDocs = latest(
    allDocs,
    (d) => d.document_id,
    (d) => d.version,
  ).filter((d) => d.index_status !== 'READY')
  const preparingDocs = unreadyDocs.filter((d) => documentStatus(d.index_status).tone === 'busy')
  const profiles = latest(
    data.profiles.data?.items || [],
    (p) => p.profile_id,
    (p) => p.version,
  )
  const rubrics = latest(
    data.rubrics.data?.items || [],
    (r) => r.rubric_id,
    (r) => r.version,
  )
  const finished = (data.sessions.data?.items || []).filter((s) => s.status === 'COMPLETED')
  const [objective, setObjective] = useState(initialDraft.objective || '')
  const [presentation, setPresentation] = useState(initialDraft.presentation || '')
  const [selectedProfiles, setSelectedProfiles] = useState<string[] | null>(
    initialDraft.selectedProfiles ?? null,
  )
  const [selectedDocs, setSelectedDocs] = useState<string[] | null>(
    initialDraft.selectedDocs ?? null,
  )
  const [rubricId, setRubricId] = useState(initialDraft.rubricId || '')
  const [previousId, setPreviousId] = useState(
    searchParams.get('previous') || initialDraft.previousId || '',
  )
  const [maxQuestions, setMaxQuestions] = useState(initialDraft.maxQuestions || 5)
  const [draftSaved, setDraftSaved] = useState(false)
  const [touched, setTouched] = useState({ objective: false, presentation: false })
  const pendingCommand = useRef<{
    key: string
    payload: Parameters<typeof api.createSession>[1]
  } | null>(null)
  useEffect(() => {
    try {
      sessionStorage.setItem(
        draftKey(id),
        JSON.stringify({
          objective,
          presentation,
          selectedProfiles,
          selectedDocs,
          rubricId,
          previousId,
          maxQuestions,
        } satisfies SetupDraft),
      )
      setDraftSaved(true)
    } catch {
      setDraftSaved(false)
    }
  }, [
    id,
    objective,
    presentation,
    selectedProfiles,
    selectedDocs,
    rubricId,
    previousId,
    maxQuestions,
  ])
  const activeProfiles = (selectedProfiles ?? profiles.slice(0, 5).map((p) => p.profile_id)).filter(
    (profileId) => profiles.some((profile) => profile.profile_id === profileId),
  )
  const questionLimit = Math.max(maxQuestions, activeProfiles.length)
  const activeDocs = (selectedDocs ?? docs.map((d) => d.document_id)).filter((documentId) =>
    docs.some((doc) => doc.document_id === documentId),
  )
  const activeRubric = rubrics.find((r) => r.rubric_id === rubricId) || rubrics[0]
  const activePreviousId = finished.some((session) => session.id === previousId) ? previousId : ''
  const loading = data.documents.isPending || data.profiles.isPending || data.rubrics.isPending
  const loadError = data.documents.error || data.profiles.error || data.rubrics.error
  const limitReached = activeProfiles.length >= 5
  const limitRaised = maxQuestions < activeProfiles.length
  const docsIssue = () => {
    if (data.documents.isPending) return null
    if (docs.length === 0 && preparingDocs.length)
      return 'Esperá a que termine de prepararse al menos un material: esta pantalla se actualiza sola.'
    if (docs.length === 0 && unreadyDocs.length)
      return 'Ningún material está listo: subí una nueva versión de los que fallaron.'
    if (docs.length === 0)
      return 'Agregá al menos un documento en Materiales y esperá a que figure como listo.'
    return activeDocs.length === 0 ? 'Seleccioná al menos un material listo.' : null
  }
  const issues = [
    !objective.trim() ? 'Escribí el objetivo de la sesión.' : null,
    !presentation.trim() ? 'Sumá una presentación inicial.' : null,
    docsIssue(),
    !profiles.length && !data.profiles.isPending
      ? 'Necesitás al menos un evaluador.'
      : activeProfiles.length === 0 && profiles.length
        ? 'Seleccioná al menos un evaluador.'
        : null,
    !rubrics.length && !data.rubrics.isPending ? 'Necesitás una rúbrica con criterios.' : null,
  ].filter((issue): issue is string => !!issue)
  const canSubmit =
    !loading &&
    !loadError &&
    activeProfiles.length >= 1 &&
    activeProfiles.length <= 5 &&
    !!activeRubric &&
    activeDocs.length > 0 &&
    !issues.length
  const create = useMutation({
    mutationFn: () => {
      const command = (pendingCommand.current ||= {
        key: commandKey(),
        payload: {
          objective: objective.trim(),
          presentation: presentation.trim(),
          profile_versions: profiles
            .filter((p) => activeProfiles.includes(p.profile_id))
            .map((p) => ({ id: p.profile_id, version: p.version })),
          rubric_version: { id: activeRubric!.rubric_id, version: activeRubric!.version },
          document_versions: docs
            .filter((d) => activeDocs.includes(d.document_id))
            .map((d) => ({ document_id: d.document_id, version: d.version })),
          previous_session_id: activePreviousId || null,
          max_questions: questionLimit,
        },
      })
      return api.createSession(id, command.payload, command.key)
    },
    onSuccess: (accepted) => {
      pendingCommand.current = null
      if (accepted.session_id) {
        try {
          sessionStorage.removeItem(draftKey(id))
        } catch {
          /* storage unavailable */
        }
        navigate(`/sessions/${accepted.session_id}`)
      }
    },
    onError: (error) => {
      if (error instanceof ApiError && error.status > 0) pendingCommand.current = null
    },
  })
  useDocumentTitle('Preparar sesión', data.project.data?.title)
  function toggle(value: string, current: string[], set: (next: string[]) => void) {
    set(current.includes(value) ? current.filter((item) => item !== value) : [...current, value])
  }
  function submit(event: React.FormEvent) {
    event.preventDefault()
    if (!canSubmit || create.isPending) return
    create.mutate()
  }
  if (data.project.isError && isNotFound(data.project.error))
    return (
      <AppShell back={{ to: '/', label: 'Todos los proyectos' }}>
        <NotFoundState title="No encontramos este proyecto">
          Puede que el enlace sea incorrecto o que el proyecto ya no exista.
        </NotFoundState>
      </AppShell>
    )
  const projectTitle = data.project.data?.title
  const objectiveMissing = touched.objective && !objective.trim()
  const presentationMissing = touched.presentation && !presentation.trim()
  const issuesVisible = issues.length > 0 && !loading && !loadError
  return (
    <AppShell
      back={{ to: `/projects/${id}`, label: projectTitle || 'Volver al proyecto' }}
      eyebrow="Preparar sesión"
    >
      <div className="page-wrap setup-page">
        <div className="page-kicker">
          <span className="kicker-dot" /> UNA NUEVA REVISIÓN <span className="kicker-line" />
        </div>
        <div className="setup-head">
          <div>
            <p className="eyebrow">CONFIGURAR SESIÓN</p>
            <h1>
              Antes de entrar
              <br />
              <em>a la sala.</em>
            </h1>
            <p>Elegí qué querés poner a prueba y con qué evidencia trabajará el panel.</p>
          </div>
          <div className="setup-head__note">
            <span>NOTA DE TRABAJO</span>
            <p>
              Las versiones seleccionadas quedan guardadas en esta sesión. Podrás seguir editando tu
              proyecto para la próxima.
            </p>
          </div>
        </div>
        <form onSubmit={submit} className="setup-grid" noValidate>
          <div className="setup-main">
            <p className="form-legend">Los campos con * son obligatorios.</p>
            <section className="setup-section">
              <span className="setup-section__number">01</span>
              <div>
                <h2>Lo que vas a presentar</h2>
                <p>Un foco concreto ayuda al panel a formular preguntas útiles.</p>
                <Label htmlFor="session-objective" required>
                  Objetivo de esta sesión
                </Label>
                <input
                  id="session-objective"
                  value={objective}
                  onChange={(event) => setObjective(event.target.value)}
                  onBlur={() => setTouched((value) => ({ ...value, objective: true }))}
                  required
                  aria-invalid={objectiveMissing ? true : undefined}
                  aria-describedby={objectiveMissing ? 'session-objective-error' : undefined}
                  maxLength={500}
                  placeholder="Ej. Validar la decisión de arquitectura de esta semana"
                />
                <FieldError id="session-objective-error">
                  {objectiveMissing
                    ? 'Falta el objetivo: contá en una frase qué querés poner a prueba.'
                    : null}
                </FieldError>
                <Label
                  htmlFor="session-presentation"
                  required
                  hint={`${presentation.length.toLocaleString('es-AR')} / 12.000 caracteres`}
                >
                  Presentación inicial
                </Label>
                <textarea
                  id="session-presentation"
                  value={presentation}
                  onChange={(event) => setPresentation(event.target.value)}
                  onBlur={() => setTouched((value) => ({ ...value, presentation: true }))}
                  required
                  aria-invalid={presentationMissing ? true : undefined}
                  aria-describedby={
                    presentationMissing ? 'session-presentation-error' : 'session-presentation-note'
                  }
                  maxLength={12000}
                  rows={9}
                  placeholder="Contá el problema, qué hiciste y qué decisiones querés defender…"
                />
                <FieldError id="session-presentation-error">
                  {presentationMissing
                    ? 'Falta la presentación: pegá el relato con el que arrancarías frente al panel.'
                    : null}
                </FieldError>
                <p className="field-note" id="session-presentation-note">
                  Esta presentación es tu relato inicial; los materiales se consultan por separado.
                </p>
              </div>
            </section>
            <section className="setup-section">
              <span className="setup-section__number">02</span>
              <div role="group" aria-labelledby="setup-evaluators-title">
                <h2 id="setup-evaluators-title">Quiénes van a preguntar</h2>
                <p>
                  Seleccioná entre uno y cinco evaluadores. Cada uno tendrá un turno antes de
                  repetir.
                </p>
                <div className="setup-choice-grid">
                  {profiles.map((profile, index) => {
                    const checked = activeProfiles.includes(profile.profile_id)
                    const blocked = !checked && limitReached
                    return (
                      <label
                        className={`choice-card choice-card--${index % 3} ${checked ? 'selected' : ''} ${blocked ? 'choice-card--blocked' : ''}`}
                        key={profile.profile_id}
                        title={
                          blocked
                            ? 'Ya elegiste 5 evaluadores. Quitá uno para elegir este.'
                            : undefined
                        }
                      >
                        <input
                          type="checkbox"
                          checked={checked}
                          onChange={() =>
                            toggle(profile.profile_id, activeProfiles, setSelectedProfiles)
                          }
                          disabled={blocked}
                        />
                        <span className="choice-card__check">
                          <Check size={14} aria-hidden />
                        </span>
                        <span className="eyebrow">EVALUADOR {index + 1}</span>
                        <strong>{profile.name}</strong>
                        <small>
                          {profile.role} · versión {profile.version}
                        </small>
                        {blocked ? (
                          <small className="choice-card__why">
                            Máximo 5. Quitá otro evaluador para elegir este.
                          </small>
                        ) : null}
                      </label>
                    )
                  })}
                </div>
                {limitReached ? (
                  <p className="field-note" role="status">
                    Elegiste el máximo de 5 evaluadores.
                  </p>
                ) : null}
              </div>
            </section>
            <section className="setup-section">
              <span className="setup-section__number">03</span>
              <div>
                <h2>Con qué evidencia</h2>
                <p>Solo se pueden citar materiales listos.</p>
                {docs.length ? (
                  <div className="source-choices">
                    {docs.map((doc) => (
                      <label className="source-choice" key={doc.document_id}>
                        <input
                          type="checkbox"
                          checked={activeDocs.includes(doc.document_id)}
                          onChange={() => toggle(doc.document_id, activeDocs, setSelectedDocs)}
                        />
                        <FileText size={18} aria-hidden />
                        <span>
                          <strong>{doc.title}</strong>
                          <small>
                            {documentKindLabel(doc.kind)} · versión {doc.version}
                          </small>
                        </span>
                        <Check size={17} className="source-choice__check" aria-hidden />
                      </label>
                    ))}
                  </div>
                ) : null}
                {unreadyDocs.length ? (
                  <div className="source-choices source-choices--unready" role="status">
                    <p className="source-choices__title">
                      {preparingDocs.length
                        ? `${preparingDocs.length === 1 ? 'Un material se está preparando' : `${preparingDocs.length} materiales se están preparando`}. Se suma acá apenas esté listo.`
                        : 'Estos materiales no se pudieron preparar y no se pueden usar:'}
                    </p>
                    {unreadyDocs.map((doc) => {
                      const status = documentStatus(doc.index_status)
                      return (
                        <div className="source-choice source-choice--unready" key={doc.document_id}>
                          <FileText size={18} aria-hidden />
                          <span>
                            <strong>{doc.title}</strong>
                            <small>
                              {documentKindLabel(doc.kind)} · versión {doc.version}
                              {status.tone === 'bad'
                                ? ' · Subí una nueva versión desde Materiales.'
                                : ''}
                            </small>
                          </span>
                          <StatePill tone={status.tone}>{status.label}</StatePill>
                        </div>
                      )
                    })}
                  </div>
                ) : null}
                <div className="setup-inline-fields">
                  <div>
                    <Label htmlFor="rubric">Rúbrica</Label>
                    <div className="select-wrap">
                      <select
                        id="rubric"
                        value={activeRubric?.rubric_id || ''}
                        onChange={(event) => setRubricId(event.target.value)}
                      >
                        {rubrics.map((r) => (
                          <option key={r.rubric_id} value={r.rubric_id}>
                            {r.name} · versión {r.version}
                          </option>
                        ))}
                      </select>
                      <ChevronDown size={17} aria-hidden />
                    </div>
                  </div>
                  <div>
                    <Label htmlFor="question-count">Preguntas</Label>
                    <div className="select-wrap">
                      <select
                        id="question-count"
                        value={questionLimit}
                        aria-describedby="question-count-help"
                        onChange={(event) => setMaxQuestions(Number(event.target.value))}
                      >
                        <option value={3} disabled={activeProfiles.length > 3}>
                          3 preguntas
                        </option>
                        <option value={4} disabled={activeProfiles.length > 4}>
                          4 preguntas
                        </option>
                        <option value={5}>5 preguntas</option>
                      </select>
                      <ChevronDown size={17} aria-hidden />
                    </div>
                  </div>
                </div>
                <p className="field-note" id="question-count-help" role="status">
                  {limitRaised
                    ? `Subimos el máximo a ${questionLimit} preguntas porque elegiste ${activeProfiles.length} evaluadores: cada uno pregunta al menos una vez.`
                    : activeProfiles.length > 3
                      ? `Con ${activeProfiles.length} evaluadores el mínimo es ${activeProfiles.length} preguntas: cada uno pregunta al menos una vez.`
                      : 'Es un máximo: podés terminar antes desde la sala.'}
                </p>
                <Label htmlFor="previous">Comparar con una sesión anterior</Label>
                <div className="select-wrap">
                  <select
                    id="previous"
                    value={activePreviousId}
                    disabled={!finished.length}
                    aria-describedby="previous-help"
                    onChange={(event) => setPreviousId(event.target.value)}
                  >
                    <option value="">Sin comparación</option>
                    {finished.map((session) => (
                      <option value={session.id} key={session.id}>
                        {dateLabel(session.created_at)} · {session.objective}
                      </option>
                    ))}
                  </select>
                  <ChevronDown size={17} aria-hidden />
                </div>
                <p className="field-note" id="previous-help">
                  {finished.length
                    ? 'El informe va a mostrar qué cambió desde esa sesión.'
                    : 'Todavía no tenés sesiones terminadas para comparar.'}
                </p>
              </div>
            </section>
          </div>
          <aside className="setup-summary" aria-label="Resumen de la sesión">
            <span className="eyebrow">TU SESIÓN EN UNA MIRADA</span>
            <h3>
              {canSubmit ? (
                <>
                  La mesa está
                  <br />
                  lista.
                </>
              ) : (
                <>
                  La mesa está
                  <br />
                  casi lista.
                </>
              )}
            </h3>
            <div className="summary-line">
              <Users size={18} aria-hidden />
              <span>
                {activeProfiles.length} evaluador{activeProfiles.length === 1 ? '' : 'es'}
              </span>
            </div>
            <div className="summary-line">
              <FileText size={18} aria-hidden />
              <span>
                {activeDocs.length} material{activeDocs.length === 1 ? '' : 'es'} seleccionado
                {activeDocs.length === 1 ? '' : 's'}
              </span>
            </div>
            <div className="summary-line">
              <span className="summary-line__number">{questionLimit}</span>
              <span>preguntas como máximo</span>
            </div>
            {loading ? (
              <p className="setup-feedback" role="status">
                Comprobando materiales y criterios…
              </p>
            ) : null}
            {loadError ? (
              <div className="setup-recovery">
                <ErrorNotice
                  error={loadError}
                  retrying={
                    data.documents.isFetching || data.profiles.isFetching || data.rubrics.isFetching
                  }
                  onRetry={() => {
                    void data.documents.refetch()
                    void data.profiles.refetch()
                    void data.rubrics.refetch()
                  }}
                />
              </div>
            ) : null}
            {issuesVisible ? (
              <div className="setup-issues" id="setup-issues">
                <CircleAlert size={17} aria-hidden />
                <div>
                  <strong>Para iniciar, completá:</strong>
                  {issues.map((issue) => (
                    <p key={issue}>{issue}</p>
                  ))}
                  {!docs.length || !profiles.length || !rubrics.length ? (
                    <Link to={`/projects/${id}`}>
                      Ir al proyecto <ArrowRight size={14} aria-hidden />
                    </Link>
                  ) : null}
                </div>
              </div>
            ) : null}
            <ErrorNotice error={create.error} />
            <Button
              type="submit"
              disabled={!canSubmit}
              loading={create.isPending}
              aria-describedby={issuesVisible ? 'setup-issues' : undefined}
            >
              Iniciar revisión <ArrowRight size={17} aria-hidden />
            </Button>
            {draftSaved ? (
              <p className="summary-fineprint">
                Tu preparación se guarda en esta pestaña hasta iniciar la sesión.
              </p>
            ) : null}
            <p className="summary-fineprint">
              Podés terminar antes de llegar al límite y recibir igual un informe sobre lo
              conversado.
            </p>
          </aside>
        </form>
      </div>
    </AppShell>
  )
}
