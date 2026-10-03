"""Version-scoped Redis Search retrieval with verifiable source citations."""

from __future__ import annotations

import hashlib
import math
import re
import struct
from collections import defaultdict
from collections.abc import Awaitable, Callable
from typing import Any

from pydantic import BaseModel, ConfigDict, Field
from redis.commands.search.field import TagField, TextField, VectorField
from redis.commands.search.index_definition import IndexDefinition, IndexType
from redis.commands.search.query import Query
from redis.exceptions import ResponseError

from app.contracts import Citation

INDEX = "panellab:chunks"  # valor por defecto; se configura con PANEL_RAG_INDEX
PREFIX = "panellab:chunk:"
Embed = Callable[[str], Awaitable[list[float]]]


class InvalidCitation(ValueError):
    pass


class SearchSourcesInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    query: str = Field(min_length=3, max_length=600)
    top_k: int = Field(default=5, ge=1, le=5)


class SearchSourcesOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    evidence_status: str = Field(pattern="^(found|insufficient)$")
    citations: list[Citation] = Field(default_factory=list, max_length=5)


def _words(text: str) -> list[str]:
    return re.findall(r"[\wáéíóúüñ]+", text.casefold(), flags=re.UNICODE)


def demo_embedding(text: str, dimensions: int = 64) -> list[float]:
    """Explicit offline fixture. Stable lexical hashing, not a semantic model."""
    values = [0.0] * dimensions
    for token in _words(text):
        digest = hashlib.sha256(token.encode()).digest()
        slot = int.from_bytes(digest[:4], "big") % dimensions
        values[slot] += 1.0 if digest[4] & 1 else -1.0
    norm = math.sqrt(sum(value * value for value in values)) or 1.0
    return [value / norm for value in values]


def chunks(text: str, size: int = 900, overlap: int = 120) -> list[tuple[str, str]]:
    """Bounded source substrings that never overlap across section/page headings."""
    if size < 1 or overlap < 0 or overlap >= size:
        raise ValueError("size must be positive and overlap smaller than size")
    output: list[tuple[str, str]] = []
    section = "Documento"
    page = ""
    segment: list[str] = []

    def emit() -> None:
        body = "".join(segment)
        if not body.strip():
            return
        step = size - overlap
        for start in range(0, len(body), step):
            excerpt = body[start : start + size].strip()
            if excerpt:
                output.append((section, excerpt))
            if start + size >= len(body):
                break

    for line in text.splitlines(keepends=True):
        heading = re.match(r"^[ \t]{0,3}#{1,6}[ \t]+(.+?)[ \t\r\n]*$", line)
        if heading:
            emit()
            segment = []
            title = heading.group(1).strip()[:120]
            if re.fullmatch(r"Página\s+\d+", title, flags=re.IGNORECASE):
                page = title
                section = title
            else:
                section = f"{page} · {title}" if page else title
        segment.append(line)
    emit()
    return output


def _tag(value: str) -> str:
    return re.sub(r"([^A-Za-z0-9_])", r"\\\1", value)


def _vector(values: list[float]) -> bytes:
    return struct.pack(f"<{len(values)}f", *values)


class RedisRAG:
    def __init__(
        self, redis: Any, embed: Embed, dimensions: int = 64, signature: str = "demo:hash-v1", index: str = INDEX
    ):
        self.redis = redis
        self.embed = embed
        self.dimensions = dimensions
        self.signature = f"{signature}:{dimensions}"
        self.index = index

    async def ensure_index(self) -> None:
        signature_key = "panellab:rag:signature"
        await self.redis.set(signature_key, self.signature, nx=True)
        existing = await self.redis.get(signature_key)
        if isinstance(existing, bytes):
            existing = existing.decode()
        if existing != self.signature:
            raise ValueError("RAG index embedding signature differs from configured model")
        try:
            await self.redis.ft(self.index).create_index(
                [
                    TagField("project_id"),
                    TagField("document_id"),
                    TagField("version"),
                    TextField("text"),
                    VectorField(
                        "embedding", "FLAT", {"TYPE": "FLOAT32", "DIM": self.dimensions, "DISTANCE_METRIC": "COSINE"}
                    ),
                ],
                definition=IndexDefinition(prefix=[PREFIX], index_type=IndexType.HASH),
            )
        except ResponseError as exc:
            if "Index already exists" not in str(exc):
                raise

    async def index_document(self, document: dict[str, Any]) -> list[str]:
        await self.ensure_index()
        document_id = document["document_id"]
        version = int(document["version"])
        project_id = document["project_id"]
        output: list[str] = []
        for number, (section, body) in enumerate(chunks(document["text"])):
            chunk_id = f"{document_id}:v{version}:{number}"
            key = f"{PREFIX}{project_id}:{chunk_id}"
            output.append(chunk_id)
            if await self.redis.exists(key):
                continue
            vector = await self.embed(body)
            if len(vector) != self.dimensions:
                raise ValueError("Embedding dimension mismatch")
            await self.redis.hset(
                key,
                mapping={
                    "project_id": project_id,
                    "document_id": document_id,
                    "version": str(version),
                    "chunk_id": chunk_id,
                    "section": section,
                    "text": body,
                    "embedding": _vector(vector),
                },
            )
        marker = f"panellab:rag:docchunks:{project_id}:{document_id}:{version}"
        if output:
            await self.redis.sadd(marker, *output)
        return output

    async def search(
        self, query: str, project_id: str, allowed: list[dict[str, Any]], top_k: int = 5
    ) -> list[Citation]:
        await self.ensure_index()
        allowed_set = {(ref["document_id"], int(ref["version"])) for ref in allowed}
        if not allowed_set:
            return []
        scope = " | ".join(
            f"(@document_id:{{{_tag(doc)}}} @version:{{{version}}})" for doc, version in sorted(allowed_set)
        )
        base = f"@project_id:{{{_tag(project_id)}}} ({scope})"
        terms = list(dict.fromkeys(_words(query)))[:20]
        if not terms:
            return []
        # Every query still carries the server-controlled project filter. The
        # immutable session snapshot is additionally enforced after retrieval.
        lexical = (
            Query(f"{base} @text:({'|'.join(_tag(word) for word in terms)})")
            .paging(0, 30)
            .return_fields("project_id", "document_id", "version", "chunk_id", "section", "text")
            .dialect(2)
        )
        vector = await self.embed(query)
        if len(vector) != self.dimensions:
            raise ValueError("Embedding dimension mismatch")
        semantic = (
            Query(f"({base})=>[KNN 30 @embedding $vec AS distance]")
            .sort_by("distance")
            .paging(0, 30)
            .return_fields("project_id", "document_id", "version", "chunk_id", "section", "text", "distance")
            .dialect(2)
        )
        results = await self.redis.ft(self.index).search(lexical)
        semantic_results = await self.redis.ft(self.index).search(semantic, query_params={"vec": _vector(vector)})
        score: dict[str, float] = defaultdict(float)
        records: dict[str, Any] = {}
        for ranked in (results.docs, semantic_results.docs):
            position = 0
            for item in ranked:
                if item.project_id != project_id or (item.document_id, int(item.version)) not in allowed_set:
                    continue
                position += 1
                score[item.chunk_id] += 1 / (60 + position)
                records[item.chunk_id] = item
        selected = sorted(score, key=lambda key: (-score[key], key))[: max(1, min(top_k, 5))]
        return [
            Citation(
                document_id=records[key].document_id,
                version=int(records[key].version),
                chunk_id=key,
                section=records[key].section,
                excerpt=records[key].text[:1200],
            )
            for key in selected
        ]

    async def search_tool(
        self, request: SearchSourcesInput, *, project_id: str, allowed: list[dict[str, Any]]
    ) -> SearchSourcesOutput:
        citations = await self.search(request.query, project_id, allowed, request.top_k)
        return SearchSourcesOutput(evidence_status="found" if citations else "insufficient", citations=citations)

    async def validate(self, citation: Citation, project_id: str, allowed: list[dict[str, Any]]) -> None:
        if (citation.document_id, citation.version) not in {
            (ref["document_id"], int(ref["version"])) for ref in allowed
        }:
            raise InvalidCitation("Citation outside the session snapshot")
        key = f"{PREFIX}{project_id}:{citation.chunk_id}"
        stored = await self.redis.hgetall(key)

        def field(name: str) -> str:
            raw = stored.get(name.encode(), stored.get(name))
            return raw.decode() if isinstance(raw, bytes) else str(raw or "")

        if (
            field("project_id") != project_id
            or field("document_id") != citation.document_id
            or field("version") != str(citation.version)
        ):
            raise InvalidCitation("Unknown citation source")
        marker = f"panellab:rag:docchunks:{project_id}:{citation.document_id}:{citation.version}"
        if not await self.redis.sismember(marker, citation.chunk_id):
            raise InvalidCitation("Citation chunk is not part of the indexed version")
        source = " ".join(field("text").split())
        excerpt = " ".join(citation.excerpt.split())
        if not excerpt or excerpt not in source:
            raise InvalidCitation("Citation excerpt is not present in source")
