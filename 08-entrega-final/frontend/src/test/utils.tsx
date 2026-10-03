import type { ReactElement } from 'react'
import { vi } from 'vitest'
import { render } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter, Route, Routes } from 'react-router-dom'

type Reply = { status?: number; body: unknown } | 'pending'
type ApiRoutes = Array<[RegExp, Reply | (() => Reply)]>

/** Replaces `fetch` with a router over regular expressions. Unmatched URLs answer 404. */
export function stubApi(routes: ApiRoutes) {
  const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
    // Routes match "METHOD /url", so a pattern can target e.g. /^PATCH .*\/projects\/p1$/.
    const url = `${init?.method || 'GET'} ${String(input)}`
    const route = routes.find(([pattern]) => pattern.test(url))
    const reply = route ? (typeof route[1] === 'function' ? route[1]() : route[1]) : undefined
    if (reply === 'pending') return new Promise(() => {})
    const status = reply?.status ?? (reply ? 200 : 404)
    return Promise.resolve({
      ok: status < 400,
      status,
      json: async () => (reply ? reply.body : { code: 'http_404', message: 'not found' }),
    })
  })
  vi.stubGlobal('fetch', fetchMock)
  return fetchMock
}

export function renderAt(
  ui: ReactElement,
  { path, route }: { path: string; route: string | { pathname: string; state?: unknown } },
) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[route]}>
        <Routes>
          <Route path={path} element={ui} />
          <Route path="*" element={<p>otra ruta</p>} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

export const page = <T,>(items: T[]) => ({ status: 200, body: { items, next_cursor: null } })
export const ready = {
  status: 200,
  body: { status: 'ready', llm_mode: 'demo', redis: true, worker: true, observability: true },
}
