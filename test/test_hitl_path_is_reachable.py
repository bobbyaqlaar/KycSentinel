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
    # The ADDRESSED form, since the pin moved to v1.3.0 which defines it.
    # It sent the unaddressed `hitl_approved` while the pin was v1.2.0, whose
    # BaseAgentWorkflow has no handler for the addressed one — and Temporal
    # drops a signal with no registered handler with nothing but a warning, so
    # sending it then would have looked like it worked and done nothing.
    assert "hitl_approved_for" in signals, (
        f"expected the addressed hitl_approved_for signal, got {signals}"
    )


def test_the_sender_and_the_workflow_agree_on_the_gate_id() -> None:
    """The one thing an addressed signal can get wrong.

    `hitl_approved_for` queues the approval under a gate id. If the sender names
    a gate the workflow is not waiting on, Temporal accepts the signal, the
    handler stores it, and the gate goes on waiting until it times out — a
    silence indistinguishable from nobody having approved. Read from both
    sources rather than restated here, because a constant written twice in a
    test is just a third copy of it.
    """
    sender = (REPO / "resolve_hitl.py").read_text(encoding="utf-8")
    sent = [
        node.value.value
        for node in ast.walk(ast.parse(sender))
        if isinstance(node, ast.Assign)
        and any(getattr(t, "id", None) == "GATE_ID" for t in node.targets)
        and isinstance(node.value, ast.Constant)
    ]
    assert len(sent) == 1, f"resolve_hitl.py should define one GATE_ID, found {sent}"

    workflow = (REPO / "workflows" / "kyc_workflow.py").read_text(encoding="utf-8")
    awaited = [
        kw.value.value
        for node in ast.walk(ast.parse(workflow))
        if isinstance(node, ast.Call)
        for kw in node.keywords
        if kw.arg == "gate_id" and isinstance(kw.value, ast.Constant)
    ]
    assert awaited, "kyc_workflow.py passes no gate_id to run_with_hitl_gate"
    assert sent[0] in awaited, (
        f"resolve_hitl.py signals gate {sent[0]!r} but the workflow waits on "
        f"{awaited} — the approval would be stored against a gate nobody reads"
    )


def test_the_readme_does_not_claim_the_portal_approves() -> None:
    """It did. The portal's HITL surface is DLQ replay/discard — an operator
    following that instruction would wait for a button that is not there."""
    readme = (REPO / "README.md").read_text(encoding="utf-8")
    running_live = readme.split("## Running live", 1)[-1].split("## ", 1)[0]
    assert "resolve_hitl.py" in running_live, "the live instructions name no way to approve"
    lowered = running_live.lower()
    approve_via_portal = "approve via the ops portal" in lowered
    assert not approve_via_portal, "the README points approvals at a surface that does not exist"
