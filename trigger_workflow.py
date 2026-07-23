"""
trigger_workflow.py — submit one fixture applicant to the live workflow.

Usage: python3 trigger_workflow.py <applicant-id>   (e.g. sanc-005)
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

# Resolves the framework the same way worker.py does: a no-op when
# agentsmith-runtime is installed, or a sys.path bootstrap when
# AGENTSMITH_DIR points at a live checkout. Without this import,
# `workflows.kyc_workflow`'s own `from runtime...` import fails whenever
# the runtime isn't pip-installed — this script has no worker.py-equivalent
# entrypoint to inherit the bootstrap from, so it needs its own.
from agents import _framework  # noqa: E402,F401

from temporalio.client import Client  # noqa: E402

from workflows.kyc_workflow import KycApplicationWorkflow, KycWorkflowInput  # noqa: E402


async def main(applicant_id: str) -> None:
    fixtures = json.loads((Path(__file__).parent / "fixtures" / "applicants.json").read_text())
    submission = next(a["submission"] for a in fixtures if a["id"] == applicant_id)
    client = await Client.connect(os.environ.get("TEMPORAL_ADDRESS", "localhost:7233"))
    handle = await client.start_workflow(
        KycApplicationWorkflow.run,
        KycWorkflowInput(tenant_id="kyc-sentinel", submission=submission),
        id=f"kyc-{applicant_id}-{uuid.uuid4().hex[:8]}",
        task_queue=os.environ.get("TASK_QUEUE", "kyc-sentinel"),
    )
    print(f"started {handle.id}; result: {await handle.result()}")


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1] if len(sys.argv) > 1 else "clean-001"))
