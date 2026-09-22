"""Agente investigador: recupera datos de la base de conocimiento y de metricas.

Herramientas acotadas a su dominio: sabe BUSCAR, no sabe calcular. Si le piden una
cuenta, tiene que devolver los datos crudos para que los procese el analista. Esa
separacion es lo que hace que la delegacion tenga sentido.
"""

from typing import Any

from langchain_core.language_models import BaseChatModel
from langchain_core.tools import tool
from langgraph.prebuilt import create_react_agent

# --- Base de conocimiento simulada (haria de Vector DB) --------------------

_DOCS: dict[str, str] = {
    "sla-latencia": (
        "El acuerdo de nivel de servicio vigente fija un p95 de latencia de 300 ms para "
        "todos los servicios de cara al usuario. Por encima de ese umbral se considera "
        "incumplimiento y dispara una revision de arquitectura."
    ),
    "arquitectura-checkout": (
        "El servicio de checkout corre sobre FastAPI, cachea en Redis y persiste en "
        "PostgreSQL. El pool de conexiones esta configurado en 100."
    ),
    "arquitectura-busqueda": (
        "El servicio de busqueda consulta un indice vectorial y agrega resultados de "
        "BM25. Cada consulta hace dos llamadas de red en serie."
    ),
}

_METRICAS: dict[str, list[int]] = {
    "checkout": [180, 210, 195, 240, 205, 190, 260, 215, 198, 230],
    "busqueda": [320, 410, 380, 520, 360, 395, 610, 340, 370, 450],
    "perfil": [90, 110, 95, 105, 88, 120, 99, 101, 93, 115],
}


@tool
def buscar_documentacion(consulta: str) -> dict[str, Any]:
    """Busca en la documentación interna de arquitectura y de acuerdos de servicio.

    Usala para responder preguntas sobre cómo funciona un servicio, o sobre cuáles son
    los umbrales y acuerdos vigentes (por ejemplo el SLA de latencia).

    Devuelve {"resultados": [{"doc_id": str, "texto": str}]} con las coincidencias.
    Si no encuentra nada devuelve {"resultados": [], "doc_ids_disponibles": [...]}.
    """
    q = consulta.lower()
    hits = [
        {"doc_id": k, "texto": v}
        for k, v in _DOCS.items()
        if any(t in k.lower() or t in v.lower() for t in q.split() if len(t) > 3)
    ]
    if not hits:
        return {"resultados": [], "doc_ids_disponibles": list(_DOCS)}
    return {"resultados": hits}


@tool
def obtener_metricas(servicio: str) -> dict[str, Any]:
    """Devuelve las últimas 10 mediciones de latencia (en milisegundos) de un servicio.

    Devuelve los valores CRUDOS, sin procesar: no calcula promedios ni percentiles. Si
    hace falta un cálculo, esos números tiene que analizarlos el agente analista.

    Servicios disponibles: checkout, busqueda, perfil.
    Devuelve {"servicio": str, "unidad": "ms", "muestras": [int, ...]}.
    Si el servicio no existe devuelve {"error": "...", "servicios_disponibles": [...]}.
    """
    s = servicio.strip().lower()
    if s not in _METRICAS:
        return {
            "error": f"No hay métricas para el servicio '{servicio}'.",
            "servicios_disponibles": list(_METRICAS),
        }
    return {"servicio": s, "unidad": "ms", "muestras": _METRICAS[s]}


HERRAMIENTAS_INVESTIGACION = [buscar_documentacion, obtener_metricas]

PROMPT_INVESTIGADOR = (
    "Sos el agente INVESTIGADOR de un equipo. Tu único trabajo es recuperar datos con "
    "tus herramientas y reportarlos.\n"
    "- No hagas cálculos ni saques conclusiones: de eso se encarga el analista.\n"
    "- Si te piden comparar servicios, traé las métricas de TODOS los relevantes.\n"
    "- Cerrá tu turno con un resumen breve de qué datos conseguiste, incluyendo los "
    "números crudos, para que el analista los pueda usar sin volver a buscarlos."
)


def build_research_agent(modelo: BaseChatModel):
    """Agente ReAct con las herramientas de investigación."""
    return create_react_agent(
        model=modelo,
        tools=HERRAMIENTAS_INVESTIGACION,
        prompt=PROMPT_INVESTIGADOR,
        name="investigador",
    )
