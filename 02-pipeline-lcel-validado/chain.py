"""Cadena LCEL de extraccion de entidades tecnicas, con validacion y reintentos.

Forma de la cadena:

    prompt | model.with_structured_output(ExtraccionTecnica, include_raw=True) | validar

y todo eso envuelto en `.with_retry()`.

Se usa `include_raw=True` a proposito: sin eso, LangChain se traga los errores de
parseo o devuelve `None` en silencio. Con el crudo a mano podemos revisar el
`finish_reason` (respuesta cortada por falta de tokens) y decidir nosotros cuando
vale la pena reintentar.
"""

import logging
import os

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import Runnable, RunnableLambda

from schemas import ExtraccionTecnica

logger = logging.getLogger("pipeline")

MAX_INTENTOS = 3
# Razones de corte que significan "el modelo se quedo sin tokens": la respuesta
# esta incompleta aunque parezca valida.
CORTE_POR_LONGITUD = {"length", "max_tokens"}


class SalidaInvalida(Exception):
    """El modelo respondio algo que no encaja en el esquema. Vale reintentar."""


class RespuestaIncompleta(Exception):
    """El modelo corto la respuesta por limite de tokens. Vale reintentar."""


# --- 1. Modelo -------------------------------------------------------------

def build_model() -> BaseChatModel:
    """Elige el proveedor segun la variable de entorno LLM_PROVIDER."""
    provider = os.getenv("LLM_PROVIDER", "openai").lower()
    max_tokens = int(os.getenv("MAX_TOKENS", "512"))

    if provider == "openai":
        from langchain_openai import ChatOpenAI

        return ChatOpenAI(
            model=os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
            temperature=0,  # extraccion: queremos determinismo, no creatividad
            max_tokens=max_tokens,
            max_retries=0,  # los reintentos los maneja .with_retry(), no el SDK
        )
    if provider == "anthropic":
        from langchain_anthropic import ChatAnthropic

        # Sin `temperature`: la Messages API actual no la acepta para estos modelos.
        return ChatAnthropic(
            model=os.getenv("ANTHROPIC_MODEL", "claude-sonnet-5"),
            max_tokens=max_tokens,
            max_retries=0,
        )
    raise ValueError(f"LLM_PROVIDER invalido: '{provider}'. Usa 'openai' o 'anthropic'.")


# --- 2. Prompt (modular, sin f-strings) ------------------------------------

PROMPT = ChatPromptTemplate.from_messages(
    [
        (
            "system",
            "Sos un analista tecnico. Extraes entidades tecnicas de textos crudos "
            "(logs de error, descripciones de arquitectura, tickets) y las devolves "
            "en el esquema pedido.\n"
            "Reglas:\n"
            "- Solo tecnologias que aparezcan explicitamente en el texto. No inventes.\n"
            "- Si el texto es ambiguo, elegi el nivel de criticidad mas conservador.\n"
            "- El resumen va en espanol, en una o dos oraciones.",
        ),
        ("human", "Analiza el siguiente texto:\n\n<texto>\n{texto}\n</texto>"),
    ]
)


# --- 3. Validacion del crudo -----------------------------------------------

def _validar(salida: dict) -> ExtraccionTecnica:
    """Convierte la salida cruda en un objeto validado o lanza para forzar reintento."""
    raw: AIMessage = salida["raw"]
    parsed = salida["parsed"]
    error = salida["parsing_error"]

    meta = raw.response_metadata or {}
    finish = meta.get("finish_reason") or meta.get("stop_reason")
    if finish in CORTE_POR_LONGITUD:
        logger.warning("Respuesta cortada por limite de tokens (finish_reason=%s)", finish)
        raise RespuestaIncompleta(f"finish_reason={finish}")

    if error is not None:
        logger.warning("JSON invalido o incompleto: %s", error)
        raise SalidaInvalida(str(error))

    if parsed is None:
        logger.warning("El modelo no devolvio ningun objeto estructurado")
        raise SalidaInvalida("respuesta vacia")

    logger.info(
        "Validacion OK: %d tecnologias, criticidad=%s",
        len(parsed.tecnologias),
        parsed.nivel_de_criticidad.value,
    )
    return parsed


# --- 4. Ensamblado LCEL ----------------------------------------------------

def build_chain() -> Runnable:
    model = build_model()
    cadena = PROMPT | model.with_structured_output(
        ExtraccionTecnica, include_raw=True
    ) | RunnableLambda(_validar)

    # Solo reintentamos errores recuperables. Los ValidationError de Pydantic no
    # aparecen aca: LangChain los captura en `parsing_error` y `_validar` los
    # reemite como SalidaInvalida. Un 401 o un error de cuota es permanente:
    # reintentarlo solo suma latencia y gasto.
    return cadena.with_retry(
        retry_if_exception_type=(SalidaInvalida, RespuestaIncompleta),
        wait_exponential_jitter=True,  # backoff exponencial con jitter
        stop_after_attempt=MAX_INTENTOS,
    )


# --- 5. Punto de entrada asincrono -----------------------------------------

async def process_text(text: str, chain: Runnable | None = None) -> ExtraccionTecnica | None:
    """Ejecuta el pipeline sobre un texto. Devuelve None si agoto los reintentos."""
    chain = chain or build_chain()
    logger.info("Procesando texto (%d caracteres)", len(text))
    try:
        resultado = await chain.ainvoke({"texto": text})
    except (SalidaInvalida, RespuestaIncompleta) as exc:
        logger.error("Fallo tras %d intentos: %s", MAX_INTENTOS, exc)
        return None
    except Exception as exc:  # errores permanentes: auth, cuota, red
        logger.error("Error no recuperable (%s): %s", type(exc).__name__, exc)
        return None
    logger.info("Listo: %s", resultado.resumen_tecnico[:60])
    return resultado
