import { afterEach, describe, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { SessionSetup } from './SessionSetup'

afterEach(() => {
  cleanup()
  sessionStorage.clear()
})

vi.mock('../api/hooks', () => ({
  useProjectData: () => ({
    project: { data: { id: 'project-1', title: 'Proyecto' } },
    documents: { data: { items: [] } },
    profiles: {
      data: {
        items: Array.from({ length: 6 }, (_, i) => ({
          profile_id: `reviewer-${i}`,
          version: 1,
          name: `Revisor ${i}`,
          role: 'Arquitectura',
        })),
      },
    },
    rubrics: {
      data: {
        items: [
          {
            rubric_id: 'principal',
            version: 1,
            name: 'General',
            criteria: [{ id: 'evidencia', title: 'Evidencia', description: '' }],
          },
        ],
      },
    },
    sessions: { data: { items: [] } },
  }),
}))

describe('preparación de sesión', () => {
  it('selecciona cinco, limita el sexto y reserva cinco preguntas', () => {
    render(
      <QueryClientProvider client={new QueryClient()}>
        <MemoryRouter initialEntries={['/projects/project-1/sessions/new']}>
          <Routes>
            <Route path="/projects/:id/sessions/new" element={<SessionSetup />} />
          </Routes>
        </MemoryRouter>
      </QueryClientProvider>,
    )
    const choices = screen.getAllByRole('checkbox')
    expect(choices.filter((c) => (c as HTMLInputElement).checked)).toHaveLength(5)
    expect(choices[5]).toBeDisabled()
    expect(screen.getByLabelText('Preguntas')).toHaveValue('5')
    expect(screen.getByRole('option', { name: '3 preguntas' })).toBeDisabled()
    fireEvent.click(choices[0])
    expect(choices[5]).toBeEnabled()
    fireEvent.click(choices[5])
    expect(choices.filter((c) => (c as HTMLInputElement).checked)).toHaveLength(5)
    expect(choices[0]).toBeDisabled()
  })
  it('explica que falta una fuente lista y bloquea el inicio', () => {
    render(
      <QueryClientProvider client={new QueryClient()}>
        <MemoryRouter initialEntries={['/projects/project-1/sessions/new']}>
          <Routes>
            <Route path="/projects/:id/sessions/new" element={<SessionSetup />} />
          </Routes>
        </MemoryRouter>
      </QueryClientProvider>,
    )
    expect(screen.getByText(/agregá al menos un documento/i)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /iniciar revisión/i })).toBeDisabled()
  })
  it('recupera el texto y las selecciones después de volver a abrir la preparación', () => {
    const view = () => (
      <QueryClientProvider client={new QueryClient()}>
        <MemoryRouter initialEntries={['/projects/project-1/sessions/new']}>
          <Routes>
            <Route path="/projects/:id/sessions/new" element={<SessionSetup />} />
          </Routes>
        </MemoryRouter>
      </QueryClientProvider>
    )
    const first = render(view())
    fireEvent.change(screen.getByLabelText('Objetivo de esta sesión'), {
      target: { value: 'Validar arquitectura' },
    })
    fireEvent.change(screen.getByLabelText(/Presentación inicial/), {
      target: { value: 'Defiendo esta decisión.' },
    })
    fireEvent.click(screen.getAllByRole('checkbox')[0])
    first.unmount()
    render(view())
    expect(screen.getByLabelText('Objetivo de esta sesión')).toHaveValue('Validar arquitectura')
    expect(screen.getByLabelText(/Presentación inicial/)).toHaveValue('Defiendo esta decisión.')
    expect(screen.getAllByRole('checkbox')[0]).not.toBeChecked()
  })
  it('explica qué falta cuando se deseleccionan todos los evaluadores', () => {
    render(
      <QueryClientProvider client={new QueryClient()}>
        <MemoryRouter initialEntries={['/projects/project-1/sessions/new']}>
          <Routes>
            <Route path="/projects/:id/sessions/new" element={<SessionSetup />} />
          </Routes>
        </MemoryRouter>
      </QueryClientProvider>,
    )
    screen
      .getAllByRole('checkbox')
      .slice(0, 5)
      .forEach((choice) => fireEvent.click(choice))
    expect(screen.getByText('Seleccioná al menos un evaluador.')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /iniciar revisión/i })).toBeDisabled()
  })
  it('no cuenta perfiles que ya no existen en un borrador restaurado', () => {
    sessionStorage.setItem(
      'panellab:session-draft:project-1',
      JSON.stringify({
        objective: 'Objetivo',
        presentation: 'Presentación',
        selectedProfiles: ['eliminado'],
        maxQuestions: 5,
      }),
    )
    render(
      <QueryClientProvider client={new QueryClient()}>
        <MemoryRouter initialEntries={['/projects/project-1/sessions/new']}>
          <Routes>
            <Route path="/projects/:id/sessions/new" element={<SessionSetup />} />
          </Routes>
        </MemoryRouter>
      </QueryClientProvider>,
    )
    expect(screen.getByText('Seleccioná al menos un evaluador.')).toBeInTheDocument()
    expect(screen.getByText('0 evaluadores')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /iniciar revisión/i })).toBeDisabled()
  })
})
