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

try:
    from runtime.moderation import ModerationResult
except ImportError:  # pragma: no cover — flat runtime layout
    from moderation import ModerationResult  # type: ignore

# Emirates ID and card numbers must never appear in a rationale. The input
# guardrail scrubs them from prompts; this is the symmetric output check.
_EMIRATES_ID = re.compile(r"\b784-?\d{4}-?\d{7}-?\d\b")
_CARD = re.compile(r"(?:\d[ -]?){13,19}")

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

    if _EMIRATES_ID.search(text):
        reasons.append("pii_emirates_id_in_output")

    for candidate in _CARD.findall(text):
        digits = re.sub(r"\D", "", candidate)
        if 13 <= len(digits) <= 19:
            reasons.append("pii_card_in_output")
            break

    if _PROTECTED_JUSTIFICATION.search(text):
        reasons.append("protected_attribute_justification")

    return ModerationResult(allowed=not reasons, reasons=reasons)
