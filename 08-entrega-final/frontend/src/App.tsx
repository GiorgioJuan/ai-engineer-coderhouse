import { lazy, Suspense } from 'react'
import { Route, Routes } from 'react-router-dom'
import { AppShell } from './components/AppShell'
import { NotFoundState } from './components/NotFound'
import { LoadingState } from './components/UI'
import { Help } from './pages/Help'
import { useDocumentTitle } from './hooks/usePageHelpers'

const Projects = lazy(() =>
  import('./pages/Projects').then((module) => ({ default: module.Projects })),
)
const ProjectWorkspace = lazy(() =>
  import('./pages/ProjectWorkspace').then((module) => ({ default: module.ProjectWorkspace })),
)
const SessionSetup = lazy(() =>
  import('./pages/SessionSetup').then((module) => ({ default: module.SessionSetup })),
)
const SessionRoom = lazy(() =>
  import('./pages/SessionRoom').then((module) => ({ default: module.SessionRoom })),
)
const SessionReport = lazy(() =>
  import('./pages/SessionReport').then((module) => ({ default: module.SessionReport })),
)

function NotFoundPage() {
  useDocumentTitle('Página no encontrada')
  return (
    <AppShell>
      <NotFoundState />
    </AppShell>
  )
}

export function App() {
  return (
    <Suspense
      fallback={
        <AppShell>
          <div className="page-wrap">
            <LoadingState label="Cargando…" rows={3} />
          </div>
        </AppShell>
      }
    >
      <Routes>
        <Route
          path="/"
          element={
            <AppShell>
              <Projects />
            </AppShell>
          }
        />
        <Route path="/ayuda" element={<Help />} />
        <Route path="/projects/:id" element={<ProjectWorkspace />} />
        <Route path="/projects/:id/sessions/new" element={<SessionSetup />} />
        <Route path="/sessions/:id" element={<SessionRoom />} />
        <Route path="/sessions/:id/report" element={<SessionReport />} />
        <Route path="*" element={<NotFoundPage />} />
      </Routes>
    </Suspense>
  )
}
