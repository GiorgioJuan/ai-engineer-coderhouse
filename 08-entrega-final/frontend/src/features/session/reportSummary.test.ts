import { describe, expect, it } from 'vitest'
import type { CriterionFeedback } from '../../api/types'
import { joinList, summarizeReport } from './reportSummary'

const item = (criterion_id: string, status: string) =>
  ({
    criterion_id,
    status,
    observation: '',
    citations: [],
    related_turn_ids: [],
    next_action: null,
  }) as CriterionFeedback
const titles: Record<string, string> = {
  a: 'Comprensión del problema',
  b: 'Justificación de decisiones',
  c: 'Evidencia del avance',
  d: 'Alcance y próximos pasos',
  e: 'Riesgos',
}
const titleOf = (id: string) => titles[id] ?? id
const text = (chips: ReturnType<typeof summarizeReport>['chips']) =>
  chips.map((chip) => `${chip.count} ${chip.label}`).join(' · ')

describe('resumen del informe', () => {
  it('cuenta los criterios por estado, incluso los que están en cero', () => {
    const { chips } = summarizeReport(
      [
        item('a', 'supported'),
        item('b', 'supported'),
        item('c', 'partial'),
        item('d', 'not_assessed'),
      ],
      titleOf,
    )
    expect(text(chips)).toBe('2 sustentados · 1 parcial · 0 sin evidencia · 1 no evaluado')
  })

  it('nombra primero los criterios sin evidencia y después los parciales', () => {
    const { sentence } = summarizeReport(
      [item('a', 'partial'), item('b', 'supported'), item('c', 'missing')],
      titleOf,
    )
    expect(sentence).toBe('Para la próxima: Evidencia del avance y Comprensión del problema.')
  })

  it('resume cuando todo quedó sustentado y avisa de lo que no se trató', () => {
    expect(
      summarizeReport([item('a', 'supported'), item('b', 'supported')], titleOf).sentence,
    ).toBe('Todos los criterios quedaron sustentados.')
    expect(
      summarizeReport([item('a', 'supported'), item('b', 'not_assessed')], titleOf).sentence,
    ).toBe(
      'Los criterios evaluados quedaron sustentados. No se trató en la conversación: Justificación de decisiones.',
    )
    expect(summarizeReport([item('a', 'not_assessed')], titleOf).sentence).toBe(
      'Ningún criterio se llegó a evaluar en esta sesión.',
    )
  })

  it('acorta las listas largas, cuenta las preguntas abiertas y no pierde estados desconocidos', () => {
    const many = summarizeReport(
      [
        item('a', 'missing'),
        item('b', 'missing'),
        item('c', 'partial'),
        item('d', 'partial'),
        item('e', 'partial'),
      ],
      titleOf,
      2,
    )
    expect(many.sentence).toContain(
      'Para la próxima: Comprensión del problema, Justificación de decisiones, Evidencia del avance y 2 más.',
    )
    expect(many.sentence).toContain('Quedaron 2 preguntas abiertas')
    expect(text(summarizeReport([item('a', 'algo_nuevo')], titleOf).chips)).toContain(
      '1 sin clasificar',
    )
  })

  it('une listas en español', () => {
    expect(joinList(['A'])).toBe('A')
    expect(joinList(['A', 'B'])).toBe('A y B')
    expect(joinList(['A', 'B', 'C'])).toBe('A, B y C')
  })
})
