"""The claim workflow as a LangGraph StateGraph, checkpointed to SQLite so a paused claim resumes after a restart.

    load_record -> [classification_gate] -> run_checks -> assess -> settle -> [review_gate -> settle ...] -> done

`classification_gate` and `review_gate` call `interrupt()`: the graph pauses, the UI acts (confirm page types /
review findings) and the API resumes the thread (thread_id = claim_id) with `Command(resume=...)`. Every node
start / end / pause is recorded in the `runs` collection, which the UI polls.
"""
from __future__ import annotations

import functools
import logging
import sqlite3
import threading
import uuid
from typing import Any, Callable, Dict, List, Optional, TypedDict

from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.errors import GraphInterrupt
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph
from langgraph.types import Command, interrupt

from core.checks import recalculate_settlement, run_checks
from core.schemas.finding import AmountKind, Finding, FindingStatus
from core.schemas.master import MasterRecord

from backend.master import build_master_record, history_index
from backend.settings import get_settings
from backend.store import Repository, get_store, now_iso, to_doc

logger = logging.getLogger(__name__)


class ClaimState(TypedDict, total=False):
    claim_id: str
    record: Dict[str, Any]
    findings: List[Dict[str, Any]]
    settlement: Optional[Dict[str, Any]]
    needs_classification_review: bool
    review_pending: bool
    run_id: str
    cost_usd: float
    errors: List[str]


# ----------------------------------------------------------------------------------------------- run progress


def _run_update(run_id: Optional[str], **fields: Any) -> None:
    if not run_id:
        return
    store = get_store()
    run = store.get(collection="runs", doc_id=run_id)
    if run is None:
        return
    run.update(fields)
    store.upsert(collection="runs", doc_id=run_id, doc=run)


def _step_start(run_id: Optional[str], name: str) -> None:
    if not run_id:
        return
    store = get_store()
    run = store.get(collection="runs", doc_id=run_id)
    if run is None:
        return
    steps = run.setdefault("steps", [])
    last = steps[-1] if steps else None
    if last and last["name"] == name and last["status"] == "paused":
        last.update({"status": "running", "resumed": now_iso()})
    else:
        steps.append({"name": name, "status": "running", "started": now_iso(), "ended": None})
    run["status"] = "running"
    store.upsert(collection="runs", doc_id=run_id, doc=run)


def _step_end(run_id: Optional[str], name: str, status: str, error: Optional[str] = None) -> None:
    if not run_id:
        return
    store = get_store()
    run = store.get(collection="runs", doc_id=run_id)
    if run is None:
        return
    for step in reversed(run.get("steps", [])):
        if step["name"] == name:
            step["status"] = status
            step["ended"] = None if status == "paused" else now_iso()
            if error:
                step["error"] = error
            break
    if status == "paused":
        run.update({"status": "paused", "paused_at": name})
    elif status == "failed":
        run.update({"status": "failed", "error": error, "ended": now_iso()})
    store.upsert(collection="runs", doc_id=run_id, doc=run)


def tracked(name: str) -> Callable[[Callable[[ClaimState], dict]], Callable[[ClaimState], dict]]:
    """Node decorator: records start / done / paused / failed on the run document."""
    def wrap(fn: Callable[[ClaimState], dict]) -> Callable[[ClaimState], dict]:
        @functools.wraps(fn)
        def inner(state: ClaimState) -> dict:
            run_id = state.get("run_id")
            _step_start(run_id=run_id, name=name)
            try:
                out = fn(state)
            except GraphInterrupt:
                _step_end(run_id=run_id, name=name, status="paused")
                raise
            except Exception as exc:
                logger.exception("node failed", extra={"node": name, "claim_id": state.get("claim_id")})
                _step_end(run_id=run_id, name=name, status="failed", error=str(exc))
                raise
            _step_end(run_id=run_id, name=name, status="done")
            return out
        return inner
    return wrap


# ----------------------------------------------------------------------------------------------- nodes


def _set_claim_status(store: Repository, claim_id: str, status: str) -> None:
    claim = store.get(collection="claims", doc_id=claim_id)
    if claim is not None:
        claim["status"] = status
        store.upsert(collection="claims", doc_id=claim_id, doc=claim)


def _stored_findings(store: Repository, claim_id: str) -> List[Finding]:
    return [Finding.model_validate(doc) for doc in store.list(collection="findings", filter_={"claim_id": claim_id})]


def _persist_findings(store: Repository, findings: List[Finding]) -> List[Dict[str, Any]]:
    docs = [to_doc(finding) for finding in findings]
    for doc in docs:
        store.upsert(collection="findings", doc_id=doc["finding_id"], doc=doc)
    return docs


@tracked("load_record")
def load_record(state: ClaimState) -> dict:
    store = get_store()
    record = build_master_record(store=store, claim_id=state["claim_id"])
    if record is None:
        raise ValueError(f"claim {state['claim_id']} is not in the store")
    needs_review = bool(record.documents) and any(doc_id not in record.document_types for doc_id in record.documents)
    return {"record": to_doc(record), "needs_classification_review": needs_review, "errors": []}


@tracked("classification_gate")
def classification_gate(state: ClaimState) -> dict:
    record = state["record"]
    unconfirmed = [doc_id for doc_id in record.get("documents", []) if doc_id not in record.get("document_types", {})]
    interrupt({"type": "classification_review", "claim_id": state["claim_id"], "documents": unconfirmed,
               "resume_with": "POST /claims/{id}/classification/confirm"})
    # The confirm endpoint stored the page types before resuming; reload the record with them.
    refreshed = build_master_record(store=get_store(), claim_id=state["claim_id"])
    return {"record": to_doc(refreshed), "needs_classification_review": False}


@tracked("run_checks")
def run_checks_node(state: ClaimState) -> dict:
    store = get_store()
    record = MasterRecord.model_validate(state["record"])
    findings = run_checks(record, history_index(store=store))
    store.delete_where(collection="findings", filter_={"claim_id": record.claim.claim_id}, id_field="finding_id")
    docs = _persist_findings(store=store, findings=findings)
    _set_claim_status(store=store, claim_id=record.claim.claim_id, status="checked")
    logger.info("checks done", extra={"claim_id": record.claim.claim_id, "findings": len(findings)})
    return {"findings": docs}


@tracked("assess")
def assess(state: ClaimState) -> dict:
    """Auto-triage: calculated findings at or under the product threshold are applied without a reviewer."""
    store = get_store()
    record = MasterRecord.model_validate(state["record"])
    threshold = record.product.auto_triage_threshold if record.product else 0.0
    findings = [Finding.model_validate(doc) for doc in state.get("findings", [])]
    for finding in findings:
        if (finding.status == FindingStatus.OPEN and finding.amount_kind == AmountKind.CALCULATED
                and finding.amount <= threshold):
            finding.status = FindingStatus.AUTO_APPLIED
    docs = _persist_findings(store=store, findings=findings)
    return {"findings": docs, "review_pending": any(f.status == FindingStatus.OPEN for f in findings)}


@tracked("settle")
def settle(state: ClaimState) -> dict:
    store = get_store()
    record = MasterRecord.model_validate(state["record"])
    findings = _stored_findings(store=store, claim_id=record.claim.claim_id)  # reviews land in the store
    settlement = recalculate_settlement(record, findings)
    store.upsert(collection="settlements", doc_id=record.claim.claim_id, doc=to_doc(settlement))
    pending = any(f.status == FindingStatus.OPEN for f in findings)
    return {"findings": [to_doc(f) for f in findings], "settlement": to_doc(settlement), "review_pending": pending}


@tracked("review_gate")
def review_gate(state: ClaimState) -> dict:
    open_ids = [doc["finding_id"] for doc in state.get("findings", []) if doc.get("status") == FindingStatus.OPEN.value]
    interrupt({"type": "findings_review", "claim_id": state["claim_id"], "open_findings": open_ids,
               "resume_with": "POST /claims/{id}/findings/{fid}/review"})
    findings = _stored_findings(store=get_store(), claim_id=state["claim_id"])
    return {"findings": [to_doc(f) for f in findings],
            "review_pending": any(f.status == FindingStatus.OPEN for f in findings)}


@tracked("done")
def done(state: ClaimState) -> dict:
    store = get_store()
    _set_claim_status(store=store, claim_id=state["claim_id"], status="settled")
    return {"review_pending": False}


def _after_load(state: ClaimState) -> str:
    return "classification_gate" if state.get("needs_classification_review") else "run_checks"


def _after_settle(state: ClaimState) -> str:
    return "review_gate" if state.get("review_pending") else "done"


# ----------------------------------------------------------------------------------------------- graph


def build_graph(checkpointer: Optional[SqliteSaver] = None) -> CompiledStateGraph:
    builder = StateGraph(ClaimState)
    builder.add_node("load_record", load_record)
    builder.add_node("classification_gate", classification_gate)
    builder.add_node("run_checks", run_checks_node)
    builder.add_node("assess", assess)
    builder.add_node("settle", settle)
    builder.add_node("review_gate", review_gate)
    builder.add_node("done", done)
    builder.add_edge(START, "load_record")
    builder.add_conditional_edges("load_record", _after_load, ["classification_gate", "run_checks"])
    builder.add_edge("classification_gate", "run_checks")
    builder.add_edge("run_checks", "assess")
    builder.add_edge("assess", "settle")
    builder.add_conditional_edges("settle", _after_settle, ["review_gate", "done"])
    builder.add_edge("review_gate", "settle")
    builder.add_edge("done", END)
    return builder.compile(checkpointer=checkpointer)


_graph: Optional[CompiledStateGraph] = None
_graph_lock = threading.Lock()
_claim_locks: Dict[str, threading.Lock] = {}


def get_graph() -> CompiledStateGraph:
    """The compiled graph with its SQLite checkpointer under DATA_DIR (built once per process)."""
    global _graph
    with _graph_lock:
        if _graph is None:
            root = get_settings().data_dir_abs
            root.mkdir(parents=True, exist_ok=True)
            conn = sqlite3.connect(str(root / "checkpoints.sqlite"), check_same_thread=False)
            _graph = build_graph(checkpointer=SqliteSaver(conn))
        return _graph


def reset_graph() -> None:
    global _graph
    with _graph_lock:
        _graph = None
        _claim_locks.clear()


def _claim_lock(claim_id: str) -> threading.Lock:
    with _graph_lock:
        return _claim_locks.setdefault(claim_id, threading.Lock())


def _config(claim_id: str) -> dict:
    return {"configurable": {"thread_id": claim_id}}


def paused_at(claim_id: str) -> Optional[str]:
    """Name of the node the claim's thread is paused on, or None when nothing is pending."""
    snapshot = get_graph().get_state(_config(claim_id))
    if not snapshot.next:
        return None
    for task in snapshot.tasks:
        if task.interrupts:
            return task.name
    return snapshot.next[0]


def latest_run(store: Repository, claim_id: str) -> Optional[Dict[str, Any]]:
    runs = store.list(collection="runs", filter_={"claim_id": claim_id})
    runs.sort(key=lambda run: run.get("started", ""), reverse=True)
    return runs[0] if runs else None


def _invoke(payload: Any, claim_id: str, run_id: str) -> None:
    graph = get_graph()
    config = _config(claim_id)
    with _claim_lock(claim_id):
        try:
            graph.invoke(payload, config=config)
        except Exception as exc:
            _run_update(run_id, status="failed", error=str(exc), ended=now_iso())
            return
        snapshot = graph.get_state(config)
        cost = float(snapshot.values.get("cost_usd", 0.0) or 0.0)
        if snapshot.next:
            _run_update(run_id, status="paused", cost_usd=cost)
        else:
            _run_update(run_id, status="completed", cost_usd=cost, ended=now_iso(), paused_at=None)


def create_run(claim_id: str) -> str:
    store = get_store()
    if store.get(collection="claims", doc_id=claim_id) is None:
        raise KeyError(claim_id)
    run_id = f"RUN-{uuid.uuid4().hex[:10]}"
    store.upsert(collection="runs", doc_id=run_id,
                 doc={"run_id": run_id, "claim_id": claim_id, "status": "queued", "steps": [], "cost_usd": 0.0,
                      "cost_cap_usd": get_settings().cost_cap_usd_per_claim, "started": now_iso(), "ended": None,
                      "paused_at": None, "error": None})
    return run_id


def execute_run(claim_id: str, run_id: str) -> None:
    """Run the graph from the start for this claim (a fresh run supersedes any paused one)."""
    initial = ClaimState(claim_id=claim_id, record={}, findings=[], settlement=None, needs_classification_review=False,
                         review_pending=False, run_id=run_id, cost_usd=0.0, errors=[])
    _invoke(payload=initial, claim_id=claim_id, run_id=run_id)


def start_run(claim_id: str, background: bool = False) -> str:
    """Create a run and execute it, inline or on a worker thread; returns the run id."""
    run_id = create_run(claim_id=claim_id)
    if background:
        threading.Thread(target=execute_run, kwargs={"claim_id": claim_id, "run_id": run_id}, daemon=True).start()
    else:
        execute_run(claim_id=claim_id, run_id=run_id)
    return run_id


def resume_run(claim_id: str, payload: Any, background: bool = False) -> Optional[str]:
    """Resume a paused thread with the reviewer's payload; returns the run id, or None when nothing was paused."""
    graph = get_graph()
    snapshot = graph.get_state(_config(claim_id))
    if not snapshot.next:
        return None
    run_id = snapshot.values.get("run_id") or create_run(claim_id=claim_id)
    _run_update(run_id, status="running")
    command = Command(resume=payload)
    if background:
        threading.Thread(target=_invoke, kwargs={"payload": command, "claim_id": claim_id, "run_id": run_id}, daemon=True).start()
    else:
        _invoke(payload=command, claim_id=claim_id, run_id=run_id)
    return run_id
