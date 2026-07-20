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
sys.path.insert(0, str(Path(__file__).resolve().parent / "workflows"))

from agents._framework import FRAMEWORK_DIR  # noqa: E402

sys.path.insert(0, str(FRAMEWORK_DIR / "runtime"))
sys.path.insert(0, str(FRAMEWORK_DIR / "runtime" / "workflows"))

from temporalio.client import Client  # noqa: E402
from temporalio.worker import Worker  # noqa: E402

from base_workflow import dlq_enqueue_activity, self_correct_payload_activity  # noqa: E402
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
