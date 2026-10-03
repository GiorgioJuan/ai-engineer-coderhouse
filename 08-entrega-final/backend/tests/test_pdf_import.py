from __future__ import annotations

import subprocess
from io import BytesIO

import pytest
from fakeredis.aioredis import FakeRedis
from httpx import ASGITransport, AsyncClient
from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

import app.pdf_import as pdf_import
from app.main import app
from app.pdf_import import PdfImportError, _extract_in_subprocess, extract_pdf
from app.storage import Repository


def pdf(*pages: str, encrypted: bool = False) -> bytes:
    writer = PdfWriter()
    for value in pages:
        page = writer.add_blank_page(width=612, height=792)
        if value:
            font = DictionaryObject(
                {
                    NameObject("/Type"): NameObject("/Font"),
                    NameObject("/Subtype"): NameObject("/Type1"),
                    NameObject("/BaseFont"): NameObject("/Helvetica"),
                }
            )
            page[NameObject("/Resources")] = DictionaryObject(
                {NameObject("/Font"): DictionaryObject({NameObject("/F1"): writer._add_object(font)})}
            )
            stream = DecodedStreamObject()
            stream.set_data(f"BT /F1 12 Tf 72 720 Td ({value}) Tj ET".encode("ascii"))
            page[NameObject("/Contents")] = writer._add_object(stream)
    if encrypted:
        writer.encrypt("password")
    output = BytesIO()
    writer.write(output)
    return output.getvalue()


@pytest.fixture
def repo():
    return Repository(FakeRedis(decode_responses=False))


@pytest.fixture
def client(repo):
    app.state.repo = repo
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


@pytest.mark.asyncio
async def test_pdf_preview_preserves_page_numbers_and_does_not_save(client, repo):
    await repo.put("project", "p", {"id": "p", "title": "P", "context": "C", "objective": "O"})
    response = await client.post(
        "/api/projects/p/documents/extract?filename=notes.pdf",
        content=pdf("First point", "", "Last point"),
        headers={"Content-Type": "application/pdf"},
    )
    assert response.status_code == 200, response.text
    assert response.json() == {
        "title": "notes",
        "text": "## Página 1\n\nFirst point\n\n## Página 3\n\nLast point",
        "page_count": 3,
        "warnings": [
            "No se encontró texto seleccionable en las páginas 2; revisalas si contienen información importante."
        ],
    }
    assert await repo.list("document", "p") == []
    assert await repo.list("job", "p") == []


@pytest.mark.asyncio
async def test_pdf_endpoint_rejects_missing_project_and_wrong_media_type(client):
    missing = await client.post(
        "/api/projects/unknown/documents/extract", content=pdf("Text"), headers={"Content-Type": "application/pdf"}
    )
    assert missing.status_code == 404
    repo = app.state.repo
    await repo.put("project", "p", {"id": "p"})
    wrong_type = await client.post(
        "/api/projects/p/documents/extract", content=pdf("Text"), headers={"Content-Type": "application/octet-stream"}
    )
    assert wrong_type.status_code == 415


@pytest.mark.asyncio
async def test_pdf_endpoint_rejects_oversized_upload(client, repo):
    await repo.put("project", "p", {"id": "p"})
    response = await client.post(
        "/api/projects/p/documents/extract",
        content=b"%PDF-" + b"x" * (10 * 1024 * 1024),
        headers={"Content-Type": "application/pdf"},
    )
    assert response.status_code == 413


@pytest.mark.parametrize(
    "payload,expected",
    [
        (b"garbage", "PDF válido"),
        (b"%PDF-1.4\ncorrupt", "no esté dañado"),
        (pdf("", ""), "OCR"),
        (pdf("Secret", encrypted=True), "contraseña"),
        (pdf(*(["Text"] * 51)), "50 páginas"),
    ],
)
def test_pdf_parser_rejects_unusable_files(payload, expected):
    with pytest.raises(PdfImportError, match=expected):
        extract_pdf(payload, "file.pdf")


def test_pdf_parser_enforces_extracted_utf8_limit():
    with pytest.raises(PdfImportError, match="200 KB") as exc:
        extract_pdf(pdf("X" * 200_000))
    assert exc.value.status_code == 413


def test_pdf_worker_timeout_is_actionable(monkeypatch):
    def time_out(*_args, **_kwargs):
        raise subprocess.TimeoutExpired(cmd="pdf-worker", timeout=15)

    monkeypatch.setattr(pdf_import.subprocess, "run", time_out)
    with pytest.raises(PdfImportError, match="tardó demasiado") as exc:
        _extract_in_subprocess(pdf("Text"), "file.pdf")
    assert exc.value.status_code == 422
