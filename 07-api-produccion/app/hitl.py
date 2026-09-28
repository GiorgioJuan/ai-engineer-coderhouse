"""Human-in-the-loop: pausa el grafo antes de una accion con efectos secundarios.

`interrupt()` de LangGraph corta la ejecucion en el medio del nodo y devuelve el control
al llamador. El estado queda guardado en el checkpointer (Redis), asi que el proceso
puede morirse y la aprobacion sigue siendo posible despues.

Se reanuda con `Command(resume=...)`: el valor que se pasa ahi es exactamente lo que
devuelve `interrupt()` cuando el nodo se vuelve a ejecutar.
"""

from typing import Any

from langchain_core.tools import tool
from langgraph.types import interrupt

from app.config import UMBRAL_COSTO_CRITICO

# Catalogo de acciones con efectos secundarios y su costo estimado.
_ACCIONES: dict[str, dict[str, Any]] = {
    "escalar_infraestructura": {
        "descripcion": "Duplicar las instancias del servicio para bajar la latencia.",
        "costo_estimado_usd": 4800,
        "reversible": True,
    },
    "purgar_cache": {
        "descripcion": "Vaciar la cache de Redis del servicio.",
        "costo_estimado_usd": 0,
        "reversible": False,
    },
    "reindexar_busqueda": {
        "descripcion": "Reconstruir el indice vectorial completo.",
        "costo_estimado_usd": 1200,
        "reversible": True,
    },
}


def es_critica(accion: str) -> bool:
    """Una accion es critica si es cara o si no se puede deshacer."""
    meta = _ACCIONES.get(accion)
    if meta is None:
        return True  # lo desconocido se trata como critico
    return meta["costo_estimado_usd"] >= UMBRAL_COSTO_CRITICO or not meta["reversible"]


def describir(accion: str) -> dict[str, Any]:
    meta = _ACCIONES.get(accion, {"descripcion": "Accion desconocida", "costo_estimado_usd": None})
    return {"accion": accion, **meta, "critica": es_critica(accion)}


def solicitar_aprobacion(accion: str, justificacion: str) -> dict[str, Any]:
    """Pausa el grafo. Lo que se devuelve aca es lo que ve el humano en la API."""
    return interrupt(
        {
            "tipo": "aprobacion_requerida",
            "justificacion": justificacion,
            **describir(accion),
        }
    )


@tool
def ejecutar_accion(accion: str) -> dict[str, Any]:
    """Ejecuta una acción de infraestructura ya aprobada.

    Acciones válidas: escalar_infraestructura, purgar_cache, reindexar_busqueda.
    Devuelve {"ejecutada": bool, "accion": str, "detalle": str}.
    """
    if accion not in _ACCIONES:
        return {"ejecutada": False, "accion": accion, "detalle": "Acción desconocida."}
    return {
        "ejecutada": True,
        "accion": accion,
        "detalle": f"{_ACCIONES[accion]['descripcion']} Aplicada correctamente.",
    }
