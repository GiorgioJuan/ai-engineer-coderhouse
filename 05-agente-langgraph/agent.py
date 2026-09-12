"""Agente ReAct con LangGraph: StateGraph ciclico + persistencia en SQLite.

Topologia del grafo:

    START -> modelo -> (tools_condition) -> herramientas -> modelo -> ... -> END

La arista condicional es lo que hace el ciclo: si la ultima respuesta del modelo trae
tool_calls, va al nodo de herramientas; si no, termina. El modelo decide solo cuando
llamar a una herramienta y cuando ya tiene lo que necesita. No hay ningun if/else que
enrute por nosotros.

El checkpointer guarda el estado despues de cada paso, indexado por thread_id: por eso
una segunda pregunta en el mismo hilo llega con todo el historial.
"""

import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AnyMessage, SystemMessage
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from langgraph.graph import END, START, MessagesState, StateGraph
from langgraph.graph.state import CompiledStateGraph
from langgraph.prebuilt import ToolNode, tools_condition

from tools import HERRAMIENTAS

BASE_DIR = Path(__file__).parent
DB_PATH = BASE_DIR / "checkpoints.sqlite"

# Techo de pasos del ciclo. Sin esto, un agente que se traba llamando herramientas en
# loop sigue quemando llamadas a la API hasta que alguien lo corta a mano.
RECURSION_LIMIT = 10

PROMPT_SISTEMA = SystemMessage(
    content=(
        "Sos un asistente de soporte con acceso a la base de pedidos.\n"
        "- Usá las herramientas para responder; no inventes datos de clientes ni pedidos.\n"
        "- Si una herramienta devuelve un error, leelo: suele decirte qué hacer "
        "(por ejemplo, buscar primero el ID del cliente, o pedirle al usuario que aclare "
        "a cuál de varias personas se refiere).\n"
        "- Si el error es ambiguedad entre varios clientes, no adivines: preguntá.\n"
        "- Respondé en español, en una o dos oraciones, con los montos en pesos."
    )
)


def build_model() -> BaseChatModel:
    """Modelo con las herramientas vinculadas: `bind_tools` es lo que le da autonomia."""
    provider = os.getenv("LLM_PROVIDER", "openai").lower()

    if provider == "openai":
        from langchain_openai import ChatOpenAI

        modelo: BaseChatModel = ChatOpenAI(
            model=os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
            temperature=0,
        )
    elif provider == "anthropic":
        from langchain_anthropic import ChatAnthropic

        modelo = ChatAnthropic(
            model=os.getenv("ANTHROPIC_MODEL", "claude-sonnet-5"),
            max_tokens=1024,
        )
    else:
        raise ValueError(f"LLM_PROVIDER invalido: '{provider}'. Usa 'openai' o 'anthropic'.")

    return modelo.bind_tools(HERRAMIENTAS)


def build_graph(modelo: BaseChatModel | None = None) -> StateGraph:
    """Arma el grafo sin compilar (el checkpointer se inyecta al compilar)."""
    llm = modelo if modelo is not None else build_model()

    async def nodo_modelo(state: MessagesState) -> dict[str, list[AnyMessage]]:
        """Un solo turno del modelo. El prompt de sistema no se guarda en el estado."""
        respuesta = await llm.ainvoke([PROMPT_SISTEMA, *state["messages"]])
        return {"messages": [respuesta]}

    grafo = StateGraph(MessagesState)
    grafo.add_node("modelo", nodo_modelo)
    grafo.add_node("herramientas", ToolNode(HERRAMIENTAS))

    grafo.add_edge(START, "modelo")
    # Arista condicional: si hay tool_calls va a "herramientas", si no va a END.
    grafo.add_conditional_edges(
        "modelo", tools_condition, {"tools": "herramientas", END: END}
    )
    # Y de vuelta al modelo: acá se cierra el ciclo.
    grafo.add_edge("herramientas", "modelo")
    return grafo


@asynccontextmanager
async def agente(
    modelo: BaseChatModel | None = None, db_path: Path | str | None = None
) -> AsyncIterator[CompiledStateGraph]:
    """Context manager que abre el checkpointer y entrega el grafo compilado."""
    ruta = str(db_path if db_path is not None else DB_PATH)
    async with AsyncSqliteSaver.from_conn_string(ruta) as checkpointer:
        yield build_graph(modelo).compile(checkpointer=checkpointer)


def config_hilo(thread_id: str) -> dict[str, Any]:
    """Configuracion de invocacion: identifica la sesion y limita el ciclo."""
    return {
        "configurable": {"thread_id": thread_id},
        "recursion_limit": RECURSION_LIMIT,
    }
