import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { ComparisonTable, describeChange } from './ComparisonTable'

const change = (previous_status: string, current_status: string) =>
  ({
    criterion_id: 'evidencia',
    title: 'Evidencia del avance',
    previous_status,
    current_status,
    previous_sources: 0,
    current_sources: 2,
  }) as Parameters<typeof describeChange>[0]

describe('ComparisonTable', () => {
  it('describes the trend of each criterion in plain Spanish', () => {
    expect(describeChange(change('missing', 'partial')).label).toBe('Mejoró')
    expect(describeChange(change('supported', 'partial')).label).toBe('Retrocedió')
    expect(describeChange(change('partial', 'partial')).label).toBe('Sin cambios')
    expect(describeChange(change('not_assessed', 'partial')).label).toBe('Tratado por primera vez')
    expect(describeChange(change('partial', 'not_assessed')).label).toBe('No se trató esta vez')
  })

  it('shows titles and human labels, never raw statuses or ids', () => {
    render(<ComparisonTable changes={[change('missing', 'partial')]} />)
    expect(screen.getByRole('rowheader', { name: 'Evidencia del avance' })).toBeInTheDocument()
    expect(screen.getByText('Sin evidencia')).toBeInTheDocument()
    expect(screen.getByText('Parcial')).toBeInTheDocument()
    expect(screen.getByText('2 fuentes citadas')).toBeInTheDocument()
    expect(screen.queryByText(/missing|partial/)).not.toBeInTheDocument()
  })
})
