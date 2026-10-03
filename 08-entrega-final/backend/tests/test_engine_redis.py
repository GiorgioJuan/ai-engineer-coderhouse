"""End-to-end offline graph with a durable Redis checkpoint."""

from __future__ import annotations

import os
import uuid

import pytest
import redis.asyncio as redis

from app.config import Settings
from app.engine import GraphEngine, SupervisorDecision, now
from app.llm import BudgetExceeded, BudgetLedger
from app.storage import Repository


@pytest.mark.asyncio
async def test_session_survives_new_engine_instance():
    url = os.getenv("PANEL_TEST_REDIS_URL")
    if not url:
        pytest.skip("Set PANEL_TEST_REDIS_URL to a Redis Search test instance")
    client = redis.from_url(url, decode_responses=False)
    repo = Repository(client)
    settings = Settings(redis_url=url, llm_mode="demo", embedding_dimensions=1536)
    project_id = uuid.uuid4().hex
    session_id = uuid.uuid4().hex
    doc_id = uuid.uuid4().hex
    profile_id = "tecnico"
    rubric_id = "revision"
    keys = [
        ("document", f"{doc_id}:1"),
        ("profile", f"{project_id}:{profile_id}:1"),
        ("rubric", f"{project_id}:{rubric_id}:1"),
        ("session", session_id),
        ("report", session_id),
    ]
    try:
        await repo.put(
            "document",
            f"{doc_id}:1",
            {
                "document_id": doc_id,
                "project_id": project_id,
                "version": 1,
                "text": "# Evidencia\nSe entrevistó a cinco personas y se documentó el prototipo.",
                "index_status": "QUEUED",
            },
        )
        await repo.put(
            "profile",
            f"{project_id}:{profile_id}:1",
            {
                "profile_id": profile_id,
                "project_id": project_id,
                "version": 1,
                "name": "Técnico",
                "role": "Revisor",
                "focus": ["evidencia"],
                "style": "exigente",
                "markdown": "Pide evidencia precisa.",
            },
        )
        await repo.put(
            "rubric",
            f"{project_id}:{rubric_id}:1",
            {
                "rubric_id": rubric_id,
                "project_id": project_id,
                "version": 1,
                "name": "Revisión del proyecto",
                "criteria": [{"id": "evidencia", "title": "Evidencia", "description": "Pruebas documentadas"}],
                "markdown": "Evaluar evidencia.",
            },
        )
        await repo.put(
            "session",
            session_id,
            {
                "id": session_id,
                "project_id": project_id,
                "objective": "Defender el prototipo",
                "status": "QUEUED",
                "revision": 0,
                "question_count": 0,
                "max_questions": 3,
                "pending_question": None,
                "transcript": [
                    {
                        "id": f"{session_id}:presentation",
                        "kind": "presentation",
                        "author_id": "presenter",
                        "text": "Hicimos un prototipo y lo probamos.",
                        "citations": [],
                        "created_at": now(),
                    }
                ],
                "active_job_id": None,
                "report_id": None,
                "snapshot": {
                    "profile_versions": [{"id": profile_id, "version": 1}],
                    "rubric_version": {"id": rubric_id, "version": 1},
                    "document_versions": [{"document_id": doc_id, "version": 1}],
                    "previous_session_id": None,
                },
                "created_at": now(),
                "updated_at": now(),
            },
        )
        engine = GraphEngine(repo, settings)
        await engine.execute(
            {
                "id": "index",
                "kind": "INDEX_DOCUMENT",
                "project_id": project_id,
                "session_id": None,
                "job_id": "job-index",
                "payload": {"document_id": doc_id, "version": 1},
            }
        )
        original_start_structured = engine.model.structured

        async def early_finish(role, context, schema):
            if schema.__name__ == "SupervisorDecision":
                return SupervisorDecision(
                    action="finish",
                    profile_id="outside",
                    criterion_id="outside",
                    topic_id="outside",
                    reason="premature",
                )
            return await original_start_structured(role, context, schema)

        engine.model.structured = early_finish
        await engine.execute(
            {
                "id": "start",
                "kind": "START_SESSION",
                "project_id": project_id,
                "session_id": session_id,
                "job_id": "job-start",
                "payload": {},
            }
        )
        paused = await repo.get("session", session_id)
        assert paused["status"] == "WAITING_RESPONSE"
        assert paused["pending_question"]["citations"]
        question_id = paused["pending_question"]["id"]
        restarted = GraphEngine(repo, settings)
        answer_command = {
            "id": "answer",
            "kind": "ANSWER",
            "project_id": project_id,
            "session_id": session_id,
            "job_id": "job-answer",
            "payload": {"question_id": question_id, "text": "Probamos el prototipo con cinco personas."},
        }

        async def crash_after_checkpoint(*args):
            raise RuntimeError("simulated projection crash")

        observed_assessments = []
        original_structured = restarted.model.structured

        async def capture_structured(role, context, schema):
            if schema.__name__ == "AnswerAssessment":
                observed_assessments.append(context)
            return await original_structured(role, context, schema)

        restarted.model.structured = capture_structured
        restarted._project = crash_after_checkpoint
        with pytest.raises(RuntimeError, match="projection crash"):
            await restarted.execute(answer_command)
        assert observed_assessments[0]["criterion"]["id"] == "evidencia"
        assert observed_assessments[0]["rubric"]["name"] == "Revisión del proyecto"
        assert observed_assessments[0]["reviewer"]["role"] == "Revisor"
        recovered = GraphEngine(repo, settings)
        await recovered.execute(
            {**answer_command, "id": "answer-retry", "logical_id": "answer", "job_id": "job-answer-retry"}
        )
        next_pause = await repo.get("session", session_id)
        assert next_pause["question_count"] == 2
        assert next_pause["status"] == "WAITING_RESPONSE"
        assert len([turn for turn in next_pause["transcript"] if turn["kind"] == "answer"]) == 1
        await recovered.execute(
            {
                "id": "finish",
                "kind": "FINISH",
                "project_id": project_id,
                "session_id": session_id,
                "job_id": "job-finish",
                "payload": {"question_id": next_pause["pending_question"]["id"]},
            }
        )
        done = await repo.get("session", session_id)
        report = await repo.get("report", session_id)
        assert done["status"] == "COMPLETED"
        assert report["criterion_feedback"][0]["criterion_id"] == "evidencia"
        assert report["criterion_feedback"][0]["citations"]
    finally:
        for kind, key in keys:
            await client.delete(repo.key(kind, key))
            await client.srem(f"panellab:index:{kind}", key)
        marker = f"panellab:rag:docchunks:{project_id}:{doc_id}:1"
        for member in await client.smembers(marker):
            member = member.decode() if isinstance(member, bytes) else member
            await client.delete(f"panellab:chunk:{project_id}:{member}")
        await client.delete(marker)
        await client.aclose()


@pytest.mark.asyncio
async def test_budget_atomic_under_concurrent_reservations():
    url = os.getenv("PANEL_TEST_REDIS_URL")
    if not url:
        pytest.skip("Set PANEL_TEST_REDIS_URL to a Redis test instance")
    client = redis.from_url(url, decode_responses=False)
    budget = BudgetLedger(client, cap=0.95, prior=0.01526940)
    budget.key = f"panellab:test-budget:{uuid.uuid4().hex}"
    try:
        import asyncio

        results = await asyncio.gather(*(budget.reserve(0.5) for _ in range(2)), return_exceptions=True)
        successes = [x for x in results if isinstance(x, str)]
        failures = [x for x in results if isinstance(x, BudgetExceeded)]
        assert len(successes) == 1 and len(failures) == 1
        summary = await budget.summary()
        assert summary["reserved_usd"] == pytest.approx(0.5)
        assert summary["prior_usd"] == pytest.approx(0.01526940)
        await budget.settle(successes[0], 0.001)
        assert (await budget.summary())["spent_usd"] == pytest.approx(0.001)
    finally:
        await client.delete(budget.key)
        await client.aclose()
