"""Grafo del panel: supervisor, evaluador con evidencia citada, pausa humana e informe.

    START -> supervisor -> retrieve -> question -> wait (interrupt) -> assess -> supervisor
             supervisor -> report -> END            wait -> report (la persona termina)

Cada rol usa herramientas acotadas (ver app/tools.py) y el estado se persiste con
AsyncRedisSaver: una sesión pausada sobrevive al reinicio de API y worker.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Literal, TypedDict

from langgraph.checkpoint.redis.aio import AsyncRedisSaver
from langgraph.errors import GraphInterrupt
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, RetryPolicy, interrupt
from opentelemetry import trace
from pydantic import BaseModel, ConfigDict, Field, ValidationError, create_model

from app import prompts
from app.contracts import Citation, CriterionFeedback, Question, Report
from app.llm import ModelClient
from app.observability import content_attr, span
from app.rag import INDEX, InvalidCitation, RedisRAG, SearchSourcesOutput
from app.reporting import compare_feedback, comparison_text
from app.tools import COVERAGE_TOOL, CoverageOutput, VerifyCitationOutput, build_evidence_tools, invoke_tool

# Una salida del modelo que no respeta el esquema o cita un fragmento no provisto se
# reintenta una vez antes de dar el comando por fallido.
LLM_RETRY = RetryPolicy(max_attempts=2, initial_interval=0.5, retry_on=(ValidationError, InvalidCitation))


def now() -> str:
    return datetime.now(UTC).isoformat()


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SupervisorDecision(Strict):
    action: Literal["question", "finish"]
    profile_id: str
    criterion_id: str
    topic_id: str
    reason: str
    search_query: str = Field(default="", max_length=300)


class ReviewerQuestion(Strict):
    text: str = Field(min_length=1, max_length=1600)
    basis: Literal["document", "user_statement", "clarification"]
    citation_chunk_ids: list[str] = Field(default_factory=list, max_length=5)


class AnswerAssessment(Strict):
    status: Literal["supported", "partial", "missing"]
    observation: str = Field(min_length=1, max_length=2000)
    evidence_stage: Literal[
        "documented_result", "source_context", "user_report", "future_plan", "reasoned_explanation", "unclear"
    ] = "unclear"
    criterion_requires_execution: bool = True
    supporting_chunk_ids: list[str] = Field(default_factory=list, max_length=5)
    next_action: str | None = Field(default=None, max_length=600)


def calibrate_assessment(
    assessment: AnswerAssessment, question: dict[str, Any], criterion: dict[str, Any]
) -> dict[str, Any]:
    """Keep a cited plan or unsupported user claim from becoming achieved work."""
    cited = {citation["chunk_id"]: citation for citation in question["citations"]}
    if len(assessment.supporting_chunk_ids) != len(set(assessment.supporting_chunk_ids)):
        raise InvalidCitation("Assessment repeated a citation")
    if not set(assessment.supporting_chunk_ids) <= cited.keys():
        raise InvalidCitation("Assessment selected a chunk not cited in the question")
    stage = assessment.evidence_stage
    if stage == "documented_result" and not assessment.supporting_chunk_ids:
        stage = "unclear"
    if stage == "source_context" and not assessment.supporting_chunk_ids:
        stage = "unclear"
    documented_plan = (
        stage == "future_plan" and not assessment.criterion_requires_execution and bool(assessment.supporting_chunk_ids)
    )
    selected = (
        [cited[chunk_id] for chunk_id in assessment.supporting_chunk_ids]
        if stage in {"documented_result", "source_context"} or documented_plan
        else []
    )
    status = assessment.status
    observation = assessment.observation
    next_action = assessment.next_action
    topic = criterion["title"].lower()
    if stage == "future_plan":
        if documented_plan:
            observation = (
                f"La propuesta documentada aborda {topic}; esta valoración se refiere al plan, no a su ejecución."
            )
            next_action = next_action or f"Definir cómo se verificará el resultado previsto para {topic}."
        else:
            status = "partial" if status == "supported" else status
            observation = (
                f"Se describió un plan para {topic}, pero todavía no consta su ejecución ni un resultado verificable."
            )
            next_action = f"Ejecutar la actividad prevista para {topic} y registrar qué se obtuvo."
    elif stage == "user_report":
        status = "partial" if status == "supported" else status
        observation = f"Se afirmó un avance en {topic}, pero las fuentes citadas no verifican su ejecución o resultado."
        next_action = f"Vincular el avance afirmado en {topic} con un documento o registro de resultados."
    elif stage == "source_context":
        status = "partial" if status == "supported" else status
        observation = (
            f"La fuente citada aporta contexto sobre {topic}, pero no verifica por sí sola "
            "la ejecución o el resultado declarado."
        )
        next_action = f"Relacionar la fuente con un registro concreto de la ejecución y los resultados de {topic}."
    elif stage == "reasoned_explanation":
        if assessment.criterion_requires_execution:
            status = "partial" if status == "supported" else status
            observation = f"La explicación sobre {topic} no acredita una ejecución ni sus resultados."
            next_action = f"Aportar un registro de la ejecución y los resultados de {topic}."
        else:
            observation = (
                f"La respuesta ofrece una justificación de {topic}; esta valoración se basa en el "
                "turno de la persona, no en una ejecución verificada."
            )
            next_action = (
                next_action or f"Contrastar la justificación de {topic} con los resultados cuando estén disponibles."
            )
    elif stage == "unclear":
        status = "partial" if status == "supported" else status
        observation = (
            f"No se pudo distinguir qué se completó en {topic} ni verificar su resultado con las fuentes citadas."
        )
        next_action = f"Separar lo realizado de lo previsto en {topic} y aportar evidencia del resultado."
    return {
        "status": status,
        "observation": observation,
        "citations": selected,
        "next_action": next_action or f"Aportar evidencia verificable para {topic}.",
    }


def with_chunk_choices(schema: type[BaseModel], field: str, chunk_ids: list[str]) -> type[BaseModel]:
    """Restringe un campo de IDs de fragmentos a los provistos en este turno.

    El JSON Schema resultante lleva un ``enum``: en modo estricto el proveedor no puede
    devolver un ID inventado ni uno de otra sesión, y Pydantic lo vuelve a validar.
    """
    if not chunk_ids:
        return schema
    choice = Literal[tuple(dict.fromkeys(chunk_ids))]  # type: ignore[valid-type]
    return create_model(
        schema.__name__,
        __base__=schema,
        **{field: (list[choice], Field(default_factory=list, max_length=5))},
    )


def previous_summary(report: dict[str, Any] | None) -> dict[str, Any] | None:
    """Informe anterior sin sus citas: los IDs de otra sesión no son citables en esta."""
    if not report:
        return None
    keys = ("criterion_id", "status", "observation", "next_action")
    return {
        "criterion_feedback": [{key: item.get(key) for key in keys} for item in report.get("criterion_feedback", [])],
        "next_steps": report.get("next_steps", []),
    }


def canonical_citations(chunk_ids: list[str], retrieved: list[dict[str, Any]]) -> list[Citation]:
    """Materialize model-selected IDs from trusted retrieval output."""
    by_id = {item["chunk_id"]: item for item in retrieved}
    if len(chunk_ids) != len(set(chunk_ids)):
        raise InvalidCitation("Reviewer repeated a citation")
    try:
        return [Citation.model_validate(by_id[chunk_id]) for chunk_id in chunk_ids]
    except KeyError as exc:
        raise InvalidCitation("Reviewer selected a chunk not supplied by retrieval") from exc


def command_input(command: dict[str, Any], state: dict[str, Any] | None) -> str:
    """Lo que aportó la persona en este comando (para la traza)."""
    payload = command.get("payload") or {}
    if command["kind"] == "ANSWER":
        return str(payload.get("text", ""))
    if command["kind"] == "FINISH":
        return "La persona eligió terminar la sesión."
    if command["kind"] == "START_SESSION":
        return str((state or {}).get("presentation") or "Inicio de la sesión.")
    return f"Indexar {payload.get('document_id', '')} v{payload.get('version', '')}"


def command_output(command: dict[str, Any], state: dict[str, Any] | None) -> str:
    """Lo que devolvió el panel tras el comando: la nueva pregunta o el resumen del informe."""
    if not state:
        return "Documento indexado." if command["kind"] == "INDEX_DOCUMENT" else ""
    report = state.get("report")
    if report:
        statuses = ", ".join(f"{item['criterion_id']}: {item['status']}" for item in report["criterion_feedback"])
        return f"Informe listo. {statuses}"
    pending = state.get("pending_question") or {}
    return pending.get("text", "")


class PanelState(TypedDict, total=False):
    project_id: str
    session_id: str
    objective: str
    presentation: str
    snapshot: dict[str, Any]
    profiles: list[dict[str, Any]]
    rubric: dict[str, Any]
    transcript: list[dict[str, Any]]
    question_count: int
    max_questions: int
    decision: dict[str, Any]
    citations: list[dict[str, Any]]
    pending_question: dict[str, Any] | None
    answer: str
    last_command_id: str
    next_action: str
    assessments: list[dict[str, Any]]
    previous_report: dict[str, Any] | None
    topic_counts: dict[str, int]
    report: dict[str, Any] | None


class GraphEngine:
    def __init__(self, repo: Any, settings: Any):
        self.repo = repo
        self.settings = settings
        self.model = ModelClient(settings, repo.redis)
        signature = "demo:hash-v1" if self.model.mode == "demo" else f"live:{self.model.embedding_model}"
        self.rag = RedisRAG(
            repo.redis, self.model.embed, self.model.dimensions, signature, index=getattr(settings, "rag_index", INDEX)
        )

    async def execute(self, command: dict[str, Any]) -> None:
        with span(
            "panellab.command",
            **{
                "openinference.span.kind": "CHAIN",
                "panellab.project_id": command["project_id"],
                "panellab.session_id": command.get("session_id") or "",
                "session.id": command.get("session_id") or "",
                "panellab.job_id": command["job_id"],
                "panellab.command_id": command.get("logical_id", command["id"]),
                "panellab.command_kind": command["kind"],
                "panellab.llm_mode": self.model.mode,
                "llm.model_name": self.model.model_name,
            },
        ) as trace_span:
            # input/output del span raíz: Phoenix los usa en la vista Sessions para mostrar
            # cada sesión como una conversación (qué dijo la persona y qué devolvió el panel).
            state = await self._execute(command)
            trace_span.set_attribute("input.value", content_attr(command_input(command, state)))
            trace_span.set_attribute("output.value", content_attr(command_output(command, state)))

    async def _execute(self, command: dict[str, Any]) -> dict[str, Any] | None:
        kind = command["kind"]
        logical_id = command.get("logical_id", command["id"])
        if kind == "INDEX_DOCUMENT":
            await self._index(command)
            return None
        if kind not in {"START_SESSION", "ANSWER", "FINISH"}:
            raise ValueError(f"Unknown command kind: {kind}")
        session = await self.repo.get("session", command["session_id"])
        if not session or session["project_id"] != command["project_id"]:
            raise ValueError("Session missing or outside project")
        async with AsyncRedisSaver.from_conn_string(str(self.settings.redis_url)) as saver:
            await saver.asetup()
            graph = self._build_graph().compile(checkpointer=saver)
            config = {"configurable": {"thread_id": f"panellab:{session['id']}"}, "recursion_limit": 30}
            checkpoint = await graph.aget_state(config)
            state = checkpoint.values or {}
            if kind == "START_SESSION":
                if not state:
                    initial = await self._initial_state(session, logical_id)
                    await graph.ainvoke(initial, config)
                elif checkpoint.next and not any(task.interrupts for task in checkpoint.tasks):
                    await graph.ainvoke(None, config)
            else:
                if not state:
                    raise ValueError("No session checkpoint to resume")
                if state.get("last_command_id") == logical_id:
                    if checkpoint.next and not any(task.interrupts for task in checkpoint.tasks):
                        await graph.ainvoke(None, config)
                else:
                    pending = state.get("pending_question")
                    if not pending or pending["id"] != command["payload"].get("question_id"):
                        raise ValueError("Question is no longer pending")
                    if not any(task.interrupts for task in checkpoint.tasks):
                        raise ValueError("Session is not waiting for a response")
                    await graph.ainvoke(
                        Command(
                            resume={
                                "action": "finish" if kind == "FINISH" else "answer",
                                "command_id": logical_id,
                                "question_id": pending["id"],
                                "text": command["payload"].get("text", ""),
                            }
                        ),
                        config,
                    )
            latest = await graph.aget_state(config)
            await self._project(session, latest.values, latest.next, command)
            return latest.values

    async def _index(self, command: dict[str, Any]) -> None:
        payload = command["payload"]
        key = f"{payload['document_id']}:{payload['version']}"
        document = await self.repo.get("document", key)
        if not document or document["project_id"] != command["project_id"]:
            raise ValueError("Document missing or outside project")
        if document["index_status"] == "READY":
            return
        document["index_status"] = "RUNNING"
        await self.repo.put("document", key, document)
        await self.rag.index_document(document)
        document["index_status"] = "READY"
        await self.repo.put("document", key, document)

    async def _initial_state(self, session: dict[str, Any], command_id: str) -> PanelState:
        snapshot = session["snapshot"]
        profiles = []
        for ref in snapshot["profile_versions"]:
            profile = await self.repo.get("profile", f"{session['project_id']}:{ref['id']}:{ref['version']}")
            if not profile or profile["project_id"] != session["project_id"]:
                raise ValueError("Profile missing from snapshot")
            profiles.append(profile)
        rubric_ref = snapshot["rubric_version"]
        rubric = await self.repo.get("rubric", f"{session['project_id']}:{rubric_ref['id']}:{rubric_ref['version']}")
        if not rubric or rubric["project_id"] != session["project_id"]:
            raise ValueError("Rubric missing from snapshot")
        for ref in snapshot["document_versions"]:
            document = await self.repo.get("document", f"{ref['document_id']}:{ref['version']}")
            if not document or document["project_id"] != session["project_id"] or document["index_status"] != "READY":
                raise ValueError("Snapshot source is not indexed")
        previous = None
        if snapshot.get("previous_session_id"):
            old_session = await self.repo.get("session", snapshot["previous_session_id"])
            if (
                not old_session
                or old_session["project_id"] != session["project_id"]
                or old_session["status"] != "COMPLETED"
            ):
                raise ValueError("Previous session unavailable")
            previous = await self.repo.get("report", old_session["id"])
        transcript = [dict(turn) for turn in session["transcript"]]
        presentation = next((turn["text"] for turn in transcript if turn["kind"] == "presentation"), "")
        return {
            "project_id": session["project_id"],
            "session_id": session["id"],
            "objective": session["objective"],
            "presentation": presentation,
            "snapshot": snapshot,
            "profiles": profiles,
            "rubric": rubric,
            "transcript": transcript,
            "question_count": 0,
            "max_questions": session["max_questions"],
            "assessments": [],
            "previous_report": previous,
            "topic_counts": {},
            "last_command_id": command_id,
            "pending_question": None,
            "report": None,
        }

    def _build_graph(self) -> StateGraph:
        async def supervisor(state: PanelState) -> dict[str, Any]:
            if state.get("question_count", 0) >= state["max_questions"]:
                return {"next_action": "finish"}
            counts = state.get("topic_counts", {})
            coverage = await invoke_tool(
                COVERAGE_TOOL,
                {
                    "profiles": [{"profile_id": p["profile_id"], "focus": p["focus"]} for p in state["profiles"]],
                    "criteria": [{"id": c["id"], "title": c["title"]} for c in state["rubric"]["criteria"]],
                    "heard_profile_ids": sorted(
                        {turn["author_id"] for turn in state["transcript"] if turn["kind"] == "question"}
                    ),
                    "topic_counts": counts,
                },
                CoverageOutput,
            )
            if coverage.should_finish:
                return {"next_action": "finish"}
            allowed = [pair.model_dump() for pair in coverage.allowed_pairs]
            decision = await self.model.structured(
                prompts.SUPERVISOR,
                {
                    "profiles": state["profiles"],
                    "criteria": state["rubric"]["criteria"],
                    "question_count": state.get("question_count", 0),
                    "assessments": state.get("assessments", []),
                    "previous_report": previous_summary(state.get("previous_report")),
                    "objective": state["objective"],
                    "presentation": state["presentation"],
                    "recent_turns": state["transcript"][-4:],
                    "topic_counts": counts,
                    "coverage": coverage.reason,
                    "allowed_pairs": allowed,
                },
                SupervisorDecision,
            )
            if decision.action == "finish" and not coverage.unheard_profile_ids and state.get("question_count", 0) >= 3:
                return {"next_action": "finish"}
            valid_pairs = {(pair["profile_id"], pair["criterion_id"]) for pair in allowed}
            if (decision.profile_id, decision.criterion_id) not in valid_pairs or decision.action == "finish":
                # El modelo propuso un par fuera de la cobertura o quiso cerrar antes de la
                # primera ronda: se toma el primer par válido calculado por la herramienta.
                decision = decision.model_copy(
                    update={
                        "profile_id": allowed[0]["profile_id"],
                        "criterion_id": allowed[0]["criterion_id"],
                        "reason": "Completar la cobertura mínima con un par válido",
                    }
                )
            decision = decision.model_copy(update={"action": "question", "topic_id": decision.criterion_id})
            return {"decision": decision.model_dump(), "next_action": "question"}

        async def retrieve(state: PanelState) -> dict[str, Any]:
            criterion = next(
                item for item in state["rubric"]["criteria"] if item["id"] == state["decision"]["criterion_id"]
            )
            search, _ = build_evidence_tools(self.rag, state["project_id"], state["snapshot"]["document_versions"])
            # Primero la consulta que redactó el supervisor; si no encuentra evidencia, una
            # consulta derivada del criterio y del objetivo (ciclo de reintento del agente).
            model_query = " ".join(str(state["decision"].get("search_query", "")).split())
            criterion_query = " ".join(f"{criterion['title']} {criterion['description']} {state['objective']}".split())
            result = SearchSourcesOutput(evidence_status="insufficient", citations=[])
            for query in dict.fromkeys(q[:600] for q in (model_query, criterion_query) if len(q) >= 3):
                result = await invoke_tool(search, {"query": query, "top_k": 5}, SearchSourcesOutput)
                if result.evidence_status == "found":
                    break
            return {"citations": [citation.model_dump() for citation in result.citations]}

        async def question(state: PanelState) -> dict[str, Any]:
            decision = state["decision"]
            criterion = next(item for item in state["rubric"]["criteria"] if item["id"] == decision["criterion_id"])
            profile = next(item for item in state["profiles"] if item["profile_id"] == decision["profile_id"])
            generated = await self.model.structured(
                prompts.reviewer(profile["name"], profile["role"], profile["markdown"]),
                {
                    "criterion": criterion,
                    "presentation": state["presentation"],
                    "citations": state.get("citations", []),
                    "previous_report": previous_summary(state.get("previous_report")),
                    "recent_turns": state["transcript"][-4:],
                },
                with_chunk_choices(
                    ReviewerQuestion,
                    "citation_chunk_ids",
                    [item["chunk_id"] for item in state.get("citations", [])],
                ),
            )
            if not state.get("citations") and generated.basis == "document":
                # Sin fragmentos recuperados no puede haber una pregunta basada en documentos:
                # se formula como pedido de aclaración en vez de fallar el turno.
                generated = generated.model_copy(update={"basis": "clarification", "citation_chunk_ids": []})
            citations = canonical_citations(generated.citation_chunk_ids, state.get("citations", []))
            _, verify = build_evidence_tools(self.rag, state["project_id"], state["snapshot"]["document_versions"])
            for citation in citations:
                check = await invoke_tool(verify, {"citation": citation.model_dump()}, VerifyCitationOutput)
                if not check.valid:
                    raise InvalidCitation(check.reason)
            if generated.basis == "document" and not citations:
                raise InvalidCitation("Document-based question must cite a source")
            if generated.basis == "user_statement" and not state["transcript"]:
                raise ValueError("No user statement exists")
            number = state.get("question_count", 0) + 1
            question_obj = Question(
                id=f"{state['session_id']}:q{number}",
                reviewer_id=decision["profile_id"],
                criterion_id=decision["criterion_id"],
                text=generated.text,
                basis=generated.basis,
                citations=citations,
                related_turn_ids=[],
            )
            transcript = [
                *state["transcript"],
                {
                    "id": question_obj.id,
                    "kind": "question",
                    "author_id": decision["profile_id"],
                    "text": question_obj.text,
                    "citations": [item.model_dump() for item in question_obj.citations],
                    "created_at": now(),
                },
            ]
            topic_counts = dict(state.get("topic_counts", {}))
            topic_counts[decision["topic_id"]] = topic_counts.get(decision["topic_id"], 0) + 1
            return {
                "question_count": number,
                "pending_question": question_obj.model_dump(),
                "topic_counts": topic_counts,
                "transcript": transcript,
            }

        def wait_for_answer(state: PanelState) -> dict[str, Any]:
            # This node has no side effects before interrupt: LangGraph may run it again.
            incoming = interrupt({"question_id": state["pending_question"]["id"]})
            if incoming.get("question_id") != state["pending_question"]["id"]:
                raise ValueError("Response targets a different question")
            action = incoming.get("action")
            if action not in {"answer", "finish"}:
                raise ValueError("Invalid response action")
            if action == "finish":
                return {"next_action": "finish", "last_command_id": incoming["command_id"], "pending_question": None}
            answer = str(incoming.get("text", "")).strip()
            if not answer or len(answer) > 4000:
                raise ValueError("Answer length invalid")
            transcript = [
                *state["transcript"],
                {
                    "id": f"{state['pending_question']['id']}:answer",
                    "kind": "answer",
                    "author_id": "presenter",
                    "text": answer,
                    "citations": [],
                    "created_at": now(),
                },
            ]
            return {
                "next_action": "answer",
                "answer": answer,
                "last_command_id": incoming["command_id"],
                "transcript": transcript,
            }

        async def assess(state: PanelState) -> dict[str, Any]:
            pending = state["pending_question"]
            criterion = next(item for item in state["rubric"]["criteria"] if item["id"] == pending["criterion_id"])
            profile = next(item for item in state["profiles"] if item["profile_id"] == pending["reviewer_id"])
            assessment = await self.model.structured(
                prompts.ASSESSMENT,
                {
                    "question": pending,
                    "answer": state["answer"],
                    "citations": pending["citations"],
                    "presentation": state["presentation"],
                    "criterion": criterion,
                    "rubric": {"name": state["rubric"]["name"], "markdown": state["rubric"]["markdown"]},
                    "reviewer": {"name": profile["name"], "role": profile["role"], "style": profile["style"]},
                },
                with_chunk_choices(
                    AnswerAssessment,
                    "supporting_chunk_ids",
                    [item["chunk_id"] for item in pending["citations"]],
                ),
            )
            calibrated = calibrate_assessment(assessment, pending, criterion)
            record = {
                "criterion_id": pending["criterion_id"],
                **calibrated,
                "related_turn_ids": [pending["id"], f"{pending['id']}:answer"],
            }
            return {"assessments": [*state.get("assessments", []), record], "pending_question": None}

        async def report(state: PanelState) -> dict[str, Any]:
            feedback = []
            for criterion in state["rubric"]["criteria"]:
                records = [entry for entry in state.get("assessments", []) if entry["criterion_id"] == criterion["id"]]
                if records:
                    last = records[-1]
                    feedback.append(
                        CriterionFeedback(
                            criterion_id=criterion["id"],
                            status=last["status"],
                            observation=last["observation"],
                            citations=[Citation.model_validate(c) for c in last["citations"]],
                            related_turn_ids=last["related_turn_ids"],
                            next_action=last.get("next_action")
                            or f"Aportar evidencia verificable para {criterion['title'].lower()}.",
                        ).model_dump()
                    )
                else:
                    feedback.append(
                        CriterionFeedback(
                            criterion_id=criterion["id"],
                            status="not_assessed",
                            observation="Este criterio no fue tratado en la sesión.",
                        ).model_dump()
                    )
            prior = state.get("previous_report")
            titles = {item["id"]: item["title"] for item in state["rubric"]["criteria"]}
            changes = compare_feedback(prior, feedback, titles) if prior else []
            comparison = comparison_text(changes) if prior else None
            report_obj = Report(
                id=state["session_id"],
                session_id=state["session_id"],
                project_id=state["project_id"],
                criterion_feedback=[CriterionFeedback.model_validate(x) for x in feedback],
                strengths=[item["observation"] for item in feedback if item["status"] == "supported"],
                pending_questions=[
                    item["text"]
                    for item in state["transcript"]
                    if item["kind"] == "question"
                    and not any(answer["id"] == f"{item['id']}:answer" for answer in state["transcript"])
                ],
                next_steps=[item["next_action"] for item in feedback if item.get("next_action")],
                comparison=comparison,
                comparison_items=changes,
                created_at=now(),
            )
            return {"report": report_obj.model_dump(mode="json")}

        def traced(name: str, node: Any) -> Any:
            async def run(state: PanelState) -> dict[str, Any]:
                with span(
                    f"graph.node.{name}",
                    **{
                        "openinference.span.kind": "CHAIN",
                        "panellab.project_id": state["project_id"],
                        "panellab.session_id": state["session_id"],
                        "session.id": state["session_id"],
                    },
                ):
                    return await node(state)

            return run

        def traced_wait(state: PanelState) -> dict[str, Any]:
            # interrupt is expected control flow, so it is not recorded as an error.
            with trace.get_tracer("panellab").start_as_current_span(
                "graph.node.wait", record_exception=False, set_status_on_exception=False
            ) as current:
                current.set_attribute("openinference.span.kind", "CHAIN")
                current.set_attribute("panellab.project_id", state["project_id"])
                current.set_attribute("panellab.session_id", state["session_id"])
                current.set_attribute("session.id", state["session_id"])
                try:
                    result = wait_for_answer(state)
                except GraphInterrupt:
                    # Pausa esperando a la persona: flujo previsto, no un error.
                    current.set_attribute("panellab.paused", True)
                    current.set_status(trace.Status(trace.StatusCode.OK))
                    raise
                current.set_status(trace.Status(trace.StatusCode.OK))
                return result

        def route_after_supervisor(state: PanelState) -> Literal["retrieve", "report"]:
            """El supervisor delega otra pregunta o da la sesión por cubierta."""
            return "report" if state["next_action"] == "finish" else "retrieve"

        def route_after_answer(state: PanelState) -> Literal["assess", "report"]:
            """La persona respondió (se valora) o eligió terminar (se informa)."""
            return "report" if state["next_action"] == "finish" else "assess"

        graph = StateGraph(PanelState)
        graph.add_node("supervisor", traced("supervisor", supervisor), retry_policy=LLM_RETRY)
        graph.add_node("retrieve", traced("retrieve", retrieve))
        graph.add_node("question", traced("question", question), retry_policy=LLM_RETRY)
        graph.add_node("wait", traced_wait)
        graph.add_node("assess", traced("assess", assess), retry_policy=LLM_RETRY)
        graph.add_node("report", traced("report", report))
        graph.add_edge(START, "supervisor")
        graph.add_conditional_edges("supervisor", route_after_supervisor, ["retrieve", "report"])
        graph.add_edge("retrieve", "question")
        graph.add_edge("question", "wait")
        graph.add_conditional_edges("wait", route_after_answer, ["assess", "report"])
        graph.add_edge("assess", "supervisor")
        graph.add_edge("report", END)
        return graph

    async def _project(
        self, session: dict[str, Any], state: dict[str, Any], next_nodes: tuple[str, ...], command: dict[str, Any]
    ) -> None:
        if not state:
            raise RuntimeError("Graph has no checkpoint after execution")
        projected_status = "COMPLETED" if state.get("report") else "WAITING_RESPONSE"
        if (
            session.get("status") == projected_status
            and session.get("transcript") == state["transcript"]
            and session.get("pending_question") == state.get("pending_question")
        ):
            return
        session["transcript"] = state["transcript"]
        session["question_count"] = state["question_count"]
        session["pending_question"] = state.get("pending_question")
        session["active_job_id"] = None
        session["updated_at"] = now()
        if state.get("report"):
            await self.repo.put("report", session["id"], state["report"])
            session["status"] = "COMPLETED"
            session["report_id"] = session["id"]
        elif next_nodes and state.get("pending_question"):
            session["status"] = "WAITING_RESPONSE"
        else:
            raise RuntimeError("Graph stopped outside a durable user pause or final report")
        session["revision"] = int(session.get("revision", 0)) + 1
        await self.repo.put("session", session["id"], session)
