import { useState } from 'react'
import { afterEach, expect, it } from 'vitest'
import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { useDialogFocus } from './useDialogFocus'

afterEach(cleanup)

function Fixture() {
  const [open, setOpen] = useState(false)
  const ref = useDialogFocus<HTMLDivElement>(open, () => setOpen(false))
  return (
    <>
      <button onClick={() => setOpen(true)}>Abrir</button>
      {open ? (
        <div ref={ref} role="dialog" tabIndex={-1}>
          <button data-dialog-initial-focus>Cerrar</button>
          <button>Última acción</button>
        </div>
      ) : null}
    </>
  )
}

it('mantiene el foco en el diálogo, permite Escape y lo devuelve al control inicial', () => {
  render(<Fixture />)
  const trigger = screen.getByRole('button', { name: 'Abrir' })
  trigger.focus()
  fireEvent.click(trigger)
  const close = screen.getByRole('button', { name: 'Cerrar' })
  const last = screen.getByRole('button', { name: 'Última acción' })
  expect(close).toHaveFocus()
  fireEvent.keyDown(document, { key: 'Tab', shiftKey: true })
  expect(last).toHaveFocus()
  fireEvent.keyDown(document, { key: 'Tab' })
  expect(close).toHaveFocus()
  fireEvent.keyDown(document, { key: 'Escape' })
  expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
  expect(trigger).toHaveFocus()
})
