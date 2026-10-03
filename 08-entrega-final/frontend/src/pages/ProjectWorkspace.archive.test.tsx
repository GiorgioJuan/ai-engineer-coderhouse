import { afterEach, describe, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, screen } from '@testing-library/react'
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
  revision: 3,
  created_at: '2026-10-01T10:00:00Z',
  updated_at: '2026-10-01T10:00:00Z',
}
const others: Parameters<typeof stubApi>[0] = [
  [/\/api\/health\/ready/, ready],
  [/\/api\/projects\/p1\/documents/, page([])],
  [/\/api\/projects\/p1\/profiles/, page([])],
  [/\/api\/projects\/p1\/rubrics/, page([])],
  [/\/api\/projects\/p1\/sessions/, page([])],
]
const getProject = (archived: boolean, revision = 3) =>
  [/^GET .*\/api\/projects\/p1$/, { body: { ...project, archived, revision } }] as Parameters<
    typeof stubApi
  >[0][number]
const patchBodies = (mock: ReturnType<typeof stubApi>) =>
  mock.mock.calls
    .filter(([, init]) => init?.method === 'PATCH')
    .map(([, init]) => JSON.parse(String(init?.body)))
const view = () => renderAt(<ProjectWorkspace />, { path: '/projects/:id', route: '/projects/p1' })

describe('espacio de trabajo: archivar y restaurar', () => {
  it('pide confirmación antes de archivar y no archiva hasta confirmar', async () => {
    const fetchMock = stubApi([
      [/^PATCH .*\/projects\/p1$/, { body: { ...project, archived: true, revision: 4 } }],
      ...others,
      getProject(false),
    ])
    view()
    const action = await screen.findByRole('button', { name: 'Archivar proyecto' })
    expect(screen.queryByText('Este proyecto está archivado')).not.toBeInTheDocument()
    fireEvent.click(action)
    expect(screen.getByRole('alertdialog')).toHaveTextContent(
      'Vas a ocultar «Mi proyecto» de tu lista. No se borra nada: podés restaurarlo desde Proyectos archivados.',
    )
    expect(screen.getByRole('button', { name: 'Cancelar' })).toHaveFocus()
    fireEvent.click(screen.getByRole('button', { name: 'Cancelar' }))
    expect(patchBodies(fetchMock)).toHaveLength(0)
    fireEvent.click(action)
    fireEvent.click(screen.getByRole('button', { name: 'Archivar' }))
    await screen.findByText('otra ruta')
    expect(patchBodies(fetchMock)).toEqual([{ expected_revision: 3, archived: true }])
  })

  it('si la revisión quedó vieja (409) vuelve a leer el proyecto y reintenta una vez', async () => {
    let patches = 0
    let reads = 0
    const fetchMock = stubApi([
      [
        /^PATCH .*\/projects\/p1$/,
        () =>
          ++patches === 1
            ? { status: 409, body: { code: 'conflict', message: 'stale revision' } }
            : { body: { ...project, archived: true, revision: 10 } },
      ],
      ...others,
      // First read: the page load (revision 3). Later reads see the newer revision.
      [
        /^GET .*\/api\/projects\/p1$/,
        () => ({ body: { ...project, archived: false, revision: ++reads === 1 ? 3 : 9 } }),
      ],
    ])
    view()
    fireEvent.click(await screen.findByRole('button', { name: 'Archivar proyecto' }))
    fireEvent.click(screen.getByRole('button', { name: 'Archivar' }))
    await screen.findByText('otra ruta')
    expect(patchBodies(fetchMock)).toEqual([
      { expected_revision: 3, archived: true },
      { expected_revision: 9, archived: true },
    ])
  })

  it('un proyecto archivado abierto por URL muestra un aviso con "Restaurar"', async () => {
    const fetchMock = stubApi([
      [/^PATCH .*\/projects\/p1$/, { body: { ...project, archived: false, revision: 4 } }],
      ...others,
      getProject(true),
    ])
    view()
    expect(await screen.findByText('Este proyecto está archivado')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Archivar proyecto' })).not.toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: /Restaurar/ }))
    expect(await screen.findByText(/Restauraste este proyecto/)).toBeInTheDocument()
    expect(screen.queryByText('Este proyecto está archivado')).not.toBeInTheDocument()
    expect(patchBodies(fetchMock)).toEqual([{ expected_revision: 3, archived: false }])
    expect(await screen.findByRole('button', { name: 'Archivar proyecto' })).toBeInTheDocument()
  })
})
