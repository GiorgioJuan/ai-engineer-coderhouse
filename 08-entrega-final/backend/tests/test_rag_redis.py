"""Redis Search integration: run with PANEL_TEST_REDIS_URL on the isolated test Redis."""

from __future__ import annotations

import os
import uuid

import pytest
import redis.asyncio as redis

from app.rag import RedisRAG, demo_embedding


@pytest.mark.asyncio
async def test_search_respects_project_and_immutable_versions():
    url = os.getenv("PANEL_TEST_REDIS_URL")
    if not url:
        pytest.skip("Set PANEL_TEST_REDIS_URL to a Redis Search test instance")
    client = redis.from_url(url, decode_responses=False)
    rag = RedisRAG(client, lambda text: _embed(text), dimensions=1536)
    project = uuid.uuid4().hex
    other = uuid.uuid4().hex
    try:
        documents = [
            {
                "project_id": project,
                "document_id": "brief",
                "version": 1,
                "text": (
                    "## Página 1\nSe entrevistó a cinco personas para comprobar el prototipo.\n\n"
                    "## Página 2\nEl presupuesto previsto es de mil pesos."
                ),
            },
            {
                "project_id": project,
                "document_id": "brief",
                "version": 2,
                "text": "# Validación\nSe entrevistó a cincuenta personas para comprobar el prototipo.",
            },
            {
                "project_id": other,
                "document_id": "secreto",
                "version": 1,
                "text": "# Validación\nSe entrevistó a mil personas para comprobar el prototipo.",
            },
        ]
        for document in documents:
            await rag.index_document(document)
        result = await rag.search(
            "entrevistas validación prototipo", project, [{"document_id": "brief", "version": 1}], top_k=5
        )
        assert result and all(item.document_id == "brief" and item.version == 1 for item in result)
        assert "cinco" in result[0].excerpt
        assert result[0].section == "Página 1"
        assert "presupuesto" not in result[0].excerpt
        for citation in result:
            await rag.validate(citation, project, [{"document_id": "brief", "version": 1}])
    finally:
        for document in documents:
            marker = f"panellab:rag:docchunks:{document['project_id']}:{document['document_id']}:{document['version']}"
            members = await client.smembers(marker)
            for member in members:
                member = member.decode() if isinstance(member, bytes) else member
                await client.delete(f"panellab:chunk:{document['project_id']}:{member}")
            await client.delete(marker)
        await client.aclose()


async def _embed(text: str) -> list[float]:
    return demo_embedding(text, 1536)
