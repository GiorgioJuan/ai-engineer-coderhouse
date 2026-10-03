import { afterEach, describe, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, screen, within } from '@testing-library/react'
import { page, ready, renderAt, stubApi } from '../test/utils'
import { SessionReport } from './SessionReport'

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
})

const stamp = '2026-10-03T15:00:00Z'
const session = {
  id: 's1',
  project_id: 'p1',
  objective: 'Validar la arquitectura',
  status: 'COMPLETED',
  revision: 5,
  question_count: 3,
  max_questions: 3,
  pending_question: null,
  transcript: [
    {
      id: 's1:q1',
      kind: 'question',
      author_id: 'arquitectura',
      text: 'p',
      citations: [],
      created_at: stamp,
    },
    {
      id: 's1:q1:answer',
      kind: 'answer',
      author_id: 'user',
      text: 'r',
      citations: [],
      created_at: stamp,
    },
  ],
  active_job_id: null,
  report_id: 's1',
  snapshot: {
    profile_versions: [],
    rubric_version: { id: 'principal', version: 1 },
    document_versions: [],
    previous_session_id: null,
  },
  created_at: stamp,
  updated_at: stamp,
}
const citation = {
  document_id: 'd1',
  version: 1,
  chunk_id: 'c1',
  section: 'Contexto',
  excerpt: 'Un centro de actividades',
}
const report = {
  id: 's1',
  session_id: 's1',
  project_id: 'p1',
  criterion_feedback: [
    {
      criterion_id: 'evidencia',
      status: 'supported',
      observation: 'Mostraste pruebas.',
      citations: [citation],
      related_turn_ids: ['s1:q1:answer'],
      next_action: 'Sumar métricas',
    },
    {
      criterion_id: 'otro',
      status: 'algo_nuevo',
      observation: 'Estado que el frontend no conoce.',
      citations: [],
      related_turn_ids: [],
      next_action: null,
    },
  ],
  strengths: [],
  pending_questions: [],
  next_steps: ['Medir'],
  comparison: null,
  created_at: stamp,
}
const documents = page([
  {
    document_id: 'd1',
    project_id: 'p1',
    version: 1,
    title: 'Brief del proyecto',
    kind: 'source',
    text: 't',
    content_hash: 'h',
    index_status: 'READY',
    created_at: stamp,
  },
])
const rubrics = page([
  {
    rubric_id: 'principal',
    version: 1,
    name: 'General',
    criteria: [{ id: 'evidencia', title: 'Evidencia del avance', description: 'd' }],
  },
])
const view = () =>
  renderAt(<SessionReport />, { path: '/sessions/:id/report', route: '/sessions/s1/report' })

describe('informe', () => {
  it('muestra migas de pan, citas con título de documento y enlaces claros', async () => {
    stubApi([
      [/\/api\/health\/ready/, ready],
      [/\/api\/sessions\/s1\/report/, { body: report }],
      [/\/api\/sessions\/s1$/, { body: session }],
      [/\/api\/projects\/p1\/documents/, documents],
      [/\/api\/projects\/p1\/rubrics/, rubrics],
      [
        /\/api\/projects\/p1$/,
        { body: { id: 'p1', title: 'Proyecto Demo', context: 'c', objective: 'o' } },
      ],
    ])
    view()
    const crumbs = await screen.findByRole('navigation', { name: 'Ruta de navegación' })
    expect(within(crumbs).getByRole('link', { name: 'Proyectos' })).toHaveAttribute('href', '/')
    expect(await within(crumbs).findByRole('link', { name: 'Proyecto Demo' })).toHaveAttribute(
      'href',
      '/projects/p1',
    )
    expect(within(crumbs).getByText('Informe')).toHaveAttribute('aria-current', 'page')
    expect(
      await screen.findByRole('button', { name: /Brief del proyecto · Contexto/ }),
    ).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /Fuente 1/ })).not.toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Ver mi respuesta' })).toHaveAttribute(
      'href',
      '/sessions/s1#turn-s1:q1:answer',
    )
    expect(await screen.findByText('Evidencia del avance')).toBeInTheDocument()
  })

  it('un estado desconocido tiene una etiqueta de respaldo y se puede imprimir', async () => {
    stubApi([
      [/\/api\/health\/ready/, ready],
      [/\/api\/sessions\/s1\/report/, { body: report }],
      [/\/api\/sessions\/s1$/, { body: session }],
      [/\/api\/projects\/p1\/documents/, documents],
      [/\/api\/projects\/p1\/rubrics/, rubrics],
      [
        /\/api\/projects\/p1$/,
        { body: { id: 'p1', title: 'Proyecto Demo', context: 'c', objective: 'o' } },
      ],
    ])
    const print = vi.fn()
    vi.stubGlobal('print', print)
    view()
    expect(await screen.findByText('Sin clasificar')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: /imprimir \/ guardar pdf/i }))
    expect(print).toHaveBeenCalledTimes(1)
  })

  it('mientras carga no dice que la sesión no terminó ni muestra "0 preguntas"', async () => {
    stubApi([
      [/\/api\/health\/ready/, ready],
      [/\/api\/sessions\/s1/, 'pending'],
    ])
    view()
    expect(await screen.findByText('Cargando el informe…')).toBeInTheDocument()
    expect(screen.queryByText(/todavía no terminó/)).not.toBeInTheDocument()
    expect(screen.queryByText(/Sin fecha/)).not.toBeInTheDocument()
    expect(screen.queryByText(/0 PREGUNTAS/)).not.toBeInTheDocument()
  })

  it('un informe inexistente muestra un mensaje claro con enlace para volver', async () => {
    stubApi([
      [/\/api\/health\/ready/, ready],
      [
        /\/api\/sessions\/s1/,
        { status: 404, body: { code: 'http_404', message: 'session not found' } },
      ],
    ])
    view()
    expect(
      await screen.findByRole('heading', { name: 'No encontramos este informe' }),
    ).toBeInTheDocument()
    expect(screen.queryByText('session not found')).not.toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Volver a mis proyectos' })).toHaveAttribute(
      'href',
      '/',
    )
  })
})

describe('informe: lectura por estado', () => {
  it('muestra los contadores por estado y nombra los criterios más débiles', async () => {
    const mixed = {
      ...report,
      criterion_feedback: [
        { ...report.criterion_feedback[0], status: 'supported' },
        {
          ...report.criterion_feedback[0],
          criterion_id: 'evidencia',
          status: 'partial',
          citations: [],
        },
        {
          ...report.criterion_feedback[0],
          criterion_id: 'otro',
          status: 'not_assessed',
          citations: [],
        },
      ],
    }
    stubApi([
      [/\/api\/health\/ready/, ready],
      [/\/api\/sessions\/s1\/report/, { body: mixed }],
      [/\/api\/sessions\/s1$/, { body: session }],
      [/\/api\/projects\/p1\/documents/, documents],
      [/\/api\/projects\/p1\/rubrics/, rubrics],
      [
        /\/api\/projects\/p1$/,
        { body: { id: 'p1', title: 'Proyecto Demo', context: 'c', objective: 'o' } },
      ],
    ])
    view()
    const chips = await screen.findByRole('list', { name: 'Criterios por estado' })
    expect(chips).toHaveTextContent('1 sustentado')
    expect(chips).toHaveTextContent('1 parcial')
    expect(chips).toHaveTextContent('0 sin evidencia')
    expect(chips).toHaveTextContent('1 no evaluado')
    expect(await screen.findByText(/Para la próxima: Evidencia del avance\./)).toBeInTheDocument()
    expect(screen.queryByText(/El informe reúne/)).not.toBeInTheDocument()
  })

  it('muestra un único rótulo de informe (sin la línea duplicada)', async () => {
    stubApi([
      [/\/api\/health\/ready/, ready],
      [/\/api\/sessions\/s1\/report/, { body: report }],
      [/\/api\/sessions\/s1$/, { body: session }],
      [/\/api\/projects\/p1\/documents/, documents],
      [/\/api\/projects\/p1\/rubrics/, rubrics],
      [
        /\/api\/projects\/p1$/,
        { body: { id: 'p1', title: 'Proyecto Demo', context: 'c', objective: 'o' } },
      ],
    ])
    view()
    expect(await screen.findByText('INFORME / Proyecto Demo')).toBeInTheDocument()
    expect(screen.queryByText(/INFORME DE REVISIÓN/)).not.toBeInTheDocument()
  })
})
