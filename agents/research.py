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

from . import _framework  # noqa: F401 — SIDE-EFFECT import: puts the framework on sys.path for the imports below
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
    # Pin the policies that GOVERN the evidence actually gathered, not a fixed
    # pair. This used to pin policy-005 + policy-003 unconditionally, which was
    # wrong in both directions: it surfaced the sanctions SOP for applicants
    # with no sanctions hit, and never surfaced the adverse-media policy for
    # applicants who HAD adverse media.
    #
    # That second half made a correct citation impossible rather than merely
    # unlikely: policy-008 treats a citation outside the retrieved set as a
    # hallucination, and agents/judge.py enforces it — so the Analyst could not
    # legitimately cite policy-004 for an adverse-media rating, because
    # retrieval never put it in scope. The golden fixtures expect exactly that
    # citation (kyc_008), and the gate reported the gap as an Analyst failure.
    #
    # Surfaced by calibrating the golden threshold: fixing the fake gateway's
    # citation selection was not enough, because the retrieved set it filters
    # against did not contain the policy the rating rests on.
    governing = ["policy-005"]  # the rubric underpins every rating
    if sanctions:
        governing.append("policy-003")  # sanctions screening SOP (incl. aliases)
    # >= 2, not truthiness: policy-004 reads "TWO OR MORE credible adverse media
    # items within five years warrant at least a MEDIUM rating". Citing it on a
    # single item claims a policy whose own threshold is unmet — an ungrounded
    # citation under policy-008, and the judge scored exactly that 0.30 on
    # kyc_halluc_single_media_item. agents/judge.py already had the threshold
    # right (`media >= 2`); the citation selectors did not, so one module
    # enforced the floor while two cited it below the floor.
    #
    # The RATING is unaffected: policy-005's rubric says "MEDIUM: adverse media
    # or incomplete source of funds" with no count, so a single item still
    # warrants MEDIUM on policy-005 alone. Only the basis changes.
    if len(media) >= 2:
        governing.append("policy-004")  # adverse media (policy-004 floor: >= 2)
    if (profile.source_of_funds or "").strip().lower() in ("", "missing", "unknown"):
        governing.append("policy-002")  # source of funds
    ids = list(dict.fromkeys([h.id for h in hits] + governing))
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
