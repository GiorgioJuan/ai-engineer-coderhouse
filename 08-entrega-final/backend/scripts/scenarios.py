"""Batería de cinco escenarios end-to-end contra la API real (demo o live).

Cada escenario es una sesión completa; en Phoenix aparecen agrupadas por ``session.id``.
Se corre desde el host, en la carpeta ``08-entrega-final`` con el stack levantado:

    python backend/scripts/scenarios.py --output evidence/scenarios.json

En live, exportar ``COMPOSE_FILE`` con ambos archivos (el escenario 4 reinicia servicios) y
pasar ``--redis-service redis-live`` para registrar el presupuesto.

1. revision_fundamentada   Material completo: las preguntas citan fragmentos verificables.
2. evidencia_insuficiente  Sólo un plan: el informe no puede dar por probado lo no ejecutado.
3. seguimiento_semanal     Nueva versión de avance + referencia al informe anterior.
4. reinicio_con_pausa      La pregunta pendiente sobrevive a reiniciar API y worker.
5. validacion_y_cierre     Pydantic rechaza entradas inválidas; cierre anticipado del usuario.

Las respuestas las redacta este script sobre el caso ficticio de ``demo/laboratorio3``.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import subprocess
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

ROOT = Path(__file__).resolve().parents[2]
DEMO = ROOT / "demo" / "laboratorio3"
JOB_TIMEOUT = 300  # segundos: en live cada turno implica varias llamadas al modelo


class Api:
    def __init__(self, client: httpx.AsyncClient):
        self.client = client

    async def get(self, path: str) -> Any:
        response = await self.client.get(path)
        response.raise_for_status()
        return response.json()

    async def post(self, path: str, body: dict[str, Any], *, key: str | None = None, expected: int = 202) -> Any:
        response = await self.client.post(path, json=body, headers={"Idempotency-Key": key or uuid.uuid4().hex})
        assert response.status_code == expected, f"{path}: {response.status_code} {response.text[:300]}"
        return response.json()

    async def raw_post(self, path: str, body: dict[str, Any]) -> httpx.Response:
        return await self.client.post(path, json=body, headers={"Idempotency-Key": uuid.uuid4().hex})

    async def wait(self, job_id: str) -> dict[str, Any]:
        deadline = time.monotonic() + JOB_TIMEOUT
        while time.monotonic() < deadline:
            job = await self.get(f"/api/jobs/{job_id}")
            if job["status"] == "SUCCEEDED":
                return job
            if job["status"] == "FAILED":
                raise AssertionError(f"job {job_id} falló: {job['error']}")
            await asyncio.sleep(0.5)
        raise AssertionError(f"job {job_id} no terminó en {JOB_TIMEOUT} s")


async def new_project(api: Api, title: str, docs: list[tuple[str, str, str]]) -> dict[str, Any]:
    project = await api.post(
        "/api/projects",
        {
            "title": title,
            "context": "Caso ficticio Turno Claro (Laboratorio 3): reservas de salas para un centro barrial.",
            "objective": "Defender alcance, decisiones técnicas y evidencia del avance.",
        },
        expected=201,
    )
    for doc_title, kind, filename in docs:
        accepted = await api.post(
            f"/api/projects/{project['id']}/documents",
            {"title": doc_title, "kind": kind, "text": (DEMO / filename).read_text(encoding="utf-8")},
        )
        await api.wait(accepted["job_id"])
    return project


async def catalog(api: Api, project_id: str) -> tuple[list[dict], dict, list[dict]]:
    profiles = (await api.get(f"/api/projects/{project_id}/profiles?limit=100"))["items"]
    rubric = (await api.get(f"/api/projects/{project_id}/rubrics?limit=100"))["items"][0]
    documents = (await api.get(f"/api/projects/{project_id}/documents?limit=100"))["items"]
    return profiles, rubric, [d for d in documents if d["index_status"] == "READY"]


def session_body(
    profiles: list[dict],
    rubric: dict,
    documents: list[dict],
    *,
    objective: str,
    presentation: str,
    max_questions: int,
    previous: str | None = None,
) -> dict[str, Any]:
    body = {
        "objective": objective,
        "presentation": presentation,
        "profile_versions": [{"id": p["profile_id"], "version": p["version"]} for p in profiles],
        "rubric_version": {"id": rubric["rubric_id"], "version": rubric["version"]},
        "document_versions": [{"document_id": d["document_id"], "version": d["version"]} for d in documents],
        "max_questions": max_questions,
    }
    if previous:
        body["previous_session_id"] = previous
    return body


async def verify_citations(api: Api, project_id: str, question: dict[str, Any]) -> int:
    for citation in question["citations"]:
        original = await api.get(
            f"/api/projects/{project_id}/documents/{citation['document_id']}/versions/{citation['version']}"
        )
        assert " ".join(citation["excerpt"].split()) in " ".join(original["text"].split()), "cita no textual"
    return len(question["citations"])


async def answer_all(api: Api, project_id: str, session_id: str, answers: list[str]) -> tuple[dict, list[dict]]:
    session = await api.get(f"/api/sessions/{session_id}")
    asked: list[dict[str, Any]] = []
    turn = 0
    while session["status"] == "WAITING_RESPONSE":
        question = session["pending_question"]
        verified = await verify_citations(api, project_id, question)
        asked.append(
            {
                "reviewer_id": question["reviewer_id"],
                "criterion_id": question["criterion_id"],
                "basis": question["basis"],
                "citations_verified": verified,
                "text": question["text"],
            }
        )
        accepted = await api.post(
            f"/api/sessions/{session_id}/responses",
            {
                "question_id": question["id"],
                "expected_revision": session["revision"],
                "text": answers[turn % len(answers)],
            },
        )
        await api.wait(accepted["job_id"])
        session = await api.get(f"/api/sessions/{session_id}")
        turn += 1
    return session, asked


async def report_summary(api: Api, session_id: str) -> dict[str, Any]:
    report = await api.get(f"/api/sessions/{session_id}/report")
    return {
        "criteria": {item["criterion_id"]: item["status"] for item in report["criterion_feedback"]},
        "next_steps": len(report["next_steps"]),
        "comparison": report.get("comparison"),
    }


GROUNDED_ANSWERS = [
    "El brief documenta el problema: la coordinadora copia solicitudes a una planilla y hubo dobles reservas. "
    "Las cinco entrevistas confirman ese dolor.",
    "Elegimos una aplicación web porque centraliza disponibilidad y la demo debe correr localmente. "
    "La validación de reservas simultáneas va del lado del servidor; todavía no está implementada.",
    "Lo hecho: cinco entrevistas y un prototipo navegable. Lo pendiente: la prueba con la coordinadora "
    "y el control de concurrencia. No afirmamos haberlos completado.",
]
UNVERIFIED_ANSWERS = [
    "Ya probamos todo con muchos usuarios y funcionó perfecto, aunque no lo documentamos.",
    "La concurrencia está resuelta, confiá en nosotros; el código lo tenemos en otra computadora.",
    "El alcance lo vamos a definir más adelante según lo que pida el cliente.",
]
FOLLOW_UP_ANSWERS = [
    "Esta semana la coordinadora probó cuatro tareas: completó tres sin ayuda y necesitó asistencia en "
    "solicitudes pendientes. Cambiamos el estado visual y el texto del botón.",
    "Definimos una restricción de exclusión por sala e intervalo en la base y una respuesta de conflicto "
    "en la API. La implementación sigue pendiente.",
    "Pendiente: repetir la tarea con el prototipo corregido y probar dos solicitudes simultáneas contra la API.",
]


async def scenario_grounded(api: Api, state: dict[str, Any]) -> dict[str, Any]:
    project = await new_project(
        api,
        "Escenario 1 · Revisión fundamentada",
        [
            ("Brief del cliente", "source", "01-brief.md"),
            ("Entrevistas", "source", "02-entrevistas.md"),
            ("Arquitectura", "source", "03-arquitectura.md"),
            ("Avance semana 1", "progress", "04-semana-1.md"),
        ],
    )
    profiles, rubric, documents = await catalog(api, project["id"])
    chosen = [p for p in profiles if p["profile_id"] in {"estrategia", "arquitectura", "experimentacion"}]
    accepted = await api.post(
        f"/api/projects/{project['id']}/sessions",
        session_body(
            chosen,
            rubric,
            documents,
            objective="Defender el alcance y la evidencia de la semana 1",
            presentation=(DEMO / "presentacion.txt").read_text(encoding="utf-8"),
            max_questions=3,
        ),
    )
    await api.wait(accepted["job_id"])
    session, asked = await answer_all(api, project["id"], accepted["session_id"], GROUNDED_ANSWERS)
    assert session["status"] == "COMPLETED"
    assert any(q["citations_verified"] for q in asked), "ninguna pregunta citó una fuente"
    assert len({q["reviewer_id"] for q in asked}) == 3, "no intervinieron los tres evaluadores"
    state.update(project=project, session_id=accepted["session_id"], profiles=chosen, rubric=rubric)
    return {
        "project_id": project["id"],
        "session_id": accepted["session_id"],
        "questions": asked,
        "report": await report_summary(api, accepted["session_id"]),
    }


async def scenario_insufficient(api: Api, state: dict[str, Any]) -> dict[str, Any]:
    project = await new_project(
        api, "Escenario 2 · Evidencia insuficiente", [("Avance semana 1", "progress", "04-semana-1.md")]
    )
    profiles, rubric, documents = await catalog(api, project["id"])
    chosen = [p for p in profiles if p["profile_id"] in {"experimentacion", "entrega", "arquitectura"}]
    accepted = await api.post(
        f"/api/projects/{project['id']}/sessions",
        session_body(
            chosen,
            rubric,
            documents,
            objective="Mostrar que el prototipo está validado",
            presentation="Validamos el prototipo con usuarios y resolvimos la concurrencia.",
            max_questions=3,
        ),
    )
    await api.wait(accepted["job_id"])
    session, asked = await answer_all(api, project["id"], accepted["session_id"], UNVERIFIED_ANSWERS)
    assert session["status"] == "COMPLETED"
    report = await report_summary(api, accepted["session_id"])
    # Afirmaciones sin respaldo documental no pueden quedar como evidencia sustentada.
    assert report["criteria"].get("evidencia") != "supported", report
    return {"project_id": project["id"], "session_id": accepted["session_id"], "questions": asked, "report": report}


async def scenario_follow_up(api: Api, state: dict[str, Any]) -> dict[str, Any]:
    project = state["project"]
    accepted_doc = await api.post(
        f"/api/projects/{project['id']}/documents",
        {"title": "Avance semana 2", "kind": "progress", "text": (DEMO / "05-semana-2.md").read_text(encoding="utf-8")},
    )
    await api.wait(accepted_doc["job_id"])
    _, rubric, documents = await catalog(api, project["id"])
    accepted = await api.post(
        f"/api/projects/{project['id']}/sessions",
        session_body(
            state["profiles"],
            rubric,
            documents,
            objective="Mostrar el avance de la semana 2 frente a la devolución anterior",
            presentation="Esta semana probamos el flujo con la coordinadora y definimos el control de concurrencia.",
            max_questions=3,
            previous=state["session_id"],
        ),
    )
    await api.wait(accepted["job_id"])
    session, asked = await answer_all(api, project["id"], accepted["session_id"], FOLLOW_UP_ANSWERS)
    assert session["status"] == "COMPLETED"
    report = await report_summary(api, accepted["session_id"])
    assert report["comparison"], "el informe no compara con la sesión anterior"
    return {
        "project_id": project["id"],
        "session_id": accepted["session_id"],
        "previous_session_id": state["session_id"],
        "questions": asked,
        "report": report,
    }


def compose(*args: str) -> None:
    subprocess.run(["docker", "compose", *args], cwd=ROOT, check=True, capture_output=True)


async def scenario_restart(api: Api, state: dict[str, Any]) -> dict[str, Any]:
    project = state["project"]
    profiles, rubric, documents = await catalog(api, project["id"])
    chosen = [p for p in profiles if p["profile_id"] in {"entrega", "claridad"}]
    accepted = await api.post(
        f"/api/projects/{project['id']}/sessions",
        session_body(
            chosen,
            rubric,
            documents,
            objective="Explicar alcance y decisiones",
            presentation=(DEMO / "presentacion.txt").read_text(encoding="utf-8"),
            max_questions=3,
        ),
    )
    await api.wait(accepted["job_id"])
    before = await api.get(f"/api/sessions/{accepted['session_id']}")
    compose("restart", "api", "worker")
    deadline = time.monotonic() + 120
    while True:
        try:
            ready = await api.get("/api/health/ready")
            if ready["redis"] and ready["worker"]:
                break
        except httpx.HTTPError:
            pass
        assert time.monotonic() < deadline, "el stack no volvió a estar listo"
        await asyncio.sleep(2)
    after = await api.get(f"/api/sessions/{accepted['session_id']}")
    assert after["pending_question"] == before["pending_question"], "la pregunta pendiente cambió"
    assert after["transcript"] == before["transcript"], "el transcript cambió"
    session, asked = await answer_all(api, project["id"], accepted["session_id"], GROUNDED_ANSWERS)
    assert session["status"] == "COMPLETED"
    return {
        "project_id": project["id"],
        "session_id": accepted["session_id"],
        "pending_question_preserved": True,
        "questions": asked,
        "report": await report_summary(api, accepted["session_id"]),
    }


async def scenario_validation(api: Api, state: dict[str, Any]) -> dict[str, Any]:
    project = state["project"]
    rejected = {
        "proyecto_sin_titulo": (await api.raw_post("/api/projects", {"title": ""})).status_code,
        "campo_desconocido": (
            await api.raw_post("/api/projects", {"title": "x", "context": "x", "objective": "x", "admin": True})
        ).status_code,
    }
    profiles, rubric, documents = await catalog(api, project["id"])
    chosen = [p for p in profiles if p["profile_id"] in {"estrategia", "experimentacion"}]
    body = session_body(
        chosen,
        rubric,
        documents,
        objective="Defender el valor para la coordinadora",
        presentation="Queremos mostrar por qué la coordinadora necesita el calendario.",
        max_questions=3,
    )
    rejected["seis_evaluadores"] = (
        await api.raw_post(
            f"/api/projects/{project['id']}/sessions", {**body, "profile_versions": body["profile_versions"] * 3}
        )
    ).status_code
    accepted = await api.post(f"/api/projects/{project['id']}/sessions", body)
    await api.wait(accepted["job_id"])
    session = await api.get(f"/api/sessions/{accepted['session_id']}")
    question = session["pending_question"]
    rejected["revision_desactualizada"] = (
        await api.raw_post(
            f"/api/sessions/{accepted['session_id']}/responses",
            {"question_id": question["id"], "expected_revision": session["revision"] + 7, "text": "Respuesta"},
        )
    ).status_code
    key = uuid.uuid4().hex
    finish = {"question_id": question["id"], "expected_revision": session["revision"]}
    first = await api.post(f"/api/sessions/{accepted['session_id']}/finish", finish, key=key)
    replay = await api.post(f"/api/sessions/{accepted['session_id']}/finish", finish, key=key)
    assert first["job_id"] == replay["job_id"], "la idempotencia no devolvió el mismo trabajo"
    await api.wait(first["job_id"])
    report = await report_summary(api, accepted["session_id"])
    assert rejected["proyecto_sin_titulo"] == 422 and rejected["campo_desconocido"] == 422
    assert rejected["seis_evaluadores"] == 422 and rejected["revision_desactualizada"] == 409
    assert "not_assessed" in report["criteria"].values(), "el cierre anticipado debería dejar criterios sin tratar"
    return {
        "project_id": project["id"],
        "session_id": accepted["session_id"],
        "rejected_status_codes": rejected,
        "idempotent_finish": True,
        "report": report,
    }


SCENARIOS = [
    ("revision_fundamentada", scenario_grounded),
    ("evidencia_insuficiente", scenario_insufficient),
    ("seguimiento_semanal", scenario_follow_up),
    ("reinicio_con_pausa", scenario_restart),
    ("validacion_y_cierre", scenario_validation),
]


def budget(service: str) -> dict[str, str]:
    output = subprocess.run(
        ["docker", "compose", "exec", "-T", service, "redis-cli", "HGETALL", "panellab:budget:api"],
        cwd=ROOT,
        capture_output=True,
        text=True,
    ).stdout.split()
    return dict(zip(output[::2], output[1::2], strict=False))


async def run(url: str, only: set[str] | None, redis_service: str) -> dict[str, Any]:
    results: dict[str, Any] = {"started_at": datetime.now(UTC).isoformat(), "scenarios": []}
    async with httpx.AsyncClient(base_url=url.rstrip("/"), timeout=30) as client:
        api = Api(client)
        ready = await api.get("/api/health/ready")
        results["llm_mode"] = ready["llm_mode"]
        results["budget_before"] = budget(redis_service)
        state: dict[str, Any] = {}
        for name, scenario in SCENARIOS:
            if only and name not in only:
                continue
            started = time.monotonic()
            spent_before = float(budget(redis_service).get("spent", 0) or 0)
            print(f"→ {name}…", flush=True)
            try:
                outcome = await scenario(api, state)
                status = "ok"
            except Exception as exc:  # se registra y se sigue con el resto
                outcome, status = {"error": f"{type(exc).__name__}: {exc}"}, "failed"
            elapsed = round(time.monotonic() - started, 1)
            cost = round(float(budget(redis_service).get("spent", 0) or 0) - spent_before, 8)
            print(f"  {status} ({elapsed} s, USD {cost:.6f})", flush=True)
            results["scenarios"].append(
                {"name": name, "status": status, "seconds": elapsed, "cost_usd": cost, **outcome}
            )
        results["budget_after"] = budget(redis_service)
    results["finished_at"] = datetime.now(UTC).isoformat()
    return results


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--url", default="http://127.0.0.1:8080")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--only", nargs="*", help="nombres de escenarios a correr")
    parser.add_argument(
        "--redis-service", default="redis", help="servicio Redis con el presupuesto (redis-live con compose.live.yaml)"
    )
    args = parser.parse_args()
    data = asyncio.run(run(args.url, set(args.only) if args.only else None, args.redis_service))
    text = json.dumps(data, ensure_ascii=False, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text + "\n", encoding="utf-8")
    failed = [s["name"] for s in data["scenarios"] if s["status"] != "ok"]
    print(
        f"\n{len(data['scenarios']) - len(failed)}/{len(data['scenarios'])} escenarios OK"
        + (f" · fallaron: {', '.join(failed)}" if failed else "")
    )
