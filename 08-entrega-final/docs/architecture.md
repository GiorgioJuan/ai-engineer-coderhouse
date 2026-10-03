# Arquitectura implementada

El [README](../README.md) muestra el diagrama de servicios, el grafo de agentes generado desde el
código y el recorrido de un turno. Este documento profundiza en las decisiones de diseño.

## Servicios

Compose levanta `web`, `api`, `worker`, `redis` y `phoenix` (más `redis-test`, sólo con el perfil
`test`). La web (Nginx) publica el puerto 8080 y reenvía `/api` a FastAPI re-resolviendo el nombre
`api` con el DNS de Docker, de modo que recrear la API no deja a Nginx apuntando a una IP vieja.
Phoenix publica el 6007. API y worker comparten una imagen Python 3.12 con dependencias fijadas en
`backend/requirements.lock`.

Redis Stack conserva documentos y sus versiones, perfiles, rúbricas, sesiones, informes, trabajos,
comandos, fragmentos indexados, el ledger de presupuesto y los checkpoints de LangGraph, en un
volumen con AOF.

## Comandos asíncronos

Los comandos de larga duración (indexar un documento, iniciar sesión, responder, finalizar) se
aceptan con `202` y un `job_id`. La API escribe en una transacción Redis el comando, el trabajo, el
registro de idempotencia y el cambio de estado de la entidad, y lo encola en un **Redis Stream**.
El worker es un consumidor de un grupo: recupera mensajes propios pendientes y, con `XAUTOCLAIM`,
los que quedaron colgados de un worker anterior. Marca el trabajo `RUNNING`, ejecuta el grafo y lo
deja en `SUCCEEDED` o `FAILED` con un error clasificado:

| Tipo de falla | Ejemplos | ¿Reintentable? |
| --- | --- | --- |
| Transitoria | caída de red, 429 por velocidad, 5xx, Redis momentáneamente caído, salida inválida del modelo | Sí, hasta 3 intentos |
| Permanente | clave inválida (401/403), falta de crédito, presupuesto agotado, estado de sesión inválido | No |

Un reintento conserva el identificador lógico del comando: si la respuesta ya se había aplicado al
checkpoint, no se aplica dos veces.

## Sesiones, snapshot y pausa humana

Crear una sesión congela un **snapshot** de versiones: perfiles, rúbrica, documentos listos y, si se
indica, la sesión anterior a comparar. Editar un documento o un perfil después crea una versión
nueva sin alterar sesiones existentes ni sus citas.

Cada sesión es un hilo de LangGraph con `thread_id = panellab:<session_id>` en `AsyncRedisSaver`.
El nodo `wait` llama a `interrupt()`: el estado queda persistido y el worker queda libre. Al llegar
una respuesta, la API valida `question_id` y `expected_revision`, y el worker reanuda con
`Command(resume=...)`. La API proyecta del checkpoint el estado, la pregunta pendiente y el
transcript para `GET /sessions/{id}`.

## Herramientas y control del modelo

El modelo nunca decide sobre lo que no puede verificarse:

- El supervisor elige entre los pares evaluador/criterio que calcula `evaluar_cobertura`; si propone
  uno inválido o intenta cerrar antes de la primera ronda, se toma el primer par válido.
- `buscar_evidencia` recibe del modelo sólo la consulta; el proyecto y las versiones permitidas los
  fija el servidor al construir la herramienta.
- Los IDs de fragmentos que el evaluador puede citar se restringen con un `enum` a los recuperados
  en ese turno; el informe anterior le llega sin sus citas. Luego `verificar_cita` comprueba cada
  cita contra el texto almacenado.
- La valoración pasa por una calibración determinista: un plan citado nunca cuenta como resultado
  ejecutado, y una afirmación sin respaldo documental queda como `partial`.

## Recuperación

Los documentos se fragmentan por sección y por página (para PDF) antes de cortar por tamaño
(900 caracteres, 120 de solapamiento), de modo que un fragmento no mezcla atribuciones. Cada
fragmento guarda proyecto, documento, versión, sección, texto y embedding. La búsqueda combina una
consulta léxica y una KNN vectorial en Redis Search con Reciprocal Rank Fusion (k = 60), siempre
filtrada por proyecto y por las versiones del snapshot. El índice registra el modelo y la dimensión
de sus embeddings: no se pueden mezclar vectores demo y live en el mismo índice.

## Modelo y presupuesto

`PANEL_LLM_MODE=demo` usa decisiones deterministas y vectores calculados localmente. `live` usa
`httpx.AsyncClient` contra una API compatible con OpenAI, con salida estructurada estricta y una
tabla de modelos con tarifa verificada. Antes de cada llamada se **reserva** en Redis el costo
máximo posible (script Lua atómico) y después se liquida con el uso real informado; una llamada que
el proveedor rechaza libera su reserva. El techo se configura con `PANEL_BUDGET_CAP_USD`.

## Observabilidad

Spans OTLP hacia Phoenix con convenciones OpenInference: uno por comando HTTP en la API
(`POST /api/sessions/{session_id}/responses`, etc.; las lecturas de polling no se trazan);
`panellab.command` (`CHAIN`) por comando del worker, con lo que aportó la persona y lo que
devolvió el panel como `input.value`/`output.value` (Phoenix los muestra en la vista Sessions); `graph.node.*` (`CHAIN`) por nodo; `tool.*` (`TOOL`) con
argumentos y salida; `panellab.rag.search` (`RETRIEVER`) con los documentos devueltos; `llm.*`
(`LLM`) con mensajes, parámetros, tokens y costo; `embedding` (`EMBEDDING`). Todos llevan
`session.id`. La clave del proveedor nunca se registra; el contenido se puede omitir con
`PANEL_TRACE_CONTENT=false`. Si Phoenix no está disponible, la API informa `degraded` en readiness
y sigue funcionando.

## Límites

- 30 documentos por proyecto, 200 KB por documento y 1 MB de fuentes por proyecto.
- PDF con texto: 10 MiB y 50 páginas, extraído en un proceso aparte con timeout de 15 s.
- Una sesión: de 1 a 5 evaluadores y de 3 a 5 preguntas (al menos una por evaluador).
- Uso local sin autenticación; un worker.
