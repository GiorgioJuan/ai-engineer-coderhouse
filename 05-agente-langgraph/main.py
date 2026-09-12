"""Prueba de ejecucion del agente + generacion de la traza ReAct.

Escenarios:
  1. Hilo "soporte-001": pregunta que obliga a encadenar DOS herramientas
     (nombre -> ID -> pedidos), y despues una repregunta que solo se puede
     responder recordando el turno anterior.
  2. Hilo "soporte-002": la herramienta devuelve un error de ambiguedad y el
     agente tiene que pedir aclaracion en vez de adivinar.

Cada hilo deja su traza en ./trazas/traza-<thread_id>.json

Uso:
    python main.py
"""

import asyncio
import json
import logging
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from langchain_core.messages import AnyMessage, HumanMessage

from agent import RECURSION_LIMIT, agente, config_hilo

logger = logging.getLogger("agente")
TRAZAS_DIR = Path(__file__).parent / "trazas"

HILO_PRINCIPAL = [
    "¿Cuántos pedidos tuvo Bruno y cuál fue el total?",
    "¿Y cuál fue el último? Dame el detalle completo.",
]
HILO_AMBIGUO = ["¿Cuántos pedidos tuvo el cliente de apellido a?"]


def serializar(msg: AnyMessage) -> dict[str, Any]:
    """Convierte un mensaje del estado en algo volcable a JSON."""
    entrada: dict[str, Any] = {"tipo": msg.type}

    if msg.type == "tool":
        entrada["herramienta"] = msg.name
        entrada["resultado"] = msg.content
        return entrada

    if getattr(msg, "tool_calls", None):
        entrada["accion"] = "llamar_herramientas"
        entrada["tool_calls"] = [
            {"herramienta": tc["name"], "argumentos": tc["args"]} for tc in msg.tool_calls
        ]
        if msg.content:
            entrada["razonamiento"] = msg.content
        return entrada

    entrada["contenido"] = msg.content
    return entrada


def imprimir(msg: AnyMessage) -> None:
    if msg.type == "human":
        print(f"\nUsuario: {msg.content}")
    elif msg.type == "tool":
        print(f"  <- {msg.name} devolvio: {msg.content[:150]}")
    elif getattr(msg, "tool_calls", None):
        for tc in msg.tool_calls:
            print(f"  -> el agente decide llamar: {tc['name']}({tc['args']})")
    elif msg.content:
        print(f"Agente: {msg.content}")


async def correr_hilo(grafo: Any, thread_id: str, preguntas: list[str]) -> None:
    config = config_hilo(thread_id)
    print(f"\n{'=' * 76}\nHilo '{thread_id}'  (recursion_limit={RECURSION_LIMIT})\n{'=' * 76}")

    estado: dict[str, Any] = {}
    vistos = 0
    for pregunta in preguntas:
        estado = await grafo.ainvoke({"messages": [HumanMessage(content=pregunta)]}, config)
        # El estado acumula: solo mostramos lo nuevo de este turno.
        for msg in estado["messages"][vistos:]:
            imprimir(msg)
        vistos = len(estado["messages"])

    llamadas = sum(1 for m in estado["messages"] if m.type == "tool")
    print(f"\n[{llamadas} llamadas a herramientas, {len(estado['messages'])} mensajes en el estado]")

    TRAZAS_DIR.mkdir(exist_ok=True)
    destino = TRAZAS_DIR / f"traza-{thread_id}.json"
    destino.write_text(
        json.dumps(
            {
                "thread_id": thread_id,
                "recursion_limit": RECURSION_LIMIT,
                "llamadas_a_herramientas": llamadas,
                "traza": [serializar(m) for m in estado["messages"]],
            },
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    print(f"[traza guardada en trazas/{destino.name}]")


async def main() -> None:
    load_dotenv()
    logging.basicConfig(level=logging.WARNING, format="%(levelname)-8s %(name)s | %(message)s")

    async with agente() as grafo:
        await correr_hilo(grafo, "soporte-001", HILO_PRINCIPAL)
        await correr_hilo(grafo, "soporte-002", HILO_AMBIGUO)


if __name__ == "__main__":
    asyncio.run(main())
