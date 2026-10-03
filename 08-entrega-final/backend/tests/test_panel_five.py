from types import SimpleNamespace

import pytest
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command
from pydantic import ValidationError

from app.config import Settings
from app.contracts import SessionCreate
from app.engine import GraphEngine, SupervisorDecision
from app.rag import SearchSourcesOutput


def test_session_accepts_five_and_rejects_insufficient_turns_or_six():
    payload = dict(
        objective="Review",
        presentation="A prototype",
        profile_versions=[{"id": f"reviewer-{i}", "version": 1} for i in range(5)],
        rubric_version={"id": "rubric", "version": 1},
        document_versions=[{"document_id": "doc", "version": 1}],
        max_questions=5,
    )
    assert len(SessionCreate(**payload).profile_versions) == 5
    with pytest.raises(ValidationError, match="one question per reviewer"):
        SessionCreate(**{**payload, "max_questions": 3})
    with pytest.raises(ValidationError):
        SessionCreate(**{**payload, "profile_versions": payload["profile_versions"] + [{"id": "sixth", "version": 1}]})


@pytest.mark.asyncio
@pytest.mark.parametrize("model_action", ["finish", "question"])
async def test_all_five_speak_despite_premature_finish_repeated_reviewer_and_shared_focus(model_action):
    engine = GraphEngine(SimpleNamespace(redis=None), Settings(llm_mode="demo"))
    original = engine.model.structured

    async def stubborn_model(role, context, schema):
        if schema is SupervisorDecision:
            return SupervisorDecision(
                action=model_action,
                profile_id="reviewer-0",
                criterion_id="evidencia",
                topic_id="evidencia",
                reason="Repeated model choice",
            )
        return await original(role, context, schema)

    async def empty_search(*args, **kwargs):
        return SearchSourcesOutput(evidence_status="insufficient", citations=[])

    engine.model.structured = stubborn_model
    engine.rag.search_tool = empty_search
    graph = engine._build_graph().compile(checkpointer=InMemorySaver())
    config = {"configurable": {"thread_id": "five-reviewers"}}
    state = dict(
        project_id="p",
        session_id="s",
        objective="Review evidence",
        presentation="Prototype",
        profiles=[
            dict(
                profile_id=f"reviewer-{i}",
                name=f"Reviewer {i}",
                role="Review",
                style="direct",
                focus=["evidencia"],
                markdown="Ask about evidence",
            )
            for i in range(5)
        ],
        rubric={
            "name": "Review",
            "markdown": "Use evidence",
            "criteria": [{"id": "evidencia", "title": "Evidence", "description": "Documented evidence"}],
        },
        snapshot={"document_versions": []},
        transcript=[],
        question_count=0,
        max_questions=5,
        assessments=[],
        topic_counts={},
        previous_report=None,
    )
    result = await graph.ainvoke(state, config)
    heard = []
    for i in range(5):
        question = result["pending_question"]
        assert question and question["reviewer_id"] not in heard
        heard.append(question["reviewer_id"])
        result = await graph.ainvoke(
            Command(
                resume={
                    "action": "answer",
                    "command_id": str(i),
                    "question_id": question["id"],
                    "text": "La evidencia sigue pendiente.",
                }
            ),
            config,
        )
    assert len(set(heard)) == 5
    assert result["question_count"] == 5
    assert result["report"]
