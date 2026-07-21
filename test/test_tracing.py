"""test/test_tracing.py — the pipeline emits per-step + tool-call spans
(framework G8). Proves the tenant's non-LLM work reaches a tracer, using the
framework's shipped span helpers."""

from __future__ import annotations

import asyncio

import pytest
from conftest import submission

from agents.gateway import get_gateway
from pipeline import process_application

pytest.importorskip("opentelemetry.sdk")


@pytest.fixture(scope="module")
def exporter():
    from opentelemetry import trace
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import SimpleSpanProcessor
    from opentelemetry.sdk.trace.export.in_memory_span_exporter import (
        InMemorySpanExporter,
    )

    exp = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exp))
    trace.set_tracer_provider(provider)
    if trace.get_tracer_provider() is not provider:
        pytest.skip("a different global TracerProvider is already installed")
    return exp


def test_pipeline_emits_step_and_tool_spans(exporter):
    exporter.clear()
    asyncio.run(process_application(get_gateway(), submission("sanc-005")))

    finished = exporter.get_finished_spans()
    by_name = {s.name: dict(s.attributes) for s in finished}
    # One span per pipeline step
    for step in ("agent.intake", "agent.research", "agent.analyst", "agent.judge"):
        assert step in by_name, f"missing {step}"

    assert by_name["agent.intake"]["agent.step"] == "intake"
    assert by_name["agent.intake"]["tenant.id"] == "kyc-sentinel"
    assert by_name["agent.research"]["agent.sanctions_hits"] >= 1
    assert by_name["agent.judge"]["agent.judge_flagged"] in (True, False)

    # Each research tool call is its own child span (ToolRegistry.invoke) —
    # sanctions_lookup among them for a sanctions applicant.
    tool_spans = {s.name for s in finished if s.name.startswith("agent.tool.")}
    assert "agent.tool.sanctions_lookup" in tool_spans
