"""Prepare a paused session, then verify it after an external process restart."""

from __future__ import annotations

import argparse
import asyncio
import json
import time
import uuid
from pathlib import Path

import httpx


async def probe(url: str, state_file: Path, prepare: bool):
    async with httpx.AsyncClient(base_url=url.rstrip("/"), timeout=20) as client:

        async def get(path):
            response = await client.get(path)
            response.raise_for_status()
            return response.json()

        async def post(path, body):
            response = await client.post(path, json=body, headers={"Idempotency-Key": uuid.uuid4().hex})
            response.raise_for_status()
            return response.json()

        async def wait(job_id):
            deadline = time.monotonic() + 60
            while time.monotonic() < deadline:
                job = await get(f"/api/jobs/{job_id}")
                if job["status"] == "SUCCEEDED":
                    return
                if job["status"] == "FAILED":
                    raise AssertionError(job["error"])
                await asyncio.sleep(0.2)
            raise AssertionError("Worker deadline exceeded")

        assert (await get("/api/health/ready"))["llm_mode"] == "demo"
        if prepare:
            projects = (await get("/api/projects?limit=100"))["items"]
            previous = None
            for project in projects:
                sessions = (await get(f"/api/projects/{project['id']}/sessions?limit=100"))["items"]
                previous = next((item for item in sessions if item["status"] == "COMPLETED"), None)
                if previous:
                    break
            assert previous, "Run scripts.smoke before preparing the restart probe"
            snapshot = previous["snapshot"]
            body = {
                "objective": "Continuar después de reiniciar el servidor",
                "presentation": "Retomamos nuestro avance y queremos defender qué evidencia falta.",
                "profile_versions": snapshot["profile_versions"],
                "rubric_version": snapshot["rubric_version"],
                "document_versions": snapshot["document_versions"],
                "previous_session_id": previous["id"],
                "max_questions": 3,
            }
            accepted = await post(f"/api/projects/{previous['project_id']}/sessions", body)
            await wait(accepted["job_id"])
            session = await get(f"/api/sessions/{accepted['session_id']}")
            assert session["status"] == "WAITING_RESPONSE"
            state_file.parent.mkdir(parents=True, exist_ok=True)
            state_file.write_text(
                json.dumps({"mode": "demo", "before": session}, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            return {"prepared_session": session["id"], "question_id": session["pending_question"]["id"]}
        record = json.loads(state_file.read_text(encoding="utf-8"))
        before = record["before"]
        after = await get(f"/api/sessions/{before['id']}")
        assert after["pending_question"] == before["pending_question"]
        assert after["transcript"] == before["transcript"]
        assert after["snapshot"] == before["snapshot"]
        accepted = await post(
            f"/api/sessions/{after['id']}/responses",
            {
                "question_id": after["pending_question"]["id"],
                "expected_revision": after["revision"],
                "text": (
                    "La evidencia del documento sigue siendo cinco entrevistas. "
                    "La prueba de usabilidad es el próximo paso."
                ),
            },
        )
        await wait(accepted["job_id"])
        resumed = await get(f"/api/sessions/{after['id']}")
        assert resumed["question_count"] == before["question_count"] + 1
        assert len([turn for turn in resumed["transcript"] if turn["kind"] == "answer"]) == 1
        record.update(
            after=resumed,
            result="PASS",
            checks=["same_question", "same_sources", "same_transcript", "answer_resumed_once"],
        )
        state_file.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
        return {"result": "PASS", "session_id": resumed["id"], "checks": record["checks"]}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://localhost:8080")
    parser.add_argument("--state", type=Path, default=Path("../evidence/restart-demo.json"))
    parser.add_argument("--prepare", action="store_true")
    args = parser.parse_args()
    print(json.dumps(asyncio.run(probe(args.url, args.state, args.prepare)), indent=2, ensure_ascii=False))
