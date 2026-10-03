"""Bounded, local PDF text extraction for a review-before-save workflow."""

from __future__ import annotations

import asyncio
import contextlib
import json
import re
import subprocess
import sys
from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory

from pypdf import PdfReader

MAX_PDF_BYTES = 10 * 1024 * 1024
MAX_PAGES = 50
MAX_TEXT_BYTES = 200_000
EXTRACTION_TIMEOUT_SECONDS = 15
_EXTRACTION_SLOTS = asyncio.Semaphore(2)


class PdfImportError(Exception):
    def __init__(self, status_code: int, message: str):
        super().__init__(message)
        self.status_code = status_code


def _title(filename: str | None, metadata_title: str | None) -> str:
    basename = (filename or "").replace("\\", "/").rsplit("/", 1)[-1]
    if basename.lower().endswith(".pdf"):
        basename = basename[:-4]
    value = basename or metadata_title or "Documento PDF"
    value = re.sub(r"[\x00-\x1f\x7f]+", " ", value)
    value = " ".join(value.split()).strip(" .")
    return value[:160] or "Documento PDF"


def extract_pdf(data: bytes, filename: str | None = None) -> dict:
    """Runs inside the worker subprocess; never stores the source PDF."""
    if not data or len(data) > MAX_PDF_BYTES:
        raise PdfImportError(
            413 if data else 422, "El PDF supera el límite de 10 MB." if data else "El PDF está vacío."
        )
    if not data.startswith(b"%PDF-"):
        raise PdfImportError(422, "El archivo no es un PDF válido.")

    try:
        reader = PdfReader(BytesIO(data), strict=False)
        if reader.is_encrypted:
            raise PdfImportError(422, "El PDF tiene contraseña. Quitá la protección y volvé a subirlo.")
        page_count = len(reader.pages)
        if page_count == 0:
            raise PdfImportError(422, "El PDF no contiene páginas.")
        if page_count > MAX_PAGES:
            raise PdfImportError(413, "El PDF supera el límite de 50 páginas.")

        sections: list[str] = []
        blank_pages: list[int] = []
        used_bytes = 0
        for number, page in enumerate(reader.pages, 1):
            page_text = (page.extract_text() or "").strip()
            if not page_text:
                blank_pages.append(number)
                continue
            section = f"## Página {number}\n\n{page_text}"
            added = len(("\n\n" if sections else "").encode("utf-8")) + len(section.encode("utf-8"))
            used_bytes += added
            if used_bytes > MAX_TEXT_BYTES:
                raise PdfImportError(413, "El texto extraído supera el límite de 200 KB.")
            sections.append(section)

        if not sections:
            raise PdfImportError(
                422, "No se encontró texto seleccionable. Si el PDF está escaneado, aplicá OCR y volvé a subirlo."
            )
        warnings = []
        if blank_pages:
            page_numbers = ", ".join(str(number) for number in blank_pages)
            warnings.append(
                f"No se encontró texto seleccionable en las páginas {page_numbers}; "
                "revisalas si contienen información importante."
            )
        metadata_title = None
        # Metadatos corruptos no deben impedir importar el texto ya extraído.
        with contextlib.suppress(Exception):
            metadata_title = reader.metadata.title if reader.metadata else None
        return {
            "title": _title(filename, metadata_title),
            "text": "\n\n".join(sections),
            "page_count": page_count,
            "warnings": warnings,
        }
    except PdfImportError:
        raise
    except Exception as exc:
        raise PdfImportError(422, "No se pudo leer el PDF. Verificá que el archivo no esté dañado.") from exc


def _extract_in_subprocess(data: bytes, filename: str | None) -> dict:
    with TemporaryDirectory(prefix="panellab-pdf-") as directory:
        path = Path(directory) / "source.pdf"
        path.write_bytes(data)
        try:
            completed = subprocess.run(
                [sys.executable, "-m", "app.pdf_import", str(path), filename or ""],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=EXTRACTION_TIMEOUT_SECONDS,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise PdfImportError(
                422, "La extracción del PDF tardó demasiado. Probá con un archivo más simple."
            ) from exc
        if completed.returncode != 0:
            raise PdfImportError(422, "No se pudo leer el PDF. Verificá que el archivo no esté dañado.")
        try:
            result = json.loads(completed.stdout)
        except (json.JSONDecodeError, ValueError) as exc:
            raise PdfImportError(422, "No se pudo leer el PDF. Verificá que el archivo no esté dañado.") from exc
        if "error" in result:
            raise PdfImportError(result["status_code"], result["error"])
        return result


async def extract_pdf_isolated(data: bytes, filename: str | None = None) -> dict:
    async with _EXTRACTION_SLOTS:
        return await asyncio.to_thread(_extract_in_subprocess, data, filename)


def _worker() -> None:
    if sys.platform != "win32":
        try:
            import resource

            resource.setrlimit(resource.RLIMIT_AS, (512 * 1024 * 1024, 512 * 1024 * 1024))
            resource.setrlimit(resource.RLIMIT_CPU, (EXTRACTION_TIMEOUT_SECONDS, EXTRACTION_TIMEOUT_SECONDS))
        except (ImportError, OSError, ValueError):
            pass
    try:
        result = extract_pdf(Path(sys.argv[1]).read_bytes(), sys.argv[2] or None)
    except PdfImportError as exc:
        result = {"status_code": exc.status_code, "error": str(exc)}
    print(json.dumps(result, ensure_ascii=True))


if __name__ == "__main__":
    _worker()
