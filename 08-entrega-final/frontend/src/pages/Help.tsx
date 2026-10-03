import { ArrowRight } from 'lucide-react'
import { Link } from 'react-router-dom'
import { AppShell } from '../components/AppShell'
import { useDocumentTitle, useScrollToHash } from '../hooks/usePageHelpers'

const steps = [
  {
    title: 'Cargá tus materiales',
    text: 'Subí o pegá los documentos del proyecto: el brief, los avances, la consigna. Aceptamos PDF, Markdown y texto. Esperá a que cada material figure como “Listo”.',
  },
  {
    title: 'Elegí evaluadores y rúbrica',
    text: 'Cada evaluador mira tu proyecto desde una perspectiva distinta, y la rúbrica define qué criterios se revisan. Podés usar los que vienen cargados o editarlos.',
  },
  {
    title: 'Preparé la sesión',
    text: 'Escribí el objetivo, pegá tu presentación inicial y elegí entre 1 y 5 evaluadores y entre 3 y 5 preguntas como máximo.',
  },
  {
    title: 'Respondé al panel',
    text: 'El panel pregunta de a una cosa por vez. Cuando una pregunta cita tus materiales, podés abrir la cita para ver el fragmento original. Si ya viste lo que necesitabas, podés terminar antes.',
  },
  {
    title: 'Leé el informe',
    text: 'Para cada criterio de la rúbrica vas a ver qué quedó sustentado, qué falta y qué conviene hacer después. Podés imprimirlo o guardarlo como PDF.',
  },
]

const shortcuts: Array<[string, string]> = [
  ['Ctrl / ⌘ + Enter', 'Envía tu respuesta desde el cuadro de texto.'],
  ['Esc', 'Cierra ventanas y paneles. Si hay cambios sin guardar, te preguntamos antes.'],
  [
    'Tab / Shift + Tab',
    'Avanza o retrocede entre los controles. El primer Tab ofrece “Saltar al contenido”.',
  ],
  [
    '← →',
    'Cambian de pestaña en las secciones del proyecto (Materiales, Evaluadores y rúbricas, Sesiones).',
  ],
]

const glossary: Array<[string, string]> = [
  ['Materiales', 'Los documentos que cargás. Cada material puede tener varias versiones.'],
  [
    'Evaluadores',
    'Las personas ficticias del panel; cada una tiene su rol y su forma de preguntar.',
  ],
  ['Rúbrica', 'La lista de criterios que se revisan en la sesión.'],
  ['Sesión', 'Un ensayo: una conversación con el panel sobre un objetivo concreto.'],
  ['Informe', 'El resultado de una sesión, criterio por criterio.'],
]

export function Help() {
  useDocumentTitle('¿Cómo funciona?')
  useScrollToHash(true)
  return (
    <AppShell back={{ to: '/', label: 'Mis proyectos' }} eyebrow="Ayuda">
      <div className="page-wrap help-page">
        <div className="page-kicker">
          <span className="kicker-dot" /> AYUDA <span className="kicker-line" />
        </div>
        <header className="help-head">
          <p className="eyebrow">Guía rápida</p>
          <h1>
            ¿Cómo funciona <em>PanelLab</em>?
          </h1>
          <p className="help-lead">
            PanelLab te deja ensayar la presentación de un proyecto frente a un panel de evaluadores
            que lee tus documentos, te hace preguntas y, al final, te entrega un informe. En cinco
            pasos:
          </p>
        </header>

        <ol className="help-steps">
          {steps.map((step, index) => (
            <li key={step.title}>
              <span className="help-steps__number" aria-hidden>
                {String(index + 1).padStart(2, '0')}
              </span>
              <div>
                <h2>{step.title}</h2>
                <p>{step.text}</p>
              </div>
            </li>
          ))}
        </ol>

        <div className="help-grid">
          <section className="help-card" aria-labelledby="help-ia">
            <p className="eyebrow">Por dentro</p>
            <h2 id="help-ia">Qué hace la IA</h2>
            <ul>
              <li>
                Un supervisor decide qué evaluador pregunta en cada turno y sobre qué criterio.
              </li>
              <li>Las preguntas se apoyan en tus materiales y citan los fragmentos que usaron.</li>
              <li>
                No hay nota numérica: el informe describe la evidencia y el criterio final es tuyo.
              </li>
              <li>
                Podés cerrar la pestaña y volver cuando quieras: la sesión se guarda y sigue donde
                la dejaste.
              </li>
            </ul>
          </section>

          <section className="help-card" id="modo-demostracion" aria-labelledby="help-demo">
            <p className="eyebrow">Etiqueta del encabezado</p>
            <h2 id="help-demo">Modo demostración e IA en vivo</h2>
            <p>
              Si ves <strong>Modo demostración</strong>, las respuestas del panel son de ejemplo: no
              hay conexión con un modelo de IA ni costo, y sirve para recorrer la herramienta con un
              caso ficticio.
            </p>
            <p>
              Con <strong>IA en vivo</strong>, las preguntas las genera un modelo a partir de tus
              materiales y cada una puede tardar entre 5 y 40 segundos.
            </p>
          </section>
        </div>

        <section className="help-block" aria-labelledby="help-keys">
          <h2 id="help-keys">Atajos de teclado</h2>
          <dl className="help-list">
            {shortcuts.map(([keys, text]) => (
              <div key={keys}>
                <dt>
                  <kbd>{keys}</kbd>
                </dt>
                <dd>{text}</dd>
              </div>
            ))}
          </dl>
        </section>

        <section className="help-block" aria-labelledby="help-glossary">
          <h2 id="help-glossary">Palabras que usamos</h2>
          <dl className="help-list">
            {glossary.map(([term, text]) => (
              <div key={term}>
                <dt>{term}</dt>
                <dd>{text}</dd>
              </div>
            ))}
          </dl>
        </section>

        <div className="help-cta">
          <p>¿Listo para empezar?</p>
          <Link className="button button--primary" to="/">
            Ir a mis proyectos <ArrowRight size={17} aria-hidden />
          </Link>
        </div>
      </div>
    </AppShell>
  )
}
