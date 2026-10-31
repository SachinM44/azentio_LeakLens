"""Level 2: corrections, review actions, notes, related claims, document comparison, report, eval scoping.

Run from the repo root:  .venv/Scripts/python.exe -m pytest tests/test_level2.py -q
"""
from __future__ import annotations

import json
import os
from datetime import date
from pathlib import Path
from typing import Any, Dict, Iterator

import pytest
from fastapi.testclient import TestClient

from core.checks import run_checks
from core.schemas.finding import (AmountKind, CheckCategory, CheckId, Correction, Finding, FindingStatus, Severity)
from core.schemas.master import Claim, ClaimType
from tests.test_checks import record

REPO = Path(__file__).resolve().parent.parent
FIXTURES = REPO / "backend" / "fixtures"
API_KEY = "test-key"
HEADERS = {"X-API-Key": API_KEY}
CLAIM = "CLM-2026-0003"


@pytest.fixture(scope="module")
def client(tmp_path_factory: pytest.TempPathFactory) -> Iterator[TestClient]:
    os.environ["DATA_DIR"] = str(tmp_path_factory.mktemp("store_l2"))
    os.environ["DOCUMENTS_MANIFEST_PATH"] = str(tmp_path_factory.mktemp("no_manifest") / "documents_manifest.json")
    os.environ["LEAKLENS_API_KEY"] = API_KEY
    os.environ["MONGODB_URI"] = ""
    os.environ["DOCUMENTS_OFFLINE"] = "1"
    os.environ["INVESTIGATOR_ENABLED"] = "0"
    os.environ["IMPORT_DATASET_DOCUMENTS"] = "0"
    from backend import graph, settings, store
    from backend.main import create_app

    settings.reset_settings()
    store.reset_store()
    graph.reset_graph()
    with TestClient(create_app()) as test_client:
        files = [("files", (name, (FIXTURES / name).read_bytes()))
                 for name in ["products.json", "policies.json", "claims.csv", "invoice_lines.csv", "history.csv"]]
        assert test_client.post("/ingest", files=files, headers=HEADERS).status_code == 200
        yield test_client
    graph.reset_graph()
    store.reset_store()
    settings.reset_settings()


def _store():
    from backend.store import get_store
    return get_store()


def _put_finding(finding_id: str, amount: float = 1000.0, kind: AmountKind = AmountKind.CALCULATED,
                 recommendation: str | None = None) -> Finding:
    finding = Finding(finding_id=finding_id, claim_id=CLAIM, check_id=CheckId.ROOM_LIMIT_EXCEEDED,
                      category=CheckCategory.POLICY_RULE, severity=Severity.MEDIUM, amount=amount, amount_kind=kind,
                      currency="INR", rule_id="ROOM-01", rule_text="Room rent limited per day",
                      recommendation=recommendation,
                      correction=Correction(action="cap_room", label="Cap the room charge at the daily limit",
                                            original_amount=5000.0, corrected_amount=5000.0 - amount, delta=amount,
                                            basis="lines", calculation="", rule_id="ROOM-01", rule_text="", clause_id="3.1"))
    _store().upsert(collection="findings", doc_id=finding_id, doc=finding.model_dump(mode="json"))
    return finding


def _review(client: TestClient, finding_id: str, body: Dict[str, Any], analyst: str | None = None):
    headers = {**HEADERS, **({"X-Analyst": analyst} if analyst else {})}
    return client.post(f"/claims/{CLAIM}/findings/{finding_id}/review", json=body, headers=headers)


# ----------------------------------------------------------------------------------------------- corrections


def test_every_finding_gets_a_correction_and_the_room_line_is_capped() -> None:
    findings = run_checks(record(), {})
    assert all(f.correction is not None for f in findings)
    room = next(f for f in findings if f.check_id == CheckId.ROOM_LIMIT_EXCEEDED)
    assert (room.correction.action, room.correction.original_amount, room.correction.corrected_amount,
            room.correction.delta, room.correction.basis) == ("cap_room", 15000.0, 9000.0, 6000.0, "lines")
    rec = record()
    rec.policy = None
    missing = next(f for f in run_checks(rec, {}) if f.check_id == CheckId.MISSING_EVIDENCE)
    assert missing.correction.action == "request_documents" and missing.correction.delta == 0.0


def test_effective_amount_for_escalated_and_accepted_correction() -> None:
    base = Finding(finding_id="x", claim_id="c", check_id=CheckId.ROOM_LIMIT_EXCEEDED, category=CheckCategory.POLICY_RULE,
                   severity=Severity.LOW, amount=600.0, amount_kind=AmountKind.SUSPECTED, currency="INR", rule_id="r",
                   rule_text="t", correction=Correction(action="cap_room", label="l", original_amount=1000, corrected_amount=500,
                                                        delta=500, basis="lines"))
    base.status = FindingStatus.ESCALATED
    assert base.effective_amount == 0.0  # escalated = open: a suspected amount does not count yet
    base.status = FindingStatus.CORRECTION_ACCEPTED
    assert base.effective_amount == 500.0


# ----------------------------------------------------------------------------------------------- review actions


def test_review_actions_validation_and_original_snapshot(client: TestClient) -> None:
    fid = f"{CLAIM}:ROOM_LIMIT_EXCEEDED:91"
    _put_finding(finding_id=fid, recommendation="confirm")
    bad = _review(client, fid, {"action": "false_positive"})
    assert bad.status_code == 400
    assert bad.json() == {"detail": "A reason is required to mark a finding as a false positive"}
    assert _review(client, fid, {"action": "escalate", "escalate_to": "manager"}).status_code == 400

    escalated = _review(client, fid, {"action": "escalate", "escalate_to": "siu", "reason": "linked claimants"}, analyst="Priya N")
    assert escalated.status_code == 200, escalated.text
    finding = escalated.json()["finding"]
    assert finding["status"] == "escalated" and finding["escalated_to"] == "siu" and finding["decided_by"] == "Priya N"
    assert finding["original"]["status"] == "open" and finding["original"]["amount"] == 1000.0
    assert finding["original"]["correction"]["delta"] == 1000.0
    captured = finding["original"]["captured_at"]
    rows = client.get(f"/claims?status=escalated", headers=HEADERS).json()
    assert any(row["claim_id"] == CLAIM and row["status"] == "escalated" for row in rows)
    assert client.get("/dashboard", headers=HEADERS).json()["awaiting_review"] >= 1

    accepted = _review(client, fid, {"action": "accept_correction"}, analyst="Ravi K").json()["finding"]
    assert accepted["status"] == "correction_accepted" and accepted["escalated_to"] is None
    assert accepted["original"]["captured_at"] == captured and accepted["original"]["status"] == "open"
    assert [h["to_status"] for h in accepted["decision_history"]] == ["escalated", "correction_accepted"]
    assert [h["by"] for h in accepted["decision_history"]] == ["Priya N", "Ravi K"]

    assert _review(client, fid, {"action": "correct", "amount": 700}).status_code == 400  # no reason
    corrected = _review(client, fid, {"action": "correct", "amount": 700, "reason": "two days"}).json()
    assert corrected["finding"]["status"] == "corrected" and corrected["finding"]["corrected_amount"] == 700.0
    assert any(d["finding_id"] == fid and d["amount"] == 700.0 for d in corrected["settlement"]["deductions"])
    fp = _review(client, fid, {"action": "false_positive", "reason": "room upgrade was approved"}).json()["finding"]
    assert fp["status"] == "dismissed" and fp["decision_reason"] == "room upgrade was approved"
    assert _review(client, fid, {"action": "request_evidence"}).json()["finding"]["status"] == "clarification_requested"
    assert _review(client, fid, {"action": "confirm"}).json()["finding"]["status"] == "confirmed"

    audit = client.get(f"/audit?claim_id={CLAIM}", headers=HEADERS).json()
    mine = [row for row in audit if row["details"].get("finding_id") == fid]
    by_action = {row["action"]: row for row in mine}
    assert by_action["review_escalate"]["actor"] == "Priya N" and by_action["review_accept_correction"]["actor"] == "Ravi K"
    assert "original" in by_action["review_escalate"]["details"]
    assert "original" not in by_action["review_accept_correction"]["details"]
    assert by_action["review_false_positive"]["details"]["overrides_recommendation"] is True
    assert by_action["review_correct"]["details"]["overrides_recommendation"] is True  # 700 vs the recommended 1,000
    assert by_action["review_accept_correction"]["details"]["overrides_recommendation"] is False


def test_legacy_actions_still_work(client: TestClient) -> None:
    fid = f"{CLAIM}:ROOM_LIMIT_EXCEEDED:92"
    _put_finding(finding_id=fid)
    assert _review(client, fid, {"action": "dismiss"}).json()["finding"]["status"] == "dismissed"
    assert _review(client, fid, {"action": "clarify"}).json()["finding"]["status"] == "clarification_requested"
    assert _review(client, fid, {"action": "nonsense"}).status_code == 422


# ----------------------------------------------------------------------------------------------- notes / workspace


def test_notes_and_policy_terms(client: TestClient) -> None:
    first = client.post(f"/claims/{CLAIM}/notes", json={"text": "Called the hospital"}, headers={**HEADERS, "X-Analyst": "Priya N"})
    assert first.status_code == 200 and first.json()["author"] == "Priya N"
    client.post(f"/claims/{CLAIM}/notes", json={"text": "Bill confirmed"}, headers=HEADERS)
    detail = client.get(f"/claims/{CLAIM}", headers=HEADERS).json()
    assert [note["text"] for note in detail["notes"]][:2] == ["Bill confirmed", "Called the hospital"]
    assert set(detail["notes"][0]) == {"note_id", "claim_id", "author", "ts", "text"}
    terms = {term["term"] for term in detail["policy_terms"]}
    assert {"Annual limit", "Room rent per day", "Copay inpatient", "Deductible", "Network", "Non-payable items"} <= terms
    audit = client.get(f"/audit?claim_id={CLAIM}", headers=HEADERS).json()
    assert any(row["action"] == "note_added" and row["actor"] == "Priya N" for row in audit)


# ----------------------------------------------------------------------------------------------- related claims


def _claim(claim_id: str, policy: str, member: str, invoice: str, phone: str | None = None) -> None:
    claim = Claim(claim_id=claim_id, policy_number=policy, product_id="IN-HEALTH-RETAIL", claimant_id=member,
                  claimant_name="Test Member", provider_id="PRV-T-1", provider_name="Test Hospital",
                  claim_type=ClaimType.OUTPATIENT, incident_date=date(2026, 6, 1), requested_amount=1000, currency="INR",
                  invoice_numbers=[invoice], contact_phone=phone)
    _store().upsert(collection="claims", doc_id=claim_id, doc=claim.model_dump(mode="json"))


def test_related_claims_by_invoice_and_shared_phone(client: TestClient) -> None:
    _claim("CLM-T-0101", policy="POL-T-A", member="M-T-1", invoice="INV-DUP-1")
    _claim("CLM-T-0102", policy="POL-T-B", member="M-T-2", invoice="INV-DUP-1")
    _claim("CLM-T-0103", policy="POL-T-A", member="M-T-3", invoice="INV-T-3", phone="+91 90000 11111")
    _claim("CLM-T-0104", policy="POL-T-B", member="M-T-4", invoice="INV-T-4", phone="+91 90000 11111")
    link = Finding(finding_id="CLM-T-0101:DUPLICATE_CLAIM:1", claim_id="CLM-T-0101", check_id=CheckId.DUPLICATE_CLAIM,
                   category=CheckCategory.DUPLICATE, severity=Severity.HIGH, amount=1000, amount_kind=AmountKind.CALCULATED,
                   currency="INR", rule_id="DUP", rule_text="t", related_claim_ids=["CLM-T-0102"])
    _store().upsert(collection="findings", doc_id=link.finding_id, doc=link.model_dump(mode="json"))

    body = client.get("/claims/CLM-T-0101/related", headers=HEADERS).json()
    row = next(r for r in body["related"] if r["claim_id"] == "CLM-T-0102")
    assert row["strength"] == "strong" and row["source"] == "claim"
    assert row["matches"][0] == {"attribute": "invoice_number", "label": "Same invoice number", "value": "INV-DUP-1"}
    assert row["finding_ids"] == ["CLM-T-0101:DUPLICATE_CLAIM:1"]

    phone = client.get("/claims/CLM-T-0103/related", headers=HEADERS).json()["related"]
    assert phone[0]["claim_id"] == "CLM-T-0104" and phone[0]["strength"] == "strong"
    assert phone[0]["matches"][0]["attribute"] == "phone" and phone[0]["matches"][0]["value"] == "****1111"


# ----------------------------------------------------------------------------------------------- comparison


def test_comparison_without_and_with_extraction(client: TestClient) -> None:
    before = client.get(f"/claims/{CLAIM}/comparison", headers=HEADERS).json()
    assert before["extracted"] is False and all(f["status"] == "not_read" for f in before["fields"])
    claim = client.get(f"/claims/{CLAIM}", headers=HEADERS).json()
    lines = claim["lines"]
    document_lines = [{**line, "document_id": "DOC-T-1", "page": 1} for line in lines]
    document_lines.append({"line_id": "doc:extra", "claim_id": CLAIM, "invoice_no": "X", "serial_no": 99, "description": "Attendant charges",
                           "amount": 1200.0, "quantity": 1, "document_id": "DOC-T-1", "page": 2})
    _store().upsert(collection="digitisations", doc_id=CLAIM, doc={
        "claim_id": CLAIM, "document_facts": {"claimant_name": claim["claim"]["claimant_name"], "policy_number": "POL-WRONG-9"},
        "document_fact_sources": {"policy_number": {"document_id": "DOC-T-1", "document_name": "bill.pdf", "page": 1}},
        "document_lines": document_lines, "printed_total": None, "reconciled": None, "extracted_by": "ai-text",
        "extracted_at": "2026-10-31T10:00:00Z", "model": "test-model", "read_seconds": 1.5})
    body = client.get(f"/claims/{CLAIM}/comparison", headers=HEADERS).json()
    fields = {f["field"]: f for f in body["fields"]}
    assert body["extracted"] is True and body["extracted_by"] == "ai-text"
    assert fields["claimant_name"]["status"] == "match"
    assert fields["policy_number"]["status"] == "mismatch" and fields["policy_number"]["source"]["page"] == 1
    assert body["summary"]["fields_mismatched"] == 1
    assert body["summary"]["lines_matched"] == len(lines) and body["summary"]["lines_only_in_document"] == 1
    extra = next(l for l in body["lines"] if l["status"] == "only_in_document")
    assert extra["description"] == "Attendant charges" and extra["source"]["page"] == 2
    assert body["summary"]["total_difference"] == -1200.0


# ----------------------------------------------------------------------------------------------- report / eval


def test_report_json_and_html(client: TestClient) -> None:
    response = client.get(f"/claims/{CLAIM}/report?format=json", headers={**HEADERS, "X-Analyst": "Priya N"})
    assert response.status_code == 200
    assert f'investigation_{CLAIM}.json' in response.headers["content-disposition"]
    report = response.json()
    assert {"generated_at", "generated_by", "claim", "policy_terms", "settlement", "findings", "related", "comparison",
            "notes", "audit"} <= set(report)
    assert report["generated_by"] == "Priya N"
    assert {"proposed", "recalculated", "difference", "steps"} <= set(report["settlement"])
    assert any(f.get("decision_history") for f in report["findings"])
    page = client.get(f"/claims/{CLAIM}/report?format=html", headers=HEADERS)
    assert page.status_code == 200 and page.headers["content-type"].startswith("text/html") and CLAIM in page.text
    assert client.get(f"/claims/{CLAIM}/report?format=pdf", headers=HEADERS).status_code == 422


def test_eval_scores_every_synthetic_claim_but_not_portal_claims(client: TestClient, tmp_path: Path) -> None:
    from backend import eval_summary

    key = tmp_path / "answer_key.json"
    key.write_text(json.dumps({"positives": [{"claim_id": CLAIM, "check_id": "ROOM_LIMIT_EXCEEDED", "amount": 1000}],
                               "negatives": []}), encoding="utf-8")
    result = eval_summary.summary(store=_store(), key_path=key)
    assert result["available"] is True
    assert not any(row.get("claim_id", "").startswith("CLM-T-") for row in result["look_alikes_wrongly_flagged"])
    # a finding on a claim outside the key is a false alarm (strict scoring) ...
    assert result["by_check"]["DUPLICATE_CLAIM"]["fp"] == 1
    # ... but a claim submitted through the customer portal has no ground truth and is not scored
    store = _store()
    store.upsert(collection="findings", doc_id="CLM-P-0099:ROOM_LIMIT_EXCEEDED:1",
                 doc={"finding_id": "CLM-P-0099:ROOM_LIMIT_EXCEEDED:1", "claim_id": "CLM-P-0099",
                      "check_id": "ROOM_LIMIT_EXCEEDED", "status": "open", "amount": 5.0, "amount_kind": "calculated"})
    again = eval_summary.summary(store=store, key_path=key)
    assert again["by_check"]["ROOM_LIMIT_EXCEEDED"]["fp"] == result["by_check"]["ROOM_LIMIT_EXCEEDED"]["fp"]
    store.delete(collection="findings", doc_id="CLM-P-0099:ROOM_LIMIT_EXCEEDED:1")
