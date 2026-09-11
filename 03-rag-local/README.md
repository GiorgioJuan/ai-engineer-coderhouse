# 03 — Sistema de recuperación semántica local (RAG)

Pre-entrega 3. Un pipeline RAG end-to-end sobre ChromaDB local: ingesta con chunking,
recuperación por similitud y generación *grounded* que solo puede responder con lo que está
en los documentos.

## Archivos

| Archivo | Contenido |
|---|---|
| `data/` | Dataset de ejemplo: 4 documentos `.md` sobre ingeniería de sistemas de IA. |
| `ingest.py` | Lee `data/`, fragmenta y persiste en ChromaDB. Define el modelo de embeddings y cómo se abre la colección. |
| `rag.py` | Cadena LCEL asíncrona: retriever → prompt → LLM → `PydanticOutputParser`. Expone `get_rag_response()`. |
| `schemas.py` | `RespuestaRAG`: texto, referencias y `tiene_respuesta`. |
| `main.py` | Las dos pruebas: pregunta respondible y pregunta trampa. |
| `.env.example` | Variables de entorno. |

## Cómo correrlo

Requiere **Python 3.12**.

```bash
python -m venv .venv
.venv\Scripts\activate          # Windows  (Linux/macOS: source .venv/bin/activate)
pip install -r requirements.txt
copy .env.example .env          # Linux/macOS: cp .env.example .env
```

Editá `.env` con tu clave y después:

```bash
python ingest.py        # indexa data/ en ./vectorstore (solo si está vacía)
python ingest.py --force  # vacía la colección y reindexa desde cero
python main.py          # corre las dos pruebas (indexa antes si hace falta)
```

`main.py` llama a `ingest()` por su cuenta, así que podés ir directo a `python main.py`.

## Variables de entorno

| Variable | Obligatoria | Descripción |
|---|---|---|
| `OPENAI_API_KEY` | **sí, siempre** | Los embeddings son de OpenAI aunque el LLM sea Anthropic. |
| `LLM_PROVIDER` | no | `openai` o `anthropic` para el modelo que redacta. Default: `openai`. |
| `ANTHROPIC_API_KEY` | solo si `LLM_PROVIDER=anthropic` | |
| `EMBEDDING_MODEL` | no | Default `text-embedding-3-small`. |
| `OPENAI_MODEL` / `ANTHROPIC_MODEL` | no | Defaults `gpt-4o-mini` / `claude-sonnet-5`. |
| `MAX_TOKENS` | no | Default `700`. |

La carpeta `vectorstore/` está en el `.gitignore`: se regenera con `ingest.py`.

## Salida esperada

Pregunta respondible:

```
tiene_respuesta : True
referencias     : ['03-embeddings-y-vectores.md']
respuesta       : Conviene un top_k de entre 3 y 5 fragmentos. Pasar demasiados arriesga
                  superar el límite de tokens y provoca el efecto Lost in the Middle...
```

Pregunta trampa (el precio de GPT-4o no está en ningún documento):

```
tiene_respuesta : False
referencias     : (ninguna)
respuesta       : No tengo acceso a esa información en el contexto proporcionado.
```

## Decisiones de diseño

**Un solo lugar define los embeddings.** `rag.py` no crea su propio modelo de embeddings:
importa `get_vectorstore()` de `ingest.py`. Indexar con un modelo y consultar con otro es el
error más común de un sistema de recuperación, y el más difícil de detectar, porque no falla:
devuelve fragmentos irrelevantes en silencio. Con una sola función compartida, el error es
estructuralmente imposible.

**Chunking en tokens, no en caracteres.** `RecursiveCharacterTextSplitter.from_tiktoken_encoder`
con `chunk_size=500` y `chunk_overlap=50` cuenta con el mismo tokenizador que usa el modelo. El
splitter respeta los límites de párrafo, así que los fragmentos reales de este dataset salen
entre 100 y 366 tokens: 500 es el techo, no el piso. Sobre `data/` produce 12 fragmentos.

**`top_k=4`.** Dentro del rango recomendado de 3 a 5. Más fragmentos arriesgan el límite de
tokens y el efecto *Lost in the Middle*, donde el modelo presta menos atención a lo que queda
sepultado en el medio del contexto.

**No se reindexa al pepe.** `ingest()` chequea si la colección ya tiene datos antes de
trabajar. Cada fragmento cuesta una llamada al modelo de embeddings; sin esa verificación cada
corrida vuelve a pagar todo. `--force` usa `reset_collection()` de Chroma en vez de borrar la
carpeta a mano, porque en Windows el `rmtree` falla si algún cliente todavía tiene los archivos
abiertos.

**El prompt como filtro de veracidad.** El mensaje de sistema prohíbe usar conocimiento propio
y obliga a devolver `tiene_respuesta=false` cuando el contexto no alcanza. Cada fragmento entra
al contexto etiquetado con `[fuente: archivo.md]`, que es lo que permite al modelo citar en
`referencias` sin inventar nombres de archivo.

**`PydanticOutputParser` en lugar de `with_structured_output`.** Acá se usa el parser clásico,
que inyecta las instrucciones de formato en el prompt vía `.partial()` y valida después. El
módulo 2 usa el otro camino (`with_structured_output`, tool calling), que es más robusto. Se
usan los dos a propósito, para tener ambas técnicas cubiertas. Como el parser es más frágil, la
cadena lleva `.with_retry()` sobre `OutputParserException`, y `get_rag_response()` siempre
devuelve un `RespuestaRAG` válido: si el modelo no produce JSON parseable tras los reintentos,
responde con `tiene_respuesta=False` en vez de romper.
