import type { ReactNode } from 'react'
import { SearchX } from 'lucide-react'
import { Link } from 'react-router-dom'

/** Clear "this does not exist" state with a way out. `page` renders it as the page's h1. */
export function NotFoundState({
  title = 'No encontramos esta página',
  children = 'Puede que el enlace sea incorrecto o que el contenido ya no exista.',
  to = '/',
  linkLabel = 'Volver a mis proyectos',
}: {
  title?: string
  children?: ReactNode
  to?: string
  linkLabel?: string
}) {
  return (
    <div className="page-wrap">
      <div className="not-found" role="status">
        <span className="not-found__mark" aria-hidden>
          <SearchX size={30} strokeWidth={1.6} />
        </span>
        <h1>{title}</h1>
        <p>{children}</p>
        <Link className="button button--primary" to={to}>
          {linkLabel}
        </Link>
      </div>
    </div>
  )
}
