import { describe, expect, it } from 'vitest'
import type { ProfileVersion, RubricVersion } from '../../api/types'
import { profileTemplate, rubricTemplate } from './templates'

const rubric = {
  rubric_id: 'proyecto-cliente',
  criteria: [
    { id: 'problema', title: 'a', description: 'a' },
    { id: 'evidencia', title: 'b', description: 'b' },
    { id: 'alcance', title: 'c', description: 'c' },
  ],
} as RubricVersion

describe('plantillas del editor Markdown', () => {
  it('la plantilla de evaluador tiene exactamente los campos que exige el backend', () => {
    const text = profileTemplate([{ profile_id: 'evaluador-1' } as ProfileVersion], [rubric])
    const front = text.split('\n---\n')[0]
    expect(text.startsWith('---\n')).toBe(true)
    for (const key of ['id:', 'name:', 'role:', 'focus:', 'style:']) expect(front).toContain(key)
    expect(front).not.toContain('criteria:')
    expect(front).toContain('id: evaluador-2')
    expect(front).toContain('  - problema')
    expect(front).toContain('  - evidencia')
    expect(text.split('\n---\n')[1].trim()).not.toBe('')
  })

  it('usa un criterio genérico cuando todavía no hay rúbrica', () => {
    expect(profileTemplate([], [])).toContain('  - evidencia')
  })

  it('la plantilla de rúbrica trae criterios con id, título y descripción y un id libre', () => {
    const text = rubricTemplate([{ rubric_id: 'rubrica-2' } as RubricVersion])
    expect(text).toContain('id: rubrica-3')
    expect(text.match(/- id: /g)?.length).toBeGreaterThanOrEqual(1)
    expect(text).toMatch(/title: .+/)
    expect(text).toMatch(/description: .+/)
    expect(text).toContain('## Cómo devolver')
  })
})
