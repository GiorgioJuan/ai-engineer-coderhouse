from __future__ import annotations

import asyncio
import hashlib
from contextlib import contextmanager

import pytest
from fakeredis.aioredis import FakeRedis
from httpx import ASGITransport, AsyncClient

import app.content as content_module
import app.main as main_module
from app.config import Settings
from app.content import ContentError, parse_markdown
from app.main import app
from app.storage import Repository


@pytest.fixture
def repo():
    return Repository(FakeRedis(decode_responses=False))


@pytest.fixture
def client(repo, tmp_path):
    app.state.repo = repo
    app.state.settings = Settings(config_dir=tmp_path, demo_dir=tmp_path)
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


@pytest.mark.asyncio
async def test_create_project_idempotency_and_conflict(client):
    body = {"title": "Demo", "context": "Context", "objective": "Review"}
    headers = {"Idempotency-Key": "same-key"}
    first = await client.post("/api/projects", json=body, headers=headers)
    again = await client.post("/api/projects", json=body, headers=headers)
    changed = await client.post("/api/projects", json={**body, "title": "Other"}, headers=headers)
    assert first.status_code == 201
    assert again.json()["id"] == first.json()["id"]
    assert changed.status_code == 409


@pytest.mark.asyncio
async def test_answer_replay_after_session_state_advanced(client, repo):
    await repo.put(
        "session",
        "s",
        {
            "id": "s",
            "project_id": "p",
            "status": "WAITING_RESPONSE",
            "revision": 3,
            "pending_question": {"id": "q"},
            "active_job_id": None,
        },
    )
    body = {"question_id": "q", "expected_revision": 3, "text": "An answer"}
    headers = {"Idempotency-Key": "answer-1"}
    first = await client.post("/api/sessions/s/responses", json=body, headers=headers)
    assert first.status_code == 202, first.text
    session = await repo.get("session", "s")
    assert session["status"] == "QUEUED"
    second = await client.post("/api/sessions/s/responses", json=body, headers=headers)
    assert second.status_code == 202
    assert second.json() == first.json()
    stale = await client.post("/api/sessions/s/responses", json=body, headers={"Idempotency-Key": "other"})
    assert stale.status_code == 409


@pytest.mark.asyncio
async def test_competing_answers_accept_only_one(client, repo):
    await repo.put(
        "session",
        "compete",
        {
            "id": "compete",
            "project_id": "p",
            "status": "WAITING_RESPONSE",
            "revision": 2,
            "pending_question": {"id": "q"},
            "active_job_id": None,
        },
    )
    body = {"question_id": "q", "expected_revision": 2, "text": "An answer"}
    responses = await asyncio.gather(
        *[
            client.post("/api/sessions/compete/responses", json=body, headers={"Idempotency-Key": key})
            for key in ("first", "second")
        ]
    )
    assert sorted(x.status_code for x in responses) == [202, 409]
    assert len(await repo.list("job", "p")) == 1


@pytest.mark.asyncio
async def test_retry_is_single_and_reuses_logical_command(client, repo):
    await repo.put(
        "command",
        "cmd",
        {
            "id": "cmd",
            "kind": "INDEX_DOCUMENT",
            "project_id": "p",
            "session_id": None,
            "job_id": "failed",
            "payload": {"document_id": "d", "version": 1},
        },
    )
    await repo.put(
        "job",
        "failed",
        {
            "id": "failed",
            "command_id": "cmd",
            "kind": "INDEX_DOCUMENT",
            "project_id": "p",
            "document_id": "d",
            "status": "FAILED",
            "attempt": 1,
            "error": {"code": "temporary", "message": "temporary", "retryable": True},
        },
    )
    body = {"expected_attempt": 1}
    first = await client.post("/api/jobs/failed/retry", json=body, headers={"Idempotency-Key": "retry-1"})
    replay = await client.post("/api/jobs/failed/retry", json=body, headers={"Idempotency-Key": "retry-1"})
    competing = await client.post("/api/jobs/failed/retry", json=body, headers={"Idempotency-Key": "retry-2"})
    assert first.status_code == replay.status_code == 202
    assert first.json() == replay.json()
    assert competing.status_code == 409
    job = await repo.get("job", first.json()["job_id"])
    command = await repo.get("command", job["command_id"])
    assert command["logical_id"] == "cmd"


def test_markdown_rejects_unknown_keys_and_duplicate_criteria():
    with pytest.raises(ContentError, match="frontmatter keys"):
        parse_markdown(
            "---\nid: reviewer\nname: Reviewer\nrole: Role\nfocus: [evidence]\nstyle: direct\n"
            "api_key: secret\n---\nBody",
            "profile",
        )
    with pytest.raises(ContentError, match="duplicate criterion"):
        parse_markdown(
            "---\nid: rubric\nname: Rubric\ncriteria:\n"
            "  - id: evidence\n    title: Evidence\n    description: A\n"
            "  - id: evidence\n    title: Evidence 2\n    description: B\n---\nBody",
            "rubric",
        )


@pytest.mark.asyncio
async def test_concurrent_profile_edits_preserve_both_versions(client, repo):
    await repo.put("project", "p", {"id": "p", "title": "P", "context": "C", "objective": "O"})

    def markdown(name):
        return f"---\nid: custom-reviewer\nname: {name}\nrole: Reviewer\nfocus: [evidence]\nstyle: direct\n---\nBody"

    responses = await asyncio.gather(
        *[client.post("/api/projects/p/profiles", json={"markdown": markdown(name)}) for name in ("First", "Second")]
    )
    assert [x.status_code for x in responses] == [201, 201]
    profiles = await repo.list("profile", "p")
    assert {x["version"] for x in profiles} == {1, 2}
    assert {x["name"] for x in profiles} == {"First", "Second"}


@pytest.mark.asyncio
async def test_concurrent_document_edits_preserve_both_versions(client, repo):
    await repo.put("project", "p", {"id": "p", "title": "P", "context": "C", "objective": "O"})
    await repo.put(
        "document",
        "d:1",
        {
            "document_id": "d",
            "project_id": "p",
            "version": 1,
            "title": "D",
            "kind": "source",
            "text": "one",
            "content_hash": "h1",
            "index_status": "READY",
        },
    )
    responses = await asyncio.gather(
        *[
            client.post(
                "/api/projects/p/documents",
                json={"title": "D", "kind": "source", "text": text, "document_id": "d"},
                headers={"Idempotency-Key": key},
            )
            for key, text in (("v2", "two"), ("v3", "three"))
        ]
    )
    assert [x.status_code for x in responses] == [202, 202]
    documents = [x for x in await repo.list("document", "p") if x["document_id"] == "d"]
    assert {x["version"] for x in documents} == {1, 2, 3}
    assert {x["text"] for x in documents} == {"one", "two", "three"}


@pytest.mark.asyncio
async def test_http_span_records_route_method_and_status_without_payload(client, monkeypatch):
    captured = []

    class FakeSpan:
        def __init__(self, attributes):
            self.attributes = attributes

        def set_attribute(self, key, value):
            self.attributes[key] = value

        def update_name(self, name):
            self.attributes["name"] = name

    @contextmanager
    def fake_span(name, **attributes):
        record = {"name": name, **attributes}
        captured.append(record)
        yield FakeSpan(record)

    monkeypatch.setattr(main_module, "span", fake_span)
    created = await client.post(
        "/api/projects", json={"title": "P", "context": "C", "objective": "O"}, headers={"Idempotency-Key": "span-test"}
    )
    missing = await client.post("/api/not-found", json={}, headers={"Idempotency-Key": "x"})
    polled = await client.get(f"/api/projects/{created.json()['id']}")
    health = await client.get("/api/health/live")
    assert [created.status_code, missing.status_code, polled.status_code, health.status_code] == [201, 404, 200, 200]
    # Las lecturas (polling) no generan spans; los comandos sí, nombrados por plantilla de ruta.
    assert captured == [
        {
            "name": "POST /api/projects",
            "openinference.span.kind": "CHAIN",
            "http.request.method": "POST",
            "http.route": "/api/projects",
            "http.response.status_code": 201,
        },
        {
            "name": "POST unmatched",
            "openinference.span.kind": "CHAIN",
            "http.request.method": "POST",
            "http.route": "unmatched",
            "http.response.status_code": 404,
        },
    ]


@pytest.mark.asyncio
async def test_catalog_refresh_hides_retired_but_keeps_history_and_custom(client, repo, tmp_path, monkeypatch):
    monkeypatch.setattr(content_module, "RETIRED_CATALOG_HASHES", frozenset({hashlib.sha256(b"legacy").hexdigest()}))
    (tmp_path / "profiles").mkdir()
    (tmp_path / "profiles" / "active.md").write_text(
        "---\nid: active\nname: New reviewer\nrole: Evidence\nfocus: [evidence]\nstyle: direct\n---\nBody",
        encoding="utf-8",
    )
    await repo.put("project", "p", {"id": "p", "title": "P", "context": "C", "objective": "O"})
    for profile_id in ("legacy", "custom"):
        await repo.put(
            "profile",
            f"p:{profile_id}:1",
            {
                "project_id": "p",
                "profile_id": profile_id,
                "version": 1,
                "name": profile_id,
                "role": "Role",
                "focus": ["evidence"],
                "style": "direct",
                "markdown": "Body",
                "content_hash": profile_id,
                "created_at": "2026-01-01T00:00:00Z",
            },
        )
    listed = await client.get("/api/projects/p/profiles")
    assert listed.status_code == 200
    assert {item["profile_id"] for item in listed.json()["items"]} == {"active", "custom"}
    assert await repo.get("profile", "p:legacy:1") is not None
    rejected = await client.post(
        "/api/projects/p/profiles",
        json={"markdown": "---\nid: legacy\nname: Old\nrole: Role\nfocus: [evidence]\nstyle: direct\n---\nBody"},
    )
    assert rejected.status_code == 422


@pytest.mark.asyncio
async def test_archiving_hides_a_project_reversibly_without_losing_it(client):
    created = (
        await client.post(
            "/api/projects",
            json={"title": "Prueba", "context": "Contexto", "objective": "Objetivo"},
            headers={"Idempotency-Key": "archive-me"},
        )
    ).json()
    assert created["archived"] is False
    archived = await client.patch(f"/api/projects/{created['id']}", json={"expected_revision": 0, "archived": True})
    assert archived.status_code == 200 and archived.json()["archived"] is True
    active = (await client.get("/api/projects")).json()["items"]
    hidden = (await client.get("/api/projects?archived=true")).json()["items"]
    assert created["id"] not in {item["id"] for item in active}
    assert [item["id"] for item in hidden] == [created["id"]]
    # Sigue accesible por su URL y se puede restaurar.
    assert (await client.get(f"/api/projects/{created['id']}")).status_code == 200
    restored = await client.patch(f"/api/projects/{created['id']}", json={"expected_revision": 1, "archived": False})
    assert restored.json()["archived"] is False
    assert created["id"] in {item["id"] for item in (await client.get("/api/projects")).json()["items"]}
