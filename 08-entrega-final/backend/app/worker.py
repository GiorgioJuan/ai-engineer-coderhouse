"""Consumidor único y durable del Stream de comandos. Correr con: python -m app.worker.

La API encola cada comando largo (indexar, iniciar sesión, responder, finalizar) y
contesta 202; este proceso los ejecuta. Un comando que queda pendiente porque el worker
murió se recupera con XAUTOCLAIM al volver a arrancar.
"""

from __future__ import annotations

import asyncio
import logging
import os
import socket
import time
from contextlib import suppress
from datetime import UTC, datetime
from typing import Any

import httpx
import redis.asyncio as redis
from pydantic import ValidationError
from redis.exceptions import RedisError

from .config import get_settings
from .llm import BudgetExceeded, LiveModeUnavailable, ProviderQuotaExceeded
from .observability import flush_observability, setup_observability
from .rag import InvalidCitation
from .storage import GROUP, STREAM, Repository

logger = logging.getLogger("panellab.worker")

MAX_ATTEMPTS = 3
# Fallas transitorias o de salida del modelo: otro intento puede salir bien.
TRANSIENT = (
    httpx.TransportError,
    httpx.HTTPStatusError,
    RedisError,
    TimeoutError,
    ConnectionError,
    InvalidCitation,
    ValidationError,
)
# Fallas que otro intento no resuelve: hay que corregir configuración o estado.
PERMANENT = (BudgetExceeded, LiveModeUnavailable, ProviderQuotaExceeded)


def now() -> str:
    return datetime.now(UTC).isoformat()


def job_error(exc: Exception, attempt: int) -> dict[str, Any]:
    retryable = isinstance(exc, TRANSIENT) and not isinstance(exc, PERMANENT) and attempt < MAX_ATTEMPTS
    code = type(exc).__name__
    if isinstance(exc, httpx.HTTPStatusError):
        status = exc.response.status_code
        # 401/403 (clave), 400/404/422 (pedido inválido): otro intento falla igual.
        if 400 <= status < 500 and status not in {408, 409, 429}:
            retryable = False
        code = f"ProviderHTTP{status}"
    return {"code": code, "message": str(exc)[:500], "retryable": retryable}


async def process(repo: Repository, engine: Any, client: Any, stream_id: Any, fields: dict[Any, Any]) -> None:
    raw_command_id = fields.get(b"command_id") or fields.get("command_id")
    command_id = raw_command_id.decode() if isinstance(raw_command_id, bytes) else raw_command_id
    command = await repo.get("command", command_id)
    if not command:
        await client.xack(STREAM, GROUP, stream_id)
        return
    job = await repo.get("job", command["job_id"])
    if not job or job["status"] == "SUCCEEDED":
        await client.xack(STREAM, GROUP, stream_id)
        return
    job.update(status="RUNNING", attempt=job["attempt"] + 1, error=None, updated_at=now())
    await repo.put("job", job["id"], job)
    if command.get("session_id"):
        session = await repo.get("session", command["session_id"])
        if session and session.get("status") in {"QUEUED", "FAILED", "RUNNING"}:
            session.update(status="RUNNING", active_job_id=job["id"], updated_at=now())
            await repo.put("session", session["id"], session)
    try:
        await engine.execute(command)
    except Exception as exc:
        logger.warning("Command %s failed: %s", command_id, type(exc).__name__)
        job.update(status="FAILED", error=job_error(exc, job["attempt"]), updated_at=now())
        await repo.put("job", job["id"], job)
        if command["kind"] == "INDEX_DOCUMENT":
            ref = command["payload"]
            doc_key = f"{ref['document_id']}:{ref['version']}"
            document = await repo.get("document", doc_key)
            if document and document.get("index_status") != "READY":
                document["index_status"] = "FAILED"
                await repo.put("document", doc_key, document)
        if command.get("session_id"):
            session = await repo.get("session", command["session_id"])
            if session and session.get("active_job_id") == job["id"]:
                session.update(status="FAILED", updated_at=now())
                await repo.put("session", session["id"], session)
    else:
        job.update(status="SUCCEEDED", error=None, updated_at=now())
        await repo.put("job", job["id"], job)
    await client.xack(STREAM, GROUP, stream_id)


async def run() -> None:
    from .engine import GraphEngine

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s | %(message)s")
    settings = get_settings()
    client = redis.from_url(str(settings.redis_url), decode_responses=False, socket_timeout=15)
    repo = Repository(client)
    await repo.ensure_group()
    setup_observability(settings, "panellab-worker")
    engine = GraphEngine(repo, settings)
    consumer = f"{socket.gethostname()}-{os.getpid()}"

    async def heartbeat() -> None:
        while True:
            with suppress(RedisError):
                await client.set("panellab:worker:heartbeat", str(time.time()), ex=45)
            await asyncio.sleep(10)

    heartbeat_task = asyncio.create_task(heartbeat())
    try:
        while True:
            try:
                stale = await client.xautoclaim(STREAM, GROUP, consumer, min_idle_time=30000, start_id="0-0", count=10)
                messages = stale[1] if stale and len(stale) > 1 else []
                if not messages:
                    own = await client.xreadgroup(GROUP, consumer, {STREAM: "0"}, count=10)
                    messages = own[0][1] if own else []
                if not messages:
                    fresh = await client.xreadgroup(GROUP, consumer, {STREAM: ">"}, count=10, block=5000)
                    messages = fresh[0][1] if fresh else []
                for stream_id, fields in messages:
                    await process(repo, engine, client, stream_id, fields)
            except RedisError as exc:
                # Redis caído o reiniciando: el comando sigue pendiente en el Stream y se
                # retoma al reconectar. El worker no debe morir por esto.
                logger.warning("Redis unavailable (%s); retrying in 2 s", type(exc).__name__)
                await asyncio.sleep(2)
    finally:
        heartbeat_task.cancel()
        with suppress(asyncio.CancelledError):
            await heartbeat_task
        flush_observability()
        await client.aclose()


if __name__ == "__main__":
    asyncio.run(run())
