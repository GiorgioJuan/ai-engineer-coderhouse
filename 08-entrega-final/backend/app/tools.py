"""Herramientas de los agentes, con entrada y salida validadas por Pydantic.

Cada rol del grafo usa herramientas acotadas a su función, como los especialistas de
la pre-entrega 6:

- Supervisor: ``evaluar_cobertura`` calcula qué evaluadores faltan intervenir y qué pares
  evaluador/criterio son válidos. El modelo elige *dentro* de esa lista.
- Evaluador: ``buscar_evidencia`` (RAG híbrido sobre el snapshot de la sesión) y
  ``verificar_cita`` (comprueba que el fragmento citado exista en la versión indexada).

Son ``StructuredTool`` de LangChain: ``ainvoke`` valida los argumentos contra ``args_schema``
antes de ejecutar, e :func:`invoke_tool` valida la salida contra su modelo. El alcance
(proyecto y versiones congeladas en la sesión) se inyecta del lado del servidor al construir
la herramienta: el modelo sólo controla la consulta, nunca qué documentos puede leer.
"""

from __future__ import annotations

import json
from typing import Any

from langchain_core.tools import StructuredTool
from pydantic import BaseModel, ConfigDict, Field

from app.contracts import Citation
from app.observability import content_attr, span
from app.rag import InvalidCitation, SearchSourcesInput, SearchSourcesOutput


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


# --- evaluar_cobertura (supervisor) -------------------------------------------------


class CoverageProfile(Strict):
    profile_id: str = Field(min_length=1)
    focus: list[str] = Field(min_length=1)


class CoverageCriterion(Strict):
    id: str = Field(min_length=1)
    title: str = Field(min_length=1)


class CoverageInput(Strict):
    profiles: list[CoverageProfile] = Field(min_length=1, max_length=5)
    criteria: list[CoverageCriterion] = Field(min_length=1)
    heard_profile_ids: list[str] = Field(default_factory=list)
    topic_counts: dict[str, int] = Field(default_factory=dict)
    max_questions_per_criterion: int = Field(default=2, ge=1, le=5)


class ReviewerCriterionPair(Strict):
    profile_id: str
    criterion_id: str


class CoverageOutput(Strict):
    unheard_profile_ids: list[str]
    allowed_pairs: list[ReviewerCriterionPair]
    should_finish: bool
    reason: str


async def _evaluar_cobertura(**kwargs: Any) -> CoverageOutput:
    # StructuredTool ya validó los argumentos; llegan como instancias de los modelos anidados.
    return evaluate_coverage(CoverageInput(**kwargs))


def evaluate_coverage(request: CoverageInput) -> CoverageOutput:
    """Reglas de turno: cada evaluador seleccionado habla antes de que alguno repita."""
    counts = request.topic_counts
    heard = set(request.heard_profile_ids)
    unheard = [profile for profile in request.profiles if profile.profile_id not in heard]
    # Mientras falten evaluadores por hablar, el tope por criterio no aplica: un foco
    # compartido no puede agotar el criterio antes de la primera ronda.
    available = [
        criterion
        for criterion in request.criteria
        if unheard or counts.get(criterion.id, 0) < request.max_questions_per_criterion
    ]
    available.sort(key=lambda criterion: counts.get(criterion.id, 0))
    unheard_ids = [profile.profile_id for profile in unheard]
    if not available:
        return CoverageOutput(
            unheard_profile_ids=unheard_ids,
            allowed_pairs=[],
            should_finish=True,
            reason="Todos los criterios alcanzaron el máximo de preguntas.",
        )
    pool = unheard or request.profiles
    pairs = [
        ReviewerCriterionPair(profile_id=profile.profile_id, criterion_id=criterion.id)
        for criterion in available
        for profile in pool
        if criterion.id in profile.focus
    ]
    if not pairs:
        return CoverageOutput(
            unheard_profile_ids=unheard_ids,
            allowed_pairs=[],
            should_finish=True,
            reason="Ningún evaluador seleccionado cubre los criterios pendientes.",
        )
    reason = (
        f"Faltan intervenir {len(unheard)} evaluadores."
        if unheard
        else "Todos intervinieron; se priorizan los criterios menos tratados."
    )
    return CoverageOutput(unheard_profile_ids=unheard_ids, allowed_pairs=pairs, should_finish=False, reason=reason)


COVERAGE_TOOL = StructuredTool.from_function(
    coroutine=_evaluar_cobertura,
    name="evaluar_cobertura",
    description=(
        "Calcula qué evaluadores todavía no intervinieron y qué pares evaluador/criterio "
        "son válidos según el foco de cada evaluador y las preguntas ya hechas por criterio. "
        "Devuelve should_finish=true si no queda ningún par válido."
    ),
    args_schema=CoverageInput,
)


# --- buscar_evidencia y verificar_cita (evaluador) ----------------------------------


class VerifyCitationInput(Strict):
    citation: Citation


class VerifyCitationOutput(Strict):
    valid: bool
    reason: str


def build_evidence_tools(
    rag: Any, project_id: str, allowed: list[dict[str, Any]]
) -> tuple[StructuredTool, StructuredTool]:
    """Herramientas del evaluador, limitadas al proyecto y al snapshot de la sesión."""

    async def buscar_evidencia(query: str, top_k: int = 5) -> SearchSourcesOutput:
        with span(
            "panellab.rag.search",
            **{"openinference.span.kind": "RETRIEVER", "input.value": query, "panellab.project_id": project_id},
        ) as trace_span:
            # Se resuelve en cada llamada (no al construir) para poder sustituirlo en tests.
            result = await rag.search_tool(
                SearchSourcesInput(query=query, top_k=top_k), project_id=project_id, allowed=allowed
            )
            output = SearchSourcesOutput.model_validate(result)
            for number, citation in enumerate(output.citations):
                prefix = f"retrieval.documents.{number}.document"
                trace_span.set_attribute(f"{prefix}.id", citation.chunk_id)
                trace_span.set_attribute(f"{prefix}.content", content_attr(citation.excerpt))
                trace_span.set_attribute(
                    f"{prefix}.metadata",
                    json.dumps(
                        {"document_id": citation.document_id, "version": citation.version, "section": citation.section},
                        ensure_ascii=False,
                    ),
                )
            trace_span.set_attribute("panellab.evidence_status", output.evidence_status)
        return output

    async def verificar_cita(citation: Citation | dict[str, Any]) -> VerifyCitationOutput:
        try:
            await rag.validate(Citation.model_validate(citation), project_id, allowed)
        except InvalidCitation as exc:
            return VerifyCitationOutput(valid=False, reason=str(exc))
        return VerifyCitationOutput(valid=True, reason="El fragmento existe en la versión indexada del documento.")

    search = StructuredTool.from_function(
        coroutine=buscar_evidencia,
        name="buscar_evidencia",
        description=(
            "Busca fragmentos de los documentos del proyecto que respalden o contradigan un "
            "criterio. Combina búsqueda léxica y vectorial (Reciprocal Rank Fusion) y sólo "
            "devuelve versiones incluidas en la sesión. evidence_status='insufficient' "
            "indica que no hay fragmentos relevantes."
        ),
        args_schema=SearchSourcesInput,
    )
    verify = StructuredTool.from_function(
        coroutine=verificar_cita,
        name="verificar_cita",
        description=(
            "Comprueba que una cita exista textualmente en el fragmento almacenado y que "
            "pertenezca a una versión de documento incluida en la sesión."
        ),
        args_schema=VerifyCitationInput,
    )
    return search, verify


async def invoke_tool[Output: BaseModel](
    tool: StructuredTool, args: dict[str, Any], output_model: type[Output]
) -> Output:
    """Ejecuta una herramienta en un span TOOL y valida su salida con Pydantic."""
    with span(
        f"tool.{tool.name}",
        **{
            "openinference.span.kind": "TOOL",
            "tool.name": tool.name,
            "tool.description": tool.description,
            "tool.parameters": json.dumps(tool.args_schema.model_json_schema(), ensure_ascii=False),
            "input.value": content_attr(json.dumps(args, ensure_ascii=False, default=str)),
            "input.mime_type": "application/json",
        },
    ) as trace_span:
        result = output_model.model_validate(await tool.ainvoke(args))
        trace_span.set_attribute("output.value", content_attr(result.model_dump_json()))
        trace_span.set_attribute("output.mime_type", "application/json")
        return result
