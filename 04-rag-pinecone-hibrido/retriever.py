"""Recuperador hibrido: Pinecone (semantico) + BM25 (lexico), fusionados con Ensemble.

Por que hibrido: la busqueda vectorial encuentra significado parecido pero se le escapan
los terminos exactos (nombres de funcion, identificadores, versiones). BM25 acierta
justo ahi. EnsembleRetriever fusiona los dos rankings con Reciprocal Rank Fusion, que
usa las posiciones y no los puntajes, asi no hay que normalizar escalas distintas.

Uso:
    python retriever.py "que es el efecto Lost in the Middle"
"""

import logging

from langchain_classic.retrievers import EnsembleRetriever
from langchain_community.retrievers import BM25Retriever
from langchain_core.documents import Document
from langchain_core.retrievers import BaseRetriever
from langchain_pinecone import PineconeVectorStore

from config import INDEX_NAME, NAMESPACE, PESOS_ENSEMBLE, TOP_K, get_embeddings
from ingest import cargar_documentos, fragmentar
from setup_index import get_pinecone

logger = logging.getLogger("rag.retriever")


class RAGSystem:
    """Encapsula los tres recuperadores. `retrieve()` usa el hibrido."""

    def __init__(self, top_k: int = TOP_K) -> None:
        self.top_k = top_k

        indice = get_pinecone().Index(INDEX_NAME)
        store = PineconeVectorStore(
            index=indice, embedding=get_embeddings(), namespace=NAMESPACE
        )
        self.vectorial: BaseRetriever = store.as_retriever(search_kwargs={"k": top_k})

        # BM25 corre en proceso, asi que necesita los fragmentos en memoria. Se
        # reconstruyen desde ./data con el mismo splitter que uso la ingesta, para que
        # el corpus lexico y el vectorial sean identicos. En produccion se persistiria
        # el indice BM25, o se usarian los vectores sparse de Pinecone.
        chunks = fragmentar(cargar_documentos())
        self.bm25 = BM25Retriever.from_documents(chunks)
        self.bm25.k = top_k

        self.hibrido = EnsembleRetriever(
            retrievers=[self.vectorial, self.bm25],
            weights=PESOS_ENSEMBLE,
        )
        logger.info(
            "RAGSystem listo (top_k=%d, pesos vectorial/bm25=%s)", top_k, PESOS_ENSEMBLE
        )

    async def retrieve(self, query: str) -> list[Document]:
        """Top-k del recuperador hibrido."""
        # Ensemble fusiona dos listas, asi que puede devolver mas de k: se recorta.
        docs = await self.hibrido.ainvoke(query)
        return docs[: self.top_k]

    async def retrieve_con(self, retriever: BaseRetriever, query: str) -> list[Document]:
        """Igual que retrieve() pero con un recuperador puntual (para comparar en la evaluacion)."""
        return (await retriever.ainvoke(query))[: self.top_k]


if __name__ == "__main__":
    import asyncio
    import sys

    logging.basicConfig(level=logging.INFO, format="%(levelname)-8s %(name)s | %(message)s")
    consulta = " ".join(sys.argv[1:]) or "que es el efecto Lost in the Middle"

    async def _main() -> None:
        docs = await RAGSystem().retrieve(consulta)
        print(f"\nConsulta: {consulta}\n")
        for i, d in enumerate(docs, 1):
            print(f"{i}. [{d.metadata.get('fuente')}] seccion: {d.metadata.get('seccion')}")
            print(f"   {d.page_content[:110].replace(chr(10), ' ')}...\n")

    asyncio.run(_main())
