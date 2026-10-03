import { describe, expect, it } from 'vitest'
import { ApiError } from './client'
import { describeError, describeJobError, friendlyMessage, isNotFound } from './errors'

const apiError = (status: number, message: string, code?: string) =>
  new ApiError(status, message, { code, message }, { code, request: 'GET /api/x' })

describe('describeError', () => {
  it('explica una falla de red con el siguiente paso', () => {
    const info = describeError(new ApiError(0, 'Network request failed'))
    expect(info.message).toBe('No pudimos conectar con el servidor.')
    expect(info.hint).toBe('Revisá que PanelLab esté corriendo y reintentá.')
    expect(info.retryable).toBe(true)
    expect(friendlyMessage(new ApiError(0, 'x'))).toBe(
      'No pudimos conectar con el servidor. Revisá que PanelLab esté corriendo y reintentá.',
    )
  })

  it.each([
    [404, 'project not found', 'http_404', /No encontramos este proyecto/],
    [413, 'document exceeds 200 KB', 'http_413', /supera los 200 KB/],
    [422, 'duplicate profile', 'http_422', /mismo evaluador/],
    [503, 'storage unavailable', 'redis_unavailable', /almacenamiento/],
    [409, 'session state or question changed', 'conflict', /sesión cambió/],
  ])('traduce %s "%s" a español claro', (status, message, code, expected) => {
    const info = describeError(apiError(status, message, code))
    expect(info.message).toMatch(expected)
    expect(info.message).not.toMatch(/not found|exceeds|duplicate|storage unavailable|changed/i)
    expect(info.hint).toBeTruthy()
  })

  it('convierte los campos inválidos en nombres que la persona reconoce', () => {
    const info = describeError(
      apiError(422, 'invalid fields: body.title, body.objective', 'validation_error'),
    )
    expect(info.message).toBe('Revisá estos campos: nombre o título, objetivo.')
  })

  it('traduce los errores del Markdown de evaluadores y rúbricas', () => {
    const info = describeError(apiError(422, 'YAML frontmatter is required', 'invalid_content'))
    expect(info.message).toMatch(/bloque inicial/)
    expect(info.hint).toMatch(/Insertar plantilla/)
  })

  it('usa un mensaje genérico por estado si el texto no se reconoce', () => {
    const server = describeError(apiError(500, 'HTTP 500'))
    expect(server.message).toBe('Algo falló de nuestro lado.')
    expect(server.message).not.toMatch(/solicitud falló/i)
    expect(server.retryable).toBe(true)
    expect(describeError(apiError(422, 'algo raro')).retryable).toBe(false)
    expect(describeError(apiError(418, 'teapot')).message).toBe('Ocurrió un error inesperado.')
  })

  it('conserva el texto técnico solo como detalle', () => {
    const info = describeError(apiError(404, 'project not found', 'http_404'))
    expect(info.technical).toContain('project not found')
    expect(info.technical).toContain('HTTP 404')
    expect(info.message).not.toContain('project not found')
  })

  it('respeta el mensaje en español que ya envía el endpoint de PDF', () => {
    const error = new ApiError(
      422,
      'El PDF tiene contraseña. Quitá la protección y volvé a subirlo.',
    )
    error.userMessage = error.message
    expect(describeError(error).message).toMatch(/contraseña/)
  })

  it('reconoce los 404 y no expone textos de errores desconocidos', () => {
    expect(isNotFound(apiError(404, 'job not found'))).toBe(true)
    expect(isNotFound(apiError(500, 'boom'))).toBe(false)
    const unknown = describeError(new Error('TypeError: x is undefined'))
    expect(unknown.message).toBe('Ocurrió un error inesperado.')
    expect(unknown.technical).toBe('TypeError: x is undefined')
  })
})

describe('describeJobError', () => {
  it('no muestra el texto crudo de la excepción como mensaje', () => {
    const info = describeJobError({
      code: 'ValueError',
      message: 'Snapshot source is not indexed',
      retryable: true,
    })
    expect(info.message).toBe('El panel no pudo preparar la respuesta.')
    expect(info.technical).toBe('ValueError: Snapshot source is not indexed')
    expect(info.retryable).toBe(true)
  })

  it('distingue demoras, límites de uso y falta de acceso', () => {
    expect(describeJobError({ code: 'TimeoutError', message: 'x' }).message).toMatch(
      /tardó demasiado/,
    )
    expect(describeJobError({ code: 'RateLimitError', message: 'x' }).message).toMatch(/saturado/)
    expect(
      describeJobError({ code: 'AuthenticationError', message: 'bad api key' }).message,
    ).toMatch(/No se pudo acceder/)
  })

  it('tiene un texto razonable cuando no hay detalle del trabajo', () => {
    const info = describeJobError(null)
    expect(info.message).toBeTruthy()
    expect(info.technical).toBeUndefined()
  })
})
