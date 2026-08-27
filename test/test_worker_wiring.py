"""
test/test_worker_wiring.py — this tenant's worker installs what it must, in the
order it must.

THESE ASSERTIONS USED TO LIVE IN THE FRAMEWORK, sweeping `../KYC_Sentinel/
worker.py` from `runtime/test/`. They skipped on every CI runner: AgentSmith's
CI does not check this repo out, so the leg that covered this worker had never
run anywhere but one laptop. A tenant's wiring is the tenant's to assert.

The framework keeps the equivalent sweep over its OWN entrypoints
(`runtime/worker.py`, `examples/oil-price-agent/worker.py`), which is the half
it can actually see.
"""

from __future__ import annotations

import ast
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
WORKER = REPO / "worker.py"


def _call_lines() -> dict[str, int]:
    """First line of each bare function call in worker.py, from the AST.

    Not a text search: worker.py's comments name these functions while
    explaining the ordering, and a comment is not a call. That distinction has
    caught two tests in this project already.
    """
    calls: dict[str, int] = {}
    for node in ast.walk(ast.parse(WORKER.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            calls.setdefault(node.func.id, node.lineno)
    return calls


def test_the_worker_installs_telemetry() -> None:
    """Without it every `agent_span()` here is a no-op and no counter reaches a
    collector — the state this repo was actually in until the framework's
    `configure_telemetry()` landed."""
    assert "configure_telemetry" in _call_lines(), (
        "worker.py starts without installing a tracer or a meter"
    )


def test_the_worker_does_not_call_ahead_of_its_pin() -> None:
    """`warn_if_declared_version_differs()` is deliberately NOT called yet.

    It warns when this file's `framework.version` declaration disagrees with the
    installed package — useful, and landed in the framework after the v1.3.0 tag
    this repo pins. Calling it would ImportError on a real `docker build`, which
    is the break the pin bump fixed. Adding the call before moving the pin is
    the mistake to catch; `test_pin_satisfies_the_code.py` catches it in general
    and this names it specifically, so the two fail together and the reason is
    obvious in the output.
    """
    assert "warn_if_declared_version_differs" not in _call_lines(), (
        "worker.py calls a framework API newer than the pinned version — move "
        "the pin first"
    )


def test_env_is_loaded_before_anything_reads_it() -> None:
    """`.env` carries the OTLP endpoint and the budget cap. Configuring
    telemetry first gives a correctly installed provider with no destination —
    indistinguishable from a working one until someone looks for the traces."""
    calls = _call_lines()
    assert "load_env_file" in calls, "worker.py never loads .env"
    assert calls["load_env_file"] < calls["configure_telemetry"], (
        f"worker.py configures telemetry at line {calls['configure_telemetry']} "
        f"but loads .env at line {calls['load_env_file']}"
    )
