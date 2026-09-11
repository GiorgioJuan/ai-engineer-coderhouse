"""Pipeline de ingesta a Pinecone con metadatos enriquecidos.

Cada fragmento se sube con: el texto original, el archivo de origen, la categoria del
documento y la seccion del markdown de la que salio. Guardar el texto en los metadatos
evita tener que consultar otra base para reconstruir el contexto despues de la busqueda.

Uso:
    python ingest.py
    python ingest.py --force   # borra el namespace y reindexa
"""

import argparse
import logging
import re

from langchain_core.documents import Document
from langchain_pinecone import PineconeVectorStore
from langchain_text_splitters import RecursiveCharacterTextSplitter

from config import (
    CHUNK_OVERLAP, CHUNK_SIZE, DATA_DIR, INDEX_NAME, NAMESPACE, get_embeddings,
)
from setup_index import get_pinecone, setup_index

logger = logging.getLogger("rag.ingest")

FRONTMATTER = re.compile(r"^---\s*\ncategoria:\s*(.+?)\s*\n---\s*\n", re.DOTALL)
ENCABEZADO = re.compile(r"^#{1,3}\s+(.+)$", re.MULTILINE)


def cargar_documentos() -> list[Document]:
    """Lee ./data separando el frontmatter con la categoria del cuerpo del documento."""
    archivos = sorted([*DATA_DIR.glob("*.md"), *DATA_DIR.glob("*.txt")])
    if not archivos:
        raise FileNotFoundError(f"No hay archivos en {DATA_DIR}")

    docs = []
    for f in archivos:
        texto = f.read_text(encoding="utf-8")
        m = FRONTMATTER.match(texto)
        categoria = m.group(1) if m else "sin-categoria"
        cuerpo = texto[m.end():] if m else texto
        docs.append(
            Document(page_content=cuerpo, metadata={"fuente": f.name, "categoria": categoria})
        )
    logger.info("Leidos %d documentos", len(docs))
    return docs


def _seccion_de(texto: str, cuerpo_completo: str) -> str:
    """Encabezado markdown mas cercano por encima del fragmento.

    En un corpus de PDFs este seria el numero de pagina; en markdown, la seccion es el
    equivalente util para que el usuario sepa de donde salio la cita.
    """
    pos = cuerpo_completo.find(texto[:80])
    if pos == -1:
        return "sin-seccion"
    encabezados = [m for m in ENCABEZADO.finditer(cuerpo_completo) if m.start() <= pos]
    return encabezados[-1].group(1).strip() if encabezados else "sin-seccion"


def fragmentar(docs: list[Document]) -> list[Document]:
    """Chunking en tokens, enriqueciendo los metadatos de cada fragmento."""
    splitter = RecursiveCharacterTextSplitter.from_tiktoken_encoder(
        chunk_size=CHUNK_SIZE, chunk_overlap=CHUNK_OVERLAP
    )
    chunks: list[Document] = []
    for doc in docs:
        for i, chunk in enumerate(splitter.split_documents([doc])):
            chunk.metadata = {
                **chunk.metadata,
                "seccion": _seccion_de(chunk.page_content, doc.page_content),
                "chunk_index": i,
                "id": f"{doc.metadata['fuente']}#{i}",
            }
            chunks.append(chunk)

    logger.info(
        "Generados %d fragmentos (chunk_size=%d tokens, overlap=%d)",
        len(chunks), CHUNK_SIZE, CHUNK_OVERLAP,
    )
    return chunks


def ingest(force: bool = False) -> PineconeVectorStore:
    pc = get_pinecone()
    setup_index(pc)
    indice = pc.Index(INDEX_NAME)

    stats = indice.describe_index_stats()
    ya_hay = stats.namespaces.get(NAMESPACE)
    if ya_hay and ya_hay.vector_count > 0:
        if not force:
            logger.info(
                "El namespace '%s' ya tiene %d vectores. Usa --force para reindexar.",
                NAMESPACE, ya_hay.vector_count,
            )
            return PineconeVectorStore(
                index=indice, embedding=get_embeddings(), namespace=NAMESPACE
            )
        logger.info("--force: borrando el namespace '%s'", NAMESPACE)
        indice.delete(delete_all=True, namespace=NAMESPACE)

    chunks = fragmentar(cargar_documentos())
    store = PineconeVectorStore.from_documents(
        documents=chunks,
        embedding=get_embeddings(),
        index_name=INDEX_NAME,
        namespace=NAMESPACE,
        ids=[c.metadata["id"] for c in chunks],
    )
    logger.info("Subidos %d fragmentos al namespace '%s'", len(chunks), NAMESPACE)
    return store


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)-8s %(name)s | %(message)s")
    ap = argparse.ArgumentParser(description="Ingesta a Pinecone")
    ap.add_argument("--force", action="store_true", help="borra el namespace y reindexa")
    ingest(force=ap.parse_args().force)
