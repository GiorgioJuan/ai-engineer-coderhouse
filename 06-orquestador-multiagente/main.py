"""Demo del flujo de delegacion.

La consulta esta elegida para que ningun especialista pueda resolverla solo: hace falta
buscar el SLA y las metricas (investigador) y despues calcular percentiles y la brecha
(analista). El supervisor tiene que delegar al menos dos veces antes de cerrar.

Uso:
    python main.py
    python main.py "tu consulta"
"""

import asyncio
import sys
from pathlib import Path

from dotenv import load_dotenv
from langchain_core.messages import HumanMessage

from graph import MAX_PASOS, compile_graph

CONSULTA = (
    "¿Cuál de nuestros servicios tiene peor latencia y cuánto tendría que mejorar "
    "para cumplir el SLA vigente?"
)


def exportar_mermaid(grafo, destino: Path) -> None:
    """Guarda el diagrama del grafo para el README."""
    destino.write_text(grafo.get_graph().draw_mermaid(), encoding="utf-8")
    print(f"[diagrama guardado en {destino.name}]")


async def main() -> None:
    load_dotenv()
    consulta = " ".join(sys.argv[1:]) or CONSULTA

    grafo = compile_graph()
    exportar_mermaid(grafo, Path(__file__).parent / "grafo.mmd")

    print(f"\n{'=' * 76}\nConsulta: {consulta}\n{'=' * 76}")

    estado = {"messages": [HumanMessage(content=consulta)], "contribuciones": [], "pasos": 0}

    # astream por nodo: asi se ve la delegacion paso a paso, no solo el resultado.
    async for evento in grafo.astream(estado, {"recursion_limit": 25}):
        for nodo, salida in evento.items():
            if nodo == "supervisor":
                print(f"\n[supervisor] -> {salida['next_agent']}")
                print(f"             motivo: {salida['veredicto']}")
            elif nodo == "sintesis":
                print(f"\n{'-' * 76}\nRESPUESTA FINAL:\n{salida['messages'][-1].content}")
            else:
                resumen = salida["contribuciones"][0]["resumen"]
                print(f"\n[{nodo}] aporta:\n  {resumen[:400]}")

    print(f"\n[tope de pasos del supervisor: {MAX_PASOS}]")


if __name__ == "__main__":
    asyncio.run(main())
