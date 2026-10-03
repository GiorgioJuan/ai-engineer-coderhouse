import { ApiError } from './client'

/**
 * Central place that turns backend / network failures into plain Spanish.
 *
 * The backend answers `{ code, message }` with English, technical messages
 * (`project not found`, `invalid fields: title`, …). People should never read those:
 * they get `message` (what happened) + `hint` (what to do next); the raw text only
 * survives in `technical`, which the UI tucks inside a collapsed "Detalle técnico".
 */
export type ErrorKind = 'network' | 'not_found' | 'conflict' | 'invalid' | 'server' | 'unknown'

export type ErrorInfo = {
  kind: ErrorKind
  /** What happened, in plain Spanish. */
  message: string
  /** Suggested next step. */
  hint?: string
  /** Raw detail for support / developers (never shown by default). */
  technical?: string
  /** Whether trying the very same thing again can reasonably work. */
  retryable: boolean
}

type Text = { message: string; hint?: string }

const FIELD_LABELS: Record<string, string> = {
  title: 'nombre o título',
  context: 'contexto',
  objective: 'objetivo',
  text: 'contenido',
  kind: 'tipo de material',
  presentation: 'presentación',
  markdown: 'contenido en Markdown',
  profile_versions: 'evaluadores',
  rubric_version: 'rúbrica',
  document_versions: 'materiales',
  max_questions: 'cantidad de preguntas',
  previous_session_id: 'sesión anterior',
  question_id: 'pregunta',
  expected_revision: 'estado de la sesión',
  expected_attempt: 'intento',
}

/** Known backend messages → Spanish. First match wins. */
const MESSAGE_RULES: Array<[RegExp, (match: RegExpMatchArray) => Text]> = [
  // 404 -----------------------------------------------------------------------------
  [
    /^project not found/i,
    () => ({
      message: 'No encontramos este proyecto.',
      hint: 'Puede que el enlace sea incorrecto o que ya no exista. Volvé a tus proyectos.',
    }),
  ],
  [
    /^session not found/i,
    () => ({
      message: 'No encontramos esta sesión.',
      hint: 'Puede que el enlace sea incorrecto. Volvé a tus proyectos para encontrarla.',
    }),
  ],
  [
    /^job not found|^command not found/i,
    () => ({
      message: 'No encontramos la tarea que estaba en curso.',
      hint: 'Volvé al proyecto y empezá de nuevo desde ahí.',
    }),
  ],
  [
    /^document( version)? not found/i,
    () => ({
      message: 'No encontramos ese material.',
      hint: 'Actualizá la página y elegí otro de la lista.',
    }),
  ],
  [
    /^rubric version not found/i,
    () => ({
      message: 'No encontramos la rúbrica elegida.',
      hint: 'Actualizá la página y elegí otra rúbrica.',
    }),
  ],
  [
    /^profile version not found/i,
    () => ({
      message: 'No encontramos uno de los evaluadores elegidos.',
      hint: 'Actualizá la página y volvé a elegirlos.',
    }),
  ],
  [
    /^demo seed is unavailable|^demo fixtures are missing/i,
    () => ({
      message: 'El ejemplo de demostración no está disponible en este momento.',
      hint: 'Cargá tus propios materiales con “Agregar material”.',
    }),
  ],
  // 409 -----------------------------------------------------------------------------
  [
    /^session state or question changed/i,
    () => ({
      message: 'La sesión cambió mientras la mirabas.',
      hint: 'Actualizamos la pantalla; revisá lo que ves y volvé a intentar.',
    }),
  ],
  [
    /^stale revision/i,
    () => ({
      message: 'Esto cambió mientras lo mirabas (otra pestaña o persona lo modificó).',
      hint: 'Actualizá la página y volvé a intentar.',
    }),
  ],
  [
    /^report is not ready/i,
    () => ({
      message: 'El informe todavía no está listo.',
      hint: 'Probá de nuevo en unos segundos.',
    }),
  ],
  [
    /^document version is not indexed/i,
    () => ({
      message: 'Alguno de los materiales elegidos todavía se está preparando.',
      hint: 'Esperá a que figure como “Listo” y volvé a intentar.',
    }),
  ],
  [
    /^previous session must be completed/i,
    () => ({
      message: 'La sesión elegida para comparar todavía no terminó.',
      hint: 'Elegí una sesión terminada o dejá “Sin comparación”.',
    }),
  ],
  [
    /^job cannot be retried/i,
    () => ({
      message: 'Esta tarea ya no se puede reintentar.',
      hint: 'Volvé al proyecto y empezá de nuevo desde ahí.',
    }),
  ],
  [
    /^legacy catalogue profile cannot start/i,
    () => ({
      message: 'Uno de los evaluadores elegidos pertenece a una versión antigua.',
      hint: 'Elegí otro evaluador o creá uno nuevo.',
    }),
  ],
  [
    /^Idempotency-Key reused/i,
    () => ({
      message: 'Esta acción ya se había enviado con otros datos.',
      hint: 'Recargá la página y volvé a intentarlo.',
    }),
  ],
  [
    /^concurrent |^resource state changed/i,
    () => ({
      message: 'Dos acciones se cruzaron al mismo tiempo.',
      hint: 'Esperá unos segundos y reintentá.',
    }),
  ],
  // 413 / 422 -----------------------------------------------------------------------
  [
    /^document exceeds (\d+) ?KB/i,
    (match) => ({
      message: `Este material supera los ${match[1]} KB.`,
      hint: 'Dividilo en partes más chicas y subí cada una por separado.',
    }),
  ],
  [
    /^project source limit reached/i,
    () => ({
      message: 'Los materiales del proyecto llegaron al límite de texto (1 MB en total).',
      hint: 'Reducí o reemplazá alguno de los materiales actuales.',
    }),
  ],
  [
    /^document limit reached/i,
    () => ({
      message: 'Este proyecto ya tiene el máximo de 30 materiales.',
      hint: 'Subí una versión nueva de uno existente en lugar de agregar otro.',
    }),
  ],
  [
    /^duplicate profile/i,
    () => ({
      message: 'Elegiste el mismo evaluador más de una vez.',
      hint: 'Dejá cada evaluador una sola vez.',
    }),
  ],
  [
    /^duplicate document version/i,
    () => ({
      message: 'Elegiste el mismo material más de una vez.',
      hint: 'Dejá cada material una sola vez.',
    }),
  ],
  [
    /^profile (\S+) has no focus in rubric/i,
    (match) => ({
      message: `El evaluador “${match[1]}” no tiene criterios en común con la rúbrica elegida.`,
      hint: 'Elegí otra rúbrica o editá el evaluador para que mire alguno de sus criterios.',
    }),
  ],
  [
    /^invalid cursor/i,
    () => ({
      message: 'No pudimos cargar la lista completa.',
      hint: 'Actualizá la página y reintentá.',
    }),
  ],
  [
    /^invalid fields?: ?(.*)$/i,
    (match) => {
      const fields = match[1]
        .split(',')
        .map((raw) => raw.trim().split('.').pop() || '')
        .filter(Boolean)
        .map((name) => FIELD_LABELS[name])
        .filter((label): label is string => !!label)
      const unique = [...new Set(fields)]
      return {
        message: unique.length
          ? `Revisá estos campos: ${unique.join(', ')}.`
          : 'Hay datos que no se pudieron procesar.',
        hint: 'Corregilos y volvé a intentar.',
      }
    },
  ],
  // Markdown (perfiles y rúbricas) -------------------------------------------------
  [
    /^YAML frontmatter is required/i,
    () => ({
      message: 'Falta el bloque inicial entre líneas “---” (frontmatter).',
      hint: 'Usá “Insertar plantilla” para ver el formato esperado.',
    }),
  ],
  [
    /^closing frontmatter delimiter is missing/i,
    () => ({
      message: 'Falta la línea “---” que cierra el bloque inicial.',
      hint: 'Agregala justo antes del texto en Markdown.',
    }),
  ],
  [
    /^Markdown body is required/i,
    () => ({
      message: 'Falta el texto en Markdown debajo del bloque inicial.',
      hint: 'Escribí al menos unas líneas debajo de la segunda línea “---”.',
    }),
  ],
  [
    /^invalid YAML/i,
    () => ({
      message: 'El bloque inicial tiene un error de formato (YAML).',
      hint: 'Revisá las sangrías, los dos puntos y los guiones de las listas.',
    }),
  ],
  [
    /^frontmatter must be an object/i,
    () => ({
      message: 'El bloque inicial debe ser una lista de campos “clave: valor”.',
      hint: 'Usá “Insertar plantilla” para ver el formato esperado.',
    }),
  ],
  [
    /^frontmatter keys must be (.*)$/i,
    (match) => ({
      message: `El bloque inicial debe tener exactamente estos campos: ${match[1].replace(/[[\]']/g, '')}.`,
      hint: 'No agregues ni quites campos.',
    }),
  ],
  [
    /^id must be a slug/i,
    () => ({
      message: 'El campo id solo admite minúsculas, números, guiones y guiones bajos.',
      hint: 'Tiene que empezar con una letra y ser único. Ejemplo: mi-evaluador.',
    }),
  ],
  [
    /^(name|role|style) is required/i,
    (match) => ({
      message: `Falta completar el campo “${match[1]}” del bloque inicial.`,
    }),
  ],
  [
    /^focus must be/i,
    () => ({
      message: 'El campo focus tiene que ser una lista con al menos un criterio de la rúbrica.',
      hint: 'Cada criterio va en una línea que empieza con un guion.',
    }),
  ],
  [
    /^criteria must be|^duplicate criterion id/i,
    () => ({
      message: 'La lista de criterios está vacía o tiene ids repetidos.',
      hint: 'Cada criterio necesita un id único, un título y una descripción.',
    }),
  ],
  [
    /^(profile|rubric) exceeds (\d+) bytes/i,
    (match) => ({
      message: `Este ${match[1] === 'profile' ? 'evaluador' : 'archivo de rúbrica'} supera el tamaño máximo (${Math.round(Number(match[2]) / 1024)} KB).`,
      hint: 'Acortá el texto.',
    }),
  ],
  [
    /^(profile|rubric)_id must match frontmatter id/i,
    () => ({
      message: 'El id del archivo no coincide con el de la versión que estás editando.',
      hint: 'Dejá el campo id como estaba o creá uno nuevo.',
    }),
  ],
  [
    /legacy catalogue profile is retired/i,
    () => ({
      message: 'Ese id pertenece a un evaluador retirado.',
      hint: 'Elegí otro id para el evaluador.',
    }),
  ],
]

const NETWORK: Text = {
  message: 'No pudimos conectar con el servidor.',
  hint: 'Revisá que PanelLab esté corriendo y reintentá.',
}

function byStatus(status: number): { kind: ErrorKind; text: Text; retryable: boolean } {
  if (status === 0) return { kind: 'network', text: NETWORK, retryable: true }
  if (status === 404)
    return {
      kind: 'not_found',
      text: {
        message: 'No encontramos lo que buscabas.',
        hint: 'Volvé a tus proyectos e intentá de nuevo.',
      },
      retryable: false,
    }
  if (status === 409)
    return {
      kind: 'conflict',
      text: {
        message: 'Otra acción cambió esto mientras tanto.',
        hint: 'Actualizá la página y volvé a intentar.',
      },
      retryable: true,
    }
  if (status === 413)
    return {
      kind: 'invalid',
      text: {
        message: 'El contenido es demasiado grande.',
        hint: 'Reducilo o dividilo en partes más chicas.',
      },
      retryable: false,
    }
  if (status === 415)
    return {
      kind: 'invalid',
      text: {
        message: 'Ese tipo de archivo no está admitido.',
        hint: 'Usá un PDF, un .md o un .txt.',
      },
      retryable: false,
    }
  if (status === 422 || status === 400)
    return {
      kind: 'invalid',
      text: {
        message: 'Hay datos que no se pudieron procesar.',
        hint: 'Revisá lo que cargaste y volvé a intentar.',
      },
      retryable: false,
    }
  if (status === 429)
    return {
      kind: 'server',
      text: {
        message: 'Hay demasiados pedidos seguidos.',
        hint: 'Esperá unos segundos y reintentá.',
      },
      retryable: true,
    }
  if (status === 502 || status === 503 || status === 504)
    return {
      kind: 'server',
      text: {
        message: 'El servidor no está disponible por ahora.',
        hint: 'Esperá unos segundos y reintentá. Tu trabajo guardado no se pierde.',
      },
      retryable: true,
    }
  if (status >= 500)
    return {
      kind: 'server',
      text: {
        message: 'Algo falló de nuestro lado.',
        hint: 'Reintentá en unos segundos. Lo que ya guardaste sigue a salvo.',
      },
      retryable: true,
    }
  return {
    kind: 'unknown',
    text: { message: 'Ocurrió un error inesperado.', hint: 'Reintentá en unos segundos.' },
    retryable: true,
  }
}

function technicalOf(error: ApiError): string {
  const parts = [
    error.request,
    error.status ? `HTTP ${error.status}` : 'sin respuesta del servidor',
    error.code,
    error.message,
  ].filter(Boolean)
  return parts.join(' · ')
}

export function describeError(error: unknown): ErrorInfo {
  if (typeof error === 'string') return { kind: 'unknown', message: error, retryable: false }
  if (error instanceof ApiError) {
    const fallback = byStatus(error.status)
    const technical = technicalOf(error)
    if (error.userMessage)
      return { kind: fallback.kind, message: error.userMessage, technical, retryable: false }
    if (error.status === 0) return { kind: 'network', ...NETWORK, technical, retryable: true }
    if (error.code === 'redis_unavailable')
      return {
        kind: 'server',
        message: 'El almacenamiento de PanelLab no está disponible por ahora.',
        hint: 'Esperá unos segundos y reintentá. Lo que ya guardaste sigue a salvo.',
        technical,
        retryable: true,
      }
    if (error.code === 'pagination_loop')
      return {
        kind: 'server',
        message: 'No pudimos terminar de cargar la lista.',
        hint: 'Actualizá la página y reintentá.',
        technical,
        retryable: true,
      }
    for (const [pattern, build] of MESSAGE_RULES) {
      const match = error.message.match(pattern)
      if (match) {
        const kind: ErrorKind =
          error.status === 404
            ? 'not_found'
            : error.status === 409
              ? 'conflict'
              : error.status >= 500
                ? 'server'
                : 'invalid'
        return { kind, ...build(match), technical, retryable: fallback.retryable }
      }
    }
    return { kind: fallback.kind, ...fallback.text, technical, retryable: fallback.retryable }
  }
  if (error instanceof Error) {
    return {
      kind: 'unknown',
      message: 'Ocurrió un error inesperado.',
      hint: 'Reintentá en unos segundos.',
      technical: error.message,
      retryable: true,
    }
  }
  return {
    kind: 'unknown',
    message: 'Ocurrió un error inesperado.',
    hint: 'Reintentá en unos segundos.',
    retryable: true,
  }
}

/** One-sentence version (message + hint) for places that only have a string slot. */
export function friendlyMessage(error: unknown): string {
  const info = describeError(error)
  return info.hint ? `${info.message} ${info.hint}` : info.message
}

export function isNotFound(error: unknown): boolean {
  return error instanceof ApiError && error.status === 404
}

export type JobFailure = { code?: string; message?: string; retryable?: boolean }

/** Jobs fail with `code` = Python exception name and `message` = raw exception text. */
export function describeJobError(failure?: JobFailure | null): ErrorInfo {
  const raw = `${failure?.code || ''} ${failure?.message || ''}`
  const technical = failure ? [failure.code, failure.message].filter(Boolean).join(': ') : undefined
  const retryable = failure?.retryable ?? true
  if (/time.?out|timed out|deadline/i.test(raw))
    return {
      kind: 'server',
      message: 'El panel tardó demasiado en responder.',
      hint: 'Tu progreso está guardado. Reintentá en unos segundos.',
      technical,
      retryable,
    }
  if (/rate.?limit|quota|429|overload|saturad/i.test(raw))
    return {
      kind: 'server',
      message: 'El servicio de IA está saturado o llegó a su límite de uso.',
      hint: 'Esperá un minuto y reintentá. Tu progreso está guardado.',
      technical,
      retryable,
    }
  if (/api.?key|unauthori[sz]ed|forbidden|authentication|401|403/i.test(raw))
    return {
      kind: 'server',
      message: 'No se pudo acceder al servicio de IA.',
      hint: 'Avisá a quien administra PanelLab para revisar la configuración. Tu progreso está guardado.',
      technical,
      retryable,
    }
  if (/connect|network|unreachable|dns|refused/i.test(raw))
    return {
      kind: 'network',
      message: 'No se pudo conectar con el servicio de IA.',
      hint: 'Reintentá en unos segundos. Tu progreso está guardado.',
      technical,
      retryable,
    }
  return {
    kind: 'server',
    message: 'El panel no pudo preparar la respuesta.',
    hint: 'Tu progreso está guardado. Reintentá; si vuelve a fallar, volvé al proyecto.',
    technical,
    retryable,
  }
}
