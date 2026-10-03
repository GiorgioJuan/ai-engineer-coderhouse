"""Herramientas de los agentes, spans de Phoenix y resiliencia del adaptador y del worker."""

from __future__ import annotations

from types import SimpleNamespace

import httpx
import pytest
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from pydantic import ValidationError

from app.contracts import Citation
from app.engine import ReviewerQuestion, SupervisorDecision
from app.llm import BudgetExceeded, BudgetLedger, ModelClient, ProviderQuotaExceeded
from app.rag import InvalidCitation, SearchSourcesOutput
from app.tools import (
    COVERAGE_TOOL,
    CoverageInput,
    CoverageOutput,
    VerifyCitationOutput,
    build_evidence_tools,
    evaluate_coverage,
    invoke_tool,
)
from app.worker import job_error

EXPORTER = InMemorySpanExporter()


@pytest.fixture(scope="module", autouse=True)
def tracer_provider():
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(EXPORTER))
    trace.set_tracer_provider(provider)
    yield


@pytest.fixture(autouse=True)
def clear_spans():
    EXPORTER.clear()
    yield


def spans_named(prefix: str):
    return [item for item in EXPORTER.get_finished_spans() if item.name.startswith(prefix)]


CITATION = Citation(
    document_id="brief",
    version=1,
    chunk_id="brief:v1:0",
    section="Objetivo",
    excerpt="El prototipo se probó con cinco usuarios.",
)


def profiles(*focus_lists):
    return [{"profile_id": f"p{i}", "focus": focus} for i, focus in enumerate(focus_lists)]


CRITERIA = [{"id": "alcance", "title": "Alcance"}, {"id": "evidencia", "title": "Evidencia"}]


def test_coverage_gives_unheard_reviewers_priority_and_finishes_when_exhausted():
    first = evaluate_coverage(
        CoverageInput(
            profiles=profiles(["alcance"], ["evidencia"]),
            criteria=CRITERIA,
            heard_profile_ids=["p0"],
            topic_counts={"alcance": 1},
        )
    )
    assert first.unheard_profile_ids == ["p1"]
    assert [pair.model_dump() for pair in first.allowed_pairs] == [{"profile_id": "p1", "criterion_id": "evidencia"}]
    done = evaluate_coverage(
        CoverageInput(
            profiles=profiles(["alcance"]),
            criteria=CRITERIA,
            heard_profile_ids=["p0"],
            topic_counts={"alcance": 2, "evidencia": 2},
        )
    )
    assert done.should_finish and not done.allowed_pairs


@pytest.mark.asyncio
async def test_coverage_tool_validates_arguments_and_output_with_pydantic():
    result = await invoke_tool(COVERAGE_TOOL, {"profiles": profiles(["alcance"]), "criteria": CRITERIA}, CoverageOutput)
    assert result.allowed_pairs[0].criterion_id == "alcance"
    with pytest.raises(ValidationError):
        await invoke_tool(COVERAGE_TOOL, {"profiles": [], "criteria": CRITERIA}, CoverageOutput)
    span = spans_named("tool.evaluar_cobertura")[0]
    assert span.attributes["openinference.span.kind"] == "TOOL"
    assert span.attributes["tool.name"] == "evaluar_cobertura"
    assert "allowed_pairs" in span.attributes["output.value"]


@pytest.mark.asyncio
async def test_evidence_tools_are_scoped_and_traced_as_retriever():
    calls = []

    class FakeRAG:
        async def search_tool(self, request, *, project_id, allowed):
            calls.append((request.query, request.top_k, project_id, allowed))
            return SearchSourcesOutput(evidence_status="found", citations=[CITATION])

        async def validate(self, citation, project_id, allowed):
            if citation.chunk_id != CITATION.chunk_id:
                raise InvalidCitation("Unknown citation source")

    allowed = [{"document_id": "brief", "version": 1}]
    search, verify = build_evidence_tools(FakeRAG(), "proyecto-1", allowed)
    found = await invoke_tool(search, {"query": "pruebas con usuarios", "top_k": 3}, SearchSourcesOutput)
    assert found.citations == [CITATION]
    # El modelo controla la consulta; el alcance lo fija el servidor.
    assert calls == [("pruebas con usuarios", 3, "proyecto-1", allowed)]
    with pytest.raises(ValidationError):
        await invoke_tool(search, {"query": "ab"}, SearchSourcesOutput)

    ok = await invoke_tool(verify, {"citation": CITATION.model_dump()}, VerifyCitationOutput)
    bad = await invoke_tool(verify, {"citation": {**CITATION.model_dump(), "chunk_id": "otro"}}, VerifyCitationOutput)
    assert ok.valid and not bad.valid

    retriever = spans_named("panellab.rag.search")[0]
    assert retriever.attributes["openinference.span.kind"] == "RETRIEVER"
    assert retriever.attributes["input.value"] == "pruebas con usuarios"
    assert retriever.attributes["retrieval.documents.0.document.id"] == CITATION.chunk_id


@pytest.mark.asyncio
async def test_demo_mode_still_emits_llm_spans_with_input_and_output():
    model = ModelClient(SimpleNamespace(llm_mode="demo"), None)
    context = {
        "profiles": [{"profile_id": "p0", "focus": ["alcance"]}],
        "criteria": [{"id": "alcance", "title": "Alcance", "description": "Qué se entrega"}],
        "question_count": 0,
    }
    decision = await model.structured("Supervisor", context, SupervisorDecision)
    assert decision.search_query == "Alcance Qué se entrega"
    span = spans_named("llm.SupervisorDecision")[0]
    assert span.attributes["openinference.span.kind"] == "LLM"
    assert span.attributes["llm.model_name"] == "demo-determinista"
    assert span.attributes["llm.cost.total"] == 0.0
    assert '"profile_id":"p0"' in span.attributes["output.value"]


class LedgerRedis:
    def __init__(self):
        self.values, self.hash = {}, {}

    async def eval(self, script, numkeys, ledger, reservation, *args):
        if "HSETNX" in script:
            prior, ceiling, amount = map(float, args)
            used = prior + self.hash.get("spent", 0) + self.hash.get("reserved", 0)
            if used + amount > ceiling:
                return 0
            self.hash["reserved"] = self.hash.get("reserved", 0) + amount
            self.values[reservation] = str(amount)
            return 1
        amount = float(self.values.pop(reservation))
        self.hash["reserved"] -= amount
        self.hash["spent"] = self.hash.get("spent", 0) + float(args[0])
        return 1

    async def get(self, key):
        return self.values.get(key)

    async def hgetall(self, key):
        return {k: str(v) for k, v in self.hash.items()}


@pytest.mark.asyncio
async def test_rejected_provider_call_releases_its_budget_reservation(monkeypatch):
    attempts = []

    class Client:
        def __init__(self, timeout):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def post(self, url, *, headers, json):
            attempts.append(url)
            request = httpx.Request("POST", url)
            return httpx.Response(401, request=request, json={"error": "invalid key"})

    monkeypatch.setattr("app.llm.httpx.AsyncClient", Client)
    redis = LedgerRedis()
    model = ModelClient(
        SimpleNamespace(
            llm_mode="live",
            chat_model="gpt-4o-mini",
            openai_api_key="k",
            embedding_dimensions=64,
            max_output_tokens=100,
        ),
        redis,
    )
    with pytest.raises(httpx.HTTPStatusError):
        await model.structured("Pregunta", {"criterion": "alcance"}, ReviewerQuestion)
    assert len(attempts) == 1  # 401 no se reintenta
    summary = await model.ledger.summary()
    assert summary["reserved_usd"] == pytest.approx(0) and summary["spent_usd"] == pytest.approx(0)


@pytest.mark.asyncio
async def test_rate_limited_call_is_retried_once_with_the_same_reservation(monkeypatch):
    statuses = iter([429, 200])

    class Client:
        def __init__(self, timeout):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def post(self, url, *, headers, json):
            status = next(statuses)
            body = (
                {
                    "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
                    "choices": [
                        {
                            "message": {
                                "content": '{"text":"¿Qué falta?","basis":"clarification","citation_chunk_ids":[]}'
                            }
                        }
                    ],
                }
                if status == 200
                else {"error": "rate limited"}
            )
            return httpx.Response(status, request=httpx.Request("POST", url), json=body)

    async def no_sleep(_):
        return None

    monkeypatch.setattr("app.llm.httpx.AsyncClient", Client)
    monkeypatch.setattr("app.llm.asyncio.sleep", no_sleep)
    model = ModelClient(
        SimpleNamespace(
            llm_mode="live",
            chat_model="gpt-4o-mini",
            openai_api_key="k",
            embedding_dimensions=64,
            max_output_tokens=100,
        ),
        LedgerRedis(),
    )
    result = await model.structured("Pregunta", {"criterion": "alcance"}, ReviewerQuestion)
    assert result.basis == "clarification"
    summary = await model.ledger.summary()
    assert summary["reserved_usd"] == pytest.approx(0)
    assert summary["spent_usd"] == pytest.approx((10 * 0.15 + 5 * 0.60) / 1_000_000)


def test_worker_only_offers_retry_for_transient_failures_and_within_the_attempt_limit():
    assert job_error(httpx.ConnectError("down"), attempt=1)["retryable"] is True
    assert job_error(InvalidCitation("bad chunk"), attempt=1)["retryable"] is True
    assert job_error(BudgetExceeded("exhausted"), attempt=1)["retryable"] is False
    assert job_error(ValueError("Question is no longer pending"), attempt=1)["retryable"] is False
    assert job_error(httpx.ConnectError("down"), attempt=3)["retryable"] is False
    request = httpx.Request("POST", "https://api.example/v1/embeddings")
    unauthorized = httpx.HTTPStatusError("401", request=request, response=httpx.Response(401, request=request))
    throttled = httpx.HTTPStatusError("429", request=request, response=httpx.Response(429, request=request))
    assert job_error(unauthorized, attempt=1) | {"message": ""} == {
        "code": "ProviderHTTP401",
        "message": "",
        "retryable": False,
    }
    assert job_error(throttled, attempt=1)["retryable"] is True


@pytest.mark.asyncio
async def test_budget_ceiling_is_configurable_but_must_be_positive():
    ledger = BudgetLedger(LedgerRedis(), cap=2.0)
    await ledger.reserve(1.5)
    with pytest.raises(BudgetExceeded):
        await ledger.reserve(1.0)
    with pytest.raises(ValueError):
        BudgetLedger(LedgerRedis(), cap=0)


@pytest.mark.asyncio
async def test_exhausted_credit_fails_fast_without_retry_and_releases_reservation(monkeypatch):
    attempts = []

    class Client:
        def __init__(self, timeout):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def post(self, url, *, headers, json):
            attempts.append(url)
            return httpx.Response(
                429,
                request=httpx.Request("POST", url),
                json={"error": {"code": "credit_balance_exhausted", "type": "insufficient_quota"}},
            )

    monkeypatch.setattr("app.llm.httpx.AsyncClient", Client)
    model = ModelClient(
        SimpleNamespace(
            llm_mode="live",
            chat_model="gpt-4o-mini",
            openai_api_key="k",
            embedding_dimensions=64,
            max_output_tokens=100,
        ),
        LedgerRedis(),
    )
    with pytest.raises(ProviderQuotaExceeded):
        await model.embed("hola")
    assert len(attempts) == 1
    assert (await model.ledger.summary())["reserved_usd"] == pytest.approx(0)
    assert job_error(ProviderQuotaExceeded("sin crédito"), attempt=1)["retryable"] is False


def test_reviewer_schema_only_accepts_chunks_retrieved_this_turn():
    from app.engine import with_chunk_choices
    from app.llm import _strict_schema

    schema = with_chunk_choices(ReviewerQuestion, "citation_chunk_ids", ["brief:v1:0", "arq:v1:2"])
    assert schema.__name__ == "ReviewerQuestion"  # el fixture demo y el nombre del json_schema no cambian
    ok = schema(text="¿Qué se probó?", basis="document", citation_chunk_ids=["arq:v1:2"])
    assert ok.citation_chunk_ids == ["arq:v1:2"]
    with pytest.raises(ValidationError):
        schema(text="¿Qué se probó?", basis="document", citation_chunk_ids=["informe-anterior:v1:0"])
    items = _strict_schema(schema.model_json_schema())["properties"]["citation_chunk_ids"]["items"]
    assert items["enum"] == ["brief:v1:0", "arq:v1:2"]


def test_previous_report_reaches_the_reviewer_without_citable_ids():
    from app.engine import previous_summary

    report = {
        "criterion_feedback": [
            {
                "criterion_id": "evidencia",
                "status": "partial",
                "observation": "Falta registro.",
                "next_action": "Registrar.",
                "citations": [CITATION.model_dump()],
            }
        ],
        "next_steps": ["Registrar."],
    }
    summary = previous_summary(report)
    assert "citations" not in summary["criterion_feedback"][0]
    assert summary["criterion_feedback"][0]["status"] == "partial"
    assert previous_summary(None) is None


def test_root_span_summarizes_each_turn_for_phoenix_sessions():
    from app.engine import command_input, command_output

    start = {"kind": "START_SESSION", "payload": {}}
    answer = {"kind": "ANSWER", "payload": {"text": "Probamos cuatro tareas con la coordinadora."}}
    state = {"presentation": "Somos Turno Claro.", "pending_question": {"text": "¿Qué evidencia hay?"}}
    assert command_input(start, state) == "Somos Turno Claro."
    assert command_input(answer, state) == "Probamos cuatro tareas con la coordinadora."
    assert command_output(answer, state) == "¿Qué evidencia hay?"
    finished = {"report": {"criterion_feedback": [{"criterion_id": "evidencia", "status": "partial"}]}}
    assert command_output({"kind": "FINISH"}, finished) == "Informe listo. evidencia: partial"


def test_session_comparison_is_structured_and_readable_without_internal_ids():
    from app.reporting import compare_feedback, comparison_text

    previous = {
        "criterion_feedback": [
            {"criterion_id": "evidencia", "status": "missing", "citations": []},
            {"criterion_id": "alcance", "status": "partial", "citations": [{}, {}]},
        ]
    }
    current = [
        {"criterion_id": "evidencia", "status": "partial", "citations": [{}]},
        {"criterion_id": "problema", "status": "supported", "citations": []},
    ]
    changes = compare_feedback(previous, current, {"evidencia": "Evidencia del avance"})
    assert changes == [
        {
            "criterion_id": "evidencia",
            "title": "Evidencia del avance",
            "previous_status": "missing",
            "current_status": "partial",
            "previous_sources": 0,
            "current_sources": 1,
        }
    ]
    text = comparison_text(changes)
    assert text == "Comparación con la sesión anterior: Evidencia del avance: sin evidencia → parcial."
