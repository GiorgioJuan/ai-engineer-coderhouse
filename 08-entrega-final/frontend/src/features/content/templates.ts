import type { ProfileVersion, RubricVersion } from '../../api/types'

/** First `prefix-N` id that is not taken yet, so a template never overwrites an existing item. */
function freeId(prefix: string, taken: string[]): string {
  let number = taken.length + 1
  while (taken.includes(`${prefix}-${number}`)) number++
  return `${prefix}-${number}`
}

/**
 * Valid starting point for an evaluator (see backend/app/content.py: the frontmatter must have
 * exactly id, name, role, focus and style). `focus` reuses real criterion ids when a rubric exists
 * so the evaluator can be picked in a session right away.
 */
export function profileTemplate(profiles: ProfileVersion[], rubrics: RubricVersion[]): string {
  const criteria = rubrics.flatMap((rubric) => rubric.criteria.map((criterion) => criterion.id))
  const focus = [...new Set(criteria)].slice(0, 2)
  const id = freeId(
    'evaluador',
    profiles.map((item) => item.profile_id),
  )
  return `---
id: ${id}
name: Nuevo evaluador
role: Rol del evaluador (por ejemplo, Diseño y robustez)
focus:
${(focus.length ? focus : ['evidencia']).map((item) => `  - ${item}`).join('\n')}
style: metódico, práctico y atento a las consecuencias
---
## Tu perspectiva
Describí quién es este evaluador y qué le importa de un proyecto.

## Cómo conversás
Hacé una sola pregunta por turno, concreta y apoyada en lo que dijo la persona.

## Qué ponés a prueba
- Qué parte de la propuesta sostiene el objetivo central.
- Qué evidencia respalda lo que se afirma.

## Reglas de evidencia
No inventes datos. Citá solo materiales que respalden la pregunta.
`
}

/** Valid starting point for a rubric: id, name and at least one criterion with id/title/description. */
export function rubricTemplate(rubrics: RubricVersion[]): string {
  const id = freeId(
    'rubrica',
    rubrics.map((item) => item.rubric_id),
  )
  return `---
id: ${id}
name: Nueva rúbrica
criteria:
  - id: problema
    title: Comprensión del problema
    description: Relaciona la solución con una necesidad concreta de las personas usuarias.
  - id: evidencia
    title: Evidencia del avance
    description: Distingue lo probado de lo propuesto, con fuentes y resultados comprobables.
---
## Cómo devolver
Evaluar los argumentos con referencias a los materiales y a las respuestas. No asignar una nota numérica; si un criterio no se trató, marcarlo como no evaluado.
`
}
