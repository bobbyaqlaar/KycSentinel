"""test/test_hitl_path_is_reachable.py — policy-006 needs a way to say yes.

`workflows/kyc_workflow.py` gates the DECISION on `run_with_hitl_gate`, so
`approve_activity` runs only after a recorded human decision. Nothing in this
repo could record one: the README pointed at the Ops Portal, which has no HITL
surface at all (it does DLQ replay and discard), and no signal sender shipped
here. A HIGH-rating application therefore had exactly one reachable outcome —
wait out the 24h timeout and dead-letter. A mandatory-review control whose only
path is the timeout is a mandatory timeout.

These are source-level checks rather than a live Temporal run, which is what
CI can afford. They assert the two things that were false.
"""

from __future__ import annotations

import ast
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent


def test_a_sender_ships_and_signals_the_gate() -> None:
    script = REPO / "resolve_hitl.py"
    assert script.is_file(), "no way to approve a parked application ships in this repo"

    source = script.read_text(encoding="utf-8")
    ast.parse(source)  # it must at least be runnable Python

    signals = [
        node.args[0].value
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "signal"
        and node.args
        and isinstance(node.args[0], ast.Constant)
    ]
    assert signals, "resolve_hitl.py sends no signal at all"
    # The UNADDRESSED form. `hitl_approved_for(gate_id, approved)` exists on
    # AgentSmith main and not in the v1.2.0 this repo pins, and Temporal drops a
    # signal with no registered handler with nothing but a warning — so the
    # addressed form would look like it worked and do nothing.
    assert "hitl_approved" in signals, f"expected the hitl_approved signal, got {signals}"


def test_the_readme_does_not_claim_the_portal_approves() -> None:
    """It did. The portal's HITL surface is DLQ replay/discard — an operator
    following that instruction would wait for a button that is not there."""
    readme = (REPO / "README.md").read_text(encoding="utf-8")
    running_live = readme.split("## Running live", 1)[-1].split("## ", 1)[0]
    assert "resolve_hitl.py" in running_live, "the live instructions name no way to approve"
    lowered = running_live.lower()
    approve_via_portal = "approve via the ops portal" in lowered
    assert not approve_via_portal, "the README points approvals at a surface that does not exist"
