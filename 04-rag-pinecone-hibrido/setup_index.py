"""Crea el indice serverless de Pinecone si no existe, y valida que sea compatible.

Uso:
    python setup_index.py
"""

import logging

from pinecone import Pinecone, ServerlessSpec

from config import CLOUD, DIMENSION, EMBEDDING_MODEL, INDEX_NAME, METRICA, REGION, requerir

logger = logging.getLogger("rag.setup")


def get_pinecone() -> Pinecone:
    return Pinecone(api_key=requerir("PINECONE_API_KEY"))


def setup_index(pc: Pinecone | None = None) -> None:
    pc = pc or get_pinecone()

    if not pc.has_index(INDEX_NAME):
        logger.info(
            "Creando indice serverless '%s' (dim=%d, metrica=%s, %s/%s)",
            INDEX_NAME, DIMENSION, METRICA, CLOUD, REGION,
        )
        pc.create_index(
            name=INDEX_NAME,
            dimension=DIMENSION,
            metric=METRICA,
            spec=ServerlessSpec(cloud=CLOUD, region=REGION),
        )
        logger.info("Indice creado")
        return

    # El indice ya existe: verificamos que la dimension coincida ANTES de escribir.
    # Insertar vectores de 1536 en un indice de 768 falla, y el mensaje del error no
    # siempre deja claro cual es la causa.
    desc = pc.describe_index(INDEX_NAME)
    if desc.dimension != DIMENSION:
        raise RuntimeError(
            f"El indice '{INDEX_NAME}' tiene dimension {desc.dimension} pero "
            f"{EMBEDDING_MODEL} produce vectores de {DIMENSION}. Borra el indice o "
            f"usa otro INDEX_NAME."
        )
    logger.info("Indice '%s' ya existe (dim=%d). Nada que hacer.", INDEX_NAME, desc.dimension)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)-8s %(name)s | %(message)s")
    setup_index()
