import { useRef, useState } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { ArrowDownToLine, FilePlus2, FileUp, Pencil, Plus, Save, X } from 'lucide-react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { api, ApiError, commandKey } from '../../api/client'
import type { ProfileVersion, RubricVersion } from '../../api/types'
import { ConfirmDialog } from '../../components/ConfirmDialog'
import { TabPanel, Tabs } from '../../components/Tabs'
import { Button, EmptyState, ErrorNotice, Label, latest } from '../../components/UI'
import { useDialogFocus } from '../../hooks/useDialogFocus'
import { styleLabel } from '../../labels'
import { profileTemplate, rubricTemplate } from './templates'

type ConfigItem = ProfileVersion | RubricVersion
type ConfigType = 'profile' | 'rubric'
type EditorTab = 'edit' | 'preview'
function isProfile(item: ConfigItem): item is ProfileVersion {
  return 'profile_id' in item
}
const palette = ['reviewer--green', 'reviewer--rust', 'reviewer--blue']
const EDITOR_TABS = 'config-editor'

export function ConfigPanel({
  projectId,
  profiles,
  rubrics,
}: {
  projectId: string
  profiles: ProfileVersion[]
  rubrics: RubricVersion[]
}) {
  const queryClient = useQueryClient()
  const currentProfiles = latest(
    profiles,
    (item) => item.profile_id,
    (item) => item.version,
  )
  const currentRubrics = latest(
    rubrics,
    (item) => item.rubric_id,
    (item) => item.version,
  )
  const [type, setType] = useState<ConfigType>('profile')
  const [selected, setSelected] = useState<ConfigItem | null>(null)
  const [editorOpen, setEditorOpen] = useState(false)
  const [discarding, setDiscarding] = useState(false)
  const [markdown, setMarkdown] = useState('')
  const [tab, setTab] = useState<EditorTab>('edit')
  /** Markdown the editor opened with, to detect unsaved changes. */
  const baseline = useRef('')
  const pendingCommand = useRef<{
    key: string
    markdown: string
    type: ConfigType
    id?: string
  } | null>(null)
  const [fileError, setFileError] = useState('')
  const fileRef = useRef<HTMLInputElement>(null)
  const dirty = markdown !== baseline.current
  function closeEditor() {
    setDiscarding(false)
    setEditorOpen(false)
  }
  /** Esc, click outside, "X" and "Cancelar" all ask first when there is unsaved work. */
  function requestClose() {
    if (save.isPending) return
    if (dirty) setDiscarding(true)
    else closeEditor()
  }
  const dialogRef = useDialogFocus<HTMLDivElement>(editorOpen, requestClose)
  const save = useMutation<ConfigItem>({
    mutationFn: () => {
      const command = (pendingCommand.current ||= {
        key: commandKey(),
        markdown,
        type,
        id: selected ? (isProfile(selected) ? selected.profile_id : selected.rubric_id) : undefined,
      })
      return command.type === 'profile'
        ? api.saveProfile(projectId, command.markdown, command.key, command.id)
        : api.saveRubric(projectId, command.markdown, command.key, command.id)
    },
    onSuccess: () => {
      pendingCommand.current = null
      setEditorOpen(false)
      setSelected(null)
      setMarkdown('')
      baseline.current = ''
      queryClient.invalidateQueries({
        queryKey: [type === 'profile' ? 'profiles' : 'rubrics', projectId],
      })
    },
    onError: (error) => {
      if (error instanceof ApiError && error.status > 0) pendingCommand.current = null
    },
  })
  function open(item: ConfigItem | null, nextType: ConfigType) {
    setType(nextType)
    setSelected(item)
    setMarkdown(item?.markdown || '')
    baseline.current = item?.markdown || ''
    setTab('edit')
    pendingCommand.current = null
    save.reset()
    setFileError('')
    setEditorOpen(true)
  }
  function exportMarkdown(item: ConfigItem) {
    const blob = new Blob([item.markdown], { type: 'text/markdown;charset=utf-8' })
    const url = URL.createObjectURL(blob)
    const anchor = document.createElement('a')
    anchor.href = url
    anchor.download = `${isProfile(item) ? item.profile_id : item.rubric_id}-v${item.version}.md`
    anchor.click()
    URL.revokeObjectURL(url)
  }
  async function importFile(file?: File) {
    if (!file) return
    if (!/\.md$/i.test(file.name)) {
      setFileError('Elegí un archivo .md.')
      return
    }
    if (file.size > 32 * 1024) {
      setFileError('El archivo supera 32 KB.')
      return
    }
    try {
      setMarkdown(await file.text())
      setFileError('')
    } catch {
      setFileError('No se pudo leer el Markdown.')
    }
  }
  const noun = type === 'profile' ? 'evaluador' : 'rúbrica'
  return (
    <div className="workspace-panel">
      <div className="panel-intro">
        <div>
          <p className="eyebrow">02 / EVALUADORES Y RÚBRICA</p>
          <h2>Distintas miradas, una misma evidencia</h2>
          <p>
            Cada evaluador marca cómo pregunta. La rúbrica define qué criterios observa el panel.
          </p>
        </div>
      </div>
      <div className="subsection-heading">
        <h3>Evaluadores</h3>
        <Button variant="secondary" onClick={() => open(null, 'profile')}>
          <Plus size={16} aria-hidden /> Nuevo evaluador
        </Button>
      </div>
      {currentProfiles.length ? (
        <div className="reviewer-grid">
          {currentProfiles.map((item, index) => (
            <article
              className={`reviewer-card ${palette[index % palette.length]}`}
              key={item.profile_id}
            >
              <span className="reviewer-card__num">
                {String(index + 1).padStart(2, '0')} / EVALUADOR
              </span>
              <div className="reviewer-card__initial" aria-hidden>
                {item.name.slice(0, 1)}
              </div>
              <h4>{item.name}</h4>
              <p>{item.role}</p>
              <p className="reviewer-card__style">{styleLabel(item.style)}</p>
              <div className="reviewer-card__foot">
                <span>Versión {item.version}</span>
                <div>
                  <button
                    type="button"
                    className="icon-button"
                    onClick={() => exportMarkdown(item)}
                    aria-label={`Descargar ${item.name}`}
                    title="Descargar como Markdown"
                  >
                    <ArrowDownToLine size={17} aria-hidden />
                  </button>
                  <button
                    type="button"
                    className="icon-button"
                    onClick={() => open(item, 'profile')}
                    aria-label={`Editar ${item.name}`}
                    title="Editar"
                  >
                    <Pencil size={17} aria-hidden />
                  </button>
                </div>
              </div>
            </article>
          ))}
        </div>
      ) : (
        <EmptyState title="Sin evaluadores">
          Agregá al menos un evaluador (se escribe en Markdown) para poder preparar una sesión.
        </EmptyState>
      )}
      <div className="subsection-heading subsection-heading--spaced">
        <h3>Rúbricas</h3>
        <Button variant="secondary" onClick={() => open(null, 'rubric')}>
          <Plus size={16} aria-hidden /> Nueva rúbrica
        </Button>
      </div>
      {currentRubrics.length ? (
        <div className="rubric-list">
          {currentRubrics.map((item) => (
            <article className="rubric-card" key={item.rubric_id}>
              <div>
                <span className="eyebrow">RÚBRICA / VERSIÓN {item.version}</span>
                <h4>{item.name}</h4>
                <p>
                  {item.criteria.length} criterios: {item.criteria.map((c) => c.title).join(', ')}
                </p>
              </div>
              <div>
                <button
                  type="button"
                  className="icon-button"
                  onClick={() => exportMarkdown(item)}
                  aria-label={`Descargar ${item.name}`}
                  title="Descargar como Markdown"
                >
                  <ArrowDownToLine size={17} aria-hidden />
                </button>
                <Button variant="ghost" onClick={() => open(item, 'rubric')}>
                  <Pencil size={15} aria-hidden /> Editar
                </Button>
              </div>
            </article>
          ))}
        </div>
      ) : (
        <EmptyState title="Sin rúbrica">
          Definí los criterios observables que ordenarán el informe.
        </EmptyState>
      )}
      {editorOpen ? (
        <div
          className="modal-backdrop"
          onMouseDown={(event) => {
            if (event.target === event.currentTarget) requestClose()
          }}
        >
          <div
            ref={dialogRef}
            className="modal modal--editor"
            role="dialog"
            aria-modal="true"
            aria-labelledby="config-title"
            tabIndex={-1}
          >
            <div className="modal__head">
              <div>
                <p className="eyebrow">
                  {type === 'profile' ? 'EVALUADOR' : 'CRITERIOS DE EVALUACIÓN'}
                </p>
                <h2 id="config-title">
                  {selected ? `Editar “${selected.name}”` : `Crear ${noun}`}
                </h2>
              </div>
              <button
                type="button"
                data-dialog-initial-focus
                className="icon-button"
                onClick={requestClose}
                aria-label="Cerrar"
              >
                <X size={21} aria-hidden />
              </button>
            </div>
            <p className="editor-help">
              {type === 'profile'
                ? 'Un perfil de evaluador es un archivo Markdown con un bloque inicial YAML (entre líneas “---”) y el texto que lo describe.'
                : 'Una rúbrica es un archivo Markdown con un bloque inicial YAML (entre líneas “---”) que lista los criterios, y un texto de guía.'}{' '}
              {selected
                ? `Al guardar se crea la versión ${selected.version + 1}; las sesiones ya iniciadas conservan la que usaron.`
                : 'Al guardar se crea la primera versión.'}
            </p>
            <div className="editor-toolbar">
              <Tabs<EditorTab>
                className="segmented"
                label="Modo del editor"
                idPrefix={EDITOR_TABS}
                value={tab}
                onChange={setTab}
                items={[
                  { id: 'edit', label: 'Editar' },
                  { id: 'preview', label: 'Vista previa' },
                ]}
              />
              <div className="editor-toolbar__actions">
                {!markdown.trim() ? (
                  <button
                    type="button"
                    className="text-link"
                    onClick={() => {
                      setMarkdown(
                        type === 'profile'
                          ? profileTemplate(currentProfiles, currentRubrics)
                          : rubricTemplate(currentRubrics),
                      )
                      setTab('edit')
                    }}
                  >
                    <FilePlus2 size={16} aria-hidden /> Insertar plantilla
                  </button>
                ) : null}
                <button
                  type="button"
                  className="text-link"
                  onClick={() => fileRef.current?.click()}
                >
                  <FileUp size={16} aria-hidden /> Importar .md
                </button>
              </div>
              <input
                className="sr-only"
                type="file"
                tabIndex={-1}
                aria-label="Importar archivo Markdown"
                accept=".md,text/markdown"
                ref={fileRef}
                onChange={(event) => {
                  const file = event.target.files?.[0]
                  event.target.value = ''
                  void importFile(file)
                }}
              />
            </div>
            {tab === 'edit' ? (
              <TabPanel idPrefix={EDITOR_TABS} id="edit" focusable={false}>
                <Label htmlFor="markdown-input">Markdown</Label>
                <textarea
                  id="markdown-input"
                  className="markdown-input"
                  value={markdown}
                  onChange={(event) => setMarkdown(event.target.value)}
                  rows={20}
                  placeholder={
                    '---\nid: mi-evaluador\nname: Mi evaluador\n...\n---\n## Cómo interviene\n\n¿No sabés cómo empezar? Usá “Insertar plantilla”.'
                  }
                />
              </TabPanel>
            ) : (
              <TabPanel idPrefix={EDITOR_TABS} id="preview">
                <div className="markdown-preview">
                  {markdown.trim() ? (
                    <ReactMarkdown remarkPlugins={[remarkGfm]}>{markdown}</ReactMarkdown>
                  ) : (
                    <p className="muted">Todavía no hay nada para mostrar.</p>
                  )}
                </div>
              </TabPanel>
            )}
            <ErrorNotice error={fileError || save.error} />
            {!markdown.trim() ? (
              <p className="field-note" id="config-save-hint">
                Escribí, importá o insertá una plantilla para poder guardar.
              </p>
            ) : null}
            <div className="modal__actions">
              <Button type="button" variant="ghost" onClick={requestClose}>
                Cancelar
              </Button>
              <Button
                type="button"
                disabled={!markdown.trim()}
                loading={save.isPending}
                aria-describedby={!markdown.trim() ? 'config-save-hint' : undefined}
                onClick={() => {
                  if (!save.isPending) save.mutate()
                }}
              >
                <Save size={17} aria-hidden /> Guardar versión
              </Button>
            </div>
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
          <p>Tenés cambios sin guardar. Si cerrás ahora, se pierde lo que escribiste.</p>
        </ConfirmDialog>
      ) : null}
    </div>
  )
}
