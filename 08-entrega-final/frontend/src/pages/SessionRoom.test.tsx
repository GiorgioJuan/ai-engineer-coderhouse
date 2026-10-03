import { afterEach, describe, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, screen, waitFor } from '@testing-library/react'
import { page, ready, renderAt, stubApi } from '../test/utils'
import { SessionRoom } from './SessionRoom'

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
  sessionStorage.clear()
})

const stamp = '2026-10-03T15:00:00Z'
const question = {
  id: 's1:q2',
  reviewer_id: 'arquitectura',
  criterion_id: 'evidencia',
  text: '¿Qué evidencia respalda esa decisión?',
  basis: 'document',
  citations: [],
  related_turn_ids: [],
}
const baseSession = {
  id: 's1',
  project_id: 'p1',
  objective: 'Validar la arquitectura',
  status: 'WAITING_RESPONSE',
  revision: 2,
  question_count: 2,
  max_questions: 4,
  pending_question: question,
  transcript: [
    {
      id: 't0',
      kind: 'presentation',
      author_id: 'user',
      text: 'Presento el sistema.',
      citations: [],
      created_at: stamp,
    },
    {
      id: 's1:q1',
      kind: 'question',
      author_id: 'arquitectura',
      text: '¿Cómo se despliega?',
      citations: [],
      created_at: stamp,
    },
    {
      id: 's1:q1:answer',
      kind: 'answer',
      author_id: 'user',
      text: 'Con Docker.',
      citations: [],
      created_at: stamp,
    },
    {
      id: 's1:q2',
      kind: 'question',
      author_id: 'arquitectura',
      text: question.text,
      citations: [],
      created_at: stamp,
    },
  ],
  active_job_id: null,
  report_id: null,
  snapshot: {
    profile_versions: [{ id: 'arquitectura', version: 1 }],
    rubric_version: { id: 'principal', version: 1 },
    document_versions: [],
    previous_session_id: null,
  },
  created_at: stamp,
  updated_at: stamp,
}
const profile = {
  profile_id: 'arquitectura',
  version: 1,
  name: 'Lucía',
  role: 'Diseño y robustez',
  focus: ['evidencia'],
  style: 'metódico',
  markdown: '',
}
const rubric = {
  rubric_id: 'principal',
  version: 1,
  name: 'General',
  criteria: [{ id: 'evidencia', title: 'Evidencia del avance', description: 'd' }],
  markdown: '',
}

function api(session: Record<string, unknown>, extra: Parameters<typeof stubApi>[0] = []) {
  return stubApi([
    ...extra,
    [/\/api\/health\/ready/, ready],
    [/\/api\/sessions\/s1$/, { body: session }],
    [/\/api\/projects\/p1\/profiles/, page([profile])],
    [/\/api\/projects\/p1\/rubrics/, page([rubric])],
    [/\/api\/projects\/p1\/documents/, page([])],
    [
      /\/api\/projects\/p1$/,
      { body: { id: 'p1', title: 'Proyecto Demo', context: 'c', objective: 'o' } },
    ],
  ])
}
const room = () => renderAt(<SessionRoom />, { path: '/sessions/:id', route: '/sessions/s1' })

describe('sala de revisión: terminar la sesión', () => {
  it('pide confirmación, enfoca la opción segura y no termina hasta confirmar', async () => {
    const fetchMock = api(baseSession, [
      [
        /\/api\/sessions\/s1\/finish/,
        {
          status: 202,
          body: { job_id: 'j1', session_id: 's1', status: 'QUEUED', status_url: '/api/jobs/j1' },
        },
      ],
    ])
    room()
    const finish = await screen.findByRole('button', { name: /terminar y ver informe/i })
    expect(screen.queryByRole('button', { name: /^finalizar$/i })).not.toBeInTheDocument()
    fireEvent.click(finish)

    const dialog = screen.getByRole('alertdialog')
    expect(dialog).toHaveTextContent('¿Terminar la sesión ahora?')
    expect(dialog).toHaveTextContent(
      'Vas a recibir el informe con 1 de 4 preguntas respondidas. No vas a poder retomarla.',
    )
    expect(screen.getByRole('button', { name: 'Seguir respondiendo' })).toHaveFocus()
    const finishCalls = () =>
      fetchMock.mock.calls.filter(([url]) => String(url).includes('/finish'))
    expect(finishCalls()).toHaveLength(0)

    fireEvent.click(screen.getByRole('button', { name: 'Seguir respondiendo' }))
    expect(screen.queryByRole('alertdialog')).not.toBeInTheDocument()
    expect(finishCalls()).toHaveLength(0)

    fireEvent.click(finish)
    fireEvent.keyDown(document, { key: 'Escape' })
    expect(screen.queryByRole('alertdialog')).not.toBeInTheDocument()
    expect(finishCalls()).toHaveLength(0)

    fireEvent.click(finish)
    fireEvent.click(screen.getByRole('button', { name: 'Terminar sesión' }))
    await waitFor(() => expect(finishCalls()).toHaveLength(1))
    expect(finishCalls()[0][1]).toMatchObject({ method: 'POST' })
  })

  it('avisa que una respuesta escrita pero no enviada no se tendrá en cuenta', async () => {
    api(baseSession)
    room()
    fireEvent.change(await screen.findByLabelText('TU RESPUESTA'), {
      target: { value: 'Un borrador' },
    })
    fireEvent.click(screen.getByRole('button', { name: /terminar y ver informe/i }))
    expect(screen.getByRole('alertdialog')).toHaveTextContent(/no enviaste/)
  })

  it('encabeza la pregunta con el nombre del evaluador y muestra el avance', async () => {
    api(baseSession)
    room()
    expect(await screen.findByText('Pregunta 2 de 4 · podés terminar antes')).toBeInTheDocument()
    const heading = (await screen.findAllByText('Lucía')).find((el) => el.closest('.turn-card'))
    expect(heading).toBeDefined()
    expect(screen.getAllByText(/Evidencia del avance/).length).toBeGreaterThan(0)
    expect(screen.queryByText('evidencia')).not.toBeInTheDocument()
  })
})

describe('sala de revisión: espera y fallas', () => {
  it('cuenta el tiempo y explica qué está pasando en una región de estado', async () => {
    api({ ...baseSession, status: 'RUNNING', active_job_id: 'j2', pending_question: null }, [
      [
        /\/api\/jobs\/j2/,
        { body: { id: 'j2', kind: 'ANSWER', status: 'RUNNING', attempt: 1, error: null } },
      ],
    ])
    room()
    const title = await screen.findByText('Preparando la próxima pregunta…')
    const region = title.closest('[role="status"]')!
    expect(region).toHaveAttribute('aria-live', 'polite')
    expect(region).toHaveTextContent(/\d+ s/)
    expect(region).toHaveTextContent('Suele tardar entre 5 y 40 segundos.')
  })

  it('ante una falla ofrece Reintentar y Volver al proyecto, sin texto crudo del servidor', async () => {
    api({ ...baseSession, status: 'FAILED', active_job_id: 'j3', pending_question: null }, [
      [
        /\/api\/jobs\/j3/,
        {
          body: {
            id: 'j3',
            kind: 'ANSWER',
            status: 'FAILED',
            attempt: 1,
            error: {
              code: 'ValueError',
              message: 'Snapshot source is not indexed',
              retryable: true,
            },
          },
        },
      ],
    ])
    room()
    expect(await screen.findByText('No se pudo continuar la sesión')).toBeInTheDocument()
    expect(await screen.findByText(/El panel no pudo preparar la respuesta/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Reintentar' })).toBeInTheDocument()
    expect(screen.queryByText(/Reintentar trabajo/)).not.toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Volver al proyecto' })).toHaveAttribute(
      'href',
      '/projects/p1',
    )
    const details = screen.getByText('Detalle técnico').closest('details')!
    expect(details).not.toHaveAttribute('open')
  })

  it('muestra "no encontramos esta sesión" con salida cuando la sesión no existe', async () => {
    stubApi([[/\/api\/health\/ready/, ready]])
    room()
    expect(
      await screen.findByRole('heading', { name: 'No encontramos esta sesión' }),
    ).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Volver a mis proyectos' })).toHaveAttribute(
      'href',
      '/',
    )
  })
})

describe('sala de revisión: navegación y foco', () => {
  it('cuando llega una pregunta nueva la acerca a la vista y enfoca la respuesta', async () => {
    const targets: string[] = []
    Element.prototype.scrollIntoView = function (this: Element) {
      targets.push(this.id)
    }
    let polls = 0
    const running = {
      ...baseSession,
      status: 'RUNNING',
      pending_question: null,
      active_job_id: 'j2',
      transcript: baseSession.transcript.slice(0, 3),
    }
    api(running, [
      [
        /\/api\/jobs\/j2/,
        { body: { id: 'j2', kind: 'ANSWER', status: 'RUNNING', attempt: 1, error: null } },
      ],
      [/\/api\/sessions\/s1$/, () => ({ body: ++polls < 2 ? running : baseSession })],
    ])
    room()
    expect(await screen.findByText('Preparando la próxima pregunta…')).toBeInTheDocument()
    await waitFor(() => expect(screen.getByLabelText('TU RESPUESTA')).toHaveFocus(), {
      timeout: 6000,
    })
    expect(targets).toContain('turn-s1:q2')
  }, 10000)

  it('al llegar desde el informe con #turn-… se desplaza hasta esa respuesta y la resalta', async () => {
    const targets: string[] = []
    Element.prototype.scrollIntoView = function (this: Element) {
      targets.push(this.id)
    }
    api(baseSession)
    renderAt(<SessionRoom />, {
      path: '/sessions/:id',
      route: '/sessions/s1#turn-s1:q1:answer',
    })
    await screen.findByText('Con Docker.')
    await waitFor(() => expect(targets).toContain('turn-s1:q1:answer'))
    expect(document.getElementById('turn-s1:q1:answer')).toHaveClass('turn-card--highlight')
    expect(targets).not.toContain('turn-s1:q2')
  })
})
