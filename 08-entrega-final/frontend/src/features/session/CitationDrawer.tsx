import { useEffect, useMemo, useRef } from 'react'
import { useQuery } from '@tanstack/react-query'
import { FileText, X } from 'lucide-react'
import { api } from '../../api/client'
import type { Citation } from '../../api/types'
import { ErrorNotice, LoadingState } from '../../components/UI'
import { useDialogFocus } from '../../hooks/useDialogFocus'
import { scrollToElement } from '../../hooks/usePageHelpers'

const escapeRegExp = (value: string) => value.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')

/** Finds the cited excerpt inside the full document (tolerating different whitespace). */
export function splitAroundExcerpt(
  text?: string,
  excerpt?: string,
): { before: string; match: string; after: string } | null {
  if (!text || !excerpt?.trim()) return null
  let start = text.indexOf(excerpt)
  let length = excerpt.length
  if (start < 0) {
    const words = excerpt.trim().split(/\s+/).map(escapeRegExp)
    const found = new RegExp(words.join('\\s+')).exec(text)
    if (!found) return null
    start = found.index
    length = found[0].length
  }
  return {
    before: text.slice(0, start),
    match: text.slice(start, start + length),
    after: text.slice(start + length),
  }
}

export function CitationDrawer({
  citation,
  projectId,
  documentTitle,
  onClose,
}: {
  citation: Citation | null
  projectId: string
  /** Title already known from the materials list, shown while the full text loads. */
  documentTitle?: string
  onClose: () => void
}) {
  const panelRef = useDialogFocus<HTMLElement>(!!citation, onClose)
  const markRef = useRef<HTMLElement>(null)
  const source = useQuery({
    queryKey: ['document', projectId, citation?.document_id, citation?.version],
    queryFn: ({ signal }) =>
      api.document(projectId, citation!.document_id, citation!.version, signal),
    enabled: !!citation,
  })
  const parts = useMemo(
    () => splitAroundExcerpt(source.data?.text, citation?.excerpt),
    [source.data?.text, citation?.excerpt],
  )
  // Once the full text is on screen, jump to the highlighted passage.
  useEffect(() => {
    if (parts) scrollToElement(markRef.current, 'center')
  }, [parts])
  if (!citation) return null
  const title =
    source.data?.title ||
    documentTitle ||
    (source.isPending ? 'Cargando el material…' : 'No pudimos abrir este material')
  return (
    <div
      className="drawer-backdrop"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget) onClose()
      }}
    >
      <aside
        ref={panelRef}
        className="citation-drawer"
        role="dialog"
        aria-modal="true"
        aria-labelledby="citation-title"
        tabIndex={-1}
      >
        <div className="citation-drawer__head">
          <div>
            <p className="eyebrow">MATERIAL CONSULTADO · VERSIÓN {citation.version}</p>
            <h2 id="citation-title">{title}</h2>
          </div>
          <button
            type="button"
            data-dialog-initial-focus
            className="icon-button"
            onClick={onClose}
            aria-label="Cerrar material"
          >
            <X size={21} aria-hidden />
          </button>
        </div>
        <div className="citation-drawer__body">
          <span className="citation-section">
            <FileText size={15} aria-hidden /> {citation.section || 'Fragmento citado'}
          </span>
          <blockquote>{citation.excerpt}</blockquote>
          <p className="field-note">Extracto que usó el panel en esta pregunta.</p>
          <div className="drawer-divider" />
          <h3>Documento completo</h3>
          {source.isPending ? <LoadingState label="Cargando el documento…" rows={3} /> : null}
          <ErrorNotice
            error={source.error}
            onRetry={() => void source.refetch()}
            retrying={source.isFetching}
          />
          {source.data ? (
            <>
              {parts ? <p className="field-note">El fragmento citado aparece resaltado.</p> : null}
              <pre className="source-text">
                {parts ? (
                  <>
                    {parts.before}
                    <mark ref={markRef}>{parts.match}</mark>
                    {parts.after}
                  </>
                ) : (
                  source.data.text
                )}
              </pre>
            </>
          ) : null}
        </div>
      </aside>
    </div>
  )
}
