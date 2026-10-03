"""Adaptadores de modelo demo/live y presupuesto compartido persistente en Redis.

- ``demo``: decisiones deterministas para probar el circuito completo sin red ni costo.
  Igual emite spans LLM, así la traza de Phoenix muestra la misma forma que en live.
- ``live``: llamadas HTTP asíncronas (httpx) a un proveedor compatible con OpenAI, con
  salida estructurada validada por Pydantic y una reserva de costo antes de cada llamada.
"""

from __future__ import annotations

import asyncio
import json
import os
import uuid
from dataclasses import dataclass
from typing import Any

import httpx
from pydantic import BaseModel

from app.observability import content_attr, span
from app.rag import demo_embedding

DEMO_MODEL = "demo-determinista"


@dataclass(frozen=True)
class ChatModelSpec:
    """Tarifas en USD por millón de tokens y capacidades del modelo."""

    input_rate: float
    output_rate: float
    supports_reasoning_effort: bool
    max_standard_input_tokens: int


# Tarifas oficiales verificadas el 28/09/2026. Un modelo sin precio verificado no se usa en
# live: no se puede reservar presupuesto para algo que no sabemos cuánto cuesta.
CHAT_MODELS: dict[str, ChatModelSpec] = {
    "gpt-4o-mini": ChatModelSpec(0.15, 0.60, False, 128_000),
    "gpt-6-luna": ChatModelSpec(0.10, 0.50, True, 272_000),
}
EMBED_RATES: dict[str, float] = {"text-embedding-3-small": 0.02}

# Respuestas que el proveedor rechaza sin facturar y conviene reintentar una vez.
RETRYABLE_STATUS = {408, 409, 429, 500, 502, 503, 504}


class BudgetExceeded(RuntimeError):
    pass


class LiveModeUnavailable(RuntimeError):
    pass


class ProviderQuotaExceeded(RuntimeError):
    """La cuenta del proveedor no tiene crédito: reintentar no cambia nada."""


QUOTA_CODES = {"insufficient_quota", "credit_balance_exhausted", "billing_hard_limit_reached"}


def _quota_error(response: Any) -> bool:
    try:
        error = response.json().get("error")
    except Exception:
        return False
    if not isinstance(error, dict):
        return False
    return error.get("code") in QUOTA_CODES or error.get("type") in QUOTA_CODES


RESERVE_LUA = """
local ledger = KEYS[1]
local reservation = KEYS[2]
local prior = tonumber(ARGV[1])
local ceiling = tonumber(ARGV[2])
local amount = tonumber(ARGV[3])
redis.call('HSETNX', ledger, 'prior', tostring(prior))
redis.call('HSETNX', ledger, 'spent', '0')
redis.call('HSETNX', ledger, 'reserved', '0')
if redis.call('EXISTS', reservation) == 1 then return 2 end
local used = tonumber(redis.call('HGET', ledger, 'prior'))
  + tonumber(redis.call('HGET', ledger, 'spent'))
  + tonumber(redis.call('HGET', ledger, 'reserved'))
if used + amount > ceiling then return 0 end
redis.call('HINCRBYFLOAT', ledger, 'reserved', amount)
redis.call('SET', reservation, tostring(amount))
return 1
"""

SETTLE_LUA = """
local amount = redis.call('GET', KEYS[2])
if not amount then return 0 end
redis.call('HINCRBYFLOAT', KEYS[1], 'reserved', -tonumber(amount))
redis.call('HINCRBYFLOAT', KEYS[1], 'spent', tonumber(ARGV[1]))
redis.call('DEL', KEYS[2])
return 1
"""


class BudgetLedger:
    """Reserva el costo máximo antes de llamar y liquida con el uso real informado.

    Las operaciones son scripts Lua atómicos: varias llamadas concurrentes no pueden
    superar el techo aunque reserven al mismo tiempo.
    """

    def __init__(self, redis: Any, cap: float = 0.95, prior: float = 0.0):
        if cap <= 0 or prior < 0:
            raise ValueError("Budget ceiling must be positive and previous spending nonnegative")
        self.redis, self.cap, self.prior = redis, cap, prior
        self.key = "panellab:budget:api"

    async def reserve(self, amount: float) -> str:
        if amount <= 0:
            raise ValueError("Reservation must be positive")
        reservation = f"panellab:budget:reservation:{uuid.uuid4().hex}"
        result = await self.redis.eval(RESERVE_LUA, 2, self.key, reservation, self.prior, self.cap, amount)
        if result != 1:
            raise BudgetExceeded("Shared API budget exhausted")
        return reservation

    async def settle(self, reservation: str, actual: float) -> None:
        if actual < 0:
            raise ValueError("Actual cost must be nonnegative")
        stored = await self.redis.get(reservation)
        if stored is None:
            return
        if actual > float(stored):
            # Una reserva es una cota superior deliberada. Superarla es un error de precio o
            # configuración, así que se conserva la reserva original.
            raise BudgetExceeded("Provider usage exceeded reserved upper bound")
        await self.redis.eval(SETTLE_LUA, 2, self.key, reservation, actual)

    async def release(self, reservation: str) -> None:
        """Libera una reserva cuando la llamada falló antes de que el proveedor facturara."""
        await self.settle(reservation, 0.0)

    async def summary(self) -> dict[str, float]:
        raw = await self.redis.hgetall(self.key)

        def number(key: str, default: float = 0.0) -> float:
            value = raw.get(key.encode(), raw.get(key))
            return float(value) if value is not None else default

        return {
            "prior_usd": number("prior", self.prior),
            "spent_usd": number("spent"),
            "reserved_usd": number("reserved"),
            "cap_usd": self.cap,
        }


def _token_upper(text: str) -> int:
    # Los bytes UTF-8 acotan de forma conservadora la cantidad de tokens de estos modelos;
    # cada llamador suma margen por protocolo y esquema.
    return len(text.encode("utf-8")) + 2048


def _strict_schema(schema: dict[str, Any]) -> dict[str, Any]:
    """El JSON Schema estricto de OpenAI exige que todos los campos sean requeridos."""
    if schema.get("type") == "object":
        schema["additionalProperties"] = False
        schema["required"] = list(schema.get("properties", {}))
    for value in schema.values():
        if isinstance(value, dict):
            _strict_schema(value)
        elif isinstance(value, list):
            for part in value:
                if isinstance(part, dict):
                    _strict_schema(part)
    return schema


class ModelClient:
    def __init__(self, settings: Any, redis: Any):
        self.mode = getattr(settings, "llm_mode", "demo")
        if self.mode not in {"demo", "live"}:
            raise LiveModeUnavailable("PANEL_LLM_MODE must be demo or live")
        self.base_url = str(getattr(settings, "llm_base_url", "https://api.openai.com/v1")).rstrip("/")
        self.chat_model = getattr(settings, "chat_model", "gpt-6-luna")
        self.reasoning_effort = getattr(settings, "reasoning_effort", "low")
        self.embedding_model = getattr(settings, "embedding_model", "text-embedding-3-small")
        self.dimensions = int(getattr(settings, "embedding_dimensions", 1536))
        self.max_output_tokens = int(getattr(settings, "max_output_tokens", 4000))
        self.ledger = BudgetLedger(
            redis, float(getattr(settings, "budget_cap_usd", 0.95)), float(getattr(settings, "budget_prior_usd", 0.0))
        )
        self.api_key = getattr(settings, "openai_api_key", None) or os.environ.get("OPENAI_API_KEY", "")
        if self.mode == "live":
            if not self.api_key or self.chat_model not in CHAT_MODELS or self.embedding_model not in EMBED_RATES:
                raise LiveModeUnavailable("Live mode requires an API key and a priced model allowlist")
            if self.dimensions < 1 or self.dimensions > 1536:
                raise LiveModeUnavailable("Invalid embedding dimension")

    @property
    def model_name(self) -> str:
        return self.chat_model if self.mode == "live" else DEMO_MODEL

    async def _post(
        self, path: str, payload: dict[str, Any], reservation: str, request_timeout: float
    ) -> dict[str, Any]:
        """POST con un reintento ante rechazos transitorios que el proveedor no factura."""
        for attempt in (1, 2):
            try:
                async with httpx.AsyncClient(timeout=request_timeout) as client:
                    response = await client.post(
                        f"{self.base_url}/{path}", headers={"Authorization": f"Bearer {self.api_key}"}, json=payload
                    )
                status = getattr(response, "status_code", 200)
                if status == 429 and _quota_error(response):
                    await self.ledger.release(reservation)
                    raise ProviderQuotaExceeded("La cuenta del proveedor no tiene crédito disponible")
                if status in RETRYABLE_STATUS and attempt == 1:
                    await asyncio.sleep(1.5)
                    continue
                response.raise_for_status()
                return response.json()
            except httpx.HTTPStatusError:
                # El proveedor respondió con un error: no hubo generación facturable.
                await self.ledger.release(reservation)
                raise
            except (httpx.ConnectError, httpx.ConnectTimeout):
                # La petición no llegó al proveedor.
                if attempt == 1:
                    await asyncio.sleep(1.5)
                    continue
                await self.ledger.release(reservation)
                raise
        raise RuntimeError("unreachable")  # pragma: no cover

    async def embed(self, text: str) -> list[float]:
        if self.mode == "demo":
            return demo_embedding(text, self.dimensions)
        rate = EMBED_RATES[self.embedding_model]
        reservation = await self.ledger.reserve(_token_upper(text) * rate / 1_000_000)
        with span(
            "embedding", **{"openinference.span.kind": "EMBEDDING", "embedding.model_name": self.embedding_model}
        ) as trace_span:
            data = await self._post(
                "embeddings",
                {"model": self.embedding_model, "input": text, "dimensions": self.dimensions},
                reservation,
                45,
            )
            trace_span.set_attribute("llm.token_count.total", data["usage"]["total_tokens"])
        await self.ledger.settle(reservation, data["usage"]["total_tokens"] * rate / 1_000_000)
        return data["data"][0]["embedding"]

    async def structured(self, role: str, context: dict[str, Any], schema: type[BaseModel]) -> Any:
        prompt = json.dumps(context, ensure_ascii=False, separators=(",", ":"), default=str)
        attributes = {
            "openinference.span.kind": "LLM",
            "llm.provider": "openai" if self.mode == "live" else "panellab-demo",
            "llm.system": "openai" if self.mode == "live" else "panellab-demo",
            "llm.model_name": self.model_name,
            "llm.input_messages.0.message.role": "system",
            "llm.input_messages.0.message.content": content_attr(role),
            "llm.input_messages.1.message.role": "user",
            "llm.input_messages.1.message.content": content_attr(prompt),
            "input.value": content_attr(prompt),
            "input.mime_type": "application/json",
            "panellab.output_schema": schema.__name__,
        }
        with span(f"llm.{schema.__name__}", **attributes) as trace_span:
            if self.mode == "demo":
                result = self._demo(role, context, schema)
                content, cost = result.model_dump_json(), 0.0
            else:
                content, cost = await self._live(role, prompt, schema, trace_span)
                result = schema.model_validate_json(content)
            trace_span.set_attribute("output.value", content_attr(content))
            trace_span.set_attribute("output.mime_type", "application/json")
            trace_span.set_attribute("llm.output_messages.0.message.role", "assistant")
            trace_span.set_attribute("llm.output_messages.0.message.content", content_attr(content))
            trace_span.set_attribute("llm.cost.total", cost)
            return result

    async def _live(self, role: str, prompt: str, schema: type[BaseModel], trace_span: Any) -> tuple[str, float]:
        spec = CHAT_MODELS[self.chat_model]
        schema_json = _strict_schema(schema.model_json_schema())
        input_bound = _token_upper(role + prompt + json.dumps(schema_json, ensure_ascii=False))
        if input_bound > spec.max_standard_input_tokens:
            raise BudgetExceeded("Prompt exceeds the verified standard-price token range")
        reserve_cost = (input_bound * spec.input_rate + self.max_output_tokens * spec.output_rate) / 1_000_000
        reservation = await self.ledger.reserve(reserve_cost)
        options = {"reasoning_effort": self.reasoning_effort} if spec.supports_reasoning_effort else {}
        trace_span.set_attribute(
            "llm.invocation_parameters", json.dumps({"max_completion_tokens": self.max_output_tokens, **options})
        )
        data = await self._post(
            "chat/completions",
            {
                "model": self.chat_model,
                "max_completion_tokens": self.max_output_tokens,
                **options,
                "messages": [{"role": "system", "content": role}, {"role": "user", "content": prompt}],
                "response_format": {
                    "type": "json_schema",
                    "json_schema": {"name": schema.__name__.lower(), "strict": True, "schema": schema_json},
                },
            },
            reservation,
            75,
        )
        usage = data["usage"]
        prompt_cost = usage["prompt_tokens"] * spec.input_rate / 1_000_000
        completion_cost = usage["completion_tokens"] * spec.output_rate / 1_000_000
        trace_span.set_attribute("llm.token_count.prompt", usage["prompt_tokens"])
        trace_span.set_attribute("llm.token_count.completion", usage["completion_tokens"])
        trace_span.set_attribute("llm.token_count.total", usage["total_tokens"])
        trace_span.set_attribute("llm.cost.prompt", prompt_cost)
        trace_span.set_attribute("llm.cost.completion", completion_cost)
        await self.ledger.settle(reservation, prompt_cost + completion_cost)
        return data["choices"][0]["message"]["content"], prompt_cost + completion_cost

    @staticmethod
    def _demo(role: str, context: dict[str, Any], schema: type[BaseModel]) -> Any:
        """Fixture determinista del circuito; nunca se presenta como salida de un LLM."""
        if schema.__name__ == "SupervisorDecision":
            profile = context["profiles"][context["question_count"] % len(context["profiles"])]
            criteria = {item["id"]: item for item in context["criteria"]}
            focus = [item for item in profile["focus"] if item in criteria]
            criterion_id = focus[context["question_count"] % len(focus)] if focus else context["criteria"][0]["id"]
            criterion = criteria[criterion_id]
            return schema(
                action="question",
                profile_id=profile["profile_id"],
                criterion_id=criterion_id,
                topic_id=f"topic-{context['question_count'] + 1}",
                reason="Cobertura secuencial de la rúbrica",
                search_query=" ".join(
                    f"{criterion.get('title', criterion_id)} {criterion.get('description', '')}".split()
                )[:300],
            )
        if schema.__name__ == "ReviewerQuestion":
            source = context.get("citations", [])
            if source:
                return schema(
                    text=(
                        f"¿Qué evidencia concreta respalda {context['criterion']['title'].lower()} "
                        "y cómo comprobaste ese avance?"
                    ),
                    basis="document",
                    citation_chunk_ids=[source[0]["chunk_id"]],
                )
            return schema(
                text=f"¿Qué evidencia falta para evaluar {context['criterion']['title'].lower()}?",
                basis="clarification",
                citation_chunk_ids=[],
            )
        if schema.__name__ == "AnswerAssessment":
            answer = context["answer"].lower()
            supports = any(word in answer for word in ("probamos", "medimos", "registro", "documento", "prueba"))
            citations = context.get("citations", [])
            return schema(
                status="partial" if supports else "missing",
                observation=(
                    "La respuesta menciona evidencia; conviene precisar el resultado y su fuente."
                    if supports
                    else "La respuesta requiere vincularse con evidencia verificable."
                ),
                evidence_stage="source_context" if citations else "unclear",
                supporting_chunk_ids=[citations[0]["chunk_id"]] if citations else [],
                next_action="Precisar qué actividad se realizó y adjuntar su resultado verificable.",
            )
        raise ValueError(f"No deterministic fixture for {schema.__name__}")
