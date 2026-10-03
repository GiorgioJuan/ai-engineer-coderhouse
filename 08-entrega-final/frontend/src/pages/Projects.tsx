import { useEffect, useMemo, useRef, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  Archive,
  ArchiveRestore,
  ArrowRight,
  ChevronDown,
  FolderOpen,
  Plus,
  Undo2,
  X,
} from 'lucide-react'
import { Link, useLocation, useNavigate } from 'react-router-dom'
import { byRecent, useSetArchived } from '../api/archive'
import { api, ApiError, commandKey } from '../api/client'
import { ConfirmDialog } from '../components/ConfirmDialog'
import {
  Button,
  EmptyState,
  ErrorNotice,
  FieldError,
  Label,
  LoadingState,
  SuccessNotice,
  dateLabel,
} from '../components/UI'
import { useDialogFocus } from '../hooks/useDialogFocus'
import { useDocumentTitle } from '../hooks/usePageHelpers'

type Fields = { title: string; context: string; objective: string }
type FieldErrors = Partial<Record<keyof Fields, string>>

const REQUIRED_MESSAGES: Record<keyof Fields, string> = {
  title: 'Escribí un nombre para el proyecto.',
  context: 'Contá brevemente para quién es el proyecto y en qué etapa está.',
  objective: 'Escribí qué querés lograr o validar con esta revisión.',
}

type Notice = { kind: 'archived' | 'restored'; id: string; title: string; revision: number }

export function Projects() {
  useDocumentTitle('Mis proyectos')
  const { data, error, isPending, refetch, isFetching } = useQuery({
    queryKey: ['projects'],
    queryFn: ({ signal }) => api.projects(signal),
  })
  const [creating, setCreating] = useState(false)
  const [discarding, setDiscarding] = useState(false)
  const [title, setTitle] = useState('')
  const [context, setContext] = useState('')
  const [objective, setObjective] = useState('')
  const [errors, setErrors] = useState<FieldErrors>({})
  const pendingCommand = useRef<{ key: string; payload: Fields } | null>(null)
  const navigate = useNavigate()
  const location = useLocation()
  const queryClient = useQueryClient()
  const archivedQuery = useQuery({
    queryKey: ['projects', 'archived'],
    queryFn: ({ signal }) => api.projects(signal, true),
  })
  const projects = useMemo(() => byRecent(data?.items ?? []), [data])
  const archivedProjects = useMemo(
    () => byRecent(archivedQuery.data?.items ?? []),
    [archivedQuery.data],
  )
  const compact = projects.length > 0
  const [showArchived, setShowArchived] = useState(false)
  const setArchived = useSetArchived()
  // Arriving right after archiving a project: offer to undo it. The router state is consumed once.
  const [notice, setNotice] = useState<Notice | null>(() => {
    const state = location.state as { archived?: Omit<Notice, 'kind'> } | null
    return state?.archived ? { kind: 'archived', ...state.archived } : null
  })
  useEffect(() => {
    if (location.state) navigate(location.pathname, { replace: true, state: null })
  }, [])
  function restore(target: { id: string; title: string; revision: number }) {
    setArchived.mutate(
      { id: target.id, revision: target.revision, archived: false },
      {
        onSuccess: (project) =>
          setNotice({
            kind: 'restored',
            id: project.id,
            title: project.title,
            revision: project.revision,
          }),
      },
    )
  }
  const create = useMutation({
    mutationFn: async () => {
      const command = (pendingCommand.current ||= {
        key: commandKey(),
        payload: { title: title.trim(), context: context.trim(), objective: objective.trim() },
      })
      return api.createProject(command.payload, command.key)
    },
    onSuccess: (project) => {
      pendingCommand.current = null
      queryClient.invalidateQueries({ queryKey: ['projects'] })
      navigate(`/projects/${project.id}`)
    },
    onError: (error) => {
      if (error instanceof ApiError && error.status > 0) pendingCommand.current = null
    },
  })
  const dirty = !!(title.trim() || context.trim() || objective.trim())
  function openDialog() {
    create.reset()
    setErrors({})
    setCreating(true)
  }
  function closeDialog() {
    setCreating(false)
    setDiscarding(false)
  }
  function discardAndClose() {
    pendingCommand.current = null
    setTitle('')
    setContext('')
    setObjective('')
    setErrors({})
    closeDialog()
  }
  function requestClose() {
    if (create.isPending) return
    if (dirty) setDiscarding(true)
    else closeDialog()
  }
  const dialogRef = useDialogFocus<HTMLDivElement>(creating, requestClose)
  function submit(event: React.FormEvent) {
    event.preventDefault()
    if (create.isPending) return
    const values: Fields = { title, context, objective }
    const next: FieldErrors = {}
    for (const key of Object.keys(values) as Array<keyof Fields>) {
      if (!values[key].trim()) next[key] = REQUIRED_MESSAGES[key]
    }
    setErrors(next)
    const firstInvalid = (['title', 'context', 'objective'] as const).find((key) => next[key])
    if (firstInvalid) {
      document.getElementById(`project-${firstInvalid}`)?.focus()
      return
    }
    create.mutate()
  }
  const field = (key: keyof Fields) => ({
    'aria-invalid': errors[key] ? true : undefined,
    'aria-describedby': errors[key] ? `project-${key}-error` : undefined,
    required: true,
  })
  return (
    <div className="page-wrap projects-page">
      <div className="page-kicker">
        <span className="kicker-dot" /> TU ESPACIO DE TRABAJO <span className="kicker-line" />
      </div>
      {notice ? (
        <SuccessNotice
          onDismiss={() => {
            setNotice(null)
            setArchived.reset()
          }}
          action={
            notice.kind === 'archived' ? (
              <Button
                type="button"
                variant="secondary"
                loading={setArchived.isPending}
                onClick={() =>
                  restore({ id: notice.id, title: notice.title, revision: notice.revision })
                }
              >
                <Undo2 size={16} aria-hidden /> Deshacer
              </Button>
            ) : null
          }
        >
          {notice.kind === 'archived' ? (
            <>
              Archivaste <strong>«{notice.title}»</strong>. No se borró nada: lo encontrás en
              “Proyectos archivados”.
            </>
          ) : (
            <>
              Restauraste <strong>«{notice.title}»</strong>: ya está de nuevo en tu lista.
            </>
          )}
        </SuccessNotice>
      ) : null}
      {setArchived.error ? <ErrorNotice error={setArchived.error} /> : null}
      <section className={`hero-row${compact ? ' hero-row--compact' : ''}`}>
        <div>
          <p className="eyebrow">Presentá. Cuestioná. Mejorá.</p>
          <h1>
            Ideas más sólidas, <em>una pregunta</em> a la vez.
          </h1>
          <p className="hero-copy">
            Un panel de revisión que lee tus materiales, pone a prueba tus decisiones y te ayuda a
            preparar el próximo avance con evidencia.
          </p>
        </div>
        <div className="hero-action">
          <Button onClick={openDialog}>
            <Plus size={17} aria-hidden /> Nuevo proyecto
          </Button>
        </div>
      </section>
      <ol className="steps-strip" aria-label="Cómo funciona, en tres pasos">
        <li>
          <span className="steps-strip__n" aria-hidden>
            1
          </span>
          <div>
            <strong>Cargá tus materiales</strong>
            <span>Documentos del proyecto en PDF, Markdown o texto.</span>
          </div>
        </li>
        <li>
          <span className="steps-strip__n" aria-hidden>
            2
          </span>
          <div>
            <strong>Elegí evaluadores y rúbrica</strong>
            <span>Quiénes preguntan y qué criterios se revisan.</span>
          </div>
        </li>
        <li>
          <span className="steps-strip__n" aria-hidden>
            3
          </span>
          <div>
            <strong>Respondé al panel y leé el informe</strong>
            <span>Una pregunta por vez; al final, criterio por criterio.</span>
          </div>
        </li>
        <li className="steps-strip__help">
          <Link to="/ayuda">¿Cómo funciona?</Link>
        </li>
      </ol>
      <section className="projects-section" aria-labelledby="projects-title">
        <div className="section-header">
          <div>
            <p className="eyebrow">ARCHIVO DE TRABAJO</p>
            <h2 id="projects-title">
              Tus proyectos <span className="count">{data?.items.length ?? '—'}</span>
            </h2>
          </div>
        </div>
        <ErrorNotice error={error} onRetry={() => void refetch()} retrying={isFetching} />
        {isPending ? (
          <LoadingState label="Cargando proyectos…" rows={3} />
        ) : error ? null : projects.length ? (
          <div className="project-grid">
            {projects.map((project, index) => (
              <Link className="project-card" to={`/projects/${project.id}`} key={project.id}>
                <div className="project-card__top">
                  <span className="index">{String(index + 1).padStart(2, '0')}</span>
                  <FolderOpen size={20} strokeWidth={1.5} aria-hidden />
                </div>
                <h3>{project.title}</h3>
                <p>{project.objective || project.context}</p>
                <div className="project-card__bottom">
                  <span>Actualizado {dateLabel(project.updated_at)}</span>
                  <ArrowRight size={19} aria-hidden />
                </div>
              </Link>
            ))}
          </div>
        ) : (
          <EmptyState title="Todavía no hay proyectos">
            Creá un espacio para reunir materiales, elegir evaluadores y practicar una revisión.
          </EmptyState>
        )}
      </section>
      {archivedProjects.length ? (
        <section className="archived-section" aria-label="Proyectos archivados">
          <button
            type="button"
            className="archived-toggle"
            aria-expanded={showArchived}
            aria-controls="archived-list"
            onClick={() => setShowArchived((value) => !value)}
          >
            <Archive size={18} aria-hidden /> Proyectos archivados ({archivedProjects.length})
            <ChevronDown size={18} aria-hidden className="archived-toggle__chevron" />
          </button>
          {showArchived ? (
            <ul id="archived-list" className="archived-list">
              {archivedProjects.map((project) => (
                <li key={project.id}>
                  <div className="archived-list__main">
                    <Link to={`/projects/${project.id}`}>{project.title}</Link>
                    <small>Archivado · última actualización {dateLabel(project.updated_at)}</small>
                  </div>
                  <Button
                    type="button"
                    variant="secondary"
                    aria-label={`Restaurar «${project.title}»`}
                    loading={setArchived.isPending && setArchived.variables?.id === project.id}
                    onClick={() =>
                      restore({
                        id: project.id,
                        title: project.title,
                        revision: project.revision,
                      })
                    }
                  >
                    <ArchiveRestore size={16} aria-hidden /> Restaurar
                  </Button>
                </li>
              ))}
            </ul>
          ) : null}
        </section>
      ) : null}
      {creating ? (
        <div
          className="modal-backdrop"
          onMouseDown={(event) => {
            if (event.target === event.currentTarget) requestClose()
          }}
        >
          <div
            ref={dialogRef}
            tabIndex={-1}
            className="modal"
            role="dialog"
            aria-modal="true"
            aria-labelledby="create-title"
          >
            <div className="modal__head">
              <div>
                <p className="eyebrow">NUEVO ESPACIO</p>
                <h2 id="create-title">Empezar proyecto</h2>
              </div>
              <button
                type="button"
                className="icon-button"
                onClick={requestClose}
                aria-label="Cerrar"
              >
                <X size={21} aria-hidden />
              </button>
            </div>
            <form onSubmit={submit} className="stack-form" noValidate>
              <p className="form-legend">Los campos con * son obligatorios.</p>
              <Label htmlFor="project-title" required>
                Nombre del proyecto
              </Label>
              <input
                id="project-title"
                data-dialog-initial-focus
                value={title}
                maxLength={120}
                onChange={(event) => setTitle(event.target.value)}
                placeholder="Ej. Plataforma de turnos comunitarios"
                {...field('title')}
              />
              <FieldError id="project-title-error">{errors.title}</FieldError>
              <Label htmlFor="project-context" required>
                Contexto
              </Label>
              <textarea
                id="project-context"
                value={context}
                maxLength={4000}
                onChange={(event) => setContext(event.target.value)}
                rows={3}
                placeholder="¿Para quién es y en qué etapa está?"
                {...field('context')}
              />
              <FieldError id="project-context-error">{errors.context}</FieldError>
              <Label htmlFor="project-objective" required>
                Objetivo
              </Label>
              <textarea
                id="project-objective"
                value={objective}
                maxLength={2000}
                onChange={(event) => setObjective(event.target.value)}
                rows={3}
                placeholder="¿Qué querés lograr o validar?"
                {...field('objective')}
              />
              <FieldError id="project-objective-error">{errors.objective}</FieldError>
              <ErrorNotice error={create.error} />
              <div className="modal__actions">
                <Button type="button" variant="ghost" onClick={requestClose}>
                  Cancelar
                </Button>
                <Button type="submit" loading={create.isPending}>
                  Crear proyecto <ArrowRight size={17} aria-hidden />
                </Button>
              </div>
            </form>
          </div>
        </div>
      ) : null}
      {discarding ? (
        <ConfirmDialog
          title="¿Descartar el proyecto que empezaste?"
          cancelLabel="Seguir editando"
          confirmLabel="Descartar"
          tone="danger"
          onCancel={() => setDiscarding(false)}
          onConfirm={discardAndClose}
        >
          <p>Tenés cambios sin guardar. Si cerrás ahora, se pierde lo que escribiste.</p>
        </ConfirmDialog>
      ) : null}
    </div>
  )
}
