"""test/test_moderation.py — the tenant's output classifier (SEC-MOD-001).

Declared in tenant.yaml, so the framework runtime auto-registers it and the
security harness verifies it (framework G10). These tests cover the policy
it enforces; the harness only checks the contract.
"""

from __future__ import annotations

import pytest

from agents.moderation import classify_output


@pytest.mark.parametrize(
    "text",
    [
        "Rating LOW: no sanctions hits, complete source of funds. Basis: [policy-005]",
        "Rating HIGH: 1 sanctions hit against Al-Noor Trading Company [policy-003]",
        "Applicant is a Swiss national operating an agritech exporter.",  # mention != justification
    ],
)
def test_allows_clean_rationales(text):
    assert classify_output(text).allowed is True


def test_blocks_emirates_id_in_output():
    """The input guardrail scrubs prompts; this is the symmetric check that a
    model did not reconstruct PII into the rationale a reviewer will read."""
    result = classify_output("Verified against Emirates ID 784-1985-1234567-1.")
    assert result.allowed is False
    assert "pii_emirates_id_in_output" in result.reasons


def test_blocks_card_number_in_output():
    result = classify_output("Payment instrument 4111 1111 1111 1111 on file.")
    assert result.allowed is False
    assert "pii_card_in_output" in result.reasons


@pytest.mark.parametrize(
    "text",
    [
        "Rating HIGH because of the applicant's nationality.",
        "Elevated risk due to gender of the beneficial owner.",
        "MEDIUM based on the applicant's religion.",
    ],
)
def test_blocks_protected_attribute_justification(text):
    """policy-007: a rationale that justifies a rating with a protected
    attribute is a fairness breach even when the rating itself is right."""
    result = classify_output(text)
    assert result.allowed is False
    assert "protected_attribute_justification" in result.reasons


def test_short_digit_strings_are_not_cards():
    assert classify_output("Reference number 12345678 filed.").allowed is True


def test_never_raises_on_odd_input():
    """A classifier that throws would take the LLM call down with it."""
    for text in ("", "   ", "🙂" * 50, "-" * 500):
        assert classify_output(text) is not None
