import { afterEach, describe, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, screen, waitFor } from '@testing-library/react'
import { page, ready, renderAt, stubApi } from '../test/utils'
import { ProjectWorkspace } from './ProjectWorkspace'

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
})

const project = {
  id: 'p1',
  title: 'Mi proyecto',
  context: 'c',
  objective: 'Validar la propuesta',
  revision: 0,
  created_at: '2026-10-01T10:00:00Z',
  updated_at: '2026-10-01T10:00:00Z',
}
const view = () => renderAt(<ProjectWorkspace />, { path: '/projects/:id', route: '/projects/p1' })

describe('espacio de trabajo: estados de carga', () => {
  it('mientras carga el proyecto no muestra vacíos, contadores ni acciones', async () => {
    stubApi([
      [/\/api\/health\/ready/, ready],
      [/\/api\/projects\/p1/, 'pending'],
    ])
    view()
    expect(await screen.findByText('Cargando proyecto…')).toBeInTheDocument()
    expect(screen.queryByText(/Todavía no cargaste materiales/)).not.toBeInTheDocument()
    expect(screen.queryByText(/Sin sesiones todavía/)).not.toBeInTheDocument()
    expect(screen.queryByText('00')).not.toBeInTheDocument()
    expect(screen.queryByRole('tab')).not.toBeInTheDocument()
    expect(screen.queryByRole('link', { name: /preparar sesión/i })).not.toBeInTheDocument()
  })

  it('con el proyecto cargado pero los materiales pendientes no muestra la mesa vacía ni "00"', async () => {
    stubApi([
      [/\/api\/health\/ready/, ready],
      [/\/api\/projects\/p1\/documents/, 'pending'],
      [/\/api\/projects\/p1\/profiles/, 'pending'],
      [/\/api\/projects\/p1\/rubrics/, 'pending'],
      [/\/api\/projects\/p1\/sessions/, 'pending'],
      [/\/api\/projects\/p1$/, { body: project }],
    ])
    view()
    expect(
      await screen.findByRole('heading', { level: 1, name: 'Mi proyecto' }),
    ).toBeInTheDocument()
    expect(screen.getByText('Cargando materiales…')).toBeInTheDocument()
    expect(screen.queryByText(/Todavía no cargaste materiales/)).not.toBeInTheDocument()
    expect(screen.queryByText('Probá con un caso ficticio')).not.toBeInTheDocument()
    expect(screen.queryByText('00')).not.toBeInTheDocument()
    expect(screen.getAllByText('—').length).toBeGreaterThanOrEqual(3)
  })

  it('cuando sí no hay materiales, recién ahí muestra el estado vacío y el ejemplo de demostración', async () => {
    stubApi([
      [/\/api\/health\/ready/, ready],
      [/\/api\/projects\/p1\/documents/, page([])],
      [/\/api\/projects\/p1\/profiles/, page([])],
      [/\/api\/projects\/p1\/rubrics/, page([])],
      [/\/api\/projects\/p1\/sessions/, page([])],
      [/\/api\/projects\/p1$/, { body: project }],
    ])
    view()
    expect(await screen.findByText('Todavía no cargaste materiales')).toBeInTheDocument()
    expect(await screen.findByText('Probá con un caso ficticio')).toBeInTheDocument()
  })

  it('un proyecto inexistente muestra un mensaje claro y un enlace para volver', async () => {
    stubApi([
      [/\/api\/health\/ready/, ready],
      [
        /\/api\/projects\/p1/,
        { status: 404, body: { code: 'http_404', message: 'project not found' } },
      ],
    ])
    view()
    expect(
      await screen.findByRole('heading', { name: 'No encontramos este proyecto' }),
    ).toBeInTheDocument()
    expect(screen.queryByText('Cargando proyecto…')).not.toBeInTheDocument()
    expect(screen.queryByText('project not found')).not.toBeInTheDocument()
    expect(screen.queryByRole('tab')).not.toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Volver a mis proyectos' })).toHaveAttribute(
      'href',
      '/',
    )
  })

  it('las pestañas son accesibles: roles, selección y flechas del teclado', async () => {
    stubApi([
      [/\/api\/health\/ready/, ready],
      [/\/api\/projects\/p1\/documents/, page([])],
      [/\/api\/projects\/p1\/profiles/, page([])],
      [/\/api\/projects\/p1\/rubrics/, page([])],
      [/\/api\/projects\/p1\/sessions/, page([])],
      [/\/api\/projects\/p1$/, { body: project }],
    ])
    view()
    const tabs = await screen.findAllByRole('tab')
    expect(screen.getByRole('tablist', { name: 'Secciones del proyecto' })).toBeInTheDocument()
    expect(tabs[0]).toHaveAttribute('aria-selected', 'true')
    expect(tabs[1]).toHaveAttribute('tabindex', '-1')
    tabs[0].focus()
    fireEvent.keyDown(tabs[0], { key: 'ArrowRight' })
    await waitFor(() => expect(tabs[1]).toHaveAttribute('aria-selected', 'true'))
    expect(tabs[1]).toHaveFocus()
    expect(screen.getByRole('tabpanel')).toHaveAttribute('aria-labelledby', tabs[1].id)
  })
})
