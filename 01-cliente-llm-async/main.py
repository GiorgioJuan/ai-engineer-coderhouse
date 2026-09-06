"""Script de validación: misma pregunta, modo normal y modo streaming.

Uso:
    python main.py                 # usa LLM_PROVIDER del .env
    python main.py anthropic       # fuerza un proveedor
    python main.py openai anthropic  # corre los dos, concurrentemente
"""

import asyncio
import os
import sys

from dotenv import load_dotenv
from pydantic import ValidationError

from clients import AsyncLLMManager
from schemas import ChatMessage, LLMConfig, ModelParams, Provider, Role

PROMPT = "¿Qué es la entropía? Respondé en dos o tres oraciones."

DEFAULT_MODELS = {
    Provider.OPENAI: "gpt-4o-mini",
    Provider.ANTHROPIC: "claude-sonnet-5",
}


def build_manager(provider: Provider) -> AsyncLLMManager:
    config = LLMConfig(
        provider=provider,
        openai_api_key=os.getenv("OPENAI_API_KEY") or None,
        anthropic_api_key=os.getenv("ANTHROPIC_API_KEY") or None,
    )
    params = ModelParams(
        model=os.getenv(f"{provider.value.upper()}_MODEL") or DEFAULT_MODELS[provider],
        temperature=float(os.getenv("TEMPERATURE", "0.7")),
        max_tokens=int(os.getenv("MAX_TOKENS", "512")),
        timeout=float(os.getenv("TIMEOUT", "30")),
    )
    return AsyncLLMManager(config, params)


def build_messages() -> list[ChatMessage]:
    return [
        ChatMessage(role=Role.SYSTEM, content="Sos un divulgador científico conciso."),
        ChatMessage(role=Role.USER, content=PROMPT),
    ]


async def demo_normal(provider: Provider) -> None:
    manager = build_manager(provider)
    res = await manager.generate(build_messages())
    print(f"\n--- [{provider.value}] modo normal ---")
    if not res.ok:
        print(f"error controlado -> {res.error}")
        return
    print(res.content)
    print(
        f"[{res.model} | in={res.input_tokens} out={res.output_tokens} "
        f"| {res.elapsed:.2f}s]"
    )


async def demo_streaming(provider: Provider) -> None:
    manager = build_manager(provider)
    print(f"\n--- [{provider.value}] modo streaming ---")
    async for token in manager.stream(build_messages()):
        print(token, end="", flush=True)
    print()


async def safe(provider: Provider, demo) -> None:
    try:
        await demo(provider)
    except ValidationError as exc:
        print(f"[{provider.value}] configuración inválida: {exc}")


async def main() -> None:
    load_dotenv()

    args = [a.lower() for a in sys.argv[1:]]
    names = args or [os.getenv("LLM_PROVIDER", "openai")]
    try:
        providers = [Provider(n) for n in names]
    except ValueError:
        print(f"Proveedores válidos: {[p.value for p in Provider]}")
        return

    # Las respuestas completas se piden concurrentemente con gather: no hay razón
    # para esperar a que termine una para empezar la otra.
    await asyncio.gather(*(safe(p, demo_normal) for p in providers))

    # El streaming va secuencial: si no, los tokens de ambos se mezclan en pantalla.
    for p in providers:
        await safe(p, demo_streaming)


if __name__ == "__main__":
    asyncio.run(main())
