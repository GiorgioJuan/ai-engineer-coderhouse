"""Validated HTTP and worker boundaries for PanelLab."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class SessionStatus(StrEnum):
    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    WAITING_RESPONSE = "WAITING_RESPONSE"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class JobStatus(StrEnum):
    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"


class Citation(Contract):
    document_id: str
    version: int = Field(ge=1)
    chunk_id: str
    section: str
    excerpt: str = Field(min_length=1, max_length=1200)


class Question(Contract):
    id: str
    reviewer_id: str
    criterion_id: str
    text: str = Field(min_length=1, max_length=1600)
    basis: Literal["document", "user_statement", "clarification"]
    citations: list[Citation] = Field(default_factory=list, max_length=5)
    related_turn_ids: list[str] = Field(default_factory=list)


class Turn(Contract):
    id: str
    kind: Literal["presentation", "question", "answer", "notice"]
    author_id: str
    text: str = Field(min_length=1)
    citations: list[Citation] = Field(default_factory=list)
    created_at: datetime


class ProjectCreate(Contract):
    title: str = Field(min_length=1, max_length=160)
    context: str = Field(min_length=1, max_length=8000)
    objective: str = Field(min_length=1, max_length=2000)


class ProjectPatch(Contract):
    expected_revision: int = Field(ge=0)
    title: str | None = Field(default=None, min_length=1, max_length=160)
    context: str | None = Field(default=None, min_length=1, max_length=8000)
    objective: str | None = Field(default=None, min_length=1, max_length=2000)
    # Archivar oculta el proyecto de la lista sin borrar sus datos; es reversible.
    archived: bool | None = None


class Project(ProjectCreate):
    id: str
    revision: int = Field(ge=0)
    archived: bool = False
    created_at: datetime
    updated_at: datetime


class DocumentCreate(Contract):
    title: str = Field(min_length=1, max_length=160)
    kind: Literal["source", "presentation", "progress"]
    text: str = Field(min_length=1, max_length=200000)
    document_id: str | None = None


class PdfExtraction(Contract):
    title: str = Field(min_length=1, max_length=160)
    text: str = Field(min_length=1, max_length=200000)
    page_count: int = Field(ge=1, le=50)
    warnings: list[str] = Field(default_factory=list)


class DocumentRef(Contract):
    document_id: str
    version: int = Field(ge=1)


class DocumentVersion(DocumentCreate):
    document_id: str
    project_id: str
    version: int = Field(ge=1)
    content_hash: str
    index_status: Literal["QUEUED", "RUNNING", "READY", "FAILED"]
    created_at: datetime


class MarkdownCreate(Contract):
    markdown: str = Field(min_length=1, max_length=32768)
    profile_id: str | None = None
    rubric_id: str | None = None


class Criterion(Contract):
    id: str = Field(pattern=r"^[a-z][a-z0-9_-]{1,63}$")
    title: str = Field(min_length=1, max_length=160)
    description: str = Field(min_length=1, max_length=1200)


class ProfileVersion(Contract):
    profile_id: str
    project_id: str
    version: int = Field(ge=1)
    name: str
    role: str
    focus: list[str] = Field(min_length=1)
    style: str
    markdown: str
    content_hash: str
    created_at: datetime


class RubricVersion(Contract):
    rubric_id: str
    project_id: str
    version: int = Field(ge=1)
    name: str
    criteria: list[Criterion] = Field(min_length=1)
    markdown: str
    content_hash: str
    created_at: datetime


class VersionRef(Contract):
    id: str
    version: int = Field(ge=1)


class SessionCreate(Contract):
    objective: str = Field(min_length=1, max_length=2000)
    presentation: str = Field(min_length=1, max_length=12000)
    profile_versions: list[VersionRef] = Field(min_length=1, max_length=5)
    rubric_version: VersionRef
    document_versions: list[DocumentRef] = Field(min_length=1, max_length=30)
    previous_session_id: str | None = None
    max_questions: int = Field(default=5, ge=3, le=5)

    @model_validator(mode="after")
    def enough_questions_for_panel(self):
        if self.max_questions < len(self.profile_versions):
            raise ValueError("Select at least one question per reviewer")
        return self


class SessionSnapshot(Contract):
    profile_versions: list[VersionRef]
    rubric_version: VersionRef
    document_versions: list[DocumentRef]
    previous_session_id: str | None = None


class SessionView(Contract):
    id: str
    project_id: str
    objective: str
    status: SessionStatus
    revision: int = Field(ge=0)
    question_count: int = Field(ge=0)
    max_questions: int = Field(ge=3, le=5)
    pending_question: Question | None = None
    transcript: list[Turn]
    active_job_id: str | None = None
    report_id: str | None = None
    snapshot: SessionSnapshot
    created_at: datetime
    updated_at: datetime


class AnswerRequest(Contract):
    question_id: str
    expected_revision: int = Field(ge=0)
    text: str = Field(min_length=1, max_length=4000)


class FinishRequest(Contract):
    question_id: str
    expected_revision: int = Field(ge=0)


class CriterionFeedback(Contract):
    criterion_id: str
    status: Literal["supported", "partial", "missing", "not_assessed"]
    observation: str
    citations: list[Citation] = Field(default_factory=list)
    related_turn_ids: list[str] = Field(default_factory=list)
    next_action: str | None = None


class CriterionChange(Contract):
    """Cómo cambió un criterio respecto de la sesión anterior."""

    criterion_id: str
    title: str
    previous_status: Literal["supported", "partial", "missing", "not_assessed"]
    current_status: Literal["supported", "partial", "missing", "not_assessed"]
    previous_sources: int = Field(ge=0)
    current_sources: int = Field(ge=0)


class Report(Contract):
    id: str
    session_id: str
    project_id: str
    criterion_feedback: list[CriterionFeedback]
    strengths: list[str]
    pending_questions: list[str]
    next_steps: list[str]
    comparison: str | None = None
    comparison_items: list[CriterionChange] = Field(default_factory=list)
    created_at: datetime


class JobError(Contract):
    code: str
    message: str
    retryable: bool


class Job(Contract):
    id: str
    command_id: str
    kind: Literal["INDEX_DOCUMENT", "START_SESSION", "ANSWER", "FINISH"]
    project_id: str
    session_id: str | None = None
    document_id: str | None = None
    status: JobStatus
    attempt: int = Field(ge=0)
    error: JobError | None = None
    retry_job_id: str | None = None
    created_at: datetime
    updated_at: datetime


class JobAccepted(Contract):
    job_id: str
    session_id: str | None = None
    document_id: str | None = None
    status: Literal["QUEUED"] = "QUEUED"
    status_url: str


class DemoJobs(Contract):
    items: list[JobAccepted]


class RetryRequest(Contract):
    expected_attempt: int = Field(ge=1)


class ErrorBody(Contract):
    code: str
    message: str


class HealthResponse(Contract):
    status: Literal["ok"] = "ok"


class ReadinessResponse(Contract):
    status: Literal["ready", "degraded", "unavailable"]
    llm_mode: Literal["demo", "live"]
    redis: bool
    worker: bool
    observability: bool


class ProjectPage(Contract):
    items: list[Project]
    next_cursor: str | None = None


class DocumentPage(Contract):
    items: list[DocumentVersion]
    next_cursor: str | None = None


class ProfilePage(Contract):
    items: list[ProfileVersion]
    next_cursor: str | None = None


class RubricPage(Contract):
    items: list[RubricVersion]
    next_cursor: str | None = None


class SessionPage(Contract):
    items: list[SessionView]
    next_cursor: str | None = None
