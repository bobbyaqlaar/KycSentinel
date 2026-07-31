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
        if model_hint == "research":
            return self._research(prompt)
        if model_hint == "analyst":
            return self._analyst(prompt)
        if model_hint == "judge":
            return json.dumps({"critique": "rationale grounded in cited sources", "score": 0.9})
        return "ok"

    @staticmethod
    def _field(prompt: str, label: str) -> str:
        m = re.search(rf"{label}\s*[:=]\s*(.+)", prompt, re.IGNORECASE)
        return m.group(1).strip() if m else ""

    def _research(self, prompt: str) -> str:
        # Deterministic one-line screening brief from the evidence the agent
        # embedded in the prompt — mirrors how the real Groq model is asked.
        hits = self._field(prompt, "sanctions_hits")
        media = self._field(prompt, "adverse_media_count") or "0"
        sof = self._field(prompt, "source_of_funds") or "unknown"
        has_hits = hits not in ("", "none", "[]", "None")
        return (
            f"Screening: {'sanctions match present' if has_hits else 'no sanctions match'}, "
            f"{media} adverse media item(s), source of funds {sof}."
        )

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
        # Cite the policies that GOVERN this rating, in corpus order.
        #
        # This used to be `re.findall(...)[:2]` — the first two policy ids by
        # position in the prompt. Positional, not semantic, and it made the
        # golden gate measure the stub rather than the app: 8 of 12 cases cited
        # something other than the governing policy, and `policy-008`
        # (Citation grounding — a META-policy about how rationales must cite)
        # appeared as a rating *basis* in 6 of them, which is a category error
        # no judge should accept. The three cases where the citation IS the
        # substance scored 0.40–0.50 against references that name the correct
        # policy, so the scorecard was reporting a fixture artefact as an
        # application defect.
        #
        # A real analyst is instructed to cite the policy it applied, so this
        # raises the stub's fidelity rather than teaching to the test — the
        # mapping is read straight from corpus/policies.json:
        #   policy-002 source of funds · policy-003 sanctions SOP (incl aliases)
        #   policy-004 adverse media   · policy-005 risk rating rubric
        #   policy-006 human review (HITL)
        cited = ["policy-005"]  # the rubric is the basis for every rating
        if hits:
            cited.insert(0, "policy-003")  # sanctions hit — the governing SOP
        if media:
            cited.append("policy-004")
        if no_sof:
            cited.append("policy-002")
        if rating == "HIGH":
            cited.append("policy-006")  # routed to human review
        # Only cite what was actually retrieved: policy-008 treats a citation
        # outside the retrieved set as a hallucination, and the judge enforces
        # it (agents/judge.py check_citations).
        retrieved = set(re.findall(r"\[(policy-\d+)\]", prompt))
        if retrieved:
            cited = [c for c in cited if c in retrieved] or sorted(retrieved)[:1]
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
