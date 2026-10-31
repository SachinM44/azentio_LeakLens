"""Versioned prompts: each .md file has a front-matter header (name, version, source, sha256_12)."""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

PROMPT_DIR = Path(__file__).resolve().parent


@dataclass(frozen=True)
class Prompt:
    name: str
    version: int
    text: str
    sha256_12: str  # hash of the text the model sees, recorded on every result


@lru_cache(maxsize=None)
def load_prompt(name: str) -> Prompt:
    raw = (PROMPT_DIR / f"{name}.md").read_text(encoding="utf-8")
    header, _, body = raw.partition("\n---\n")
    meta = dict(line.split(": ", 1) for line in header.splitlines()[1:] if ": " in line)
    text = body.strip("\n")
    return Prompt(name=name, version=int(meta.get("version", 1)), text=text,
                  sha256_12=hashlib.sha256(text.encode("utf-8")).hexdigest()[:12])
