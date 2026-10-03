"""Exporta el diagrama Mermaid del grafo real (sin Redis ni red).

    python -m scripts.export_graph --output ../docs/grafo.mmd

El README incluye este diagrama: regenerarlo cuando cambien nodos o aristas.
"""

from __future__ import annotations

import argparse
from pathlib import Path
from types import SimpleNamespace

from app.config import Settings
from app.engine import GraphEngine


def mermaid() -> str:
    engine = GraphEngine(SimpleNamespace(redis=None), Settings(llm_mode="demo"))
    return engine._build_graph().compile().get_graph().draw_mermaid()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    text = mermaid()
    if args.output:
        args.output.write_text(text, encoding="utf-8")
    print(text)
