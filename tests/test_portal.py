"""Customer portal + automatic reading, offline: the page classifier and the bill reader are patched, so no model
is called. Run from the repo root:  .venv/Scripts/python.exe -m pytest tests/test_portal.py -q
"""
from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Any, Dict, Iterator, List

import pytest
from fastapi.testclient import TestClient

from core.documents.pipeline import DigitisedClaim, PagePrediction
from core.schemas.master import InvoiceLine

REPO = Path(__file__).resolve().parent.parent
FIXTURES = REPO / "backend" / "fixtures"
API_KEY = "test-key"
HEADERS = {"X-API-Key": API_KEY}
PDF = b"%PDF-1.4 synthetic"


def _pdf(lines: List[str]) -> bytes:
    import fitz

    doc = fitz.open()
    page = doc.new_page()
    for i, text in enumerate(lines):
        page.insert_text((72, 72 + 18 * i), text)
    data = doc.tobytes()
    doc.close()
    return data


@pytest.fixture(scope="module")
def client(tmp_path_factory: pytest.TempPathFactory) -> Iterator[TestClient]:
    os.environ["DATA_DIR"] = str(tmp_path_factory.mktemp("portal_store"))
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
        files = [("files", (path.name, path.read_bytes(), "text/csv")) for path in sorted(FIXTURES.iterdir()) if path.suffix in (".csv", ".json") and path.name != "broken_claims.csv"]
        response = test_client.post("/ingest", files=files, headers=HEADERS)
        assert response.status_code == 200, response.text
        yield test_client
    graph.reset_graph()
    store.reset_store()


def _policy_and_member() -> Dict[str, str]:
    from backend.store import get_store

    policy = next(p for p in get_store().list(collection="policies") if p.get("members"))
    return {"policy_number": policy["policy_number"], "member_id": policy["members"][0]}


def _form(**over: Any) -> Dict[str, Any]:
    base = {**_policy_and_member(), "claim_type": "inpatient", "incident_date": "2026-06-02", "admission_date": "2026-06-02",
            "discharge_date": "2026-06-04", "provider_name": "Portal Test Hospital", "amount_claimed": "12000",
            "diagnosis": "Acute gastroenteritis", "phone": "+91 90000 00000"}
    base.update(over)
    return {k: v for k, v in base.items() if v is not None}


def _fields(response) -> List[str]:
    assert response.status_code == 422, response.text
    return [p["field"] for p in response.json()["detail"]]


def test_unknown_policy_and_no_files_are_422(client: TestClient) -> None:
    response = client.post("/portal/claims", data=_form(policy_number="POL-NOPE"), headers=HEADERS)
    fields = _fields(response)
    assert "policy_number" in fields and "files" in fields


def test_member_not_covered_bad_date_bad_file_are_422(client: TestClient) -> None:
    response = client.post("/portal/claims", data=_form(member_id="M-NOT-COVERED", incident_date="02/06/2026"),
                           files=[("files", ("notes.txt", b"hello", "text/plain"))], headers=HEADERS)
    fields = _fields(response)
    assert {"member_id", "incident_date", "files"} <= set(fields)


def test_too_many_files_is_422(client: TestClient) -> None:
    files = [("files", (f"page{i}.pdf", PDF, "application/pdf")) for i in range(11)]
    assert "files" in _fields(client.post("/portal/claims", data=_form(), files=files, headers=HEADERS))


def test_portal_requires_api_key(client: TestClient) -> None:
    assert client.get("/portal/claims/CLM-P-0001").status_code == 401


def _patch_reader(monkeypatch: pytest.MonkeyPatch, confidence: float) -> None:
    from backend import documents

    def fake_classify(pages, ask, bundle_name="claim.pdf"):
        return [PagePrediction(p.source_file, p.page_in_file, i, "itemized_final_hospital_bill", confidence)
                for i, p in enumerate(pages)]

    def fake_digitise(pages, confirmed, ask, *, claim_id, provider_id=None):
        name = pages[0].source_file
        lines = [InvoiceLine(line_id=f"{claim_id}:INV-P1:{i}", claim_id=claim_id, invoice_no="INV-P1", serial_no=i,
                             description=desc, amount=amount, provider_id=provider_id, document_id=name, page=1)
                 for i, (desc, amount) in enumerate([("Room charges - general ward", 6000.0), ("Pharmacy", 4000.0),
                                                     ("Doctor visit charges", 2000.0)], start=1)]
        return DigitisedClaim(lines=lines, document_facts={"invoice_no": "INV-P1", "net_payable": "12,000.00",
                                                           "claimant_name": "Asha Rao"},
                              document_fact_sources={"invoice_no": {"document_name": name, "page": 1},
                                                     "net_payable": {"document_name": name, "page": 1},
                                                     "claimant_name": {"document_name": name, "page": 1}},
                              printed_total=12000.0, reconciled=True, extracted_by="ai-text",
                              model="bedrock/moonshotai.kimi-k2.5", read_seconds=1.5)

    monkeypatch.setattr(documents, "classify_pages", fake_classify)
    monkeypatch.setattr(documents, "digitise_documents", fake_digitise)


def _wait(client: TestClient, claim_id: str, until: set, seconds: float = 30.0) -> Dict[str, Any]:
    deadline = time.monotonic() + seconds
    body: Dict[str, Any] = {}
    while time.monotonic() < deadline:
        body = client.get(f"/portal/claims/{claim_id}", headers=HEADERS).json()
        if body["status"] in until:
            return body
        time.sleep(0.2)
    raise AssertionError(f"{claim_id} stuck at {body}")


def test_portal_claim_is_read_and_checked(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_reader(monkeypatch, confidence=0.97)
    bill = _pdf(["Itemised bill (synthetic)", "Room charges 6,000.00", "Pharmacy 4,000.00", "NET PAYABLE 12,000.00"])
    started = time.monotonic()
    response = client.post("/portal/claims", data=_form(), files=[("files", ("bill.pdf", bill, "application/pdf"))],
                           headers=HEADERS)
    assert response.status_code == 201, response.text
    assert time.monotonic() - started < 3
    body = response.json()
    assert body["claim_id"].startswith("CLM-P-") and body["status"] == "received"
    status = _wait(client, body["claim_id"], {"under_review", "settled"})
    assert status["lines_read"] == 3 and status["read_seconds"] == 1.5 and status["pages_read"] == 1
    assert status["amount_claimed"] == 12000 and "findings" not in status
    assert {s["name"]: s["status"] for s in status["steps"]}["read"] == "done"

    from backend.store import get_store

    store = get_store()
    claim = store.get(collection="claims", doc_id=body["claim_id"])
    assert claim["source"] == "documents" and claim["requested_amount"] == 12000
    lines = store.list(collection="invoice_lines", filter_={"claim_id": body["claim_id"]})
    assert sorted(l["amount"] for l in lines) == [2000.0, 4000.0, 6000.0]
    assert all(l["document_id"] and l["page"] == 1 for l in lines)
    doc = store.get(collection="digitisations", doc_id=body["claim_id"])
    for key in ("claim_id", "document_facts", "document_fact_sources", "document_lines", "printed_total", "reconciled",
                "extracted_by", "extracted_at", "model", "read_seconds"):
        assert key in doc, key
    source = doc["document_fact_sources"]["invoice_no"]
    assert source["document_name"] == "bill.pdf" and source["page"] == 1 and source["document_id"]
    assert doc["extracted_by"] == "ai-text" and doc["reconciled"] is True
    assert store.list(collection="runs", filter_={"claim_id": body["claim_id"]})


def test_low_confidence_waits_for_the_analyst(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_reader(monkeypatch, confidence=0.6)
    response = client.post("/portal/claims", data=_form(), files=[("files", ("photo.jpg", _jpeg(), "image/jpeg"))],
                           headers=HEADERS)
    assert response.status_code == 201, response.text
    status = _wait(client, response.json()["claim_id"], {"waiting_for_analyst"})
    assert status["lines_read"] == 0
    assert response.json()["claim_id"] != "CLM-P-0001"


def _jpeg() -> bytes:
    import io

    from PIL import Image

    buffer = io.BytesIO()
    Image.new("RGB", (60, 80), "white").save(buffer, format="JPEG")
    return buffer.getvalue()


def test_ai_recommendation_rows_reach_the_audit_trail(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    from types import SimpleNamespace

    from backend import graph
    from backend.store import get_store
    from core.schemas.finding import Finding

    store = get_store()
    claim_id = next(c["claim_id"] for c in store.list(collection="claims") if not c["claim_id"].startswith("CLM-P-"))
    graph.start_run(claim_id=claim_id)
    findings = store.list(collection="findings", filter_={"claim_id": claim_id})
    if not findings:
        pytest.skip("no findings on the first fixture claim")
    target = findings[0]
    target["amount_kind"] = "suspected"
    verdict = SimpleNamespace(finding_id=target["finding_id"], recommendation="request_evidence", confidence=0.8,
                              note="Ask for the itemised pharmacy bill.")
    monkeypatch.setattr(graph, "investigate", lambda *a, **k: ([verdict], SimpleNamespace(
        steps=[], model="test", input_tokens=0, output_tokens=0)))
    monkeypatch.setattr(graph, "_policy_index", lambda product_id: None)
    monkeypatch.setattr(graph.get_settings(), "investigator_enabled", True)
    record = graph.build_master_record(store=store, claim_id=claim_id)
    graph.investigate_node({"findings": [Finding.model_validate(target).model_dump(mode="json")],
                            "record": record.model_dump(mode="json"), "run_id": None, "cost_usd": 0.0})
    rows = [r for r in store.list(collection="audit", filter_={"claim_id": claim_id}) if r["action"] == "ai_recommendation"]
    assert rows and rows[0]["actor"] == "investigator"
    assert rows[0]["details"]["finding_id"] == target["finding_id"]
    assert rows[0]["details"]["recommendation"] == "request_evidence" and rows[0]["details"]["confidence"] == 0.8
