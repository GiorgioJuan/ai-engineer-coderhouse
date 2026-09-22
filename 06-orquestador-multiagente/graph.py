"""Grafo del orquestador: supervisor jerarquico + dos especialistas + sintesis.

    START -> supervisor -> (investigador | analista) -> supervisor -> ... -> sintesis -> END

El supervisor es el unico que enruta. Los especialistas siempre le devuelven el control:
no hablan entre si. Eso mantiene una sola fuente de decision y hace que el flujo sea
auditable paso a paso.

Contra el "supervisor infinito" hay dos frenos: una rubrica explicita de suficiencia en
su prompt, y un tope duro de pasos que fuerza el cierre pase lo que pase.

Contra la contaminacion de contexto: cada especialista recibe un briefing armado (la
tarea original mas lo que ya aportaron los otros), no el historial completo del sistema.
"""

import os
from typing import Any, Literal

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage
from langgraph.graph import END, START, StateGraph

from agents import build_analyst_agent, build_research_agent
from state import Contribucion, DecisionSupervisor, OrquestadorState

# Tope duro de vueltas del supervisor. Si se alcanza, se sintetiza con lo que haya.
MAX_PASOS = 6

RUBRICA = (
    "Sos el SUPERVISOR de un equipo de dos especialistas. Decidís quién interviene "
    "ahora, o si la tarea ya está lista para cerrarse.\n\n"
    "Equipo:\n"
    "- 'investigador': busca documentación interna y obtiene métricas crudas. No calcula.\n"
    "- 'analista': calcula estadísticas y evalúa umbrales. No busca datos.\n\n"
    "RÚBRICA DE SUFICIENCIA — respondé 'FINISH' sólo si se cumplen las tres:\n"
    "1. Están todos los datos que la pregunta necesita (documentación y/o métricas).\n"
    "2. Esos datos ya fueron procesados por el analista, con números concretos.\n"
    "3. Con lo aportado alcanza para responderle al usuario sin inventar nada.\n\n"
    "Si falta el punto 1, mandá 'investigador'. Si falta el 2, mandá 'analista'.\n"
    "Si el analista dijo que le falta un dato, mandá 'investigador' a buscarlo.\n"
    "No pidas refinamientos cosméticos: si la rúbrica se cumple, cerrá."
)


def build_model() -> BaseChatModel:
    provider = os.getenv("LLM_PROVIDER", "openai").lower()
    if provider == "openai":
        from langchain_openai import ChatOpenAI

        return ChatOpenAI(model=os.getenv("OPENAI_MODEL", "gpt-4o-mini"), temperature=0)
    if provider == "anthropic":
        from langchain_anthropic import ChatAnthropic

        return ChatAnthropic(
            model=os.getenv("ANTHROPIC_MODEL", "claude-sonnet-5"), max_tokens=1024
        )
    raise ValueError(f"LLM_PROVIDER invalido: '{provider}'. Usa 'openai' o 'anthropic'.")


def _briefing(state: OrquestadorState) -> str:
    """Lo que ya aporto el equipo, en texto compacto."""
    if not state.get("contribuciones"):
        return "Todavía no hay aportes del equipo."
    return "\n".join(
        f"- [{c['agente']}] {c['resumen']}" for c in state["contribuciones"]
    )


def _tarea(state: OrquestadorState) -> str:
    """La pregunta original del usuario (el primer mensaje humano)."""
    for m in state["messages"]:
        if m.type == "human":
            return str(m.content)
    return ""


def build_graph(modelo: BaseChatModel | None = None) -> StateGraph:
    llm = modelo if modelo is not None else build_model()
    investigador = build_research_agent(llm)
    analista = build_analyst_agent(llm)
    router = llm.with_structured_output(DecisionSupervisor)

    async def nodo_supervisor(state: OrquestadorState) -> dict[str, Any]:
        pasos = state.get("pasos", 0)

        # Freno duro: no depende de que el modelo se porte bien.
        if pasos >= MAX_PASOS:
            return {
                "next_agent": "FINISH",
                "pasos": pasos + 1,
                "veredicto": f"Tope de {MAX_PASOS} pasos alcanzado, se cierra con lo disponible.",
            }

        decision: DecisionSupervisor = await router.ainvoke(
            [
                ("system", RUBRICA),
                (
                    "human",
                    f"TAREA DEL USUARIO:\n{_tarea(state)}\n\n"
                    f"APORTES DEL EQUIPO HASTA AHORA:\n{_briefing(state)}\n\n"
                    f"(paso {pasos + 1} de {MAX_PASOS}) ¿Quién sigue?",
                ),
            ]
        )
        return {
            "next_agent": decision["siguiente"],
            "pasos": pasos + 1,
            "veredicto": decision["motivo"],
        }

    def enrutar(state: OrquestadorState) -> Literal["investigador", "analista", "sintesis"]:
        """Arista condicional: traduce la decisión del supervisor a un nodo del grafo."""
        destino = state.get("next_agent", "FINISH")
        return "sintesis" if destino == "FINISH" else destino

    async def _correr_especialista(
        agente: Any, nombre: str, state: OrquestadorState
    ) -> dict[str, Any]:
        """Invoca a un especialista con un briefing acotado, no con todo el historial.

        Cada especialista ve la tarea y lo que aportaron los demas. No ve los mensajes
        internos del supervisor ni las llamadas a herramientas de los otros agentes.
        """
        instruccion = (
            f"TAREA DEL USUARIO:\n{_tarea(state)}\n\n"
            f"APORTES PREVIOS DEL EQUIPO:\n{_briefing(state)}\n\n"
            f"Indicación del supervisor: {state.get('veredicto', '')}\n"
            f"Hacé tu parte."
        )
        salida = await agente.ainvoke({"messages": [HumanMessage(content=instruccion)]})
        resumen = str(salida["messages"][-1].content)

        return {
            "messages": [AIMessage(content=resumen, name=nombre)],
            "contribuciones": [Contribucion(agente=nombre, resumen=resumen)],
        }

    async def nodo_investigador(state: OrquestadorState) -> dict[str, Any]:
        return await _correr_especialista(investigador, "investigador", state)

    async def nodo_analista(state: OrquestadorState) -> dict[str, Any]:
        return await _correr_especialista(analista, "analista", state)

    async def nodo_sintesis(state: OrquestadorState) -> dict[str, Any]:
        """Fase final: una sola respuesta al usuario con todo lo que aporto el equipo."""
        respuesta = await llm.ainvoke(
            [
                (
                    "system",
                    "Redactá la respuesta final al usuario integrando los aportes del "
                    "equipo. Usá sólo esos datos, no agregues nada propio. Sé concreto "
                    "y citá los números. Máximo cinco oraciones.",
                ),
                (
                    "human",
                    f"PREGUNTA:\n{_tarea(state)}\n\nAPORTES:\n{_briefing(state)}",
                ),
            ]
        )
        return {"messages": [AIMessage(content=respuesta.content, name="sintesis")]}

    grafo = StateGraph(OrquestadorState)
    grafo.add_node("supervisor", nodo_supervisor)
    grafo.add_node("investigador", nodo_investigador)
    grafo.add_node("analista", nodo_analista)
    grafo.add_node("sintesis", nodo_sintesis)

    grafo.add_edge(START, "supervisor")
    grafo.add_conditional_edges("supervisor", enrutar)
    # Los especialistas siempre devuelven el control al supervisor.
    grafo.add_edge("investigador", "supervisor")
    grafo.add_edge("analista", "supervisor")
    grafo.add_edge("sintesis", END)
    return grafo


def compile_graph(modelo: BaseChatModel | None = None):
    return build_graph(modelo).compile()
