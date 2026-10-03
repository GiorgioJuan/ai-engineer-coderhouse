"""Comparación entre informes de sesiones consecutivas (funciones puras)."""

from __future__ import annotations

from typing import Any

STATUS_ES = {"supported": "sustentado", "partial": "parcial", "missing": "sin evidencia", "not_assessed": "no evaluado"}


def compare_feedback(
    previous: dict[str, Any], current: list[dict[str, Any]], titles: dict[str, str]
) -> list[dict[str, Any]]:
    """Cambio de estado por criterio entre el informe anterior y el actual."""
    before = {item["criterion_id"]: item for item in previous.get("criterion_feedback", [])}
    changes = []
    for item in current:
        old = before.get(item["criterion_id"])
        if not old:
            continue
        changes.append(
            {
                "criterion_id": item["criterion_id"],
                "title": titles.get(item["criterion_id"], item["criterion_id"]),
                "previous_status": old["status"],
                "current_status": item["status"],
                "previous_sources": len(old.get("citations", [])),
                "current_sources": len(item.get("citations", [])),
            }
        )
    return changes


def comparison_text(changes: list[dict[str, Any]]) -> str:
    """Resumen en español, sin identificadores internos."""
    if not changes:
        return "Comparación con la sesión anterior: no hay criterios en común."
    parts = [
        f"{c['title']}: {STATUS_ES.get(c['previous_status'], c['previous_status'])} → "
        f"{STATUS_ES.get(c['current_status'], c['current_status'])}"
        for c in changes
    ]
    return "Comparación con la sesión anterior: " + "; ".join(parts) + "."
