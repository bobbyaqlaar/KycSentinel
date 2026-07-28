"""
agents/moderation.py — KYC Sentinel's output moderation classifier
(SEC-MOD-001).

Declared in `.agenticframework/tenant.yaml` as
`moderation.hook: "agents.moderation:classify_output"`, so the framework
runtime auto-registers it AND the security harness can import and verify it
(framework G10 — before that, `MODERATION_HOOK=required` could never pass
CI because an imperative registration is invisible to the harness process).

What this classifier is for: the risk rationale is a document a human
reviewer acts on, so it must not leak PII that the pre-call guard scrubbed
from the *input* but a model could reconstruct into the *output*, and it
must not emit a protected-attribute justification (policy-007) — a
rationale citing nationality is a fairness breach even when the rating is
correct.

Deliberately conservative and rule-based: a heuristic classifier that a
reviewer can read beats an opaque one here, and the framework only requires
that the hook return a ModerationResult. A production deployment would
layer a real toxicity/PII model behind the same interface.
"""

from __future__ import annotations

import re

from . import _framework  # noqa: F401 — sys.path side effect

from runtime.input_guardrail import detect_pii
from runtime.moderation import ModerationResult

# Emirates ID and card numbers must never appear in a rationale. The input
# guardrail scrubs them from prompts; this is the symmetric output check — and
# it now asks the guardrail itself (detect_pii) rather than re-deriving the
# patterns. The hand-rolled versions that used to live here had drifted
# already: the card regex `(?:\d[ -]?){13,19}` carried no Luhn check, so a
# rationale mentioning an 18-digit registry filing reference was flagged as a
# leaked card and blocked, while the pre-call guard had deliberately left the
# same digits alone. Symmetric controls that disagree about what PII *is* are
# worse than one control (framework ReviewFindings-2026-07-18 B1).
_REPORTED_PII_TYPES = ("emirates_id", "card")

# policy-007: protected attributes must not appear as rating justification.
# Matched only in a *justifying* construction ("because ... nationality"),
# not as an incidental profile field, to avoid flagging every rationale that
# happens to mention a country.
_PROTECTED_JUSTIFICATION = re.compile(
    r"\b(because|due to|owing to|given|based on)\b[^.]{0,60}\b"
    r"(nationality|national origin|ethnicity|gender|sex|religion|race)\b",
    re.IGNORECASE,
)


def classify_output(text: str) -> ModerationResult:
    """Allow/deny an agent's output text. Never raises: a classifier that
    throws would take the whole call down, and the framework treats an
    exception here as a failed control rather than a block."""
    reasons: list[str] = []

    # detect_pii also reports email/phone; this hook deliberately reports only
    # the two identifiers a KYC rationale must never carry. Widening it is a
    # one-line change to _REPORTED_PII_TYPES, not a new pattern to maintain.
    found = detect_pii(text)
    for kind in _REPORTED_PII_TYPES:
        if found.get(kind):
            reasons.append(f"pii_{kind}_in_output")

    if _PROTECTED_JUSTIFICATION.search(text):
        reasons.append("protected_attribute_justification")

    return ModerationResult(allowed=not reasons, reasons=reasons)
