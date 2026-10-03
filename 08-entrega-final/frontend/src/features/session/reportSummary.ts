import type { CriterionFeedback } from '../../api/types'
import type { Tone } from '../../labels'

type Key = CriterionFeedback['status']

/** Statuses from best to weakest, with the wording used in the summary chips. */
const ORDER: Array<{ key: Key; one: string; many: string; tone: Tone }> = [
  { key: 'supported', one: 'sustentado', many: 'sustentados', tone: 'good' },
  { key: 'partial', one: 'parcial', many: 'parciales', tone: 'busy' },
  { key: 'missing', one: 'sin evidencia', many: 'sin evidencia', tone: 'bad' },
  { key: 'not_assessed', one: 'no evaluado', many: 'no evaluados', tone: 'neutral' },
]

export type SummaryChip = { key: string; count: number; label: string; tone: Tone }

/** "A", "A y B", "A, B y C". */
export function joinList(items: string[]): string {
  if (items.length <= 1) return items.join('')
  return `${items.slice(0, -1).join(', ')} y ${items[items.length - 1]}`
}

/**
 * Counts criteria per status and writes one plain sentence naming the weakest ones
 * (no evidence first, then partial), all computed from the report itself.
 */
export function summarizeReport(
  items: CriterionFeedback[],
  titleOf: (criterionId: string) => string,
  pendingQuestions = 0,
): { chips: SummaryChip[]; sentence: string } {
  const known = new Set<string>(ORDER.map((entry) => entry.key))
  const chips: SummaryChip[] = ORDER.map(({ key, one, many, tone }) => {
    const count = items.filter((item) => item.status === key).length
    return { key, count, label: count === 1 ? one : many, tone: count ? tone : 'neutral' }
  })
  const other = items.filter((item) => !known.has(item.status)).length
  if (other) chips.push({ key: 'other', count: other, label: 'sin clasificar', tone: 'neutral' })

  const titles = (status: Key) =>
    items.filter((item) => item.status === status).map((item) => titleOf(item.criterion_id))
  const list = (names: string[]) => {
    const shown = names.slice(0, 3)
    const more = names.length - shown.length
    return joinList(more ? [...shown, `${more} más`] : shown)
  }
  // Weakest first: no evidence, then partial.
  const weak = [...titles('missing'), ...titles('partial')]
  const untreated = titles('not_assessed')
  const supported = chips[0].count
  const parts: string[] = []
  if (weak.length) parts.push(`Para la próxima: ${list(weak)}.`)
  else if (items.length && supported === items.length)
    parts.push('Todos los criterios quedaron sustentados.')
  else if (supported) parts.push('Los criterios evaluados quedaron sustentados.')
  else parts.push('Ningún criterio se llegó a evaluar en esta sesión.')
  if (untreated.length && (weak.length || supported))
    parts.push(`No se trató en la conversación: ${list(untreated)}.`)
  let sentence = parts.join(' ')
  if (pendingQuestions)
    sentence += ` ${pendingQuestions === 1 ? 'Quedó 1 pregunta abierta' : `Quedaron ${pendingQuestions} preguntas abiertas`} (más abajo).`
  return { chips, sentence }
}
