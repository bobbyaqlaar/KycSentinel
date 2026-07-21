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

from runtime.vector_store import MemoryVectorStore

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


SCREENING_PROMPT = """You are the KYC research screener. Summarise the screening
evidence below in ONE factual sentence for a human reviewer. Do NOT assign a
risk rating — only state what was found. Be concise.

sanctions_hits: {sanctions}
adverse_media_count: {media_count}
source_of_funds: {sof}
company_registry_status: {registry_status}
"""


async def run_research(gateway, profile: ApplicantProfile, k: int = 4) -> ResearchFindings:
    sanctions = []
    for name in (profile.full_name, profile.company_name):
        sanctions.extend(registry.invoke("sanctions_lookup", {"name": name}))
    record = registry.invoke("company_registry_lookup", {"company": profile.company_name})
    media = registry.invoke("adverse_media_search", {"name": profile.full_name})
    media += registry.invoke("adverse_media_search", {"name": profile.company_name})
    media = sorted(set(media))

    query = (
        f"risk rating rubric sanctions screening source of funds "
        f"{profile.role} {profile.company_name}"
    )
    hits = policy_store().query(query, k=k)
    # policy-005 (rubric) and policy-003 (sanctions SOP) are always relevant
    # to a rating decision — pin them into the retrieved set.
    ids = list(dict.fromkeys([h.id for h in hits] + ["policy-005", "policy-003"]))
    snippets = [h.text for h in hits]

    # The Research agent's OWN LLM call — the Groq cheap-tier route
    # (model_hint="research"). This is what makes the fourth model route a
    # real part of the pipeline rather than only a degrade target (E2). A
    # summarization failure must not fail the application, so degrade to a
    # deterministic brief: the tool findings, not the prose, drive the rating.
    summary = ""
    try:
        result = await gateway.complete(
            SCREENING_PROMPT.format(
                sanctions=[h.get("entity") for h in sanctions] or "none",
                media_count=len(media),
                sof=profile.source_of_funds or "missing",
                registry_status=(record or {}).get("status", "unknown"),
            ),
            model_hint="research",
            max_tokens=128,
            temperature=0.0,
        )
        summary = result.text.strip()
    except Exception:  # fail-open: screening brief is informational, not the decision
        summary = (
            f"{len(sanctions)} sanctions hit(s), {len(media)} adverse media item(s); "
            f"source of funds {'declared' if profile.source_of_funds else 'missing'}."
        )

    return ResearchFindings(
        sanctions_hits=sanctions,
        registry_record=record,
        adverse_media=media,
        retrieved_doc_ids=ids,
        retrieved_snippets=snippets,
        screening_summary=summary,
    )
