"""
test/test_hallucination_fixture.py — this tenant's hallucination suite must be
able to fail.

BOTH ASSERTIONS USED TO LIVE IN THE FRAMEWORK, reaching `../KYC_Sentinel` from
`scripts/test/test_hallucination_evals.py` and returning silently when the
directory was absent — which is every CI runner, since AgentSmith's CI does not
check this repo out. They were assertions about THIS repo's data all along, and
they had never run anywhere the result was reported.

What they guard is F7: a planted ungrounded citation must be detectable, and the
context a judge sees must come from what was RETRIEVED rather than what the
agent CITED.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
FIXTURE = REPO / ".agent-rfc" / "fixtures" / "hallucination_evals.json"
CORPUS = REPO / "corpus" / "policies.json"


def _cases() -> list[dict]:
    assert FIXTURE.exists(), f"{FIXTURE} is missing — the suite has no cases"
    cases = json.loads(FIXTURE.read_text(encoding="utf-8"))
    assert cases, "the hallucination fixture is empty"
    return cases


def test_every_retrieved_context_id_exists_in_the_corpus() -> None:
    """Context is resolved from what was RETRIEVED, never from what the agent
    CITED. Resolving the agent's citations would hand a ghost citation its own
    evidence and quietly disarm the control."""
    assert CORPUS.exists(), f"{CORPUS} is missing"
    corpus_ids = {p["id"] for p in json.loads(CORPUS.read_text(encoding="utf-8"))}
    for case in _cases():
        for doc in case.get("retrieved_context") or []:
            assert doc["id"] in corpus_ids, (
                f"{case['id']}: retrieved_context names {doc['id']!r}, which is "
                f"not in the corpus — the fixture invents its own evidence"
            )


def test_the_suite_has_a_positive_control() -> None:
    """It shipped for weeks measuring only false positives. A suite that cannot
    fail reports clean for the same reason a broken one does."""
    planted = [c for c in _cases() if c.get("expect_hallucination")]
    assert planted, "no case is marked expect_hallucination — nothing to detect"
    for c in planted:
        ctx_ids = {d["id"] for d in c.get("retrieved_context") or []}
        cited = set(re.findall(r"policy-\d+", c["actual_output"]))
        assert cited - ctx_ids, (
            f"{c['id']}: every cited policy is in retrieved_context, so there is "
            f"nothing ungrounded to detect — the control cannot fail"
        )


def test_the_fixture_is_present_and_not_a_stub() -> None:
    """The control on the two above: they read a real file, not an empty list."""
    assert len(_cases()) >= 3, "the hallucination suite has almost no cases"
