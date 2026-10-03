import { afterEach, describe, expect, it, vi } from 'vitest'
import { api, ApiError } from './client'

afterEach(() => vi.unstubAllGlobals())

describe('API client', () => {
  it('loads later document versions across pages instead of hiding them', async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({ items: [{ document_id: 'brief', version: 1 }], next_cursor: '100' }),
      })
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({ items: [{ document_id: 'brief', version: 2 }], next_cursor: null }),
      })
    vi.stubGlobal('fetch', fetchMock)
    const result = await api.documents('project')
    expect(result.items.map((item) => item.version)).toEqual([1, 2])
    expect(fetchMock.mock.calls[1][0]).toBe('/api/projects/project/documents?limit=100&cursor=100')
  })

  it('sends the supplied idempotency key with a response command and keeps the canonical path', async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({
        job_id: 'job-1',
        session_id: 'session-1',
        status: 'QUEUED',
        status_url: '/api/jobs/job-1',
      }),
    })
    vi.stubGlobal('fetch', fetchMock)
    await api.respond(
      'session-1',
      { question_id: 'q-1', expected_revision: 3, text: 'Respuesta' },
      'same-key',
    )
    const [path, options] = fetchMock.mock.calls[0] as [string, RequestInit]
    expect(path).toBe('/api/sessions/session-1/responses')
    expect(new Headers(options.headers).get('Idempotency-Key')).toBe('same-key')
    expect(JSON.parse(String(options.body))).toMatchObject({
      question_id: 'q-1',
      expected_revision: 3,
    })
  })

  it('keeps a server conflict distinct from a connection failure', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue({
        ok: false,
        status: 409,
        json: async () => ({ code: 'conflict', message: 'La revisión cambió' }),
      }),
    )
    await expect(
      api.respond('s', { question_id: 'q', expected_revision: 0, text: 'A' }, 'key'),
    ).rejects.toMatchObject({ status: 409, message: 'La revisión cambió' })
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new Error('offline')))
    await expect(api.session('s')).rejects.toBeInstanceOf(ApiError)
  })
})
