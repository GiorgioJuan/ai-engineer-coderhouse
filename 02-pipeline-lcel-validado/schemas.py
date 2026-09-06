"""Contrato de datos de salida del pipeline.

Este esquema cumple dos roles a la vez:
1. Le dice al modelo qué forma debe tener su respuesta (LangChain lo convierte en
   la definición de tool que se manda a OpenAI/Anthropic).
2. Valida la respuesta que vuelve. Si el modelo alucina una clave o manda un tipo
   equivocado, Pydantic lo rechaza y la cadena reintenta.

Las descripciones de cada campo NO son decorativas: viajan al modelo como parte del
schema, asi que son parte del prompt.
"""

from enum import Enum

from pydantic import BaseModel, Field, field_validator


class NivelCriticidad(str, Enum):
    BAJA = "baja"
    MEDIA = "media"
    ALTA = "alta"


class ExtraccionTecnica(BaseModel):
    """Entidades técnicas extraidas de un texto sin procesar."""

    tecnologias: list[str] = Field(
        min_length=1,
        max_length=15,
        description=(
            "Tecnologías, frameworks, lenguajes o servicios mencionados en el texto. "
            "Usa el nombre canónico (ej. 'PostgreSQL', no 'postgres'). Al menos una."
        ),
    )
    nivel_de_criticidad: NivelCriticidad = Field(
        description=(
            "Criticidad del problema o sistema descrito: 'baja' si es informativo, "
            "'media' si hay degradacion, 'alta' si hay perdida de servicio o datos."
        ),
    )
    resumen_tecnico: str = Field(
        min_length=20,
        max_length=300,
        description=(
            "Resumen tecnico en una o dos oraciones, en español, sin adjetivos de relleno."
        ),
    )

    @field_validator("tecnologias")
    @classmethod
    def limpiar_tecnologias(cls, v: list[str]) -> list[str]:
        """Normaliza espacios y elimina duplicados conservando el orden."""
        vistas: dict[str, None] = {}
        for t in v:
            t = t.strip()
            if t and t.lower() not in {k.lower() for k in vistas}:
                vistas[t] = None
        if not vistas:
            raise ValueError("la lista de tecnologías no puede quedar vacía")
        return list(vistas)
