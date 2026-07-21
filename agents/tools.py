"""
agents/tools.py — fixture-backed research tools on a tenant-owned STRICT
ToolRegistry (SEC-TOOL-001).

wire_transfer is registered but absent from
.agent-rfc/security/tool_allowlist.yaml — F4 proves deny-by-default against
a real registered tool. The sanctions matcher is deliberately naive
substring/alias matching: the testbed's promotion-loop story depends on the
golden dataset catching an alias miss, not on a clever matcher (DEVLOG T2).
"""

from __future__ import annotations

import json
from pathlib import Path

from . import _framework
from ._framework import REPO_ROOT

from runtime.tool_registry import ToolRegistry, ToolNotAllowedError  # noqa: F401

_CORPUS = REPO_ROOT / "corpus"

registry = ToolRegistry(
    allowlist_path=REPO_ROOT / ".agent-rfc" / "security" / "tool_allowlist.yaml",
    strict=True,
)


def _load(name: str) -> list[dict]:
    return json.loads((_CORPUS / name).read_text(encoding="utf-8"))


def _sanctions_lookup(name: str) -> list[dict]:
    """Match a person/company name against the sanctions fixture incl. aliases."""
    needle = name.strip().lower()
    hits = []
    for row in _load("sanctions.json"):
        names = [row["entity"], *row.get("aliases", [])]
        if any(needle == n.lower() or needle in n.lower() or n.lower() in needle for n in names):
            hits.append({"entity": row["entity"], "program": row["program"], "matched": name})
    return hits


def _company_registry_lookup(company: str) -> dict:
    """Synthetic registry: returns an active record for any plausible name."""
    return {"company": company, "status": "active", "jurisdiction": "synthetic", "registered": True}


def _adverse_media_search(name: str) -> list[str]:
    needle = name.strip().lower()
    out: list[str] = []
    for row in _load("adverse_media.json"):
        if row["name"].lower() in needle or needle in row["name"].lower():
            out.extend(row["headlines"])
    return out


def _wire_transfer(to_account: str, amount_usd: float) -> str:
    """High-impact action that must NEVER be reachable from research —
    exists purely so F4 can demonstrate allowlist denial."""
    raise AssertionError("wire_transfer executed — allowlist failed")  # pragma: no cover


registry.register(_sanctions_lookup, name="sanctions_lookup", description="Sanctions/alias screening")
registry.register(_company_registry_lookup, name="company_registry_lookup", description="Company registry record")
registry.register(_adverse_media_search, name="adverse_media_search", description="Adverse media headlines")
registry.register(_wire_transfer, name="wire_transfer", description="NOT allowlisted (F4)")
