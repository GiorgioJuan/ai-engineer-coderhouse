import { afterEach, describe, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { ApiError } from '../api/client'
import { ErrorNotice, LoadingState } from './UI'

afterEach(cleanup)

describe('ErrorNotice', () => {
  it('muestra un mensaje claro, guarda el texto técnico colapsado y ofrece Reintentar', () => {
    const retry = vi.fn()
    render(
      <ErrorNotice
        error={new ApiError(503, 'storage unavailable', undefined, { code: 'redis_unavailable' })}
        onRetry={retry}
      />,
    )
    expect(screen.getByRole('alert')).toHaveTextContent(
      /almacenamiento de PanelLab no está disponible/,
    )
    const details = screen.getByText('Detalle técnico').closest('details')!
    expect(details).not.toHaveAttribute('open')
    expect(details).toHaveTextContent('storage unavailable')
    fireEvent.click(screen.getByRole('button', { name: /reintentar/i }))
    expect(retry).toHaveBeenCalledTimes(1)
  })

  it('no ofrece Reintentar cuando repetir no puede ayudar', () => {
    render(<ErrorNotice error={new ApiError(422, 'duplicate profile')} onRetry={() => {}} />)
    expect(screen.queryByRole('button', { name: /reintentar/i })).not.toBeInTheDocument()
    expect(screen.getByRole('alert')).toHaveTextContent(/mismo evaluador/)
  })

  it('explica la falla de red', () => {
    render(<ErrorNotice error={new ApiError(0, 'Network request failed')} />)
    expect(screen.getByRole('alert')).toHaveTextContent(
      'No pudimos conectar con el servidor. Revisá que PanelLab esté corriendo y reintentá.',
    )
  })
})

describe('LoadingState', () => {
  it('se anuncia como estado de carga', () => {
    render(<LoadingState label="Cargando materiales…" rows={2} />)
    expect(screen.getByRole('status')).toHaveTextContent('Cargando materiales…')
  })
})
