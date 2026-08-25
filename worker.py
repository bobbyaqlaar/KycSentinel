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

from runtime.temporal_client import connect as connect_temporal  # noqa: E402
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


from runtime.config import load_env_file, resolve  # noqa: E402



async def main() -> None:
    address = os.environ.get("TEMPORAL_ADDRESS", "localhost:7233")
    # `workflow.task_queue: kyc-sentinel` has been declared in tenant.yaml since
    # the scaffold and was read by nothing — this line carried a second copy of
    # it as a default. Env still overrides, for running two workers off one
    # checkout.
    task_queue = resolve("workflow.task_queue", env_var="TASK_QUEUE", default="default")
    # .env first, before anything reads configuration. The runtime loads no
    # config file of its own, so a worker started outside a shell that had
    # already exported everything ran silently on defaults — including a $150
    # budget cap where tenant.yaml declares $5.
    load_env_file()

    # Install telemetry BEFORE the worker starts. Until this, the tenant built
    # to exercise every layer of the framework installed no TracerProvider at
    # all, so every `agent_span()` in it was a no-op and no span ever reached
    # Phoenix. The documented three-step recipe produced zero correct setups
    # here; one call cannot be half-done. It carries the Resource
    # (service/project/environment/owner) and the processor that stamps
    # tenant.id and agent.role onto every span.
    #
    # `configure_telemetry` rather than `configure_tracing` because metrics were
    # in the same position and it took longer to notice: `configure_metrics()`
    # had no caller anywhere, so every counter in runtime/metrics.py wrote into
    # a proxy meter that was never resolved. Same failure, one signal over.
    #
    # The OTLP endpoint is no longer resolved here. A local `_otlp_exporter()`
    # used to read AGENT_PHOENIX_ENDPOINT and append `/v1/traces` — one of four
    # copies of that logic across two languages, only one of which handled an
    # endpoint that already names the path. runtime/otlp.py is the one copy now.
    from runtime.tracing import configure_telemetry

    configure_telemetry()

    client = await connect_temporal()   # address + TEMPORAL_TLS + timeout, one place
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
