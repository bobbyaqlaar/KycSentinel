"""
agents/gateway.py — gateway factory: real AgentSmith LLMGateway, or the
deterministic FakeGateway when KYC_FAKE_LLM=1 (RFC-002 offline mode).

FakeGateway mirrors LLMGateway.complete()'s result shape so agents are
byte-identical in both modes. Its "model behavior" is keyed off markers in
the prompt so F-scenarios are reproducible:
  - BROKEN_JSON_TRIGGER in an intake submission → invalid JSON (F2)
  - CITE_GHOST_TRIGGER in an analyst prompt   → cites a nonexistent doc (F7)
It never inspects fixture files — only the prompt it is given, like a model.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from typing import Any, Optional

from . import _framework  # noqa: F401 — sys.path side effect


@dataclass
class FakeResult:
    text: str
    model_used: str
    input_tokens: int
    output_tokens: int
    cost_usd: float
    degrade_tier: Optional[str] = None
    ttft_ms: Optional[float] = None


def fake_mode() -> bool:
    return os.environ.get("KYC_FAKE_LLM", "").strip() == "1"


class FakeGateway:
    """Deterministic stand-in for runtime/llm_gateway.LLMGateway."""

    def __init__(self, tenant_id: str = "kyc-sentinel") -> None:
        self.tenant_id = tenant_id
        self.calls: list[dict] = []

    async def complete(self, prompt: Any, model_hint: str = "developer", **kw: Any) -> FakeResult:
        text = prompt if isinstance(prompt, str) else json.dumps(prompt)
        self.calls.append({"model_hint": model_hint, "prompt": text})
        out = self._respond(model_hint, text)
        return FakeResult(
            text=out,
            model_used=f"fake-{model_hint}",
            input_tokens=max(1, len(text) // 4),
            output_tokens=max(1, len(out) // 4),
            cost_usd=0.0,
            ttft_ms=1.0,
        )

    # complete_stream shares complete()'s fake path (TTFT is faked above).
    complete_stream = complete

    def _respond(self, model_hint: str, prompt: str) -> str:
        if model_hint == "intake":
            return self._intake(prompt)
        if model_hint == "analyst":
            return self._analyst(prompt)
        if model_hint == "judge":
            return json.dumps({"critique": "rationale grounded in cited sources", "score": 0.9})
        return "ok"

    @staticmethod
    def _field(prompt: str, label: str) -> str:
        m = re.search(rf"{label}\s*[:=]\s*(.+)", prompt, re.IGNORECASE)
        return m.group(1).strip() if m else ""

    def _intake(self, prompt: str) -> str:
        if "BROKEN_JSON_TRIGGER" in prompt:
            return '{"applicant_id": "oops", "full_name": "Trunc'  # F2: malformed JSON
        profile = {
            "applicant_id": self._field(prompt, "applicant id") or "unknown",
            "full_name": self._field(prompt, "full name") or "Unknown",
            "dob": self._field(prompt, "date of birth") or "1990-01-01",
            "nationality": self._field(prompt, "nationality") or "AE",
            "company_name": self._field(prompt, "company") or "Unknown LLC",
            "role": self._field(prompt, "role") or "unknown",
            "source_of_funds": self._field(prompt, "source of funds") or None,
            "notes": "",
        }
        return json.dumps(profile)

    def _analyst(self, prompt: str) -> str:
        # Rating comes from the deterministic evidence the agent embedded in
        # the prompt (hit counts), mirroring how the real model is instructed.
        hits = int(self._field(prompt, "sanctions_hit_count") or 0)
        media = int(self._field(prompt, "adverse_media_count") or 0)
        no_sof = "source_of_funds: missing" in prompt
        rating = "HIGH" if hits else ("MEDIUM" if (media or no_sof) else "LOW")
        cited = re.findall(r"\[(policy-\d+)\]", prompt)[:2] or ["policy-001"]
        if "CITE_GHOST_TRIGGER" in prompt:
            cited = ["policy-999"]  # F7: not in the retrieved set
        rationale = (
            f"Rating {rating}: {hits} sanctions hit(s), {media} adverse media item(s)"
            + (", source of funds missing" if no_sof else "")
            + ". Basis: " + " ".join(f"[{c}]" for c in cited)
        )
        return json.dumps({"rating": rating, "rationale": rationale, "citations": cited})


def get_gateway(budget_cap_usd: Optional[float] = None):
    """Real LLMGateway unless KYC_FAKE_LLM=1. Import stays lazy so fake
    mode needs nothing from the provider stack."""
    if fake_mode():
        return FakeGateway()
    try:
        from runtime.llm_gateway import LLMGateway
    except ImportError:  # flat layout
        from llm_gateway import LLMGateway  # type: ignore

    return LLMGateway(tenant_id="kyc-sentinel", budget_cap_usd=budget_cap_usd)
