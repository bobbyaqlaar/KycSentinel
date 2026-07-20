"""
agents/_framework.py — locate the AgentSmith framework runtime.

Same pattern as the framework's examples/oil-price-agent/worker.py:
prefer $AGENTSMITH_DIR (set by install-ai-stack.sh in ~/.zshrc), fall back
to a sibling checkout (Apps/AgenticFramework next to Apps/KYC_Sentinel).
Import this module before any `runtime.*` / flat runtime import.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path


def _find_framework() -> Path:
    env = os.environ.get("AGENTSMITH_DIR", "").strip()
    if env and (Path(env) / "runtime").is_dir():
        return Path(env)
    sibling = Path(__file__).resolve().parents[2] / "AgenticFramework"
    if (sibling / "runtime").is_dir():
        return sibling
    raise RuntimeError(
        "AgentSmith framework not found. Set AGENTSMITH_DIR to your "
        "AgenticFramework checkout (see README)."
    )


FRAMEWORK_DIR = _find_framework()

for p in (str(FRAMEWORK_DIR), str(FRAMEWORK_DIR / "runtime")):
    if p not in sys.path:
        sys.path.insert(0, p)

REPO_ROOT = Path(__file__).resolve().parents[1]
