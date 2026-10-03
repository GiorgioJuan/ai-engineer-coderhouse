from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.contracts import Citation
from app.engine import AnswerAssessment, ReviewerQuestion, SupervisorDecision, calibrate_assessment, canonical_citations
from app.llm import BudgetExceeded, BudgetLedger, ModelClient, _strict_schema, _token_upper
from app.rag import InvalidCitation, RedisRAG, chunks, demo_embedding


class HashRedis:
    def __init__(self, values):
        self.values = values

    async def hgetall(self, key):
        return self.values.get(key, {})

    async def sismember(self, key, member):
        return member == "d1:v1:0" and key == "panellab:rag:docchunks:p1:d1:1"


@pytest.mark.asyncio
async def test_citation_rejects_invented_excerpt_and_wrong_snapshot():
    key = "panellab:chunk:p1:d1:v1:0"
    redis = HashRedis(
        {key: {b"project_id": b"p1", b"document_id": b"d1", b"version": b"1", b"text": "Se entrevistó a 5 personas."}}
    )
    rag = RedisRAG(redis, lambda _: None)
    good = Citation(document_id="d1", version=1, chunk_id="d1:v1:0", section="Pruebas", excerpt="a 5 personas")
    await rag.validate(good, "p1", [{"document_id": "d1", "version": 1}])
    bad = good.model_copy(update={"excerpt": "a 50 personas"})
    with pytest.raises(InvalidCitation):
        await rag.validate(bad, "p1", [{"document_id": "d1", "version": 1}])
    with pytest.raises(InvalidCitation):
        await rag.validate(good, "p1", [{"document_id": "d1", "version": 2}])
    with pytest.raises(InvalidCitation):
        await rag.validate(good, "p2", [{"document_id": "d1", "version": 1}])


def test_chunks_preserve_source_words_and_demo_vector_is_stable():
    source = "# Validación\nSe entrevistó a cinco personas.\nLa prueba se registró."
    parts = chunks(source, size=50, overlap=10)
    assert parts and all(text for _, text in parts)
    assert demo_embedding(source, 64) == demo_embedding(source, 64)
    assert demo_embedding("otra consulta", 64) != demo_embedding(source, 64)


def test_chunks_keep_short_pdf_pages_separate_and_label_previous_page_correctly():
    source = "## Página 1\nResultado de la primera página.\n\n## Página 2\nPlan previsto para la segunda página."
    parts = chunks(source, size=900, overlap=120)
    assert [section for section, _ in parts] == ["Página 1", "Página 2"]
    assert "primera página" in parts[0][1] and "segunda página" not in parts[0][1]
    assert "segunda página" in parts[1][1] and "primera página" not in parts[1][1]
    assert all(excerpt in source for _, excerpt in parts)


def test_chunks_long_paragraph_obeys_size_overlap_and_page_boundary():
    page_one = "A" * 1240
    page_two = "B" * 1180
    source = f"## Página 1\n{page_one}\n## Página 2\n{page_two}"
    parts = chunks(source, size=300, overlap=50)
    assert len(parts) > 4
    assert all(len(excerpt) <= 300 and excerpt in source for _, excerpt in parts)
    assert all("B" not in excerpt for section, excerpt in parts if section == "Página 1")
    assert all("A" not in excerpt for section, excerpt in parts if section == "Página 2")
    assert any(first[1][-50:] == second[1][:50] for first, second in zip(parts, parts[1:], strict=False))


def test_future_plan_cannot_be_reported_as_implemented_progress():
    question = {
        "citations": [
            {
                "document_id": "plan",
                "version": 1,
                "chunk_id": "plan:v1:0",
                "section": "Página 1",
                "excerpt": "La prueba se hará el próximo mes.",
            }
        ]
    }
    criterion = {"title": "Validación con usuarios"}
    model_output = AnswerAssessment(
        status="supported",
        observation="La prueba ya se implementó.",
        evidence_stage="future_plan",
        supporting_chunk_ids=["plan:v1:0"],
        next_action="Continuar.",
    )
    result = calibrate_assessment(model_output, question, criterion)
    assert result["status"] == "partial"
    assert "no consta su ejecución" in result["observation"]
    assert result["citations"] == []
    assert "validación con usuarios" in result["next_action"]

    plan_quality = calibrate_assessment(
        model_output.model_copy(update={"criterion_requires_execution": False}),
        question,
        {"title": "Calidad del plan de validación"},
    )
    assert plan_quality["status"] == "supported"
    assert plan_quality["citations"] == question["citations"]
    assert "plan, no a su ejecución" in plan_quality["observation"]


def test_explanation_criterion_can_be_supported_by_a_user_turn_without_claiming_execution():
    output = AnswerAssessment(
        status="supported",
        observation="La elección está justificada.",
        evidence_stage="reasoned_explanation",
        criterion_requires_execution=False,
    )
    explanation = calibrate_assessment(output, {"citations": []}, {"title": "Justificación técnica"})
    assert explanation["status"] == "supported"
    assert explanation["citations"] == []
    assert "no en una ejecución verificada" in explanation["observation"]
    execution = calibrate_assessment(
        output.model_copy(update={"criterion_requires_execution": True}),
        {"citations": []},
        {"title": "Prueba ejecutada"},
    )
    assert execution["status"] == "partial"


def test_documented_result_needs_specific_cited_chunk_and_keeps_contextual_action():
    source = {
        "document_id": "results",
        "version": 2,
        "chunk_id": "results:v2:1",
        "section": "Página 2",
        "excerpt": "Se completaron cinco pruebas y se registraron resultados.",
    }
    question = {"citations": [source]}
    criterion = {"title": "Validación con usuarios"}
    output = AnswerAssessment(
        status="supported",
        observation="Se documentaron cinco pruebas.",
        evidence_stage="documented_result",
        supporting_chunk_ids=[source["chunk_id"]],
        next_action="Comparar los hallazgos de las cinco pruebas con la próxima iteración.",
    )
    result = calibrate_assessment(output, question, criterion)
    assert result["status"] == "supported"
    assert result["citations"] == [source]
    assert "cinco pruebas" in result["next_action"]
    with pytest.raises(InvalidCitation):
        calibrate_assessment(output.model_copy(update={"supporting_chunk_ids": ["inventado"]}), question, criterion)
    unverified = calibrate_assessment(output.model_copy(update={"supporting_chunk_ids": []}), question, criterion)
    assert unverified["status"] == "partial" and unverified["citations"] == []


def test_demo_supervisor_selects_a_criterion_in_reviewer_focus():
    result = ModelClient._demo(
        "",
        {
            "profiles": [{"profile_id": "tecnico", "focus": ["evidencia"]}],
            "criteria": [{"id": "problema"}, {"id": "evidencia"}],
            "question_count": 0,
        },
        SupervisorDecision,
    )
    assert result.profile_id == "tecnico"
    assert result.criterion_id == "evidencia"


def test_model_chunk_selection_materializes_only_canonical_citations():
    retrieved = [
        {
            "document_id": "brief",
            "version": 2,
            "chunk_id": "brief:v2:0",
            "section": "Validación",
            "excerpt": "Se entrevistó a cinco personas.",
        }
    ]
    selected = canonical_citations(["brief:v2:0"], retrieved)
    assert selected[0].excerpt == "Se entrevistó a cinco personas."
    with pytest.raises(InvalidCitation):
        canonical_citations(["inventado"], retrieved)
    with pytest.raises(InvalidCitation):
        canonical_citations(["brief:v2:0", "brief:v2:0"], retrieved)


def test_strict_schema_marks_optional_pydantic_fields_required_for_openai():
    schema = _strict_schema(
        {
            "type": "object",
            "properties": {
                "value": {"type": "string"},
                "nested": {"type": "object", "properties": {"x": {"type": "integer"}}},
            },
        }
    )
    assert schema["required"] == ["value", "nested"]
    assert schema["additionalProperties"] is False
    assert schema["properties"]["nested"]["required"] == ["x"]


class BudgetRedis:
    def __init__(self):
        self.prior = None
        self.spent = 0.0
        self.reserved = 0.0
        self.reservations = {}

    async def eval(self, script, numkeys, ledger, reservation, *args):
        if "HSETNX" in script:
            prior, cap, amount = map(float, args)
            self.prior = self.prior if self.prior is not None else prior
            if self.prior + self.spent + self.reserved + amount > cap:
                return 0
            self.reservations[reservation] = amount
            self.reserved += amount
            return 1
        actual = float(args[0])
        amount = self.reservations.pop(reservation)
        self.reserved -= amount
        self.spent += actual
        return 1

    async def get(self, key):
        value = self.reservations.get(key)
        return str(value).encode() if value is not None else None

    async def hgetall(self, key):
        return {
            b"prior": str(self.prior).encode(),
            b"spent": str(self.spent).encode(),
            b"reserved": str(self.reserved).encode(),
        }


@pytest.mark.asyncio
async def test_budget_reservation_keeps_unknown_cost_and_counts_prior_spend():
    redis = BudgetRedis()
    budget = BudgetLedger(redis, cap=0.95)
    first = await budget.reserve(0.60)
    with pytest.raises(BudgetExceeded):
        await budget.reserve(0.40)
    assert (await budget.summary())["reserved_usd"] == pytest.approx(0.60)
    await budget.settle(first, 0.10)
    assert (await budget.summary())["spent_usd"] == pytest.approx(0.10)
    assert (await budget.summary())["reserved_usd"] == pytest.approx(0)
    with pytest.raises(ValueError):
        BudgetLedger(redis, cap=0)


def test_token_bound_covers_utf8_payload():
    assert _token_upper("ñ" * 100) >= 200


@pytest.mark.asyncio
async def test_rag_rejects_existing_index_from_another_embedding_model():
    class SignatureRedis:
        async def set(self, key, value, nx=False):
            return False

        async def get(self, key):
            return b"live:text-embedding-3-small:1536"

    rag = RedisRAG(SignatureRedis(), lambda _: None, dimensions=1536, signature="demo:hash-v1")
    with pytest.raises(ValueError, match="signature"):
        await rag.ensure_index()


@pytest.mark.asyncio
@pytest.mark.parametrize("chat_model,input_rate,output_rate", [("gpt-4o-mini", 0.15, 0.60), ("gpt-6-luna", 0.10, 0.50)])
async def test_live_adapter_uses_strict_schema_and_shared_ledger_without_network(
    monkeypatch, chat_model, input_rate, output_rate
):
    calls = []

    class Response:
        def __init__(self, value):
            self.value = value

        def raise_for_status(self):
            return None

        def json(self):
            return self.value

    class Client:
        def __init__(self, timeout):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def post(self, url, *, headers, json):
            calls.append((url, json))
            assert headers["Authorization"] == "Bearer fixture-key"
            if url.endswith("/embeddings"):
                return Response({"usage": {"total_tokens": 4}, "data": [{"embedding": [0.0] * 64}]})
            schema = json["response_format"]["json_schema"]["schema"]
            assert json["model"] == chat_model
            assert json.get("reasoning_effort") == ("low" if chat_model == "gpt-6-luna" else None)
            assert json["max_completion_tokens"] == 100
            assert schema["additionalProperties"] is False
            assert set(schema["required"]) == {"text", "basis", "citation_chunk_ids"}
            return Response(
                {
                    "usage": {"prompt_tokens": 100, "completion_tokens": 20, "total_tokens": 120},
                    "choices": [
                        {
                            "message": {
                                "content": __import__("json").dumps(
                                    {
                                        "text": "¿Qué evidencia falta?",
                                        "basis": "clarification",
                                        "citation_chunk_ids": [],
                                    }
                                )
                            }
                        }
                    ],
                }
            )

    monkeypatch.setattr("app.llm.httpx.AsyncClient", Client)
    redis = BudgetRedis()
    settings = SimpleNamespace(
        llm_mode="live",
        chat_model=chat_model,
        embedding_model="text-embedding-3-small",
        embedding_dimensions=64,
        max_output_tokens=100,
        budget_cap_usd=0.95,
        budget_prior_usd=0.01526940,
        openai_api_key="fixture-key",
    )
    model = ModelClient(settings, redis)
    assert len(await model.embed("Documento de prueba")) == 64
    result = await model.structured("Pregunta en español", {"criterion": "evidencia"}, ReviewerQuestion)
    assert result.basis == "clarification"
    assert len(calls) == 2
    assert (await model.ledger.summary())["spent_usd"] == pytest.approx(
        (4 * 0.02 + 100 * input_rate + 20 * output_rate) / 1_000_000
    )


@pytest.mark.asyncio
async def test_luna_rejects_unpriced_long_context_before_reserving():
    redis = BudgetRedis()
    model = ModelClient(SimpleNamespace(llm_mode="live", chat_model="gpt-6-luna", openai_api_key="fixture-key"), redis)
    with pytest.raises(BudgetExceeded, match="standard-price"):
        await model.structured("Review", {"text": "x" * 272_000}, ReviewerQuestion)
    assert not redis.reservations
