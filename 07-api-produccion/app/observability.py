"""Instrumentacion de trazas.

Se instrumenta LangChain/LangGraph con OpenInference, que emite un span por cada nodo
del grafo, cada llamada al modelo y cada herramienta. No hay que decorar nada a mano:
el instrumentador engancha los callbacks de LangChain.

Phoenix calcula el costo por ejecucion a partir de los tokens de entrada y salida que
vienen en esos spans, asi que no hay que reportarlo aparte.

Alternativa: poniendo OBSERVABILIDAD=langsmith solo hacen falta las variables de
entorno de LangSmith; el tracing de LangChain ya viene integrado.
"""

import logging
import os

from app.config import OBSERVABILIDAD, PHOENIX_ENDPOINT, PROJECT_NAME

logger = logging.getLogger("api.observabilidad")

_iniciado = False


def init_observabilidad() -> None:
    """Idempotente: se puede llamar en cada arranque sin duplicar instrumentacion."""
    global _iniciado
    if _iniciado:
        return

    if OBSERVABILIDAD == "phoenix":
        try:
            from openinference.instrumentation.langchain import LangChainInstrumentor
            from openinference.semconv.resource import ResourceAttributes
            from opentelemetry import trace
            from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
            from opentelemetry.sdk.resources import Resource
            from opentelemetry.sdk.trace import TracerProvider
            from opentelemetry.sdk.trace.export import BatchSpanProcessor

            # OTLP estandar evita depender de atributos privados del exporter
            # que phoenix.otel.register inspecciona al imprimir su configuracion.
            tracer_provider = TracerProvider(
                resource=Resource.create({ResourceAttributes.PROJECT_NAME: PROJECT_NAME})
            )
            tracer_provider.add_span_processor(
                BatchSpanProcessor(OTLPSpanExporter(endpoint=PHOENIX_ENDPOINT))
            )
            trace.set_tracer_provider(tracer_provider)
            LangChainInstrumentor().instrument(tracer_provider=tracer_provider)
            logger.info("Phoenix instrumentado -> %s (proyecto '%s')", PHOENIX_ENDPOINT, PROJECT_NAME)
        except Exception as exc:
            # Que no haya colector no puede tumbar la API.
            logger.warning("No se pudo iniciar Phoenix (%s): la API sigue sin trazas", exc)

    elif OBSERVABILIDAD == "langsmith":
        os.environ.setdefault("LANGSMITH_TRACING", "true")
        os.environ.setdefault("LANGSMITH_PROJECT", PROJECT_NAME)
        if not os.getenv("LANGSMITH_API_KEY"):
            logger.warning("OBSERVABILIDAD=langsmith pero falta LANGSMITH_API_KEY")
        else:
            logger.info("LangSmith activo (proyecto '%s')", PROJECT_NAME)

    else:
        logger.info("Observabilidad desactivada (OBSERVABILIDAD=%s)", OBSERVABILIDAD)

    _iniciado = True
