"""Contratos de entrada y salida de la API."""

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class EstadoJob(str, Enum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    WAITING_APPROVAL = "WAITING_APPROVAL"
    DONE = "DONE"
    FAILED = "FAILED"
    REJECTED = "REJECTED"


class CrearTarea(BaseModel):
    consulta: str = Field(min_length=5, max_length=2000)


class TareaCreada(BaseModel):
    job_id: str
    estado: EstadoJob
    url_estado: str


class Aprobacion(BaseModel):
    aprobado: bool
    comentario: str = ""


class Job(BaseModel):
    """Lo que se guarda en Redis y lo que devuelve GET /tasks/{id}."""

    job_id: str
    estado: EstadoJob
    consulta: str
    creado: datetime
    actualizado: datetime
    resultado: str | None = None
    error: str | None = None
    # Cuando el grafo se pausa, aca queda lo que hay que aprobar.
    aprobacion_pendiente: dict[str, Any] | None = None
    pasos: int = 0
    contribuciones: list[dict[str, Any]] = Field(default_factory=list)
