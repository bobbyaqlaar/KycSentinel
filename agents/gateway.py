"""
agents/gateway.py — gateway factory: real AgentSmith LLMGateway, or a
deterministic fake when KYC_FAKE_LLM=1 (RFC-002 offline mode).

The fake now subclasses the framework's shipped `runtime.testing.FakeGateway`
(added as G4 *because* of this app — see TestbedFeedback-2026-07-21). Only
the KYC-specific response scripting lives here; the CompletionResult shape,
call recording, budget simulation, and — critically — the streaming-capability
rules come from the framework.

That last point is the lesson: this app's original hand-rolled double aliased
`complete_stream` to `complete`, which made a real production crash invisible
(the analyst's Anthropic route could not stream at all, G1). A double that is
MORE capable than the real gateway hides exactly the bugs a testbed exists to
find, so the shipped double refuses to stream what the real one can't.

Response behavior is keyed off markers in the prompt so F-scenarios are
reproducible:
  - BROKEN_JSON_TRIGGER in an intake submission → invalid JSON (F2)
  - CITE_GHOST_TRIGGER in an analyst prompt   → cites a nonexistent doc (F7)
It never inspects fixture files — only the prompt it is given, like a model.
"""

from __future__ import annotations

import json
import os
import re
from typing import Optional

from . import _framework  # noqa: F401 — sys.path side effect

from runtime.testing import FakeGateway as _FrameworkFake


def fake_mode() -> bool:
    return os.environ.get("KYC_FAKE_LLM", "").strip() == "1"


class FakeGateway(_FrameworkFake):
    """KYC-specific response scripting over the framework's test double.

    `providers` mirrors this tenant's real models.yaml so the double
    enforces the same streaming rules the real gateway does — the analyst
    route is Anthropic, which the framework can now stream (G1); a route
    pointed at a cloud-native provider would fall back here exactly as it
    does in production.
    """

    def __init__(self, tenant_id: str = "kyc-sentinel") -> None:
        super().__init__(
            tenant_id=tenant_id,
            providers={
                "intake": "ollama",
                "research": "groq",
                "analyst": "anthropic",
                "judge": "anthropic",
            },
        )

    def _resolve_text(self, call) -> str:  # framework hook
        return self._script_response(call.model_hint, call.prompt)

    def _script_response(self, model_hint: str, prompt: str) -> str:
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
    from runtime.llm_gateway import LLMGateway
    return LLMGateway(tenant_id="kyc-sentinel", budget_cap_usd=budget_cap_usd)
