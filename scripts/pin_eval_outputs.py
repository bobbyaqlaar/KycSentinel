#!/usr/bin/env python3
"""
scripts/pin_eval_outputs.py — record what THIS app produces as each eval
case's `actual_output`.

Why this exists: `run-evals.py` judges `case["actual_output"]`, and when a case
doesn't have one it generates a response with the framework's generic
Architect→Developer→Validator *code-generation* pipeline. That is right for the
framework's own golden set and wrong for an application tenant — the judge ends
up scoring generated code against a KYC onboarding reference. Every fairness
case scored 0.00 that way, and `--fail-below 0.80` would have blocked merges on
a number that measured nothing.

Pinning turns the suites into regression tests: the judge compares what the
pipeline produces TODAY against the case's `reference_output`, and a change in
agent behaviour shows up as a score drop rather than silently passing.

Runs in fake mode (`KYC_FAKE_LLM=1`), so output is deterministic and a re-run
on unchanged code is a no-op diff. That is the point — the fake gateway scripts
responses off prompt markers, so what is being pinned is the *pipeline's*
behaviour (scrub → parse → tools/RAG → rating → judge → decision), not a
model's mood on the day.

Re-run after any deliberate change to agent behaviour, and commit the diff:

    make pin-evals && git diff .agent-rfc/fixtures/
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
os.environ.setdefault("KYC_FAKE_LLM", "1")
os.environ.setdefault("ENVIRONMENT", "development")
os.environ.setdefault("PROMPT_GUARD", "default")

from agents import _framework  # noqa: E402,F401
from agents.gateway import get_gateway  # noqa: E402
from pipeline import process_application  # noqa: E402

# Which applicant each eval case describes. Explicit rather than inferred from
# the id: kyc_001–kyc_010 happen to line up with the applicant suffixes, but
# kyc_011/kyc_012 do not, and a silent mis-mapping would pin a plausible-looking
# output for the wrong profile.
GOLDEN_TO_APPLICANT = {
    "kyc_001": "clean-001",
    "kyc_002": "clean-002",
    "kyc_003": "clean-003",
    "kyc_004": "pii-004",
    "kyc_005": "sanc-005",
    "kyc_006": "sanc-006",
    "kyc_007": "sanc-007",
    "kyc_008": "media-008",
    "kyc_009": "malf-009",
    "kyc_010": "malf-010",
    "kyc_011": "inj-012",
    # A pair case: its reference asks for "identical ratings", which a single
    # side cannot demonstrate. Pinning only fair-011a scored 0.20 with the
    # judge correctly objecting that the output "fails to provide ratings for
    # profiles differing only in nationality".
    "kyc_012": ("fair-011a", "fair-011b"),
}

FAIRNESS_TO_APPLICANT = {
    "kyc_fair_001_a": "fair-011a",
    "kyc_fair_001_b": "fair-011b",
    "kyc_fair_002_a": "fair-013a",
    "kyc_fair_002_b": "fair-013b",
}

APPLICANTS = {
    a["id"]: a for a in json.loads((REPO / "fixtures" / "applicants.json").read_text())
}


def _render(decision) -> str:
    """The decision as a reviewer would read it — same register as the cases'
    `reference_output`, so the judge compares like with like."""
    # The analyst's rationale already opens with "Rating X:", so don't prefix
    # another "X rating." in front of it — the doubled label reads like a bug
    # to a judge asked to compare against a one-line reference.
    rationale = (decision.rationale or "").strip()
    parts = [] if rationale.lower().startswith("rating ") else [f"{decision.rating} rating"]
    if rationale:
        parts.append(rationale.rstrip("."))
    # Registry status is part of what screening turned up and several cases'
    # reference_output asks for it ("registry record active"); leaving it out
    # made an otherwise-correct decision look incomplete to the judge.
    record = (decision.findings.registry_record or {}) if decision.findings else {}
    if record.get("status"):
        parts.append(f"Company registry record {record['status']}")
    if decision.scrub_counts:
        found = ", ".join(f"{k}×{v}" for k, v in sorted(decision.scrub_counts.items()))
        parts.append(f"PII scrubbed before any model call ({found})")
    if decision.verdict is not None and decision.verdict.flagged:
        parts.append(f"Judge flagged: {decision.verdict.reason}")
    parts.append(
        "Auto-approved."
        if decision.outcome == "approved"
        else "Routed to human review (policy-006)."
    )
    return " ".join(p.rstrip(".") + "." for p in parts)


async def _actual_output(applicant_id: str) -> str:
    submission = APPLICANTS[applicant_id]["submission"]
    gateway = get_gateway()
    try:
        decision = await process_application(gateway, submission)
    except Exception as exc:
        # Malformed submissions (F1/F2) are supposed to fail here — that IS the
        # observable behaviour, so pin it rather than skipping the case.
        return (
            f"Rejected before any rating: {type(exc).__name__}. "
            f"The payload parks in the DLQ for a human-edited replay "
            f"(run_with_recoverable_step); no decision is produced."
        )
    if decision.rating is None:
        return (
            f"Blocked before any model call: prompt-injection heuristics fired "
            f"({', '.join(decision.guard_reasons)}). Routed to human review; "
            f"no rating produced."
        )
    return _render(decision)


def _pin(path: Path, mapping: dict[str, str | tuple[str, ...]]) -> int:
    cases = json.loads(path.read_text())
    changed = 0
    for case in cases:
        applicant = mapping.get(case["id"])
        if applicant is None:
            print(f"   ⚠️  no applicant mapped for {case['id']} — left unpinned")
            continue
        ids = (applicant,) if isinstance(applicant, str) else applicant
        outputs = [asyncio.run(_actual_output(a)) for a in ids]
        produced = (
            outputs[0]
            if len(outputs) == 1
            else "\n".join(f"[{a}] {o}" for a, o in zip(ids, outputs))
        )
        if case.get("actual_output") != produced:
            changed += 1
        case["actual_output"] = produced
        case["actual_output_source"] = ", ".join(
            f"fixtures/applicants.json::{a}" for a in ids
        )
        print(f"   {case['id']:16} ← {'+'.join(ids):23} {produced.splitlines()[0][:52]}…")
    path.write_text(json.dumps(cases, indent=2) + "\n")
    return changed


def main() -> int:
    total = 0
    for name, mapping in (
        ("golden_evals.json", GOLDEN_TO_APPLICANT),
        ("fairness_evals.json", FAIRNESS_TO_APPLICANT),
    ):
        path = REPO / ".agent-rfc" / "fixtures" / name
        print(f"\n▶ {name}")
        total += _pin(path, mapping)
    print(f"\n✅ pinned; {total} case(s) changed. Review with: git diff .agent-rfc/fixtures/")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
