# Revisión heurística de la interfaz

Revisión basada en las [10 heurísticas de usabilidad de Nielsen Norman Group](https://www.nngroup.com/articles/ten-usability-heuristics/)
y en WCAG 2.2 AA. Se hizo con inspección del código, capturas de página completa a 1440 y 390 px
y pruebas automatizadas; no hubo pruebas con usuarios. Se mantuvo el lenguaje visual (crema, verde,
tipografía editorial).

## Cambios por heurística

| Heurística | Problema encontrado | Cambio aplicado |
| --- | --- | --- |
| 1. Visibilidad del estado del sistema | La sala decía sólo "en cola" mientras el panel trabajaba; las listas mostraban "vacío" y contadores "00" mientras cargaban; un proyecto inexistente quedaba en "Cargando…" para siempre. | Estado de procesamiento con lo que está haciendo el panel y tiempo transcurrido (`aria-live`); estados de carga y de "no encontrado" explícitos; aviso global si el servidor no responde; foco y scroll a la pregunta nueva. |
| 2. Relación con el mundo real | Errores del backend en inglés técnico ("project not found", excepciones crudas); IDs, UUID y valores internos (`source`, `supported`) a la vista. | Mapa central de errores a español llano con el siguiente paso; detalle técnico plegado. Etiquetas humanas para todo valor interno; títulos en lugar de IDs. |
| 3. Control y libertad | "Finalizar" cerraba la sesión sin confirmación, pegado a "Enviar"; Esc o un clic afuera descartaban textos pegados; no había forma de quitar un proyecto. | "Terminar y ver informe" como acción secundaria con confirmación; aviso de cambios sin guardar; **archivar y restaurar proyectos** con "Deshacer". Borradores conservados por pestaña. |
| 4. Consistencia y estándares | Mezcla de material/fuente/documento, evaluador/perfil, revisión/sesión; ícono de enlace externo en acciones de guardar. | Glosario único (Materiales, Evaluadores, Sesión, Informe); íconos acordes a cada acción; pestañas con semántica ARIA y navegación con flechas. |
| 5. Prevención de errores | El botón de iniciar quedaba inactivo sin explicar por qué; subir el máximo de preguntas al sumar evaluadores era silencioso; validación nativa en el idioma del navegador. | Lista concreta de lo que falta para iniciar; aviso del ajuste automático; motivo visible de cada opción deshabilitada; validación propia en español junto al campo. |
| 6. Reconocer antes que recordar | Las citas decían "Fuente 1"; el criterio en foco se mostraba como ID; el nombre del evaluador en 10 px. | Citas con documento y sección; el panel resalta el fragmento dentro del original; quién pregunta, su rol y el criterio en primer plano; "Pregunta n de m". |
| 7. Flexibilidad y eficiencia | Sin atajos ni recorrido rápido. | Proyectos ordenados por actividad reciente; atajos de teclado documentados; plantilla insertable para perfiles y rúbricas. |
| 8. Estética y diseño minimalista | Pseudo paso a paso decorativo en la portada; conversación en un recuadro de altura fija con un hueco vacío; "lectura general" sin información. | Portada con tres pasos reales; la conversación fluye con la página; resumen del informe por estado y criterios a reforzar. |
| 9. Reconocer, diagnosticar y recuperarse de errores | Un trabajo fallido sin salida; "Reintentar trabajo" (jerga). | Siempre hay "Reintentar" (si tiene sentido) y "Volver al proyecto"; los errores permanentes (clave inválida, sin crédito) se explican sin ofrecer un reintento inútil. |
| 10. Ayuda y documentación | El ícono "?" sólo llevaba a Proyectos; la insignia "API REAL" era jerga. | Página **¿Cómo funciona?** con el recorrido, qué hace la IA, el modo demostración y atajos; insignia "Modo demostración" / "IA en vivo" con explicación. |

## Accesibilidad (WCAG 2.2 AA)

- Contraste: todos los pares de texto medidos superan 4,5:1 y los bordes de controles 3:1 (antes
  había textos secundarios de 1,5–3,5:1 y bordes de campos de 1,5:1). Tamaño mínimo de texto 12 px.
- Diálogos con foco atrapado, cierre con Esc y retorno del foco al control que los abrió.
- Regiones `aria-live` para el estado del panel y los cambios de estado de los materiales; `role="status"`
  en las cargas; título del documento por ruta; enlace para saltar al contenido.
- Objetivos táctiles de 44 px en pantallas chicas y sin desplazamiento horizontal a 375–390 px.
- `prefers-reduced-motion` respetado en las animaciones y el scroll automático.

## Verificación

- 88 pruebas de frontend (mapeo de errores, confirmación de cierre, ayuda, estados de carga y de
  "no encontrado", foco al llegar una pregunta, scroll al turno citado, archivado).
- `npm run typecheck`, `npm run build` y `prettier --check` sin errores.
- Capturas de página completa en [evidence/screenshots](../evidence/screenshots).
