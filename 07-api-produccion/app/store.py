"""Persistencia del estado de los jobs en Redis.

El cliente se inyecta en el constructor: en produccion es `redis.asyncio.Redis`, en los
tests es un fake. Todo el I/O es asincrono, asi que ningun endpoint bloquea el loop.
"""

from datetime import datetime, timezone
from typing import Any

from redis.asyncio import Redis

from app.config import JOB_TTL
from app.schemas import EstadoJob, Job

PREFIJO = "job:"


def _ahora() -> datetime:
    return datetime.now(timezone.utc)


class JobStore:
    def __init__(self, cliente: Redis, ttl: int = JOB_TTL) -> None:
        self.redis = cliente
        self.ttl = ttl

    @staticmethod
    def _clave(job_id: str) -> str:
        return f"{PREFIJO}{job_id}"

    async def crear(self, job_id: str, consulta: str) -> Job:
        job = Job(
            job_id=job_id,
            estado=EstadoJob.PENDING,
            consulta=consulta,
            creado=_ahora(),
            actualizado=_ahora(),
        )
        await self._guardar(job)
        return job

    async def obtener(self, job_id: str) -> Job | None:
        crudo = await self.redis.get(self._clave(job_id))
        if crudo is None:
            return None
        return Job.model_validate_json(crudo)

    async def actualizar(self, job_id: str, **campos: Any) -> Job | None:
        """Lee, aplica los campos y reescribe. Devuelve None si el job expiro."""
        job = await self.obtener(job_id)
        if job is None:
            return None
        actualizado = job.model_copy(update={**campos, "actualizado": _ahora()})
        await self._guardar(actualizado)
        return actualizado

    async def _guardar(self, job: Job) -> None:
        await self.redis.set(self._clave(job.job_id), job.model_dump_json(), ex=self.ttl)
