import { useRef } from 'react'
import { CircleAlert, LoaderCircle, RotateCw } from 'lucide-react'
import { Link } from 'react-router-dom'
import type { ErrorInfo } from '../../api/errors'
import { ErrorNotice, Button } from '../../components/UI'
import { useElapsedSeconds } from '../../hooks/usePageHelpers'

export type ProcessingPhase = 'first' | 'next' | 'report'

const COPY: Record<ProcessingPhase, { title: string; running: string; eta: string }> = {
  first: {
    title: 'Preparando la primera pregunta…',
    running: 'El panel está leyendo tus materiales y tu presentación.',
    eta: 'Suele tardar entre 5 y 40 segundos.',
  },
  next: {
    title: 'Preparando la próxima pregunta…',
    running: 'El panel está leyendo tu respuesta y buscando evidencia en tus materiales.',
    eta: 'Suele tardar entre 5 y 40 segundos.',
  },
  report: {
    title: 'Armando tu informe…',
    running: 'El panel está repasando toda la conversación, criterio por criterio.',
    eta: 'Suele tardar entre 10 segundos y un minuto.',
  },
}

export function formatElapsed(seconds: number): string {
  if (seconds < 60) return `${seconds} s`
  if (seconds < 600)
    return `${Math.floor(seconds / 60)} min ${String(seconds % 60).padStart(2, '0')} s`
  return 'más de 10 min'
}

/** What the panel is doing right now, with an elapsed timer. The timer is not announced every second. */
export function ProcessingState({
  status,
  phase,
  startedAt,
}: {
  status: 'QUEUED' | 'RUNNING'
  phase: ProcessingPhase
  /** ISO timestamp of the last server-side change, used to keep the timer honest after a reload. */
  startedAt?: string
}) {
  const mounted = useRef(Date.now())
  const server = startedAt ? Date.parse(startedAt) : Number.NaN
  const since = Number.isNaN(server) ? mounted.current : Math.min(mounted.current, server)
  const elapsed = useElapsedSeconds(since)
  const copy = COPY[phase]
  return (
    <div className="processing-state" role="status" aria-live="polite">
      <LoaderCircle size={21} className="spin" aria-hidden />
      <div>
        <p className="processing-state__title">
          <strong>{copy.title}</strong>{' '}
          <span className="processing-state__timer" aria-live="off">
            · {formatElapsed(elapsed)}
          </span>
        </p>
        <p>
          {status === 'QUEUED'
            ? 'Tu pedido está en la fila y empieza en un momento. '
            : `${copy.running} `}
          {copy.eta}
        </p>
        {elapsed > 90 ? (
          <p>
            Está tardando más de lo habitual. Podés seguir esperando: tu progreso está guardado y
            esta pantalla se actualiza sola.
          </p>
        ) : (
          <p>Podés esperar acá o volver más tarde: la conversación se guarda automáticamente.</p>
        )}
      </div>
    </div>
  )
}

/** A failed job always offers a way out: retry (when it can help) and back to the project. */
export function FailedState({
  info,
  onRetry,
  retrying,
  retryError,
  projectTo,
}: {
  info: ErrorInfo
  onRetry?: () => void
  retrying?: boolean
  retryError?: unknown
  projectTo: string
}) {
  return (
    <div className="processing-state processing-state--error" role="alert">
      <CircleAlert size={21} aria-hidden />
      <div>
        <p className="processing-state__title">
          <strong>No se pudo continuar la sesión</strong>
        </p>
        <p>
          {info.message}
          {info.hint ? ` ${info.hint}` : ''}
        </p>
        <div className="processing-state__actions">
          {onRetry ? (
            <Button variant="secondary" loading={retrying} onClick={onRetry}>
              <RotateCw size={15} aria-hidden /> Reintentar
            </Button>
          ) : null}
          <Link className="button button--ghost" to={projectTo}>
            Volver al proyecto
          </Link>
        </div>
        <ErrorNotice error={retryError} />
        {info.technical ? (
          <details className="notice__details">
            <summary>Detalle técnico</summary>
            <pre>{info.technical}</pre>
          </details>
        ) : null}
      </div>
    </div>
  )
}
