# 05 — Agente de razonamiento cíclico con memoria persistente

Pre-entrega 5. Un agente ReAct construido con LangGraph: decide solo qué herramienta usar,
encadena varias llamadas para resolver una pregunta, se recupera de los errores que devuelven
las herramientas y recuerda la conversación entre turnos gracias a un checkpointer en SQLite.

## Archivos

| Archivo | Contenido |
|---|---|
| `tools.py` | Tres herramientas `@tool` sobre una base de pedidos simulada. |
| `agent.py` | El `StateGraph` (nodo modelo + `ToolNode` + arista condicional), `bind_tools`, el `AsyncSqliteSaver` y el `recursion_limit`. |
| `main.py` | Prueba de ejecución: dos hilos, uno multi-paso con memoria y otro que fuerza un error de herramienta. Genera las trazas. |
| `trazas/` | Trazas ReAct de ejemplo en JSON. |

## Cómo levantarlo

Requiere **Python 3.12**.

```bash
python -m venv .venv
.venv\Scripts\activate          # Windows  (Linux/macOS: source .venv/bin/activate)
pip install -r requirements.txt
copy .env.example .env          # Linux/macOS: cp .env.example .env
python main.py
```

Variables de entorno: `LLM_PROVIDER` (`openai` o `anthropic`) y la clave del proveedor
elegido. `checkpoints.sqlite` se crea solo y está en el `.gitignore`.

## El grafo

```
START ──> modelo ──(tools_condition)──> herramientas ──┐
             ▲                              │          │
             └──────────────────────────────┘          ▼
                                                      END
```

`tools_condition` mira el último mensaje del modelo: si trae `tool_calls`, va al nodo de
herramientas; si no, termina. El nodo de herramientas siempre vuelve al modelo, y ahí se cierra
el ciclo. **No hay ningún `if/else` que enrute**: el modelo decide, y `bind_tools()` es lo que
le da esa capacidad.

El estado hereda de `MessagesState`, cuyo reducer (`add_messages`) acumula los mensajes en
lugar de reemplazarlos. Por eso el segundo turno de una conversación llega con todo el
historial anterior.

## Las tres herramientas

| Herramienta | Qué hace |
|---|---|
| `buscar_cliente(nombre)` | Nombre → ID. Devuelve error si no encuentra a nadie, o si hay varias coincidencias. |
| `buscar_pedidos(cliente_id)` | Pedidos, cantidad y total de un cliente. **Pide el ID, no el nombre.** |
| `detalle_pedido(pedido_id)` | Detalle completo de un pedido puntual. |

El diseño fuerza el razonamiento multi-paso: el usuario pregunta por nombre, pero
`buscar_pedidos` sólo acepta un ID. El agente tiene que resolver primero el nombre y recién
después consultar los pedidos. No hay atajo de una sola llamada.

Los docstrings son largos a propósito. El modelo elige la herramienta leyendo **sólo** esa
descripción: cuando el agente elige mal, el problema casi siempre está ahí y no en el grafo.
Por eso cada docstring dice explícitamente qué devuelve, qué formato tiene el error y qué
hacer cuando aparece.

## Traza de ejemplo

`trazas/traza-soporte-001.json` — el ciclo ReAct completo, con dos turnos en el mismo hilo:

```
Usuario: ¿Cuántos pedidos tuvo Bruno y cuál fue el total?
  -> el agente decide llamar: buscar_cliente({'nombre': 'Bruno'})
  <- devolvió: {"cliente_id": 102, "nombre": "Bruno Salas"}
  -> el agente decide llamar: buscar_pedidos({'cliente_id': 102})
  <- devolvió: {"cliente_id": 102, "cantidad": 3, "total": 14500, ...}
Agente: Bruno Salas tuvo 3 pedidos por un total de $14.500.

Usuario: ¿Y cuál fue el último? Dame el detalle completo.
  -> el agente decide llamar: detalle_pedido({'pedido_id': 5031})
  <- devolvió: {"pedido_id": 5031, "fecha": "2024-03-08", ...}
Agente: El último fue el 5031 del 2024-03-08 por $2.100, pendiente, vía Andreani.

[3 llamadas a herramientas, 10 mensajes en el estado]
```

El segundo turno es la prueba de memoria: el `pedido_id` 5031 nunca lo dijo el usuario. El
agente lo sacó del resultado de `buscar_pedidos` del turno anterior, que seguía en el estado
porque el `thread_id` era el mismo.

`trazas/traza-soporte-002.json` muestra el ciclo de retorno: `buscar_cliente("a")` devuelve un
error de ambigüedad con las coincidencias, y el agente repregunta en vez de adivinar.

> Las trazas incluidas se generaron con el grafo, las herramientas y el checkpointer reales,
> pero con las decisiones del modelo guionadas (sin llamada a la API). Regeneralas con
> `python main.py` y tus claves para tener una traza de una corrida real.

## Criterios de aceptación

| Criterio | Cómo se cumple |
|---|---|
| Autonomía, sin `if/else` manuales | `bind_tools()` + `tools_condition`; el modelo elige |
| Ciclo de retorno ante error | Las herramientas devuelven errores estructurados y el prompt de sistema instruye a leerlos; el hilo `soporte-002` lo demuestra |
| Resiliencia de estado con `thread_id` | `AsyncSqliteSaver`; verificado reabriendo la base y recuperando los 10 mensajes del hilo |
| Python 3.12, tipado y `asyncio` | Type hints en todo, nodo del modelo `async`, `ainvoke`, `AsyncSqliteSaver` |
| Herramienta invocada ≥2 veces | 3 llamadas en `soporte-001` |
| `recursion_limit` definido | `RECURSION_LIMIT = 10`, pasado en cada invocación |

## Detalles de implementación

**Checkpointer asíncrono.** Se usa `AsyncSqliteSaver` y no `SqliteSaver`: el nodo del modelo es
una corrutina, así que el checkpointer también tiene que serlo para no bloquear el event loop.
`from_conn_string` es un context manager asíncrono, por eso `agente()` está envuelto en
`@asynccontextmanager`.

**El prompt de sistema no vive en el estado.** Se antepone en cada llamada al modelo
(`[PROMPT_SISTEMA, *state["messages"]]`) en lugar de guardarse como primer mensaje. Así no se
duplica al acumularse los turnos ni ocupa lugar en el historial persistido.

**Sobre el estado sucio.** El estado crece con cada turno y este agente no lo poda: para una
sesión larga habría que resumir o recortar los mensajes viejos antes de que el contexto se
vuelva caro. Está fuera del alcance de esta entrega, pero es el siguiente paso obvio.
