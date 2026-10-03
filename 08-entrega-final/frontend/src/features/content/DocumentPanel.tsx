import { useEffect, useMemo, useRef, useState } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { ChevronRight, FilePlus2, FileText, Plus, Save, UploadCloud, X } from 'lucide-react'
import { useDialogFocus } from '../../hooks/useDialogFocus'
import { api, ApiError, commandKey } from '../../api/client'
import { friendlyMessage } from '../../api/errors'
import type { DocumentVersion } from '../../api/types'
import { ConfirmDialog } from '../../components/ConfirmDialog'
import {
  Button,
  EmptyState,
  ErrorNotice,
  Label,
  StatePill,
  dateLabel,
  latest,
} from '../../components/UI'
import {
  documentKindLabel,
  documentKindOptions,
  documentStatus,
  documentStatusNote,
  type DocumentKind,
} from '../../labels'

export function DocumentPanel({
  projectId,
  documents,
}: {
  projectId: string
  documents: DocumentVersion[]
}) {
  const [editing, setEditing] = useState(false)
  const [discarding, setDiscarding] = useState(false)
  const [title, setTitle] = useState('')
  const [kind, setKind] = useState<DocumentKind>('source')
  const [text, setText] = useState('')
  const [selected, setSelected] = useState<DocumentVersion | null>(null)
  const [versionOf, setVersionOf] = useState<string | null>(null)
  const [fileError, setFileError] = useState('')
  const [reading, setReading] = useState(false)
  const [fileNotice, setFileNotice] = useState('')
  const [announcement, setAnnouncement] = useState('')
  /** What the editor held when it opened, to tell whether there is unsaved work. */
  const baseline = useRef({ title: '', text: '' })
  const importSequence = useRef(0)
  const importAbort = useRef<AbortController | null>(null)
  useEffect(
    () => () => {
      importSequence.current++
      importAbort.current?.abort()
    },
    [],
  )
  const pendingCommand = useRef<{
    key: string
    payload: Parameters<typeof api.addDocument>[1]
  } | null>(null)
  const inputRef = useRef<HTMLInputElement>(null)
  const queryClient = useQueryClient()
  const add = useMutation({
    mutationFn: () => {
      const command = (pendingCommand.current ||= {
        key: commandKey(),
        payload: {
          title: title.trim(),
          kind,
          text,
          ...(versionOf ? { document_id: versionOf } : {}),
        },
      })
      return api.addDocument(projectId, command.payload, command.key)
    },
    onSuccess: () => {
      pendingCommand.current = null
      setEditing(false)
      setText('')
      setTitle('')
      setVersionOf(null)
      queryClient.invalidateQueries({ queryKey: ['documents', projectId] })
    },
    onError: (error) => {
      if (error instanceof ApiError && error.status > 0) pendingCommand.current = null
    },
  })
  async function loadFile(file?: File) {
    if (!file || add.isPending) return
    importAbort.current?.abort()
    const sequence = ++importSequence.current
    setReading(false)
    setFileError('')
    setFileNotice('')
    if (!/\.(pdf|md|txt)$/i.test(file.name)) {
      setFileError('Elegí un archivo PDF, Markdown (.md) o texto (.txt).')
      return
    }
    const isPdf = /\.pdf$/i.test(file.name)
    if (file.size > (isPdf ? 10 * 1024 * 1024 : 200000)) {
      setFileError(
        isPdf
          ? 'El PDF supera los 10 MB. Dividilo en archivos más pequeños.'
          : 'El archivo supera los 200 KB. Dividilo en archivos más pequeños.',
      )
      return
    }
    const controller = new AbortController()
    importAbort.current = controller
    setReading(true)
    try {
      const result = isPdf
        ? await api.extractPdf(projectId, file, controller.signal)
        : {
            text: await file.text(),
            title: file.name.replace(/\.(md|txt)$/i, ''),
            page_count: 0,
            warnings: [],
          }
      if (sequence !== importSequence.current) return
      if (!result.text.trim()) {
        setFileError('El archivo no contiene texto. Elegí otro archivo o pegá el contenido.')
        return
      }
      setText(result.text)
      setTitle(result.title.slice(0, 160))
      setFileNotice(
        isPdf
          ? `${result.page_count} ${result.page_count === 1 ? 'página importada' : 'páginas importadas'}. Revisá el texto antes de guardar. ${(result.warnings || []).join(' ')}`
          : 'Archivo importado. Revisá el contenido antes de guardar.',
      )
    } catch (error) {
      if (sequence === importSequence.current)
        setFileError(
          error instanceof ApiError
            ? friendlyMessage(error)
            : 'No se pudo leer el archivo. Probá con otro o pegá el texto.',
        )
    } finally {
      if (sequence === importSequence.current) setReading(false)
    }
  }
  function closeEditor() {
    if (add.isPending) return
    importSequence.current++
    importAbort.current?.abort()
    setReading(false)
    setDiscarding(false)
    setEditing(false)
  }
  const dirty = title.trim() !== baseline.current.title.trim() || text !== baseline.current.text
  /** Esc, click outside, "X" and "Cancelar" all go through here so unsaved work is never lost silently. */
  function requestClose() {
    if (add.isPending) return
    if (dirty) setDiscarding(true)
    else closeEditor()
  }
  function openEditor(next: {
    title: string
    text: string
    kind: DocumentKind
    versionOf: string | null
  }) {
    baseline.current = { title: next.title, text: next.text }
    setVersionOf(next.versionOf)
    setTitle(next.title)
    setKind(next.kind)
    setText(next.text)
    setFileError('')
    setFileNotice('')
    pendingCommand.current = null
    add.reset()
    setSelected(null)
    setEditing(true)
  }
  const openNewVersion = (doc: DocumentVersion) =>
    openEditor({ title: doc.title, text: doc.text, kind: doc.kind, versionOf: doc.document_id })
  function submit(event: React.FormEvent) {
    event.preventDefault()
    if (add.isPending || reading || !title.trim() || !text.trim()) return
    if (new TextEncoder().encode(text).length > 200000) {
      setFileError('El texto supera los 200 KB. Reducí el contenido o dividilo en dos materiales.')
      return
    }
    add.mutate()
  }
  const editorDialogRef = useDialogFocus<HTMLDivElement>(editing, requestClose)
  const sourceDialogRef = useDialogFocus<HTMLDivElement>(selected !== null, () => setSelected(null))
  const current = useMemo(
    () =>
      latest(
        documents,
        (item) => item.document_id,
        (item) => item.version,
      ),
    [documents],
  )
  // Tell screen-reader users when a material changes state ("Preparando → Listo").
  const lastStatuses = useRef(new Map<string, string>())
  useEffect(() => {
    const notes: string[] = []
    for (const doc of current) {
      const key = `${doc.document_id}:${doc.version}`
      const before = lastStatuses.current.get(key)
      if (before && before !== doc.index_status)
        notes.push(
          `${doc.title}: ${documentStatus(before).label} → ${documentStatus(doc.index_status).label}`,
        )
      lastStatuses.current.set(key, doc.index_status)
    }
    if (notes.length) setAnnouncement(notes.join('. '))
  }, [current])
  const canSave = !reading && !!title.trim() && !!text.trim()
  const selectedStatus = selected ? documentStatus(selected.index_status) : null
  const selectedNote = selected ? documentStatusNote(selected.index_status) : null
  return (
    <div className="workspace-panel">
      <p className="sr-only" role="status" aria-live="polite">
        {announcement}
      </p>
      <div className="panel-intro">
        <div>
          <p className="eyebrow">01 / MATERIALES</p>
          <h2>Materiales que sostienen la conversación</h2>
          <p>
            El panel busca evidencia únicamente en los materiales listos que selecciones para cada
            sesión.
          </p>
        </div>
        <Button
          onClick={() => openEditor({ title: '', text: '', kind: 'source', versionOf: null })}
        >
          <Plus size={17} aria-hidden /> Agregar material
        </Button>
      </div>
      {!editing ? <ErrorNotice error={fileError} /> : null}
      {current.length ? (
        <div className="document-list">
          {current.map((doc) => {
            const status = documentStatus(doc.index_status)
            const note = documentStatusNote(doc.index_status)
            return (
              <div className="document-item" key={doc.document_id}>
                <button className="document-row" onClick={() => setSelected(doc)}>
                  <span className="document-row__icon">
                    <FileText size={21} aria-hidden />
                  </span>
                  <span className="document-row__main">
                    <strong>{doc.title}</strong>
                    <small>
                      {documentKindLabel(doc.kind)} · versión {doc.version} ·{' '}
                      {dateLabel(doc.created_at)}
                    </small>
                    {note ? <small className="document-row__note">{note}</small> : null}
                  </span>
                  <StatePill tone={status.tone}>{status.label}</StatePill>
                  <ChevronRight size={18} className="document-row__arrow" aria-hidden />
                </button>
                {status.tone === 'bad' ? (
                  <Button variant="secondary" onClick={() => openNewVersion(doc)}>
                    <FilePlus2 size={16} aria-hidden /> Subir una nueva versión
                  </Button>
                ) : null}
              </div>
            )
          })}
        </div>
      ) : (
        <EmptyState title="Todavía no cargaste materiales">
          Sumá un brief, una consigna o un avance en PDF, Markdown o texto. Podés pegar el contenido
          o importar un archivo.
        </EmptyState>
      )}
      {editing ? (
        <div
          className="modal-backdrop"
          onMouseDown={(event) => {
            if (event.target === event.currentTarget) requestClose()
          }}
        >
          <div
            ref={editorDialogRef}
            tabIndex={-1}
            className="modal modal--wide"
            role="dialog"
            aria-modal="true"
            aria-labelledby="document-title"
          >
            <div className="modal__head">
              <div>
                <p className="eyebrow">{versionOf ? 'NUEVA VERSIÓN' : 'NUEVO MATERIAL'}</p>
                <h2 id="document-title">{versionOf ? 'Nueva versión' : 'Agregar material'}</h2>
              </div>
              <button
                type="button"
                className="icon-button"
                aria-label="Cerrar"
                onClick={requestClose}
                disabled={add.isPending}
              >
                <X size={21} aria-hidden />
              </button>
            </div>
            <form className="stack-form" onSubmit={submit} noValidate>
              <button
                type="button"
                className="upload-target"
                disabled={reading || add.isPending}
                aria-busy={reading}
                onClick={() => inputRef.current?.click()}
                onDragOver={(event) => event.preventDefault()}
                onDrop={(event) => {
                  event.preventDefault()
                  loadFile(event.dataTransfer.files[0])
                }}
              >
                <UploadCloud size={21} aria-hidden />
                <span>
                  {reading
                    ? 'Extrayendo texto…'
                    : 'Arrastrá un PDF, .md o .txt, o elegí un archivo'}
                </span>
              </button>
              <input
                ref={inputRef}
                className="sr-only"
                type="file"
                tabIndex={-1}
                aria-label="Importar archivo"
                accept=".pdf,.md,.txt,application/pdf,text/plain,text/markdown"
                onChange={(event) => {
                  const file = event.target.files?.[0]
                  event.target.value = ''
                  void loadFile(file)
                }}
              />
              <small className="field-note">
                PDF con texto: hasta 10 MB y 50 páginas. Texto importado: hasta 200 KB. La
                extracción no consume créditos de IA.
              </small>
              <p role="status" aria-live="polite">
                {reading
                  ? 'Extrayendo texto del archivo. Podés cancelar y conservar tu contenido.'
                  : fileNotice}
              </p>
              <p className="form-legend">Los campos con * son obligatorios.</p>
              <Label htmlFor="document-name" required>
                Título
              </Label>
              <input
                id="document-name"
                disabled={reading || add.isPending}
                value={title}
                required
                maxLength={160}
                onChange={(event) => setTitle(event.target.value)}
              />
              <Label htmlFor="document-kind">Tipo de material</Label>
              <select
                id="document-kind"
                disabled={reading || add.isPending}
                value={kind}
                onChange={(event) => setKind(event.target.value as DocumentKind)}
              >
                {documentKindOptions.map(([value, label]) => (
                  <option key={value} value={value}>
                    {label}
                  </option>
                ))}
              </select>
              <Label
                htmlFor="document-text"
                required
                hint={`${text.length.toLocaleString('es-AR')} caracteres · máximo 200 KB`}
              >
                Contenido
              </Label>
              <textarea
                id="document-text"
                disabled={reading || add.isPending}
                value={text}
                required
                rows={12}
                onChange={(event) => setText(event.target.value)}
                placeholder="Pegá acá el contenido…"
              />
              <ErrorNotice error={fileError || add.error} />
              {!canSave && !reading ? (
                <p className="field-note" id="document-save-hint">
                  Para guardar, completá el título y el contenido.
                </p>
              ) : null}
              <div className="modal__actions">
                <Button
                  variant="ghost"
                  type="button"
                  onClick={requestClose}
                  disabled={add.isPending}
                >
                  Cancelar
                </Button>
                <Button
                  type="submit"
                  disabled={!canSave}
                  loading={add.isPending}
                  aria-describedby={!canSave && !reading ? 'document-save-hint' : undefined}
                >
                  <Save size={17} aria-hidden /> Guardar material
                </Button>
              </div>
            </form>
          </div>
        </div>
      ) : null}
      {discarding ? (
        <ConfirmDialog
          title="¿Descartar los cambios?"
          cancelLabel="Seguir editando"
          confirmLabel="Descartar cambios"
          tone="danger"
          onCancel={() => setDiscarding(false)}
          onConfirm={closeEditor}
        >
          <p>Tenés cambios sin guardar. Si cerrás ahora, se pierde el contenido que pegaste.</p>
        </ConfirmDialog>
      ) : null}
      {selected ? (
        <div
          className="modal-backdrop"
          onMouseDown={(event) => {
            if (event.target === event.currentTarget) setSelected(null)
          }}
        >
          <div
            ref={sourceDialogRef}
            tabIndex={-1}
            className="modal modal--wide"
            role="dialog"
            aria-modal="true"
            aria-labelledby="source-title"
          >
            <div className="modal__head">
              <div>
                <p className="eyebrow">
                  {documentKindLabel(selected.kind).toUpperCase()} · VERSIÓN {selected.version}
                </p>
                <h2 id="source-title">{selected.title}</h2>
              </div>
              <button
                type="button"
                className="icon-button"
                aria-label="Cerrar"
                onClick={() => setSelected(null)}
              >
                <X size={21} aria-hidden />
              </button>
            </div>
            {selectedStatus && selectedStatus.tone !== 'good' ? (
              <div className="notice">
                <StatePill tone={selectedStatus.tone}>{selectedStatus.label}</StatePill>
                <p className="notice__text">{selectedNote}</p>
              </div>
            ) : null}
            <pre className="source-text">{selected.text}</pre>
            <div className="modal__actions">
              <Button onClick={() => openNewVersion(selected)}>
                <FilePlus2 size={17} aria-hidden /> Crear nueva versión
              </Button>
            </div>
          </div>
        </div>
      ) : null}
    </div>
  )
}
