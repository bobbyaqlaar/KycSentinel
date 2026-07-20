"""
agents/research.py — Research Agent: RAG over the policy corpus + strict
allowlisted tools. Cheap-tier route (model_hint="research") in real mode;
in fake mode the retrieval and tools are already deterministic, so no LLM
call is needed at all — the findings ARE the output.

Prompt-guard note (F3): the guard runs on the ORIGINAL submission text in
the workflow before research; this module only ever sees structured
profile fields.
"""

from __future__ import annotations

import json

from . import _framework
from ._framework import REPO_ROOT
from .models import ApplicantProfile, ResearchFindings
from .tools import registry

try:
    from runtime.vector_store import MemoryVectorStore
except ImportError:
    from vector_store import MemoryVectorStore  # type: ignore

_STORE: MemoryVectorStore | None = None


def policy_store() -> MemoryVectorStore:
    """Corpus loaded once per process (hash embedder — deterministic)."""
    global _STORE
    if _STORE is None:
        store = MemoryVectorStore()
        docs = json.loads((REPO_ROOT / "corpus" / "policies.json").read_text())
        store.add(
            ids=[d["id"] for d in docs],
            texts=[f'{d["title"]}. {d["text"]}' for d in docs],
            metadatas=[{"title": d["title"]} for d in docs],
        )
        _STORE = store
    return _STORE


async def run_research(gateway, profile: ApplicantProfile, k: int = 4) -> ResearchFindings:
    del gateway  # reserved for the real-mode summarization call (cheap tier)
    sanctions = []
    for name in (profile.full_name, profile.company_name):
        sanctions.extend(registry.invoke("sanctions_lookup", {"name": name}))
    record = registry.invoke("company_registry_lookup", {"company": profile.company_name})
    media = registry.invoke("adverse_media_search", {"name": profile.full_name})
    media += registry.invoke("adverse_media_search", {"name": profile.company_name})

    query = (
        f"risk rating rubric sanctions screening source of funds "
        f"{profile.role} {profile.company_name}"
    )
    hits = policy_store().query(query, k=k)
    # policy-005 (rubric) and policy-003 (sanctions SOP) are always relevant
    # to a rating decision — pin them into the retrieved set.
    ids = list(dict.fromkeys([h.id for h in hits] + ["policy-005", "policy-003"]))
    snippets = [h.text for h in hits]

    return ResearchFindings(
        sanctions_hits=sanctions,
        registry_record=record,
        adverse_media=sorted(set(media)),
        retrieved_doc_ids=ids,
        retrieved_snippets=snippets,
    )
