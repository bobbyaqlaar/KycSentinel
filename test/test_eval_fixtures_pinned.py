"""
test/test_eval_fixtures_pinned.py — every eval case must carry an
`actual_output`, and it must still match what the pipeline produces.

Two failure modes this catches:

1. **A new case added without pinning.** `run-evals.py` silently falls back to
   the framework's generic Architect→Developer→Validator *code-generation*
   pipeline for any case with no `actual_output`, then judges that against a
   KYC reference. Every fairness case scored 0.00 that way, and the golden
   gate's `--fail-below 0.80` would block merges on a number measuring nothing.

2. **A drifted pin.** The whole point of pinning is that the eval becomes a
   regression test — so when agent behaviour changes, the fixture must be
   re-pinned deliberately (`make pin-evals`) and the diff reviewed, not left
   describing a version of the app that no longer exists.

Runs in fake mode, so the comparison is deterministic.
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))

from pin_eval_outputs import (  # noqa: E402
    FAIRNESS_TO_APPLICANT,
    GOLDEN_TO_APPLICANT,
    HALLUCINATION_TO_APPLICANT,
    _actual_output,
    _rationale_only,
)

# suite → (applicant mapping, projection of the Decision it pins).
#
# The projection matters as much as the mapping. Golden and fairness pin the
# full reviewer-facing render; hallucination pins the rationale alone, because
# that suite asks whether every claim is grounded in the retrieved set its case
# declares. Pinning the full render there cited policy-001 and policy-006,
# which those cases never retrieved, and drove the hallucination rate from
# 0.000 to 1.000 against a codebase that had not regressed. A guard that
# assumed one projection could not have caught that — it would have agreed
# with the wrong pins.
_SUITES = {
    "golden_evals.json": (GOLDEN_TO_APPLICANT, None),
    "fairness_evals.json": (FAIRNESS_TO_APPLICANT, None),
    "hallucination_evals.json": (HALLUCINATION_TO_APPLICANT, _rationale_only),
}


def _cases(name: str) -> list[dict]:
    return json.loads((REPO / ".agent-rfc" / "fixtures" / name).read_text())


@pytest.mark.parametrize("suite", sorted(_SUITES))
def test_every_case_is_pinned(suite: str) -> None:
    unpinned = [c["id"] for c in _cases(suite) if not c.get("actual_output")]
    assert not unpinned, (
        f"{suite}: {unpinned} have no actual_output, so run-evals.py would judge "
        f"the framework's generic pipeline instead of this app. Run: make pin-evals"
    )


@pytest.mark.parametrize("suite", sorted(_SUITES))
def test_every_case_is_mapped_to_an_applicant(suite: str) -> None:
    mapping, _ = _SUITES[suite]
    unmapped = [c["id"] for c in _cases(suite) if c["id"] not in mapping]
    assert not unmapped, (
        f"{suite}: {unmapped} have no applicant mapping in "
        f"scripts/pin_eval_outputs.py, so `make pin-evals` skips them"
    )


@pytest.mark.parametrize("suite", sorted(_SUITES))
def test_pins_match_what_the_pipeline_produces_today(suite: str) -> None:
    """Fails when agent behaviour changed but the fixtures weren't re-pinned —
    the eval would otherwise keep grading against a stale baseline and pass."""
    mapping, render = _SUITES[suite]
    stale = []
    for case in _cases(suite):
        applicant = mapping.get(case["id"])
        if applicant is None:
            continue
        ids = (applicant,) if isinstance(applicant, str) else applicant
        outputs = [asyncio.run(_actual_output(a, render)) for a in ids]
        expected = (
            outputs[0]
            if len(outputs) == 1
            else "\n".join(f"[{a}] {o}" for a, o in zip(ids, outputs))
        )
        if case.get("actual_output") != expected:
            stale.append(case["id"])
    assert not stale, (
        f"{suite}: {stale} no longer match the pipeline's output. If the change "
        f"was deliberate, run `make pin-evals` and commit the diff."
    )
