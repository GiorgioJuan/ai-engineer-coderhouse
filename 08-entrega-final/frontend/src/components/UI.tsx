import type { ButtonHTMLAttributes, LabelHTMLAttributes, ReactNode } from 'react'
import { AlertCircle, ArrowRight, CircleCheck, LoaderCircle, RotateCw, X } from 'lucide-react'
import { Link } from 'react-router-dom'
import { describeError } from '../api/errors'
import type { Tone } from '../labels'

export function Button({
  children,
  variant = 'primary',
  loading,
  ...props
}: ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: 'primary' | 'secondary' | 'ghost' | 'danger'
  loading?: boolean
}) {
  return (
    <button className={`button button--${variant}`} {...props} disabled={props.disabled || loading}>
      {loading ? <LoaderCircle size={17} className="spin" aria-hidden /> : null}
      {children}
    </button>
  )
}

/** Field label. `required` adds a visual asterisk (CSS) — pair it with `required` on the control. */
export function Label({
  children,
  hint,
  required,
  ...props
}: LabelHTMLAttributes<HTMLLabelElement> & { hint?: string; required?: boolean }) {
  return (
    <label className={`field-label${required ? ' field-label--required' : ''}`} {...props}>
      <span>{children}</span>
      {hint ? <small>{hint}</small> : null}
    </label>
  )
}

/** Inline, per-field validation message (replaces the browser's native bubble). */
export function FieldError({ id, children }: { id: string; children?: ReactNode }) {
  if (!children) return null
  return (
    <p className="field-error" id={id} role="alert">
      <AlertCircle size={15} aria-hidden /> {children}
    </p>
  )
}

/**
 * Plain-Spanish error box. Technical text from the backend never shows by default: it is
 * kept inside a collapsed "Detalle técnico". Pass `onRetry` wherever a query can be refetched.
 */
export function ErrorNotice({
  error,
  children,
  onRetry,
  retrying,
}: {
  error?: unknown
  children?: ReactNode
  onRetry?: () => void
  retrying?: boolean
}) {
  if (!error && !children) return null
  const info = describeError(error || undefined)
  return (
    <div className="notice notice--error" role="alert">
      <AlertCircle size={18} aria-hidden />
      <div className="notice__body">
        <p className="notice__text">
          {children ? (
            children
          ) : (
            <>
              <span>{info.message}</span>
              {info.hint ? <span className="notice__hint"> {info.hint}</span> : null}
            </>
          )}
        </p>
        {!children && onRetry && info.retryable ? (
          <Button type="button" variant="secondary" loading={retrying} onClick={onRetry}>
            <RotateCw size={15} aria-hidden /> Reintentar
          </Button>
        ) : null}
        {!children && info.technical ? (
          <details className="notice__details">
            <summary>Detalle técnico</summary>
            <pre>{info.technical}</pre>
          </details>
        ) : null}
      </div>
    </div>
  )
}

/** Dismissible confirmation of something that just happened, optionally with an undo-style action. */
export function SuccessNotice({
  children,
  action,
  onDismiss,
}: {
  children: ReactNode
  action?: ReactNode
  onDismiss: () => void
}) {
  return (
    <div className="notice notice--success" role="status">
      <CircleCheck size={18} aria-hidden />
      <p className="notice__text">{children}</p>
      {action}
      <button type="button" className="notice__close" aria-label="Cerrar aviso" onClick={onDismiss}>
        <X size={18} aria-hidden />
      </button>
    </div>
  )
}

/** Loading indicator that tells screen readers what is loading and never pretends the data is empty. */
export function LoadingState({
  label = 'Cargando…',
  rows = 0,
}: {
  label?: string
  /** Number of skeleton placeholder rows drawn under the label. */
  rows?: number
}) {
  return (
    <div className="loading-state" role="status">
      <p>
        <LoaderCircle size={18} className="spin" aria-hidden /> {label}
      </p>
      {rows > 0 ? (
        <div className="skeleton-rows" aria-hidden>
          {Array.from({ length: rows }, (_, index) => (
            <span className="skeleton" key={index} />
          ))}
        </div>
      ) : null}
    </div>
  )
}

export function EmptyState({
  title,
  children,
  action,
}: {
  title: string
  children: ReactNode
  action?: { label: string; to: string }
}) {
  return (
    <div className="empty-state">
      <span className="empty-state__mark" aria-hidden>
        ✳
      </span>
      <h3>{title}</h3>
      <p>{children}</p>
      {action ? (
        <Link className="text-link" to={action.to}>
          {action.label}
          <ArrowRight size={16} aria-hidden />
        </Link>
      ) : null}
    </div>
  )
}
export function StatePill({ children, tone = 'neutral' }: { children: ReactNode; tone?: Tone }) {
  return <span className={`state-pill state-pill--${tone}`}>{children}</span>
}
export function dateLabel(value?: string) {
  if (!value) return 'Sin fecha'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return 'Sin fecha'
  return new Intl.DateTimeFormat('es-AR', {
    day: 'numeric',
    month: 'short',
    year: 'numeric',
  }).format(date)
}
export function latest<T>(
  items: T[],
  getId: (item: T) => string,
  getVersion: (item: T) => number,
): T[] {
  const versions = new Map<string, T>()
  for (const item of items) {
    const id = getId(item)
    const current = versions.get(id)
    if (!current || getVersion(item) > getVersion(current)) versions.set(id, item)
  }
  return [...versions.values()]
}
