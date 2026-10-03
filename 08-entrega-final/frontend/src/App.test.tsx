import { afterEach, describe, expect, it, vi } from 'vitest'
import { cleanup, render, screen, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter } from 'react-router-dom'
import { App } from './App'
import { ready, stubApi } from './test/utils'

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
})

function app(route: string) {
  return render(
    <QueryClientProvider
      client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}
    >
      <MemoryRouter initialEntries={[route]}>
        <App />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

describe('ayuda y navegación', () => {
  it('la ruta /ayuda explica el flujo, la IA, el modo demostración y los atajos', async () => {
    stubApi([[/\/api\/health\/ready/, ready]])
    app('/ayuda')
    expect(
      await screen.findByRole('heading', { level: 1, name: /^¿Cómo funciona\s+PanelLab\s*\?$/ }),
    ).toBeInTheDocument()
    for (const step of [
      'Cargá tus materiales',
      'Elegí evaluadores y rúbrica',
      'Respondé al panel',
      'Leé el informe',
    ])
      expect(screen.getByRole('heading', { name: step })).toBeInTheDocument()
    expect(screen.getByText(/Un supervisor decide qué evaluador pregunta/)).toBeInTheDocument()
    expect(screen.getByText(/las preguntas citan|citan los fragmentos/i)).toBeInTheDocument()
    expect(screen.getByText(/la sesión se guarda/)).toBeInTheDocument()
    expect(
      screen.getByRole('heading', { name: /Modo demostración e IA en vivo/ }),
    ).toBeInTheDocument()
    expect(screen.getByText('Ctrl / ⌘ + Enter')).toBeInTheDocument()
    expect(document.title).toBe('¿Cómo funciona? · PanelLab')
  })

  it('el encabezado enlaza a la ayuda real y muestra "Modo demostración" con explicación', async () => {
    stubApi([[/\/api\/health\/ready/, ready]])
    app('/ayuda')
    const links = await screen.findAllByRole('link', { name: '¿Cómo funciona?' })
    expect(links.length).toBeGreaterThan(0)
    links.forEach((link) => expect(link).toHaveAttribute('href', '/ayuda'))
    const badge = await screen.findByRole('link', { name: /Modo demostración/ })
    expect(badge).toHaveAttribute(
      'title',
      expect.stringContaining('sin costo ni conexión a un modelo'),
    )
    expect(screen.queryByText(/API REAL/i)).not.toBeInTheDocument()
  })

  it('muestra "IA en vivo" cuando el servidor usa un modelo real', async () => {
    stubApi([[/\/api\/health\/ready/, { body: { ...ready.body, llm_mode: 'live' } }]])
    app('/ayuda')
    expect(await screen.findByText('IA en vivo')).toBeInTheDocument()
  })

  it('avisa de forma global cuando el servidor no está disponible', async () => {
    stubApi([
      [
        /\/api\/health\/ready/,
        {
          status: 503,
          body: {
            status: 'unavailable',
            llm_mode: 'demo',
            redis: false,
            worker: false,
            observability: false,
          },
        },
      ],
    ])
    app('/ayuda')
    expect(await screen.findByText('El servidor no está disponible.')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /reintentar ahora/i })).toBeInTheDocument()
  })

  it('avisa cuando el servicio que prepara las preguntas no responde', async () => {
    stubApi([
      [/\/api\/health\/ready/, { body: { ...ready.body, status: 'degraded', worker: false } }],
    ])
    app('/ayuda')
    expect(
      await screen.findByText('El servicio que prepara las preguntas no responde.'),
    ).toBeInTheDocument()
  })

  it('una ruta desconocida muestra una página "no encontrada" con salida', async () => {
    stubApi([[/\/api\/health\/ready/, ready]])
    app('/esto/no/existe')
    expect(
      await screen.findByRole('heading', { name: 'No encontramos esta página' }),
    ).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Volver a mis proyectos' })).toHaveAttribute(
      'href',
      '/',
    )
    await waitFor(() => expect(document.title).toBe('Página no encontrada · PanelLab'))
  })

  it('la lista de proyectos no dice "vacío" mientras carga', async () => {
    stubApi([
      [/\/api\/health\/ready/, ready],
      [/\/api\/projects\?/, 'pending'],
    ])
    app('/')
    expect(await screen.findByText('Cargando proyectos…')).toBeInTheDocument()
    expect(screen.queryByText('Todavía no hay proyectos')).not.toBeInTheDocument()
  })

  it('la lista de proyectos ofrece Reintentar con un mensaje claro si falla', async () => {
    stubApi([
      [/\/api\/health\/ready/, ready],
      [/\/api\/projects\?/, { status: 500, body: { code: 'http_500', message: 'request failed' } }],
    ])
    app('/')
    expect(await screen.findByText(/Algo falló de nuestro lado/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Reintentar' })).toBeInTheDocument()
    expect(screen.queryByText(/La solicitud falló/)).not.toBeInTheDocument()
  })
})
