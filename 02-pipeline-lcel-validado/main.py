"""Mini-script de prueba del pipeline.

Uso:
    python main.py
"""

import asyncio
import logging

from dotenv import load_dotenv

from chain import build_chain, process_text

TEXTOS = {
    "log de error": (
        "2024-03-11 04:12:07 ERROR api-gateway: la API en FastAPI dejo de responder. "
        "El pool de conexiones a PostgreSQL se agoto (100/100) y Redis empezo a devolver "
        "timeouts. Se perdieron peticiones de checkout durante 20 minutos."
    ),
    "descripcion de arquitectura": (
        "El servicio de recomendaciones corre en Kubernetes, consume eventos de Kafka y "
        "guarda los embeddings en Pinecone. El entrenamiento usa PyTorch en instancias GPU."
    ),
    "texto ambiguo (prueba de estres)": (
        "Ayer estuvo raro todo, medio lento, capaz era la conexion. Nadie se quejo mucho."
    ),
}


async def main() -> None:
    load_dotenv()
    logging.basicConfig(
        level=logging.INFO,
        format="%(levelname)-8s %(name)s | %(message)s",
    )

    chain = build_chain()  # se construye una sola vez y se reutiliza

    for titulo, texto in TEXTOS.items():
        print(f"\n{'=' * 70}\n{titulo}\n{'=' * 70}")
        resultado = await process_text(texto, chain)
        if resultado is None:
            print(">> Sin resultado valido tras los reintentos.")
        else:
            print(resultado.model_dump_json(indent=2))


if __name__ == "__main__":
    asyncio.run(main())
