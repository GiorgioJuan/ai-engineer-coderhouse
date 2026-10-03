import { useRef, useState } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import {
  Archive,
  ArchiveRestore,
  ArrowRight,
  BookOpen,
  Files,
  ListChecks,
  Radio,
  Sparkles,
} from 'lucide-react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { useSetArchived } from '../api/archive'
import { commandKey, api } from '../api/client'
import { isNotFound } from '../api/errors'
import { useHealth } from '../api/health'
import { useProjectData } from '../api/hooks'
import { AppShell } from '../components/AppShell'
import { ConfirmDialog } from '../components/ConfirmDialog'
import { NotFoundState } from '../components/NotFound'
import { TabPanel, Tabs } from '../components/Tabs'
import {
  Button,
  EmptyState,
  ErrorNotice,
  LoadingState,
  StatePill,
  SuccessNotice,
  dateLabel,
  latest,
} from '../components/UI'
import { ConfigPanel } from '../features/content/ConfigPanel'
import { DocumentPanel } from '../features/content/DocumentPanel'
import { useDocumentTitle } from '../hooks/usePageHelpers'
import { sessionStatus } from '../labels'

type Tab = 'materials' | 'panel' | 'sessions'
const TABS_ID = 'workspace'

/** Two-digit counter, or an em dash while the number is not known yet (never a fake "00"). */
const counter = (value: number | undefined) =>
  value === undefined ? '—' : value.toString().padStart(2, '0')

export function ProjectWorkspace() {
  const { id = '' } = useParams()
  const [tab, setTab] = useState<Tab>('materials')
  const seedKey = useRef<string | null>(null)
  const data = useProjectData(id)
  const health = useHealth()
  const queryClient = useQueryClient()
  const navigate = useNavigate()
  const setArchived = useSetArchived()
  const [confirmingArchive, setConfirmingArchive] = useState(false)
  const [restored, setRestored] = useState(false)
  const seed = useMutation({
    mutationFn: () => api.seedDemo(id, (seedKey.current ||= commandKey())),
    onSuccess: () => {
      seedKey.current = null
      queryClient.invalidateQueries({ queryKey: ['documents', id] })
    },
  })
  const project = data.project.data
  useDocumentTitle(project?.title || 'Proyecto')

  if (data.project.isPending) {
    return (
      <AppShell back={{ to: '/', label: 'Todos los proyectos' }}>
        <div className="page-wrap workspace-page">
          <LoadingState label="Cargando proyecto…" rows={4} />
        </div>
      </AppShell>
    )
  }
  if (data.project.isError) {
    if (isNotFound(data.project.error))
      return (
        <AppShell back={{ to: '/', label: 'Todos los proyectos' }}>
          <NotFoundState title="No encontramos este proyecto">
            Puede que el enlace sea incorrecto o que el proyecto ya no exista.
          </NotFoundState>
        </AppShell>
      )
    return (
      <AppShell back={{ to: '/', label: 'Todos los proyectos' }}>
        <div className="page-wrap workspace-page">
          <h1 className="page-error-title">No pudimos abrir el proyecto</h1>
          <ErrorNotice
            error={data.project.error}
            onRetry={() => void data.project.refetch()}
            retrying={data.project.isFetching}
          />
          <Link className="text-link" to="/">
            Volver a mis proyectos
          </Link>
        </div>
      </AppShell>
    )
  }

  if (!project) return null
  const docsLoaded = data.documents.isSuccess
  const docs = data.documents.data?.items || []
  const profiles = data.profiles.data?.items || []
  const rubrics = data.rubrics.data?.items || []
  const sessions = data.sessions.data?.items || []
  const currentDocs = latest(
    docs,
    (doc) => doc.document_id,
    (doc) => doc.version,
  )
  const currentProfiles = latest(
    profiles,
    (profile) => profile.profile_id,
    (profile) => profile.version,
  )
  const readyCount = currentDocs.filter((doc) => doc.index_status === 'READY').length
  const isDemo = health.data?.llm_mode === 'demo'
  const showDemoCallout = isDemo && docsLoaded && currentDocs.length === 0
  const configLoaded = data.profiles.isSuccess && data.rubrics.isSuccess
  const configError = data.profiles.error || data.rubrics.error
  return (
    <AppShell back={{ to: '/', label: 'Todos los proyectos' }} eyebrow={project.title}>
      <div className="page-wrap workspace-page">
        {project.archived ? (
          <div className="archived-banner" role="status">
            <Archive size={20} aria-hidden />
            <div>
              <strong>Este proyecto está archivado</strong>
              <p>No aparece en tu lista de proyectos hasta que lo restaures.</p>
              <ErrorNotice error={setArchived.error} />
            </div>
            <Button
              variant="secondary"
              loading={setArchived.isPending}
              onClick={() =>
                setArchived.mutate(
                  { id, revision: project.revision, archived: false },
                  { onSuccess: () => setRestored(true) },
                )
              }
            >
              <ArchiveRestore size={16} aria-hidden /> Restaurar
            </Button>
          </div>
        ) : null}
        {restored && !project.archived ? (
          <SuccessNotice onDismiss={() => setRestored(false)}>
            Restauraste este proyecto: ya está de nuevo en tu lista.
          </SuccessNotice>
        ) : null}
        <div className="workspace-hero">
          <div>
            <p className="eyebrow">ESPACIO DE TRABAJO</p>
            <h1>{project.title}</h1>
            <p>{project.objective}</p>
          </div>
          <div className="workspace-hero__action">
            <span>Prepará tu próxima revisión</span>
            <Link className="button button--primary" to={`/projects/${id}/sessions/new`}>
              Preparar sesión <ArrowRight size={17} aria-hidden />
            </Link>
          </div>
        </div>
        {showDemoCallout ? (
          <div className="demo-callout">
            <div className="demo-callout__symbol">
              <Sparkles size={22} aria-hidden />
            </div>
            <div>
              <strong>Probá con un caso ficticio</strong>
              <p>
                Importá materiales de Laboratorio 3 para explorar la revisión. Los documentos
                quedarán señalados como ejemplo.
              </p>
            </div>
            <Button
              variant="secondary"
              loading={seed.isPending}
              onClick={() => {
                if (!seed.isPending) seed.mutate()
              }}
            >
              Usar ejemplo de Laboratorio 3
            </Button>
            <ErrorNotice error={seed.error} />
          </div>
        ) : null}
        <div className="workspace-stats">
          <div>
            <span>01 / MATERIALES</span>
            <strong>{counter(docsLoaded ? readyCount : undefined)}</strong>
            <small>listos para consultar</small>
          </div>
          <div>
            <span>02 / EVALUADORES</span>
            <strong>{counter(data.profiles.isSuccess ? currentProfiles.length : undefined)}</strong>
            <small>disponibles</small>
          </div>
          <div>
            <span>03 / SESIONES</span>
            <strong>{counter(data.sessions.isSuccess ? sessions.length : undefined)}</strong>
            <small>en el historial</small>
          </div>
        </div>
        <Tabs<Tab>
          className="workspace-tabs"
          label="Secciones del proyecto"
          idPrefix={TABS_ID}
          value={tab}
          onChange={setTab}
          items={[
            {
              id: 'materials',
              label: (
                <>
                  <Files size={18} aria-hidden /> Materiales
                  {docsLoaded ? <span>{currentDocs.length}</span> : null}
                </>
              ),
            },
            {
              id: 'panel',
              label: (
                <>
                  <ListChecks size={18} aria-hidden /> Evaluadores y rúbrica
                </>
              ),
            },
            {
              id: 'sessions',
              label: (
                <>
                  <BookOpen size={18} aria-hidden /> Sesiones
                  {data.sessions.isSuccess ? <span>{sessions.length}</span> : null}
                </>
              ),
            },
          ]}
        />
        {tab === 'materials' ? (
          <TabPanel idPrefix={TABS_ID} id="materials" focusable={false}>
            {data.documents.isPending ? (
              <LoadingState label="Cargando materiales…" rows={3} />
            ) : data.documents.isError ? (
              <ErrorNotice
                error={data.documents.error}
                onRetry={() => void data.documents.refetch()}
                retrying={data.documents.isFetching}
              />
            ) : (
              <DocumentPanel projectId={id} documents={docs} />
            )}
          </TabPanel>
        ) : null}
        {tab === 'panel' ? (
          <TabPanel idPrefix={TABS_ID} id="panel" focusable={false}>
            {configError ? (
              <ErrorNotice
                error={configError}
                onRetry={() => {
                  void data.profiles.refetch()
                  void data.rubrics.refetch()
                }}
                retrying={data.profiles.isFetching || data.rubrics.isFetching}
              />
            ) : !configLoaded ? (
              <LoadingState label="Cargando evaluadores y rúbrica…" rows={3} />
            ) : (
              <ConfigPanel projectId={id} profiles={profiles} rubrics={rubrics} />
            )}
          </TabPanel>
        ) : null}
        {tab === 'sessions' ? (
          <TabPanel idPrefix={TABS_ID} id="sessions" focusable={false}>
            <div className="workspace-panel">
              <div className="panel-intro">
                <div>
                  <p className="eyebrow">03 / HISTORIAL</p>
                  <h2>Cada revisión cuenta</h2>
                  <p>Volvé a una sesión o compará los hallazgos de semanas anteriores.</p>
                </div>
                <Link className="button button--primary" to={`/projects/${id}/sessions/new`}>
                  Nueva sesión <ArrowRight size={17} aria-hidden />
                </Link>
              </div>
              {data.sessions.isPending ? (
                <LoadingState label="Cargando sesiones…" rows={3} />
              ) : data.sessions.isError ? (
                <ErrorNotice
                  error={data.sessions.error}
                  onRetry={() => void data.sessions.refetch()}
                  retrying={data.sessions.isFetching}
                />
              ) : sessions.length ? (
                <div className="session-list">
                  {sessions.map((session) => {
                    const status = sessionStatus(session.status)
                    return (
                      <Link
                        className="session-row"
                        key={session.id}
                        to={
                          session.status === 'COMPLETED'
                            ? `/sessions/${session.id}/report`
                            : `/sessions/${session.id}`
                        }
                      >
                        <span className="session-row__icon">
                          <Radio size={18} aria-hidden />
                        </span>
                        <span className="session-row__main">
                          <strong>{session.objective}</strong>
                          <small>
                            {dateLabel(session.created_at)} · {session.question_count} de{' '}
                            {session.max_questions} preguntas
                          </small>
                        </span>
                        <StatePill tone={status.tone}>{status.label}</StatePill>
                        <ArrowRight size={18} aria-hidden />
                      </Link>
                    )
                  })}
                </div>
              ) : (
                <EmptyState title="Sin sesiones todavía">
                  Cuando inicies una revisión, acá vas a poder retomarla o leer su informe.
                </EmptyState>
              )}
            </div>
          </TabPanel>
        ) : null}
        {!project.archived ? (
          <footer className="project-footer">
            <p>¿Terminaste con este proyecto? Podés ocultarlo de tu lista sin borrar nada.</p>
            <button type="button" className="text-link" onClick={() => setConfirmingArchive(true)}>
              <Archive size={16} aria-hidden /> Archivar proyecto
            </button>
          </footer>
        ) : null}
      </div>
      {confirmingArchive ? (
        <ConfirmDialog
          title="¿Archivar este proyecto?"
          cancelLabel="Cancelar"
          confirmLabel="Archivar"
          busy={setArchived.isPending}
          onCancel={() => {
            setConfirmingArchive(false)
            setArchived.reset()
          }}
          onConfirm={() =>
            setArchived.mutate(
              { id, revision: project.revision, archived: true },
              {
                onSuccess: (updated) =>
                  navigate('/', {
                    state: {
                      archived: {
                        id: updated.id,
                        title: updated.title,
                        revision: updated.revision,
                      },
                    },
                  }),
              },
            )
          }
        >
          <p>
            Vas a ocultar «{project.title}» de tu lista. No se borra nada: podés restaurarlo desde
            Proyectos archivados.
          </p>
          <ErrorNotice error={setArchived.error} />
        </ConfirmDialog>
      ) : null}
    </AppShell>
  )
}
