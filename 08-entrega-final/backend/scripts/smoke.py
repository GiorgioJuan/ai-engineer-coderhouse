"""Exercise the real HTTP API and worker in explicit, zero-provider-cost demo mode."""

from __future__ import annotations

import argparse
import asyncio
import json
import time
import uuid
from pathlib import Path

import httpx


async def run(url: str, output: Path | None = None) -> dict:
    checks: list[str] = []
    async with httpx.AsyncClient(base_url=url.rstrip("/"), timeout=20) as client:

        async def get(path: str):
            response = await client.get(path)
            response.raise_for_status()
            return response.json()

        async def post(path: str, data: dict, key: str | None = None, expected: int = 202):
            response = await client.post(path, json=data, headers={"Idempotency-Key": key or uuid.uuid4().hex})
            assert response.status_code == expected, f"{path}: {response.status_code} {response.text}"
            return response.json()

        async def wait_job(job_id: str):
            deadline = time.monotonic() + 60
            while time.monotonic() < deadline:
                job = await get(f"/api/jobs/{job_id}")
                if job["status"] == "SUCCEEDED":
                    return job
                if job["status"] == "FAILED":
                    raise AssertionError(f"Worker failed: {job['error']}")
                await asyncio.sleep(0.15)
            raise AssertionError(f"Job did not finish: {job_id}")

        health = await get("/api/health/ready")
        assert health.get("llm_mode") == "demo", "Smoke refuses to run against live mode"
        checks.append("demo_mode_no_provider_calls")
        project_key = uuid.uuid4().hex
        project_data = {
            "title": f"Verificación PanelLab {project_key[:6]}",
            "context": "Caso ficticio de Laboratorio 3.",
            "objective": "Defender decisiones y reconocer evidencia faltante.",
        }
        project = await post("/api/projects", project_data, project_key, 201)
        replay = await post("/api/projects", project_data, project_key, 201)
        assert replay["id"] == project["id"]
        checks.append("project_idempotency")
        project_id = project["id"]
        profiles = (await get(f"/api/projects/{project_id}/profiles"))["items"]
        rubrics = (await get(f"/api/projects/{project_id}/rubrics"))["items"]
        assert len(profiles) >= 3 and rubrics
        source = (
            "# Entrevistas\n\nSe entrevistó a 5 personas. El prototipo aún no fue validado.\n\n"
            "## Alcance\nLa primera entrega no incluye pagos."
        )
        doc = await post(
            f"/api/projects/{project_id}/documents", {"title": "Brief verificado", "kind": "source", "text": source}
        )
        await wait_job(doc["job_id"])
        docs = (await get(f"/api/projects/{project_id}/documents"))["items"]
        assert docs[0]["index_status"] == "READY"
        checks.append("real_redis_document_index")
        session_data = {
            "objective": "Revisar evidencia y alcance",
            "presentation": "Entrevistamos a cinco personas y todavía no validamos el prototipo.",
            "profile_versions": [{"id": x["profile_id"], "version": x["version"]} for x in profiles[:3]],
            "rubric_version": {"id": rubrics[0]["rubric_id"], "version": rubrics[0]["version"]},
            "document_versions": [{"document_id": docs[0]["document_id"], "version": docs[0]["version"]}],
            "max_questions": 3,
        }
        accepted = await post(f"/api/projects/{project_id}/sessions", session_data)
        await wait_job(accepted["job_id"])
        session_id = accepted["session_id"]
        session = await get(f"/api/sessions/{session_id}")
        assert session["status"] == "WAITING_RESPONSE" and session["pending_question"]
        checks.append("langgraph_interrupt_persisted")
        citation_count = 0
        for _ in range(3):
            question = session["pending_question"]
            for citation in question["citations"]:
                original = await get(
                    f"/api/projects/{project_id}/documents/{citation['document_id']}/versions/{citation['version']}"
                )
                assert citation["excerpt"] in original["text"], "Citation is not an exact source excerpt"
                citation_count += 1
            key = uuid.uuid4().hex
            data = {
                "question_id": question["id"],
                "expected_revision": session["revision"],
                "text": (
                    "El documento registra cinco entrevistas. La prueba del prototipo sigue pendiente; "
                    "no afirmamos haberla realizado."
                ),
            }
            answered = await post(f"/api/sessions/{session_id}/responses", data, key)
            replay_answer = await post(f"/api/sessions/{session_id}/responses", data, key)
            assert replay_answer["job_id"] == answered["job_id"]
            await wait_job(answered["job_id"])
            session = await get(f"/api/sessions/{session_id}")
        assert session["status"] == "COMPLETED"
        assert len([x for x in session["transcript"] if x["kind"] == "answer"]) == 3
        assert citation_count > 0
        report = await get(f"/api/sessions/{session_id}/report")
        assert report["criterion_feedback"]
        checks.extend(
            ["source_citations_verified", "answer_idempotency", "three_rounds_completed", "structured_report"]
        )
        second = await post(f"/api/projects/{project_id}/sessions", {**session_data, "previous_session_id": session_id})
        await wait_job(second["job_id"])
        second_view = await get(f"/api/sessions/{second['session_id']}")
        assert second_view["snapshot"]["previous_session_id"] == session_id
        early = await post(
            f"/api/sessions/{second['session_id']}/finish",
            {"question_id": second_view["pending_question"]["id"], "expected_revision": second_view["revision"]},
        )
        await wait_job(early["job_id"])
        second_report = await get(f"/api/sessions/{second['session_id']}/report")
        assert second_report["comparison"]
        checks.append("weekly_context_and_early_finish")
        invalid = await client.post("/api/projects", json={"title": ""}, headers={"Idempotency-Key": uuid.uuid4().hex})
        assert invalid.status_code == 422
        checks.append("invalid_input_rejected")
        result = {
            "mode": "demo",
            "provider_calls": 0,
            "project_id": project_id,
            "session_ids": [session_id, second["session_id"]],
            "checks": checks,
            "citations_checked": citation_count,
        }
        if output:
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://localhost:8080")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    print(json.dumps(asyncio.run(run(args.url, args.output)), ensure_ascii=False, indent=2))
