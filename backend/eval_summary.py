"""GET /eval/summary: precision / recall / amount recovered of the stored findings against the hidden answer key.

The key (data/synthetic/out/answer_key.json) holds `positives` (planted leakage: claim_id, check_id, amount, ...)
and `negatives` (legitimate look-alikes that must NOT be flagged). A plain list of items, or a dict with one under
`findings` / `items` / `planted`, is accepted too; an item may carry `should_flag: false`. Matching is by
(claim_id, check_id).
"""
from __future__ import annotations

import json
import logging
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List, Tuple

from core.schemas.finding import Finding, FindingStatus

from backend.store import Repository
from backend.views import REPORTING_CURRENCY, to_reporting

# Claims submitted through the customer portal (backend/portal.py) carry this id prefix.
PORTAL_PREFIX = "CLM-P-"

logger = logging.getLogger(__name__)

Key = Tuple[str, str]


def load_answer_key(path: Path) -> List[Dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(payload, dict) and isinstance(payload.get("positives"), list):
        items = [{**item, "should_flag": True} for item in payload["positives"]]
        items += [{**item, "should_flag": False} for item in payload.get("negatives", []) if isinstance(item, dict)]
        payload = items
    elif isinstance(payload, dict):
        for name in ("findings", "items", "planted", "answer_key"):
            if isinstance(payload.get(name), list):
                payload = payload[name]
                break
    if not isinstance(payload, list):
        raise ValueError("answer key must hold positives/negatives or a list of planted items")
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
    # Every claim of the synthetic set is scored (a finding on a clean claim is a false alarm); only claims that
    # arrived later through the customer portal have no ground truth and are left out.
    found: Dict[Key, List[Dict[str, Any]]] = defaultdict(list)
    for doc in store.list(collection="findings"):
        if doc.get("status") == FindingStatus.DISMISSED.value or str(doc.get("claim_id")).startswith(PORTAL_PREFIX):
            continue
        found[(str(doc["claim_id"]), str(doc["check_id"]))].append(doc)
    per_check: Dict[str, Dict[str, int]] = defaultdict(lambda: {"tp": 0, "fp": 0, "fn": 0})
    # Money is compared on CALCULATED cases only (suspected amounts count once a reviewer confirms them),
    # converted to the dashboard's reporting currency so INR and AED claims add up.
    currency = {doc["claim_id"]: doc.get("currency") for doc in store.list(collection="claims")}
    recovered = planted_amount = suspected_planted = 0.0
    false_alarms: List[Dict[str, Any]] = []
    for key, item in planted.items():
        amount = to_reporting(float(item.get("amount") or 0.0), currency.get(key[0]))
        calculated_case = str(item.get("amount_kind") or "calculated") == "calculated"
        if calculated_case:
            planted_amount += amount
        else:
            suspected_planted += amount
        if key in found:
            per_check[key[1]]["tp"] += 1
            if calculated_case:
                recovered += sum(to_reporting(_effective(doc), currency.get(key[0])) for doc in found[key])
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
            "amount_suspected_planted": round(suspected_planted, 2), "reporting_currency": REPORTING_CURRENCY,
            "look_alikes_wrongly_flagged": false_alarms, "by_check": checks}


def _effective(doc: Dict[str, Any]) -> float:
    """The same rule the settlement uses (Finding.effective_amount), so 'recovered' matches the deductions."""
    try:
        return Finding.model_validate(doc).effective_amount
    except Exception:
        return 0.0
