"""Scorers: bill lines against a hand-made answer (count, sum, per-line match) and page classification agreement."""
from __future__ import annotations

import re
import statistics
from collections import defaultdict
from typing import Any, Dict, Iterable, List, Optional, Tuple

TAT_NOISE_SECONDS = 45.0           # run-to-run swing seen on the 10-claim passes of 2026-10-06
MIN_STABLE_CLAIMS = 8              # fewer stable claims than this: no decision
MASTER_SUM_TOLERANCE = 1.0         # rupees; a master bill sum that moves more than this fails

_NAME_NOISE = re.compile(r"[^a-z0-9]+")


def _norm_name(value: Any) -> str:
    return _NAME_NOISE.sub(" ", str(value or "").lower()).strip()


def _amount(value: Any) -> float:
    try:
        return round(float(str(value).replace(",", "").replace("−", "-") or 0), 2)
    except (TypeError, ValueError):
        return 0.0


# ---------------------------------------------------------------------------
# Document fields: baseline agreement plus exact matches against hand-read facts.
# ---------------------------------------------------------------------------

def score_gt_fields(variant_fields: Iterable[Dict[str, Any]], facts: Dict[str, Any],
                    normalise: Any) -> Dict[str, Any]:
    """``{gt_total, gt_same, gt_missed: [field_key...]}`` for the facts the ground truth states.

    ``normalise`` is passed in so this module stays pure.
    A text fact matches when the normalised values are equal or one contains the other
    (``"cataract, right eye"`` vs ``"cataract right eye"``); numbers match within 0.01.
    """
    by_key: Dict[str, Any] = {}
    for field in variant_fields or []:
        if isinstance(field, dict):
            key = _NAME_NOISE.sub("_", str(field.get("field_id") or "").lower()).strip("_")
            if key and key not in by_key:
                by_key[key] = field.get("value")
    missed: List[str] = []
    for key, expected in facts.items():
        got = by_key.get(key)
        want, have = normalise(expected), normalise(got)
        if isinstance(want, float) or isinstance(have, float):
            ok = isinstance(want, float) and isinstance(have, float) and abs(want - have) < 0.01
        else:
            want_s, have_s = _norm_name(want), _norm_name(have)
            ok = bool(want_s) and bool(have_s) and (want_s == have_s or want_s in have_s or have_s in want_s)
        if not ok:
            missed.append(key)
    return {"gt_total": len(facts), "gt_same": len(facts) - len(missed), "gt_missed": sorted(missed)}


# ---------------------------------------------------------------------------
# Bills: every row counts, adjustment rows included (the concession-row lesson of 2026-10-06).
# ---------------------------------------------------------------------------

def _rows(items: Iterable[Dict[str, Any]]) -> List[Tuple[str, float, Dict[str, Any]]]:
    rows = []
    for item in items or []:
        if not isinstance(item, dict):
            continue
        name = item.get("item_name") if "item_name" in item else item.get("item") or item.get("name")
        amount = item.get("total_amount") if "total_amount" in item else item.get("amount")
        rows.append((_norm_name(name), _amount(amount), item))
    return rows


def _match_lines(candidate: List[Tuple[str, float, Dict[str, Any]]],
                 reference: List[Tuple[str, float, Dict[str, Any]]]) -> Tuple[int, List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Greedy one-to-one match on amount (+/- 0.01) then name similarity; returns matched count and the leftovers."""
    unmatched_ref = list(range(len(reference)))
    matched = 0
    unmatched_cand: List[Dict[str, Any]] = []
    for name, amount, item in candidate:
        best, best_score = None, -1.0
        for index in unmatched_ref:
            ref_name, ref_amount, _ = reference[index]
            if abs(ref_amount - amount) > 0.01:
                continue
            score = _name_similarity(name, ref_name)
            if score > best_score:
                best, best_score = index, score
        if best is None or best_score < 0.3:
            unmatched_cand.append({"item": item.get("item_name") or item.get("item") or item.get("name"), "amount": amount})
            continue
        unmatched_ref.remove(best)
        matched += 1
    missing = [{"item": reference[i][2].get("item_name") or reference[i][2].get("item") or reference[i][2].get("name"),
                "amount": reference[i][1]} for i in unmatched_ref]
    return matched, unmatched_cand, missing


def _name_similarity(a: str, b: str) -> float:
    if not a or not b:
        return 0.0
    if a == b or a in b or b in a:
        return 1.0
    # Spacing is not a reading error: "SodiumChlorid0.9%100mlAquapulseInjPP" is the printed
    # "SodiumChlorid0.9% 100ml Aquapulse Inj PP" (a transcriber's spacing differs from the model's).
    squashed_a, squashed_b = a.replace(" ", ""), b.replace(" ", "")
    if squashed_a == squashed_b or squashed_a in squashed_b or squashed_b in squashed_a:
        return 1.0
    ta, tb = set(a.split()), set(b.split())
    return len(ta & tb) / len(ta | tb) if ta | tb else 0.0


def score_bill(items: Iterable[Dict[str, Any]], baseline_items: Optional[Iterable[Dict[str, Any]]] = None,
               gt_lines: Optional[Iterable[Dict[str, Any]]] = None) -> Dict[str, Any]:
    """Line count, master sum over EVERY row (adjustment rows listed), per-line agreement with the
    baseline and, when given, precision/recall against hand-transcribed lines.

    ``verdict`` is FAIL when the master sum moves more than ``MASTER_SUM_TOLERANCE`` rupees from the
    baseline, or when a ground-truth line is missing or an extra line was invented; PASS otherwise.
    """
    rows = _rows(items)
    total = round(sum(amount for _, amount, _ in rows), 2)
    adjustments = [{"item": item.get("item_name") or item.get("item"), "amount": amount}
                   for _, amount, item in rows if item.get("is_reconciled_bill_adjustment") or item.get("line_kind") not in (None, "line_item")]
    out: Dict[str, Any] = {"lines": len(rows), "master_sum": total, "adjustment_rows": adjustments, "verdict": "PASS", "reasons": []}
    if baseline_items is not None:
        base = _rows(baseline_items)
        base_total = round(sum(amount for _, amount, _ in base), 2)
        matched, extra, missing = _match_lines(rows, base)
        out.update({"baseline_lines": len(base), "baseline_master_sum": base_total, "sum_delta": round(total - base_total, 2),
                    "lines_matched": matched, "lines_extra": extra[:10], "lines_missing": missing[:10]})
        if abs(total - base_total) > MASTER_SUM_TOLERANCE:
            out["verdict"] = "FAIL"
            out["reasons"].append(f"master sum moved {round(total - base_total, 2)} vs baseline")
    if gt_lines is not None:
        reference = _rows(gt_lines)
        matched, extra, missing = _match_lines(rows, reference)
        precision = matched / len(rows) if rows else 0.0
        recall = matched / len(reference) if reference else 0.0
        out.update({"gt_lines": len(reference), "gt_matched": matched, "gt_precision": round(precision, 3),
                    "gt_recall": round(recall, 3), "gt_extra": extra[:10], "gt_missing": missing[:10]})
        if missing:
            out["verdict"] = "FAIL"
            out["reasons"].append(f"{len(missing)} ground-truth lines missing")
        if extra:
            out["verdict"] = "FAIL"
            out["reasons"].append(f"{len(extra)} lines not in the ground truth")
    return out


# ---------------------------------------------------------------------------
# Stability and the switch rule.
# ---------------------------------------------------------------------------

def cell_is_dead(claim_rows: List[Dict[str, Any]]) -> bool:
    """A cell that read fewer than half of a claim's documents in every repeat is no candidate; the
    remaining claims would only repeat the failure (Nova 2 Lite spent 12 minutes a claim on a malformed
    tool call for the native schema, 2026-10-14). One good repeat keeps the cell."""
    rows = [row for row in claim_rows if row.get("kind") == "claim"]
    return bool(rows) and all(int(row.get("succeeded") or 0) * 2 < int(row.get("documents") or 0) for row in rows)


# Classification: a page whose confirmed type carries one of these is a key page; moving it to another
# type is a serious move (a bill read as a prescription loses the money; a discharge summary read as
# a case sheet loses the dates). A human key-page file per claim, where it exists, replaces this rule.
KEY_PAGE_TYPE_MARKERS = ("bill", "discharge", "claim_form", "claim form", "pre_auth", "preauth", "case_sheet")


def _get(doc: Any, key: str) -> Any:
    return doc.get(key) if isinstance(doc, dict) else getattr(doc, key, None)


def page_types(docs: Iterable[Any]) -> Dict[Tuple[str, int], str]:
    """``{(source uuid, page number): document type}`` of classified documents (dicts or models)."""
    out: Dict[Tuple[str, int], str] = {}
    for doc in docs:
        source = str(_get(doc, "source_document_uuid") or "")
        for page in _get(doc, "page_numbers") or []:
            out[(source, int(page))] = str(_get(doc, "document_type") or "")
    return out


def score_classification(candidate_docs: Iterable[Any], confirmed_docs: Iterable[Any],
                         key_pages: Optional[Iterable[Tuple[str, int]]] = None) -> Dict[str, Any]:
    """Page agreement of a candidate classification with the confirmed one, over the sources the
    candidate classified: ``pct_agree``, every moved page, and the serious moves (key pages by the
    human file when given, else by ``KEY_PAGE_TYPE_MARKERS`` on the confirmed type)."""
    candidate = page_types(candidate_docs)
    confirmed = page_types(confirmed_docs)
    sources = {source for source, _ in candidate}
    pages = sorted(key for key in confirmed if key[0] in sources)
    moved = [{"source": source, "page": page, "confirmed": confirmed[(source, page)],
              "candidate": candidate.get((source, page))}
             for source, page in pages if candidate.get((source, page)) != confirmed[(source, page)]]
    if key_pages is not None:
        keys = {(str(source), int(page)) for source, page in key_pages}
        serious = [move for move in moved if (move["source"], move["page"]) in keys]
    else:
        serious = [move for move in moved
                   if any(marker in move["confirmed"].lower() for marker in KEY_PAGE_TYPE_MARKERS)]
    agreed = len(pages) - len(moved)
    return {
        "pages": len(pages), "agreed": agreed,
        "pct_agree": round(100.0 * agreed / len(pages), 1) if pages else None,
        "moves": len(moved), "moved": moved[:60], "serious_moves": len(serious), "serious": serious[:20],
        "serious_pages": [[move["source"], move["page"]] for move in serious],
        "extra_pages": sum(1 for key in candidate if key not in confirmed),
        "docs_candidate": sum(1 for _ in candidate_docs) if not hasattr(candidate_docs, "__len__") else len(candidate_docs),  # type: ignore[arg-type]
        "docs_confirmed": sum(1 for doc in confirmed_docs if str(_get(doc, "source_document_uuid") or "") in sources),
    }


def headline(row: Dict[str, Any]) -> Any:
    """The one value whose change makes a run 'different': the bill sum, the lost-core set, the serious
    page moves, the decision. The percentage metrics are left out on purpose: they swing a few points
    between two runs of the same model (Kimi 58.7 vs 57.0 on one claim, 2026-10-14), and a claim is
    unstable only when the model changes its answer, not its wording."""
    if "master_sum" in row:
        return row.get("master_sum")
    if "decision" in row:
        return (row.get("decision"), row.get("amount"))
    if "pct_agree" in row:
        return tuple(sorted(map(tuple, row.get("serious_pages") or ())))
    return tuple(sorted(row.get("lost_core") or ()))


def _union(rows: List[Dict[str, Any]], cell: str, claim: str, key: str) -> set:
    """Every value under ``key`` the cell produced for the claim across its repeats (its own noise band)."""
    out: set = set()
    for row in rows:
        if row.get("cell") == cell and row.get("claim_id") == claim and not row.get("error"):
            out.update(tuple(value) if isinstance(value, list) else value for value in (row.get(key) or []))
    return out


def stability(rows: List[Dict[str, Any]], *, baseline: str) -> Dict[str, Any]:
    """Per claim: unstable when the baseline's repeats disagree on the headline, or a candidate's
    repeats disagree with each other. Returns ``{stable: [...], unstable: {claim: why}}``."""
    by_claim_cell: Dict[Tuple[str, str], List[Any]] = defaultdict(list)
    for row in rows:
        if row.get("error"):
            continue
        by_claim_cell[(row["claim_id"], row["cell"])].append(headline(row))
    unstable: Dict[str, str] = {}
    claims = sorted({claim for claim, _ in by_claim_cell})
    for claim in claims:
        base = by_claim_cell.get((claim, baseline)) or []
        if len(set(map(repr, base))) > 1:
            unstable[claim] = "baseline repeats disagree"
            continue
        for (c, cell), values in by_claim_cell.items():
            if c == claim and cell != baseline and len(set(map(repr, values))) > 1:
                unstable[claim] = f"{cell} repeats disagree"
                break
    return {"stable": [claim for claim in claims if claim not in unstable], "unstable": unstable}


def _claim_metric(rows: List[Dict[str, Any]], cell: str, claim: str, key: str, *, lowest: bool = False) -> Optional[float]:
    values = [float(row[key]) for row in rows if row.get("cell") == cell and row.get("claim_id") == claim
              and row.get(key) is not None and not row.get("error")]
    if not values:
        return None
    return min(values) if lowest else statistics.mean(values)


def decide(rows: List[Dict[str, Any]], *, baseline: str, slot_kind: str) -> Dict[str, Dict[str, Any]]:
    """Per candidate cell: ``{quality, cost, tat, switch, reasons}`` under the written rule.

    ``slot_kind`` is ``"extraction"`` (doc read, bills), ``"classification"`` or ``"judgment"``.
    Extraction: on every stable claim no core field lost that the baseline itself keeps (the stored
    output the rows are compared with was made by the full pipeline, so the baseline model loses a
    few fields against it too; only a loss the baseline never makes counts), ``pct_same`` not below
    the baseline's lowest repeat, bill verdict PASS. Classification: no serious page move the baseline
    never makes, ``pct_agree`` not below the baseline's lowest repeat. Judgment: no WORSE module
    verdict and the headline equal to the baseline on every stable claim. Then cost per claim below
    the baseline's and wall seconds per claim within ``TAT_NOISE_SECONDS`` of the baseline's.
    """
    stable = stability(rows, baseline=baseline)
    cells = sorted({row["cell"] for row in rows if row["cell"] != baseline})
    out: Dict[str, Dict[str, Any]] = {"_stability": stable}
    claims = stable["stable"]
    for cell in cells:
        reasons: List[str] = []
        if len(claims) < MIN_STABLE_CLAIMS:
            reasons.append(f"only {len(claims)} stable claims (need {MIN_STABLE_CLAIMS})")
        quality_ok = True
        for claim in claims:
            cand = [row for row in rows if row.get("cell") == cell and row.get("claim_id") == claim]
            base = [row for row in rows if row.get("cell") == baseline and row.get("claim_id") == claim]
            if not cand or any(row.get("error") for row in cand):
                quality_ok = False
                reasons.append(f"{claim}: candidate failed or missing")
                continue
            if slot_kind == "extraction":
                new_lost = _union(rows, cell, claim, "lost_core") - _union(rows, baseline, claim, "lost_core")
                if new_lost:
                    quality_ok = False
                    reasons.append(f"{claim}: lost core fields the baseline keeps {sorted(new_lost)}")
                if any(row.get("verdict") == "FAIL" for row in cand):
                    quality_ok = False
                    reasons.append(f"{claim}: bill verdict FAIL")
                floor = _claim_metric(rows, baseline, claim, "pct_same", lowest=True)
                got = _claim_metric(rows, cell, claim, "pct_same")
                if floor is not None and got is not None and got < floor:
                    quality_ok = False
                    reasons.append(f"{claim}: pct_same {got:.1f} below the baseline's lowest repeat {floor:.1f}")
            elif slot_kind == "classification":
                new_serious = _union(rows, cell, claim, "serious_pages") - _union(rows, baseline, claim, "serious_pages")
                if new_serious:
                    quality_ok = False
                    reasons.append(f"{claim}: serious page move(s) the baseline never makes "
                                   f"{sorted(page for _, page in new_serious)}")
                floor = _claim_metric(rows, baseline, claim, "pct_agree", lowest=True)
                got = _claim_metric(rows, cell, claim, "pct_agree")
                if floor is not None and got is not None and got < floor:
                    quality_ok = False
                    reasons.append(f"{claim}: page agreement {got:.1f} below the baseline's lowest repeat {floor:.1f}")
            else:
                # The stored result the verdict is against was made by an earlier run of today's model,
                # so the baseline cell is often WORSE against it too (intake on the AP claims, 2026-10-14);
                # only a WORSE the baseline never gets on that claim counts.
                base_worse = any(row.get("module_verdict") == "WORSE" for row in base)
                if any(row.get("module_verdict") == "WORSE" for row in cand) and not base_worse:
                    quality_ok = False
                    reasons.append(f"{claim}: module verdict WORSE where the baseline is not")
                if base and headline(cand[0]) != headline(base[0]):
                    quality_ok = False
                    reasons.append(f"{claim}: headline {headline(cand[0])} != baseline {headline(base[0])}")
        cost_cand = statistics.mean([v for v in (_claim_metric(rows, cell, c, "cost_usd") for c in claims) if v is not None] or [0])
        cost_base = statistics.mean([v for v in (_claim_metric(rows, baseline, c, "cost_usd") for c in claims) if v is not None] or [0])
        tat_cand = statistics.mean([v for v in (_claim_metric(rows, cell, c, "wall_seconds") for c in claims) if v is not None] or [0])
        tat_base = statistics.mean([v for v in (_claim_metric(rows, baseline, c, "wall_seconds") for c in claims) if v is not None] or [0])
        cost_ok = cost_cand < cost_base
        tat_ok = tat_cand <= tat_base + TAT_NOISE_SECONDS
        if not cost_ok:
            reasons.append(f"cost {cost_cand:.3f} not below baseline {cost_base:.3f}")
        if not tat_ok:
            reasons.append(f"wall {tat_cand:.0f}s above baseline {tat_base:.0f}s + {TAT_NOISE_SECONDS:.0f}s noise")
        out[cell] = {
            "quality": quality_ok, "cost_per_claim": round(cost_cand, 4), "baseline_cost_per_claim": round(cost_base, 4),
            "wall_per_claim": round(tat_cand, 1), "baseline_wall_per_claim": round(tat_base, 1),
            "switch": bool(quality_ok and cost_ok and tat_ok and len(claims) >= MIN_STABLE_CLAIMS),
            "reasons": reasons,
        }
    return out
