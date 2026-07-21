"""
worker.py — Temporal worker entrypoint (mirrors examples/oil-price-agent).

Usage:
    export TENANT_ID=kyc-sentinel TEMPORAL_ADDRESS=localhost:7233
    python3 worker.py
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

# Resolves the framework: a no-op when agentsmith-runtime is installed, or a
# sys.path bootstrap when AGENTSMITH_DIR points at a live checkout. Two more
# inserts (runtime/ and runtime/workflows/) used to be needed here because the
# runtime wasn't a package (framework G6).
from agents import _framework  # noqa: E402,F401

from temporalio.client import Client  # noqa: E402
from temporalio.worker import Worker  # noqa: E402

from runtime.workflows.base_workflow import (  # noqa: E402
    dlq_enqueue_activity,
    self_correct_payload_activity,
)
from workflows.activities import (  # noqa: E402
    analyst_activity,
    approve_activity,
    intake_activity,
    research_activity,
)
from workflows.kyc_workflow import KycApplicationWorkflow  # noqa: E402


async def main() -> None:
    address = os.environ.get("TEMPORAL_ADDRESS", "localhost:7233")
    task_queue = os.environ.get("TASK_QUEUE", "kyc-sentinel")
    client = await Client.connect(address)
    worker = Worker(
        client,
        task_queue=task_queue,
        workflows=[KycApplicationWorkflow],
        activities=[
            intake_activity,
            research_activity,
            analyst_activity,
            approve_activity,
            dlq_enqueue_activity,
            self_correct_payload_activity,
        ],
    )
    print(f"KYC Sentinel worker on {address} queue={task_queue}")
    await worker.run()


if __name__ == "__main__":
    asyncio.run(main())
