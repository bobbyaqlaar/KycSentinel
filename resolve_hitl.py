"""
resolve_hitl.py — record the human decision on a parked KYC application.

Usage:
    python3 resolve_hitl.py <workflow-id>            # approve
    python3 resolve_hitl.py <workflow-id> --reject   # reject

WHY THIS EXISTS. policy-006 says `approve_activity` runs only after a recorded
human decision, and `workflows/kyc_workflow.py` enforces it with
`run_with_hitl_gate`. Nothing shipped in this repo could make that decision.
The README said "approve via the Ops Portal (or send the `hitl_approved`
signal)" — the portal has no HITL surface at all (it does DLQ replay and
discard, not approvals), and no sender existed here, so a HIGH-rating
application had exactly one reachable outcome: wait 24 hours and dead-letter.
A mandatory-review control whose only path is the timeout is a mandatory
timeout.

The workflow id is an argument because `trigger_workflow.py` mints
`kyc-<applicant>-<random>` per run and prints it. (The oil-price example can
hardcode its id; this cannot.)

WHICH SIGNAL. `hitl_approved(approved)` — the unaddressed form, which whichever
gate is waiting will take. AgentSmith's `main` also has
`hitl_approved_for(gate_id, approved)`, which names its gate and is what a
workflow with two gates needs; this repo pins `agentsmith-runtime@v1.2.0`,
whose BaseAgentWorkflow does not define it, and Temporal drops a signal no
handler is registered for with nothing but a warning. Switch to the addressed
form — `gate_id="kyc-decision"` — when the pin moves past a release containing
it, not before.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from agents import _framework  # noqa: E402,F401

from runtime.temporal_client import connect as connect_temporal  # noqa: E402


async def main(workflow_id: str, approve: bool) -> None:
    client = await connect_temporal()   # address + TEMPORAL_TLS + timeout, one place
    handle = client.get_workflow_handle(workflow_id)
    await handle.signal("hitl_approved", approve)
    decision = "APPROVED" if approve else "REJECTED"
    print(f"{workflow_id}: hitl_approved={approve} ({decision})")
    print("trigger_workflow.py should now complete.")


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if not args:
        print(__doc__.strip().splitlines()[2], file=sys.stderr)
        print("error: pass the workflow id printed by trigger_workflow.py", file=sys.stderr)
        raise SystemExit(2)
    asyncio.run(main(args[0], "--reject" not in sys.argv))
