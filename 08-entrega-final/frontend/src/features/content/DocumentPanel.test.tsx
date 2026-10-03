import { afterEach, describe, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { DocumentPanel } from './DocumentPanel'

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
})

function editor() {
  render(
    <QueryClientProvider
      client={new QueryClient({ defaultOptions: { mutations: { retry: false } } })}
    >
      <DocumentPanel projectId="project-1" documents={[]} />
    </QueryClientProvider>,
  )
  fireEvent.click(screen.getByRole('button', { name: /agregar material/i }))
}
function upload(name = 'Brief.pdf') {
  fireEvent.change(screen.getByLabelText('Importar archivo'), {
    target: { files: [new File(['%PDF-1.7'], name, { type: 'application/pdf' })] },
  })
}

describe('importación de PDF', () => {
  it('muestra texto y páginas antes de guardar, sin indexar automáticamente', async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({
        title: 'Brief',
        text: '## Página 1\n\nObjetivo del proyecto.',
        page_count: 1,
        warnings: [],
      }),
    })
    vi.stubGlobal('fetch', fetchMock)
    editor()
    upload()
    expect(await screen.findByText(/1 página importada/)).toBeInTheDocument()
    expect(screen.getByLabelText('Título')).toHaveValue('Brief')
    expect(screen.getByLabelText(/Contenido/)).toHaveValue('## Página 1\n\nObjetivo del proyecto.')
    expect(fetchMock).toHaveBeenCalledTimes(1)
    const [url, options] = fetchMock.mock.calls[0] as [string, RequestInit]
    expect(url).toContain('/documents/extract?filename=Brief.pdf')
    expect(new Headers(options.headers).get('Content-Type')).toBe('application/pdf')
    expect(options.body).toBeInstanceOf(File)
    expect(screen.getByRole('button', { name: /guardar material/i })).toBeEnabled()
  })

  it('conserva el contenido si falla la extracción y permite reintentar', async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce({
        ok: false,
        status: 422,
        json: async () => ({ detail: 'El PDF está protegido. Exportá una copia sin contraseña.' }),
      })
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({
          title: 'Brief',
          text: 'Texto recuperado',
          page_count: 2,
          warnings: ['La página 2 no contiene texto.'],
        }),
      })
    vi.stubGlobal('fetch', fetchMock)
    editor()
    fireEvent.change(screen.getByLabelText(/Contenido/), { target: { value: 'Borrador previo' } })
    upload()
    expect(await screen.findByRole('alert')).toHaveTextContent(/sin contraseña/)
    expect(screen.getByLabelText(/Contenido/)).toHaveValue('Borrador previo')
    upload()
    expect(await screen.findByText(/La página 2 no contiene texto/)).toBeInTheDocument()
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
  })

  it('deshabilita guardado mientras extrae y descarta una respuesta tras cancelar', async () => {
    let resolve!: (value: unknown) => void
    vi.stubGlobal(
      'fetch',
      vi.fn().mockImplementation(
        () =>
          new Promise((r) => {
            resolve = r
          }),
      ),
    )
    editor()
    upload()
    expect(screen.getByRole('button', { name: /guardar material/i })).toBeDisabled()
    fireEvent.click(screen.getByRole('button', { name: 'Cancelar' }))
    resolve({
      ok: true,
      json: async () => ({
        title: 'Tardío',
        text: 'No debe reaparecer',
        page_count: 1,
        warnings: [],
      }),
    })
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument())
    fireEvent.click(screen.getByRole('button', { name: /agregar material/i }))
    expect(screen.getByLabelText(/Contenido/)).toHaveValue('')
  })
})

describe('cambios sin guardar y estados', () => {
  it('pregunta antes de descartar el contenido pegado', () => {
    editor()
    fireEvent.change(screen.getByLabelText(/Contenido/), { target: { value: 'Texto pegado' } })
    fireEvent.keyDown(document, { key: 'Escape' })
    expect(screen.getByRole('alertdialog')).toHaveTextContent('Tenés cambios sin guardar')
    expect(screen.getByRole('button', { name: 'Seguir editando' })).toHaveFocus()
    fireEvent.click(screen.getByRole('button', { name: 'Seguir editando' }))
    expect(screen.getByLabelText(/Contenido/)).toHaveValue('Texto pegado')
    fireEvent.click(screen.getByRole('button', { name: 'Cancelar' }))
    fireEvent.click(screen.getByRole('button', { name: 'Descartar cambios' }))
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
  })

  it('explica los materiales que se preparan o fallaron y ofrece subir una nueva versión', () => {
    const doc = (id: string, status: string) => ({
      document_id: id,
      project_id: 'project-1',
      version: 1,
      title: `Doc ${id}`,
      kind: 'progress',
      text: 'texto',
      content_hash: 'h',
      index_status: status,
      created_at: '2026-10-01T10:00:00Z',
    })
    render(
      <QueryClientProvider client={new QueryClient()}>
        <DocumentPanel
          projectId="project-1"
          documents={[doc('a', 'RUNNING'), doc('b', 'FAILED'), doc('c', 'READY')] as never}
        />
      </QueryClientProvider>,
    )
    expect(
      screen.getByText(/Lo estamos leyendo para que el panel pueda citarlo/),
    ).toBeInTheDocument()
    expect(screen.getByText(/No pudimos preparar este material/)).toBeInTheDocument()
    expect(screen.getAllByText('Avance · versión 1', { exact: false }).length).toBe(3)
    expect(screen.queryByText(/progress/)).not.toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: /subir una nueva versión/i }))
    expect(screen.getByRole('dialog', { name: 'Nueva versión' })).toBeInTheDocument()
    expect(screen.getByLabelText('Título')).toHaveValue('Doc b')
  })
})
