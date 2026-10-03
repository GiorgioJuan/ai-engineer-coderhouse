import { ArrowDownRight, ArrowRight, ArrowUpRight, CircleDashed } from 'lucide-react'
import type { CriterionChange } from '../../api/types'
import { StatePill } from '../../components/UI'
import { reportStatus } from '../../labels'

const rank: Record<string, number> = { missing: 1, partial: 2, supported: 3 }

function sources(count: number) {
  if (count === 0) return 'sin fuentes citadas'
  return count === 1 ? '1 fuente citada' : `${count} fuentes citadas`
}

/** Describe el cambio de un criterio entre la sesión anterior y la actual. */
export function describeChange(change: CriterionChange) {
  const before = change.previous_status
  const now = change.current_status
  if (before === 'not_assessed' && now === 'not_assessed')
    return { label: 'No se trató en ninguna', icon: CircleDashed, tone: 'neutral' as const }
  if (before === 'not_assessed')
    return { label: 'Tratado por primera vez', icon: ArrowUpRight, tone: 'good' as const }
  if (now === 'not_assessed')
    return { label: 'No se trató esta vez', icon: CircleDashed, tone: 'neutral' as const }
  if (rank[now] > rank[before])
    return { label: 'Mejoró', icon: ArrowUpRight, tone: 'good' as const }
  if (rank[now] < rank[before])
    return { label: 'Retrocedió', icon: ArrowDownRight, tone: 'bad' as const }
  return { label: 'Sin cambios', icon: ArrowRight, tone: 'neutral' as const }
}

export function ComparisonTable({ changes }: { changes: CriterionChange[] }) {
  return (
    <table className="comparison-table">
      <caption className="sr-only">Estado de cada criterio en la sesión anterior y en esta</caption>
      <thead>
        <tr>
          <th scope="col">Criterio</th>
          <th scope="col">Sesión anterior</th>
          <th scope="col">Esta sesión</th>
          <th scope="col">Cambio</th>
        </tr>
      </thead>
      <tbody>
        {changes.map((change) => {
          const before = reportStatus(change.previous_status)
          const now = reportStatus(change.current_status)
          const trend = describeChange(change)
          const Icon = trend.icon
          return (
            <tr key={change.criterion_id}>
              <th scope="row">{change.title}</th>
              <td data-label="Sesión anterior">
                <StatePill tone={before.tone}>{before.label}</StatePill>
                <small>{sources(change.previous_sources)}</small>
              </td>
              <td data-label="Esta sesión">
                <StatePill tone={now.tone}>{now.label}</StatePill>
                <small>{sources(change.current_sources)}</small>
              </td>
              <td
                data-label="Cambio"
                className={`comparison-trend comparison-trend--${trend.tone}`}
              >
                <Icon size={16} aria-hidden /> {trend.label}
              </td>
            </tr>
          )
        })}
      </tbody>
    </table>
  )
}
