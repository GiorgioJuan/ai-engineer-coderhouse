import { useEffect, useState } from 'react'
import { useLocation } from 'react-router-dom'

/** Sets `document.title` for the current route, e.g. `Informe · Mi proyecto · PanelLab`. */
export function useDocumentTitle(...parts: Array<string | null | undefined | false>) {
  const title = [...parts.filter((part): part is string => !!part), 'PanelLab'].join(' · ')
  useEffect(() => {
    document.title = title
  }, [title])
}

export function prefersReducedMotion(): boolean {
  return (
    typeof window !== 'undefined' &&
    typeof window.matchMedia === 'function' &&
    window.matchMedia('(prefers-reduced-motion: reduce)').matches
  )
}

/** Scrolls an element into view honouring the user's reduced-motion preference. */
export function scrollToElement(element: Element | null, block: ScrollLogicalPosition = 'start') {
  if (!element || typeof element.scrollIntoView !== 'function') return
  element.scrollIntoView({ behavior: prefersReducedMotion() ? 'auto' : 'smooth', block })
}

/**
 * React Router does not scroll to `#hash` targets that render after data loads.
 * Once `ready` is true, scrolls to (and focuses) the element named by the URL hash.
 */
export function useScrollToHash(ready: boolean) {
  const { hash } = useLocation()
  useEffect(() => {
    if (!ready || !hash) return
    let id = hash.slice(1)
    try {
      id = decodeURIComponent(id)
    } catch {
      /* keep raw id */
    }
    const target = document.getElementById(id)
    if (!target) return
    if (!target.hasAttribute('tabindex')) target.setAttribute('tabindex', '-1')
    scrollToElement(target, 'center')
    target.focus({ preventScroll: true })
  }, [ready, hash])
}

/** Whole seconds elapsed since `since` (a timestamp in ms), ticking once per second while mounted. */
export function useElapsedSeconds(since: number): number {
  const [now, setNow] = useState(() => Date.now())
  useEffect(() => {
    const timer = window.setInterval(() => setNow(Date.now()), 1000)
    return () => window.clearInterval(timer)
  }, [])
  return Math.max(0, Math.floor((now - since) / 1000))
}
