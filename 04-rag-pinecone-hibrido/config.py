"""Configuracion compartida: entorno, indice y modelo de embeddings.

Todo lo que tiene que coincidir entre la ingesta y la consulta vive aca. En particular
el modelo de embeddings y la dimension del indice: si se definieran por separado en cada
script, tarde o temprano se desincronizan.
"""

import os
from pathlib import Path

from dotenv import load_dotenv
from langchain_openai import OpenAIEmbeddings

load_dotenv()

BASE_DIR = Path(__file__).parent
DATA_DIR = BASE_DIR / "data"

INDEX_NAME = os.getenv("INDEX_NAME", "manual-ingenieria-ia")
NAMESPACE = os.getenv("PINECONE_NAMESPACE", "docs-v1")
CLOUD = os.getenv("PINECONE_CLOUD", "aws")
REGION = os.getenv("PINECONE_REGION", "us-east-1")

EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "text-embedding-3-small")
# Debe coincidir con la salida del modelo de arriba. text-embedding-3-small = 1536,
# text-embedding-3-large = 3072.
DIMENSIONES = {"text-embedding-3-small": 1536, "text-embedding-3-large": 3072}
DIMENSION = DIMENSIONES.get(EMBEDDING_MODEL, 1536)
METRICA = "cosine"

# Rango recomendado: 500-800 tokens. Muy chicos pierden contexto, muy grandes diluyen
# la precision del embedding.
CHUNK_SIZE = 600
CHUNK_OVERLAP = 80

TOP_K = 5
# Documentacion tecnica: mas peso al lexico, que es el que acierta con nombres propios,
# identificadores y nombres de funcion.
PESOS_ENSEMBLE = [0.4, 0.6]  # [vectorial, BM25]


def get_embeddings() -> OpenAIEmbeddings:
    """Fuente unica del modelo de embeddings (ingesta y consulta)."""
    return OpenAIEmbeddings(model=EMBEDDING_MODEL)


def requerir(nombre: str) -> str:
    valor = os.getenv(nombre)
    if not valor:
        raise RuntimeError(f"Falta la variable de entorno {nombre}. Revisa tu archivo .env")
    return valor
