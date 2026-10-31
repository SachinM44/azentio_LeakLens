"""Parse JSON from model answers with a single json-repair pass on failure."""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any, Optional

logger = logging.getLogger(__name__)

try:
    from json_repair import repair_json as _repair_json
except ImportError:  # pragma: no cover - exercised when dependency missing
    _repair_json = None  # type: ignore[assignment,misc]


@dataclass(frozen=True)
class JsonParseResult:
    """Outcome of parsing JSON, optionally after a single repair pass."""

    parsed: Any
    used_repair: bool = False
    repair_error: Optional[str] = None
    original_error: Optional[str] = None


class JsonParseError(ValueError):
    """Raised when JSON cannot be parsed even after repair."""

    def __init__(
        self,
        message: str,
        *,
        used_repair: bool = False,
        repair_error: Optional[str] = None,
        original_error: Optional[str] = None,
    ) -> None:
        super().__init__(message)
        self.used_repair = used_repair
        self.repair_error = repair_error
        self.original_error = original_error


def parse_json_with_repair(
    raw: str,
    *,
    require_object_or_array: bool = True,
) -> JsonParseResult:
    """
    Parse JSON text, attempting one json-repair pass on decode failure.

    Args:
        raw: JSON string (may be malformed).
        require_object_or_array: When True, reject scalars (str/int/bool/null).

    Returns:
        JsonParseResult with parsed value and repair metadata.

    Raises:
        JsonParseError: On empty input, unrecoverable parse failure, or shape mismatch.
    """
    if raw is None or not str(raw).strip():
        raise JsonParseError("JSON input is empty")

    text = str(raw).strip()
    original_error: Optional[str] = None

    try:
        parsed = json.loads(text)
        _validate_parsed_shape(parsed, require_object_or_array=require_object_or_array)
        return JsonParseResult(parsed=parsed, used_repair=False)
    except json.JSONDecodeError as error:
        original_error = str(error)

    if _repair_json is None:
        raise JsonParseError(
            f"Invalid JSON and json-repair is not installed: {original_error}",
            original_error=original_error,
        ) from None

    repair_error: Optional[str] = None
    try:
        repaired_text = _repair_json(text)
        if not isinstance(repaired_text, str):
            repaired_text = json.dumps(repaired_text)
        repaired_text = repaired_text.strip()
        if not repaired_text:
            raise JsonParseError(
                "JSON repair produced empty output",
                used_repair=True,
                repair_error="empty output",
                original_error=original_error,
            )
        parsed = json.loads(repaired_text)
        _validate_parsed_shape(parsed, require_object_or_array=require_object_or_array)
        logger.info(
            "JSON repaired successfully before validation",
            extra={
                "json_repair_used": True,
                "json_repair_status": "success",
                "original_error": (original_error or "")[:500],
                "repaired_preview": repaired_text[:500],
            },
        )
        return JsonParseResult(
            parsed=parsed,
            used_repair=True,
            original_error=original_error,
        )
    except json.JSONDecodeError as repair_parse_error:
        repair_error = str(repair_parse_error)
    except Exception as repair_exc:  # json_repair or unexpected failures
        repair_error = str(repair_exc)

    logger.warning(
        "JSON repair failed",
        extra={
            "json_repair_used": True,
            "json_repair_status": "failed",
            "original_error": (original_error or "")[:500],
            "repair_error": (repair_error or "")[:500],
            "input_preview": text[:500],
        },
    )
    raise JsonParseError(
        f"Invalid JSON after repair attempt: {repair_error or original_error}",
        used_repair=True,
        repair_error=repair_error,
        original_error=original_error,
    ) from None


def _validate_parsed_shape(
    parsed: Any,
    *,
    require_object_or_array: bool,
) -> None:
    if not require_object_or_array:
        return
    if not isinstance(parsed, (dict, list)):
        raise JsonParseError(
            f"Parsed JSON must be an object or array, got {type(parsed).__name__}"
        )
