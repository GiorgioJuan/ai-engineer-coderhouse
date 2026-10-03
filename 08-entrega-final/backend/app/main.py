from __future__ import annotations

import asyncio
import hashlib
import json
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

import httpx
import redis.asyncio as redis
from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from redis.exceptions import RedisError, WatchError
from starlette.exceptions import HTTPException as StarletteHTTPException

from .config import Settings, get_settings
from .content import ContentError, digest, parse_markdown, retired_catalog_profile, template_files
from .contracts import (
    AnswerRequest,
    DemoJobs,
    DocumentCreate,
    DocumentPage,
    DocumentVersion,
    ErrorBody,
    FinishRequest,
    HealthResponse,
    Job,
    JobAccepted,
    MarkdownCreate,
    PdfExtraction,
    ProfilePage,
    ProfileVersion,
    Project,
    ProjectCreate,
    ProjectPage,
    ProjectPatch,
    ReadinessResponse,
    Report,
    RetryRequest,
    RubricPage,
    RubricVersion,
    SessionCreate,
    SessionPage,
    SessionSnapshot,
    SessionView,
    Turn,
)
from .observability import flush_observability, setup_observability, span
from .pdf_import import MAX_PDF_BYTES, PdfImportError, extract_pdf_isolated
from .reporting import compare_feedback, comparison_text
from .storage import Conflict, Repository, dumps


def now() -> str:
    return datetime.now(UTC).isoformat()


def uid() -> str:
    return uuid4().hex


def hash_request(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, default=str).encode()).hexdigest()


def page(items: list[dict[str, Any]], cursor: str | None, limit: int) -> dict[str, Any]:
    ordered = sorted(
        items,
        key=lambda item: (
            item.get("created_at", ""),
            item.get("id") or item.get("document_id") or item.get("profile_id") or item.get("rubric_id"),
        ),
    )
    try:
        start = int(cursor or "0")
    except ValueError as exc:
        raise HTTPException(422, detail="invalid cursor") from exc
    if start < 0:
        raise HTTPException(422, detail="invalid cursor")
    return {
        "items": ordered[start : start + limit],
        "next_cursor": str(start + limit) if start + limit < len(ordered) else None,
    }


async def repository(request: Request) -> Repository:
    return request.app.state.repo


def require_key(idempotency_key: str | None = Header(default=None, alias="Idempotency-Key")) -> str:
    if not idempotency_key or len(idempotency_key) > 128:
        raise HTTPException(422, detail="Idempotency-Key header is required (max 128 chars)")
    return idempotency_key


async def require_project(repo: Repository, project_id: str) -> dict[str, Any]:
    item = await repo.get("project", project_id)
    if not item:
        raise HTTPException(404, detail="project not found")
    return item


async def require_session(repo: Repository, session_id: str) -> dict[str, Any]:
    item = await repo.get("session", session_id)
    if not item:
        raise HTTPException(404, detail="session not found")
    return item


async def import_templates(repo: Repository, settings: Settings, project_id: str) -> None:
    for kind in ("profile", "rubric"):
        for file in template_files(settings.config_dir, kind):
            markdown = await asyncio.to_thread(file.read_text, encoding="utf-8")
            meta = parse_markdown(markdown, kind)
            if kind == "profile" and retired_catalog_profile(meta["id"]):
                continue
            key = f"{project_id}:{meta['id']}:1"
            if await repo.get(kind, key):
                continue
            item = {
                "project_id": project_id,
                f"{kind}_id": meta["id"],
                "version": 1,
                "name": meta["name"],
                "markdown": markdown,
                "content_hash": digest(markdown),
                "created_at": now(),
            }
            if kind == "profile":
                item.update(role=meta["role"], focus=meta["focus"], style=meta["style"])
            else:
                item["criteria"] = meta["criteria"]
            await repo.put(kind, key, item)


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    client = redis.from_url(str(settings.redis_url), decode_responses=False, socket_timeout=15)
    app.state.settings = settings
    app.state.repo = Repository(client)
    setup_observability(settings, "panellab-api")
    try:
        yield
    finally:
        flush_observability()
        await client.aclose()


app = FastAPI(
    title="PanelLab API", version="0.1.0", docs_url="/api/docs", openapi_url="/api/openapi.json", lifespan=lifespan
)


# Sólo se trazan los comandos. Las lecturas (GET) son en su mayoría polling de la interfaz y
# taparían en Phoenix las trazas que importan: el trabajo del grafo queda en el span del comando.
TRACED_METHODS = {"POST", "PUT", "PATCH", "DELETE"}


@app.middleware("http")
async def trace_http(request: Request, call_next):
    if request.method not in TRACED_METHODS:
        return await call_next(request)
    with span(
        f"{request.method} {request.url.path}",
        **{"openinference.span.kind": "CHAIN", "http.request.method": request.method},
    ) as current:
        try:
            response = await call_next(request)
        except Exception:
            current.set_attribute("http.response.status_code", 500)
            raise
        route = getattr(request.scope.get("route"), "path", "unmatched")
        # Nombre por plantilla de ruta (baja cardinalidad), sin IDs ni datos del cuerpo.
        current.update_name(f"{request.method} {route}")
        current.set_attribute("http.route", route)
        current.set_attribute("http.response.status_code", response.status_code)
        return response


@app.exception_handler(Conflict)
async def conflict_handler(_request: Request, exc: Conflict):
    return JSONResponse(status_code=409, content={"code": "conflict", "message": str(exc)})


@app.exception_handler(ContentError)
async def content_handler(_request: Request, exc: ContentError):
    return JSONResponse(status_code=422, content={"code": "invalid_content", "message": str(exc)})


@app.exception_handler(RedisError)
async def redis_handler(_request: Request, _exc: RedisError):
    return JSONResponse(status_code=503, content={"code": "redis_unavailable", "message": "storage unavailable"})


@app.exception_handler(StarletteHTTPException)
async def http_handler(_request: Request, exc: StarletteHTTPException):
    message = exc.detail if isinstance(exc.detail, str) else "request failed"
    return JSONResponse(status_code=exc.status_code, content={"code": f"http_{exc.status_code}", "message": message})


@app.exception_handler(RequestValidationError)
async def validation_handler(_request: Request, exc: RequestValidationError):
    fields = ", ".join(".".join(map(str, error["loc"])) for error in exc.errors()[:5])
    return JSONResponse(status_code=422, content={"code": "validation_error", "message": f"invalid fields: {fields}"})


ERRORS = {409: {"model": ErrorBody}, 413: {"model": ErrorBody}, 422: {"model": ErrorBody}, 503: {"model": ErrorBody}}


@app.get("/api/health/live", response_model=HealthResponse)
async def live():
    return HealthResponse()


@app.get("/api/health/ready", response_model=ReadinessResponse)
async def ready(request: Request, repo: Repository = Depends(repository)):
    try:
        await repo.redis.ping()
        worker_raw = await repo.redis.get("panellab:worker:heartbeat")
        worker = bool(worker_raw and (datetime.now(UTC).timestamp() - float(worker_raw) < 30))
        observable = False
        try:
            async with httpx.AsyncClient(timeout=1) as client:
                response = await client.get(str(request.app.state.settings.phoenix_endpoint))
                observable = response.status_code < 500
        except httpx.HTTPError:
            pass
        return ReadinessResponse(
            status="ready" if worker and observable else "degraded",
            llm_mode=request.app.state.settings.llm_mode,
            redis=True,
            worker=worker,
            observability=observable,
        )
    except RedisError:
        return JSONResponse(
            status_code=503,
            content=ReadinessResponse(
                status="unavailable",
                llm_mode=request.app.state.settings.llm_mode,
                redis=False,
                worker=False,
                observability=False,
            ).model_dump(),
        )


@app.post("/api/projects", response_model=Project, status_code=201, responses=ERRORS)
async def create_project(
    body: ProjectCreate, request: Request, key: str = Depends(require_key), repo: Repository = Depends(repository)
):
    idem = repo.key("idempotency", f"project:{key}")
    body_hash = hash_request(body.model_dump())
    for _ in range(8):
        async with repo.redis.pipeline() as pipe:
            try:
                await pipe.watch(idem)
                prior = await pipe.get(idem)
                if prior:
                    stored = json.loads(prior)
                    if stored["request_hash"] != body_hash:
                        raise Conflict("Idempotency-Key reused with another request")
                    return stored["project"]
                stamp = now()
                project = Project(
                    id=uid(), revision=0, created_at=stamp, updated_at=stamp, **body.model_dump()
                ).model_dump(mode="json")
                pipe.multi()
                pipe.set(repo.key("project", project["id"]), dumps(project))
                pipe.sadd("panellab:index:project", project["id"])
                pipe.set(idem, dumps({"request_hash": body_hash, "project": project}))
                await pipe.execute()
                await import_templates(repo, request.app.state.settings, project["id"])
                return project
            except WatchError:
                continue
    raise Conflict("concurrent project creation")


@app.get("/api/projects", response_model=ProjectPage)
async def list_projects(
    cursor: str | None = None,
    limit: int = Query(20, ge=1, le=100),
    archived: bool = Query(False, description="true lista sólo los proyectos archivados"),
    repo: Repository = Depends(repository),
):
    items = [item for item in await repo.list("project") if bool(item.get("archived", False)) == archived]
    return page(items, cursor, limit)


@app.get("/api/projects/{project_id}", response_model=Project)
async def get_project(project_id: str, repo: Repository = Depends(repository)):
    return await require_project(repo, project_id)


@app.patch("/api/projects/{project_id}", response_model=Project, responses=ERRORS)
async def patch_project(project_id: str, body: ProjectPatch, repo: Repository = Depends(repository)):
    await require_project(repo, project_id)

    def mutate(current):
        current.update(body.model_dump(exclude_none=True, exclude={"expected_revision"}))
        current["revision"] += 1
        current["updated_at"] = now()
        return current

    return await repo.cas("project", project_id, body.expected_revision, mutate)


def new_job(
    kind: str, project_id: str, command_id: str, session_id: str | None = None, document_id: str | None = None
) -> dict[str, Any]:
    stamp = now()
    return Job(
        id=uid(),
        command_id=command_id,
        kind=kind,
        project_id=project_id,
        session_id=session_id,
        document_id=document_id,
        status="QUEUED",
        attempt=0,
        created_at=stamp,
        updated_at=stamp,
    ).model_dump(mode="json")


def accepted(job: dict[str, Any]) -> dict[str, Any]:
    return JobAccepted(
        job_id=job["id"],
        session_id=job.get("session_id"),
        document_id=job.get("document_id"),
        status_url=f"/api/jobs/{job['id']}",
    ).model_dump()


@app.post("/api/projects/{project_id}/documents", response_model=JobAccepted, status_code=202, responses=ERRORS)
async def create_document(
    project_id: str, body: DocumentCreate, key: str = Depends(require_key), repo: Repository = Depends(repository)
):
    return await _create_document(project_id, body, key, repo, 0)


@app.post(
    "/api/projects/{project_id}/documents/extract",
    response_model=PdfExtraction,
    responses=ERRORS,
    openapi_extra={
        "requestBody": {
            "required": True,
            "content": {"application/pdf": {"schema": {"type": "string", "format": "binary"}}},
        }
    },
)
async def extract_document_pdf(
    project_id: str,
    request: Request,
    filename: str | None = Query(default=None, max_length=255),
    repo: Repository = Depends(repository),
):
    await require_project(repo, project_id)
    if request.headers.get("content-type", "").split(";", 1)[0].strip().lower() != "application/pdf":
        raise HTTPException(415, detail="Enviá el archivo con Content-Type: application/pdf.")
    try:
        declared_size = int(request.headers.get("content-length", "0"))
    except ValueError:
        declared_size = 0
    if declared_size > MAX_PDF_BYTES:
        raise HTTPException(413, detail="El PDF supera el límite de 10 MB.")
    chunks = []
    size = 0
    async for chunk in request.stream():
        size += len(chunk)
        if size > MAX_PDF_BYTES:
            raise HTTPException(413, detail="El PDF supera el límite de 10 MB.")
        chunks.append(chunk)
    try:
        return await extract_pdf_isolated(b"".join(chunks), filename)
    except PdfImportError as exc:
        raise HTTPException(exc.status_code, detail=str(exc)) from exc


async def _create_document(project_id: str, body: DocumentCreate, key: str, repo: Repository, attempt: int):
    await require_project(repo, project_id)
    if len(body.text.encode("utf-8")) > 200000:
        raise HTTPException(413, detail="document exceeds 200 KB")
    documents = await repo.list("document", project_id)
    doc_id = body.document_id or uid()
    own = [x for x in documents if x["document_id"] == doc_id]
    if body.document_id and not own:
        raise HTTPException(404, detail="document not found")
    if not own and len({x["document_id"] for x in documents}) >= 30:
        raise HTTPException(422, detail="document limit reached")
    latest = {
        x["document_id"]: max(y["version"] for y in documents if y["document_id"] == x["document_id"])
        for x in documents
    }
    current_bytes = sum(
        len(x["text"].encode("utf-8"))
        for x in documents
        if x["version"] == latest[x["document_id"]] and x["document_id"] != doc_id
    )
    if current_bytes + len(body.text.encode("utf-8")) > 1_000_000:
        raise HTTPException(413, detail="project source limit reached")
    content_hash = digest(body.text)
    same = next((x for x in own if x["content_hash"] == content_hash), None)
    if same:
        jobs = await repo.list("job", project_id)
        existing = next((j for j in jobs if j.get("document_id") == doc_id and j["kind"] == "INDEX_DOCUMENT"), None)
        if existing:
            return accepted(existing)
    version = max((x["version"] for x in own), default=0) + 1
    stamp = now()
    doc = DocumentVersion(
        **body.model_dump(exclude={"document_id"}),
        document_id=doc_id,
        project_id=project_id,
        version=version,
        content_hash=content_hash,
        index_status="QUEUED",
        created_at=stamp,
    ).model_dump(mode="json")
    command_id = uid()
    job = new_job("INDEX_DOCUMENT", project_id, command_id, document_id=doc_id)
    command = {
        "id": command_id,
        "kind": "INDEX_DOCUMENT",
        "project_id": project_id,
        "session_id": None,
        "job_id": job["id"],
        "payload": {"document_id": doc_id, "version": version},
    }
    try:
        return await repo.enqueue(
            scope=f"document:{project_id}",
            idempotency_key=key,
            request_hash=hash_request(body.model_dump()),
            command=command,
            job=job,
            accepted=accepted(job),
            precondition=lambda current: current is None,
            entity_kind="document",
            entity_id=f"{doc_id}:{version}",
            entity=doc,
        )
    except Conflict as exc:
        if body.document_id and str(exc) == "resource state changed" and attempt < 8:
            return await _create_document(project_id, body, key, repo, attempt + 1)
        raise


@app.post("/api/projects/{project_id}/demo", response_model=DemoJobs, status_code=202, responses=ERRORS)
async def seed_demo(
    project_id: str, request: Request, key: str = Depends(require_key), repo: Repository = Depends(repository)
):
    await require_project(repo, project_id)
    if request.app.state.settings.llm_mode != "demo":
        raise HTTPException(404, detail="demo seed is unavailable")
    folder = request.app.state.settings.demo_dir
    results = []
    for number in range(1, 5):
        matches = list(folder.glob(f"{number:02d}-*.md"))
        if len(matches) != 1:
            raise HTTPException(503, detail="demo fixtures are missing")
        file = matches[0]
        text = await asyncio.to_thread(file.read_text, encoding="utf-8")
        result = await create_document(
            project_id,
            DocumentCreate(title=file.stem.replace("-", " "), kind="progress" if number == 4 else "source", text=text),
            f"{key}:{number}",
            repo,
        )
        results.append(result)
    return DemoJobs(items=results)


@app.get("/api/projects/{project_id}/documents", response_model=DocumentPage)
async def list_documents(
    project_id: str,
    cursor: str | None = None,
    limit: int = Query(20, ge=1, le=100),
    repo: Repository = Depends(repository),
):
    await require_project(repo, project_id)
    return page(await repo.list("document", project_id), cursor, limit)


@app.get("/api/projects/{project_id}/documents/{document_id}/versions/{version}", response_model=DocumentVersion)
async def get_document(project_id: str, document_id: str, version: int, repo: Repository = Depends(repository)):
    doc = await repo.get("document", f"{document_id}:{version}")
    if not doc or doc["project_id"] != project_id:
        raise HTTPException(404, detail="document not found")
    return doc


async def create_markdown(kind: str, project_id: str, markdown: str, declared_id: str | None, repo: Repository):
    await require_project(repo, project_id)
    meta = parse_markdown(markdown, kind)
    item_id = declared_id or meta["id"]
    if kind == "profile" and retired_catalog_profile(item_id):
        raise ContentError("This legacy catalogue profile is retired; choose a new ID")
    if item_id != meta["id"]:
        raise ContentError(f"{kind}_id must match frontmatter id")
    counter_key = repo.key("version", f"{kind}:{project_id}:{item_id}")
    for _ in range(8):
        async with repo.redis.pipeline() as pipe:
            try:
                await pipe.watch(counter_key)
                prior = [x for x in await repo.list(kind, project_id) if x[f"{kind}_id"] == item_id]
                same = next((x for x in prior if x["content_hash"] == digest(markdown)), None)
                if same:
                    return same
                version = max((x["version"] for x in prior), default=0) + 1
                item = {
                    "project_id": project_id,
                    f"{kind}_id": item_id,
                    "version": version,
                    "name": meta["name"],
                    "markdown": markdown,
                    "content_hash": digest(markdown),
                    "created_at": now(),
                }
                if kind == "profile":
                    item.update(role=meta["role"], focus=meta["focus"], style=meta["style"])
                else:
                    item["criteria"] = meta["criteria"]
                entity_id = f"{project_id}:{item_id}:{version}"
                pipe.multi()
                pipe.set(counter_key, version)
                pipe.set(repo.key(kind, entity_id), dumps(item))
                pipe.sadd(f"panellab:index:{kind}", entity_id)
                await pipe.execute()
                return item
            except WatchError:
                continue
    raise Conflict("concurrent content update")


@app.get("/api/projects/{project_id}/profiles", response_model=ProfilePage)
async def list_profiles(
    project_id: str,
    request: Request,
    cursor: str | None = None,
    limit: int = Query(20, ge=1, le=100),
    repo: Repository = Depends(repository),
):
    await require_project(repo, project_id)
    await import_templates(repo, request.app.state.settings, project_id)
    visible = [
        item for item in await repo.list("profile", project_id) if not retired_catalog_profile(item["profile_id"])
    ]
    return page(visible, cursor, limit)


@app.post("/api/projects/{project_id}/profiles", response_model=ProfileVersion, status_code=201)
async def add_profile(project_id: str, body: MarkdownCreate, repo: Repository = Depends(repository)):
    return await create_markdown("profile", project_id, body.markdown, body.profile_id, repo)


@app.get("/api/projects/{project_id}/rubrics", response_model=RubricPage)
async def list_rubrics(
    project_id: str,
    cursor: str | None = None,
    limit: int = Query(20, ge=1, le=100),
    repo: Repository = Depends(repository),
):
    await require_project(repo, project_id)
    return page(await repo.list("rubric", project_id), cursor, limit)


@app.post("/api/projects/{project_id}/rubrics", response_model=RubricVersion, status_code=201)
async def add_rubric(project_id: str, body: MarkdownCreate, repo: Repository = Depends(repository)):
    return await create_markdown("rubric", project_id, body.markdown, body.rubric_id, repo)


@app.post("/api/projects/{project_id}/sessions", response_model=JobAccepted, status_code=202, responses=ERRORS)
async def create_session(
    project_id: str, body: SessionCreate, key: str = Depends(require_key), repo: Repository = Depends(repository)
):
    await require_project(repo, project_id)
    rubric = await repo.get("rubric", f"{project_id}:{body.rubric_version.id}:{body.rubric_version.version}")
    if not rubric:
        raise HTTPException(404, detail="rubric version not found")
    criterion_ids = {x["id"] for x in rubric["criteria"]}
    if len({x.id for x in body.profile_versions}) != len(body.profile_versions):
        raise HTTPException(422, detail="duplicate profile")
    for ref in body.profile_versions:
        if retired_catalog_profile(ref.id):
            raise Conflict("legacy catalogue profile cannot start a new session")
        profile = await repo.get("profile", f"{project_id}:{ref.id}:{ref.version}")
        if not profile:
            raise HTTPException(404, detail="profile version not found")
        if not set(profile["focus"]).intersection(criterion_ids):
            raise HTTPException(422, detail=f"profile {ref.id} has no focus in rubric")
    if len({(x.document_id, x.version) for x in body.document_versions}) != len(body.document_versions):
        raise HTTPException(422, detail="duplicate document version")
    for ref in body.document_versions:
        document = await repo.get("document", f"{ref.document_id}:{ref.version}")
        if not document or document["project_id"] != project_id:
            raise HTTPException(404, detail="document version not found")
        if document["index_status"] != "READY":
            raise Conflict("document version is not indexed")
    if body.previous_session_id:
        previous = await repo.get("session", body.previous_session_id)
        if not previous or previous["project_id"] != project_id or previous["status"] != "COMPLETED":
            raise Conflict("previous session must be completed in this project")
    session_id = uid()
    command_id = uid()
    job = new_job("START_SESSION", project_id, command_id, session_id=session_id)
    stamp = now()
    snapshot = SessionSnapshot(
        profile_versions=body.profile_versions,
        rubric_version=body.rubric_version,
        document_versions=body.document_versions,
        previous_session_id=body.previous_session_id,
    )
    presentation_turn = Turn(
        id=uid(), kind="presentation", author_id="user", text=body.presentation, created_at=datetime.now(UTC)
    )
    session = SessionView(
        id=session_id,
        project_id=project_id,
        objective=body.objective,
        status="QUEUED",
        revision=0,
        question_count=0,
        max_questions=body.max_questions,
        transcript=[presentation_turn],
        snapshot=snapshot,
        active_job_id=job["id"],
        created_at=stamp,
        updated_at=stamp,
    ).model_dump(mode="json")
    command = {
        "id": command_id,
        "kind": "START_SESSION",
        "project_id": project_id,
        "session_id": session_id,
        "job_id": job["id"],
        "payload": {},
    }
    return await repo.enqueue(
        scope=f"session:create:{project_id}",
        idempotency_key=key,
        request_hash=hash_request(body.model_dump()),
        command=command,
        job=job,
        accepted=accepted(job),
        precondition=lambda current: current is None,
        entity_kind="session",
        entity_id=session_id,
        entity=session,
    )


@app.get("/api/projects/{project_id}/sessions", response_model=SessionPage)
async def list_sessions(
    project_id: str,
    cursor: str | None = None,
    limit: int = Query(20, ge=1, le=100),
    repo: Repository = Depends(repository),
):
    await require_project(repo, project_id)
    return page(await repo.list("session", project_id), cursor, limit)


@app.get("/api/sessions/{session_id}", response_model=SessionView)
async def get_session(session_id: str, repo: Repository = Depends(repository)):
    return await require_session(repo, session_id)


async def enqueue_turn(session_id: str, kind: str, payload: dict[str, Any], key: str, repo: Repository):
    idem = await repo.get("idempotency", f"session:{session_id}:{key}")
    request_hash = hash_request({"kind": kind, "payload": payload})
    if idem:
        if idem["request_hash"] != request_hash:
            raise Conflict("Idempotency-Key reused with another request")
        return idem["accepted"]
    session = await require_session(repo, session_id)
    expected = payload["expected_revision"]
    if (
        session["status"] != "WAITING_RESPONSE"
        or session["revision"] != expected
        or not session["pending_question"]
        or session["pending_question"]["id"] != payload["question_id"]
    ):
        raise Conflict("session state or question changed")
    command_id = uid()
    job = new_job(kind, session["project_id"], command_id, session_id=session_id)
    command = {
        "id": command_id,
        "kind": kind,
        "project_id": session["project_id"],
        "session_id": session_id,
        "job_id": job["id"],
        "payload": payload,
    }
    changed = {
        **session,
        "status": "QUEUED",
        "active_job_id": job["id"],
        "revision": session["revision"] + 1,
        "updated_at": now(),
    }

    def check(current):
        return bool(
            current
            and current["status"] == "WAITING_RESPONSE"
            and current["revision"] == expected
            and current["pending_question"]
            and current["pending_question"]["id"] == payload["question_id"]
        )

    return await repo.enqueue(
        scope=f"session:{session_id}",
        idempotency_key=key,
        request_hash=request_hash,
        command=command,
        job=job,
        accepted=accepted(job),
        precondition=check,
        entity_kind="session",
        entity_id=session_id,
        entity=changed,
    )


@app.post("/api/sessions/{session_id}/responses", response_model=JobAccepted, status_code=202, responses=ERRORS)
async def answer(
    session_id: str, body: AnswerRequest, key: str = Depends(require_key), repo: Repository = Depends(repository)
):
    return await enqueue_turn(session_id, "ANSWER", body.model_dump(), key, repo)


@app.post("/api/sessions/{session_id}/finish", response_model=JobAccepted, status_code=202, responses=ERRORS)
async def finish(
    session_id: str, body: FinishRequest, key: str = Depends(require_key), repo: Repository = Depends(repository)
):
    return await enqueue_turn(session_id, "FINISH", body.model_dump(), key, repo)


@app.get("/api/sessions/{session_id}/report", response_model=Report)
async def get_report(session_id: str, repo: Repository = Depends(repository)):
    session = await require_session(repo, session_id)
    report = await repo.get("report", session_id)
    if not report:
        raise Conflict("report is not ready")
    previous_id = session.get("snapshot", {}).get("previous_session_id")
    if previous_id and not report.get("comparison_items"):
        # Informes generados antes de guardar la comparación estructurada: se calcula al leer.
        previous = await repo.get("report", previous_id)
        ref = session["snapshot"]["rubric_version"]
        rubric = await repo.get("rubric", f"{session['project_id']}:{ref['id']}:{ref['version']}")
        if previous and rubric:
            titles = {item["id"]: item["title"] for item in rubric["criteria"]}
            changes = compare_feedback(previous, report["criterion_feedback"], titles)
            report = {**report, "comparison_items": changes, "comparison": comparison_text(changes)}
    return report


@app.get("/api/jobs/{job_id}", response_model=Job)
async def get_job(job_id: str, repo: Repository = Depends(repository)):
    job = await repo.get("job", job_id)
    if not job:
        raise HTTPException(404, detail="job not found")
    return job


@app.post("/api/jobs/{job_id}/retry", response_model=JobAccepted, status_code=202, responses=ERRORS)
async def retry_job(
    job_id: str, body: RetryRequest, key: str = Depends(require_key), repo: Repository = Depends(repository)
):
    idem = await repo.get("idempotency", f"retry:{job_id}:{key}")
    request_hash = hash_request(body.model_dump())
    if idem:
        if idem["request_hash"] != request_hash:
            raise Conflict("Idempotency-Key reused with another request")
        return idem["accepted"]
    old = await repo.get("job", job_id)
    if not old:
        raise HTTPException(404, detail="job not found")
    if (
        old["status"] != "FAILED"
        or not (old.get("error") or {}).get("retryable")
        or old["attempt"] != body.expected_attempt
        or old.get("retry_job_id")
    ):
        raise Conflict("job cannot be retried")
    original = await repo.get("command", old["command_id"])
    if not original:
        raise HTTPException(404, detail="command not found")
    command_id = uid()
    job = new_job(old["kind"], old["project_id"], command_id, old.get("session_id"), old.get("document_id"))
    command = {
        **original,
        "id": command_id,
        "job_id": job["id"],
        "logical_id": original.get("logical_id", old["command_id"]),
        "retry_of": old["command_id"],
    }
    changed = {**old, "retry_job_id": job["id"], "updated_at": now()}
    return await repo.enqueue(
        scope=f"retry:{job_id}",
        idempotency_key=key,
        request_hash=request_hash,
        command=command,
        job=job,
        accepted=accepted(job),
        precondition=lambda current: bool(
            current
            and current["status"] == "FAILED"
            and current["attempt"] == body.expected_attempt
            and not current.get("retry_job_id")
        ),
        entity_kind="job",
        entity_id=job_id,
        entity=changed,
    )
