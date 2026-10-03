import { ArrowLeft, CircleHelp, PanelTop, Radio, RotateCw, WifiOff } from 'lucide-react'
import { Link, useLocation } from 'react-router-dom'
import type { ReactNode } from 'react'
import { serverProblem, useHealth } from '../api/health'

export type Crumb = { label: string; to?: string }

function ServerStatusBanner({
  problem,
  onRetry,
  retrying,
}: {
  problem: 'down' | 'worker'
  onRetry: () => void
  retrying: boolean
}) {
  return (
    <div className="server-banner" role="status">
      <WifiOff size={18} aria-hidden />
      <p>
        {problem === 'down' ? (
          <>
            <strong>El servidor no está disponible.</strong> Seguimos intentando reconectar. Lo que
            ya guardaste no se pierde.
          </>
        ) : (
          <>
            <strong>El servicio que prepara las preguntas no responde.</strong> Podés seguir
            navegando, pero las respuestas del panel pueden demorar. Seguimos intentando.
          </>
        )}
      </p>
      <button type="button" onClick={onRetry} disabled={retrying}>
        <RotateCw size={14} aria-hidden /> Reintentar ahora
      </button>
    </div>
  )
}

export function AppShell({
  children,
  back,
  eyebrow,
  breadcrumbs,
}: {
  children: ReactNode
  back?: { to: string; label: string }
  eyebrow?: string
  breadcrumbs?: Crumb[]
}) {
  const health = useHealth()
  const location = useLocation()
  const mode = health.data?.llm_mode
  const demo = typeof mode === 'string' && /demo|mock|fixture|deterministic/i.test(mode)
  const problem = serverProblem(health)
  return (
    <div className="app-shell">
      <a className="skip-link" href="#main">
        Saltar al contenido
      </a>
      {problem ? (
        <ServerStatusBanner
          problem={problem}
          onRetry={() => void health.refetch()}
          retrying={health.isFetching}
        />
      ) : null}
      <header className="site-header">
        <Link to="/" className="brand" aria-label="PanelLab, ir a mis proyectos">
          <span className="brand__icon">
            <PanelTop size={23} strokeWidth={1.8} />
          </span>
          <span>
            panel<span className="brand__italic">lab</span>
          </span>
        </Link>
        <div className="site-header__right">
          <span className="site-header__descriptor">Mesa de revisión de proyectos</span>
          {demo || mode === 'live' ? (
            <Link
              to="/ayuda#modo-demostracion"
              className="mode-badge"
              title={
                demo
                  ? 'Respuestas de ejemplo, sin costo ni conexión a un modelo. Tocá para saber más.'
                  : 'Las preguntas las genera un modelo de IA a partir de tus materiales. Tocá para saber más.'
              }
            >
              <Radio size={14} aria-hidden /> {demo ? 'Modo demostración' : 'IA en vivo'}
            </Link>
          ) : null}
          <Link to="/ayuda" className="header-help">
            <CircleHelp size={20} aria-hidden />
            <span className="header-help__label">¿Cómo funciona?</span>
          </Link>
        </div>
      </header>
      {breadcrumbs?.length ? (
        <nav className="backbar breadcrumbs" aria-label="Ruta de navegación">
          <ol>
            {breadcrumbs.map((crumb, index) => {
              const last = index === breadcrumbs.length - 1
              return (
                <li key={`${crumb.label}-${index}`}>
                  {crumb.to && !last ? (
                    <Link to={crumb.to}>{crumb.label}</Link>
                  ) : (
                    <span aria-current={last ? 'page' : undefined}>{crumb.label}</span>
                  )}
                </li>
              )
            })}
          </ol>
        </nav>
      ) : back ? (
        <div className="backbar">
          <Link to={back.to}>
            <ArrowLeft size={17} aria-hidden /> {back.label}
          </Link>
          <span>{eyebrow}</span>
        </div>
      ) : null}
      <main id="main" tabIndex={-1} key={location.pathname}>
        {children}
      </main>
      <footer className="site-footer">
        <span>PanelLab · revisión con evidencia</span>
        <span className="site-footer__links">
          <Link to="/ayuda">¿Cómo funciona?</Link>
          <span>El criterio final siempre es tuyo</span>
        </span>
      </footer>
    </div>
  )
}
