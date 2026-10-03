"""Trazas OTLP hacia Arize Phoenix para API, worker, grafo, herramientas y modelo.

Los spans siguen las convenciones de OpenInference (``openinference.span.kind``,
``llm.*``, ``tool.*``, ``retrieval.documents.*``, ``input.value``/``output.value``) para que
Phoenix los muestre como cadena, LLM, herramienta o recuperador, y calcule tokens y costo.
Nunca se registran credenciales. El contenido (prompts, fragmentos, respuestas) se incluye
truncado mientras ``PANEL_TRACE_CONTENT=true``; con ``false`` se reemplaza por un marcador.
"""

from __future__ import annotations

import logging
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from opentelemetry import trace
from opentelemetry.trace import Status, StatusCode

_initialized = False
_trace_content = True
logger = logging.getLogger("panellab.observability")

CONTENT_LIMIT = 8000


def setup_observability(settings: Any, service_name: str) -> None:
    global _initialized, _trace_content
    if _initialized:
        return
    _trace_content = bool(getattr(settings, "trace_content", True))
    from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor

    endpoint = str(getattr(settings, "phoenix_endpoint", "")).rstrip("/")
    if not endpoint:
        return
    try:
        provider = TracerProvider(
            resource=Resource.create(
                {
                    "service.name": service_name,
                    "openinference.project.name": getattr(settings, "phoenix_project", "panellab"),
                }
            )
        )
        traces_endpoint = endpoint if endpoint.endswith("/v1/traces") else f"{endpoint}/v1/traces"
        provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(endpoint=traces_endpoint)))
        trace.set_tracer_provider(provider)
        _initialized = True
    except Exception as exc:
        logger.warning("Tracing unavailable: %s", type(exc).__name__)


def content_attr(value: str, limit: int = CONTENT_LIMIT) -> str:
    """Texto apto para un atributo de span: truncado, u omitido si así se configuró."""
    if not _trace_content:
        return "[contenido omitido: PANEL_TRACE_CONTENT=false]"
    return value if len(value) <= limit else f"{value[:limit]}… [{len(value) - limit} caracteres más]"


@contextmanager
def span(name: str, **attributes: str | int | float | bool) -> Iterator[Any]:
    """Span con atributos; termina en OK si no hubo excepción (con excepción, OTel marca ERROR)."""
    with trace.get_tracer("panellab").start_as_current_span(name) as current:
        for key, value in attributes.items():
            current.set_attribute(key, value)
        yield current
        current.set_status(Status(StatusCode.OK))


def flush_observability() -> None:
    provider = trace.get_tracer_provider()
    if hasattr(provider, "force_flush"):
        provider.force_flush(timeout_millis=5000)
