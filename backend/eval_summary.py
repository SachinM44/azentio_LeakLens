"""GET /eval/summary: precision / recall / amount recovered of the stored findings against the hidden answer key.

The key (data/synthetic/out/answer_key.json) is a list of planted items, or a dict holding one under
`findings` / `items` / `planted`. Each item names `claim_id` and `check_id`, optionally `amount`, and may carry
`should_flag: false` for a legitimate look-alike that must NOT be flagged. Matching is by (claim_id, check_id).
"""
from __future__ import annotations

import json
import logging
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List, Tuple

from core.schemas.finding import FindingStatus

from backend.store import Repository

logger = logging.getLogger(__name__)

Key = Tuple[str, str]


def load_answer_key(path: Path) -> List[Dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(payload, dict):
        for name in ("findings", "items", "planted", "answer_key"):
            if isinstance(payload.get(name), list):
                payload = payload[name]
                break
    if not isinstance(payload, list):
        raise ValueError("answer key must be a list of planted items")
    return [item for item in payload if isinstance(item, dict) and item.get("claim_id") and item.get("check_id")]


def _should_flag(item: Dict[str, Any]) -> bool:
    for name in ("should_flag", "expected", "is_leakage"):
        if name in item:
            return bool(item[name])
    return True


def _rates(tp: int, fp: int, fn: int) -> Dict[str, Any]:
    precision = tp / (tp + fp) if tp + fp else None
    recall = tp / (tp + fn) if tp + fn else None
    return {"tp": tp, "fp": fp, "fn": fn, "precision": None if precision is None else round(precision, 3),
            "recall": None if recall is None else round(recall, 3)}


def summary(store: Repository, key_path: Path) -> Dict[str, Any]:
    if not key_path.exists():
        return {"available": False, "reason": f"{key_path.name} not found"}
    try:
        items = load_answer_key(path=key_path)
    except Exception as exc:
        logger.warning("answer key unreadable", extra={"error": str(exc)})
        return {"available": False, "reason": str(exc)}
    planted: Dict[Key, Dict[str, Any]] = {}
    must_not_flag: Dict[Key, Dict[str, Any]] = {}
    for item in items:
        key = (str(item["claim_id"]), str(item["check_id"]))
        (planted if _should_flag(item) else must_not_flag)[key] = item
    found: Dict[Key, List[Dict[str, Any]]] = defaultdict(list)
    for doc in store.list(collection="findings"):
        if doc.get("status") == FindingStatus.DISMISSED.value:
            continue
        found[(str(doc["claim_id"]), str(doc["check_id"]))].append(doc)
    per_check: Dict[str, Dict[str, int]] = defaultdict(lambda: {"tp": 0, "fp": 0, "fn": 0})
    recovered = planted_amount = 0.0
    false_alarms: List[Dict[str, Any]] = []
    for key, item in planted.items():
        planted_amount += float(item.get("amount") or 0.0)
        if key in found:
            per_check[key[1]]["tp"] += 1
            recovered += sum(_effective(doc) for doc in found[key])
        else:
            per_check[key[1]]["fn"] += 1
    for key, docs in found.items():
        if key not in planted:
            per_check[key[1]]["fp"] += len(docs)
            if key in must_not_flag:
                false_alarms.append({"claim_id": key[0], "check_id": key[1], "note": "legitimate look-alike was flagged"})
    tp = sum(v["tp"] for v in per_check.values())
    fp = sum(v["fp"] for v in per_check.values())
    fn = sum(v["fn"] for v in per_check.values())
    checks = {check: _rates(tp=v["tp"], fp=v["fp"], fn=v["fn"]) for check, v in sorted(per_check.items())}
    return {"available": True, "planted": len(planted), "must_not_flag": len(must_not_flag), "overall": _rates(tp=tp, fp=fp, fn=fn),
            "amount_planted": round(planted_amount, 2), "amount_recovered": round(recovered, 2),
            "look_alikes_wrongly_flagged": false_alarms, "by_check": checks}


def _effective(doc: Dict[str, Any]) -> float:
    if doc.get("status") == FindingStatus.CORRECTED.value and doc.get("corrected_amount") is not None:
        return float(doc["corrected_amount"])
    return float(doc.get("amount") or 0.0) if doc.get("amount_kind") == "calculated" else 0.0
