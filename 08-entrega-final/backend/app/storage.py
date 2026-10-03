"""Redis source of truth and durable command queue."""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

import redis.asyncio as redis
from redis.exceptions import WatchError

STREAM = "panellab:commands"
GROUP = "panellab:workers"


def dumps(value: dict[str, Any]) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), default=str)


class Conflict(Exception):
    pass


class Repository:
    def __init__(self, client: redis.Redis):
        self.redis = client

    @staticmethod
    def key(kind: str, entity_id: str) -> str:
        return f"panellab:{kind}:{entity_id}"

    async def get(self, kind: str, entity_id: str) -> dict[str, Any] | None:
        raw = await self.redis.get(self.key(kind, entity_id))
        return json.loads(raw) if raw else None

    async def put(self, kind: str, entity_id: str, data: dict[str, Any]) -> None:
        async with self.redis.pipeline(transaction=True) as pipe:
            pipe.set(self.key(kind, entity_id), dumps(data))
            pipe.sadd(f"panellab:index:{kind}", entity_id)
            await pipe.execute()

    async def list(self, kind: str, project_id: str | None = None) -> list[dict[str, Any]]:
        ids = await self.redis.smembers(f"panellab:index:{kind}")
        if not ids:
            return []
        values = await self.redis.mget([self.key(kind, x.decode() if isinstance(x, bytes) else x) for x in ids])
        items = [json.loads(value) for value in values if value]
        if project_id is not None:
            items = [item for item in items if item.get("project_id") == project_id]
        return sorted(items, key=lambda item: (item.get("created_at", ""), item.get("id", "")))

    async def cas(
        self, kind: str, entity_id: str, expected_revision: int, mutate: Callable[[dict[str, Any]], dict[str, Any]]
    ) -> dict[str, Any]:
        key = self.key(kind, entity_id)
        for _ in range(5):
            async with self.redis.pipeline() as pipe:
                try:
                    await pipe.watch(key)
                    raw = await pipe.get(key)
                    if not raw:
                        raise KeyError(entity_id)
                    current = json.loads(raw)
                    if current.get("revision") != expected_revision:
                        raise Conflict("stale revision")
                    updated = mutate(current)
                    pipe.multi()
                    pipe.set(key, dumps(updated))
                    await pipe.execute()
                    return updated
                except WatchError:
                    continue
        raise Conflict("concurrent change")

    async def enqueue(
        self,
        *,
        scope: str,
        idempotency_key: str,
        request_hash: str,
        command: dict[str, Any],
        job: dict[str, Any],
        accepted: dict[str, Any],
        precondition: Callable[[dict[str, Any] | None], bool] | None = None,
        entity_kind: str | None = None,
        entity_id: str | None = None,
        entity: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        idem_key = self.key("idempotency", f"{scope}:{idempotency_key}")
        entity_key = self.key(entity_kind, entity_id) if entity_kind and entity_id else None
        watch_keys = [idem_key] + ([entity_key] if entity_key else [])
        for _ in range(8):
            async with self.redis.pipeline() as pipe:
                try:
                    await pipe.watch(*watch_keys)
                    prior = await pipe.get(idem_key)
                    if prior:
                        previous = json.loads(prior)
                        if previous["request_hash"] != request_hash:
                            raise Conflict("Idempotency-Key reused with another request")
                        return previous["accepted"]
                    current = json.loads(raw) if (entity_key and (raw := await pipe.get(entity_key))) else None
                    if precondition and not precondition(current):
                        raise Conflict("resource state changed")
                    pipe.multi()
                    if entity_key and entity is not None:
                        pipe.set(entity_key, dumps(entity))
                        pipe.sadd(f"panellab:index:{entity_kind}", entity_id)
                    pipe.set(self.key("job", job["id"]), dumps(job))
                    pipe.sadd("panellab:index:job", job["id"])
                    pipe.set(self.key("command", command["id"]), dumps(command))
                    pipe.set(idem_key, dumps({"request_hash": request_hash, "accepted": accepted}))
                    pipe.xadd(STREAM, {"command_id": command["id"]})
                    await pipe.execute()
                    return accepted
                except WatchError:
                    continue
        raise Conflict("concurrent command")

    async def ensure_group(self) -> None:
        try:
            await self.redis.xgroup_create(STREAM, GROUP, id="0", mkstream=True)
        except redis.ResponseError as exc:
            if "BUSYGROUP" not in str(exc):
                raise
