"""Policy-clause retrieval: the policy wording is split into numbered clauses, each clause is embedded once
(Titan Text Embeddings v2 on Bedrock) and a finding is linked to the clause closest to its rule, with the
similarity shown. A lexical BM25 index is the fallback when embeddings are unavailable, so retrieval never
blocks a run.

    index = PolicyIndex.load(Path("data/policies/IN-HEALTH-RETAIL.md"))
    index.search("room rent limit per day", k=3)   -> [(clause_id, text, score), ...]
    attach_clauses(findings, index)                 -> fills Finding.clause where the rule comes from wording
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np

from core.schemas.finding import CheckCategory, ClauseRef, Finding

logger = logging.getLogger("leaklens.rag")
EMBED_MODEL = os.environ.get("LEAKLENS_EMBED_MODEL", "amazon.titan-embed-text-v2:0")
EMBED_DIM = 512
_CLAUSE_RE = re.compile(r"^\s*(?:#+\s*)?(\d+(?:\.\d+){0,3})[\.\)]?\s+(.+)$")


@dataclass
class Clause:
    clause_id: str
    text: str


def parse_clauses(markdown: str) -> List[Clause]:
    """Numbered paragraphs ('4.2 Room rent ...') with their continuation lines."""
    clauses: List[Clause] = []
    for raw in markdown.splitlines():
        line = raw.rstrip()
        m = _CLAUSE_RE.match(line)
        if m:
            clauses.append(Clause(clause_id=m.group(1), text=m.group(2).strip()))
        elif clauses and line.strip() and not line.lstrip().startswith("#"):
            clauses[-1].text += " " + line.strip()
    return clauses


def _embed_bedrock(texts: Sequence[str]) -> np.ndarray:
    import boto3

    client = boto3.client("bedrock-runtime", region_name=os.environ.get("AWS_REGION_NAME", "ap-south-1"))
    vectors = []
    for text in texts:
        body = json.dumps({"inputText": text[:8000], "dimensions": EMBED_DIM, "normalize": True})
        response = client.invoke_model(modelId=EMBED_MODEL, body=body, contentType="application/json", accept="application/json")
        vectors.append(json.loads(response["body"].read())["embedding"])
    return np.asarray(vectors, dtype=np.float32)


class PolicyIndex:
    def __init__(self, product_id: str, clauses: List[Clause], vectors: Optional[np.ndarray]) -> None:
        self.product_id = product_id
        self.clauses = clauses
        self.vectors = vectors            # None -> lexical fallback
        self._bm25 = None
        self.mode = "embeddings" if vectors is not None else "bm25"

    @classmethod
    def load(cls, path: Path, cache_dir: Optional[Path] = None, use_embeddings: bool = True) -> "PolicyIndex":
        text = path.read_text(encoding="utf-8")
        clauses = parse_clauses(text)
        product_id = path.stem
        vectors = None
        if use_embeddings and clauses:
            digest = hashlib.sha256((EMBED_MODEL + text).encode("utf-8")).hexdigest()[:16]
            cache = (cache_dir or path.parent / ".cache") / f"{product_id}.{digest}.npy"
            try:
                if cache.exists():
                    vectors = np.load(cache)
                else:
                    vectors = _embed_bedrock([f"{c.clause_id} {c.text}" for c in clauses])
                    cache.parent.mkdir(parents=True, exist_ok=True)
                    np.save(cache, vectors)
            except Exception as exc:  # noqa: BLE001 - retrieval must never block a run
                logger.warning("policy embeddings unavailable, using lexical search", extra={"error": str(exc)[:160]})
                vectors = None
        return cls(product_id, clauses, vectors)

    def _lexical(self):
        if self._bm25 is None:
            from rank_bm25 import BM25Okapi
            self._bm25 = BM25Okapi([re.findall(r"[a-z0-9]+", f"{c.clause_id} {c.text}".lower()) for c in self.clauses])
        return self._bm25

    def search(self, query: str, k: int = 3) -> List[Tuple[str, str, float]]:
        if not self.clauses:
            return []
        if self.vectors is not None:
            try:
                q = _embed_bedrock([query])[0]
                scores = self.vectors @ q
                order = np.argsort(-scores)[:k]
                return [(self.clauses[i].clause_id, self.clauses[i].text, float(max(0.0, min(1.0, scores[i])))) for i in order]
            except Exception as exc:  # noqa: BLE001
                logger.warning("embedding query failed, using lexical search", extra={"error": str(exc)[:160]})
        scores = self._lexical().get_scores(re.findall(r"[a-z0-9]+", query.lower()))
        top = max(float(scores.max()), 1e-9)
        order = np.argsort(-scores)[:k]
        return [(self.clauses[i].clause_id, self.clauses[i].text, round(float(scores[i]) / top, 3)) for i in order if scores[i] > 0]

    def clause_text(self, clause_id: str) -> Optional[str]:
        for c in self.clauses:
            if c.clause_id == clause_id:
                return c.text
        return None


def attach_clauses(findings: List[Finding], index: PolicyIndex, min_score: float = 0.35) -> List[Finding]:
    """Policy-rule findings get the governing clause: the configured clause's full text when the rule names one,
    otherwise the nearest clause by retrieval (only when the match is reasonable)."""
    for f in findings:
        if f.category != CheckCategory.POLICY_RULE:
            continue
        if f.clause and f.clause.clause_id:
            text = index.clause_text(f.clause.clause_id)
            if text:
                f.clause = ClauseRef(clause_id=f.clause.clause_id, text=text, score=1.0)
            continue
        hits = index.search(f"{f.rule_text} {f.reason}", k=1)
        if hits and hits[0][2] >= min_score:
            cid, text, score = hits[0]
            f.clause = ClauseRef(clause_id=cid, text=text, score=round(score, 3))
    # The recommended correction cites the same clause the finding now rests on.
    for f in findings:
        if f.clause and f.correction is not None and not f.correction.clause_id:
            f.correction.clause_id = f.clause.clause_id
    return findings


_INDEXES: Dict[str, PolicyIndex] = {}


def index_for(product_id: str, policies_dir: Path) -> Optional[PolicyIndex]:
    """Cached per process; None when the product has no wording file."""
    if product_id in _INDEXES:
        return _INDEXES[product_id]
    path = policies_dir / f"{product_id}.md"
    if not path.exists():
        return None
    _INDEXES[product_id] = PolicyIndex.load(path)
    return _INDEXES[product_id]
