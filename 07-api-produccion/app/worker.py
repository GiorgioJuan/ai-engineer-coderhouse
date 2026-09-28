"""Worker: corre el grafo en segundo plano y refleja el estado en Redis.

El endpoint no espera al agente. Encola una `asyncio.Task` y contesta enseguida con el
job_id; el worker va escribiendo PENDING -> RUNNING -> (WAITING_APPROVAL) -> DONE.

La regla que sostiene todo el polling del cliente: **ninguna excepcion puede quedar sin
escribirse**. Si el agente explota, el job pasa a FAILED con el motivo. Si no, el cliente
se queda pollleando para siempre un job que ya murio.
"""

import asyncio
import logging
from typing import Any

from langchain_core.messages import HumanMessage
from langgraph.types import Command

from app.config import RECURSION_LIMIT
from app.schemas import EstadoJob
from app.store import JobStore

logger = logging.getLogger("api.worker")

# Referencias fuertes a las tareas en vuelo: sin esto el GC puede matarlas.
_EN_VUELO: set[asyncio.Task[None]] = set()


def _config(job_id: str) -> dict[str, Any]:
    """El job_id es tambien el thread_id del checkpointer: un job, un hilo de estado."""
    return {
        "configurable": {"thread_id": job_id},
        "recursion_limit": RECURSION_LIMIT,
    }


def _interrupcion(resultado: dict[str, Any]) -> dict[str, Any] | None:
    """Devuelve el payload del interrupt() si el grafo quedo pausado."""
    interrupciones = resultado.get("__interrupt__")
    if not interrupciones:
        return None
    valor = interrupciones[0].value
    return valor if isinstance(valor, dict) else {"detalle": str(valor)}


async def _volcar_estado(store: JobStore, job_id: str, resultado: dict[str, Any]) -> None:
    """Traduce el estado del grafo al estado del job."""
    pendiente = _interrupcion(resultado)
    contribuciones = resultado.get("contribuciones", [])

    if pendiente is not None:
        await store.actualizar(
            job_id,
            estado=EstadoJob.WAITING_APPROVAL,
            aprobacion_pendiente=pendiente,
            contribuciones=contribuciones,
            pasos=resultado.get("pasos", 0),
        )
        logger.info("Job %s pausado esperando aprobacion: %s", job_id, pendiente.get("accion"))
        return

    mensajes = resultado.get("messages", [])
    final = str(mensajes[-1].content) if mensajes else ""
    rechazada = str(resultado.get("accion_resultado", "")).startswith("RECHAZADA")

    await store.actualizar(
        job_id,
        estado=EstadoJob.REJECTED if rechazada else EstadoJob.DONE,
        resultado=final,
        aprobacion_pendiente=None,
        contribuciones=contribuciones,
        pasos=resultado.get("pasos", 0),
    )
    logger.info("Job %s terminado (%d pasos)", job_id, resultado.get("pasos", 0))


async def ejecutar_job(grafo: Any, store: JobStore, job_id: str, consulta: str) -> None:
    """Corrida inicial del grafo. Nunca propaga excepciones."""
    try:
        await store.actualizar(job_id, estado=EstadoJob.RUNNING)
        entrada = {
            "messages": [HumanMessage(content=consulta)],
            "contribuciones": [],
            "pasos": 0,
        }
        resultado = await grafo.ainvoke(entrada, _config(job_id))
        await _volcar_estado(store, job_id, resultado)

    except asyncio.CancelledError:
        await store.actualizar(job_id, estado=EstadoJob.FAILED, error="Cancelado.")
        raise
    except Exception as exc:
        logger.exception("Job %s fallo", job_id)
        await store.actualizar(
            job_id, estado=EstadoJob.FAILED, error=f"{type(exc).__name__}: {exc}"
        )


async def reanudar_job(
    grafo: Any, store: JobStore, job_id: str, aprobado: bool, comentario: str
) -> None:
    """Reanuda un grafo pausado. `resume` es lo que devuelve interrupt() en el nodo."""
    try:
        await store.actualizar(job_id, estado=EstadoJob.RUNNING, aprobacion_pendiente=None)
        resultado = await grafo.ainvoke(
            Command(resume={"aprobado": aprobado, "comentario": comentario}),
            _config(job_id),
        )
        await _volcar_estado(store, job_id, resultado)

    except asyncio.CancelledError:
        await store.actualizar(job_id, estado=EstadoJob.FAILED, error="Cancelado.")
        raise
    except Exception as exc:
        logger.exception("La reanudacion del job %s fallo", job_id)
        await store.actualizar(
            job_id, estado=EstadoJob.FAILED, error=f"{type(exc).__name__}: {exc}"
        )


def lanzar(corrutina: Any) -> asyncio.Task[None]:
    """Encola la corrutina y le guarda una referencia hasta que termine."""
    tarea = asyncio.create_task(corrutina)
    _EN_VUELO.add(tarea)
    tarea.add_done_callback(_EN_VUELO.discard)
    return tarea
