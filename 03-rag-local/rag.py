"""Cadena RAG asincrona: recuperar -> fundamentar -> responder validado.

Forma de la cadena (LCEL):

    {"contexto": retriever | formatear, "pregunta": passthrough}
      | PROMPT | model | PydanticOutputParser

El prompt actua como filtro de veracidad: el modelo solo puede usar el contexto, y si
no alcanza tiene que decirlo en vez de completar con lo que sabe de memoria.
"""

import logging
import os

from langchain_core.documents import Document
from langchain_core.exceptions import OutputParserException
from langchain_core.language_models import BaseChatModel
from langchain_core.output_parsers import PydanticOutputParser
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import Runnable, RunnableLambda, RunnablePassthrough

from ingest import get_vectorstore
from schemas import RespuestaRAG

logger = logging.getLogger("rag.chain")

# Entre 3 y 5: mas fragmentos disparan el limite de tokens y el efecto Lost in the Middle.
TOP_K = 4
MAX_INTENTOS = 2


def build_model() -> BaseChatModel:
    """El proveedor del LLM es configurable; el de embeddings no (ver ingest.py)."""
    provider = os.getenv("LLM_PROVIDER", "openai").lower()
    max_tokens = int(os.getenv("MAX_TOKENS", "700"))

    if provider == "openai":
        from langchain_openai import ChatOpenAI

        return ChatOpenAI(
            model=os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
            temperature=0,
            max_tokens=max_tokens,
        )
    if provider == "anthropic":
        from langchain_anthropic import ChatAnthropic

        return ChatAnthropic(
            model=os.getenv("ANTHROPIC_MODEL", "claude-sonnet-5"),
            max_tokens=max_tokens,
        )
    raise ValueError(f"LLM_PROVIDER invalido: '{provider}'. Usa 'openai' o 'anthropic'.")


def formatear_contexto(docs: list[Document]) -> str:
    """Etiqueta cada fragmento con su archivo de origen para que el modelo pueda citarlo."""
    if not docs:
        logger.warning("El retriever no devolvio ningun fragmento")
        return "(sin resultados)"

    fuentes = [d.metadata.get("fuente", "desconocida") for d in docs]
    logger.info("Recuperados %d fragmentos de: %s", len(docs), ", ".join(sorted(set(fuentes))))

    return "\n\n---\n\n".join(
        f"[fuente: {d.metadata.get('fuente', 'desconocida')}]\n{d.page_content}"
        for d in docs
    )


PARSER = PydanticOutputParser(pydantic_object=RespuestaRAG)

PROMPT = ChatPromptTemplate.from_messages(
    [
        (
            "system",
            "Sos un asistente tecnico. Respondes UNICAMENTE con lo que dice el CONTEXTO.\n"
            "Reglas estrictas:\n"
            "- Si la respuesta no esta en el contexto, deci que no tenes acceso a esa "
            "informacion y devolve tiene_respuesta=false. No completes con conocimiento "
            "propio ni especules.\n"
            "- Citá en `referencias` los archivos que efectivamente usaste.\n"
            "- No inventes nombres de archivo.\n\n"
            "{format_instructions}",
        ),
        (
            "human",
            "CONTEXTO:\n{contexto}\n\nPREGUNTA: {pregunta}",
        ),
    ]
).partial(format_instructions=PARSER.get_format_instructions())


def build_chain() -> Runnable:
    retriever = get_vectorstore().as_retriever(search_kwargs={"k": TOP_K})
    cadena = (
        {
            "contexto": retriever | RunnableLambda(formatear_contexto),
            "pregunta": RunnablePassthrough(),
        }
        | PROMPT
        | build_model()
        | PARSER
    )
    # Un JSON mal formado es transitorio: se reintenta. Un 401 no.
    return cadena.with_retry(
        retry_if_exception_type=(OutputParserException,),
        wait_exponential_jitter=True,
        stop_after_attempt=MAX_INTENTOS,
    )


async def get_rag_response(query: str, chain: Runnable | None = None) -> RespuestaRAG:
    """Punto de entrada asincrono. Devuelve siempre un RespuestaRAG valido."""
    chain = chain or build_chain()
    logger.info("Consulta: %s", query)
    try:
        respuesta = await chain.ainvoke(query)
    except OutputParserException as exc:
        logger.error("El modelo no produjo JSON valido tras %d intentos: %s", MAX_INTENTOS, exc)
        return RespuestaRAG(
            respuesta="No se pudo generar una respuesta valida.",
            referencias=[],
            tiene_respuesta=False,
        )
    except Exception as exc:
        logger.error("Error no recuperable (%s): %s", type(exc).__name__, exc)
        return RespuestaRAG(
            respuesta=f"Error al consultar el modelo: {type(exc).__name__}",
            referencias=[],
            tiene_respuesta=False,
        )

    logger.info("tiene_respuesta=%s | referencias=%s", respuesta.tiene_respuesta, respuesta.referencias)
    return respuesta
