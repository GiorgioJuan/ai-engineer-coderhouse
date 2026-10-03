import { afterEach, describe, expect, it, vi } from 'vitest'
import { cleanup, screen, within } from '@testing-library/react'
import { page, ready, renderAt, stubApi } from '../test/utils'
import { SessionRoom } from './SessionRoom'

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
})

const stamp = '2026-10-03T15:00:00Z'
const completed = {
  id: 's1',
  project_id: 'p1',
  objective: 'Validar la arquitectura',
  status: 'COMPLETED',
  revision: 6,
  question_count: 3,
  max_questions: 3,
  pending_question: null,
  transcript: [
    {
      id: 't0',
      kind: 'presentation',
      author_id: 'user',
      text: 'Presento.',
      citations: [],
      created_at: stamp,
    },
    {
      id: 's1:q1',
      kind: 'question',
      author_id: 'arquitectura',
      text: '¿Cómo?',
      citations: [],
      created_at: stamp,
    },
    {
      id: 's1:q1:answer',
      kind: 'answer',
      author_id: 'user',
      text: 'Así.',
      citations: [],
      created_at: stamp,
    },
  ],
  active_job_id: null,
  report_id: 's1',
  snapshot: {
    profile_versions: [{ id: 'arquitectura', version: 1 }],
    rubric_version: { id: 'principal', version: 1 },
    document_versions: [],
    previous_session_id: null,
  },
  created_at: stamp,
  updated_at: stamp,
}

describe('sala de revisión: sesión terminada', () => {
  it('ofrece "Ver informe" arriba, en el panel lateral y al final, con un mensaje de cierre', async () => {
    stubApi([
      [/\/api\/health\/ready/, ready],
      [/\/api\/sessions\/s1$/, { body: completed }],
      [/\/api\/projects\/p1\/profiles/, page([])],
      [/\/api\/projects\/p1\/rubrics/, page([])],
      [/\/api\/projects\/p1\/documents/, page([])],
      [
        /\/api\/projects\/p1$/,
        { body: { id: 'p1', title: 'Proyecto Demo', context: 'c', objective: 'o' } },
      ],
    ])
    renderAt(<SessionRoom />, { path: '/sessions/:id', route: '/sessions/s1' })
    await screen.findAllByRole('link', { name: /Ver informe/ })
    const header = document.querySelector('.room-header') as HTMLElement
    expect(within(header).getByRole('link', { name: /Ver informe/ })).toHaveAttribute(
      'href',
      '/sessions/s1/report',
    )
    const links = screen.getAllByRole('link', { name: /Ver informe/ })
    expect(links.length).toBe(3)
    links.forEach((link) => expect(link).toHaveAttribute('href', '/sessions/s1/report'))
    expect(
      screen.getByText('La sesión terminó. El informe resume cada criterio con sus citas.'),
    ).toBeInTheDocument()
    expect(screen.queryByText(/Cuando llegue la siguiente pregunta/)).not.toBeInTheDocument()
    expect(screen.queryByText('Leer informe')).not.toBeInTheDocument()
  })

  it('en una sesión en curso no muestra "Ver informe"', async () => {
    stubApi([
      [/\/api\/health\/ready/, ready],
      [/\/api\/sessions\/s1$/, { body: { ...completed, status: 'RUNNING', active_job_id: 'j' } }],
      [
        /\/api\/jobs\/j/,
        { body: { id: 'j', kind: 'ANSWER', status: 'RUNNING', attempt: 1, error: null } },
      ],
      [/\/api\/projects\/p1\/profiles/, page([])],
      [/\/api\/projects\/p1\/rubrics/, page([])],
      [/\/api\/projects\/p1\/documents/, page([])],
      [
        /\/api\/projects\/p1$/,
        { body: { id: 'p1', title: 'Proyecto Demo', context: 'c', objective: 'o' } },
      ],
    ])
    renderAt(<SessionRoom />, { path: '/sessions/:id', route: '/sessions/s1' })
    await screen.findByText('Preparando la próxima pregunta…')
    expect(screen.queryByRole('link', { name: /Ver informe/ })).not.toBeInTheDocument()
  })
})
