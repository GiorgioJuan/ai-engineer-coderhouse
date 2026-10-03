import { afterEach, describe, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, screen } from '@testing-library/react'
import { page, renderAt, stubApi } from '../test/utils'
import { Projects } from './Projects'

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
})

const stamp = (day: number) => `2026-10-0${day}T10:00:00Z`
const project = (id: string, title: string, day: number, extra = {}) => ({
  id,
  title,
  context: 'c',
  objective: `Objetivo de ${title}`,
  revision: day,
  archived: false,
  created_at: stamp(1),
  updated_at: stamp(day),
  ...extra,
})
const home = (route: Parameters<typeof renderAt>[1]['route'] = '/') =>
  renderAt(<Projects />, { path: '/', route })
const patchBodies = (mock: ReturnType<typeof stubApi>) =>
  mock.mock.calls
    .filter(([, init]) => init?.method === 'PATCH')
    .map(([, init]) => JSON.parse(String(init?.body)))

describe('inicio: orden, pasos y archivados', () => {
  it('ordena los proyectos por actualización, el más reciente primero', async () => {
    stubApi([
      [/archived=true/, page([])],
      [
        /\/api\/projects\?/,
        page([project('a', 'Viejo', 1), project('c', 'Nuevo', 3), project('b', 'Medio', 2)]),
      ],
    ])
    home()
    await screen.findByText('Nuevo')
    const titles = screen.getAllByRole('heading', { level: 3 }).map((h) => h.textContent)
    expect(titles).toEqual(['Nuevo', 'Medio', 'Viejo'])
  })

  it('muestra los tres pasos y una única acción principal "Nuevo proyecto"', async () => {
    stubApi([[/\/api\/projects\?/, page([])]])
    home()
    const steps = await screen.findByRole('list', { name: /Cómo funciona, en tres pasos/ })
    expect(steps).toHaveTextContent('Cargá tus materiales')
    expect(steps).toHaveTextContent('Elegí evaluadores y rúbrica')
    expect(steps).toHaveTextContent('Respondé al panel y leé el informe')
    expect(screen.getAllByRole('button', { name: 'Nuevo proyecto' })).toHaveLength(1)
    expect(screen.queryByText('01 / 03')).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Crear proyecto' })).not.toBeInTheDocument()
  })

  it('no muestra la sección de archivados si no hay ninguno', async () => {
    stubApi([[/\/api\/projects\?/, page([])]])
    home()
    await screen.findByText('Todavía no hay proyectos')
    expect(screen.queryByRole('button', { name: /Proyectos archivados/ })).not.toBeInTheDocument()
  })

  it('lista los archivados plegados y "Restaurar" los devuelve con la revisión vigente', async () => {
    const fetchMock = stubApi([
      [/archived=true/, page([project('z', 'Guardado', 2, { archived: true, revision: 7 })])],
      [/^PATCH .*\/projects\/z$/, { body: project('z', 'Guardado', 4, { revision: 8 }) }],
      [/\/api\/projects\?/, page([project('a', 'Activo', 1)])],
    ])
    home()
    const toggle = await screen.findByRole('button', { name: /Proyectos archivados \(1\)/ })
    expect(toggle).toHaveAttribute('aria-expanded', 'false')
    expect(screen.queryByRole('button', { name: /Restaurar/ })).not.toBeInTheDocument()
    fireEvent.click(toggle)
    expect(toggle).toHaveAttribute('aria-expanded', 'true')
    fireEvent.click(screen.getByRole('button', { name: 'Restaurar «Guardado»' }))
    expect(await screen.findByText(/Restauraste/)).toHaveTextContent('«Guardado»')
    expect(patchBodies(fetchMock)).toEqual([{ expected_revision: 7, archived: false }])
  })

  it('después de archivar ofrece un aviso con "Deshacer" que restaura el proyecto', async () => {
    const fetchMock = stubApi([
      [/archived=true/, page([])],
      [/^PATCH .*\/projects\/p9$/, { body: project('p9', 'Mi proyecto', 4, { revision: 6 }) }],
      [/\/api\/projects\?/, page([])],
    ])
    home({
      pathname: '/',
      state: { archived: { id: 'p9', title: 'Mi proyecto', revision: 5 } },
    })
    const notice = await screen.findByText(/Archivaste/)
    expect(notice).toHaveTextContent('«Mi proyecto»')
    fireEvent.click(screen.getByRole('button', { name: /Deshacer/ }))
    expect(await screen.findByText(/Restauraste/)).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /Deshacer/ })).not.toBeInTheDocument()
    expect(patchBodies(fetchMock)).toEqual([{ expected_revision: 5, archived: false }])
    fireEvent.click(screen.getByRole('button', { name: 'Cerrar aviso' }))
    expect(screen.queryByText(/Restauraste/)).not.toBeInTheDocument()
  })
})
