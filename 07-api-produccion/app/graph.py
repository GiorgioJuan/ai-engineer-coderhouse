"""Orquestador del modulo 6 + checkpointer en Redis + nodo de aprobacion humana.

    START -> supervisor -> (investigador | analista | aprobacion) -> supervisor -> ...
                                              aprobacion -> ejecutor -> supervisor
             supervisor -> sintesis -> END

Lo nuevo respecto del modulo 6:

- El supervisor puede proponer una ACCION con efectos secundarios. Esa rama no va
  directo al ejecutor: pasa por `aprobacion`, que llama a `interrupt()` y frena el grafo.
- El estado vive en Redis (`AsyncRedisSaver`), asi que la pausa sobrevive a un reinicio
  del proceso: la aprobacion puede llegar minutos despues, desde otra request.
"""

import operator
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Annotated, Any, Literal, TypedDict

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage
from langgraph.checkpoint.redis.aio import AsyncRedisSaver
from langgraph.graph import END, START, MessagesState, StateGraph

from app.agents import build_analyst_agent, build_research_agent
from app.config import ANTHROPIC_MODEL, LLM_PROVIDER, MAX_PASOS, OPENAI_MODEL, REDIS_URL
from app.hitl import ejecutar_accion, es_critica, solicitar_aprobacion

Destino = Literal["investigador", "analista", "accion", "FINISH"]


class Contribucion(TypedDict):
    agente: str
    resumen: str


class OrquestadorState(MessagesState):
    next_agent: Destino
    contribuciones: Annotated[list[Contribucion], operator.add]
    pasos: int
    veredicto: str
    accion_propuesta: str
    accion_resultado: str


class DecisionSupervisor(TypedDict):
    siguiente: Destino
    motivo: str
    # Solo se completa cuando `siguiente` es "accion".
    accion: str


RUBRICA = (
    "Sos el SUPERVISOR de un equipo. Decidís quién interviene ahora.\n\n"
    "Equipo:\n"
    "- 'investigador': busca documentación y métricas crudas. No calcula.\n"
    "- 'analista': calcula estadísticas y evalúa umbrales. No busca datos.\n"
    "- 'accion': ejecuta un cambio de infraestructura. Sólo si el usuario pidió actuar "
    "y el análisis ya justifica cuál acción. Acciones válidas: escalar_infraestructura, "
    "purgar_cache, reindexar_busqueda. Las acciones caras o irreversibles requieren "
    "aprobación humana antes de ejecutarse.\n\n"
    "RÚBRICA DE SUFICIENCIA — respondé 'FINISH' sólo si se cumplen las tres:\n"
    "1. Están todos los datos que la pregunta necesita.\n"
    "2. Ya fueron procesados por el analista, con números concretos.\n"
    "3. Con lo aportado alcanza para responder sin inventar nada (y, si el usuario pidió "
    "actuar, la acción ya se ejecutó o fue rechazada).\n\n"
    "No pidas refinamientos cosméticos: si la rúbrica se cumple, cerrá."
)


def build_model() -> BaseChatModel:
    if LLM_PROVIDER == "openai":
        from langchain_openai import ChatOpenAI

        return ChatOpenAI(model=OPENAI_MODEL, temperature=0)
    if LLM_PROVIDER == "anthropic":
        from langchain_anthropic import ChatAnthropic

        return ChatAnthropic(model=ANTHROPIC_MODEL, max_tokens=1024)
    raise ValueError(f"LLM_PROVIDER invalido: '{LLM_PROVIDER}'.")


def _briefing(state: OrquestadorState) -> str:
    if not state.get("contribuciones"):
        return "Todavía no hay aportes del equipo."
    return "\n".join(f"- [{c['agente']}] {c['resumen']}" for c in state["contribuciones"])


def _tarea(state: OrquestadorState) -> str:
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
                    f"APORTES DEL EQUIPO:\n{_briefing(state)}\n\n"
                    f"(paso {pasos + 1} de {MAX_PASOS}) ¿Quién sigue?",
                ),
            ]
        )
        salida: dict[str, Any] = {
            "next_agent": decision["siguiente"],
            "pasos": pasos + 1,
            "veredicto": decision["motivo"],
        }
        if decision["siguiente"] == "accion":
            salida["accion_propuesta"] = decision.get("accion", "")
        return salida

    def enrutar(
        state: OrquestadorState,
    ) -> Literal["investigador", "analista", "aprobacion", "sintesis"]:
        destino = state.get("next_agent", "FINISH")
        if destino == "FINISH":
            return "sintesis"
        if destino == "accion":
            return "aprobacion"
        return destino

    async def _correr_especialista(
        agente: Any, nombre: str, state: OrquestadorState
    ) -> dict[str, Any]:
        """Briefing acotado: la tarea y lo que aportaron los demas, no todo el historial."""
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

    def nodo_aprobacion(state: OrquestadorState) -> dict[str, Any]:
        """Punto de interrupcion. Solo frena si la accion es critica."""
        accion = state.get("accion_propuesta", "")

        if not es_critica(accion):
            return {
                "contribuciones": [
                    Contribucion(
                        agente="aprobacion", resumen=f"'{accion}' no requiere aprobación."
                    )
                ]
            }

        # interrupt() corta aca. Al reanudar con Command(resume=...), el nodo se vuelve a
        # ejecutar desde el principio y esta linea devuelve ese valor.
        respuesta = solicitar_aprobacion(accion, state.get("veredicto", ""))

        if not respuesta.get("aprobado"):
            comentario = respuesta.get("comentario") or "sin motivo"
            return {
                "next_agent": "FINISH",
                "accion_resultado": f"RECHAZADA: {comentario}",
                "contribuciones": [
                    Contribucion(
                        agente="aprobacion",
                        resumen=f"Un humano rechazó '{accion}'. Motivo: {comentario}.",
                    )
                ],
            }
        return {
            "contribuciones": [
                Contribucion(agente="aprobacion", resumen=f"Un humano aprobó '{accion}'.")
            ]
        }

    def nodo_ejecutor(state: OrquestadorState) -> dict[str, Any]:
        accion = state.get("accion_propuesta", "")
        res = ejecutar_accion.invoke({"accion": accion})
        return {
            "accion_resultado": str(res),
            "contribuciones": [
                Contribucion(
                    agente="ejecutor", resumen=f"Ejecutada '{accion}': {res['detalle']}"
                )
            ],
        }

    def tras_aprobacion(state: OrquestadorState) -> Literal["ejecutor", "sintesis"]:
        rechazada = state.get("accion_resultado", "").startswith("RECHAZADA")
        return "sintesis" if rechazada else "ejecutor"

    async def nodo_sintesis(state: OrquestadorState) -> dict[str, Any]:
        respuesta = await llm.ainvoke(
            [
                (
                    "system",
                    "Redactá la respuesta final integrando los aportes del equipo. Usá "
                    "sólo esos datos. Si hubo una acción aprobada o rechazada, decilo. "
                    "Máximo cinco oraciones.",
                ),
                ("human", f"PREGUNTA:\n{_tarea(state)}\n\nAPORTES:\n{_briefing(state)}"),
            ]
        )
        return {"messages": [AIMessage(content=respuesta.content, name="sintesis")]}

    grafo = StateGraph(OrquestadorState)
    grafo.add_node("supervisor", nodo_supervisor)
    grafo.add_node("investigador", nodo_investigador)
    grafo.add_node("analista", nodo_analista)
    grafo.add_node("aprobacion", nodo_aprobacion)
    grafo.add_node("ejecutor", nodo_ejecutor)
    grafo.add_node("sintesis", nodo_sintesis)

    grafo.add_edge(START, "supervisor")
    grafo.add_conditional_edges("supervisor", enrutar)
    grafo.add_edge("investigador", "supervisor")
    grafo.add_edge("analista", "supervisor")
    grafo.add_conditional_edges("aprobacion", tras_aprobacion)
    grafo.add_edge("ejecutor", "supervisor")
    grafo.add_edge("sintesis", END)
    return grafo


@asynccontextmanager
async def orquestador(
    modelo: BaseChatModel | None = None, redis_url: str | None = None
) -> AsyncIterator[Any]:
    """Compila el grafo con el checkpointer de Redis."""
    async with AsyncRedisSaver.from_conn_string(redis_url or REDIS_URL) as saver:
        await saver.asetup()
        yield build_graph(modelo).compile(checkpointer=saver)
