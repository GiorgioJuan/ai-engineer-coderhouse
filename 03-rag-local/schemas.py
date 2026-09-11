"""Contrato de salida del pipeline RAG."""

from pydantic import BaseModel, Field


class RespuestaRAG(BaseModel):
    """Respuesta fundamentada en el contexto recuperado."""

    respuesta: str = Field(
        description=(
            "Respuesta a la pregunta, basada UNICAMENTE en el contexto. Si el contexto "
            "no alcanza, deci explicitamente que no tenes acceso a esa informacion."
        )
    )
    referencias: list[str] = Field(
        default_factory=list,
        description=(
            "Nombres de los archivos fuente que respaldan la respuesta, tal como "
            "aparecen en las etiquetas [fuente: ...] del contexto. Vacio si no se uso "
            "ninguno."
        ),
    )
    tiene_respuesta: bool = Field(
        description=(
            "true si el contexto contenia la informacion necesaria; false si tuviste "
            "que decir que no sabes."
        )
    )
