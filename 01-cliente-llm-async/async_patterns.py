"""Demo de los patrones de la unidad: gather + Semaphore + timeout.

Simula un batch de embeddings. No necesita API keys: la latencia de red es fingida.
Responde la pregunta de reflexion: nunca se hace gather de 10.000 llamadas a la vez;
se encolan todas y el semaforo deja correr solo N en simultaneo.

Uso: python async_patterns.py
"""

import asyncio
import random
import time

MAX_CONCURRENCIA = 3
TIMEOUT_POR_LLAMADA = 2.0


async def get_embedding(text: str, sem: asyncio.Semaphore) -> dict:
    async with sem:  # respeta el limite de llamadas en paralelo (evita el 429)
        latency = random.uniform(0.5, 2.5)
        try:
            async with asyncio.timeout(TIMEOUT_POR_LLAMADA):
                await asyncio.sleep(latency)  # await, NO time.sleep: bloquearia el loop
                return {"text": text, "dim": 1536, "ok": True}
        except TimeoutError:
            return {"text": text, "ok": False, "error": "timeout"}


async def embed_batch(texts: list[str]) -> list[dict]:
    sem = asyncio.Semaphore(MAX_CONCURRENCIA)
    tasks = [get_embedding(t, sem) for t in texts]
    # return_exceptions=True: un fallo aislado no tumba el lote entero.
    return await asyncio.gather(*tasks, return_exceptions=True)


async def main() -> None:
    textos = [f"documento_{i}" for i in range(8)]

    inicio = time.perf_counter()
    resultados = await embed_batch(textos)
    elapsed = time.perf_counter() - inicio

    ok = [r for r in resultados if isinstance(r, dict) and r.get("ok")]
    fallidos = [r for r in resultados if isinstance(r, dict) and not r.get("ok")]

    print(f"Procesados OK: {len(ok)}/{len(textos)} en {elapsed:.2f}s "
          f"(concurrencia maxima: {MAX_CONCURRENCIA})")
    for f in fallidos:
        print(f"  Fallo: {f['text']} -> {f['error']}")


if __name__ == "__main__":
    asyncio.run(main())
