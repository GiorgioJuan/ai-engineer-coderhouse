"""Clientes asíncronos de LLM detrás de una interfaz común.

- `BaseLLMClient` define el contrato: `generate()` y `stream()`.
- `OpenAIClient` / `AnthropicClient` esconden las diferencias de cada SDK.
- `AsyncLLMManager` elige la implementación según la configuración (Factory).
"""

import asyncio
import time
from abc import ABC, abstractmethod
from collections.abc import AsyncIterator

from schemas import ChatMessage, LLMConfig, ModelParams, ModelResponse, Provider, Role


class BaseLLMClient(ABC):
    def __init__(self, config: LLMConfig, params: ModelParams) -> None:
        self.config = config
        self.params = params

    @abstractmethod
    async def generate(self, messages: list[ChatMessage]) -> ModelResponse:
        """Respuesta completa, en una sola llamada."""

    @abstractmethod
    def stream(self, messages: list[ChatMessage]) -> AsyncIterator[str]:
        """Generador asíncrono que va cediendo fragmentos de texto."""

    # -- helpers compartidos -------------------------------------------------

    @property
    @abstractmethod
    def provider(self) -> Provider: ...

    def _error(self, exc: Exception) -> ModelResponse:
        """Traduce cualquier fallo (red, rate limit, auth) a una respuesta controlada."""
        name = type(exc).__name__
        if "RateLimit" in name:
            detail = "rate limit alcanzado, reintentá más tarde"
        elif "Authentication" in name or "PermissionDenied" in name:
            detail = "API key inválida o sin permisos"
        elif isinstance(exc, (asyncio.TimeoutError, TimeoutError)):
            detail = f"timeout tras {self.params.timeout}s"
        elif "Connection" in name or "APIConnection" in name:
            detail = "no se pudo conectar con el proveedor"
        else:
            detail = str(exc) or name
        return ModelResponse(
            provider=self.provider,
            model=self.params.model,
            ok=False,
            error=f"{name}: {detail}",
        )

    @staticmethod
    def _split_system(messages: list[ChatMessage]) -> tuple[str | None, list[ChatMessage]]:
        """Anthropic recibe el system prompt aparte, no dentro de `messages`."""
        system = next((m.content for m in messages if m.role is Role.SYSTEM), None)
        rest = [m for m in messages if m.role is not Role.SYSTEM]
        return system, rest


class OpenAIClient(BaseLLMClient):
    provider = Provider.OPENAI

    def __init__(self, config: LLMConfig, params: ModelParams) -> None:
        super().__init__(config, params)
        from openai import AsyncOpenAI  # import diferido: solo si se usa este proveedor

        self._client = AsyncOpenAI(
            api_key=config.openai_api_key.get_secret_value(),
            timeout=params.timeout,
        )

    async def generate(self, messages: list[ChatMessage]) -> ModelResponse:
        started = time.perf_counter()
        try:
            async with asyncio.timeout(self.params.timeout):
                res = await self._client.chat.completions.create(
                    model=self.params.model,
                    messages=[m.model_dump(mode="json") for m in messages],
                    temperature=self.params.temperature,
                    max_tokens=self.params.max_tokens,
                )
        except Exception as exc:
            return self._error(exc)

        usage = res.usage
        return ModelResponse(
            provider=self.provider,
            model=res.model,
            content=res.choices[0].message.content or "",
            input_tokens=usage.prompt_tokens if usage else None,
            output_tokens=usage.completion_tokens if usage else None,
            elapsed=time.perf_counter() - started,
        )

    async def stream(self, messages: list[ChatMessage]) -> AsyncIterator[str]:
        try:
            stream = await self._client.chat.completions.create(
                model=self.params.model,
                messages=[m.model_dump(mode="json") for m in messages],
                temperature=self.params.temperature,
                max_tokens=self.params.max_tokens,
                stream=True,
            )
            async for chunk in stream:
                delta = chunk.choices[0].delta.content
                if delta:
                    yield delta
        except Exception as exc:
            yield f"\n[error] {self._error(exc).error}"


class AnthropicClient(BaseLLMClient):
    provider = Provider.ANTHROPIC

    def __init__(self, config: LLMConfig, params: ModelParams) -> None:
        super().__init__(config, params)
        from anthropic import AsyncAnthropic

        self._client = AsyncAnthropic(
            api_key=config.anthropic_api_key.get_secret_value(),
            timeout=params.timeout,
        )

    async def generate(self, messages: list[ChatMessage]) -> ModelResponse:
        started = time.perf_counter()
        system, rest = self._split_system(messages)
        try:
            async with asyncio.timeout(self.params.timeout):
                res = await self._client.messages.create(
                    model=self.params.model,
                    system=system or "",
                    messages=[m.model_dump(mode="json") for m in rest],
                    max_tokens=self.params.max_tokens,
                    # Sin `temperature`: el SDK 1.x la removió de la Messages API.
                )
        except Exception as exc:
            return self._error(exc)

        # `content` es una lista de bloques; nos quedamos con los de texto.
        text = "".join(b.text for b in res.content if getattr(b, "type", None) == "text")
        return ModelResponse(
            provider=self.provider,
            model=res.model,
            content=text,
            input_tokens=res.usage.input_tokens,
            output_tokens=res.usage.output_tokens,
            elapsed=time.perf_counter() - started,
        )

    async def stream(self, messages: list[ChatMessage]) -> AsyncIterator[str]:
        system, rest = self._split_system(messages)
        try:
            async with self._client.messages.stream(
                model=self.params.model,
                system=system or "",
                messages=[m.model_dump(mode="json") for m in rest],
                max_tokens=self.params.max_tokens,
            ) as stream:
                async for text in stream.text_stream:
                    yield text
        except Exception as exc:
            yield f"\n[error] {self._error(exc).error}"


class AsyncLLMManager:
    """Factory + fachada. El resto de la app solo habla con esta clase."""

    _REGISTRY: dict[Provider, type[BaseLLMClient]] = {
        Provider.OPENAI: OpenAIClient,
        Provider.ANTHROPIC: AnthropicClient,
    }

    def __init__(self, config: LLMConfig, params: ModelParams) -> None:
        try:
            client_cls = self._REGISTRY[config.provider]
        except KeyError:  # pragma: no cover - Provider es un Enum cerrado
            raise ValueError(f"Proveedor no soportado: {config.provider}") from None
        self.client: BaseLLMClient = client_cls(config, params)

    async def generate(self, messages: list[ChatMessage]) -> ModelResponse:
        return await self.client.generate(messages)

    def stream(self, messages: list[ChatMessage]) -> AsyncIterator[str]:
        return self.client.stream(messages)
