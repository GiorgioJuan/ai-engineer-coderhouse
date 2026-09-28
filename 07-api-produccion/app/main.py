"""API FastAPI del orquestador multi-agente.

    POST /tasks              -> encola y devuelve job_id (202, no bloquea)
    GET  /tasks/{id}         -> estado del job (polling)
    POST /tasks/{id}/approve -> resuelve una pausa human-in-the-loop
    GET  /health             -> ping de la API y de Redis

Todo el I/O es asincrono: Redis con `redis.asyncio`, el grafo con `ainvoke`. No hay una
sola llamada bloqueante dentro de un endpoint.
"""

import logging
import uuid
from contextlib import AsyncExitStack, asynccontextmanager
from typing import Any, AsyncIterator

from fastapi import Depends, FastAPI, HTTPException, status
from redis.asyncio import Redis

from app.config import REDIS_URL
from app.graph import orquestador
from app.observability import init_observabilidad
from app.schemas import Aprobacion, CrearTarea, EstadoJob, Job, TareaCreada
from app.store import JobStore
from app.worker import ejecutar_job, lanzar, reanudar_job

logging.basicConfig(level=logging.INFO, format="%(levelname)-8s %(name)s | %(message)s")
logger = logging.getLogger("api")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Instrumentacion, Redis y grafo se crean una vez y se comparten."""
    init_observabilidad()

    async with AsyncExitStack() as stack:
        redis = await stack.enter_async_context(Redis.from_url(REDIS_URL, decode_responses=True))
        grafo = await stack.enter_async_context(orquestador())

        app.state.store = JobStore(redis)
        app.state.grafo = grafo
        app.state.redis = redis
        logger.info("API lista (Redis en %s)", REDIS_URL)
        yield


app = FastAPI(
    title="Orquestador multi-agente",
    description="API asincrona sobre el grafo del modulo 6, con Redis y human-in-the-loop.",
    version="1.0.0",
    lifespan=lifespan,
)


def get_store() -> JobStore:
    return app.state.store


def get_grafo() -> Any:
    return app.state.grafo


async def _buscar_job(store: JobStore, job_id: str) -> Job:
    job = await store.obtener(job_id)
    if job is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"No existe el job '{job_id}'.")
    return job


@app.get("/health")
async def health() -> dict[str, Any]:
    try:
        await app.state.redis.ping()
        redis_ok = True
    except Exception:
        redis_ok = False
    return {"api": "ok", "redis": "ok" if redis_ok else "sin conexion"}


@app.post("/tasks", response_model=TareaCreada, status_code=status.HTTP_202_ACCEPTED)
async def crear_tarea(
    body: CrearTarea,
    store: JobStore = Depends(get_store),
    grafo: Any = Depends(get_grafo),
) -> TareaCreada:
    """Encola la tarea y contesta enseguida. El agente corre en segundo plano."""
    job_id = uuid.uuid4().hex[:12]
    await store.crear(job_id, body.consulta)
    lanzar(ejecutar_job(grafo, store, job_id, body.consulta))

    logger.info("Job %s encolado", job_id)
    return TareaCreada(
        job_id=job_id, estado=EstadoJob.PENDING, url_estado=f"/tasks/{job_id}"
    )


@app.get("/tasks/{job_id}", response_model=Job)
async def estado_tarea(job_id: str, store: JobStore = Depends(get_store)) -> Job:
    """Polling del cliente. Nunca espera al agente."""
    return await _buscar_job(store, job_id)


@app.post("/tasks/{job_id}/approve", response_model=Job)
async def aprobar_tarea(
    job_id: str,
    body: Aprobacion,
    store: JobStore = Depends(get_store),
    grafo: Any = Depends(get_grafo),
) -> Job:
    """Resuelve la pausa human-in-the-loop y reanuda el grafo en segundo plano."""
    job = await _buscar_job(store, job_id)

    if job.estado is not EstadoJob.WAITING_APPROVAL:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"El job '{job_id}' esta en estado {job.estado.value}, no espera aprobacion.",
        )

    lanzar(reanudar_job(grafo, store, job_id, body.aprobado, body.comentario))
    logger.info("Job %s %s por un humano", job_id, "aprobado" if body.aprobado else "rechazado")

    actualizado = await store.obtener(job_id)
    return actualizado or job
