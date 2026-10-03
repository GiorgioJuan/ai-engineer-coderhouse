import { useEffect, useRef } from 'react'

const focusableSelector =
  'button:not([disabled]), a[href], input:not([disabled]):not([type="hidden"]), textarea:not([disabled]), select:not([disabled]), summary, [tabindex]:not([tabindex="-1"])'

/** Open dialogs, oldest first. Only the top-most one reacts to keys (a confirm above an editor). */
const openDialogs: object[] = []

/** Keeps keyboard focus inside an open dialog and returns it to the trigger on close. */
export function useDialogFocus<T extends HTMLElement>(open: boolean, onClose: () => void) {
  const dialogRef = useRef<T>(null)
  const closeRef = useRef(onClose)
  closeRef.current = onClose

  useEffect(() => {
    if (!open) return
    const token = {}
    openDialogs.push(token)
    const previous = document.activeElement instanceof HTMLElement ? document.activeElement : null
    const dialog = dialogRef.current
    const first =
      dialog?.querySelector<HTMLElement>('[data-dialog-initial-focus]') ||
      dialog?.querySelector<HTMLElement>(focusableSelector)
    ;(first || dialog)?.focus()

    function handleKeyDown(event: KeyboardEvent) {
      if (openDialogs[openDialogs.length - 1] !== token) return
      if (event.key === 'Escape') {
        event.preventDefault()
        closeRef.current()
        return
      }
      if (event.key !== 'Tab') return
      const controls = [
        ...(dialogRef.current?.querySelectorAll<HTMLElement>(focusableSelector) || []),
      ]
      if (!controls.length) {
        event.preventDefault()
        dialogRef.current?.focus()
        return
      }
      const firstControl = controls[0]
      const lastControl = controls[controls.length - 1]
      if (
        event.shiftKey &&
        (document.activeElement === firstControl ||
          !dialogRef.current?.contains(document.activeElement))
      ) {
        event.preventDefault()
        lastControl.focus()
      } else if (
        !event.shiftKey &&
        (document.activeElement === lastControl ||
          !dialogRef.current?.contains(document.activeElement))
      ) {
        event.preventDefault()
        firstControl.focus()
      }
    }
    document.addEventListener('keydown', handleKeyDown)
    return () => {
      document.removeEventListener('keydown', handleKeyDown)
      const index = openDialogs.indexOf(token)
      if (index >= 0) openDialogs.splice(index, 1)
      previous?.focus()
    }
  }, [open])

  return dialogRef
}
