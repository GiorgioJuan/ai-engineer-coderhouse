"""Servidor para la captura de evidencia, con presupuesto persistente de USD 0,95.

Ejecutar desde la carpeta del modulo: python -m scripts.servidor_presupuesto
Un solo proceso/worker debe usar este archivo de presupuesto. No borrar el registro
entre reintentos de una misma entrega. No guarda claves, prompts ni respuestas.
"""

import asyncio
import json
import os
from pathlib import Path

import httpx

MODEL = "gpt-4o-mini"
MAX_OUTPUT = 1024
# Unidades de USD 10^-8. Tarifas standard, sin descontar cache.
INPUT_RATE = 15
OUTPUT_RATE = 60
LIMIT = 95_000_000
# Reserva conservadora: contexto completo de entrada MAS salida maxima.
RESERVE = 128_000 * INPUT_RATE + MAX_OUTPUT * OUTPUT_RATE
LEDGER = Path(os.getenv("BUDGET_LEDGER", "screenshots/presupuesto.json"))


class BudgetTransport(httpx.AsyncBaseTransport):
    def __init__(self, path=LEDGER, inner=None):
        self.path = Path(path)
        self.inner = inner or httpx.AsyncHTTPTransport(retries=0)
        self.lock = asyncio.Lock()
        self.data = json.loads(self.path.read_text()) if self.path.exists() else {
            "model": MODEL, "limit_usd": LIMIT / 1e8, "charged_e8": 0, "calls": []
        }

    async def save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temp = self.path.with_suffix(".tmp")
        temp.write_text(json.dumps(self.data, indent=2), encoding="utf-8")
        # Windows puede retener brevemente el archivo mientras otro proceso lo lee.
        for attempt in range(20):
            try:
                temp.replace(self.path)
                return
            except PermissionError:
                if attempt == 19:
                    raise
                await asyncio.sleep(0.05)

    async def handle_async_request(self, request):
        body = json.loads(request.content)
        maximum = body.get("max_completion_tokens", body.get("max_tokens"))
        if (request.url.host != "api.openai.com"
                or request.url.path != "/v1/chat/completions"
                or body.get("model") != MODEL
                or not isinstance(maximum, int) or not 0 < maximum <= MAX_OUTPUT
                or body.get("stream") or body.get("n", 1) != 1
                or body.get("service_tier", "default") != "default"):
            raise RuntimeError("Solicitud fuera de las condiciones del presupuesto")
        async with self.lock:
            if self.data["charged_e8"] + RESERVE > LIMIT:
                raise RuntimeError("Presupuesto agotado: llamada bloqueada ANTES del envio")
            record = {"status": "reserved", "charged_e8": RESERVE}
            self.data["calls"].append(record)
            self.data["charged_e8"] += RESERVE
            await self.save()
        # Si hay error/timeout, la reserva se conserva por prudencia.
        response = await self.inner.handle_async_request(request)
        await response.aread()
        if response.is_success:
            usage = response.json().get("usage", {})
            prompt, completion = usage.get("prompt_tokens"), usage.get("completion_tokens")
            if isinstance(prompt, int) and isinstance(completion, int):
                cost = prompt * INPUT_RATE + completion * OUTPUT_RATE
                async with self.lock:
                    self.data["charged_e8"] += cost - RESERVE
                    record.update(status="completed", prompt_tokens=prompt,
                                  completion_tokens=completion, charged_e8=cost)
                    await self.save()
        return response

    async def aclose(self):
        await self.inner.aclose()


def main():
    import uvicorn
    from langchain_openai import ChatOpenAI
    import app.graph as graph

    client = httpx.AsyncClient(transport=BudgetTransport(), timeout=60.0)
    model = ChatOpenAI(model=MODEL, temperature=0, max_tokens=MAX_OUTPUT,
                       max_retries=0, streaming=False, http_async_client=client,
                       base_url="https://api.openai.com/v1")
    graph.build_model = lambda: model
    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, workers=1)


if __name__ == "__main__":
    main()
