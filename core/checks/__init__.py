"""The leakage checks. Every check is a pure function over a MasterRecord that returns Findings.

    from core.checks import run_checks, recalculate_settlement

run_checks(record, history_index, other_claims=None, peer_lines=None) -> list[Finding]
    history_index: claim_id -> HistoryRecord for every earlier (paid) claim in the dataset
    other_claims:  every other Claim currently ingested (duplicate-claim and related-party patterns)
    peer_lines:    every InvoiceLine in the store except this claim's (provider price benchmarking)
recalculate_settlement(record, findings) -> Settlement
"""
from __future__ import annotations

from typing import Dict, List, Optional

from core.schemas.finding import Finding
from core.schemas.master import Claim, HistoryRecord, InvoiceLine, MasterRecord
from core.schemas.settlement import Settlement

HistoryIndex = Dict[str, HistoryRecord]


def run_checks(record: MasterRecord, history_index: Optional[HistoryIndex] = None, *,
               other_claims: Optional[List[Claim]] = None, peer_lines: Optional[List[InvoiceLine]] = None) -> List[Finding]:
    try:
        from core.checks.runner import run_all
    except ImportError:  # the runner lands shortly; the API can be wired before it does
        return []
    return run_all(record=record, history_index=history_index or {}, other_claims=other_claims or [],
                   peer_lines=peer_lines or [])


def recalculate_settlement(record: MasterRecord, findings: List[Finding]) -> Settlement:
    try:
        from core.checks.settlement import recalculate
    except ImportError:
        total = round(sum(line.amount for line in record.lines), 2)
        return Settlement(claim_id=record.claim.claim_id, currency=record.claim.currency,
                          requested_amount=record.claim.requested_amount, lines_total=total,
                          after_deductions=total, payable=total, patient_pays=0.0,
                          proposed_settlement=record.claim.proposed_settlement,
                          steps=["settlement engine not loaded; lines total shown"])
    return recalculate(record=record, findings=findings)
