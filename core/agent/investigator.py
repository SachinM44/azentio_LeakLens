"""The investigator: a tool-calling agent that looks into the SUSPECTED findings of a claim (near-duplicates,
provider outliers, related parties, document mismatches) and writes a reviewer note with a recommendation.

It never changes an amount or a status. It can only call read-only tools over the master record, the member's
history, peer prices and the policy clauses, and it must end with a JSON verdict per finding:
    {"finding_id": ..., "recommendation": "confirm" | "dismiss" | "clarify", "confidence": 0..1, "note": ...}
Each tool call and its result is kept as the trail shown in the UI.
"""
from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

from pydantic import BaseModel, Field, ValidationError

from core.checks._common import norm, unit_price
from core.llm.json_parse import parse_json_with_repair
from core.prompts import load_prompt
from core.rag.policy_index import PolicyIndex
from core.schemas.finding import AmountKind, Finding
from core.schemas.master import InvoiceLine, MasterRecord

logger = logging.getLogger("leaklens.agent")
MODEL = os.environ.get("LEAKLENS_AGENT_MODEL", os.environ.get("LEAKLENS_MODEL", "bedrock/moonshotai.kimi-k2.5"))
MAX_STEPS = 8


class Verdict(BaseModel):
    finding_id: str = Field(..., description="The finding reviewed")
    recommendation: str = Field(..., description="confirm | dismiss | clarify")
    confidence: float = Field(default=0.5, ge=0.0, le=1.0, description="How sure the investigator is")
    note: str = Field(default="", description="Two or three sentences for the reviewer, citing what was checked")


class Verdicts(BaseModel):
    verdicts: List[Verdict] = Field(default_factory=list)


@dataclass
class Trail:
    steps: List[Dict[str, Any]] = field(default_factory=list)
    model: str = MODEL
    input_tokens: int = 0
    output_tokens: int = 0


def _tools(record: MasterRecord, index: Optional[PolicyIndex], peer_lines: List[InvoiceLine]) -> Dict[str, Callable[..., Any]]:
    def get_lines(query: str = "") -> List[Dict[str, Any]]:
        """Invoice lines of this claim, optionally filtered by a word in the description or code."""
        q = norm(query)
        rows = [l for l in record.lines if not q or q in norm(l.description) or (l.code and q in l.code.lower())]
        return [{"line_id": l.line_id, "date": str(l.service_date), "code": l.code, "description": l.description,
                 "qty": l.quantity, "unit_price": l.unit_price, "amount": l.amount} for l in rows[:40]]

    def get_history() -> List[Dict[str, Any]]:
        """Earlier claims of this member: dates, providers, invoices, amounts paid, and paid lines when known."""
        return [{"claim_id": h.claim_id, "incident_date": str(h.incident_date), "provider_id": h.provider_id,
                 "invoices": h.invoice_numbers, "paid": h.paid_amount,
                 "lines": [{"date": str(l.service_date), "code": l.code, "description": l.description, "amount": l.amount}
                           for l in h.lines[:30]]} for h in record.history[:20]]

    def peer_prices(description_or_code: str) -> Dict[str, Any]:
        """Unit prices other providers charge for an item (by code or description words)."""
        q = norm(description_or_code)
        prices = [unit_price(l) for l in peer_lines if l.provider_id != record.claim.provider_id and l.amount > 0
                  and (q and (q in norm(l.description) or (l.code and q == l.code.lower())))]
        prices.sort()
        if not prices:
            return {"n": 0}
        return {"n": len(prices), "min": prices[0], "median": prices[len(prices) // 2], "max": prices[-1]}

    def policy_clauses(query: str) -> List[Dict[str, Any]]:
        """The policy clauses closest to a question (clause id, text, similarity)."""
        if index is None:
            return []
        return [{"clause_id": c, "text": t, "score": s} for c, t, s in index.search(query, k=3)]

    return {"get_lines": get_lines, "get_history": get_history, "peer_prices": peer_prices, "policy_clauses": policy_clauses}


TOOL_SPECS = [
    {"type": "function", "function": {"name": "get_lines", "description": "Invoice lines of this claim, optionally filtered by a word.",
                                      "parameters": {"type": "object", "properties": {"query": {"type": "string"}}}}},
    {"type": "function", "function": {"name": "get_history", "description": "Earlier claims of this member with paid amounts and lines.",
                                      "parameters": {"type": "object", "properties": {}}}},
    {"type": "function", "function": {"name": "peer_prices", "description": "Unit prices other providers charge for an item.",
                                      "parameters": {"type": "object", "properties": {"description_or_code": {"type": "string"}},
                                                     "required": ["description_or_code"]}}},
    {"type": "function", "function": {"name": "policy_clauses", "description": "Policy clauses closest to a question.",
                                      "parameters": {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]}}},
]


def investigate(record: MasterRecord, findings: List[Finding], *, index: Optional[PolicyIndex] = None,
                peer_lines: Optional[List[InvoiceLine]] = None, model: str = MODEL) -> tuple[List[Verdict], Trail]:
    """Run the agent over the suspected findings. Returns verdicts (may be empty) and the tool trail."""
    import litellm

    suspected = [f for f in findings if f.amount_kind == AmountKind.SUSPECTED]
    trail = Trail(model=model)
    if not suspected:
        return [], trail
    tools = _tools(record, index, peer_lines or [])
    claim = record.claim
    system = (load_prompt("_preamble").text + "\n\n" + load_prompt("investigator").text)
    brief = {"claim": {"claim_id": claim.claim_id, "type": claim.claim_type.value, "provider": claim.provider_name or claim.provider_id,
                       "incident_date": str(claim.incident_date), "admission": str(claim.admission_date), "discharge": str(claim.discharge_date),
                       "diagnosis": claim.diagnosis, "requested": claim.requested_amount, "currency": claim.currency},
             "findings_to_investigate": [{"finding_id": f.finding_id, "check": f.check_id.value, "amount": f.amount, "rule": f.rule_text,
                                          "calculation": f.calculation, "reason": f.reason, "line_ids": f.line_ids,
                                          "related_claims": f.related_claim_ids} for f in suspected]}
    messages: List[Dict[str, Any]] = [{"role": "system", "content": system},
                                      {"role": "user", "content": json.dumps(brief, ensure_ascii=False)}]
    for _ in range(MAX_STEPS):
        sampling = {} if "anthropic" in model else {"temperature": 0.1}
        response = litellm.completion(model=model, messages=messages, tools=TOOL_SPECS, tool_choice="auto", max_tokens=4096,
                                      aws_region_name=os.environ.get("AWS_REGION_NAME", "ap-south-1"),
                                      timeout=180, drop_params=True, **sampling)
        usage = getattr(response, "usage", None)
        trail.input_tokens += int(getattr(usage, "prompt_tokens", 0) or 0)
        trail.output_tokens += int(getattr(usage, "completion_tokens", 0) or 0)
        message = response.choices[0].message
        calls = getattr(message, "tool_calls", None) or []
        if not calls:
            text = message.content or ""
            try:
                parsed = Verdicts.model_validate(parse_json_with_repair(text).parsed)
            except (ValidationError, ValueError, Exception) as exc:  # noqa: BLE001 - a bad final answer ends with no verdicts
                trail.steps.append({"type": "final_unparsed", "text": text[:500], "error": str(exc)[:160]})
                return [], trail
            trail.steps.append({"type": "final", "verdicts": len(parsed.verdicts)})
            return parsed.verdicts, trail
        messages.append({"role": "assistant", "content": message.content or "", "tool_calls": [c.model_dump() if hasattr(c, "model_dump") else c for c in calls]})
        for call in calls:
            name = call.function.name
            try:
                args = json.loads(call.function.arguments or "{}")
            except json.JSONDecodeError:
                args = {}
            try:
                result = tools[name](**args) if name in tools else {"error": f"unknown tool {name}"}
            except Exception as exc:  # noqa: BLE001 - a tool error is returned to the model, not raised
                result = {"error": str(exc)[:200]}
            trail.steps.append({"type": "tool", "name": name, "args": args, "result_preview": json.dumps(result, ensure_ascii=False)[:300]})
            messages.append({"role": "tool", "tool_call_id": call.id, "name": name, "content": json.dumps(result, ensure_ascii=False)[:6000]})
    trail.steps.append({"type": "stopped", "reason": f"more than {MAX_STEPS} steps"})
    return [], trail
