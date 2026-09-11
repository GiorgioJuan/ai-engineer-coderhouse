"""Prueba end-to-end del sistema RAG.

Corre dos consultas: una respondible con los documentos de ./data y una pregunta
trampa cuya respuesta no esta en ningun lado, para verificar que el modelo no alucine.

Uso:
    python main.py
"""

import asyncio
import logging

from dotenv import load_dotenv

from ingest import ingest
from rag import build_chain, get_rag_response

PREGUNTAS = [
    (
        "respondible",
        "¿Que valor de top_k conviene usar al recuperar fragmentos y por que?",
    ),
    (
        "trampa (no esta en los documentos)",
        "¿Cuanto cuesta el modelo GPT-4o por millon de tokens de entrada?",
    ),
]


async def main() -> None:
    load_dotenv()
    logging.basicConfig(level=logging.INFO, format="%(levelname)-8s %(name)s | %(message)s")

    ingest()  # indexa solo si hace falta
    chain = build_chain()

    for etiqueta, pregunta in PREGUNTAS:
        print(f"\n{'=' * 72}\n{etiqueta}: {pregunta}\n{'=' * 72}")
        r = await get_rag_response(pregunta, chain)
        print(f"\ntiene_respuesta : {r.tiene_respuesta}")
        print(f"referencias     : {r.referencias or '(ninguna)'}")
        print(f"respuesta       : {r.respuesta}")


if __name__ == "__main__":
    asyncio.run(main())
