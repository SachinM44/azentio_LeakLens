"""The checks on a hand-built claim: each planted issue is found with the exact amount, the legitimate repeat is not."""
from __future__ import annotations

from datetime import date, datetime

from core.checks import recalculate_settlement, run_checks
from core.schemas.finding import AmountKind, CheckId
from core.schemas.master import (Claim, ClaimType, Copay, Deductible, Exclusion, HistoryRecord, InvoiceLine,
                                 MasterRecord, Policy, ProductConfig, Sublimit)

CUR = "INR"


def line(claim_id: str, n: int, desc: str, qty: float, rate: float, day: str, code: str | None = None,
         amount: float | None = None, category: str | None = None) -> InvoiceLine:
    return InvoiceLine(line_id=f"{claim_id}:INV-1:{n}", claim_id=claim_id, invoice_no="INV-1", serial_no=n,
                       service_date=date.fromisoformat(day), code=code, description=desc, quantity=qty, unit_price=rate,
                       amount=amount if amount is not None else round(qty * rate, 2), provider_id="P-001",
                       category=category)


def product() -> ProductConfig:
    return ProductConfig(product_id="IN-HEALTH-RETAIL", name="Retail health", insurer="Sahara Health Assurance", market="IN",
                         currency=CUR, non_payable_items=["surgical gloves", "admission kit", "thermometer"],
                         repeatable_service_codes=["PHY001"], auto_triage_threshold=5000,
                         required_documents={"inpatient": ["itemized_final_hospital_bill", "discharge_summary"]})


def policy() -> Policy:
    return Policy(policy_number="POL-1", product_id="IN-HEALTH-RETAIL", holder_id="M-1", members=["M-1"],
                  start_date=date(2026, 1, 1), end_date=date(2026, 12, 31), currency=CUR, annual_limit=300000,
                  deductible=Deductible(amount=0), copay=Copay(inpatient_pct=10), room_rent_limit_per_day=3000,
                  icu_limit_per_day=6000, waiting_period_days=30,
                  sublimits=[Sublimit(sublimit_id="CATARACT", name="Cataract", limit=40000, basis="per_claim",
                                      keywords=["cataract", "phaco"], clause_id="5.2")],
                  exclusions=[Exclusion(exclusion_id="DENTAL", text="Dental treatment is excluded.", keywords=["dental", "tooth"],
                                        clause_id="7.4")])


def record() -> MasterRecord:
    cid = "CLM-1"
    claim = Claim(claim_id=cid, policy_number="POL-1", product_id="IN-HEALTH-RETAIL", claimant_id="M-1",
                  claimant_name="Asha Rao", provider_id="P-001", provider_name="Meridian Care Hospital",
                  claim_type=ClaimType.INPATIENT, incident_date=date(2026, 5, 10), admission_date=date(2026, 5, 10),
                  discharge_date=date(2026, 5, 13), diagnosis="Acute appendicitis", requested_amount=0, currency=CUR,
                  invoice_numbers=["INV-1"], submitted_at=datetime(2026, 5, 20, 10, 0))
    lines = [
        line(cid, 1, "Room rent - single AC", 3, 5000, "2026-05-10", code="RM001", category="room"),   # 2,000 x 3 = 6,000
        line(cid, 2, "Complete Blood Count", 1, 450, "2026-05-10", code="LAB-CBC"),
        line(cid, 3, "Complete Blood Count", 1, 450, "2026-05-10", code="LAB-CBC"),                     # duplicate 450
        line(cid, 4, "Surgical gloves 7.5", 4, 60, "2026-05-11"),                                        # non-payable 240
        line(cid, 5, "Appendectomy surgeon fee", 1, 35000, "2026-05-11", code="SUR-APP"),
        line(cid, 6, "Physiotherapy session", 1, 800, "2026-05-11", code="PHY001"),
        line(cid, 7, "Physiotherapy session", 1, 800, "2026-05-12", code="PHY001"),                     # legitimate repeat
        line(cid, 8, "Dental scaling", 1, 1500, "2026-05-12"),                                           # excluded 1,500
        line(cid, 9, "Nursing charges per day", 3, 700, "2026-05-10", amount=2600),                      # arithmetic +500
    ]
    claim.requested_amount = round(sum(l.amount for l in lines), 2)
    # proposed settlement ignores the copay
    claim.proposed_settlement = None
    return MasterRecord(claim=claim, lines=lines, policy=policy(), product=product(),
                        history=[HistoryRecord(claim_id="CLM-0", policy_number="POL-1", claimant_id="M-1", provider_id="P-001",
                                               incident_date=date(2026, 2, 1), invoice_numbers=["INV-0"], requested_amount=20000,
                                               approved_amount=18000, paid_amount=18000, paid_on=date(2026, 2, 20))])


def by_check(findings):
    out = {}
    for f in findings:
        out.setdefault(f.check_id, []).append(f)
    return out


def test_planted_issues_are_found_with_exact_amounts():
    rec = record()
    findings = run_checks(rec, {})
    got = by_check(findings)
    assert [f.amount for f in got[CheckId.ROOM_LIMIT_EXCEEDED]] == [6000.0]
    assert got[CheckId.ROOM_LIMIT_EXCEEDED][0].amount_kind == AmountKind.CALCULATED
    assert "x 3 day(s) = INR 6,000.00" in got[CheckId.ROOM_LIMIT_EXCEEDED][0].calculation
    assert [f.amount for f in got[CheckId.DUPLICATE_LINE]] == [450.0]
    assert [f.amount for f in got[CheckId.NON_PAYABLE_ITEM]] == [240.0]
    assert [f.amount for f in got[CheckId.EXCLUDED_SERVICE]] == [1500.0]
    assert got[CheckId.EXCLUDED_SERVICE][0].clause.clause_id == "7.4"
    assert [f.amount for f in got[CheckId.ARITHMETIC_MISMATCH]] == [500.0]
    assert CheckId.NEAR_DUPLICATE not in got, "physio sessions on different dates are legitimate"
    assert all(f.finding_id.startswith("CLM-1:") for f in findings)


def test_settlement_applies_deductions_then_copay_and_flags_missing_copay():
    rec = record()
    findings = run_checks(rec, {})
    settlement = recalculate_settlement(rec, findings)
    deducted = sum(d.amount for d in settlement.deductions)
    assert deducted == 6000 + 450 + 240 + 1500 + 500
    assert settlement.after_deductions == settlement.lines_total - deducted
    assert settlement.copay_amount == round(settlement.after_deductions * 0.10, 2)
    assert settlement.payable == round(settlement.after_deductions - settlement.copay_amount, 2)

    rec.claim.proposed_settlement = settlement.after_deductions  # the handler forgot the copay
    findings2 = run_checks(rec, {})
    got = by_check(findings2)
    assert [f.amount for f in got[CheckId.COPAY_NOT_APPLIED]] == [settlement.copay_amount]


def test_dismissing_a_finding_moves_the_money_back():
    rec = record()
    findings = run_checks(rec, {})
    before = recalculate_settlement(rec, findings).payable
    room = next(f for f in findings if f.check_id == CheckId.ROOM_LIMIT_EXCEEDED)
    room.status = "dismissed"
    after = recalculate_settlement(rec, findings).payable
    assert round(after - before, 2) == round(6000 * 0.9, 2)


def test_duplicate_claim_against_history_and_other_claims():
    rec = record()
    rec.claim.invoice_numbers = ["INV-0"]  # the invoice already paid under CLM-0
    history = {"CLM-0": rec.history[0]}
    got = by_check(run_checks(rec, history))
    dup = got[CheckId.DUPLICATE_CLAIM][0]
    assert dup.amount == 18000.0 and dup.related_claim_ids == ["CLM-0"]


def test_missing_policy_requests_clarification():
    rec = record()
    rec.policy = None
    got = by_check(run_checks(rec, {}))
    assert got[CheckId.MISSING_EVIDENCE][0].amount == 0.0
    assert "policy" in got[CheckId.MISSING_EVIDENCE][0].reason
