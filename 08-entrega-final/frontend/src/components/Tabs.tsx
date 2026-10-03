import { useRef } from 'react'
import type { KeyboardEvent, ReactNode } from 'react'

export type TabItem<T extends string> = { id: T; label: ReactNode }

export const tabDomId = (prefix: string, id: string) => `${prefix}-tab-${id}`
export const panelDomId = (prefix: string, id: string) => `${prefix}-panel-${id}`

/**
 * WAI-ARIA tabs: one tab stop, ←/→ (and Home/End) move between tabs and activate them.
 * Pair with <TabPanel> using the same `idPrefix`.
 */
export function Tabs<T extends string>({
  items,
  value,
  onChange,
  label,
  idPrefix,
  className,
}: {
  items: Array<TabItem<T>>
  value: T
  onChange: (value: T) => void
  label: string
  idPrefix: string
  className?: string
}) {
  const refs = useRef(new Map<T, HTMLButtonElement>())
  function move(event: KeyboardEvent, index: number) {
    const last = items.length - 1
    let next = index
    if (event.key === 'ArrowRight') next = index === last ? 0 : index + 1
    else if (event.key === 'ArrowLeft') next = index === 0 ? last : index - 1
    else if (event.key === 'Home') next = 0
    else if (event.key === 'End') next = last
    else return
    event.preventDefault()
    const target = items[next]
    onChange(target.id)
    refs.current.get(target.id)?.focus()
  }
  return (
    <div className={className} role="tablist" aria-label={label}>
      {items.map((item, index) => {
        const selected = item.id === value
        return (
          <button
            key={item.id}
            ref={(node) => {
              if (node) refs.current.set(item.id, node)
              else refs.current.delete(item.id)
            }}
            type="button"
            role="tab"
            id={tabDomId(idPrefix, item.id)}
            aria-selected={selected}
            aria-controls={panelDomId(idPrefix, item.id)}
            tabIndex={selected ? 0 : -1}
            className={selected ? 'active' : ''}
            onClick={() => onChange(item.id)}
            onKeyDown={(event) => move(event, index)}
          >
            {item.label}
          </button>
        )
      })}
    </div>
  )
}

export function TabPanel({
  idPrefix,
  id,
  children,
  focusable = true,
}: {
  idPrefix: string
  id: string
  children: ReactNode
  /** Make the panel itself a tab stop. Turn off when it already contains focusable controls. */
  focusable?: boolean
}) {
  return (
    <div
      role="tabpanel"
      id={panelDomId(idPrefix, id)}
      aria-labelledby={tabDomId(idPrefix, id)}
      tabIndex={focusable ? 0 : undefined}
      className="tab-panel"
    >
      {children}
    </div>
  )
}
