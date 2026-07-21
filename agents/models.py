"""agents/models.py — Pydantic contracts shared by the agents (RFC-002)."""

from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field, field_validator


class ApplicantProfile(BaseModel):
    """Intake output — validated by runtime/structured_output.parse_llm_json.
    A validation failure here is the F1/F2 trigger upstream, by design."""

    applicant_id: str
    full_name: str
    dob: str = Field(description="ISO date YYYY-MM-DD")
    nationality: str
    company_name: str
    role: str
    source_of_funds: Optional[str] = None
    notes: str = ""

    @field_validator("dob")
    @classmethod
    def _iso_date(cls, v: str) -> str:
        from datetime import date

        date.fromisoformat(v)  # raises ValueError on malformed input (F1)
        return v


class ResearchFindings(BaseModel):
    sanctions_hits: list[dict] = []
    registry_record: Optional[dict] = None
    adverse_media: list[str] = []
    retrieved_doc_ids: list[str] = []
    retrieved_snippets: list[str] = []
    # One-line factual screening brief produced by the Research agent's own
    # LLM call (the Groq cheap-tier route). Not a rating — the Analyst decides
    # that; this just summarises what screening turned up for the reviewer.
    screening_summary: str = ""


class RiskAssessment(BaseModel):
    rating: Literal["LOW", "MEDIUM", "HIGH"]
    rationale: str
    citations: list[str] = []


class JudgeVerdict(BaseModel):
    citation_ok: bool
    unresolved_citations: list[str] = []
    flagged: bool
    reason: str = ""
