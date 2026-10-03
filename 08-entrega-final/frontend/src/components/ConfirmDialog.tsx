import { useId } from 'react'
import type { ReactNode } from 'react'
import { useDialogFocus } from '../hooks/useDialogFocus'
import { Button } from './UI'

/**
 * Small modal that asks before doing something hard to undo. Focus starts on the safe
 * (cancel) option; Esc, a click outside and the cancel button all mean "no".
 * Render it only while it is open.
 */
export function ConfirmDialog({
  title,
  children,
  confirmLabel,
  cancelLabel,
  onConfirm,
  onCancel,
  tone = 'primary',
  busy,
}: {
  title: string
  children: ReactNode
  confirmLabel: string
  cancelLabel: string
  onConfirm: () => void
  onCancel: () => void
  tone?: 'primary' | 'danger'
  busy?: boolean
}) {
  const ref = useDialogFocus<HTMLDivElement>(true, onCancel)
  const titleId = useId()
  const bodyId = useId()
  return (
    <div
      className="modal-backdrop modal-backdrop--confirm"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget) onCancel()
      }}
    >
      <div
        ref={ref}
        tabIndex={-1}
        className="modal modal--confirm"
        role="alertdialog"
        aria-modal="true"
        aria-labelledby={titleId}
        aria-describedby={bodyId}
      >
        <h2 id={titleId}>{title}</h2>
        <div id={bodyId} className="modal__body">
          {children}
        </div>
        <div className="modal__actions">
          <Button type="button" variant="secondary" data-dialog-initial-focus onClick={onCancel}>
            {cancelLabel}
          </Button>
          <Button type="button" variant={tone} loading={busy} onClick={onConfirm}>
            {confirmLabel}
          </Button>
        </div>
      </div>
    </div>
  )
}
