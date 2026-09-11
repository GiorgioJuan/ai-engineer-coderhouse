"""Ingesta: lee los documentos de ./data, los fragmenta y los persiste en ChromaDB.

Este modulo tambien es el unico lugar donde se define el modelo de embeddings y como
se abre la coleccion. `rag.py` importa esas funciones en vez de repetirlas: asi es
imposible indexar con un modelo y consultar con otro, que es el error mas comun (y mas
silencioso) de un sistema de recuperacion.

Uso:
    python ingest.py           # indexa solo si la coleccion esta vacia
    python ingest.py --force   # borra y reindexa desde cero
"""

import argparse
import logging
import os
from pathlib import Path

from langchain_chroma import Chroma
from langchain_core.documents import Document
from langchain_openai import OpenAIEmbeddings
from langchain_text_splitters import RecursiveCharacterTextSplitter

logger = logging.getLogger("rag.ingest")

BASE_DIR = Path(__file__).parent
DATA_DIR = BASE_DIR / "data"
PERSIST_DIR = BASE_DIR / "vectorstore"
COLLECTION = "manual-ingenieria-ia"

# Chunking en TOKENS, no en caracteres: 500 con 50 de solapamiento.
CHUNK_SIZE = 500
CHUNK_OVERLAP = 50


def get_embeddings() -> OpenAIEmbeddings:
    """Fuente unica de verdad del modelo de embeddings (indexacion y consulta)."""
    return OpenAIEmbeddings(model=os.getenv("EMBEDDING_MODEL", "text-embedding-3-small"))


def get_vectorstore() -> Chroma:
    """Abre (o crea) la coleccion persistente en ./vectorstore."""
    return Chroma(
        collection_name=COLLECTION,
        embedding_function=get_embeddings(),
        persist_directory=str(PERSIST_DIR),
    )


def cargar_documentos() -> list[Document]:
    """Lee todos los .md y .txt de ./data. El metadato `fuente` es el nombre de archivo."""
    archivos = sorted([*DATA_DIR.glob("*.md"), *DATA_DIR.glob("*.txt")])
    if not archivos:
        raise FileNotFoundError(f"No hay archivos .md ni .txt en {DATA_DIR}")

    docs = [
        Document(page_content=f.read_text(encoding="utf-8"), metadata={"fuente": f.name})
        for f in archivos
    ]
    logger.info("Leidos %d documentos de %s", len(docs), DATA_DIR.name)
    return docs


def fragmentar(docs: list[Document]) -> list[Document]:
    """Chunking recursivo contando tokens con el mismo tokenizador que usa el modelo."""
    splitter = RecursiveCharacterTextSplitter.from_tiktoken_encoder(
        chunk_size=CHUNK_SIZE,
        chunk_overlap=CHUNK_OVERLAP,
    )
    chunks = splitter.split_documents(docs)
    logger.info(
        "Generados %d fragmentos (chunk_size=%d tokens, overlap=%d)",
        len(chunks), CHUNK_SIZE, CHUNK_OVERLAP,
    )
    return chunks


def ya_indexado(store: Chroma) -> bool:
    """Evita volver a pagar la ingesta en cada corrida."""
    try:
        return bool(store.get(limit=1)["ids"])
    except Exception:
        return False


def ingest(force: bool = False) -> Chroma:
    store = get_vectorstore()

    if force:
        # `reset_collection` vacia la coleccion a traves de Chroma. Borrar la carpeta a
        # mano falla en Windows si algun cliente todavia tiene los archivos abiertos.
        logger.info("--force: vaciando la coleccion")
        store.reset_collection()
    elif ya_indexado(store):
        logger.info("La coleccion ya tiene datos, no se reindexa (usa --force para rehacerla)")
        return store

    chunks = fragmentar(cargar_documentos())
    store.add_documents(chunks)
    logger.info("Indexados %d fragmentos en %s", len(chunks), PERSIST_DIR.name)
    return store


if __name__ == "__main__":
    from dotenv import load_dotenv

    load_dotenv()
    logging.basicConfig(level=logging.INFO, format="%(levelname)-8s %(name)s | %(message)s")

    ap = argparse.ArgumentParser(description="Indexa ./data en ChromaDB")
    ap.add_argument("--force", action="store_true", help="borra la base y reindexa")
    ingest(force=ap.parse_args().force)
