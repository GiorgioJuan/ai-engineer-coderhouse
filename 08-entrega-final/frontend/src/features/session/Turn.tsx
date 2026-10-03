import { BookOpen } from 'lucide-react'
import type { Citation, Turn } from '../../api/types'
import { citationLabel } from '../../api/hooks'
import { turnKindLabel } from '../../labels'

export function CitationButtons({
  citations,
  onSelect,
  titleOf,
}: {
  citations: Citation[]
  onSelect: (citation: Citation) => void
  /** Resolves the human title of the cited document (empty while materials load). */
  titleOf: (citation: Citation) => string
}) {
  return citations.length ? (
    <div className="citation-buttons">
      {citations.map((citation, index) => {
        const label = citationLabel(titleOf(citation), citation.section)
        return (
          <button
            type="button"
            key={`${citation.chunk_id}-${index}`}
            onClick={() => onSelect(citation)}
            title={`Ver el fragmento citado: ${label}`}
          >
            <BookOpen size={14} aria-hidden /> <span>{label}</span>
          </button>
        )
      })}
    </div>
  ) : null
}

export function TurnCard({
  turn,
  name,
  role,
  criterion,
  highlighted,
  onCitation,
  titleOf,
}: {
  turn: Turn
  /** Evaluator name (question turns only). */
  name?: string
  role?: string
  /** Criterion title the question is about, when known. */
  criterion?: string
  highlighted?: boolean
  onCitation: (citation: Citation) => void
  titleOf: (citation: Citation) => string
}) {
  const isQuestion = turn.kind === 'question'
  const time = new Date(turn.created_at).toLocaleTimeString('es-AR', {
    hour: '2-digit',
    minute: '2-digit',
  })
  return (
    <article
      className={`turn-card turn-card--${turn.kind}${highlighted ? ' turn-card--highlight' : ''}`}
      id={`turn-${turn.id}`}
    >
      <div className="turn-card__meta">
        {isQuestion ? (
          <div className="turn-card__who">
            <strong>{name || 'Evaluador'}</strong>
            {role || criterion ? (
              <span>{[role, criterion].filter(Boolean).join(' · ')}</span>
            ) : null}
          </div>
        ) : (
          <span className="turn-card__kind">{turnKindLabel[turn.kind] || 'Mensaje'}</span>
        )}
        <time dateTime={turn.created_at}>{time}</time>
      </div>
      <p id={`turn-text-${turn.id}`}>{turn.text}</p>
      <CitationButtons citations={turn.citations || []} onSelect={onCitation} titleOf={titleOf} />
    </article>
  )
}
