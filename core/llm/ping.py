"""Check that the keys, region and network work: one tiny call per model.

    python -m core.llm.ping            # Kimi on Bedrock, then each Gemini fallback
"""
from __future__ import annotations

from pydantic import BaseModel, Field

from core.llm.client import FALLBACK_MODELS, PRIMARY_MODEL, call_model


class PingAnswer(BaseModel):
    ok: bool = Field(default=False, description="true when the model read the payload")
    echo: str = Field(default="", description="the payload's word, copied")


def main() -> None:
    for model in [PRIMARY_MODEL] + FALLBACK_MODELS:
        try:
            result = call_model("ping", {"word": "leaklens"}, [], PingAnswer, tag="ping", model=model,
                                max_tokens=2048, timeout=60, use_fallback=False)
            print(f"OK    {model:32s} {result.seconds:5.1f}s  echo={result.parsed.echo!r}  ${result.cost_usd:.5f}")
        except Exception as exc:  # noqa: BLE001 - a check script reports every failure and goes on
            print(f"FAIL  {model:32s} {str(exc)[:300]}")


if __name__ == "__main__":
    main()
