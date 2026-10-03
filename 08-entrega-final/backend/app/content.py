"""Safe, versioned Markdown configuration."""

from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Any

import yaml
from pydantic import ValidationError

from .contracts import Criterion


class ContentError(ValueError):
    pass


# Identificadores de un catálogo inicial ya retirado. Se guardan como hash para que las
# sesiones históricas sigan resolviendo sus versiones, sin poder elegirlos en sesiones nuevas.
RETIRED_CATALOG_HASHES = frozenset(
    {
        "081a8aef8df1aeea3a424b7d0a02b96df2fb8c0c2d1a3ccb9da3aa7154f31916",
        "0e949b5f9de9cfa8437d0beeca8d8c96a6b578caa889fd6659e85b7dff22e59b",
        "7c8f9ab8445a49e3ce03b62d3c0f1ddc8cfd52ce75b596a4897117a546d08193",
        "85dc0c638f095c20fa6e90eeaf897d9f821ae2419ef05f5e078e69d5a06454d5",
        "906294dd1e8ba6474e770d1c74e9f184555060e55789d0bcd5f49f6806901d7f",
        "95eca31c5fa50b40be8be1a99b929451abbae207a5e41979341be53f406edeb2",
        "a60b85d409a01d46023f90741e01b79543a3cb1ba048eaefbe5d7a63638043bf",
        "f3e6e45112b8b83032d5b0f710876590d856ceedd65537686d7426b5a015b5ce",
    }
)


def retired_catalog_profile(profile_id: str) -> bool:
    return hashlib.sha256(profile_id.encode("utf-8")).hexdigest() in RETIRED_CATALOG_HASHES


def digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def parse_markdown(markdown: str, kind: str) -> dict[str, Any]:
    limit = 16384 if kind == "profile" else 32768
    if len(markdown.encode("utf-8")) > limit:
        raise ContentError(f"{kind} exceeds {limit} bytes")
    if not markdown.startswith("---\n"):
        raise ContentError("YAML frontmatter is required")
    try:
        front, body = markdown[4:].split("\n---\n", 1)
    except ValueError as exc:
        raise ContentError("closing frontmatter delimiter is missing") from exc
    if not body.strip():
        raise ContentError("Markdown body is required")
    try:
        meta = yaml.safe_load(front)
    except yaml.YAMLError as exc:
        raise ContentError(f"invalid YAML: {exc}") from exc
    if not isinstance(meta, dict):
        raise ContentError("frontmatter must be an object")
    required = {"id", "name", "role", "focus", "style"} if kind == "profile" else {"id", "name", "criteria"}
    if set(meta) != required:
        raise ContentError(f"frontmatter keys must be {sorted(required)}")
    if not isinstance(meta["id"], str) or not re.fullmatch(r"[a-z][a-z0-9_-]{1,63}", meta["id"]):
        raise ContentError("id must be a slug")
    if not isinstance(meta["name"], str) or not meta["name"].strip():
        raise ContentError("name is required")
    if kind == "profile":
        if not isinstance(meta["role"], str) or not meta["role"].strip():
            raise ContentError("role is required")
        if not isinstance(meta["style"], str) or not meta["style"].strip():
            raise ContentError("style is required")
        if (
            not isinstance(meta["focus"], list)
            or not meta["focus"]
            or not all(isinstance(x, str) and x for x in meta["focus"])
        ):
            raise ContentError("focus must be a nonempty list of criterion IDs")
    else:
        if not isinstance(meta["criteria"], list) or not meta["criteria"]:
            raise ContentError("criteria must be a nonempty list")
        try:
            criteria = [Criterion.model_validate(c).model_dump() for c in meta["criteria"]]
        except ValidationError as exc:
            raise ContentError(str(exc)) from exc
        ids = [item["id"] for item in criteria]
        if len(ids) != len(set(ids)):
            raise ContentError("duplicate criterion id")
        meta["criteria"] = criteria
    return meta


def template_files(config_dir: Path, kind: str) -> list[Path]:
    folder = config_dir / ("profiles" if kind == "profile" else "rubrics")
    return sorted(folder.glob("*.md")) if folder.is_dir() else []
