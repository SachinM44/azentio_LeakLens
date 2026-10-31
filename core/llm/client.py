"""One function for every model call: call_model().

Kimi K2.5 on AWS Bedrock (ap-south-1) through litellm, with Gemini as the fallback. Every answer is
parsed (json_repair when needed) and validated against a Pydantic schema before anyone uses it.
Guardrails here: injection preamble, schema validation with one re-ask, bounded retries with backoff,
model fallback, per-call timeout, cost meter with a per-claim cap, and a result cache so a re-run (or
a demo on bad Wi-Fi) replays the stored answer instead of calling the model again.
"""
from __future__ import annotations

import base64
import hashlib
import json
import logging
import os
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple, Type, Union

from dotenv import load_dotenv
from pydantic import BaseModel, ValidationError

from core.llm.json_parse import JsonParseError, parse_json_with_repair
from core.media.pages import image_block
from core.prompts import Prompt, load_prompt

load_dotenv(Path(__file__).resolve().parents[2] / ".env")
logger = logging.getLogger("leaklens.llm")

PRIMARY_MODEL = os.environ.get("LEAKLENS_MODEL", "bedrock/moonshotai.kimi-k2.5")
FALLBACK_MODELS = [m.strip() for m in os.environ.get(
    "LEAKLENS_FALLBACK_MODELS", "gemini-3.5-flash,gemini-3.1-pro-preview").split(",") if m.strip()]
AWS_REGION = os.environ.get("AWS_REGION_NAME", "ap-south-1")
COST_CAP_USD = float(os.environ.get("COST_CAP_USD_PER_CLAIM", "2"))
# USD per million tokens (input, output). Kimi list price; Claude via env.
# by us; set from Google's price page before quoting a Gemini cost.
PRICES: Dict[str, Tuple[float, float]] = {
    "bedrock/moonshotai.kimi-k2.5": (0.72, 3.60),
    "gemini-3.5-flash": (float(os.environ.get("GEMINI_FLASH_PRICE_IN", "0")), float(os.environ.get("GEMINI_FLASH_PRICE_OUT", "0"))),
    "gemini-3.1-pro-preview": (float(os.environ.get("GEMINI_PRO_PRICE_IN", "0")), float(os.environ.get("GEMINI_PRO_PRICE_OUT", "0"))),
}
RETRY_BACKOFF_S = (2, 8, 20)
SECRET_PATTERN = re.compile(r"AIza[0-9A-Za-z_\-]{20,}|(?:AKIA|ASIA)[0-9A-Z]{16}")
TRANSIENT_MARKERS = ("throttl", "timeout", "timed out", "rate limit", "too many requests", "429", "500", "502",
                     "503", "504", "internal server", "service unavailable", "connection", "overloaded")


class CostCapExceeded(RuntimeError):
    """The claim's model spend reached COST_CAP_USD_PER_CLAIM; no further calls are started."""


class ModelCallFailed(RuntimeError):
    """Every model (primary and fallbacks) failed or never produced a schema-valid answer."""


@dataclass
class CostMeter:
    """Spend for one claim; call_model refuses to start a call once the cap is reached."""
    cap_usd: float = COST_CAP_USD
    spent_usd: float = 0.0
    calls: int = 0
    cached_calls: int = 0

    def check(self) -> None:
        if self.spent_usd >= self.cap_usd:
            raise CostCapExceeded(f"claim spend ${self.spent_usd:.2f} reached the cap ${self.cap_usd:.2f}")

    def add(self, usd: float) -> None:
        self.spent_usd += usd
        self.calls += 1


@dataclass
class ModelResult:
    parsed: BaseModel
    raw: str
    model: str
    prompt_name: str
    prompt_version: int
    prompt_sha: str
    attempts: int
    repaired: bool
    fallback_used: bool
    cached: bool
    input_tokens: int
    output_tokens: int
    cost_usd: float
    seconds: float
    notes: List[str] = field(default_factory=list)

    def audit(self) -> Dict[str, Any]:
        """What the guardrails panel and the audit log show for this call."""
        return {k: getattr(self, k) for k in ("model", "prompt_name", "prompt_version", "prompt_sha", "attempts",
                                              "repaired", "fallback_used", "cached", "input_tokens",
                                              "output_tokens", "cost_usd", "seconds", "notes")}


def _system_text(prompt_name: str, schema: Type[BaseModel]) -> Tuple[str, Prompt]:
    preamble = load_prompt("_preamble")
    prompt = load_prompt(prompt_name)
    text = (f"{preamble.text}\n\n{prompt.text}\n\n### OUTPUT SCHEMA (JSON Schema; answer with one object of "
            f"this shape)\n{json.dumps(schema.model_json_schema(), ensure_ascii=False)}")
    return text, prompt


def _user_content(payload: Union[Dict[str, Any], str], images: Sequence[bytes],
                  labels: Optional[Sequence[str]]) -> List[dict]:
    """Payload first (JSON, or text as given), then each page image with its label, as the extraction prompts expect."""
    text = payload if isinstance(payload, str) else json.dumps(payload, ensure_ascii=False)
    content: List[dict] = [{"type": "text", "text": text}]
    for i, jpeg in enumerate(images):
        if labels:
            content.append({"type": "text", "text": labels[i]})
        content.append(image_block(jpeg))
    return content


def _cost(model: str, tokens_in: int, tokens_out: int) -> float:
    price_in, price_out = PRICES.get(model, (0.0, 0.0))
    return tokens_in * price_in / 1e6 + tokens_out * price_out / 1e6


def _redact(text: str) -> str:
    """Provider errors can echo the API key (Gemini does); keys never reach notes, logs or caches."""
    return SECRET_PATTERN.sub("[redacted-key]", text)


def _is_transient(exc: Exception) -> bool:
    code = getattr(exc, "status_code", None) or getattr(exc, "code", None)
    if isinstance(code, int):
        return code in (408, 429) or code >= 500
    text = f"{type(exc).__name__} {exc}".lower()
    return any(marker in text for marker in TRANSIENT_MARKERS)


def _call_bedrock(model: str, system: str, content: List[dict], max_tokens: int, timeout: float) -> Tuple[str, int, int]:
    import litellm  # imported on first use: litellm takes seconds to import

    response = litellm.completion(
        model=model, messages=[{"role": "system", "content": system}, {"role": "user", "content": content}],
        max_tokens=max_tokens, temperature=0.1, response_format={"type": "json_object"},
        aws_region_name=AWS_REGION, timeout=timeout, drop_params=True)
    usage = getattr(response, "usage", None)
    return (response.choices[0].message.content or "", int(getattr(usage, "prompt_tokens", 0) or 0),
            int(getattr(usage, "completion_tokens", 0) or 0))


def _call_gemini(model: str, system: str, content: List[dict], max_tokens: int, timeout: float) -> Tuple[str, int, int]:
    from google import genai
    from google.genai import types

    client = genai.Client(api_key=os.environ["GEMINI_API_KEY"],
                          http_options=types.HttpOptions(timeout=int(timeout * 1000)))
    parts = []
    for block in content:
        if block["type"] == "text":
            parts.append(types.Part.from_text(text=block["text"]))
        else:
            data = block["image_url"]["url"].split(",", 1)[1]
            parts.append(types.Part.from_bytes(data=base64.b64decode(data), mime_type="image/jpeg"))
    response = client.models.generate_content(
        model=model, contents=[types.Content(role="user", parts=parts)],
        config=types.GenerateContentConfig(system_instruction=system, temperature=0.1, max_output_tokens=max_tokens,
                                           response_mime_type="application/json"))
    usage = response.usage_metadata
    tokens_out = (getattr(usage, "candidates_token_count", 0) or 0) + (getattr(usage, "thoughts_token_count", 0) or 0)
    return response.text or "", int(getattr(usage, "prompt_token_count", 0) or 0), int(tokens_out)


def _json_text(raw: str) -> str:
    """The JSON object inside an answer that may carry code fences or a sentence around it."""
    text = raw.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else text
        text = text.rsplit("```", 1)[0]
    if not text.lstrip().startswith(("{", "[")) and "{" in text:
        text = text[text.index("{"): text.rindex("}") + 1]
    return text


def _parse(raw: str, schema: Type[BaseModel]) -> Tuple[BaseModel, bool]:
    result = parse_json_with_repair(_json_text(raw))
    value = result.parsed
    if isinstance(value, dict) and set(value) == {"error"}:
        raise ValueError(f"model answered with an error object: {str(value)[:200]}")
    return schema.model_validate(value), result.used_repair


def call_model(prompt_name: str, payload: Union[Dict[str, Any], str], images: Sequence[bytes],
               schema: Type[BaseModel], *, tag: str, cache_dir: Optional[Path] = None,
               meter: Optional[CostMeter] = None, labels: Optional[Sequence[str]] = None,
               model: str = PRIMARY_MODEL, max_tokens: int = 16384, timeout: float = 300.0,
               use_fallback: bool = True, offline: bool = False) -> ModelResult:
    """Run one prompt over a payload and page images; return a schema-valid answer or raise ModelCallFailed.

    offline=True answers from the cache only (a cache miss raises), for demos and CI without network.
    """
    system, prompt = _system_text(prompt_name, schema)
    content = _user_content(payload, images, labels)
    key = hashlib.sha256((system + json.dumps(content, ensure_ascii=False)).encode("utf-8")).hexdigest()[:16]
    cache_file = cache_dir / f"{tag}.{key}.json" if cache_dir else None
    if cache_file and cache_file.exists():
        stored = json.loads(cache_file.read_text(encoding="utf-8"))
        meta = {k: v for k, v in stored["meta"].items() if k != "cached"}
        if meter:
            meter.cached_calls += 1
        return ModelResult(parsed=schema.model_validate(stored["parsed"]), raw=stored["raw"], cached=True, **meta)
    if offline:
        raise ModelCallFailed(f"{tag}: offline and no cached answer for this exact request")

    started = time.monotonic()
    notes: List[str] = []
    attempts = 0
    for current in [model] + (FALLBACK_MODELS if use_fallback else []):
        caller = _call_gemini if current.startswith("gemini") else _call_bedrock
        turn_content = content
        reasked = False
        for backoff in (0,) + RETRY_BACKOFF_S:
            if meter:
                meter.check()
            if backoff:
                time.sleep(backoff)
            attempts += 1
            try:
                raw, tokens_in, tokens_out = caller(current, system, turn_content, max_tokens, timeout)
            except Exception as exc:  # noqa: BLE001 - transient errors retry, anything else moves to the fallback
                notes.append(_redact(f"{current}: {type(exc).__name__}: {str(exc)[:300]}"))
                if _is_transient(exc):
                    continue
                break
            cost = _cost(current, tokens_in, tokens_out)
            if meter:
                meter.add(cost)
            try:
                parsed, repaired = _parse(raw, schema)
            except (JsonParseError, ValueError, ValidationError) as exc:
                notes.append(_redact(f"{current}: answer failed the schema: {str(exc)[:200]}"))
                if not reasked:
                    reasked = True
                    turn_content = content + [{"type": "text", "text": "Your previous answer did not match the "
                                               "OUTPUT SCHEMA. Answer again with one JSON object that matches it."}]
                    continue
                break
            result = ModelResult(parsed=parsed, raw=raw, model=current, prompt_name=prompt.name,
                                 prompt_version=prompt.version, prompt_sha=prompt.sha256_12, attempts=attempts,
                                 repaired=repaired, fallback_used=current != model, cached=False,
                                 input_tokens=tokens_in, output_tokens=tokens_out, cost_usd=round(cost, 5),
                                 seconds=round(time.monotonic() - started, 2), notes=notes)
            if cache_file:
                cache_file.parent.mkdir(parents=True, exist_ok=True)
                cache_file.write_text(json.dumps({"meta": result.audit(), "parsed": parsed.model_dump(mode="json"),
                                                  "raw": raw}, ensure_ascii=False, indent=1), encoding="utf-8")
            logger.info("model call ok", extra={"tag": tag, "model": current, "attempts": attempts,
                                                "cost_usd": result.cost_usd, "seconds": result.seconds})
            return result
    raise ModelCallFailed(f"{tag}: every model failed after {attempts} attempts: {' | '.join(notes)[-600:]}")
