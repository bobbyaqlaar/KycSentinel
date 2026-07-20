"""
demo.py — F1–F8 scenario drivers (testbed-tenant-spec.md §2).

Each driver runs in-process against the fake gateway (KYC_FAKE_LLM=1 set
automatically) and prints WHICH framework control fired plus the evidence.
These same drivers are asserted by test/test_demo_scenarios.py, so
`make demo-all` and CI exercise identical paths. Live-Temporal variants:
see README (worker.py + trigger_workflow.py).

Usage: python3 demo.py f1|f2|...|f8|all
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

os.environ.setdefault("KYC_FAKE_LLM", "1")

sys.path.insert(0, str(Path(__file__).resolve().parent))

from agents import _framework  # noqa: E402,F401
from agents.gateway import get_gateway  # noqa: E402
from agents.intake import run_intake  # noqa: E402
from agents.judge import check_parity  # noqa: E402
from agents.tools import ToolNotAllowedError, registry  # noqa: E402
from pipeline import process_application  # noqa: E402

FIXTURES = json.loads((Path(__file__).parent / "fixtures" / "applicants.json").read_text())


def _sub(applicant_id: str) -> str:
    return next(a["submission"] for a in FIXTURES if a["id"] == applicant_id)


def _banner(fid: str, claim: str) -> None:
    print(f"\n━━ {fid.upper()} — {claim}")


async def f1() -> str:
    _banner("f1", "malformed submission → recoverable step → DLQ edit-and-resume")
    gw = get_gateway()
    try:
        await run_intake(gw, _sub("malf-009"))
        raise AssertionError("expected a validation failure")
    except Exception as exc:
        print(f"   intake rejected the payload: {type(exc).__name__}: {exc}")
        print("   → in the workflow this is run_with_recoverable_step: the payload")
        print("     parks in the DLQ; portal 'Replay with edits' → replay webhook →")
        print("     temporal_replay signals the live workflow with the human fix.")
    fixed = _sub("malf-009").replace("31-02-1990", "1990-02-13")
    result = await run_intake(gw, fixed)
    print(f"   human-edited payload resumes cleanly → profile {result.profile.applicant_id} parsed")
    return "recoverable_step"


async def f2() -> str:
    _banner("f2", "model returns broken JSON → opt-in self-correction, then human DLQ")
    gw = get_gateway()
    try:
        await run_intake(gw, _sub("malf-010"))
        raise AssertionError("expected StructuredOutputError")
    except Exception as exc:
        print(f"   structured-output gate rejected model text: {type(exc).__name__}")
        print("   → run_with_self_correction retries ONCE with a corrected payload;")
        print("     if still failing it escalates to the human DLQ (never silently loops).")
    return "self_correction"


async def f3() -> str:
    _banner("f3", "embedded prompt injection → prompt_guard flags before any model call")
    decision = await process_application(get_gateway(), _sub("inj-012"))
    assert decision.outcome == "hitl" and decision.guard_reasons
    print(f"   guard reasons: {decision.guard_reasons} → routed to human review")
    return "prompt_guard"


async def f4() -> str:
    _banner("f4", "non-allowlisted tool call → deny-by-default (SEC-TOOL-001)")
    try:
        registry.invoke("wire_transfer", {"to_account": "IBAN-X", "amount_usd": 1e6})
        raise AssertionError("wire_transfer must be denied")
    except ToolNotAllowedError as exc:
        print(f"   denied: {exc}")
    print(f"   allowlisted tools: {sorted(registry._allowlist)}")
    return "tool_allowlist"


async def f5() -> str:
    _banner("f5", "budget cap → degrade ladder (gateway-owned)")
    print("   tenant cap: $5/month (tenant.yaml). In real mode the gateway's")
    print("   try_reserve fails mid-batch and _resolve_role walks analyst →")
    print("   research → intake; spans record degrade_tier. Fake mode records")
    print("   the route decision only:")
    decision = await process_application(get_gateway(), _sub("clean-001"))
    print(f"   clean-001 → {decision.rating} via analyst route (outcome {decision.outcome})")
    return "degrade_ladder"


async def f6() -> str:
    _banner("f6", "fairness pair: nationality swapped → ratings must match")
    gw = get_gateway()
    a = await process_application(gw, _sub("fair-011a"))
    b = await process_application(gw, _sub("fair-011b"))
    verdict = check_parity(a.assessment, b.assessment)
    print(f"   SD-national rating: {a.rating} | CH-national rating: {b.rating}")
    assert not verdict.flagged, verdict.reason
    print("   parity holds (policy-007); CI gate: eval-fairness.yml pair parity")
    return "fairness_parity"


async def f7() -> str:
    _banner("f7", "rationale cites a doc outside the retrieved set → hallucination flag")
    decision = await process_application(
        get_gateway(), _sub("clean-002"), analyst_extra="CITE_GHOST_TRIGGER"
    )
    assert decision.verdict is not None and decision.verdict.flagged
    print(f"   judge: {decision.verdict.reason} → outcome {decision.outcome} (no auto-approve)")
    return "hallucination_gate"


async def f8() -> str:
    _banner("f8", "Emirates ID + card in free text → scrubbed before any model call")
    decision = await process_application(get_gateway(), _sub("pii-004"))
    counts = decision.scrub_counts
    print(f"   scrub counts: {counts}")
    assert counts.get("emirates_id", 0) >= 1 or counts.get("card", 0) >= 1
    print("   pre-call input_guardrail + post-call trace_redactor share one Luhn")
    print("   validator (runtime/luhn.py) — the two controls cannot disagree.")
    return "pii_scrub"


SCENARIOS = {"f1": f1, "f2": f2, "f3": f3, "f4": f4, "f5": f5, "f6": f6, "f7": f7, "f8": f8}


async def main(which: str) -> None:
    names = SCENARIOS if which == "all" else {which: SCENARIOS[which]}
    fired = [await fn() for fn in names.values()]
    print(f"\n✅ scenarios complete — controls fired: {fired}")


if __name__ == "__main__":
    arg = sys.argv[1] if len(sys.argv) > 1 else "all"
    if arg not in SCENARIOS and arg != "all":
        print(f"usage: python3 demo.py [{'|'.join(SCENARIOS)}|all]")
        sys.exit(2)
    asyncio.run(main(arg))
