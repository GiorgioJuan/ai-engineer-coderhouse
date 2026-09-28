"""Agentes especialistas del orquestador (heredados del modulo 6).

Herramientas acotadas por dominio: el investigador busca y no calcula, el analista
calcula y no busca. Esa separacion es lo que hace que la delegacion tenga sentido.
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


import statistics



@tool
def calcular_estadisticas(valores: list[float]) -> dict[str, Any]:
    """Calcula media, mediana, máximo, mínimo y percentil 95 de una lista de números.

    Usala siempre que necesites resumir mediciones. No estimes estos valores a ojo:
    pasá la lista completa a esta herramienta.

    Devuelve {"n": int, "media": float, "mediana": float, "min": float, "max": float,
    "p95": float}. Si la lista viene vacía devuelve {"error": "..."}.
    """
    if not valores:
        return {"error": "La lista de valores está vacía."}

    ordenados = sorted(float(v) for v in valores)
    # Percentil 95 por el método del vecino más cercano.
    idx = min(len(ordenados) - 1, max(0, round(0.95 * len(ordenados)) - 1))
    return {
        "n": len(ordenados),
        "media": round(statistics.fmean(ordenados), 2),
        "mediana": round(statistics.median(ordenados), 2),
        "min": ordenados[0],
        "max": ordenados[-1],
        "p95": ordenados[idx],
    }


@tool
def evaluar_sla(valor_observado: float, umbral: float) -> dict[str, Any]:
    """Compara un valor medido contra un umbral de SLA y calcula la brecha.

    Usala después de calcular_estadisticas, para saber si un servicio cumple el acuerdo
    y cuánto tendría que mejorar si no lo cumple.

    Devuelve {"cumple": bool, "brecha_absoluta": float, "brecha_porcentual": float,
    "mejora_necesaria_pct": float}, donde mejora_necesaria_pct es cuánto habría que
    bajar el valor observado para cumplir (0 si ya cumple).
    """
    cumple = valor_observado <= umbral
    brecha = round(valor_observado - umbral, 2)
    return {
        "cumple": cumple,
        "umbral": umbral,
        "valor_observado": valor_observado,
        "brecha_absoluta": brecha,
        "brecha_porcentual": round(100 * brecha / umbral, 2),
        "mejora_necesaria_pct": 0.0 if cumple else round(100 * brecha / valor_observado, 2),
    }


HERRAMIENTAS_ANALISIS = [calcular_estadisticas, evaluar_sla]

PROMPT_ANALISTA = (
    "Sos el agente ANALISTA de un equipo. Procesás los datos que ya trajo el "
    "investigador.\n"
    "- Usá las herramientas para calcular: no hagas aritmética a ojo.\n"
    "- Si te falta un dato para poder concluir, decilo explícitamente y nombrá qué dato "
    "falta. No lo inventes ni lo estimes: el supervisor va a pedírselo al investigador.\n"
    "- Cerrá tu turno con la conclusión y los números que la respaldan."
)


def build_analyst_agent(modelo: BaseChatModel):
    """Agente ReAct con las herramientas de análisis."""
    return create_react_agent(
        model=modelo,
        tools=HERRAMIENTAS_ANALISIS,
        prompt=PROMPT_ANALISTA,
        name="analista",
    )
