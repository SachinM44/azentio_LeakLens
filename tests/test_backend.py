"""Backend tests against the local JSON store and the fixture data under backend/fixtures.

Run from the repo root:  .venv/Scripts/python.exe -m pytest tests/test_backend.py -q
The tests share one store (module scope) and run top to bottom: ingest first, then the reads and the workflow.
"""
from __future__ import annotations

import importlib.util
import os
import time
from pathlib import Path
from typing import Any, Dict, Iterator, List

import pytest
from fastapi.testclient import TestClient

REPO = Path(__file__).resolve().parent.parent
FIXTURES = REPO / "backend" / "fixtures"
API_KEY = "test-key"
HEADERS = {"X-API-Key": API_KEY}
REAL_SETTLEMENT_ENGINE = importlib.util.find_spec("core.checks.settlement") is not None
REAL_CHECKS_ENGINE = importlib.util.find_spec("core.checks.runner") is not None


def _settle_identity(settlement: Dict[str, Any]) -> None:
    """payable = lines - deductions - deductible - copay - benefit cap, whichever engine produced it."""
    deductions = sum(d["amount"] for d in settlement["deductions"])
    expected = settlement["lines_total"] - deductions - settlement["deductible_amount"] - settlement["copay_amount"] - settlement["benefit_cap_applied"]
    assert abs(settlement["payable"] - expected) < 0.01, settlement


def _dismiss_open_findings(client: TestClient, claim_id: str) -> int:
    detail = client.get(f"/claims/{claim_id}", headers=HEADERS).json()
    open_ids = [f["finding_id"] for f in detail["findings"] if f["status"] == "open"]
    for fid in open_ids:
        response = client.post(f"/claims/{claim_id}/findings/{fid}/review", json={"action": "dismiss", "note": "test"}, headers=HEADERS)
        assert response.status_code == 200, response.text
    return len(open_ids)


def _write_manifest(folder: Path) -> Path:
    """A documents manifest for CLM-2026-0004: one rendered bill (file on disk) and one listed-only claim form."""
    import json

    pdf_dir = folder / "documents" / "CLM-2026-0004"
    pdf_dir.mkdir(parents=True)
    (pdf_dir / "CLM-2026-0004_bill.pdf").write_bytes(_synthetic_pdf(["Itemised bill (synthetic)", "NET PAYABLE 32,000.00"]))
    manifest = {"seed": 1, "documents_root": str(folder), "claims": [{
        "claim_id": "CLM-2026-0004", "claim_type": "daycare", "product_id": "IN-HEALTH-RETAIL",
        "required_documents": ["claim_form", "itemized_final_hospital_bill", "discharge_summary"],
        "required_documents_present": ["claim_form", "itemized_final_hospital_bill"], "missing_documents": ["discharge_summary"],
        "documents": [{"document_id": "DOC-CLM-2026-0004-01", "document_type": "claim_form", "file": None, "rendered": False, "pages": None},
                      {"document_id": "DOC-CLM-2026-0004-02", "document_type": "itemized_final_hospital_bill",
                       "file": "documents/CLM-2026-0004/CLM-2026-0004_bill.pdf", "rendered": True, "pages": 1, "format": "pdf"}],
        "document_facts": {"claimant_name": "Rohan Verma", "policy_number": "POL-IN-0001", "provider_name": "Sunrise Multispeciality Hospital",
                           "admission_date": "2026-06-02", "discharge_date": None, "invoice_no": "INV-4001", "net_payable": "32,000.00"}}]}
    path = folder / "documents_manifest.json"
    path.write_text(json.dumps(manifest), encoding="utf-8")
    return path


@pytest.fixture(scope="module")
def client(tmp_path_factory: pytest.TempPathFactory) -> Iterator[TestClient]:
    os.environ["DATA_DIR"] = str(tmp_path_factory.mktemp("store"))
    os.environ["DOCUMENTS_MANIFEST_PATH"] = str(_write_manifest(tmp_path_factory.mktemp("synthetic")))
    os.environ["LEAKLENS_API_KEY"] = API_KEY
    os.environ["MONGODB_URI"] = ""
    os.environ["DOCUMENTS_OFFLINE"] = "1"  # document models answer from the (empty) cache: no network, no spend
    os.environ["INVESTIGATOR_ENABLED"] = "0"  # the agent is exercised through a patched investigate() below
    os.environ["IMPORT_DATASET_DOCUMENTS"] = "1"  # these tests cover the dataset's document files being attached
    from backend import graph, settings, store
    from backend.main import create_app

    settings.reset_settings()
    store.reset_store()
    graph.reset_graph()
    with TestClient(create_app()) as test_client:
        yield test_client
    graph.reset_graph()
    store.reset_store()
    settings.reset_settings()


def _upload(names: List[str]) -> List[tuple]:
    return [("files", (name, (FIXTURES / name).read_bytes())) for name in names]


def _wait_run(client: TestClient, claim_id: str, statuses: tuple, timeout: float = 15.0) -> Dict[str, Any]:
    deadline = time.time() + timeout
    while time.time() < deadline:
        run = client.get(f"/claims/{claim_id}/run", headers=HEADERS).json()
        if run["status"] in statuses:
            return run
        time.sleep(0.05)
    raise AssertionError(f"run for {claim_id} did not reach {statuses}: {run}")


def _synthetic_pdf(lines: List[str]) -> bytes:
    import pymupdf

    doc = pymupdf.open()
    page = doc.new_page()
    for index, line in enumerate(lines):
        page.insert_text((72, 72 + 18 * index), line, fontsize=11)
    data = doc.tobytes()
    doc.close()
    return data


# ----------------------------------------------------------------------------------------------- auth / health


def test_health_is_public_and_everything_else_needs_the_key(client: TestClient) -> None:
    assert client.get("/health").json()["status"] == "ok"
    assert client.get("/claims").status_code == 401
    assert client.get("/claims", headers={"X-API-Key": "wrong"}).status_code == 401
    assert client.get("/claims", headers=HEADERS).status_code == 200


# ----------------------------------------------------------------------------------------------- ingest


def test_ingest_fixture_counts_and_validation_report(client: TestClient) -> None:
    files = _upload(["products.json", "policies.json", "claims.csv", "invoice_lines.csv", "history.csv",
                     "CLM-2026-0001_bill.pdf", "broken_claims.csv"])
    response = client.post("/ingest", files=files, headers=HEADERS)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["batch_id"].startswith("BATCH-")
    # documents: the uploaded bill for 0001 + the rendered bill the manifest lists for 0004, pulled in at ingest
    assert body["counts"] == {"products": 2, "policies": 2, "claims": 4, "invoice_lines": 20, "history": 3, "documents": 2}
    assert body["claims_created"] == 4  # 3 clean + the valid row of broken_claims.csv
    rejected = [issue for issue in body["validation"] if not issue["accepted"]]
    assert len(rejected) == 1
    assert rejected[0]["file"] == "broken_claims.csv" and rejected[0]["row"] == 3
    assert rejected[0]["field"] == "requested_amount"
    uploaded = next(doc for doc in body["documents"] if doc["name"] == "CLM-2026-0001_bill.pdf")
    assert uploaded["claim_id"] == "CLM-2026-0001" and uploaded["pages"] == 2
    imported = next(doc for doc in body["documents"] if doc["name"] == "CLM-2026-0004_bill.pdf")
    assert imported["claim_id"] == "CLM-2026-0004" and imported["pages"] == 1
    # the broken row was reported, not stored
    assert client.get("/claims/CLM-2026-0005", headers=HEADERS).status_code == 404
    assert client.get("/claims/CLM-2026-0004", headers=HEADERS).status_code == 200


def test_ingest_rejects_unknown_table_and_unsupported_type(client: TestClient) -> None:
    files = [("files", ("mystery.csv", b"foo,bar\n1,2\n")), ("files", ("notes.txt", b"hello"))]
    body = client.post("/ingest", files=files, headers=HEADERS).json()
    problems = {issue["file"]: issue["problem"] for issue in body["validation"]}
    assert "could not tell which table" in problems["mystery.csv"]
    assert "unsupported file type" in problems["notes.txt"]
    assert body["counts"] == {}


# ----------------------------------------------------------------------------------------------- list / detail


def test_claim_list_and_filters(client: TestClient) -> None:
    rows = client.get("/claims", headers=HEADERS).json()
    assert {row["claim_id"] for row in rows} == {"CLM-2026-0001", "CLM-2026-0002", "CLM-2026-0003", "CLM-2026-0004"}
    first = next(row for row in rows if row["claim_id"] == "CLM-2026-0001")
    assert first["claimant"] == "AV" and first["provider"] == "Sunrise Multispeciality Hospital"
    assert first["leakage_calculated"] == 0 and first["leakage_suspected"] == 0 and first["severity"] is None
    assert [r["claim_id"] for r in client.get("/claims?type=outpatient", headers=HEADERS).json()] == ["CLM-2026-0002"]
    assert len(client.get("/claims?provider=PRV-IN-01", headers=HEADERS).json()) == 2
    assert len(client.get("/claims?min_amount=50000", headers=HEADERS).json()) == 2
    assert len(client.get("/claims?from=2026-05-01&to=2026-05-31", headers=HEADERS).json()) == 1
    assert client.get("/claims?category=duplicate", headers=HEADERS).json() == []


def test_manifest_documents_feed_the_master_record(client: TestClient) -> None:
    """The synthetic manifest binds every submitted document (rendered or not) and the header facts to the claim."""
    from backend.store import get_store

    detail = client.get("/claims/CLM-2026-0004", headers=HEADERS).json()
    assert [doc["name"] for doc in detail["documents"]] == ["CLM-2026-0004_bill.pdf"]
    assert detail["documents"][0]["type"] == "itemized_final_hospital_bill" and detail["documents"][0]["confirmed"] is False
    assert detail["document_facts"] == {"claimant_name": "Rohan Verma", "policy_number": "POL-IN-0001",
                                        "provider_name": "Sunrise Multispeciality Hospital", "admission_date": "2026-06-02",
                                        "invoice_no": "INV-4001", "net_payable": "32,000.00"}  # null discharge_date dropped
    assert detail["printed_total"] == 32000.0 and detail["reconciled"] is False  # fixture has no lines for 0004: 0 != 32,000
    assert detail["claim"]["source"] == "mixed"
    master = get_store().get(collection="master_records", doc_id="CLM-2026-0004")
    stored_id = detail["documents"][0]["id"]
    assert master["documents"] == [stored_id, "DOC-CLM-2026-0004-01"]  # stored file first, then the listed-only claim form
    assert master["document_types"] == {stored_id: "itemized_final_hospital_bill", "DOC-CLM-2026-0004-01": "claim_form"}
    # re-ingesting the claim does not import the file twice
    body = client.post("/ingest", files=_upload(["claims.csv", "broken_claims.csv"]), headers=HEADERS).json()
    assert body["counts"].get("documents", 0) == 0 and body["claims_created"] == 0
    assert len(client.get("/claims/CLM-2026-0004", headers=HEADERS).json()["documents"]) == 1


def test_claim_detail_shape(client: TestClient) -> None:
    detail = client.get("/claims/CLM-2026-0001", headers=HEADERS).json()
    assert set(detail) >= {"claim", "policy", "lines", "documents", "classification", "findings", "settlement", "audit", "run"}
    assert detail["policy"]["policy_number"] == "POL-IN-0001"
    assert len(detail["lines"]) == 10 and detail["lines"][0]["serial_no"] == 1
    assert detail["documents"][0]["name"] == "CLM-2026-0001_bill.pdf" and detail["documents"][0]["type"] is None
    assert [row["page"] for row in detail["classification"]] == [1, 2]
    assert detail["classification"][0]["predicted_type"] == "itemized_final_hospital_bill"
    assert detail["claim"]["source"] == "mixed"
    assert detail["settlement"] is None and detail["findings"] == []


# ----------------------------------------------------------------------------------------------- workflow


def test_run_completes_and_settlement_equals_lines_total(client: TestClient) -> None:
    response = client.post("/claims/CLM-2026-0003/run", headers=HEADERS)
    assert response.status_code == 200 and response.json()["run_id"].startswith("RUN-")
    run = _wait_run(client, "CLM-2026-0003", ("paused", "completed", "failed"))
    if run["status"] == "paused":  # a checks engine that flags this clean claim: review everything, then it completes
        assert run["paused_at"] == "review_gate"
        _dismiss_open_findings(client, "CLM-2026-0003")
        run = _wait_run(client, "CLM-2026-0003", ("completed", "failed"))
    assert run["status"] == "completed", run
    assert [step["name"] for step in run["steps"]][:5] == ["load_record", "run_checks", "assess", "investigate", "settle"]
    assert run["steps"][-1]["name"] == "done" and all(step["status"] == "done" for step in run["steps"])
    detail = client.get("/claims/CLM-2026-0003", headers=HEADERS).json()
    settlement = detail["settlement"]
    assert settlement["lines_total"] == 54000.0
    _settle_identity(settlement)
    if not REAL_SETTLEMENT_ENGINE:
        assert settlement["payable"] == 54000.0 and settlement["deductions"] == []
    assert detail["claim"]["status"] == "settled"


def test_classification_gate_pauses_until_confirmed(client: TestClient) -> None:
    client.post("/claims/CLM-2026-0001/run", headers=HEADERS)
    run = _wait_run(client, "CLM-2026-0001", ("paused", "completed", "failed"))
    assert run["status"] == "paused" and run["paused_at"] == "classification_gate"
    pages = client.get("/claims/CLM-2026-0001", headers=HEADERS).json()["classification"]
    body = [{"page_id": page["page_id"], "document_type": "itemized_final_hospital_bill" if page["page"] == 1 else "discharge_summary"}
            for page in pages]
    response = client.post("/claims/CLM-2026-0001/classification/confirm", json=body, headers=HEADERS)
    assert response.status_code == 200 and response.json()["run_id"] == run["run_id"]
    confirmed = response.json()
    assert [row["confirmed_type"] for row in confirmed["classification"]] == ["itemized_final_hospital_bill", "discharge_summary"]
    # offline: the digitisation models cannot answer, the failure is reported and the structured lines stay
    assert confirmed["digitised"] is False and confirmed["digitisation_error"]
    assert confirmed["document_lines"] == 0 and confirmed["source"] == "mixed"
    assert client.get("/claims/CLM-2026-0001", headers=HEADERS).json()["claim"]["digitisation_error"]
    run = _wait_run(client, "CLM-2026-0001", ("paused", "completed", "failed"))
    names = [step["name"] for step in run["steps"]]
    assert names[:6] == ["load_record", "classification_gate", "run_checks", "assess", "investigate", "settle"]
    detail = client.get("/claims/CLM-2026-0001", headers=HEADERS).json()
    assert detail["documents"][0]["type"] == "itemized_final_hospital_bill"
    assert detail["settlement"]["lines_total"] == 86000.0
    _settle_identity(detail["settlement"])
    if REAL_CHECKS_ENGINE:  # the brief's own example is planted in the fixture: (7,000 - 5,000) x 3 days
        room = [f for f in detail["findings"] if f["check_id"] == "ROOM_LIMIT_EXCEEDED"]
        assert room and room[0]["amount"] == 6000.0 and room[0]["amount_kind"] == "calculated"
        assert run["status"] == "paused" and run["paused_at"] == "review_gate"
        assert _dismiss_open_findings(client, "CLM-2026-0001") >= 1
    run = _wait_run(client, "CLM-2026-0001", ("completed", "failed"))
    assert run["status"] == "completed" and run["steps"][-1]["name"] == "done"
    assert client.get("/claims/CLM-2026-0001", headers=HEADERS).json()["claim"]["status"] == "settled"


def test_review_gate_pauses_on_open_finding_and_resumes_after_review(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    from core.schemas.finding import AmountKind, CheckCategory, CheckId, Finding, Severity

    def fake_checks(record, history_index, **kwargs):  # type: ignore[no-untyped-def]
        assert "other_claims" in kwargs and "peer_lines" in kwargs
        assert all(c.claim_id != record.claim.claim_id for c in kwargs["other_claims"])
        assert all(line.claim_id != record.claim.claim_id for line in kwargs["peer_lines"])
        return [Finding(finding_id=f"{record.claim.claim_id}:COPAY_NOT_APPLIED:1", claim_id=record.claim.claim_id,
                        check_id=CheckId.COPAY_NOT_APPLIED, category=CheckCategory.SETTLEMENT, severity=Severity.HIGH,
                        amount=248.0, amount_kind=AmountKind.CALCULATED, currency="AED", rule_id="COPAY_OP",
                        rule_text="20% copay on outpatient visits", calculation="1240 x 20% = 248")]

    monkeypatch.setattr("backend.graph.run_checks", fake_checks)
    client.post("/claims/CLM-2026-0002/run", headers=HEADERS)
    run = _wait_run(client, "CLM-2026-0002", ("paused", "completed", "failed"))
    assert run["status"] == "paused" and run["paused_at"] == "review_gate", run
    detail = client.get("/claims/CLM-2026-0002", headers=HEADERS).json()
    assert len(detail["findings"]) == 1 and detail["findings"][0]["status"] == "open"  # 248 > auto-triage 100
    assert detail["summary"]["open_findings"] == 1
    fid = detail["findings"][0]["finding_id"]
    response = client.post(f"/claims/CLM-2026-0002/findings/{fid}/review", json={"action": "confirm", "note": "agreed"}, headers=HEADERS)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["findings"][0]["status"] == "confirmed" and body["findings"][0]["reviewer_note"] == "agreed"
    assert body["run_id"] == run["run_id"]
    run = _wait_run(client, "CLM-2026-0002", ("completed", "failed"))
    assert run["status"] == "completed"
    assert [step["name"] for step in run["steps"]][-3:] == ["review_gate", "settle", "done"]
    assert client.get("/claims/CLM-2026-0002", headers=HEADERS).json()["claim"]["status"] == "settled"


def test_review_on_manually_inserted_finding_changes_the_settlement(client: TestClient) -> None:
    from backend.store import get_store
    from core.schemas.finding import AmountKind, CheckCategory, CheckId, Finding, Severity

    finding = Finding(finding_id="CLM-2026-0003:ROOM_LIMIT_EXCEEDED:1", claim_id="CLM-2026-0003",
                      check_id=CheckId.ROOM_LIMIT_EXCEEDED, category=CheckCategory.POLICY_RULE, severity=Severity.MEDIUM,
                      amount=1000.0, amount_kind=AmountKind.CALCULATED, currency="INR", rule_id="ROOM_RENT_LIMIT",
                      rule_text="Room rent limited to 5,000 per day", calculation="(5,500 - 5,000) x 2 days = 1,000")
    baseline = client.get("/claims/CLM-2026-0003", headers=HEADERS).json()
    base_leakage = baseline["summary"]["leakage_calculated"]
    get_store().upsert(collection="findings", doc_id=finding.finding_id, doc=finding.model_dump(mode="json"))
    before = client.get("/claims/CLM-2026-0003", headers=HEADERS).json()
    assert before["summary"]["leakage_calculated"] == base_leakage + 1000.0
    bad = client.post(f"/claims/CLM-2026-0003/findings/{finding.finding_id}/review", json={"action": "correct"}, headers=HEADERS)
    assert bad.status_code == 422
    response = client.post(f"/claims/CLM-2026-0003/findings/{finding.finding_id}/review",
                           json={"action": "correct", "amount": 800, "note": "two days, not three"}, headers=HEADERS)
    assert response.status_code == 200, response.text
    body = response.json()
    reviewed = next(f for f in body["findings"] if f["finding_id"] == finding.finding_id)
    assert reviewed["status"] == "corrected" and reviewed["corrected_amount"] == 800.0
    assert body["summary"]["leakage_calculated"] == base_leakage + 800.0
    assert body["settlement"]["lines_total"] == 54000.0
    _settle_identity(body["settlement"])
    if REAL_SETTLEMENT_ENGINE:  # the corrected finding is now a deduction and the payable moved
        assert any(d["finding_id"] == finding.finding_id and d["amount"] == 800.0 for d in body["settlement"]["deductions"])
        assert body["settlement"]["payable"] < baseline["settlement"]["payable"]
    dismissed = client.post(f"/claims/CLM-2026-0003/findings/{finding.finding_id}/review",
                            json={"action": "dismiss", "note": "withdrawn"}, headers=HEADERS).json()
    assert dismissed["summary"]["leakage_calculated"] == base_leakage
    assert dismissed["settlement"]["payable"] == baseline["settlement"]["payable"]
    audit = client.get("/audit?claim_id=CLM-2026-0003", headers=HEADERS).json()
    assert [row["action"] for row in audit[:2]] == ["review_dismiss", "review_correct"]


# ----------------------------------------------------------------------------------------------- dashboard / config


def test_dashboard_counts(client: TestClient) -> None:
    board = client.get("/dashboard", headers=HEADERS).json()
    assert board["claims"] == 4 and board["processed"] == 3  # 0001, 0002, 0003 ran; 0004 did not
    assert board["flagged"] >= 1 and board["awaiting_review"] == 0  # every open finding was reviewed above
    assert board["leakage_calculated"] >= 248.0 and board["leakage_suspected"] == 0.0
    assert {"category", "count", "amount_calculated", "amount_suspected"} <= set(board["by_category"][0])
    assert any(row["check_id"] == "COPAY_NOT_APPLIED" for row in board["by_check"])
    assert any(row["severity"] == "high" for row in board["by_severity"])
    uae = next(row for row in board["by_provider"] if row["provider_id"] == "PRV-AE-01")
    assert uae["claims"] == 1 and uae["flagged"] == 1 and uae["leakage_calculated"] == 248.0
    # filters narrow every figure: only the outpatient claim carries the confirmed copay finding
    outpatient = client.get("/dashboard?type=outpatient", headers=HEADERS).json()
    assert outpatient["claims"] == 1 and outpatient["flagged"] == 1 and outpatient["leakage_calculated"] == 248.0
    assert outpatient["by_category"] == [{"category": "settlement", "count": 1, "amount_calculated": 248.0, "amount_suspected": 0.0}]
    none = client.get("/dashboard?provider=PRV-NONE", headers=HEADERS).json()
    assert none["claims"] == 0 and none["by_provider"] == [] and none["leakage_calculated"] == 0.0


def test_config_put_and_get(client: TestClient) -> None:
    config = client.get("/config/IN-HEALTH-RETAIL", headers=HEADERS).json()
    assert config["currency"] == "INR" and config["auto_triage_threshold"] == 1000.0
    config["auto_triage_threshold"] = 2500
    config["non_payable_items"].append("hand sanitiser")
    response = client.put("/config/IN-HEALTH-RETAIL", json=config, headers=HEADERS)
    assert response.status_code == 200 and response.json()["auto_triage_threshold"] == 2500.0
    again = client.get("/config/IN-HEALTH-RETAIL", headers=HEADERS).json()
    assert again["auto_triage_threshold"] == 2500.0 and "hand sanitiser" in again["non_payable_items"]
    unknown = client.get("/config/XX-UNKNOWN", headers=HEADERS).json()
    assert unknown["product_id"] == "XX-UNKNOWN" and unknown["insurer"] == "unconfigured"
    audit = client.get("/audit", headers=HEADERS).json()
    assert audit[0]["action"] == "config_update" and "auto_triage_threshold" in audit[0]["details"]["changed_fields"]


# ----------------------------------------------------------------------------------------------- documents


def test_document_upload_attach_and_stream(client: TestClient) -> None:
    pdf = _synthetic_pdf(["Discharge summary (synthetic)", "Patient O. Haddad", "Visit 2 Apr 2026"])
    png = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32
    files = [("files", ("CLM-2026-0002_discharge.pdf", pdf)), ("files", ("random_note.png", png))]
    body = client.post("/ingest", files=files, headers=HEADERS).json()
    assert body["counts"] == {"documents": 2}
    attached = next(doc for doc in body["documents"] if doc["name"] == "CLM-2026-0002_discharge.pdf")
    loose = next(doc for doc in body["documents"] if doc["name"] == "random_note.png")
    assert attached["claim_id"] == "CLM-2026-0002" and loose["claim_id"] is None
    assert any("not attached" in issue["problem"] and issue["accepted"] for issue in body["validation"])
    detail = client.get("/claims/CLM-2026-0002", headers=HEADERS).json()
    assert [doc["name"] for doc in detail["documents"]] == ["CLM-2026-0002_discharge.pdf"]
    assert detail["classification"][0]["predicted_type"] == "discharge_summary"
    streamed = client.get(f"/documents/{attached['document_id']}", headers=HEADERS)
    assert streamed.status_code == 200 and streamed.headers["content-type"] == "application/pdf"
    assert streamed.content == pdf
    assert client.get(f"/documents/{loose['document_id']}", headers=HEADERS).headers["content-type"] == "image/png"
    assert client.get("/documents/nope", headers=HEADERS).status_code == 404


def test_classify_documents_offline_reports_failure_and_keeps_rows(client: TestClient) -> None:
    response = client.post("/claims/CLM-2026-0002/documents/classify", headers=HEADERS)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["classified"] is False and body["error"] and body["cost_usd"] == 0.0
    assert body["needs_classification_review"] is True
    assert [row["predicted_type"] for row in body["classification"]] == ["discharge_summary"]  # file-name guess kept
    audit = client.get("/audit?claim_id=CLM-2026-0002", headers=HEADERS).json()
    assert audit[0]["action"] == "documents_classify" and audit[0]["details"]["error"]
    assert client.post("/claims/CLM-9999/documents/classify", headers=HEADERS).status_code == 404
    run = client.get("/claims/CLM-2026-0002/run", headers=HEADERS).json()
    assert "retrieval_mode" in run and run["cost_usd"] == 0.0


def test_investigator_recommends_on_suspected_findings_without_changing_them(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    from backend.settings import get_settings
    from core.agent.investigator import Trail, Verdict
    from core.schemas.finding import AmountKind, CheckCategory, CheckId, Finding, Severity

    def fake_checks(record, history_index, **kwargs):  # type: ignore[no-untyped-def]
        return [Finding(finding_id=f"{record.claim.claim_id}:NEAR_DUPLICATE:1", claim_id=record.claim.claim_id,
                        check_id=CheckId.NEAR_DUPLICATE, category=CheckCategory.DUPLICATE, severity=Severity.MEDIUM,
                        amount=32000.0, amount_kind=AmountKind.SUSPECTED, currency="INR", rule_id="NEAR_DUP",
                        rule_text="Same provider, amount within 2%, date within 3 days of an earlier claim",
                        related_claim_ids=["HIS-2025-0002"])]

    def fake_investigate(record, findings, *, index=None, peer_lines=None):  # type: ignore[no-untyped-def]
        assert [f.finding_id for f in findings] == ["CLM-2026-0004:NEAR_DUPLICATE:1"]
        assert peer_lines and all(line.claim_id != "CLM-2026-0004" for line in peer_lines)
        trail = Trail(steps=[{"tool": "history", "args": {"claimant_id": "MBR-0002"}, "result": "1 earlier claim, different diagnosis"}],
                      model="test-model", input_tokens=1_000_000, output_tokens=100_000)
        return [Verdict(finding_id="CLM-2026-0004:NEAR_DUPLICATE:1", recommendation="dismiss", confidence=0.8,
                        note="The earlier claim is a different episode and diagnosis.")], trail

    monkeypatch.setattr("backend.graph.run_checks", fake_checks)
    monkeypatch.setattr("backend.graph.investigate", fake_investigate)
    monkeypatch.setattr(get_settings(), "investigator_enabled", True)
    client.post("/claims/CLM-2026-0004/run", headers=HEADERS)
    run = _wait_run(client, "CLM-2026-0004", ("paused", "completed", "failed"))
    assert run["status"] == "paused" and run["paused_at"] == "review_gate", run
    assert run["investigation"]["model"] == "test-model" and run["investigation"]["verdicts"] == 1
    assert run["investigation"]["steps"][0]["tool"] == "history"
    assert run["cost_usd"] == round(0.72 + 0.36, 5)  # 1M input at $0.72/M + 100k output at $3.60/M
    finding = client.get("/claims/CLM-2026-0004", headers=HEADERS).json()["findings"][0]
    assert finding["recommendation"] == "dismiss" and finding["recommendation_confidence"] == 0.8
    assert "different episode" in finding["recommendation_note"]
    assert finding["status"] == "open" and finding["amount"] == 32000.0  # review-only: nothing decided for the human
    assert _dismiss_open_findings(client, "CLM-2026-0004") == 1
    assert _wait_run(client, "CLM-2026-0004", ("completed", "failed"))["status"] == "completed"


def test_eval_summary_reports_unavailable_without_answer_key(client: TestClient) -> None:
    body = client.get("/eval/summary", headers=HEADERS).json()
    assert body["available"] in (True, False)
    if not body["available"]:
        assert "answer_key" in body["reason"]
