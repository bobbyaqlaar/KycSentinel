"""
agents/_framework.py — make the AgentSmith runtime importable.

Preferred setup is to install it (framework G6 added packaging):

    pip install -e ../AgenticFramework
    # or: pip install "agentsmith-runtime @ git+https://github.com/bobbyaqlaar/AgentSmith@v1.0.0"

when `import runtime` just works and this module does nothing at all.

The `AGENTSMITH_DIR` / sibling-checkout fallback below stays for the
develop-against-a-live-checkout workflow, where you want edits in the
framework tree to take effect without reinstalling. It is a convenience,
no longer a requirement — before G6 every tenant needed a bootstrap like
this before it could import anything.
"""

from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


def _framework_dir() -> Path | None:
    """Locate a framework checkout, or None when the package is installed."""
    env = os.environ.get("AGENTSMITH_DIR", "").strip()
    if env and (Path(env) / "runtime").is_dir():
        return Path(env)
    sibling = REPO_ROOT.parent / "AgenticFramework"
    if (sibling / "runtime").is_dir():
        return sibling
    return None


def _ensure_runtime_importable() -> Path | None:
    """Put a framework checkout on sys.path when the package isn't installed.

    An explicit AGENTSMITH_DIR wins over an installed copy — that is the
    whole point of setting it: you are pointing at a working tree on
    purpose, and silently preferring the installed version would make your
    edits appear to have no effect.
    """
    checkout = _framework_dir()
    if checkout is not None and os.environ.get("AGENTSMITH_DIR", "").strip():
        _prepend(checkout)
        return checkout

    if importlib.util.find_spec("runtime") is not None:
        return None  # installed — nothing to do

    if checkout is None:
        raise RuntimeError(
            "AgentSmith runtime not found. Either install it "
            "(pip install -e ../AgenticFramework) or set AGENTSMITH_DIR to a "
            "framework checkout. See README."
        )
    _prepend(checkout)
    return checkout


def _prepend(path: Path) -> None:
    p = str(path)
    if p not in sys.path:
        sys.path.insert(0, p)


FRAMEWORK_DIR = _ensure_runtime_importable()
