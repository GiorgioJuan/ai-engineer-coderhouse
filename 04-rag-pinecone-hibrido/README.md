# 04 — RAG escalable en la nube con Pinecone y recuperación híbrida

Pre-entrega 4. Módulo de recuperación sobre Pinecone Serverless: ingesta con metadatos
enriquecidos, recuperador híbrido (vectorial + BM25) y evaluación con Precision@5 y Recall@5
sobre un golden set.

Este módulo termina en la recuperación: no genera respuestas. La generación *grounded* está en
el [módulo 3](../03-rag-local/).

## Archivos

| Archivo | Contenido |
|---|---|
| `data/` | 5 documentos `.md` con frontmatter de categoría. |
| `config.py` | Índice, namespace, dimensión, modelo de embeddings y parámetros de chunking. Todo lo que debe coincidir entre ingesta y consulta. |
| `setup_index.py` | Crea el índice serverless si no existe y valida que la dimensión coincida. |
| `ingest.py` | Carga, chunking y subida a Pinecone con metadatos (`fuente`, `categoria`, `seccion`, `chunk_index`, `id`) más el texto original. |
| `retriever.py` | Clase `RAGSystem`: `EnsembleRetriever` con Pinecone + BM25, top-5. |
| `evaluate.py` | Recall@5 y Precision@5 sobre el golden set, comparando los tres recuperadores. |
| `golden_set.json` | 5 preguntas con su documento fuente conocido. |

## Replicar el índice desde cero

Requiere **Python 3.12** y una cuenta de Pinecone (el tier gratuito alcanza).

```bash
python -m venv .venv
.venv\Scripts\activate          # Windows  (Linux/macOS: source .venv/bin/activate)
pip install -r requirements.txt
copy .env.example .env          # Linux/macOS: cp .env.example .env
```

Poné tu `PINECONE_API_KEY` y tu `OPENAI_API_KEY` en el `.env`. Después:

```bash
python setup_index.py                     # crea el índice serverless (dim 1536, cosine, aws/us-east-1)
python ingest.py                          # chunkea data/ y sube al namespace docs-v1
python retriever.py "que es un namespace" # consulta suelta contra el híbrido
python evaluate.py                        # reporte de métricas
```

`ingest.py` llama a `setup_index()` por su cuenta, así que se puede ir directo a `python
ingest.py`. Con `--force` borra el namespace y reindexa.

## Variables de entorno

| Variable | Obligatoria | Descripción |
|---|---|---|
| `PINECONE_API_KEY` | sí | Clave de Pinecone. |
| `OPENAI_API_KEY` | sí | Se usa solo para los embeddings. |
| `INDEX_NAME` | no | Default `manual-ingenieria-ia`. |
| `PINECONE_NAMESPACE` | no | Default `docs-v1`. |
| `PINECONE_CLOUD` / `PINECONE_REGION` | no | Default `aws` / `us-east-1`. |
| `EMBEDDING_MODEL` | no | Default `text-embedding-3-small` (1536 dimensiones). |

## Reporte de evaluación

`evaluate.py` imprime algo así:

```
==============================================================================
REPORTE DE EVALUACION  (k=5, 5 preguntas)
==============================================================================

Recuperador      Recall@5    Precision@5
----------------------------------------
vectorial            1.00           0.44
bm25                 1.00           0.44
hibrido              1.00           0.44

Detalle por pregunta (recuperador hibrido):
------------------------------------------------------------------------------
  [OK  ] P@5=0.40  ¿Que valor de top_k conviene usar al recuperar fragmentos?
  [OK  ] P@5=0.60  ¿Que hace asyncio.Semaphore y para que sirve?
  ...
```

**Cómo se calculan.** *Recall@5* es binario por pregunta: 1 si el `documento_esperado` aparece
entre los 5 recuperados, 0 si no; el reporte muestra el promedio. *Precision@5* es la
proporción de los 5 resultados que vienen de una fuente marcada como relevante en
`fuentes_relevantes`. Por eso el golden set lleva dos campos: sin la lista de relevantes, la
precisión estaría acotada a 0.20 y no diría nada útil.

**Sobre estos números.** Con 13 fragmentos y 5 preguntas el recall satura en 1.00 para los tres
recuperadores: el corpus es demasiado chico para que la fusión luzca. La comparación de tres
columnas está para que, al crecer el corpus, se vea dónde cada recuperador se rompe — que es
cuando la métrica empieza a servir para decidir.

## Decisiones de diseño

**Contra el mismatch de dimensiones.** `config.py` deriva la dimensión del modelo de embeddings
en vez de hardcodearla, y `setup_index.py` compara la dimensión del índice existente con la
esperada **antes** de escribir. Si no coinciden, corta con un mensaje que dice exactamente qué
pasó, en lugar de dejar que falle el upsert con un error críptico.

**Namespace siempre.** Todo va a `docs-v1`. Separa versiones del corpus y entornos dentro del
mismo índice, y evita que una consulta recorra vectores que no le corresponden. Cambiar
`PINECONE_NAMESPACE` permite indexar una versión nueva sin pisar la anterior.

**El texto viaja en los metadatos.** Cada vector lleva su propio `page_content` más `fuente`,
`categoria`, `seccion` y `chunk_index`. Una sola llamada a Pinecone devuelve todo lo necesario
para armar el contexto: no hace falta una segunda consulta a otra base para recuperar el texto.
En markdown, `seccion` (el encabezado más cercano) cumple el rol que tendría el número de
página en un corpus de PDFs.

**Chunking de 600 tokens con 80 de overlap.** Dentro del rango recomendado de 500–800. Sobre
`data/` produce 13 fragmentos de entre 81 y 448 tokens: 600 es el techo, no el piso, porque el
splitter respeta los límites de párrafo.

**Pesos 0.4 vectorial / 0.6 BM25.** Es documentación técnica, con nombres de función y de
librería que la búsqueda semántica tiende a diluir y la léxica acierta. En un corpus de prosa
general convendría lo contrario. `EnsembleRetriever` fusiona con Reciprocal Rank Fusion, que
usa las posiciones y no los puntajes, así no hay que normalizar escalas distintas.

**BM25 corre en proceso.** No es un servicio remoto: necesita los fragmentos en memoria, y
`RAGSystem` los reconstruye desde `data/` con el mismo splitter que usó la ingesta, para que el
corpus léxico y el vectorial sean idénticos. Es una limitación real: en producción se
persistiría el índice BM25 o se usarían los vectores sparse de Pinecone, que resuelven lo mismo
del lado del servicio.

**El ensemble devuelve más de k.** Fusiona dos listas de 5, así que puede devolver hasta 10
documentos. `retrieve()` recorta a `top_k` explícitamente.

## Nota sobre las versiones de LangChain

En LangChain 1.x los dos recuperadores viven fuera del paquete principal, y no en las rutas que
suele mostrar la documentación vieja:

- `EnsembleRetriever` → `langchain_classic.retrievers` (el módulo `langchain.retrievers` ya no
  existe).
- `BM25Retriever` → `langchain_community.retrievers`, que está marcado como *sunset*. Funciona,
  pero conviene tenerlo presente: si desaparece, el reemplazo natural son los vectores sparse
  de Pinecone.

Ambos paquetes están pineados en `requirements.txt`.
