import { afterEach, describe, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, screen, within } from '@testing-library/react'
import { page, renderAt, stubApi } from '../test/utils'
import { Projects } from './Projects'

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
})

function view() {
  stubApi([[/\/api\/projects\?/, page([])]])
  renderAt(<Projects />, { path: '/', route: '/' })
}

describe('modal de nuevo proyecto', () => {
  it('enfoca el primer campo, cierra con Esc y devuelve el foco al botón que lo abrió', async () => {
    view()
    const trigger = await screen.findByRole('button', { name: 'Nuevo proyecto' })
    trigger.focus()
    fireEvent.click(trigger)
    expect(screen.getByRole('dialog', { name: 'Empezar proyecto' })).toBeInTheDocument()
    expect(screen.getByLabelText(/Nombre del proyecto/)).toHaveFocus()
    fireEvent.keyDown(document, { key: 'Escape' })
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
    expect(trigger).toHaveFocus()
  })

  it('mantiene el Tab dentro del diálogo', async () => {
    view()
    fireEvent.click(await screen.findByRole('button', { name: 'Nuevo proyecto' }))
    const create = within(screen.getByRole('dialog')).getByRole('button', {
      name: /crear proyecto/i,
    })
    create.focus()
    fireEvent.keyDown(document, { key: 'Tab' })
    expect(screen.getByRole('button', { name: 'Cerrar' })).toHaveFocus()
    fireEvent.keyDown(document, { key: 'Tab', shiftKey: true })
    expect(create).toHaveFocus()
  })

  it('muestra mensajes en español junto a cada campo en lugar de la burbuja del navegador', async () => {
    view()
    fireEvent.click(await screen.findByRole('button', { name: 'Nuevo proyecto' }))
    fireEvent.click(
      within(screen.getByRole('dialog')).getByRole('button', { name: /crear proyecto/i }),
    )
    expect(screen.getByText('Escribí un nombre para el proyecto.')).toBeInTheDocument()
    expect(screen.getByLabelText(/Nombre del proyecto/)).toHaveAttribute('aria-invalid', 'true')
    expect(screen.getByLabelText(/Nombre del proyecto/)).toHaveFocus()
    expect(screen.getByRole('dialog').querySelector('form')).toHaveAttribute('novalidate')
  })

  it('pregunta antes de descartar lo escrito', async () => {
    view()
    fireEvent.click(await screen.findByRole('button', { name: 'Nuevo proyecto' }))
    fireEvent.change(screen.getByLabelText(/Nombre del proyecto/), { target: { value: 'Algo' } })
    fireEvent.keyDown(document, { key: 'Escape' })
    expect(screen.getByRole('alertdialog')).toHaveTextContent(/cambios sin guardar/)
    fireEvent.click(screen.getByRole('button', { name: 'Seguir editando' }))
    expect(screen.queryByRole('alertdialog')).not.toBeInTheDocument()
    expect(screen.getByLabelText(/Nombre del proyecto/)).toHaveValue('Algo')
    fireEvent.keyDown(document, { key: 'Escape' })
    fireEvent.click(screen.getByRole('button', { name: 'Descartar' }))
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
  })
})
