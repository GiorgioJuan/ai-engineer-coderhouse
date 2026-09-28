"""Prueba de carga: 5 peticiones concurrentes contra la API.

Mide la latencia end-to-end de cada job (desde el POST hasta que queda en un estado
terminal) e imprime p50 / p95 / max. Ese p95 es el que hay que cruzar con el del
dashboard de Phoenix o LangSmith.

Uso:
    python scripts/carga.py
    python scripts/carga.py --n 5 --url http://localhost:8000
"""

import argparse
import asyncio
import statistics
import time
from typing import Any

import httpx

CONSULTAS = [
    "¿Cuál de nuestros servicios tiene peor latencia y cuánto tendría que mejorar para cumplir el SLA?",
    "¿El servicio de checkout cumple el SLA de latencia vigente?",
    "Compará la latencia de checkout y perfil, y decime cuál está mejor.",
    "¿Cuál es el p95 del servicio de búsqueda y qué dice la documentación de su arquitectura?",
    "¿Qué servicios incumplen el SLA y cuál es la brecha de cada uno?",
]

TERMINALES = {"DONE", "FAILED", "REJECTED", "WAITING_APPROVAL"}


async def una_peticion(cliente: httpx.AsyncClient, consulta: str, i: int) -> dict[str, Any]:
    inicio = time.perf_counter()
    try:
        r = await cliente.post("/tasks", json={"consulta": consulta})
        r.raise_for_status()
        job_id = r.json()["job_id"]

        # Polling hasta estado terminal.
        estado = "PENDING"
        while estado not in TERMINALES:
            await asyncio.sleep(0.5)
            s = await cliente.get(f"/tasks/{job_id}")
            s.raise_for_status()
            estado = s.json()["estado"]

        elapsed = time.perf_counter() - inicio
        print(f"  [{i}] {job_id}  {estado:<18} {elapsed:6.2f}s")
        return {"ok": True, "estado": estado, "elapsed": elapsed, "job_id": job_id}

    except Exception as exc:
        elapsed = time.perf_counter() - inicio
        print(f"  [{i}] ERROR {type(exc).__name__}: {exc}")
        return {"ok": False, "estado": "ERROR", "elapsed": elapsed, "error": str(exc)}


def percentil(valores: list[float], p: float) -> float:
    ordenados = sorted(valores)
    idx = min(len(ordenados) - 1, max(0, round(p * len(ordenados)) - 1))
    return ordenados[idx]


async def main() -> None:
    ap = argparse.ArgumentParser(description="Prueba de carga de la API")
    ap.add_argument("--url", default="http://localhost:8000")
    ap.add_argument("--n", type=int, default=5)
    ap.add_argument("--timeout", type=float, default=180.0)
    args = ap.parse_args()

    print(f"\nLanzando {args.n} peticiones concurrentes contra {args.url}\n")
    inicio = time.perf_counter()

    async with httpx.AsyncClient(base_url=args.url, timeout=args.timeout) as cliente:
        tareas = [
            una_peticion(cliente, CONSULTAS[i % len(CONSULTAS)], i + 1) for i in range(args.n)
        ]
        resultados = await asyncio.gather(*tareas)

    total = time.perf_counter() - inicio
    latencias = [r["elapsed"] for r in resultados if r["ok"]]
    ok = len(latencias)

    print(f"\n{'=' * 60}")
    print(f"{ok}/{args.n} completadas en {total:.2f}s de reloj")
    if latencias:
        print(f"  p50 : {percentil(latencias, 0.50):6.2f}s")
        print(f"  p95 : {percentil(latencias, 0.95):6.2f}s")
        print(f"  max : {max(latencias):6.2f}s")
        print(f"  media: {statistics.fmean(latencias):5.2f}s")
    print("=" * 60)
    print("\nCruzá este p95 con el del dashboard, y sacá de ahí el costo por ejecución.")


if __name__ == "__main__":
    asyncio.run(main())
