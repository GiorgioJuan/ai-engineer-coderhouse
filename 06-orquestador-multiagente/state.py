"""Estado compartido del orquestador.

Hereda de MessagesState (que ya trae `messages` con el reducer `add_messages`) y le
suma los campos que necesita la supervision:

- `next_agent`: a quien le toca. Lo escribe el supervisor en cada vuelta.
- `contribuciones`: quien aporto que. Sin esto, el supervisor tendria que releer todo
  el historial para saber si el investigador ya hizo su parte, y ahi es donde se pierde
  el contexto en un sistema con varios agentes.
- `pasos`: contador de vueltas del supervisor. Es el freno duro contra el bucle infinito.
- `veredicto`: por que el supervisor decidio terminar. Queda como registro auditable.
"""

import operator
from typing import Annotated, Literal, TypedDict

from langgraph.graph import MessagesState

Agente = Literal["investigador", "analista"]
Destino = Literal["investigador", "analista", "FINISH"]


class Contribucion(TypedDict):
    """Lo que un especialista aporto en un turno."""

    agente: str
    resumen: str


class OrquestadorState(MessagesState):
    """Estado del grafo. `messages` viene de MessagesState."""

    next_agent: Destino
    # operator.add acumula en vez de reemplazar: cada turno suma su contribucion.
    contribuciones: Annotated[list[Contribucion], operator.add]
    pasos: int
    veredicto: str


class DecisionSupervisor(TypedDict):
    """Salida estructurada del supervisor. Fuerza al modelo a elegir un destino valido."""

    siguiente: Destino
    motivo: str
