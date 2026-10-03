import { afterEach, describe, expect, it, vi } from 'vitest'
import { cleanup, render, screen, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { stubApi } from '../../test/utils'
import { CitationDrawer, splitAroundExcerpt } from './CitationDrawer'

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
})

const citation = {
  document_id: 'd1',
  version: 1,
  chunk_id: 'c1',
  section: 'Contexto',
  excerpt: 'un centro de actividades',
}
const fullText =
  'Intro del brief.\n\n## Contexto\nSomos un centro de actividades barrial.\n\n## Cierre\nFin.'

function drawer(documentTitle?: string) {
  render(
    <QueryClientProvider
      client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}
    >
      <CitationDrawer
        citation={citation}
        projectId="p1"
        documentTitle={documentTitle}
        onClose={() => {}}
      />
    </QueryClientProvider>,
  )
}

describe('panel de cita', () => {
  it('mientras carga no se titula "Fuente original"', async () => {
    stubApi([[/documents\/d1\/versions\/1/, 'pending']])
    drawer()
    expect(
      await screen.findByRole('heading', { name: 'Cargando el material…' }),
    ).toBeInTheDocument()
    expect(screen.queryByText('Fuente original')).not.toBeInTheDocument()
    expect(screen.getByRole('status')).toHaveTextContent('Cargando el documento…')
  })

  it('usa el título que ya se conoce mientras llega el texto completo', async () => {
    stubApi([[/documents\/d1\/versions\/1/, 'pending']])
    drawer('Brief del proyecto')
    expect(await screen.findByRole('heading', { name: 'Brief del proyecto' })).toBeInTheDocument()
  })

  it('resalta el fragmento citado dentro del documento y se desplaza hasta él', async () => {
    const scroll = vi.fn()
    Element.prototype.scrollIntoView = scroll
    stubApi([
      [
        /documents\/d1\/versions\/1/,
        { body: { document_id: 'd1', version: 1, title: 'Brief del proyecto', text: fullText } },
      ],
    ])
    drawer()
    const mark = await waitFor(() => {
      const found = document.querySelector('mark')
      expect(found).not.toBeNull()
      return found!
    })
    expect(mark).toHaveTextContent('un centro de actividades')
    expect(screen.getByText('El fragmento citado aparece resaltado.')).toBeInTheDocument()
    await waitFor(() => expect(scroll).toHaveBeenCalled())
    expect(await screen.findByRole('heading', { name: 'Brief del proyecto' })).toBeInTheDocument()
  })

  it('encuentra el extracto aunque cambien los espacios o saltos de línea', () => {
    const parts = splitAroundExcerpt('Uno dos\ntres   cuatro cinco', 'dos tres cuatro')
    expect(parts?.match).toBe('dos\ntres   cuatro')
    expect(parts?.before).toBe('Uno ')
    expect(splitAroundExcerpt('texto', 'otra cosa')).toBeNull()
  })
})
