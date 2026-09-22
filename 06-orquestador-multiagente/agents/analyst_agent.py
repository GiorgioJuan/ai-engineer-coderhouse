"""Agente analista: procesa los datos que trajo el investigador.

Sus herramientas calculan de verdad (no le pedimos al LLM que haga aritmetica mental,
que es donde se equivoca). No tiene acceso a la base de conocimiento: si le falta un
dato, tiene que decirlo para que el supervisor devuelva la pelota al investigador.
"""

import statistics
from typing import Any

from langchain_core.language_models import BaseChatModel
from langchain_core.tools import tool
from langgraph.prebuilt import create_react_agent


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
