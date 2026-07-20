"""test/conftest.py — offline test environment for the KYC Sentinel testbed."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

os.environ.setdefault("KYC_FAKE_LLM", "1")
os.environ.setdefault("ENVIRONMENT", "development")

from agents import _framework  # noqa: E402,F401
from agents.gateway import FakeGateway  # noqa: E402

_FIXTURES = json.loads((REPO / "fixtures" / "applicants.json").read_text())


@pytest.fixture()
def gateway() -> FakeGateway:
    return FakeGateway()


@pytest.fixture()
def applicants() -> dict[str, dict]:
    return {a["id"]: a for a in _FIXTURES}


def submission(applicant_id: str) -> str:
    return next(a["submission"] for a in _FIXTURES if a["id"] == applicant_id)
