"""Evaluacion de la recuperacion: Recall@k y Precision@k sobre un golden set.

Se mide la recuperacion, no la respuesta final: si los fragmentos correctos no llegan,
ningun prompt los va a salvar.

Corre las mismas preguntas contra los tres recuperadores (vectorial, BM25 e hibrido)
para que se vea si la fusion realmente aporta.

Uso:
    python evaluate.py
"""

import asyncio
import json
import logging
from pathlib import Path

from langchain_core.retrievers import BaseRetriever

from config import TOP_K
from retriever import RAGSystem

logger = logging.getLogger("rag.eval")

GOLDEN_SET = Path(__file__).parent / "golden_set.json"


def cargar_golden_set() -> list[dict]:
    casos = json.loads(GOLDEN_SET.read_text(encoding="utf-8"))
    logger.info("Golden set: %d preguntas", len(casos))
    return casos


async def evaluar(sistema: RAGSystem, retriever: BaseRetriever, casos: list[dict]) -> dict:
    """Recall@k: ¿aparecio el documento esperado? Precision@k: ¿cuantos de los k son relevantes?"""
    recalls: list[float] = []
    precisions: list[float] = []
    detalle: list[tuple[str, bool, float]] = []

    for caso in casos:
        docs = await sistema.retrieve_con(retriever, caso["pregunta"])
        fuentes = [d.metadata.get("fuente") for d in docs]

        # Recall@k binario: el documento esperado esta entre los k recuperados.
        encontrado = caso["documento_esperado"] in fuentes
        # Precision@k: proporcion de los k devueltos que son de una fuente relevante.
        relevantes = set(caso["fuentes_relevantes"])
        aciertos = sum(1 for f in fuentes if f in relevantes)
        precision = aciertos / len(docs) if docs else 0.0

        recalls.append(1.0 if encontrado else 0.0)
        precisions.append(precision)
        detalle.append((caso["pregunta"], encontrado, precision))

    n = len(casos) or 1
    return {
        "recall": sum(recalls) / n,
        "precision": sum(precisions) / n,
        "detalle": detalle,
    }


def imprimir_reporte(resultados: dict[str, dict], k: int) -> None:
    print(f"\n{'=' * 78}")
    print(f"REPORTE DE EVALUACION  (k={k}, {len(next(iter(resultados.values()))['detalle'])} preguntas)")
    print("=" * 78)

    print(f"\n{'Recuperador':<14} {'Recall@' + str(k):>10} {'Precision@' + str(k):>14}")
    print("-" * 40)
    for nombre, r in resultados.items():
        print(f"{nombre:<14} {r['recall']:>10.2f} {r['precision']:>14.2f}")

    print(f"\nDetalle por pregunta (recuperador hibrido):\n{'-' * 78}")
    for pregunta, encontrado, precision in resultados["hibrido"]["detalle"]:
        marca = "OK  " if encontrado else "FALLA"
        print(f"  [{marca}] P@{k}={precision:.2f}  {pregunta[:60]}")

    mejor = max(resultados.items(), key=lambda kv: (kv[1]["recall"], kv[1]["precision"]))
    print(f"\nMejor recall: {mejor[0]}")
    print("=" * 78)


async def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)-8s %(name)s | %(message)s")

    casos = cargar_golden_set()
    sistema = RAGSystem()

    resultados = {}
    for nombre, retriever in [
        ("vectorial", sistema.vectorial),
        ("bm25", sistema.bm25),
        ("hibrido", sistema.hibrido),
    ]:
        resultados[nombre] = await evaluar(sistema, retriever, casos)

    imprimir_reporte(resultados, TOP_K)


if __name__ == "__main__":
    asyncio.run(main())
