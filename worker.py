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


def _otlp_exporter():
    """OTLP exporter when an endpoint is configured, else None (spans stay local).

    None is not a failure: a developer running the worker without Phoenix still
    gets the provider, the Resource and the identity processor — so a span that
    is never exported is still correctly attributed, and turning the endpoint on
    later changes nothing but the destination.
    """
    endpoint = os.environ.get("AGENT_PHOENIX_ENDPOINT", "").strip()
    if not endpoint:
        return None
    try:
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import (
            OTLPSpanExporter,
        )
    except ImportError:
        return None
    return OTLPSpanExporter(endpoint=f"{endpoint.rstrip('/')}/v1/traces")


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

    # Install tracing BEFORE the worker starts. Until now this tenant — the one
    # built to exercise every layer of the framework — installed no
    # TracerProvider at all, so every `agent_span()` in it was a no-op and no
    # span ever reached Phoenix. The documented three-step recipe produced zero
    # correct setups here; configure_tracing() is one call that cannot be
    # half-done. It carries the Resource (service/project/environment/owner) and
    # the processor that stamps tenant.id and agent.role onto every span.
    from runtime.tracing import configure_tracing

    configure_tracing(exporter=_otlp_exporter())

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
