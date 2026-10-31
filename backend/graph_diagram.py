"""Writes the workflow graph as Mermaid text to docs/graph.mmd (and prints it).

    .venv/Scripts/python.exe -m backend.graph_diagram
"""
from __future__ import annotations

import logging
import sys
from pathlib import Path

from backend.graph import build_graph
from backend.settings import REPO_ROOT

logger = logging.getLogger(__name__)


def mermaid_text() -> str:
    return build_graph().get_graph().draw_mermaid()


def write_diagram(target: Path = REPO_ROOT / "docs" / "graph.mmd") -> Path:
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(mermaid_text(), encoding="utf-8")
    return target


if __name__ == "__main__":
    path = write_diagram()
    sys.stdout.write(path.read_text(encoding="utf-8"))
    logger.info("diagram written", extra={"path": str(path)})
